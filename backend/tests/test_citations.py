"""Deterministic citation and grounding tests."""
from __future__ import annotations

import unittest

from backend.app.graph.limits import GraphLimits
from backend.app.research.evidence import (
    assemble_report,
    claim_grounded,
    enforce_claim_assessments,
    finalize_ledger,
    materialize_hits,
    merge_worker_outputs,
    validate_citations,
)
from backend.app.schemas.research import Claim, FetchResult, Passage, ReportDraft, ReportSection, SearchHit, SourceRecord


def _passage() -> Passage:
    return Passage(
        evidence_id="ev1",
        source_id="src1",
        subquestion_id="sq1",
        quote="Widget latency fell in the lab report.",
        url="https://example.com/lab",
        relevance_reason="overlap",
        term_overlap=3,
    )


def _source(**updates) -> SourceRecord:
    data = dict(
        source_id="src1",
        url="https://example.com/lab",
        canonical_url="https://example.com/lab",
        domain="example.com",
        title="Lab",
        excerpt="Widget latency fell in the lab report.",
        content_hash="abc",
        extraction_method="html",
        fetched=True,
        retrieved_at="2026-11-07T00:00:00+00:00",
        subquestion_id="sq1",
    )
    data.update(updates)
    return SourceRecord(**data)


class CitationTests(unittest.TestCase):
    def test_supported_without_overlap_is_downgraded(self) -> None:
        claim = Claim(
            claim_id="cl1",
            text="The moon is made of cheese.",
            evidence_ids=["ev1"],
            status="supported",
            verification_reason="The model felt confident.",
        )
        repaired, notes = enforce_claim_assessments([claim], [_passage()])
        self.assertEqual(repaired[0].status, "insufficient")
        self.assertTrue(notes)
        self.assertFalse(claim_grounded(claim.text, _passage().quote))

    def test_quote_mismatch_and_invented_id_do_not_stay_supported(self) -> None:
        claim = Claim(
            claim_id="cl1",
            text="Widget latency fell in the lab report.",
            evidence_ids=["ev1", "e999"],
            status="supported",
            verification_reason="Quoted.",
        )
        source = _source(excerpt="A different sentence about something else.")
        passage = _passage()
        report = ReportDraft(
            title="T",
            sections=[
                ReportSection(
                    section_id="sec1",
                    heading="Finding",
                    body="Widget latency fell in the lab report.",
                    evidence_ids=["e999"],
                    claim_ids=["cl1"],
                )
            ],
        )
        claims, repaired, meta = finalize_ledger([claim], [passage], [source], report)
        self.assertTrue(all(item.status != "supported" or item.evidence_ids for item in claims))
        self.assertNotEqual(claims[0].status, "supported")
        cited = {evidence_id for section in repaired.sections for evidence_id in section.evidence_ids}
        self.assertNotIn("e999", cited)
        self.assertTrue(meta["repairs"])
        self.assertTrue(any(section.kind == "gap" for section in repaired.sections))

    def test_validate_flags_duplicate_url_mismatch_and_missing_quote(self) -> None:
        first = _source()
        duplicate = _source(source_id="src2", url="https://www.example.com/lab")
        duplicate = duplicate.model_copy(update={"canonical_url": "https://example.com/lab"})
        passage = _passage().model_copy(update={"url": "https://evil.example/other", "quote": "not in source"})
        claim = Claim(
            claim_id="cl1",
            text="Widget latency fell in the lab report.",
            evidence_ids=["ev1", "ev-missing"],
            status="supported",
            verification_reason="n/a",
        )
        report = ReportDraft(
            title="T",
            sections=[
                ReportSection(section_id="sec1", heading="Finding", body="x", evidence_ids=["ev-missing"])
            ],
        )
        issues = validate_citations(report, [claim], [passage], [first, duplicate])
        codes = {issue.code for issue in issues}
        self.assertIn("duplicate_source", codes)
        self.assertIn("missing_evidence", codes)
        self.assertIn("url_mismatch", codes)
        self.assertIn("quote_not_in_passage", codes)
        self.assertIn("invented_citation", codes)
        self.assertIn("supported_without_evidence", codes)

    def test_finding_without_supported_claim_is_dropped(self) -> None:
        passage = _passage()
        insufficient = Claim(
            claim_id="cl_gap",
            text="The lab did not measure widget latency.",
            evidence_ids=["ev1"],
            status="insufficient",
            verification_reason="Not enough overlap.",
        )
        supported = Claim(
            claim_id="cl_ok",
            text="Widget latency fell in the lab report.",
            evidence_ids=["ev1"],
            status="supported",
            verification_reason="Quoted.",
        )
        contradictory = Claim(
            claim_id="cl_cx",
            text="Widget latency rose in the field report.",
            evidence_ids=["ev1"],
            status="contradictory",
            verification_reason="A second passage disagrees.",
        )
        report = ReportDraft(
            title="T",
            sections=[
                ReportSection(
                    section_id="sec_bad",
                    heading="Finding",
                    body="The lab did not measure widget latency.",
                    evidence_ids=["ev1"],
                    claim_ids=["cl_gap"],
                    kind="finding",
                ),
                ReportSection(
                    section_id="sec_good",
                    heading="Finding",
                    body="Widget latency fell in the lab report.",
                    evidence_ids=["ev1"],
                    claim_ids=["cl_ok"],
                    kind="finding",
                ),
                ReportSection(
                    section_id="sec_invented",
                    heading="Finding",
                    body="The moon is made of cheese.",
                    evidence_ids=["ev1"],
                    claim_ids=["cl_ok"],
                    kind="finding",
                ),
            ],
        )
        repaired, repairs = assemble_report(report, [insufficient, supported, contradictory], [passage])
        findings = [section for section in repaired.sections if section.kind == "finding"]
        finding_ids = [section.section_id for section in findings]
        self.assertNotIn("sec_bad", finding_ids)
        self.assertIn("sec_good", finding_ids)
        kept = next(section for section in findings if section.section_id == "sec_good")
        self.assertEqual(kept.claim_ids, ["cl_ok"])
        self.assertEqual(kept.body, supported.text)
        invented = next(section for section in findings if section.section_id == "sec_invented")
        self.assertEqual(invented.claim_ids, ["cl_ok"])
        self.assertEqual(invented.body, supported.text)
        self.assertNotIn("moon", invented.body.lower())
        self.assertTrue(any(section.kind == "gap" and "cl_gap" in section.claim_ids for section in repaired.sections))
        self.assertTrue(any(section.kind == "conflict" and "cl_cx" in section.claim_ids for section in repaired.sections))
        self.assertTrue(any("sec_bad" in note for note in repairs))

    def test_negated_finding_body_is_replaced_with_supported_claim(self) -> None:
        passage = _passage()
        supported = Claim(
            claim_id="cl_access",
            text="Access is available",
            evidence_ids=["ev1"],
            status="supported",
            verification_reason="Quoted.",
        )
        report = ReportDraft(
            title="T",
            sections=[
                ReportSection(
                    section_id="sec_flip",
                    heading="Finding",
                    body="Access is not available",
                    evidence_ids=["ev1"],
                    claim_ids=["cl_access"],
                    kind="finding",
                ),
                ReportSection(
                    section_id="sec_same",
                    heading="Finding",
                    body="Access is available",
                    evidence_ids=["ev1"],
                    claim_ids=["cl_access"],
                    kind="finding",
                ),
            ],
        )
        repaired, repairs = assemble_report(report, [supported], [passage])
        findings = {section.section_id: section for section in repaired.sections if section.kind == "finding"}
        self.assertEqual(findings["sec_flip"].body, supported.text)
        self.assertNotIn("not", findings["sec_flip"].body.lower().split())
        self.assertEqual(findings["sec_same"].body, supported.text)
        self.assertTrue(any("sec_flip" in note for note in repairs))

    def test_merge_drops_duplicate_urls(self) -> None:
        source = _source().model_dump()
        other = _source(source_id="src2", subquestion_id="sq2").model_dump()
        passage = _passage().model_dump()
        copied = _passage().model_copy(update={"evidence_id": "ev2", "subquestion_id": "sq2", "source_id": "src2"}).model_dump()
        sources, passages, searches, warnings = merge_worker_outputs(
            [
                {
                    "result_id": "r1",
                    "subquestion_id": "sq1",
                    "status": "ok",
                    "search_query": "q",
                    "search_calls": 1,
                    "sources": [source],
                    "passages": [passage],
                    "warnings": [],
                },
                {
                    "result_id": "r2",
                    "subquestion_id": "sq2",
                    "status": "ok",
                    "search_query": "q2",
                    "search_calls": 1,
                    "sources": [other],
                    "passages": [copied],
                    "warnings": [],
                },
            ]
        )
        self.assertEqual(len(sources), 1)
        self.assertEqual(searches, 2)
        self.assertTrue(any(warning.startswith("duplicate source") for warning in warnings))
        self.assertTrue(passages)

    def test_pdf_hit_is_not_fetched_or_parsed(self) -> None:
        def _fetch(url: str) -> FetchResult:
            raise AssertionError(f"fetched {url}")

        sources, passages, warnings = materialize_hits(
            subquestion_id="sq1",
            question="What did the lab report say about widget latency?",
            hits=[SearchHit(title="Paper", url="https://example.com/files/report.pdf", snippet="Widget latency fell in the lab report.")],
            fetch=_fetch,
            fetch_budget=1,
            limits=GraphLimits(pdf_enabled=True),
            retrieved_at="2026-11-07T00:00:00+00:00",
        )
        self.assertEqual(sources[0].extraction_method, "unsupported_pdf")
        self.assertFalse(sources[0].fetched)
        self.assertTrue(passages)
        self.assertTrue(any("pdf_snippet_only" in warning for warning in warnings))
        self.assertFalse(GraphLimits(pdf_enabled=True).clamped().pdf_enabled)


if __name__ == "__main__":
    unittest.main()
