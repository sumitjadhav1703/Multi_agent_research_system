"""Deterministic citation and grounding tests."""
from __future__ import annotations

import unittest

from backend.app.graph.limits import GraphLimits
from backend.app.research.evidence import (
    assemble_report,
    claim_grounded,
    claims_from_passages,
    enforce_claim_assessments,
    finalize_ledger,
    materialize_hits,
    merge_worker_outputs,
    passage_evidence_id,
    synthesize_provisional_body,
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

    def test_empty_claims_keep_writer_caveat_and_gap(self) -> None:
        report = ReportDraft(
            title="T",
            sections=[
                ReportSection(
                    section_id="sec_caveat",
                    heading="Provisional answer (unverified)",
                    body="Public sources did not confirm the latency figure.",
                    evidence_ids=["ev-invented"],
                    claim_ids=["cl-invented"],
                    kind="caveat",
                )
            ],
        )
        repaired, repairs = assemble_report(report, [], [])
        kinds = [section.kind for section in repaired.sections]
        self.assertIn("caveat", kinds)
        self.assertIn("gap", kinds)
        caveat = next(section for section in repaired.sections if section.kind == "caveat")
        self.assertEqual(caveat.heading, "Provisional answer (unverified)")
        self.assertEqual(caveat.body, "Public sources did not confirm the latency figure.")
        self.assertEqual(caveat.evidence_ids, [])
        self.assertEqual(caveat.claim_ids, [])
        gap = next(section for section in repaired.sections if section.kind == "gap")
        self.assertEqual(gap.heading, "Insufficient evidence")
        self.assertIn("unverified", gap.body.lower())
        self.assertFalse(any(section.kind == "finding" for section in repaired.sections))
        self.assertFalse(repairs)

    def test_insufficient_finding_is_salvaged_as_provisional_caveat(self) -> None:
        passage = _passage()
        insufficient = Claim(
            claim_id="cl_gap",
            text="The lab did not measure widget latency.",
            evidence_ids=["ev1"],
            status="insufficient",
            verification_reason="Not enough overlap.",
        )
        report = ReportDraft(
            title="T",
            sections=[
                ReportSection(
                    section_id="sec_bad",
                    heading="Finding",
                    body="Widget latency looks lower in informal notes, but that is unverified.",
                    evidence_ids=["ev1"],
                    claim_ids=["cl_gap"],
                    kind="finding",
                )
            ],
        )
        repaired, repairs = assemble_report(report, [insufficient], [passage])
        self.assertFalse(any(section.kind == "finding" for section in repaired.sections))
        caveats = [section for section in repaired.sections if section.kind == "caveat"]
        self.assertEqual(len(caveats), 1)
        self.assertEqual(caveats[0].heading, "Provisional answer (unverified)")
        self.assertEqual(caveats[0].body, "Widget latency looks lower in informal notes, but that is unverified.")
        self.assertEqual(caveats[0].evidence_ids, [])
        self.assertEqual(caveats[0].claim_ids, [])
        self.assertTrue(any(section.kind == "gap" and "cl_gap" in section.claim_ids for section in repaired.sections))
        self.assertTrue(any("sec_bad" in note for note in repairs))
        self.assertTrue(any("provisional caveat" in note.lower() for note in repairs))

    def test_supported_path_keeps_findings_with_evidence(self) -> None:
        passage = _passage()
        supported = Claim(
            claim_id="cl_ok",
            text="Widget latency fell in the lab report.",
            evidence_ids=["ev1"],
            status="supported",
            verification_reason="Quoted.",
        )
        report = ReportDraft(
            title="T",
            sections=[
                ReportSection(
                    section_id="sec_good",
                    heading="Finding",
                    body="Widget latency fell in the lab report.",
                    evidence_ids=["ev1"],
                    claim_ids=["cl_ok"],
                    kind="finding",
                ),
                ReportSection(
                    section_id="sec_caveat",
                    heading="Provisional answer (unverified)",
                    body="Treat this as a limit note, not a finding.",
                    evidence_ids=[],
                    claim_ids=[],
                    kind="caveat",
                ),
            ],
        )
        repaired, _repairs = assemble_report(report, [supported], [passage])
        findings = [section for section in repaired.sections if section.kind == "finding"]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].section_id, "sec_good")
        self.assertEqual(findings[0].evidence_ids, ["ev1"])
        self.assertEqual(findings[0].claim_ids, ["cl_ok"])
        self.assertEqual(findings[0].body, supported.text)
        caveats = [section for section in repaired.sections if section.kind == "caveat"]
        self.assertEqual(len(caveats), 1)
        self.assertEqual(caveats[0].evidence_ids, [])
        finding_index = next(index for index, section in enumerate(repaired.sections) if section.kind == "finding")
        caveat_index = next(index for index, section in enumerate(repaired.sections) if section.kind == "caveat")
        self.assertLess(finding_index, caveat_index)

    def test_caveat_without_evidence_is_not_a_citation_issue(self) -> None:
        report = ReportDraft(
            title="T",
            sections=[
                ReportSection(
                    section_id="sec_caveat",
                    heading="Provisional answer (unverified)",
                    body="Public notes did not settle the latency figure.",
                    evidence_ids=[],
                    claim_ids=[],
                    kind="caveat",
                )
            ],
        )
        issues = validate_citations(report, [], [], [])
        codes = {issue.code for issue in issues}
        self.assertNotIn("missing_evidence", codes)
        self.assertNotIn("finding_without_evidence", codes)
        self.assertNotIn("invented_citation", codes)

    def test_multi_source_passages_get_unique_evidence_ids(self) -> None:
        def _fetch(url: str) -> FetchResult:
            host = url.split("/")[2]
            return FetchResult(
                url=url,
                text=f"Widget latency fell in the lab report on {host}. Extra sentence about streaming.",
                extraction_method="html",
            )

        hits = [
            SearchHit(title=f"Src {index}", url=f"https://example{index}.com/a", snippet="Widget latency fell.")
            for index in range(1, 7)
        ]
        sources, passages, _warnings = materialize_hits(
            subquestion_id="sq1",
            question="What did the lab report say about widget latency?",
            hits=hits,
            fetch=_fetch,
            fetch_budget=6,
            limits=GraphLimits(max_passages_per_source=2),
            retrieved_at="2026-11-07T00:00:00+00:00",
        )
        self.assertEqual(len(sources), 6)
        ids = [passage.evidence_id for passage in passages]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(passages), 6)
        self.assertTrue(all(passage.evidence_id.startswith("ev_sq1_") for passage in passages))
        self.assertNotEqual(
            passage_evidence_id("sq1", "src_sq1_1", 1),
            passage_evidence_id("sq1", "src_sq1_2", 1),
        )
        merged_sources, merged_passages, _searches, _merge_warnings = merge_worker_outputs(
            [
                {
                    "result_id": "r1",
                    "subquestion_id": "sq1",
                    "status": "ok",
                    "search_query": "widget latency",
                    "search_calls": 1,
                    "sources": [source.model_dump() for source in sources],
                    "passages": [passage.model_dump() for passage in passages],
                    "warnings": [],
                }
            ]
        )
        self.assertEqual(len(merged_sources), 6)
        merged_ids = [item["evidence_id"] for item in merged_passages]
        self.assertEqual(len(merged_ids), len(set(merged_ids)))
        self.assertGreaterEqual(len(merged_passages), 6)

    def test_meta_refusal_caveat_is_replaced_with_synthesized_provisional(self) -> None:
        insufficient = Claim(
            claim_id="cl_gap",
            text="SSE resumes from an event cursor more easily than raw sockets.",
            evidence_ids=[],
            status="insufficient",
            verification_reason="Not enough overlap.",
        )
        report = ReportDraft(
            title="SSE versus WebSockets",
            sections=[
                ReportSection(
                    section_id="sec_caveat",
                    heading="Provisional answer (unverified)",
                    body="No verified claims are available to provide a definitive answer.",
                    evidence_ids=[],
                    claim_ids=[],
                    kind="caveat",
                )
            ],
        )
        repaired, repairs = assemble_report(report, [insufficient], [])
        caveats = [section for section in repaired.sections if section.kind == "caveat"]
        self.assertEqual(len(caveats), 1)
        self.assertIn("SSE resumes from an event cursor", caveats[0].body)
        self.assertNotIn("No verified claims are available", caveats[0].body)
        self.assertTrue(any("meta-refusal" in note.lower() or "synthesized" in note.lower() for note in repairs))
        self.assertTrue(any(section.kind == "gap" for section in repaired.sections))

    def test_ungrounded_writer_gap_is_replaced_with_ledger_text(self) -> None:
        report = ReportDraft(
            title="T",
            sections=[
                ReportSection(
                    section_id="sec_writer_gap",
                    heading="Coverage gap",
                    body="Public pages discussed protocols but never compared resume behavior.",
                    evidence_ids=[],
                    claim_ids=[],
                    kind="gap",
                )
            ],
        )
        repaired, repairs = assemble_report(report, [], [])
        gaps = [section for section in repaired.sections if section.kind == "gap"]
        self.assertTrue(gaps)
        self.assertTrue(any("No claim ledger rows were available" in section.body for section in gaps))
        self.assertFalse(any("resume behavior" in section.body for section in gaps))
        self.assertTrue(any("ungrounded writer gap" in note.lower() for note in repairs))
        caveats = [section for section in repaired.sections if section.kind == "caveat"]
        self.assertTrue(caveats)
        self.assertTrue(any("synthesized" in note.lower() for note in repairs))

    def test_grounded_writer_gap_is_kept_against_claim_ledger(self) -> None:
        insufficient = Claim(
            claim_id="cl_gap",
            text="Public pages discussed protocols but never compared resume behavior.",
            evidence_ids=[],
            status="insufficient",
            verification_reason="Not enough overlap.",
        )
        report = ReportDraft(
            title="T",
            sections=[
                ReportSection(
                    section_id="sec_writer_gap",
                    heading="Coverage gap",
                    body="Public pages discussed protocols but never compared resume behavior.",
                    evidence_ids=[],
                    claim_ids=["cl_gap"],
                    kind="gap",
                )
            ],
        )
        repaired, repairs = assemble_report(report, [insufficient], [])
        # Claim-derived gap section is preferred when insufficient claims exist.
        gaps = [section for section in repaired.sections if section.kind == "gap"]
        self.assertTrue(gaps)
        self.assertTrue(any("resume behavior" in section.body for section in gaps))
        self.assertFalse(any("ungrounded writer gap" in note.lower() for note in repairs))

    def test_all_supported_claims_do_not_get_unverified_provisional(self) -> None:
        from backend.app.research.evidence import provisional_caveat_section

        supported = Claim(
            claim_id="cl_ok",
            text="Widget latency fell in the lab report.",
            evidence_ids=["ev1"],
            status="supported",
            verification_reason="Quoted.",
        )
        self.assertIsNone(provisional_caveat_section("Widget latency", [supported]))
        report = ReportDraft(title="Widget latency", sections=[])
        repaired, repairs = assemble_report(report, [supported], [_passage()])
        self.assertFalse(any(section.kind == "caveat" for section in repaired.sections))
        self.assertTrue(any(section.kind == "finding" for section in repaired.sections))
        self.assertFalse(any("synthesized provisional" in note.lower() for note in repairs))

    def test_empty_claims_with_passages_surface_excerpts_under_topic(self) -> None:
        """Fusion-style run: 6 sources, 0 claims, writer titled the ledger — still show excerpts."""
        topic = "What are the main barriers to practical fusion energy?"
        passages = [
            Passage(
                evidence_id=f"ev_sq1_{index}",
                source_id=f"src_sq1_{index}",
                subquestion_id="sq1",
                quote=(
                    "Plasma confinement and material durability under neutron flux remain "
                    f"primary engineering barriers for commercial fusion plants note {index}."
                ),
                url=f"https://example{index}.com/fusion",
                relevance_reason="overlap",
                term_overlap=4,
            )
            for index in range(1, 7)
        ]
        report = ReportDraft(
            title="Verified Claim Ledger Report",
            sections=[
                ReportSection(
                    section_id="sec_caveat",
                    heading="Provisional answer (unverified)",
                    body="No verified claims are available to provide a definitive answer.",
                    evidence_ids=[],
                    claim_ids=[],
                    kind="caveat",
                )
            ],
        )
        body = synthesize_provisional_body(topic, [], passages)
        self.assertIn(topic, body)
        self.assertIn("Plasma confinement", body)
        self.assertIn("ev_sq1_1", body)

        auto = claims_from_passages(passages)
        self.assertEqual(len(auto), 4)
        self.assertTrue(all(claim.status == "insufficient" for claim in auto))
        self.assertIn("Plasma confinement", auto[0].text)

        repaired, repairs = assemble_report(report, [], passages, topic=topic)
        self.assertEqual(repaired.title, topic)
        self.assertNotEqual(repaired.title, "Verified Claim Ledger Report")
        caveats = [section for section in repaired.sections if section.kind == "caveat"]
        self.assertEqual(len(caveats), 1)
        self.assertIn("Plasma confinement", caveats[0].body)
        self.assertIn(topic, caveats[0].body)
        gaps = [section for section in repaired.sections if section.kind == "gap"]
        self.assertTrue(gaps)
        self.assertTrue(any("Stored passages still exist" in section.body for section in gaps))
        self.assertTrue(any("synthesized" in note.lower() for note in repairs))

    def test_generic_writer_caveat_is_replaced_when_passages_exist(self) -> None:
        topic = "What are the main barriers to practical fusion energy?"
        passages = [
            Passage(
                evidence_id="ev_sq1_1",
                source_id="src_sq1_1",
                subquestion_id="sq1",
                quote=(
                    "Plasma confinement and material durability under neutron flux remain "
                    "primary engineering barriers for commercial fusion plants."
                ),
                url="https://example1.com/fusion",
                relevance_reason="overlap",
                term_overlap=4,
            )
        ]
        report = ReportDraft(
            title="Verified Claim Ledger Report",
            sections=[
                ReportSection(
                    section_id="sec_caveat",
                    heading="Provisional answer (unverified)",
                    body="Public sources did not settle this question in enough detail for a definitive answer.",
                    evidence_ids=[],
                    claim_ids=[],
                    kind="caveat",
                )
            ],
        )
        repaired, repairs = assemble_report(report, [], passages, topic=topic)
        caveats = [section for section in repaired.sections if section.kind == "caveat"]
        self.assertEqual(len(caveats), 1)
        self.assertIn("Plasma confinement", caveats[0].body)
        self.assertIn(topic, caveats[0].body)
        self.assertNotIn("did not settle this question", caveats[0].body)
        self.assertTrue(any("replaced generic writer caveat" in note.lower() for note in repairs))

    def test_auto_passage_claims_cannot_become_supported(self) -> None:
        passage = Passage(
            evidence_id="ev1",
            source_id="src1",
            subquestion_id="sq1",
            quote=(
                "Plasma confinement and material durability under neutron flux remain "
                "primary engineering barriers for commercial fusion plants."
            ),
            url="https://example.com/lab",
            relevance_reason="overlap",
            term_overlap=4,
        )
        auto = claims_from_passages([passage])
        self.assertTrue(auto)
        forced = [
            claim.model_copy(update={"status": "supported", "verification_reason": "Exact quote match."})
            for claim in auto
        ]
        repaired, notes = enforce_claim_assessments(forced, [passage])
        self.assertTrue(all(claim.status == "insufficient" for claim in repaired))
        self.assertTrue(any("passage excerpt seed" in note.lower() for note in notes))
        self.assertFalse(any(claim.status == "supported" for claim in repaired))

    def test_ungrounded_gap_with_supported_claims_does_not_deny_verified_rows(self) -> None:
        supported = Claim(
            claim_id="cl_ok",
            text="Widget latency fell in the lab report.",
            evidence_ids=["ev1"],
            status="supported",
            verification_reason="Quoted.",
        )
        report = ReportDraft(
            title="Widget latency",
            sections=[
                ReportSection(
                    section_id="sec_good",
                    heading="Finding",
                    body=supported.text,
                    evidence_ids=["ev1"],
                    claim_ids=["cl_ok"],
                    kind="finding",
                ),
                ReportSection(
                    section_id="sec_gap",
                    heading="Gaps",
                    body="Totally unrelated inventiveness about resume behavior protocols.",
                    evidence_ids=[],
                    claim_ids=[],
                    kind="gap",
                ),
            ],
        )
        repaired, repairs = assemble_report(report, [supported], [_passage()], topic="Widget latency")
        gaps = [section for section in repaired.sections if section.kind == "gap"]
        self.assertTrue(gaps)
        self.assertTrue(any("Supported findings are listed above" in section.body for section in gaps))
        self.assertFalse(any("No claim ledger rows were verified" in section.body for section in gaps))
        self.assertTrue(any("ungrounded writer gap" in note.lower() for note in repairs))
        self.assertTrue(any(section.kind == "finding" for section in repaired.sections))


if __name__ == "__main__":
    unittest.main()
