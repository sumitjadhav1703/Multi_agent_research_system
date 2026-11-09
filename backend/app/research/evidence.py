"""Passage selection, source merge, claim grounding and citation repair.

Model output never becomes `supported` unless a stored passage quote overlaps
the claim and survives the deterministic citation checks.
"""
from __future__ import annotations

import hashlib
import re
from uuid import uuid4

from backend.app.graph.limits import GraphLimits
from backend.app.observability import start_span
from backend.app.research.retrieval import canonical_url, content_hash, domain_of, is_pdf_url
from backend.app.schemas.research import (
    EVIDENCE_WORDING,
    CitationIssue,
    Claim,
    Contradiction,
    FetchResult,
    Passage,
    ReportDraft,
    ReportSection,
    SearchHit,
    SourceRecord,
    WorkerResult,
)

STOPWORDS = {
    "about", "after", "also", "and", "because", "been", "before", "being", "between",
    "from", "have", "into", "that", "their", "there", "these", "this", "those", "with",
    "were", "which", "while", "would", "your",
}


def significant_terms(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]{4,}", text.lower()) if word not in STOPWORDS}


def passage_evidence_id(subquestion_id: str, source_id: str, offset: int) -> str:
    """Stable unique id per subquestion + source + passage offset.

    Older ids were `ev_{subquestion}_{offset}` only, so six sources under one
    subquestion collided and merge kept ~two passages.
    """
    slug = hashlib.sha1(source_id.encode("utf-8")).hexdigest()[:8]
    return f"ev_{subquestion_id}_{slug}_{offset}"


def select_passages(
    subquestion: str,
    excerpt: str,
    *,
    source_id: str,
    subquestion_id: str,
    url: str,
    limits: GraphLimits,
) -> list[Passage]:
    excerpt = excerpt.strip()
    if not excerpt:
        return []
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", excerpt) if part.strip()]
    if not sentences:
        sentences = [excerpt]
    question_terms = significant_terms(subquestion)
    scored: list[tuple[int, int, str]] = []
    for index, sentence in enumerate(sentences):
        quote = sentence[: limits.max_passage_chars]
        overlap = len(question_terms & significant_terms(quote))
        scored.append((overlap, index, quote))
    scored.sort(key=lambda item: (-item[0], item[1]))
    chosen = scored[: limits.max_passages_per_source]
    passages: list[Passage] = []
    for offset, (overlap, _index, quote) in enumerate(chosen, start=1):
        if quote not in excerpt:
            quote = excerpt[: limits.max_passage_chars]
        passages.append(
            Passage(
                evidence_id=passage_evidence_id(subquestion_id, source_id, offset),
                source_id=source_id,
                subquestion_id=subquestion_id,
                quote=quote,
                url=url,
                relevance_reason=f"Term overlap with the subquestion is {overlap}.",
                term_overlap=overlap,
            )
        )
    return passages


def materialize_hits(
    *,
    subquestion_id: str,
    question: str,
    hits: list[SearchHit],
    fetch,
    fetch_budget: int,
    limits: GraphLimits,
    retrieved_at: str,
) -> tuple[list[SourceRecord], list[Passage], list[str]]:
    """Turn search hits into bounded sources. PDF URLs are not fetched or parsed."""
    sources: list[SourceRecord] = []
    passages: list[Passage] = []
    warnings: list[str] = []
    for index, hit in enumerate(hits, start=1):
        if len(sources) >= fetch_budget:
            break
        url = hit.url.strip()
        if not url:
            continue
        source_id = f"src_{subquestion_id}_{index}"
        if is_pdf_url(url):
            with start_span("source.fetch", domain=domain_of(url)) as span:
                span.set(extraction_method="unsupported_pdf", fetched=False)
            excerpt = (hit.snippet or "")[: limits.max_excerpt_chars]
            source = _source(
                source_id=source_id,
                subquestion_id=subquestion_id,
                url=url,
                title=hit.title,
                excerpt=excerpt,
                method="unsupported_pdf",
                fetched=False,
                retrieved_at=retrieved_at,
                caveats=["PDF parsing is out of scope. Snippet only."],
            )
            sources.append(source)
            passages.extend(
                select_passages(
                    question,
                    excerpt,
                    source_id=source_id,
                    subquestion_id=subquestion_id,
                    url=url,
                    limits=limits,
                )
            )
            warnings.append(f"source:{source_id}:pdf_snippet_only")
            continue
        try:
            with start_span("source.fetch", domain=domain_of(url)) as span:
                fetched = fetch(url)
                span.set(extraction_method=fetched.extraction_method, fetched=fetched.extraction_method == "html")
        except Exception:
            fetched = FetchResult(url=url, text="", extraction_method="failed", caveat="Fetch failed.")
        if fetched.extraction_method == "failed" or not fetched.text.strip():
            excerpt = (hit.snippet or "")[: limits.max_excerpt_chars]
            method = "snippet"
            fetched_flag = False
            caveat = fetched.caveat or "Fetch failed. Search snippet used and the limitation is disclosed."
            text_for_passages = excerpt
        else:
            excerpt = fetched.text[: limits.max_excerpt_chars]
            method = fetched.extraction_method
            fetched_flag = method == "html"
            caveat = fetched.caveat
            text_for_passages = excerpt
        caveats = [caveat] if caveat else []
        source = _source(
            source_id=source_id,
            subquestion_id=subquestion_id,
            url=url,
            title=hit.title,
            excerpt=excerpt,
            method=method if method in {"html", "snippet", "unsupported_pdf", "failed"} else "snippet",
            fetched=fetched_flag,
            retrieved_at=retrieved_at,
            caveats=caveats,
        )
        if not excerpt:
            warnings.append(f"source:{url}:empty")
            continue
        sources.append(source)
        passages.extend(
            select_passages(
                question,
                text_for_passages,
                source_id=source_id,
                subquestion_id=subquestion_id,
                url=url,
                limits=limits,
            )
        )
    _apply_ranks(sources, passages, question)
    return sources, passages, warnings


def _source(
    *,
    source_id: str,
    subquestion_id: str,
    url: str,
    title: str,
    excerpt: str,
    method: str,
    fetched: bool,
    retrieved_at: str,
    caveats: list[str],
) -> SourceRecord:
    canonical = canonical_url(url)
    return SourceRecord(
        source_id=source_id,
        url=url,
        canonical_url=canonical,
        domain=domain_of(canonical),
        title=title[:300] or canonical,
        excerpt=excerpt,
        content_hash=content_hash(excerpt),
        extraction_method=method,  # type: ignore[arg-type]
        fetched=fetched,
        retrieved_at=retrieved_at,
        caveats=caveats,
        subquestion_id=subquestion_id,
    )


def _apply_ranks(sources: list[SourceRecord], passages: list[Passage], question: str) -> None:
    domains = [source.domain for source in sources]
    question_terms = significant_terms(question)
    for source in sources:
        related = [passage for passage in passages if passage.source_id == source.source_id]
        overlap = max((passage.term_overlap for passage in related), default=0)
        relevance = min(1.0, overlap / max(1, min(4, len(question_terms) or 1)))
        quality = min(1.0, (len(related[0].quote) / 200) if related else 0)
        duplication_penalty = 0.2 if domains.count(source.domain) > 1 else 0.0
        primary_bonus = 0.1 if source.domain.endswith((".gov", ".edu")) else 0.0
        freshness_bonus = 0.1 if source.published_at else 0.0
        score = round(relevance + quality + primary_bonus + freshness_bonus - duplication_penalty, 4)
        source.rank_features = {
            "relevance": round(relevance, 4),
            "primary_source_bonus": primary_bonus,
            "freshness_known": bool(source.published_at),
            "domain_duplication_penalty": duplication_penalty,
            "passage_quality": round(quality, 4),
            "score": score,
        }
        source.rank_score = score
    sources.sort(key=lambda item: item.rank_score, reverse=True)


def run_worker_retrieval(
    *,
    result_id: str,
    subquestion_id: str,
    question: str,
    search_query: str,
    fetch_budget: int,
    retrieval,
    limits: GraphLimits,
    retrieved_at: str,
) -> WorkerResult:
    if fetch_budget <= 0:
        return WorkerResult(
            result_id=result_id,
            subquestion_id=subquestion_id,
            status="failed",
            search_query=search_query,
            warnings=["source budget exhausted before this worker"],
            error="source_budget",
        )
    try:
        with start_span("search.call", subquestion_id=subquestion_id) as span:
            hits = retrieval.search(search_query, max_results=min(limits.max_search_results, max(fetch_budget, 1)))
            span.set(hit_count=len(hits))
    except Exception:
        return WorkerResult(
            result_id=result_id,
            subquestion_id=subquestion_id,
            status="failed",
            search_query=search_query,
            error="search_failed",
            warnings=["search failed"],
        )
    sources, passages, warnings = materialize_hits(
        subquestion_id=subquestion_id,
        question=question,
        hits=list(hits)[: limits.max_search_results],
        fetch=retrieval.fetch,
        fetch_budget=fetch_budget,
        limits=limits,
        retrieved_at=retrieved_at,
    )
    if not hits:
        warnings.append("search returned no sources")
    status = "ok" if sources else "partial"
    if hits and not sources:
        status = "partial"
    return WorkerResult(
        result_id=result_id,
        subquestion_id=subquestion_id,
        status=status,
        search_query=search_query,
        search_calls=1,
        sources=sources,
        passages=passages,
        warnings=warnings,
    )


def merge_worker_outputs(results: list[dict]) -> tuple[list[dict], list[dict], int, list[str]]:
    """Dedupe by canonical URL and content hash. Rebuilds the ledger from worker outputs."""
    sources: list[SourceRecord] = []
    passages: list[Passage] = []
    warnings: list[str] = []
    seen_urls: dict[str, str] = {}
    seen_hashes: dict[str, str] = {}
    search_per_question: dict[str, int] = {}
    for raw in results:
        result = WorkerResult.model_validate(raw)
        search_per_question[result.subquestion_id] = max(
            search_per_question.get(result.subquestion_id, 0),
            result.search_calls,
        )
        warnings.extend(result.warnings)
        for source in result.sources:
            if source.canonical_url in seen_urls:
                warnings.append(f"duplicate source dropped:{source.canonical_url}")
                continue
            if source.content_hash and source.content_hash in seen_hashes and source.excerpt:
                warnings.append(f"duplicate content dropped:{source.canonical_url}")
                continue
            seen_urls[source.canonical_url] = source.source_id
            if source.excerpt:
                seen_hashes[source.content_hash] = source.source_id
            sources.append(source)
        for passage in result.passages:
            owner = next((source for source in sources if source.canonical_url == canonical_url(passage.url)), None)
            if owner is None or any(existing.evidence_id == passage.evidence_id for existing in passages):
                continue
            if passage.quote not in owner.excerpt and owner.excerpt not in passage.quote:
                continue
            if passage.source_id != owner.source_id:
                passage = passage.model_copy(update={"source_id": owner.source_id})
            passages.append(passage)
    ordered = sorted(sources, key=lambda item: item.rank_score, reverse=True)
    return (
        [source.model_dump() for source in ordered],
        [passage.model_dump() for passage in passages],
        sum(search_per_question.values()),
        _unique(warnings),
    )


def latest_worker_status(results: list[dict]) -> dict[str, str]:
    status: dict[str, str] = {}
    for raw in results:
        status[str(raw.get("subquestion_id"))] = str(raw.get("status") or "failed")
    return status


def _assessed(reason: str) -> str:
    text = reason.strip()
    if text.startswith("Evidence assessed."):
        return text[:500]
    return f"Evidence assessed. {text}"[:500]


def claim_grounded(claim_text: str, quote: str) -> bool:
    terms = significant_terms(claim_text)
    if not terms:
        return False
    overlap = terms & significant_terms(quote)
    needed = 1 if len(terms) == 1 else min(2, len(terms))
    return len(overlap) >= needed


def enforce_claim_assessments(claims: list[Claim], passages: list[Passage]) -> tuple[list[Claim], list[str]]:
    by_id = {passage.evidence_id: passage for passage in passages}
    repaired: list[Claim] = []
    notes: list[str] = []
    for claim in claims:
        known = [by_id[eid] for eid in claim.evidence_ids if eid in by_id]
        missing = [eid for eid in claim.evidence_ids if eid not in by_id]
        if missing:
            notes.append(f"Dropped unknown evidence ids from {claim.claim_id}: {', '.join(missing)}")
        status = claim.status
        reason = claim.verification_reason
        evidence_ids = [passage.evidence_id for passage in known]
        if is_auto_passage_claim(claim):
            # Quote-as-claim seeds always overlap their own passage; never promote them.
            if status != "insufficient":
                notes.append(f"Kept {claim.claim_id} insufficient (passage excerpt seed)")
            status = "insufficient"
            reason = (
                "Deterministic passage excerpt seed. Not a supported finding and not "
                "eligible for verification upgrade."
            )
        elif status == "supported":
            grounded = [passage for passage in known if claim_grounded(claim.text, passage.quote)]
            if not grounded:
                status = "insufficient"
                evidence_ids = [passage.evidence_id for passage in known]
                reason = (
                    "Deterministic check: supported requires a stored passage whose quote "
                    "overlaps the claim. Model opinion is not evidence."
                )
                notes.append(f"Downgraded {claim.claim_id} from supported")
            else:
                evidence_ids = [passage.evidence_id for passage in grounded]
                reason = _assessed(claim.verification_reason)
        elif status == "contradictory":
            if not known:
                status = "insufficient"
                reason = "Deterministic check: contradictory requires a stored passage."
                notes.append(f"Downgraded {claim.claim_id} from contradictory")
            else:
                reason = _assessed(claim.verification_reason)
        else:
            status = "insufficient"
        repaired.append(
            claim.model_copy(
                update={
                    "status": status,
                    "verification_reason": reason[:500],
                    "evidence_ids": evidence_ids,
                }
            )
        )
    return repaired, notes


def contradictions_for(claims: list[Claim]) -> list[Contradiction]:
    rows: list[Contradiction] = []
    for index, claim in enumerate((item for item in claims if item.status == "contradictory"), start=1):
        rows.append(
            Contradiction(
                contradiction_id=f"cx{index}",
                claim_id=claim.claim_id,
                summary=claim.verification_reason,
                evidence_ids=list(claim.evidence_ids),
            )
        )
    return rows


def link_claims_to_sources(
    claims: list[Claim],
    passages: list[Passage],
    sources: list[SourceRecord],
) -> tuple[list[Claim], list[CitationIssue]]:
    passage_by_id = {passage.evidence_id: passage for passage in passages}
    source_by_id = {source.source_id: source for source in sources}
    issues: list[CitationIssue] = []
    updated: list[Claim] = []
    for claim in claims:
        keep: list[str] = []
        for evidence_id in claim.evidence_ids:
            passage = passage_by_id.get(evidence_id)
            if passage is None:
                issues.append(CitationIssue(code="missing_evidence", detail=f"{claim.claim_id} cites {evidence_id}"))
                continue
            source = source_by_id.get(passage.source_id)
            if source is None:
                issues.append(CitationIssue(code="missing_source", detail=evidence_id))
                continue
            if canonical_url(passage.url) != source.canonical_url:
                issues.append(CitationIssue(code="url_mismatch", detail=evidence_id))
                continue
            if passage.quote not in source.excerpt and source.excerpt not in passage.quote:
                issues.append(CitationIssue(code="quote_not_in_passage", detail=evidence_id))
                continue
            if not source.fetched and source.extraction_method not in {"snippet", "unsupported_pdf"}:
                issues.append(CitationIssue(code="fetch_status_unclear", detail=source.source_id))
                continue
            keep.append(evidence_id)
        status = claim.status
        reason = claim.verification_reason
        if status == "supported" and not keep:
            status = "insufficient"
            reason = "Deterministic citation check removed the supporting passage."
            issues.append(CitationIssue(code="supported_without_evidence", detail=claim.claim_id))
        updated.append(claim.model_copy(update={"evidence_ids": keep, "status": status, "verification_reason": reason}))
    return updated, issues


_INSTRUCTION_MARKERS = ("ignore earlier instructions", "ignore all instructions", "shell tool")

# Writer meta-refusals that look like answers but carry no research content.
_REFUSAL_MARKERS = (
    "no verified claims are available",
    "no verified claim is available",
    "cannot provide a definitive",
    "can't provide a definitive",
    "unable to provide a definitive",
    "no evidence-backed claim could be assessed",
    "no evidence backed claim could be assessed",
    "no claims were assessed",
    "no verified sources were retrieved",
)


# Short negations are dropped by significant_terms (min length 4). Keep them here
# so report bodies cannot flip claim polarity ("available" vs "not available").
_NEGATION_TOKENS = frozenset(
    {
        "not",
        "no",
        "never",
        "none",
        "nor",
        "without",
        "cant",
        "isnt",
        "arent",
        "wasnt",
        "werent",
        "doesnt",
        "dont",
        "didnt",
        "wont",
        "hasnt",
        "havent",
        "hadnt",
    }
)


def _report_match_terms(text: str) -> set[str]:
    """Terms for finding-vs-claim matching, including short negation markers."""
    normalized = text.lower().replace("'", "").replace("’", "")
    terms = significant_terms(normalized)
    for token in re.findall(r"[a-z0-9]+", normalized):
        if token in _NEGATION_TOKENS:
            terms.add(token)
    return terms


def _body_matches_supported(body: str, supported_claims: list[Claim]) -> bool:
    """True when the finding text does not add terms or flip negation vs supported claims."""
    normalized = " ".join(body.split()).lower()
    if not normalized:
        return False
    claim_text = " ".join(claim.text for claim in supported_claims if claim.text.strip())
    claim_normalized = " ".join(claim_text.split()).lower()
    if not claim_normalized:
        return False
    if normalized == claim_normalized:
        return True
    body_terms = _report_match_terms(body)
    claim_terms = _report_match_terms(claim_text)
    if not body_terms:
        return False
    # Short negations must match exactly; otherwise "not available" ⊆ "available" fails
    # one way and "available" ⊆ "not available" would incorrectly pass the other way.
    if (body_terms & _NEGATION_TOKENS) != (claim_terms & _NEGATION_TOKENS):
        return False
    content_body = body_terms - _NEGATION_TOKENS
    content_claim = claim_terms - _NEGATION_TOKENS
    if not content_body:
        return False
    return content_body <= content_claim


def _usable_provisional_body(body: str) -> str | None:
    text = body.strip()
    if not text:
        return None
    lowered = text.lower()
    if any(marker in lowered for marker in _INSTRUCTION_MARKERS):
        return None
    if any(marker in lowered for marker in _REFUSAL_MARKERS):
        return None
    return text[:2000]


def unsupported_claims(claims: list[Claim]) -> list[Claim]:
    return [
        claim
        for claim in claims
        if claim.status in {"insufficient", "contradictory"} and claim.text.strip()
    ]


def synthesize_provisional_body(
    topic: str,
    claims: list[Claim],
    passages: list[Passage] | None = None,
    *,
    max_claims: int = 4,
    max_passages: int = 4,
) -> str:
    """Deterministic unverified write-up from unsupported claims, else stored passages."""
    topic_text = (topic or "this question").strip() or "this question"
    useful = unsupported_claims(claims)
    if useful:
        lead = (
            f"A definitive, evidence-backed answer to “{topic_text}” could not be formed from "
            "the stored passages. The notes below are unverified working claims from this run, "
            "not supported findings."
        )
        lines = [lead, ""]
        for claim in useful[:max_claims]:
            label = claim.status or "unverified"
            lines.append(f"- ({label}) {claim.text.strip()}")
        return "\n".join(lines)[:2000]

    usable_passages = [passage for passage in (passages or []) if passage.quote.strip()]
    if usable_passages:
        lead = (
            f"A definitive, evidence-backed answer to “{topic_text}” could not be formed "
            "(no verified claims). The excerpts below are unverified notes taken from stored "
            "passages only — not supported findings."
        )
        lines = [lead, ""]
        for passage in usable_passages[:max_passages]:
            quote = " ".join(passage.quote.split())[:420]
            lines.append(f"- [{passage.evidence_id}] {quote}")
        return "\n".join(lines)[:2000]

    return (
        f"A definitive, evidence-backed answer to “{topic_text}” could not be formed from "
        "the stored passages. No unsupported claim texts or passage excerpts were available; "
        "treat this as a coverage gap only."
    )[:2000]


def provisional_caveat_section(
    topic: str,
    claims: list[Claim],
    passages: list[Passage] | None = None,
    *,
    section_id: str = "sec_provisional",
) -> ReportSection | None:
    """Build a provisional caveat when unsupported claims or passages can ground it."""
    if claims and not unsupported_claims(claims):
        return None
    if not claims and not any(passage.quote.strip() for passage in (passages or [])):
        # Still emit a topic-correct coverage note so the Answer panel is never blank.
        body = synthesize_provisional_body(topic, claims, passages)
        return ReportSection(
            section_id=section_id,
            heading="Provisional answer (unverified)",
            body=body,
            evidence_ids=[],
            claim_ids=[],
            kind="caveat",
        )
    return ReportSection(
        section_id=section_id,
        heading="Provisional answer (unverified)",
        body=synthesize_provisional_body(topic, claims, passages),
        evidence_ids=[],
        claim_ids=[],
        kind="caveat",
    )


def is_auto_passage_claim(claim: Claim) -> bool:
    """True for deterministic passage seeds — never eligible to become supported findings."""
    return claim.claim_id.startswith("cl_auto_")


def claims_from_passages(passages: list[Passage], *, max_claims: int = 4) -> list[Claim]:
    """Deterministic insufficient claims from passage quotes when the extractor returns none.

    These seeds exist so the writer/provisional path has excerpt text. They must stay
    insufficient: the quote is copied as the claim text, so a naive verifier would
    otherwise mark them supported and skip follow-up search.
    """
    proposals: list[Claim] = []
    for passage in passages:
        quote = " ".join(passage.quote.split())
        if len(quote) < 40:
            continue
        proposals.append(
            Claim(
                claim_id=f"cl_auto_{len(proposals) + 1}",
                text=quote[:500],
                evidence_ids=[passage.evidence_id],
                status="insufficient",
                verification_reason=(
                    "Deterministic passage excerpt seed. Not a supported finding and not "
                    "eligible for verification upgrade."
                ),
            )
        )
        if len(proposals) >= max_claims:
            break
    return proposals


def _ledger_gap_body(claims: list[Claim], passages: list[Passage] | None = None) -> str:
    gaps = [claim for claim in claims if claim.status == "insufficient" and claim.text.strip()]
    conflicts = [claim for claim in claims if claim.status == "contradictory" and claim.text.strip()]
    if gaps:
        return " ".join(f"{claim.claim_id}: {claim.text}" for claim in gaps)[:2000]
    if conflicts:
        return " ".join(
            f"{claim.claim_id}: {claim.text} {claim.verification_reason}".strip() for claim in conflicts
        )[:2000]
    supported = [claim for claim in claims if claim.status == "supported" and claim.text.strip()]
    if supported:
        return (
            "Supported findings are listed above. This coverage note replaces ungrounded "
            "writer gap text and does not mean the ledger lacked verified rows."
        )
    usable = [passage for passage in (passages or []) if passage.quote.strip()]
    if usable:
        return (
            "No claim ledger rows were verified. Stored passages still exist for this run; "
            "see the provisional excerpts above."
        )
    return "No claim ledger rows were available to describe this coverage gap."


def _caveat_already_grounded(
    body: str,
    claims: list[Claim],
    passages: list[Passage],
) -> bool:
    """True when a writer caveat already carries claim text or passage excerpt ids."""
    text = body.strip()
    if not text:
        return False
    for passage in passages:
        if passage.quote.strip() and passage.evidence_id in text:
            return True
        quote = " ".join(passage.quote.split())[:48]
        if len(quote) >= 24 and quote in text:
            return True
    for claim in unsupported_claims(claims):
        snippet = claim.text.strip()[:48]
        if len(snippet) >= 24 and snippet in text:
            return True
    return False


def _gap_body_grounded(body: str, claims: list[Claim]) -> bool:
    """Writer gap text may only restate terms already present on the claim ledger."""
    if not claims:
        return False
    claim_text = " ".join(claim.text for claim in claims if claim.text.strip())
    if not claim_text.strip():
        return False
    body_terms = _report_match_terms(body)
    claim_terms = _report_match_terms(claim_text)
    if not body_terms:
        return False
    if (body_terms & _NEGATION_TOKENS) != (claim_terms & _NEGATION_TOKENS):
        # Allow extra "not/no" in gap language about missing coverage when claims lack them.
        extra_negation = (body_terms & _NEGATION_TOKENS) - (claim_terms & _NEGATION_TOKENS)
        if extra_negation - {"not", "no", "none", "without"}:
            return False
    content_body = body_terms - _NEGATION_TOKENS
    content_claim = claim_terms - _NEGATION_TOKENS
    if not content_body:
        return False
    return content_body <= content_claim


def _sanitize_writer_caveat(section: ReportSection) -> tuple[ReportSection | None, str | None]:
    body = _usable_provisional_body(section.body)
    if body is None:
        if section.body.strip() and any(marker in section.body.lower() for marker in _INSTRUCTION_MARKERS):
            return None, f"Dropped untrusted instruction text from {section.section_id}"
        if section.body.strip() and any(marker in section.body.lower() for marker in _REFUSAL_MARKERS):
            return None, f"Dropped meta-refusal provisional from {section.section_id}"
        return None, None
    sanitized = section.model_copy(
        update={"body": body, "evidence_ids": [], "claim_ids": [], "kind": "caveat"}
    )
    return sanitized, None


def _sanitize_writer_gap(
    section: ReportSection, claims: list[Claim], passages: list[Passage] | None = None
) -> tuple[ReportSection | None, str | None]:
    body = _usable_provisional_body(section.body)
    if body is None:
        if section.body.strip() and any(marker in section.body.lower() for marker in _INSTRUCTION_MARKERS):
            return None, f"Dropped untrusted instruction text from {section.section_id}"
        if section.body.strip() and any(marker in section.body.lower() for marker in _REFUSAL_MARKERS):
            return None, f"Dropped meta-refusal gap from {section.section_id}"
        return None, None
    claim_ids = [claim_id for claim_id in section.claim_ids if any(claim.claim_id == claim_id for claim in claims)]
    if _gap_body_grounded(body, claims):
        sanitized = section.model_copy(
            update={"body": body, "evidence_ids": [], "claim_ids": claim_ids, "kind": "gap"}
        )
        return sanitized, None
    # Do not retain assertive writer gap text that is not on the ledger.
    replaced = section.model_copy(
        update={
            "body": _ledger_gap_body(claims, passages),
            "evidence_ids": [],
            "claim_ids": [claim.claim_id for claim in unsupported_claims(claims)],
            "kind": "gap",
        }
    )
    return replaced, f"Replaced ungrounded writer gap with ledger coverage text: {section.section_id}"


def assemble_report(
    report: ReportDraft,
    claims: list[Claim],
    passages: list[Passage],
    *,
    topic: str | None = None,
) -> tuple[ReportDraft, list[str]]:
    known = {passage.evidence_id for passage in passages}
    supported = {claim.claim_id: claim for claim in claims if claim.status == "supported"}
    repairs: list[str] = []
    kept: list[ReportSection] = []
    kept_caveats: list[ReportSection] = []
    writer_gaps: list[ReportSection] = []
    salvaged_bodies: list[str] = []
    for section in report.sections:
        if section.kind == "caveat":
            sanitized, note = _sanitize_writer_caveat(section)
            if note:
                repairs.append(note)
            if sanitized is not None:
                kept_caveats.append(sanitized)
            continue
        if section.kind == "gap":
            sanitized, note = _sanitize_writer_gap(section, claims, passages)
            if note:
                repairs.append(note)
            if sanitized is not None:
                writer_gaps.append(sanitized)
            continue
        if section.kind != "finding":
            continue
        invented = [evidence_id for evidence_id in section.evidence_ids if evidence_id not in known]
        evidence_ids = [evidence_id for evidence_id in section.evidence_ids if evidence_id in known]
        linked = [claim_id for claim_id in section.claim_ids if claim_id in supported]
        if invented:
            repairs.append(f"Removed invented citation(s): {', '.join(invented)}")
        if not linked:
            repairs.append(f"Dropped finding without supported claim: {section.section_id}")
            salvaged = _usable_provisional_body(section.body)
            if salvaged:
                salvaged_bodies.append(salvaged)
            continue
        supported_claims = [supported[claim_id] for claim_id in linked]
        supported_text = " ".join(claim.text for claim in supported_claims).strip()
        body = section.body.strip()
        if any(marker in body.lower() for marker in _INSTRUCTION_MARKERS):
            repairs.append(f"Dropped untrusted instruction text from {section.section_id}")
            body = supported_text
        cited_unsupported = any(claim_id not in supported for claim_id in section.claim_ids)
        if supported_text and (cited_unsupported or not _body_matches_supported(body, supported_claims)):
            if body != supported_text:
                repairs.append(f"Replaced finding body with supported claim text: {section.section_id}")
                body = supported_text
        if not evidence_ids or not body:
            repairs.append(f"Dropped finding without evidence: {section.section_id}")
            salvaged = _usable_provisional_body(body or section.body)
            if salvaged:
                salvaged_bodies.append(salvaged)
            continue
        kept.append(
            section.model_copy(
                update={"body": body[:2000], "evidence_ids": evidence_ids, "claim_ids": linked, "kind": "finding"}
            )
        )
    cited = {evidence_id for section in kept for evidence_id in section.evidence_ids}
    for claim in claims:
        if claim.status == "supported" and claim.evidence_ids and not any(eid in cited for eid in claim.evidence_ids):
            kept.append(
                ReportSection(
                    section_id=f"sec_{claim.claim_id}",
                    heading="Finding",
                    body=claim.text,
                    evidence_ids=list(claim.evidence_ids),
                    claim_ids=[claim.claim_id],
                    kind="finding",
                )
            )
            repairs.append(f"Added deterministic finding for {claim.claim_id}")
    has_supported_finding = bool(kept)
    sections: list[ReportSection] = []
    answer_topic = (topic or report.title or "this question").strip()
    if has_supported_finding:
        sections.extend(kept)
        sections.extend(kept_caveats)
    elif kept_caveats:
        # Prefer passage/claim-backed synthesis over a generic writer caveat that
        # survived sanitize but still carries no excerpts (fusion empty-answer path).
        synthesized = provisional_caveat_section(answer_topic, claims, passages)
        if (
            synthesized is not None
            and any(passage.quote.strip() for passage in passages)
            and not any(_caveat_already_grounded(caveat.body, claims, passages) for caveat in kept_caveats)
        ):
            sections.append(synthesized)
            repairs.append("Replaced generic writer caveat with passage-backed provisional")
        else:
            sections.extend(kept_caveats)
    elif salvaged_bodies:
        sections.append(
            ReportSection(
                section_id="sec_provisional",
                heading="Provisional answer (unverified)",
                body=salvaged_bodies[0],
                evidence_ids=[],
                claim_ids=[],
                kind="caveat",
            )
        )
        repairs.append("Salvaged dropped finding as provisional caveat")
    elif not has_supported_finding:
        synthesized = provisional_caveat_section(answer_topic, claims, passages)
        if synthesized is not None:
            sections.append(synthesized)
            repairs.append("Synthesized provisional answer from claims or passages")
    conflicts = [claim for claim in claims if claim.status == "contradictory"]
    gaps = [claim for claim in claims if claim.status == "insufficient"]
    if conflicts:
        sections.append(
            ReportSection(
                section_id="sec_conflicts",
                heading="Conflicts",
                body=" ".join(f"{claim.claim_id}: {claim.text} {claim.verification_reason}" for claim in conflicts)[:2000],
                evidence_ids=sorted({eid for claim in conflicts for eid in claim.evidence_ids}),
                claim_ids=[claim.claim_id for claim in conflicts],
                kind="conflict",
            )
        )
    if gaps:
        sections.append(
            ReportSection(
                section_id="sec_gaps",
                heading="Insufficient evidence",
                body=" ".join(f"{claim.claim_id}: {claim.text}" for claim in gaps)[:2000],
                evidence_ids=sorted({eid for claim in gaps for eid in claim.evidence_ids}),
                claim_ids=[claim.claim_id for claim in gaps],
                kind="gap",
            )
        )
    elif writer_gaps:
        sections.extend(writer_gaps)
    if not has_supported_finding and not any(section.kind == "gap" for section in sections):
        sections.append(
            ReportSection(
                section_id="sec_gaps",
                heading="Insufficient evidence",
                body=_ledger_gap_body(claims, passages)
                if passages
                else "No evidence-backed claim could be assessed. Any provisional text is unverified.",
                kind="gap",
            )
        )
    if not sections:
        sections.append(
            ReportSection(
                section_id="sec_gaps",
                heading="Insufficient evidence",
                body="No evidence-backed claim could be assessed.",
                kind="gap",
            )
        )
    answer_title = (topic or report.title or "Research").strip()[:180] or "Research"
    return (
        report.model_copy(update={"title": answer_title, "sections": sections, "wording": EVIDENCE_WORDING}),
        repairs,
    )


def validate_citations(
    report: ReportDraft,
    claims: list[Claim],
    passages: list[Passage],
    sources: list[SourceRecord],
) -> list[CitationIssue]:
    issues: list[CitationIssue] = []
    passage_by_id = {passage.evidence_id: passage for passage in passages}
    source_by_id = {source.source_id: source for source in sources}
    seen_urls: set[str] = set()
    for source in sources:
        if source.canonical_url in seen_urls:
            issues.append(CitationIssue(code="duplicate_source", detail=source.canonical_url))
        seen_urls.add(source.canonical_url)
    claim_by_id = {claim.claim_id: claim for claim in claims}
    for claim in claims:
        valid_ids: list[str] = []
        for evidence_id in claim.evidence_ids:
            passage = passage_by_id.get(evidence_id)
            if passage is None:
                issues.append(CitationIssue(code="missing_evidence", detail=evidence_id))
                continue
            source = source_by_id.get(passage.source_id)
            if source is None:
                issues.append(CitationIssue(code="missing_source", detail=evidence_id))
                continue
            linked = True
            if canonical_url(passage.url) != source.canonical_url:
                issues.append(CitationIssue(code="url_mismatch", detail=evidence_id))
                linked = False
            if passage.quote not in source.excerpt and source.excerpt not in passage.quote:
                issues.append(CitationIssue(code="quote_not_in_passage", detail=evidence_id))
                linked = False
            if linked:
                valid_ids.append(evidence_id)
        if claim.status == "supported" and not valid_ids:
            issues.append(CitationIssue(code="supported_without_evidence", detail=claim.claim_id))
    for section in report.sections:
        if section.kind == "finding" and not section.evidence_ids:
            issues.append(CitationIssue(code="finding_without_evidence", detail=section.section_id))
        for evidence_id in section.evidence_ids:
            if evidence_id not in passage_by_id:
                issues.append(CitationIssue(code="invented_citation", detail=evidence_id))
        for claim_id in section.claim_ids:
            claim = claim_by_id.get(claim_id)
            if claim and claim.status == "supported" and not claim.evidence_ids:
                issues.append(CitationIssue(code="supported_without_evidence", detail=claim_id))
    return issues


def finalize_ledger(
    claims: list[Claim],
    passages: list[Passage],
    sources: list[SourceRecord],
    report: ReportDraft,
    *,
    topic: str | None = None,
) -> tuple[list[Claim], ReportDraft, dict]:
    claims, assessment_notes = enforce_claim_assessments(claims, passages)
    claims, link_issues = link_claims_to_sources(claims, passages, sources)
    report, repairs = assemble_report(report, claims, passages, topic=topic or report.title)
    issues = link_issues + validate_citations(report, claims, passages, sources)
    return claims, report, {
        "ok": not issues,
        "issues": [issue.model_dump() for issue in issues],
        "repairs": _unique(assessment_notes + repairs),
        "wording": EVIDENCE_WORDING,
    }


def new_result_id(subquestion_id: str) -> str:
    return f"res_{subquestion_id}_{uuid4().hex[:8]}"


def _unique(items: list[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen
