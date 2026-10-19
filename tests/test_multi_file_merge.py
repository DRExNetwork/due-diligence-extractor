"""V1-2273 — several files per requirement, partial objects, AI-provider failures.

Covers the extractor side:
- list fields are never resolved by picking one file's list (additive lists stay per
  file, combined lists are merged);
- an AI-provider or parse failure never falls back to the first candidate — ranked
  rules choose (source rank → cited value → majority → most recent upload) and the
  result is flagged as a provider fallback;
- `document_status` is lifted out of the extracted data and returned beside it;
- the extractor's additive-list set covers every repeated field the projects service
  explodes into rows (contract test against the sibling repo when it is checked out).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List
from unittest.mock import patch

import pytest

from ddx.classification import extraction_api as ea
from ddx.classification.categories import DocumentType, TopLevelCategory
from ddx.classification.extraction_api import DocumentResult, validate_batch_results
from ddx.classification.landing_ai_poc_sdk import ADDITIVE_LIST_FIELDS, COMBINED_LIST_FIELDS
from ddx.classification.validation_layer import (
    AI_PROVIDER_FAILURE_MARKER,
    FALLBACK_CONFIDENCE,
    PROVIDER_FALLBACK_FLAG,
    FieldCandidate,
    FieldConflict,
    ValidationLayer,
    ValidationReport,
    ValidationResult,
)

CERT_TYPE = DocumentType.PROJECT_ACCEPTANCE_CERTIFICATES.value
EXPERIENCE = TopLevelCategory.COMPANY_EXPERIENCE

# Real values read by the AI from Natalie's files (project 17, 2026-10-15 fresh run).
WS_ACTA_CERT = {
    "client_name": "W.S. & A CIA. LTDA.",
    "certificate_date": "2022-08-11",
    "project_capacity_kw": 35.28,
    "project_title": "Instalación de sistema fotovoltaico CHAULLABAMBA - SUPERMAXI",
}
WSA_LETTER_CERT = {
    "client_name": "WS & A Cia. Ltda.",
    "certificate_date": "2023-07-06",
    "project_capacity_kw": 300,
    "project_title": "Sistemas fotovoltaicos Corporación Favorita C.A.",
}


def _cert_result(file_name: str, certificates: List[dict], company_name: str) -> DocumentResult:
    return DocumentResult(
        file_name=file_name,
        file_path=f"/tmp/{file_name}",
        document_type=CERT_TYPE,
        top_level_category=EXPERIENCE.value,
        extracted_data={"company_name": company_name, "certificates": certificates},
    )


class _RecordingValidator:
    """Stands in for ValidationLayer: records which fields reached conflict resolution."""

    instances: List["_RecordingValidator"] = []

    def __init__(self, model: str = "test") -> None:
        self.fields: List[str] = []
        _RecordingValidator.instances.append(self)

    def validate_all_conflicts(self, conflicts, top_level_category, document_type, source_files):
        self.fields.extend(c.field_name for c in conflicts)
        validations = [
            ValidationResult(
                field_name=c.field_name,
                selected_value=c.candidates[-1].value,
                selected_source=c.candidates[-1].source_file,
                selected_source_filename=c.candidates[-1].source_filename,
                confidence_score=0.9,
                justification="picked last",
            )
            for c in conflicts
        ]
        return ValidationReport(
            top_level_category=top_level_category,
            top_level_folder="x",
            document_type=document_type,
            document_type_folder="x",
            total_fields_validated=len(validations),
            total_files_processed=len(source_files),
            source_files=source_files,
            validations=validations,
            overall_confidence=0.9,
            summary="ok",
        )


# ---------------------------------------------------------------------------
# C1 — additive lists are never collapsed to one file's list
# ---------------------------------------------------------------------------


def test_certificates_from_several_files_are_not_resolved_by_pick_one() -> None:
    _RecordingValidator.instances.clear()
    results = [
        _cert_result("Acta_Entrega_recepción_WS.pdf", [WS_ACTA_CERT], "KUBIEC-CONDUIT"),
        _cert_result("WS_Fotovoltaico.pdf", [WSA_LETTER_CERT], "KUBIEC S.A."),
    ]

    with patch.object(ea, "ValidationLayer", _RecordingValidator):
        validated = validate_batch_results(results, EXPERIENCE)

    fields = validated[CERT_TYPE].validated_fields
    # No validated entry for the list → the projects service keeps every file's items.
    assert "certificates" not in fields
    # Scalar conflicts are still resolved by the validator.
    assert _RecordingValidator.instances[0].fields == ["company_name"]
    assert fields["company_name"].value == "KUBIEC S.A."


@pytest.mark.parametrize(
    "field_name",
    ["certificates", "shareholders", "electrical_test_results", "performance_metrics", "existing_mortgages"],
)
def test_previously_collapsed_list_fields_are_additive(field_name: str) -> None:
    assert field_name in ADDITIVE_LIST_FIELDS


def test_no_conflict_list_is_still_not_emitted_as_a_validated_value() -> None:
    # Same list in both files: no conflict, but emitting it would still make the
    # projects service treat the second file as "not selected".
    results = [
        _cert_result("a.pdf", [WS_ACTA_CERT], "KUBIEC S.A."),
        _cert_result("b.pdf", [WS_ACTA_CERT], "KUBIEC S.A."),
    ]
    validated = validate_batch_results(results, EXPERIENCE)
    assert "certificates" not in validated[CERT_TYPE].validated_fields


# ---------------------------------------------------------------------------
# C1 — single-value lists are combined across files (services_included is not)
# ---------------------------------------------------------------------------


def _eshs_result(file_name: str, risks: List[str], services: List[str]) -> DocumentResult:
    return DocumentResult(
        file_name=file_name,
        file_path=f"/tmp/{file_name}",
        document_type="Emergency Response & Security Plan",
        top_level_category=TopLevelCategory.ESG.value,
        extracted_data={"risks_covered": risks, "services_included": services},
    )


def test_combined_list_fields_are_merged_and_deduplicated() -> None:
    _RecordingValidator.instances.clear()
    results = [
        _eshs_result("plan_a.pdf", ["Fire", "Flood"], ["Cleaning"]),
        _eshs_result("plan_b.pdf", ["flood ", "Earthquake"], ["Inspection"]),
    ]
    with patch.object(ea, "ValidationLayer", _RecordingValidator):
        validated = validate_batch_results(results, TopLevelCategory.ESG)

    doc = next(iter(validated.values()))
    risks = doc.validated_fields["risks_covered"]
    assert risks.value == ["Fire", "Flood", "Earthquake"]
    assert risks.provider_fallback is False
    assert "plan_a.pdf" in risks.justification and "plan_b.pdf" in risks.justification
    # services_included is NOT a combined field: still resolved by pick-one.
    assert "services_included" in _RecordingValidator.instances[0].fields
    assert "risks_covered" not in _RecordingValidator.instances[0].fields
    assert "risks_covered" in COMBINED_LIST_FIELDS
    assert "services_included" not in COMBINED_LIST_FIELDS


# ---------------------------------------------------------------------------
# C5 — AI provider can't choose → ranked fallback rules, never "first candidate"
# ---------------------------------------------------------------------------


def _candidate(
    value: str,
    file_name: str,
    *,
    status: str | None = None,
    cited: bool = True,
    order: int = 0,
) -> FieldCandidate:
    return FieldCandidate(
        value=value,
        source_file=f"/tmp/{file_name}",
        source_filename=file_name,
        extracted_text=value,
        chunk_ids=["chunk-1"] if cited else [],
        document_status=status,
        upload_order=order,
    )


def _conflict(*candidates: FieldCandidate) -> FieldConflict:
    return FieldConflict(
        field_name="issuance_date",
        field_description="Date the certificate was issued",
        candidates=list(candidates)
        or [
            # Project 17: the RUC was uploaded first, the real certificate second.
            _candidate("2026-08-21", "1 RUC ACTUAL 21-AGO.pdf", status="report", order=0),
            _candidate(
                "2026-10-06", "10 Certificado_Cumplimiento_Tributario (7).pdf", status="report", order=1
            ),
        ],
        top_level_category=TopLevelCategory.COMPANY_FINANCIALS.value,
        document_type=DocumentType.TAX_COMPLIANCE_CERTIFICATE.value,
    )


class _FakeCompletions:
    def __init__(self, outcomes: List[Any]) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    def create(self, **_kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=outcome))]
        )


def _layer(outcomes: List[Any]) -> tuple[ValidationLayer, _FakeCompletions]:
    layer = ValidationLayer(api_key="test-key", model="test-model")
    completions = _FakeCompletions(outcomes)
    layer.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return layer, completions


_QUOTA_ERROR = RuntimeError("Error code: 429 - insufficient_quota: You have no credits remaining")


def test_provider_error_chooses_by_rules_not_first_candidate(caplog) -> None:
    layer, _ = _layer([_QUOTA_ERROR])
    with caplog.at_level(logging.ERROR, logger="ddx.validation"):
        result = layer.validate_field(_conflict())

    # Same rank, both cited, no majority → most recently uploaded file (the real
    # certificate), not the first file (the RUC) as before V1-2273.
    assert result.provider_fallback is True
    assert result.selected_value == "2026-10-06"
    assert result.selected_source_filename == "10 Certificado_Cumplimiento_Tributario (7).pdf"
    assert result.confidence_score == FALLBACK_CONFIDENCE
    assert "most recently uploaded file" in result.justification
    assert "Defaulting to first candidate" not in result.justification
    assert [a["value"] for a in result.alternative_values] == ["2026-08-21"]
    assert PROVIDER_FALLBACK_FLAG in result.flags
    assert any(AI_PROVIDER_FAILURE_MARKER in r.getMessage() for r in caplog.records)


def test_fallback_rule_1_higher_source_rank_wins() -> None:
    layer, _ = _layer([_QUOTA_ERROR])
    result = layer.validate_field(
        _conflict(
            _candidate("A", "audited.pdf", status="audited", order=0),
            _candidate("B", "summary.pdf", status="summary", order=1),
        )
    )
    assert result.selected_value == "A"
    assert "higher-ranked source document" in result.justification


def test_fallback_rule_2_cited_value_beats_uncited() -> None:
    layer, _ = _layer([_QUOTA_ERROR])
    result = layer.validate_field(
        _conflict(
            _candidate("A", "cited.pdf", cited=True, order=0),
            _candidate("B", "uncited.pdf", cited=False, order=1),
        )
    )
    assert result.selected_value == "A"
    assert "value cited from the document" in result.justification


def test_fallback_rule_3_majority_value_wins() -> None:
    layer, _ = _layer([_QUOTA_ERROR])
    result = layer.validate_field(
        _conflict(
            _candidate("A", "one.pdf", order=0),
            _candidate("A", "two.pdf", order=1),
            _candidate("B", "three.pdf", order=2),
        )
    )
    assert result.selected_value == "A"
    assert "value given by 2 of 3 files" in result.justification


def test_fallback_rules_apply_in_order() -> None:
    # Rank beats majority: one audited file outweighs two summary sheets.
    layer, _ = _layer([_QUOTA_ERROR])
    result = layer.validate_field(
        _conflict(
            _candidate("A", "s1.pdf", status="summary", order=0),
            _candidate("A", "s2.pdf", status="summary", order=1),
            _candidate("B", "audited.pdf", status="audited", order=2),
        )
    )
    assert result.selected_value == "B"
    assert "higher-ranked source document" in result.justification


def test_unparseable_answer_is_retried_then_falls_back_to_rules(caplog) -> None:
    layer, completions = _layer(["not json", "still not json"])
    with caplog.at_level(logging.ERROR, logger="ddx.validation"):
        result = layer.validate_field(_conflict())
    assert completions.calls == 2
    assert result.provider_fallback is True
    assert result.selected_value == "2026-10-06"
    assert any(AI_PROVIDER_FAILURE_MARKER in r.getMessage() for r in caplog.records)


def test_unparseable_answer_recovers_on_retry() -> None:
    good = json.dumps({"selected_index": 0, "confidence_score": 0.95, "justification": "ok"})
    layer, completions = _layer(["oops", good])
    result = layer.validate_field(_conflict())
    assert completions.calls == 2
    assert result.provider_fallback is False
    assert result.selected_value == "2026-08-21"  # the model's own choice is kept


def test_out_of_range_index_is_not_silently_mapped_to_first_candidate() -> None:
    bad = json.dumps({"selected_index": 7, "confidence_score": 0.9, "justification": "x"})
    layer, _ = _layer([bad, bad])
    result = layer.validate_field(_conflict())
    assert result.provider_fallback is True
    assert result.selected_value == "2026-10-06"


def test_openai_client_is_configured_with_retries() -> None:
    layer = ValidationLayer(api_key="test-key", model="test-model")
    assert layer.client.max_retries >= 3


def test_fallback_flows_into_validated_output_with_rank_and_order() -> None:
    def _fallback_all(self, conflicts, top_level_category, document_type, source_files):
        validations = [
            ValidationLayer._fallback_result(c, reason="provider down", flag="API_ERROR: x")
            for c in conflicts
        ]
        return ValidationReport(
            top_level_category=top_level_category,
            top_level_folder="x",
            document_type=document_type,
            document_type_folder="x",
            total_fields_validated=len(validations),
            total_files_processed=len(source_files),
            source_files=source_files,
            validations=validations,
            overall_confidence=FALLBACK_CONFIDENCE,
            summary="fallback",
        )

    tax_type = DocumentType.TAX_COMPLIANCE_CERTIFICATE.value
    results = [
        DocumentResult(
            file_name=name,
            file_path=f"/tmp/{name}",
            document_type=tax_type,
            top_level_category=TopLevelCategory.COMPANY_FINANCIALS.value,
            extracted_data={"issuance_date": date},
            document_status=status,
        )
        for name, date, status in (
            ("audited.pdf", "2026-08-21", "final"),
            ("later.pdf", "2026-10-06", "report"),
        )
    ]
    with patch.object(ValidationLayer, "__init__", lambda self, model="x": None), patch.object(
        ValidationLayer, "validate_all_conflicts", _fallback_all
    ):
        validated = validate_batch_results(results, TopLevelCategory.COMPANY_FINANCIALS)

    field = validated[tax_type].validated_fields["issuance_date"]
    # document_status reaches the candidates: the "final" file outranks the later "report".
    assert field.provider_fallback is True
    assert field.value == "2026-08-21"
    assert field.source_filename == "audited.pdf"
    assert field.confidence_score == FALLBACK_CONFIDENCE
    assert [a["value"] for a in field.alternatives] == ["2026-10-06"]


# ---------------------------------------------------------------------------
# C2 support — document_status is returned beside the data, never as a field
# ---------------------------------------------------------------------------


def test_document_status_is_lifted_out_of_extracted_data() -> None:
    async def fake_extract(client, markdown, schema, model=None, rate_limiter=None):
        assert "document_status" in json.loads(schema)["properties"]
        return {
            "extraction": {
                "document_status": "Audited",
                "fiscal_year": 2024,
                "financial_ratios": [{"year": 2024, "current_assets": 71529420}],
            },
            "extraction_metadata": {"document_status": {"value": "Audited", "references": []}},
        }

    with patch.object(ea, "_async_extract", fake_extract):
        extracted, raw = asyncio.run(
            ea._async_extract_fields(None, "# md", DocumentType.FINANCIAL_STATEMENTS.value)
        )

    assert "document_status" not in extracted
    assert "document_status" not in raw["extraction_metadata"]
    assert raw["document_status"] == "audited"


@pytest.mark.parametrize(
    "value,expected",
    [("Summary", "summary"), (" amended ", "amended"), ("unknown", None), (None, None), (3, None)],
)
def test_normalize_document_status(value, expected) -> None:
    assert ea._normalize_document_status(value) == expected


# ---------------------------------------------------------------------------
# Contract — every repeated field the projects service explodes is additive here
# ---------------------------------------------------------------------------

# Filled by equipment web research after extraction, never by cross-file validation.
RESEARCH_ONLY_FIELDS = {
    "module_certificate_evidence",
    "inverter_certificate_evidence",
    "module_test_evidence",
    "inverter_test_evidence",
}


def _registry_path() -> Path:
    env = os.getenv("DREX_PROJECTS_REPO")
    base = Path(env) if env else Path(__file__).resolve().parents[2] / "app-drex-projects"
    return base / "src" / "projects" / "config" / "repeated-field.registry.ts"


def test_additive_fields_cover_projects_repeated_field_registry() -> None:
    path = _registry_path()
    if not path.exists():
        pytest.skip(f"projects repo not checked out at {path}")
    source = path.read_text(encoding="utf-8")
    active_block = source.split("export const ACTIVE_REPEATED_FIELDS", 1)[1].split(
        "export const PENDING_REPEATED_FIELDS", 1
    )[0]
    root_fields = set(re.findall(r"rootFieldName:\s*'([a-z_]+)'", active_block))
    assert root_fields, "could not parse ACTIVE_REPEATED_FIELDS"
    missing = sorted(root_fields - ADDITIVE_LIST_FIELDS - RESEARCH_ONLY_FIELDS)
    assert not missing, f"repeated fields missing from ADDITIVE_LIST_FIELDS: {missing}"
