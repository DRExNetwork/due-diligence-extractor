from __future__ import annotations

import pytest

from ddx.api.services import _normalize_document_type, _validate_target_fields
from ddx.classification.categories import (
    DOCUMENT_TYPE_DESCRIPTIONS,
    DOCUMENT_TYPE_TO_TOP_LEVEL,
    PYDANTIC_MODELS,
    CnelEnergyBillData,
    DocumentType,
)

# The exact target_fields the NestJS bill pipeline sends (capture set + derived).
NESTJS_TARGET_FIELDS = [
    "contract_account",
    "barcode_text",
    "company_name",
    "service_address",
    "tariff_raw",
    "issue_date",
    "billing_period_from",
    "billing_period_to",
    "valor_total",
    "valor_consumo",
    "valor_demanda",
    "detail_rows",
    "total_active_energy_kwh",
    "solar_kwh",
    "grid_kwh",
    "billable_amount_usd",
    "tariff_code",
]


def test_slug_resolves_to_canonical_document_type():
    # NestJS sends the snake_case slug; it must resolve to the canonical value.
    resolved = _normalize_document_type("cnel_energy_bill")
    assert resolved == "CNEL Energy Bill"


def test_canonical_and_case_insensitive_forms_resolve():
    assert _normalize_document_type("CNEL Energy Bill") == "CNEL Energy Bill"
    assert _normalize_document_type("cnel energy bill") == "CNEL Energy Bill"


def test_registered_in_pydantic_models():
    assert PYDANTIC_MODELS[DocumentType.CNEL_ENERGY_BILL] is CnelEnergyBillData


def test_not_a_data_room_classification_candidate():
    # Regression lock: DOCUMENT_TYPE_TO_TOP_LEVEL feeds the bulk-ingest
    # classification prompts (build_classification_schema_for_category).
    # Registering this type there would let Data Room energy-bill uploads
    # classify as "CNEL Energy Bill" and break the existing flow.
    assert DocumentType.CNEL_ENERGY_BILL not in DOCUMENT_TYPE_TO_TOP_LEVEL


def test_has_description_for_listing():
    assert DOCUMENT_TYPE_DESCRIPTIONS[DocumentType.CNEL_ENERGY_BILL]


def test_nestjs_target_fields_validate():
    resolved = _normalize_document_type("cnel_energy_bill")
    _validate_target_fields(resolved, NESTJS_TARGET_FIELDS)  # must not raise


def test_typo_in_target_fields_rejected():
    resolved = _normalize_document_type("cnel_energy_bill")
    with pytest.raises(ValueError, match="Invalid fields"):
        _validate_target_fields(resolved, ["grid_kwh", "billable_amount"])  # typo


def test_capture_fields_have_instruction_descriptions():
    for field_name, field_info in CnelEnergyBillData.model_fields.items():
        assert field_info.description, f"{field_name} is missing a description"


def test_derived_fields_marked_computed_server_side():
    for field_name in (
        "total_active_energy_kwh",
        "solar_kwh",
        "grid_kwh",
        "billable_amount_usd",
        "tariff_code",
    ):
        description = CnelEnergyBillData.model_fields[field_name].description
        assert "Computed server-side" in description, field_name


def test_no_tariff_vocabulary_in_any_description():
    # The capture prompt must carry ZERO tariff row vocabulary — row names live
    # in the reducer only (plan §5 rule 2). Guards against prompt-drift edits.
    # ('Días facturados' is a header label, not a row name — not forbidden.)
    forbidden = ("energía facturable", "energia facturable", "inyectada", "activa total", "act. hor")
    for field_name, field_info in CnelEnergyBillData.model_fields.items():
        description = (field_info.description or "").lower()
        for token in forbidden:
            assert token not in description, f"{field_name} description names a tariff row ({token})"


def test_all_fields_nullable():
    # Absence must be reportable: a required field forces the model to invent
    # values on tariffs that omit it (e.g. Factor de multiplicación on BT bills).
    payload = CnelEnergyBillData()
    assert payload.detail_rows == []
    assert payload.multiplication_factor is None
    assert payload.valor_demanda is None
