from __future__ import annotations

import pytest

from ddx.classification.categories import (
    DocumentType,
    FinancialStatementsData,
    normalize_extracted_document,
)


def _financial_row(year: int, current_assets: float) -> dict:
    return {
        "year": year,
        "current_assets": current_assets,
        "inventory": 10.0,
        "total_assets": 300.0,
        "current_liabilities": 50.0,
        "total_liabilities": 120.0,
        "equity": 180.0,
        "revenue": 500.0,
        "net_income": 25.0,
        "ebit": 40.0,
        "interest_expenses": 5.0,
    }


def test_financial_statements_keep_only_document_fiscal_year() -> None:
    data = FinancialStatementsData.model_validate(
        {
            "fiscal_year": 2021,
            "financial_ratios": [
                _financial_row(2021, 100.0),
                _financial_row(2020, 90.0),
            ],
        }
    )

    assert data.fiscal_year == 2021
    assert [row.year for row in data.financial_ratios] == [2021]
    assert data.financial_ratios[0].current_ratio == pytest.approx(2.0)
    assert data.financial_ratios[0].interest_coverage_ratio == pytest.approx(8.0)


def test_financial_statement_normalization_infers_latest_year_and_trims_metadata() -> None:
    extracted = {
        "company_name": "Example Co",
        "financial_ratios": [
            _financial_row(2021, 100.0),
            _financial_row(2020, 90.0),
        ],
    }
    extraction_metadata = {
        "financial_ratios": [
            {"year": {"value": 2021, "references": ["chunk-2021"]}},
            {"year": {"value": 2020, "references": ["chunk-2020"]}},
        ]
    }

    normalized_extracted, normalized_metadata = normalize_extracted_document(
        DocumentType.FINANCIAL_STATEMENTS,
        extracted,
        extraction_metadata,
    )

    assert normalized_extracted["fiscal_year"] == 2021
    assert [row["year"] for row in normalized_extracted["financial_ratios"]] == [2021]
    assert normalized_metadata == {
        "financial_ratios": [
            {"year": {"value": 2021, "references": ["chunk-2021"]}},
        ]
    }
