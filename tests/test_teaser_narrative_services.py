from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ddx.api.models import TeaserNarrativeGenerationRequest
from ddx.api.services import (
    _build_fallback_teaser_narrative,
    _build_teaser_narrative_user_payload,
    _validate_teaser_narrative_section_boundaries,
)


def create_request() -> TeaserNarrativeGenerationRequest:
    return TeaserNarrativeGenerationRequest.model_validate(
        {
            "project_id": "104",
            "project_name": "gye01",
            "language": "es",
            "tone": "Concise Spanish investment teaser for infrastructure diligence",
            "teaser_data": {
                "project": {
                    "id": 104,
                    "name": "gye01",
                    "location": "-2.0979133,-79.9416678,15",
                },
                "metrics": {
                    "totalDcCapacityKw": 1500,
                    "totalAcCapacityKw": 0,
                    "annualEnergyProductionMwh": 0,
                    "performanceRatioPct": 98.4,
                    "dcAcRatio": None,
                    "totalCapexIncVatUsd": 883701,
                    "totalCapexExVatUsd": 819000,
                    "unleveredIrrPct": None,
                    "dscr": 1.2,
                    "investedByOfftakerUsd": 441850.5,
                    "ppaLengthYears": 5,
                },
                "technical": {
                    "solarModuleBrand": "GCL",
                    "solarModuleModel": "NT12/66GDF",
                    "solarModuleTechWarrantyYears": 12,
                    "solarModuleLinearWarrantyYears": 30,
                    "inverterBrand": "Huawei",
                    "inverterModel": "SUN2000-50K-MGL0",
                    "inverterTechWarrantyYears": None,
                    "degradationYear1Pct": 1,
                    "degradationYear2OnwardsPct": 0.4,
                    "shadowLossPct": 0,
                },
                "regulatory": {
                    "feasibilityIssued": "Yes",
                    "capacityRequestedKw": 4500,
                    "availableHostingCapacityKw": 3400,
                    "maxPermittedAnnualGenerationKwh": 7272000,
                    "regulatoryFramework": "ARCERNNR-005/24",
                    "issueDate": "2024-12-31",
                    "validityPeriodMonths": 6,
                    "validityExpiryDate": "2025-06-30",
                    "feasibilitySummary": "The electrical utility feasibility report confirms the project is feasible for grid interconnection.",
                },
                "esg": {
                    "esmpAlignment": {"state": "delivered"},
                    "industrialSafetyPlan": {"state": "missing"},
                    "qaQcPlan": {"state": "missing"},
                    "wasteManagementPlan": {"state": "delivered"},
                    "esmpValidity": {"state": "missing"},
                    "landUsePermit": {"state": "missing"},
                    "emergencyResponse": {"state": "missing"},
                    "certificateNonProtectedAreas": {"state": "missing"},
                },
                "narrativeContext": {
                    "country": "EC",
                    "industry": "default_type",
                    "offtakerSector": None,
                    "investmentAngle": "documented grid-feasibility status, defined commercial assumptions, and partial delivered ESG evidence",
                },
            },
        }
    )


def test_teaser_prompt_payload_marks_financial_content_as_forbidden_in_overview() -> None:
    payload = _build_teaser_narrative_user_payload(create_request())

    overview_guidance = payload["section_guidance"]["overview"]

    assert "CAPEX amounts" in overview_guidance["forbidden_topics"]
    assert "DSCR" in overview_guidance["forbidden_topics"]
    assert (
        "raw regulatory framework codes or document IDs such as ARCERNNR"
        in overview_guidance["forbidden_topics"]
    )
    assert payload["hard_rules"]["keep_overview_non_financial"] is True
    assert payload["hard_rules"]["overview_forbids_raw_regulatory_detail"] is True


def test_teaser_overview_boundary_validator_rejects_financial_and_raw_regulatory_detail() -> None:
    with pytest.raises(RuntimeError, match="overview violated section boundary"):
        _validate_teaser_narrative_section_boundaries(
            create_request(),
            {
                "overview": (
                    "El proyecto presenta un CAPEX de 883,701 USD, un DSCR de 1.2 y el marco "
                    "ARCERNNR-005/24 con fecha 31/12/2024."
                )
            },
        )


def test_teaser_fallback_overview_stays_non_financial_even_if_investment_angle_mentions_commercial_language() -> (
    None
):
    result = _build_fallback_teaser_narrative(
        create_request(),
        "budget failure",
    )

    assert "883701" not in result.overview
    assert "819000" not in result.overview
    assert "441850.5" not in result.overview
    assert "1.2" not in result.overview
    assert "5 years" not in result.overview
    assert "defined commercial assumptions" not in result.overview
    assert "documented technical configuration" in result.overview
