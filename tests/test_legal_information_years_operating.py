"""V1-2448: years_operating is calculated from incorporation_date, never asked of the model."""

from __future__ import annotations

import asyncio
import json
from datetime import date

import pytest

from ddx.classification import extraction_api as ea
from ddx.classification.categories import (
    DocumentType,
    LegalInformation,
    compute_years_operating,
    normalize_extracted_document,
    normalize_legal_information_extraction,
)

TODAY = date(2026, 11, 26)
DOC_TYPE = DocumentType.CERTIFICATE_OF_LEGAL_EXISTENCE.value
DATE_META = {
    "confidence": 0.97,
    "extracted_text": "Fecha de constitución 08/04/2003",
    "references": ["0-8"],
}


@pytest.mark.parametrize(
    "value, expected",
    [
        ("2003-04-08", 23),
        ("08/04/2003", 23),
        ("8 de abril de 2003", 23),
        ("2003", 23),
        ("2026-01-02", 0),
        ("1998", 28),
    ],
)
def test_years_are_current_year_minus_incorporation_year(value, expected) -> None:
    assert compute_years_operating(value, TODAY) == expected


@pytest.mark.parametrize("value", [None, "", "  ", "No registra", "2030-01-01", 2003, "12/04"])
def test_no_readable_year_gives_none_not_a_guess(value) -> None:
    assert compute_years_operating(value, TODAY) is None


def test_model_guess_is_replaced_by_the_calculated_value() -> None:
    extracted = {
        "legal_name": "CONDOMINIO PARQUE CALIFORNIA DOS",
        "incorporation_date": "2003-04-08",
        "years_operating": 22,
    }
    metadata = {"incorporation_date": DATE_META, "years_operating": {"confidence": 0.4}}

    out, meta = normalize_legal_information_extraction(extracted, metadata, TODAY)

    assert out["years_operating"] == 23
    assert out["incorporation_date"] == "2003-04-08"
    # The years carry the date's proof (same confidence, same page reference).
    assert meta["years_operating"] == DATE_META
    assert meta["years_operating"] is not DATE_META
    # Inputs are not mutated.
    assert extracted["years_operating"] == 22
    assert metadata["years_operating"] == {"confidence": 0.4}


def test_empty_date_clears_years_and_their_metadata() -> None:
    """The V1-2448 case: the parse lost the date, so the years must be empty too."""
    out, meta = normalize_legal_information_extraction(
        {"incorporation_date": "", "years_operating": 22},
        {"incorporation_date": {"confidence": 0.1}, "years_operating": {"confidence": 0.5}},
        TODAY,
    )
    assert out["years_operating"] is None
    assert "years_operating" not in meta


def test_request_without_either_field_is_left_alone() -> None:
    extracted = {"legal_name": "X", "tax_id_ruc": "0992292474001"}
    out, meta = normalize_legal_information_extraction(extracted, {"legal_name": {}}, TODAY)
    assert out == extracted
    assert "years_operating" not in out
    assert meta == {"legal_name": {}}


def test_dispatch_runs_for_the_certificate_document_type() -> None:
    validated = LegalInformation.model_validate(
        {
            "legal_name": "X",
            "tax_id_ruc": "1",
            "commercial_activity": "Y",
            "incorporation_date": "2003-04-08",
        }
    ).model_dump()
    out, _ = normalize_extracted_document(DOC_TYPE, validated, None)
    assert out["years_operating"] == date.today().year - 2003


def test_other_document_types_are_not_touched() -> None:
    extracted = {"incorporation_date": "2003-04-08", "years_operating": 22}
    out, _ = normalize_extracted_document(DocumentType.SHAREHOLDERS_DECLARATION.value, extracted)
    assert out["years_operating"] == 22


def test_schema_fields_swap_years_for_the_date() -> None:
    assert ea._schema_fields_for_request(DOC_TYPE, ["years_operating"]) == ["incorporation_date"]
    assert ea._schema_fields_for_request(DOC_TYPE, ["incorporation_date", "years_operating"]) == [
        "incorporation_date"
    ]
    assert ea._schema_fields_for_request(DOC_TYPE, ["legal_name"]) == ["legal_name"]
    other = DocumentType.PROJECT_SIMULATION_REPORT.value
    assert ea._schema_fields_for_request(other, ["years_operating"]) == ["years_operating"]


def _fake_extract(captured: dict, extraction: dict, metadata: dict):
    async def fake(client, markdown_content, schema, model=None, rate_limiter=None):
        captured["schema"] = json.loads(schema) if isinstance(schema, str) else schema
        return {"extraction": dict(extraction), "extraction_metadata": dict(metadata)}

    return fake


def test_full_extraction_never_asks_the_model_for_years(monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(
        ea,
        "_async_extract",
        _fake_extract(
            captured,
            {
                "legal_name": "X",
                "tax_id_ruc": "0992292474001",
                "commercial_activity": "Y",
                "incorporation_date": "2003-04-08",
            },
            {"incorporation_date": DATE_META},
        ),
    )

    extracted, raw = asyncio.run(ea._async_extract_fields(None, "md", DOC_TYPE))

    props = captured["schema"]["properties"]
    assert "years_operating" not in props
    assert "incorporation_date" in props
    assert extracted["years_operating"] == date.today().year - 2003
    assert raw["extraction_metadata"]["years_operating"]["confidence"] == 0.97


def test_field_request_for_years_asks_for_the_date_and_returns_only_years(monkeypatch) -> None:
    captured: dict = {}

    async def fake_parse(*args, **kwargs):
        return "md", None

    monkeypatch.setattr(ea, "_parse_or_use_existing", fake_parse)
    monkeypatch.setattr(ea, "_get_async_client", lambda: None)
    monkeypatch.setattr(
        ea,
        "_async_extract",
        _fake_extract(
            captured,
            {"incorporation_date": "08/04/2003"},
            {"incorporation_date": DATE_META},
        ),
    )

    result = asyncio.run(
        ea.extract_specific_fields_async(
            b"%PDF", DOC_TYPE, ["years_operating"], file_name="ruc.pdf"
        )
    )

    assert result.success, result
    props = captured["schema"]["properties"]
    assert set(props) == {"incorporation_date"}
    assert result.extracted_fields == {"years_operating": date.today().year - 2003}
    assert set(result.extraction_metadata) == {"years_operating"}
