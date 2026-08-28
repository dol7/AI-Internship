"""pytest assertions for the two most concrete failure categories in the
capstone's failure taxonomy:

  Failure A -- citation contamination: a citation references a document
  outside the real knowledge base (found live: a vague "help" query once
  cited POL-220, a leftover document from an unrelated exercise sharing
  the same Pinecone index).

  Failure B -- adjacent-content over-reach: the agent claims the
  knowledge base doesn't answer the question (sources_needed=True) while
  still presenting citations as if it does (found live: cap-004 cited an
  unrelated S3 upload-speed runbook for a checkout-latency question).

Runs against eval_dataset/oncall-capstone-traces-annotated.jsonl -- a
frozen, regenerated-clean dataset (full structured output, not truncated
agent step-log text, which is lossy and was the source of a real bug
earlier). Binary pass/fail per case, one-line reason on failure, no LLM
judging. Lives inside week-1/ (not the local-only data/Trace/ copy it was
built from) so both pytest and the deployed API/Streamlit page can read it.
"""

import json
from pathlib import Path

import pytest

from eval_checks import check_citation_allowlist, check_sources_needed_citation_consistency
from rag_core import ONCALL_DOCUMENT_IDS

TRACE_PATH = Path(__file__).resolve().parent / "eval_dataset" / "oncall-capstone-traces-annotated.jsonl"
KNOWN_IDS = set(ONCALL_DOCUMENT_IDS)


def _load_cases() -> list[dict]:
    with open(TRACE_PATH) as f:
        return [json.loads(line) for line in f]


CASES = _load_cases()
CASE_IDS = [c["trace_id"] for c in CASES]


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_citation_allowlist(case: dict) -> None:
    """Failure A: every citation must reference a real knowledge-base document."""

    result = check_citation_allowlist(case["output"]["citations"], KNOWN_IDS)
    assert result.passed, f"[{case['trace_id']}] {result.detail}"


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_sources_needed_citation_consistency(case: dict) -> None:
    """Failure B: sources_needed=True and non-empty citations can't coexist --
    that's the actual mechanism of adjacent-content over-reach."""

    output = case["output"]
    result = check_sources_needed_citation_consistency(output["sources_needed"], output["citations"])
    assert result.passed, f"[{case['trace_id']}] {result.detail}"
