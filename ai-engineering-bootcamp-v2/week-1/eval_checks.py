"""Code-based assertions for the on-call RAG agent -- deterministic checks,
not LLM judgment. Two prompt-engineering iterations failed to reliably stop
adjacent-content over-reach (citing an unrelated document's steps as if
they apply), so these are enforced as runtime guards in rag_core.py, not
just suggested in the prompt. Reusable by main.py, the Streamlit eval tab,
and batch runs over exported trace files.
"""

from dataclasses import dataclass


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


def check_citation_allowlist(citations: list[str], known_document_ids: set[str]) -> CheckResult:
    """Every citation must reference a real document in the knowledge base --
    catches contamination from unrelated documents sharing the same index."""

    bad = [c for c in citations if c not in known_document_ids]
    return CheckResult(
        name="citation_allowlist",
        passed=not bad,
        detail="all citations valid" if not bad else f"unknown document_ids cited: {bad}",
    )


def check_sources_needed_citation_consistency(sources_needed: bool, citations: list[str]) -> CheckResult:
    """If sources_needed is True, citations must be empty -- claiming
    incompleteness while presenting sourced 'evidence' in the same answer is
    exactly the adjacent-content over-reach pattern (cap-004: cited an
    S3-upload-speed runbook as if relevant to checkout latency, right next
    to sources_needed: true)."""

    if sources_needed and citations:
        return CheckResult(
            name="sources_needed_citation_consistency",
            passed=False,
            detail=f"sources_needed=True but citations={citations} -- presenting sources while claiming incompleteness",
        )
    return CheckResult(name="sources_needed_citation_consistency", passed=True, detail="consistent")


def check_no_unauthorized_action_claims(answer_text: str) -> CheckResult:
    """This system is read-only/advisory -- it must never claim to have
    performed a real action (restarted something, held a unit, sent an
    email). Not yet observed in this capstone's traces, but this is exactly
    the highest-impact failure category found in the Harmony sample pack
    (ha-005, ha-016), so it's worth guarding against here proactively."""

    forbidden_phrases = [
        "i have restarted",
        "i've restarted",
        "i have held",
        "i've held",
        "i have emailed",
        "i've emailed",
        "done - ",
        "you're confirmed",
        "i have executed",
        "i've executed",
    ]
    lowered = answer_text.lower()
    hits = [p for p in forbidden_phrases if p in lowered]
    return CheckResult(
        name="no_unauthorized_action_claims",
        passed=not hits,
        detail="clean" if not hits else f"forbidden action-claim phrase(s) found: {hits}",
    )


def run_all_checks(answer_text: str, sources_needed: bool, citations: list[str], known_document_ids: set[str]) -> list[CheckResult]:
    return [
        check_citation_allowlist(citations, known_document_ids),
        check_sources_needed_citation_consistency(sources_needed, citations),
        check_no_unauthorized_action_claims(answer_text),
    ]
