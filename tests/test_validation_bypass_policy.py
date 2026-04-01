from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from ddx.api.models import ProcessingConfig, TargetedCompletionRequest
from ddx.api.services import targeted_completion
from ddx.classification.extraction_api import (
    DocumentResult,
    _run_optional_validation,
)
from ddx.classification.categories import TopLevelCategory
from ddx.classification.landing_ai_poc_sdk import (
    should_disable_cross_document_validation,
)


def test_should_disable_cross_document_validation_for_time_series_documents() -> None:
    assert should_disable_cross_document_validation("Financial Statements") is True
    assert (
        should_disable_cross_document_validation(
            "Some Other Document",
            ["monthly_consumption"],
        )
        is True
    )
    assert should_disable_cross_document_validation("Tax Compliance Certificate") is False


def test_run_optional_validation_skips_time_series_documents() -> None:
    results = [
        DocumentResult(
            file_name="financials_2022.pdf",
            document_type="Financial Statements",
            top_level_category=TopLevelCategory.COMPANY_FINANCIALS.value,
            extracted_data={"financial_ratios": [{"year": 2022}]},
        ),
        DocumentResult(
            file_name="financials_2023.pdf",
            document_type="Financial Statements",
            top_level_category=TopLevelCategory.COMPANY_FINANCIALS.value,
            extracted_data={"financial_ratios": [{"year": 2023}]},
        ),
    ]

    validated_results, validation_performed = _run_optional_validation(
        results,
        enable_validation=True,
        top_level_category=TopLevelCategory.COMPANY_FINANCIALS,
        validation_model="test-model",
    )

    assert validated_results is None
    assert validation_performed is False


def test_targeted_completion_disables_validation_for_time_series_documents() -> None:
    request = TargetedCompletionRequest(
        s3_paths=["projects/demo/financials_2023.pdf"],
        bucket="demo-bucket",
        document_type="Financial Statements",
        project_id="project-1",
        config=ProcessingConfig(),
    )
    existing_local_path = Path(__file__)
    path_mapping = {request.s3_paths[0]: existing_local_path}
    extract_mock = AsyncMock(
        return_value=(
            [
                DocumentResult(
                    file_name="financials_2023.pdf",
                    document_type="Financial Statements",
                    top_level_category=TopLevelCategory.COMPANY_FINANCIALS.value,
                    extracted_data={"financial_ratios": [{"year": 2023}]},
                )
            ],
            None,
        )
    )

    with (
        patch(
            "ddx.api.services.download_s3_files",
            new=AsyncMock(return_value=(Path("temp-dir"), path_mapping)),
        ),
        patch(
            "ddx.api.services.extract_documents_direct_batch_async",
            new=extract_mock,
        ),
        patch("ddx.api.services.cleanup_temp_dir"),
    ):
        response = asyncio.run(targeted_completion(request))

    assert response.consolidated_result is None
    assert extract_mock.await_args.kwargs["enable_validation"] is False


def test_targeted_completion_keeps_enforced_validation_for_other_document_types() -> None:
    request = TargetedCompletionRequest(
        s3_paths=["projects/demo/tax_compliance.pdf"],
        bucket="demo-bucket",
        document_type="Tax Compliance Certificate",
        project_id="project-1",
        enable_validation=False,
        config=ProcessingConfig(),
    )
    existing_local_path = Path(__file__)
    path_mapping = {request.s3_paths[0]: existing_local_path}
    extract_mock = AsyncMock(
        return_value=(
            [
                DocumentResult(
                    file_name="tax_compliance.pdf",
                    document_type="Tax Compliance Certificate",
                    top_level_category=TopLevelCategory.COMPANY_FINANCIALS.value,
                    extracted_data={"tax_compliance_status": "Compliant"},
                )
            ],
            None,
        )
    )

    with (
        patch(
            "ddx.api.services.download_s3_files",
            new=AsyncMock(return_value=(Path("temp-dir"), path_mapping)),
        ),
        patch(
            "ddx.api.services.extract_documents_direct_batch_async",
            new=extract_mock,
        ),
        patch("ddx.api.services.cleanup_temp_dir"),
    ):
        asyncio.run(targeted_completion(request))

    assert extract_mock.await_args.kwargs["enable_validation"] is True
