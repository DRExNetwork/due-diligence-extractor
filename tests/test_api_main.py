"""
Test cases for DDX API main endpoints with debug output.

Tests the following endpoints:
- GET /health
- GET /api/v1/schemas/categories
- GET /api/v1/schemas/categories/{category}
- GET /api/v1/schemas/document-types/{document_type}
- GET /api/v1/schemas/document-types
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from ddx.api.main import app
from ddx.api.models import HealthResponse, CategoryInfo, DocumentTypeInfo
from ddx.api.services import _resolve_document_type


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def client():
    """Create a TestClient instance for the FastAPI app."""
    return TestClient(app)


@pytest.fixture
def mock_categories():
    """Mock supported categories."""
    return ["Company Information", "Technical", "Legal & Permits"]


@pytest.fixture
def mock_category_doc_types():
    """Mock document types for a category."""
    return ["Project Simulation Report", "Financial Statements"]


@pytest.fixture
def mock_document_type_fields():
    """Mock fields for a document type."""
    return {
        "performance_ratio_pct": {"type": "float", "description": "Performance ratio percentage"},
        "total_pv_energy_mwh": {"type": "float", "description": "Total PV energy in MWh"},
    }


@pytest.fixture
def mock_all_schemas():
    """Mock all schemas info."""
    return {
        "Company Information": {
            "Project Simulation Report": {
                "performance_ratio_pct": {"type": "float"},
                "total_pv_energy_mwh": {"type": "float"},
            }
        }
    }


# =============================================================================
# Health Endpoint Tests
# =============================================================================


class TestHealthEndpoint:
    """Test cases for GET /health endpoint."""

    def test_health_success(self, client, mock_categories):
        """Test health endpoint returns successful response."""
        print(f"\n{'='*60}")
        print("TEST: test_health_success")
        print(f"Input mock_categories: {mock_categories}")

        with patch("ddx.api.main.get_supported_categories", return_value=mock_categories):
            with patch(
                "ddx.api.main.CATEGORY_DOCUMENT_TYPES",
                {
                    "Company Information": ["doc1", "doc2"],
                    "Technical": ["doc3"],
                },
            ):
                response = client.get("/health")
                print(f"Response status: {response.status_code}")
                print(f"Response data: {response.json()}")

                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "ok"
                assert data["version"] == "2.0.0"
                assert data["supported_categories"] == mock_categories
                assert data["total_document_types"] == 3
                assert "timestamp" in data
                print("✓ All assertions passed")
                print(f"{'='*60}\n")

    def test_health_response_model(self, client):
        """Test health endpoint returns valid HealthResponse model."""
        print(f"\n{'='*60}")
        print("TEST: test_health_response_model")

        with patch("ddx.api.main.get_supported_categories", return_value=[]):
            with patch("ddx.api.main.CATEGORY_DOCUMENT_TYPES", {}):
                response = client.get("/health")
                print(f"Response status: {response.status_code}")
                print(f"Response data: {response.json()}")

                assert response.status_code == 200

                health_response = HealthResponse(**response.json())
                print(f"Pydantic model parsed: {health_response}")
                assert health_response.status == "ok"
                assert health_response.version == "2.0.0"
                print("✓ All assertions passed")
                print(f"{'='*60}\n")


# =============================================================================
# List Categories Endpoint Tests
# =============================================================================


class TestListCategoriesEndpoint:
    """Test cases for GET /api/v1/schemas/categories endpoint."""

    def test_list_categories_success(self, client, mock_categories, mock_category_doc_types):
        """Test listing all categories successfully."""
        print(f"\n{'='*60}")
        print("TEST: test_list_categories_success")
        print(f"Input mock_categories: {mock_categories}")
        print(f"Input mock_category_doc_types: {mock_category_doc_types}")

        with patch("ddx.api.main.get_supported_categories", return_value=mock_categories):
            with patch(
                "ddx.api.main.get_document_types_for_category_api",
                return_value=mock_category_doc_types,
            ):
                response = client.get("/api/v1/schemas/categories")
                print(f"Response status: {response.status_code}")
                print(f"Response data: {response.json()}")

                assert response.status_code == 200
                data = response.json()
                assert len(data) == 3
                assert data[0]["name"] == "Company Information"
                assert data[0]["document_types"] == mock_category_doc_types
                assert data[0]["document_count"] == 2
                print("✓ All assertions passed")
                print(f"{'='*60}\n")

    def test_list_categories_empty(self, client):
        """Test listing categories when none are supported."""
        print(f"\n{'='*60}")
        print("TEST: test_list_categories_empty")

        with patch("ddx.api.main.get_supported_categories", return_value=[]):
            response = client.get("/api/v1/schemas/categories")
            print(f"Response status: {response.status_code}")
            print(f"Response data: {response.json()}")

            assert response.status_code == 200
            assert response.json() == []
            print("✓ All assertions passed")
            print(f"{'='*60}\n")

    def test_list_categories_skips_invalid(self, client, mock_categories):
        """Test that invalid categories are skipped."""
        print(f"\n{'='*60}")
        print("TEST: test_list_categories_skips_invalid")
        print(f"Input mock_categories: {mock_categories}")

        def side_effect(cat):
            print(f"  side_effect called with: {cat}")
            if cat == "Technical":
                raise ValueError("Invalid category")
            return ["doc1"]

        with patch("ddx.api.main.get_supported_categories", return_value=mock_categories):
            with patch("ddx.api.main.get_document_types_for_category_api", side_effect=side_effect):
                response = client.get("/api/v1/schemas/categories")
                print(f"Response status: {response.status_code}")
                print(f"Response data: {response.json()}")

                assert response.status_code == 200
                data = response.json()
                print(f"Valid categories returned: {[cat['name'] for cat in data]}")
                assert len(data) == 2
                assert "Technical" not in [cat["name"] for cat in data]
                print("✓ All assertions passed")
                print(f"{'='*60}\n")

    def test_list_categories_response_model(self, client, mock_categories, mock_category_doc_types):
        """Test response conforms to List[CategoryInfo] model."""
        with patch("ddx.api.main.get_supported_categories", return_value=mock_categories[:1]):
            with patch(
                "ddx.api.main.get_document_types_for_category_api",
                return_value=mock_category_doc_types,
            ):
                response = client.get("/api/v1/schemas/categories")
                assert response.status_code == 200

                # Validate each item against CategoryInfo model
                categories = [CategoryInfo(**item) for item in response.json()]
                assert len(categories) == 1
                assert categories[0].name == "Company Information"
                assert categories[0].document_count == 2


# =============================================================================
# Get Category Endpoint Tests
# =============================================================================


class TestGetCategoryEndpoint:
    """Test cases for GET /api/v1/schemas/categories/{category} endpoint."""

    def test_get_category_success(self, client, mock_category_doc_types):
        """Test getting a specific category successfully."""
        with patch(
            "ddx.api.main.get_document_types_for_category_api", return_value=mock_category_doc_types
        ):
            response = client.get("/api/v1/schemas/categories/Company%20Information")
            assert response.status_code == 200
            data = response.json()
            assert data["name"] == "Company Information"
            assert data["document_types"] == mock_category_doc_types
            assert data["document_count"] == 2

    def test_get_category_not_found(self, client):
        """Test getting a non-existent category returns 404."""
        with patch(
            "ddx.api.main.get_document_types_for_category_api",
            side_effect=ValueError("Category not found"),
        ):
            response = client.get("/api/v1/schemas/categories/InvalidCategory")
            assert response.status_code == 404
            assert "detail" in response.json()

    def test_get_category_url_encoded(self, client, mock_category_doc_types):
        """Test category names with spaces are properly URL-encoded."""
        with patch(
            "ddx.api.main.get_document_types_for_category_api", return_value=mock_category_doc_types
        ):
            response = client.get("/api/v1/schemas/categories/Company%20Information")
            assert response.status_code == 200

    def test_get_category_response_model(self, client, mock_category_doc_types):
        """Test response conforms to CategoryInfo model."""
        with patch(
            "ddx.api.main.get_document_types_for_category_api", return_value=mock_category_doc_types
        ):
            response = client.get("/api/v1/schemas/categories/Technical")
            assert response.status_code == 200

            category_info = CategoryInfo(**response.json())
            assert category_info.name == "Technical"
            assert category_info.document_count == 2


# =============================================================================
# Get Document Type Schema Endpoint Tests
# =============================================================================


class TestGetDocumentTypeSchemaEndpoint:
    """Test cases for GET /api/v1/schemas/document-types/{document_type} endpoint."""

    def test_get_document_type_schema_success(self, client, mock_document_type_fields):
        """Test getting schema for a specific document type."""
        with patch(
            "ddx.api.main.get_fields_for_document_type", return_value=mock_document_type_fields
        ):
            with patch("ddx.api.main._get_top_level_for_document_type") as mock_top_level:
                mock_top_level.return_value.value = "Technical"
                response = client.get(
                    "/api/v1/schemas/document-types/Project%20Simulation%20Report"
                )
                assert response.status_code == 200
                data = response.json()
                assert data["name"] == "Project Simulation Report"
                assert data["top_level_category"] == "Technical"
                assert data["fields"] == mock_document_type_fields
                assert data["field_count"] == 2

    def test_get_document_type_schema_not_found(self, client):
        """Test getting schema for non-existent document type returns 404."""
        with patch(
            "ddx.api.main.get_fields_for_document_type",
            side_effect=ValueError("Document type not found"),
        ):
            response = client.get("/api/v1/schemas/document-types/InvalidType")
            assert response.status_code == 404
            assert "detail" in response.json()

    def test_get_document_type_schema_no_top_level(self, client, mock_document_type_fields):
        """Test handling when top_level_category is None."""
        with patch(
            "ddx.api.main.get_fields_for_document_type", return_value=mock_document_type_fields
        ):
            with patch("ddx.api.main._get_top_level_for_document_type", return_value=None):
                response = client.get("/api/v1/schemas/document-types/SomeType")
                assert response.status_code == 200
                data = response.json()
                assert data["top_level_category"] == "unknown"

    def test_get_document_type_schema_accepts_slash_in_name(
        self, client, mock_document_type_fields
    ):
        """Test document type names containing '/' are routed and resolved correctly."""
        with patch(
            "ddx.api.main.get_fields_for_document_type", return_value=mock_document_type_fields
        ):
            with patch("ddx.api.main._get_top_level_for_document_type") as mock_top_level:
                mock_top_level.return_value.value = "Company Financials"
                response = client.get("/api/v1/schemas/document-types/Economical%20Offer%20/%20BOQ")
                assert response.status_code == 200
                data = response.json()
                assert data["name"] == "Economical Offer / BOQ"
                assert data["top_level_category"] == "Company Financials"
                assert data["field_count"] == 2

    def test_get_document_type_schema_response_model(self, client, mock_document_type_fields):
        """Test response conforms to DocumentTypeInfo model."""
        with patch(
            "ddx.api.main.get_fields_for_document_type", return_value=mock_document_type_fields
        ):
            with patch("ddx.api.main._get_top_level_for_document_type") as mock_top_level:
                mock_top_level.return_value.value = "Technical"
                response = client.get("/api/v1/schemas/document-types/Report")
                assert response.status_code == 200

                doc_type_info = DocumentTypeInfo(**response.json())
                assert doc_type_info.name == "Report"
                assert doc_type_info.field_count == 2
                assert "performance_ratio_pct" in doc_type_info.fields


# =============================================================================
# List All Document Types Endpoint Tests
# =============================================================================


class TestListAllDocumentTypesEndpoint:
    """Test cases for GET /api/v1/schemas/document-types endpoint."""

    def test_list_all_document_types_success(self, client, mock_all_schemas):
        """Test listing all document types and schemas."""
        with patch("ddx.api.main.get_all_schemas_info", return_value=mock_all_schemas):
            response = client.get("/api/v1/schemas/document-types")
            assert response.status_code == 200
            data = response.json()
            assert data == mock_all_schemas
            assert "Company Information" in data
            assert "Project Simulation Report" in data["Company Information"]

    def test_list_all_document_types_empty(self, client):
        """Test when no schemas are available."""
        with patch("ddx.api.main.get_all_schemas_info", return_value={}):
            response = client.get("/api/v1/schemas/document-types")
            assert response.status_code == 200
            assert response.json() == {}

    def test_list_all_document_types_complex_structure(self, client):
        """Test with a complex nested schema structure."""
        complex_schemas = {
            "Category1": {
                "DocType1": {"field1": {"type": "str"}, "field2": {"type": "int"}},
                "DocType2": {"field3": {"type": "float"}},
            },
            "Category2": {
                "DocType3": {"field4": {"type": "bool"}},
            },
        }
        with patch("ddx.api.main.get_all_schemas_info", return_value=complex_schemas):
            response = client.get("/api/v1/schemas/document-types")
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 2
            assert len(data["Category1"]) == 2
            assert len(data["Category1"]["DocType1"]) == 2


# =============================================================================
# Integration Tests
# =============================================================================


class TestSchemaDiscoveryIntegration:
    """Integration tests for schema discovery endpoints."""

    def test_full_schema_discovery_flow(
        self, client, mock_categories, mock_category_doc_types, mock_document_type_fields
    ):
        """Test the complete flow of discovering schemas."""
        print(f"\n{'='*80}")
        print("TEST: test_full_schema_discovery_flow (INTEGRATION)")
        print(f"Input mock_categories: {mock_categories}")
        print(f"Input mock_category_doc_types: {mock_category_doc_types}")
        print(f"Input mock_document_type_fields: {mock_document_type_fields}")

        with patch("ddx.api.main.get_supported_categories", return_value=mock_categories):
            with patch(
                "ddx.api.main.get_document_types_for_category_api",
                return_value=mock_category_doc_types,
            ):
                with patch(
                    "ddx.api.main.get_fields_for_document_type",
                    return_value=mock_document_type_fields,
                ):
                    with patch("ddx.api.main._get_top_level_for_document_type") as mock_top_level:
                        mock_top_level.return_value.value = "Technical"
                        with patch(
                            "ddx.api.main.CATEGORY_DOCUMENT_TYPES",
                            {
                                "Company Information": mock_category_doc_types,
                                "Technical": mock_category_doc_types,
                            },
                        ):

                            # Step 1: Get all categories
                            print("\n--- Step 1: Get all categories ---")
                            response = client.get("/api/v1/schemas/categories")
                            print(f"Response status: {response.status_code}")
                            categories = response.json()
                            print(f"Categories found: {len(categories)}")
                            print(f"Category names: {[c['name'] for c in categories]}")
                            assert response.status_code == 200
                            assert len(categories) == 3

                            # Step 2: Get specific category
                            print("\n--- Step 2: Get specific category ---")
                            category_name = categories[0]["name"]
                            url = f"/api/v1/schemas/categories/{category_name.replace(' ', '%20')}"
                            print(f"Request URL: {url}")
                            response = client.get(url)
                            print(f"Response status: {response.status_code}")
                            print(f"Category data: {response.json()}")
                            assert response.status_code == 200

                            # Step 3: Get document type schema
                            print("\n--- Step 3: Get document type schema ---")
                            doc_type = mock_category_doc_types[0]
                            url = f"/api/v1/schemas/document-types/{doc_type.replace(' ', '%20')}"
                            print(f"Request URL: {url}")
                            response = client.get(url)
                            print(f"Response status: {response.status_code}")
                            schema = response.json()
                            print(f"Schema fields: {list(schema['fields'].keys())}")
                            assert response.status_code == 200
                            assert "fields" in schema
                            assert "performance_ratio_pct" in schema["fields"]
                            print("\n✓ All integration test assertions passed")
                            print(f"{'='*80}\n")


# =============================================================================
# Validation Service Helpers
# =============================================================================


class TestValidationDocumentTypeNormalization:
    """Regression tests for tolerant document_type matching."""

    def test_resolve_document_type_accepts_snake_case_alias(self):
        doc_type, top_level = _resolve_document_type("tax_compliance_certificate")
        assert doc_type == "Tax Compliance Certificate"
        assert top_level == "Company Financials"

    def test_resolve_document_type_accepts_case_insensitive_alias(self):
        doc_type, top_level = _resolve_document_type("tax compliance certificate")
        assert doc_type == "Tax Compliance Certificate"
        assert top_level == "Company Financials"
