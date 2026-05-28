from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from ddx.api.main import app
from ddx.api.models import TeaserNarrativeGenerationResponse


@pytest.fixture
def client():
    return TestClient(app)


def create_request_payload() -> dict:
    return {
        "project_id": "44",
        "project_name": "Parque Solar Norte",
        "language": "en",
        "tone": "institutional-investment-brief",
        "teaser_data": {
            "project": {
                "id": 44,
                "name": "Parque Solar Norte",
                "location": "Quito, Ecuador",
            },
            "metrics": {
                "totalDcCapacityKw": 1200,
                "totalAcCapacityKw": 1000,
                "annualEnergyProductionMwh": 2450.5,
                "performanceRatioPct": 82.4,
                "dcAcRatio": 1.2,
                "totalCapexIncVatUsd": 1064000.75,
                "totalCapexExVatUsd": 950000.5,
                "unleveredIrrPct": None,
                "dscr": None,
                "investedByOfftakerUsd": None,
                "ppaLengthYears": 15,
            },
            "technical": {
                "solarModuleBrand": "Trina Solar",
                "solarModuleModel": "Vertex N 700W",
                "solarModuleTechWarrantyYears": 12,
                "solarModuleLinearWarrantyYears": 30,
                "inverterBrand": "Sungrow",
                "inverterModel": "SG350HX",
                "inverterTechWarrantyYears": 10,
                "degradationYear1Pct": 1,
                "degradationYear2OnwardsPct": 0.4,
                "shadowLossPct": 2.5,
            },
            "regulatory": {
                "feasibilityIssued": "Yes",
                "capacityRequestedKw": 1200,
                "availableHostingCapacityKw": 1500,
                "maxPermittedAnnualGenerationKwh": 2500000,
                "regulatoryFramework": "Resolution ARCERNNR 003/23",
                "issueDate": "2026-01-15",
                "validityPeriodMonths": 12,
                "validityExpiryDate": "2027-01-15",
                "feasibilitySummary": "Feasibility is confirmed.",
            },
            "esg": {
                "esmpAlignment": {"state": "delivered"},
                "industrialSafetyPlan": {"state": "missing"},
                "qaQcPlan": {"state": "delivered"},
                "wasteManagementPlan": {"state": "missing"},
                "esmpValidity": {"state": "delivered"},
                "landUsePermit": {"state": "deliver_later"},
                "emergencyResponse": {"state": "missing"},
                "certificateNonProtectedAreas": {"state": "delivered"},
            },
            "narrativeContext": {
                "country": "Ecuador",
                "industry": "Industrial manufacturing",
                "offtakerSector": "Industrial",
                "investmentAngle": "documented interconnection feasibility and energy output",
            },
        },
    }


def test_generate_teaser_narrative_endpoint_success(client: TestClient):
    mocked_response = TeaserNarrativeGenerationResponse(
        generated_at="2026-04-22T10:00:00+00:00",
        project_id="44",
        project_name="Parque Solar Norte",
        language="en",
        model_version="gpt-test",
        overview="overview text " * 10,
        financial="financial text " * 8,
        technical="technical text " * 8,
        regulatory="regulatory text " * 6,
        esg="esg text " * 7,
        conclusion="conclusion text " * 7,
        quality_checks={"within_budget": True},
        generation_mode="llm",
    )

    with patch(
        "ddx.api.main.generate_teaser_narrative",
        return_value=mocked_response,
    ):
        response = client.post(
            "/api/v1/teaser/narrative/generate",
            json=create_request_payload(),
        )

    assert response.status_code == 200
    data = response.json()
    assert data["project_id"] == "44"
    assert data["generation_mode"] == "llm"
    assert "overview" in data
    assert "financial" in data


def test_generate_teaser_narrative_endpoint_maps_value_error_to_bad_request(
    client: TestClient,
):
    with patch(
        "ddx.api.main.generate_teaser_narrative",
        side_effect=ValueError("invalid teaser payload"),
    ):
        response = client.post(
            "/api/v1/teaser/narrative/generate",
            json=create_request_payload(),
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid teaser payload"
