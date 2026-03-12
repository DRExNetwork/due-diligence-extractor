from __future__ import annotations

import argparse
import json
import os
import requests
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type

from pydantic import BaseModel, ConfigDict, Field
from enum import Enum

from ddx.classification.classifier import DocumentCategory
from ddx.classification.categories import (
    TopLevelCategory,
    DocumentType,
    ClassificationResult,
    # Company Information
    LegalInformation,
    ShareholderStructure,
    LegalRepresentation,
    # Company Financials
    FinancialStatementsData,
    IncomeTaxFilingsData,
    CashFlowStatementsData,
    TaxComplianceCertificateData,
    EconomicalOfferBOQData,
    EnergyConsumptionBillsData,
    PYDANTIC_MODELS as CATEGORY_PYDANTIC_MODELS,
    DOCUMENT_TYPE_DESCRIPTIONS,
    DOCUMENT_TYPE_TO_TOP_LEVEL,
    ESHSESMSPoliciesData,
    QAQCCommissioningData,
    HRManualCodeOfConductData,
    EnvironmentalLicenceEIAData,
    EmergencyResponseSecurityPlanData,
    SiteLegalStatusSummaryData,
    LiensCertificateData,
    NonOverlapProtectedAreasCertificateData,
    HRPolicyCodeOfConductData,
    ElectricalUtilityFeasibilityReportData,
    LandUsePermitData,
    # Company Experience
    ProjectAcceptanceCertificatesData,
    OAMContractData,
    normalize_extracted_document,
)

from dotenv import load_dotenv

load_dotenv()
# =============================================================================
# Constants
# =============================================================================

LEGACY_API_MAX_PAGES = 50  # Legacy API supports up to 50 pages
LEGACY_API_URL = "https://api.va.landing.ai/v1/tools/agentic-document-analysis"
LEGACY_API_URL_EU = "https://api.va.eu-west-1.landing.ai/v1/tools/agentic-document-analysis"
SUPPORTED_INPUT_EXTENSIONS = {".pdf", ".docx", ".png", ".jpeg", ".jpg"}


_EQUIPMENT_RESEARCH_ONLY_FIELDS = {
    "module_bloomberg",
    "module_certifications",
    "module_certificate_evidence",
    "module_factory_test_date",
    "module_test_evidence",
    "inverter_bloomberg",
    "inverter_certifications",
    "inverter_certificate_evidence",
    "inverter_anti_island_test_date",
    "inverter_test_evidence",
}


def _is_equipment_sheets_document_type(document_type: str) -> bool:
    return (
        document_type or ""
    ).strip().lower() == DocumentType.PROJECT_DATA_EQUIPMENT_SHEETS.value.strip().lower()


def _remove_schema_fields(schema: Any, field_names: set[str]) -> Any:
    """Remove fields from a JSON schema represented as dict or JSON string."""
    if isinstance(schema, str):
        try:
            parsed = json.loads(schema)
        except Exception:
            return schema

        filtered = _remove_schema_fields(parsed, field_names)

        try:
            return json.dumps(filtered)
        except Exception:
            return schema

    if not isinstance(schema, dict):
        return schema

    properties = schema.get("properties")
    if isinstance(properties, dict):
        for field_name in field_names:
            properties.pop(field_name, None)

    required = schema.get("required")
    if isinstance(required, list):
        schema["required"] = [name for name in required if name not in field_names]

    return schema


# =============================================================================
# PDF Page Count Utility
# =============================================================================


def get_pdf_page_count(pdf_path: Path) -> int:
    """
    Get the number of pages in a PDF file.

    Tries multiple methods in order of preference:
    1. PyMuPDF (fitz) - fastest and most reliable
    2. pypdf - pure Python fallback
    3. pdfplumber - another fallback

    Args:
        pdf_path: Path to the PDF file

    Returns:
        Number of pages in the PDF

    Raises:
        RuntimeError: If no PDF library is available or file cannot be read
    """
    # Try PyMuPDF first (fastest)
    try:
        import fitz  # PyMuPDF

        with fitz.open(pdf_path) as doc:
            return len(doc)
    except ImportError:
        pass
    except Exception as e:
        print(f"  ⚠️  PyMuPDF failed: {e}")

    # Try pypdf
    try:
        from pypdf import PdfReader

        reader = PdfReader(pdf_path)
        return len(reader.pages)
    except ImportError:
        pass
    except Exception as e:
        print(f"  ⚠️  pypdf failed: {e}")

    # Try pdfplumber
    try:
        import pdfplumber

        with pdfplumber.open(pdf_path) as pdf:
            return len(pdf.pages)
    except ImportError:
        pass
    except Exception as e:
        print(f"  ⚠️  pdfplumber failed: {e}")

    raise RuntimeError(
        "Cannot count PDF pages. Install one of: PyMuPDF (pip install pymupdf), "
        "pypdf (pip install pypdf), or pdfplumber (pip install pdfplumber)"
    )


def should_use_legacy_api(
    pdf_path: Path, max_pages: int = LEGACY_API_MAX_PAGES
) -> Tuple[bool, int]:
    """
    Determine if the legacy API should be used based on page count.

    Args:
        pdf_path: Path to the PDF file
        max_pages: Maximum pages for legacy API (default: 50)

    Returns:
        Tuple of (should_use_legacy, page_count)
    """
    try:
        page_count = get_pdf_page_count(pdf_path)
        return page_count <= max_pages, page_count
    except Exception as e:
        print(f"  ⚠️  Could not count pages ({e}), defaulting to SDK API")
        return False, -1


# =============================================================================
# SDK Client Setup
# =============================================================================


def _get_client():
    """Get LandingAI ADE client with API key from environment."""
    try:
        from landingai_ade import LandingAIADE
    except ImportError as e:
        raise RuntimeError(
            "Missing dependency 'landingai-ade'. Install with: pip install landingai-ade"
        ) from e

    api_key = os.environ.get("VISION_AGENT_API_KEY") or os.environ.get("VA_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing API key. Set VISION_AGENT_API_KEY or VA_API_KEY environment variable."
        )

    return LandingAIADE(apikey=api_key)


def _get_api_key() -> str:
    """Get API key from environment."""
    api_key = os.environ.get("VISION_AGENT_API_KEY") or os.environ.get("VA_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing API key. Set VISION_AGENT_API_KEY or VA_API_KEY environment variable."
        )
    return api_key


# =============================================================================
# Legacy API Functions (Parse + Classify only)
# =============================================================================


def _build_legacy_classification_schema(
    top_level_category: Optional[TopLevelCategory] = None,
) -> Dict[str, Any]:
    """
    Build JSON schema for classification using legacy API.

    Args:
        top_level_category: Optional top-level category to filter document types

    Returns:
        JSON schema dict for classification
    """
    if top_level_category:
        # Get document types for this category
        doc_types = [
            doc_type
            for doc_type, category in DOCUMENT_TYPE_TO_TOP_LEVEL.items()
            if category == top_level_category
        ]
        enum_values = [dt.value for dt in doc_types]
        # Always include UNCATEGORIZED as fallback
        if DocumentType.UNCATEGORIZED.value not in enum_values:
            enum_values.append(DocumentType.UNCATEGORIZED.value)
    else:
        # Use all document types
        enum_values = [dt.value for dt in DocumentType]

    # Build descriptions for better classification
    descriptions = []
    for dt in DocumentType:
        if dt.value in enum_values:
            desc = DOCUMENT_TYPE_DESCRIPTIONS.get(dt, "")
            if desc:
                descriptions.append(f"- {dt.value}: {desc}")

    description_text = "\n".join(descriptions) if descriptions else "Document type classification"

    return {
        "type": "object",
        "properties": {
            "document_type": {
                "type": "string",
                "enum": enum_values,
                "description": f"The document type. Choose from:\n{description_text}",
            },
            "confidence": {
                "type": "number",
                "description": "Confidence score for the classification (0.0 to 1.0)",
            },
            "reasoning": {
                "type": "string",
                "description": "Brief explanation of why this classification was chosen",
            },
        },
        "required": ["document_type"],
    }


def legacy_api_parse_and_classify(
    pdf_path: Path,
    top_level_category: Optional[TopLevelCategory] = None,
    *,
    use_eu_endpoint: bool = False,
) -> Tuple[str, str, Dict[str, Any]]:
    """
    Use legacy API to parse and classify in a single call (cost-effective for ≤50 pages).

    The legacy API combines parsing and extraction in a single call.
    We use it only for classification, then use SDK for field extraction.

    Args:
        pdf_path: Path to the PDF file
        top_level_category: Optional top-level category to filter classification
        use_eu_endpoint: Use EU endpoint instead of US

    Returns:
        Tuple of (document_type, markdown_content, classification_raw)
    """
    api_key = _get_api_key()
    headers = {"Authorization": f"Bearer {api_key}"}
    url = LEGACY_API_URL_EU if use_eu_endpoint else LEGACY_API_URL

    pdf_name = pdf_path.name

    # Build classification schema
    classification_schema = _build_legacy_classification_schema(top_level_category)

    print(f"  [Legacy API] Parsing and classifying document...")
    with open(pdf_path, "rb") as f:
        files = [("pdf", (pdf_name, f, "application/pdf"))]
        payload = {"fields_schema": json.dumps(classification_schema)}
        response = requests.post(url, headers=headers, files=files, data=payload)

    if response.status_code != 200:
        raise RuntimeError(f"Legacy API failed: {response.status_code} - {response.text}")

    response_data = response.json()
    data = response_data.get("data", {})

    # Extract classification result
    extracted_schema = data.get("extracted_schema", {})
    doc_type = extracted_schema.get("document_type", DocumentType.UNCATEGORIZED.value)

    # Get markdown from response
    markdown_content = data.get("markdown", "")

    classification_raw = {
        "extraction": extracted_schema,
        "extraction_metadata": data.get("chunks", []),
        "top_level_category": top_level_category.value if top_level_category else None,
        "api_used": "legacy",
    }

    print(f"  → Classified as: {doc_type}")

    return doc_type, markdown_content, classification_raw


# =============================================================================
# Classification Schema (Pydantic)
# =============================================================================


class DocumentTypeEnum(str, Enum):
    """Document type enum matching DocumentCategory values."""

    PROJECT_SIMULATION_REPORT = "Project Simulation Report"
    PROJECT_DATA_EQUIPMENT_SHEETS = (
        "Project Data Main Equipment Sheets (Solar Modules, Inverters, Mounting Structure)"
    )
    PROJECT_BASIC_ENGINEERING = "Project Basic Engineering"
    PROJECT_VISIT_REPORT = "Project Visit Report"
    PROJECT_LAYOUT = "Project Layout"
    KMZ_POLIGON = "KMZ Poligon"
    CABLE_SIZING_CALCULATION = "Cable Sizing Calculation Report"
    GROUNDING_SYSTEM_DIAGRAM = "Grounding System"
    UNCATEGORIZED = "Uncategorized Document"


class ClassificationResult(BaseModel):
    """Schema for document classification."""

    model_config = ConfigDict(extra="forbid")

    document_type: DocumentTypeEnum = Field(
        description="The category/type of this document based on its content, structure, and purpose."
    )


# =============================================================================
# Extraction Schemas (Pydantic) - Matching your existing models
# =============================================================================


class MonthlyStatistic(BaseModel):
    """Monthly production statistics from simulation report."""

    model_config = ConfigDict(extra="forbid")

    month: str = Field(description="Month name (January, February, etc.)")
    egrid_monthly_mwh: Optional[float] = Field(
        default=None,
        description="E_Grid - Energy injected into grid for the month in MWh",
    )
    egrid_daily_avg_mwh: Optional[float] = Field(
        default=None,
        description="Daily average energy injected into grid in MWh. Calculate as E_Grid divided by days in month (Jan=31, Feb=28, Mar=31, etc.)",
    )
    pr_pct: Optional[float] = Field(
        default=None, description="Performance Ratio for the month in %"
    )


class ProjectSimulationReportData(BaseModel):
    """Schema for Project Simulation Report (Section 1.5) - PVsyst/Helioscope."""

    model_config = ConfigDict(extra="forbid")

    project_name: str = Field(description="Project name (e.g., 'Biogemar - Santa Elena')")
    geographical_coordinates: Optional[str] = Field(
        default=None,
        description='Geographical coordinates (e.g., "-02°06\'03", -080°44\'47"")',
    )
    elevation_m: Optional[float] = Field(default=None, description="Elevation in meters")
    land_cover: Optional[str] = Field(
        default=None, description="Land cover type (water bodies, land, rooftop, etc.)"
    )
    specific_pv_output_kwh_kwp: Optional[float] = Field(
        default=None,
        description="Annual Specific Photovoltaic Power Output in kWh/kWp",
    )
    total_pv_energy_mwh: float = Field(description="Total photovoltaic energy output in MWh")
    performance_ratio_pct: float = Field(description="Performance ratio in %")
    air_temperature_c: Optional[float] = Field(
        default=None, description="Air temperature in Celsius"
    )
    total_pv_power_mwp: float = Field(description="Total photovoltaic power output in MWp")
    monthly_statistics: Optional[List[MonthlyStatistic]] = Field(
        default=None,
        description="Monthly statistics for 12 months with PVOUT daily avg, monthly sum, and PR",
    )
    cumulative_degradation_pct: Optional[float] = Field(
        default=None,
        description="Cumulative Degradation Rate in percent, also known as Module Degradation Loss or rate of Degradation  - it can be present in years and we might need to divide to get the average. ",
    )
    shadow_loss_pct: Optional[float] = Field(default=None, description="Shadow loss in %")
    p90_value: Optional[float] = Field(
        default=None,
        description="P90 annual production probability value in MWh - production level with 90% probability of exceedance",
    )
    p95_value: Optional[float] = Field(
        default=None,
        description="P95 annual production probability value in MWh - production level with 95% probability of exceedance",
    )


class BloombergResearchEvidence(BaseModel):
    """Web-research evidence from the latest Bloomberg list for the current year."""

    model_config = ConfigDict(extra="forbid")

    rating: Optional[str] = Field(
        default=None,
        description="Qualification/rating found in latest Bloomberg evidence for current year (for example AAA, AA, A)",
    )
    source: Optional[str] = Field(
        default=None,
        description="Source URL supporting the Bloomberg qualification/rating",
    )


class CertificateResearchEvidence(BaseModel):
    """Web-research evidence for certificate name, source, and validity date."""

    model_config = ConfigDict(extra="forbid")

    standard_code: str = Field(
        description="Certificate standard code being researched (for example IEC 61215, IEC 62109)",
    )
    certificate_name: Optional[str] = Field(
        default=None,
        description="Certificate/report name found for the standard",
    )
    source: Optional[str] = Field(
        default=None,
        description="Source URL for the certificate evidence",
    )
    validity_date: Optional[str] = Field(
        default=None,
        description="Extracted certificate validity date in YYYY-MM-DD (null if not found)",
    )


class TestResearchEvidence(BaseModel):
    """Web-research evidence for module/inverter test reports."""

    model_config = ConfigDict(extra="forbid")

    test_name: str = Field(
        description="Target test name from research query (for example Fabric report test or Anti-islanding test)",
    )
    source: Optional[str] = Field(
        default=None,
        description="Source URL for the test report evidence",
    )
    test_date: Optional[str] = Field(
        default=None,
        description="Extracted test date in YYYY-MM-DD (null if not found)",
    )


class ProjectDataMainEquipmentSheetsData(BaseModel):
    """Schema for Project Data Main Equipment Sheets (Section 1.7)."""

    model_config = ConfigDict(extra="forbid")

    # Solar Modules
    module_brand: str = Field(description="Solar module brand (e.g., JA Solar)")
    module_model: str = Field(description="Solar module model (e.g., JAM72S30-540/MR)")
    module_capacity_wdc: Optional[float] = Field(default=None, description="Module capacity in Wdc")
    module_efficiency_pct: Optional[float] = Field(
        default=None, description="Module efficiency in %"
    )
    module_dimensions_mm: Optional[str] = Field(default=None, description="Module dimensions in mm")
    module_technical_warranty_years: Optional[int] = Field(
        default=None, description="Technical warranty in years"
    )
    module_linear_degradation_warranty_years: Optional[int] = Field(
        default=None, description="Linear degradation warranty in years"
    )
    module_degradation_rate_year1_pct: Optional[float] = Field(
        default=None,
        description="Module degradation rate for year 1 in % - derived from linear degradation curve in datasheet",
    )
    module_degradation_rate_year2_onwards_pct: Optional[float] = Field(
        default=None,
        description="Module degradation rate for year 2 onwards in % - derived from linear degradation curve in datasheet",
    )
    module_bloomberg: Optional[BloombergResearchEvidence] = Field(
        default=None,
        description="Latest/current-year Bloomberg research evidence for module_brand",
    )
    module_certificate_evidence: Optional[List[CertificateResearchEvidence]] = Field(
        default=None,
        description="Detailed module certificate evidence from latest research for IEC 61215, IEC 61730, IEC TS 62804 (PID), IEC 62716, and IEC 61701",
    )
    module_test_evidence: Optional[List[TestResearchEvidence]] = Field(
        default=None,
        description="Detailed module test evidence from latest research (Fabric report test)",
    )

    # Inverter
    inverter_brand: Optional[str] = Field(default=None, description="Inverter brand")
    inverter_model: Optional[str] = Field(default=None, description="Inverter model")
    inverter_ac_capacity_kw: Optional[float] = Field(default=None, description="AC capacity in kW")
    inverter_dc_capacity_kw: Optional[float] = Field(default=None, description="DC capacity in kW")
    inverter_efficiency_pct: Optional[float] = Field(
        default=None, description="Inverter efficiency in %"
    )
    inverter_mppt_voltage_range_v: Optional[str] = Field(
        default=None, description="MPPT voltage range in V"
    )
    inverter_mppt_current_range_a: Optional[str] = Field(
        default=None, description="MPPT current range in A"
    )
    inverter_type: Optional[str] = Field(
        default=None, description="Inverter type (On grid, Off grid, Hybrid)"
    )
    inverter_technical_warranty_years: Optional[int] = Field(
        default=None, description="Inverter warranty in years"
    )
    inverter_bloomberg: Optional[BloombergResearchEvidence] = Field(
        default=None,
        description="Latest/current-year Bloomberg research evidence for inverter_brand",
    )
    inverter_certificate_evidence: Optional[List[CertificateResearchEvidence]] = Field(
        default=None,
        description="Detailed inverter certificate evidence from latest research for IEC 62109, IEC 61727, and IEC 61000",
    )
    inverter_test_evidence: Optional[List[TestResearchEvidence]] = Field(
        default=None,
        description="Detailed inverter test evidence from latest research (Anti-islanding test)",
    )


class ProjectVisitReportData(BaseModel):
    """Schema for Project Visit Report (Section 1.9) - Site Characteristics."""

    model_config = ConfigDict(extra="forbid")

    site_description: str = Field(description="Site description")
    installation_area_m2: float = Field(description="Area for project installation in m²")
    installation_location: str = Field(
        description="Location of area available for installation (Rooftop, Land, Floating, etc.)"
    )


class ProjectLayoutData(BaseModel):
    """Schema for Project Layout (Section 1.10) - Technology Sizing."""

    model_config = ConfigDict(extra="forbid")

    nominal_capacity_kw: float = Field(description="Nominal capacity in kW")
    peak_capacity_kwp: float = Field(description="Peak capacity in kWp")
    solar_modules_quantity: int = Field(description="Solar modules quantity")
    solar_module_brand: str = Field(description="Solar module brand (e.g., JA Solar)")
    solar_module_model: str = Field(description="Solar module model (e.g., JAM72S30-540/MR)")
    inverter_brand: Optional[str] = Field(default=None, description="Inverter brand")
    inverter_model: Optional[str] = Field(default=None, description="Inverter model")
    inverters_quantity: int = Field(description="Inverters quantity")
    strings_per_inverter: Optional[int] = Field(
        default=None, description="Strings per inverter quantity"
    )
    module_orientation: Optional[str] = Field(default=None, description="Solar module orientation")


class GroundingSystemSingleLineDiagramData(BaseModel):
    """Schema for Grounding System (Section 1.13) - Grounding Criteria."""

    model_config = ConfigDict(extra="forbid")

    system_type: str = Field(description="Type of grounding system")
    resistance_value_ohm: float = Field(
        description="Ground resistance value in Ohms (Ω). Extract the exact decimal value, do not round."
    )


class ProjectBasicEngineeringData(BaseModel):
    """Schema for Project Basic Engineering"""

    model_config = ConfigDict(extra="forbid")

    system_type: str = Field(description="Type of system (three-phase 3F, one-phase 1F)")
    voltage_mains_v: float = Field(description="Voltage mains in V (220, 440, etc.)")
    load_description: str = Field(
        description="Description of the load (Industrial load, commercial load, motors, etc.)"
    )
    load_capacity_kw: float = Field(description="Load capacity in kW")
    annual_load_energy_kwh: Optional[float] = Field(
        default=None, description="Annual load consumed energy in kWh"
    )
    structure_type: Optional[str] = Field(
        default=None,
        description=(
            "Type of mounting structure (anodized aluminum structure, coplanar, "
            "land mounting, carports mounting on a metal roof, etc.)"
        ),
    )
    structure_material: Optional[str] = Field(
        default=None,
        description="Material of the mounting structure (Anodized Aluminum, Hot deep Galvanized, etc.)",
    )
    structure_warranty_years: Optional[int] = Field(
        default=None,
        description="Structural warranty against corrosion in years",
    )
    # project_visitation_report: Optional[ProjectVisitReportData] = Field(
    #     default=None, description="Site visit information"
    # )

    site_description: str = Field(description="Site description")
    installation_area_m2: float = Field(description="Area for project installation in m²")
    installation_location: str = Field(
        description="Location of area available for installation (Rooftop, Land, Floating, etc.)"
    )
    # project_layout: Optional[ProjectLayoutData] = Field(
    #     default=None,
    #     description="Layout and sizing information",
    # )

    nominal_capacity_kw: float = Field(description="Nominal capacity in kW")
    peak_capacity_kwp: float = Field(description="Peak capacity in kWp")
    solar_modules_quantity: int = Field(description="Solar modules quantity")
    solar_module_brand: str = Field(description="Solar module brand (e.g., JA Solar)")
    solar_module_model: str = Field(description="Solar module model (e.g., JAM72S30-540/MR)")
    inverter_brand: Optional[str] = Field(default=None, description="Inverter brand")
    inverter_model: Optional[str] = Field(default=None, description="Inverter model")
    inverters_quantity: int = Field(description="Inverters quantity")
    strings_per_inverter: Optional[int] = Field(
        default=None, description="Strings per inverter quantity"
    )
    module_orientation: Optional[str] = Field(default=None, description="Solar module orientation")
    # grouding_system: Optional[GroundingSystemSingleLineDiagramData] = Field(
    #     default=None,
    #     description="Grounding system information",
    # )
    system_type: str = Field(description="Type of grounding system")
    resistance_value_ohm: float = Field(
        description="Ground resistance value in Ohms (Ω). Extract the exact decimal value, do not round."
    )


class KmzPoligonData(BaseModel):
    """Schema for KMZ Polygon (Section 1.11) - Area of Intervention."""

    model_config = ConfigDict(extra="forbid")

    polygon_area_m2: float = Field(description="Polygon surface area in m² from Google Earth")


class CableEntry(BaseModel):
    """Individual cable sizing entry for DC/AC connections."""

    model_config = ConfigDict(extra="forbid")

    connection_type: str = Field(
        description="Type of circuit or connection. Allowed values: 'DC load connection' or 'AC load connection'"
    )
    sizing: str = Field(description="Conductor sizing (e.g., '35 mm²' or '10 AWG')")
    cable_type: str = Field(description="Cable type (e.g., 'XLPE type')")
    voltage_drop_pct: float = Field(description="Voltage drop in %")
    installation: Optional[str] = Field(default=None, description="Installation method")
    total_length_m: Optional[float] = Field(default=None, description="Total length in meters")


class CableSizingCalculationReportData(BaseModel):
    """Schema for Cable Sizing Calculation Report (Section 1.12)."""

    model_config = ConfigDict(extra="forbid")

    cable_entries: List[CableEntry] = Field(
        description="Table of cable sizing for DC load and AC load connections"
    )


class UncategorizedDocumentData(BaseModel):
    """Schema for documents that don't match any predefined category."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(description="Brief summary of what the document contains")
    why_uncategorized: str = Field(
        description="Why the document does not match any predefined category"
    )


# =============================================================================
# Model Registry
# =============================================================================

PYDANTIC_MODELS: Dict[str, Type[BaseModel]] = {
    # Company Information (from categories.py)
    DocumentType.CERTIFICATE_OF_LEGAL_EXISTENCE.value: LegalInformation,
    DocumentType.SHAREHOLDERS_DECLARATION.value: ShareholderStructure,
    DocumentType.LEGAL_REPRESENTATIVE_APPOINTMENT.value: LegalRepresentation,
    DocumentType.ENERGY_CONSUMPTION_BILLS.value: EnergyConsumptionBillsData,
    # Company Financials (from categories.py)
    DocumentType.FINANCIAL_STATEMENTS.value: FinancialStatementsData,
    DocumentType.INCOME_TAX_FILINGS.value: IncomeTaxFilingsData,
    DocumentType.CASH_FLOW_STATEMENTS.value: CashFlowStatementsData,
    DocumentType.TAX_COMPLIANCE_CERTIFICATE.value: TaxComplianceCertificateData,
    DocumentType.ECONOMICAL_OFFER_BOQ.value: EconomicalOfferBOQData,  # NEW
    # Technical (defined in this file)
    DocumentType.PROJECT_SIMULATION_REPORT.value: ProjectSimulationReportData,
    DocumentType.PROJECT_DATA_EQUIPMENT_SHEETS.value: ProjectDataMainEquipmentSheetsData,
    DocumentType.PROJECT_BASIC_ENGINEERING.value: ProjectBasicEngineeringData,
    DocumentType.PROJECT_VISIT_REPORT.value: ProjectVisitReportData,
    DocumentType.PROJECT_LAYOUT.value: ProjectLayoutData,
    DocumentType.KMZ_POLIGON.value: KmzPoligonData,
    DocumentType.CABLE_SIZING_CALCULATION.value: CableSizingCalculationReportData,
    DocumentType.GROUNDING_SYSTEM_DIAGRAM.value: GroundingSystemSingleLineDiagramData,
    DocumentType.UNCATEGORIZED.value: UncategorizedDocumentData,
    # ESG (from categories.py)
    DocumentType.ENVIRONMENTAL_AND_SOCIAL_MANAGEMENT_PLAN.value: ESHSESMSPoliciesData,
    DocumentType.QAQC_COMMISSIONING_PROCEDURES.value: QAQCCommissioningData,
    DocumentType.INDUSTRIAL_SAFETY_PLAN.value: HRManualCodeOfConductData,
    DocumentType.ENVIRONMENTAL_LICENCE_EIA.value: EnvironmentalLicenceEIAData,
    DocumentType.EMERGENCY_RESPONSE_SECURITY_PLAN.value: EmergencyResponseSecurityPlanData,
    DocumentType.SITE_LEGAL_STATUS_SUMMARY.value: SiteLegalStatusSummaryData,
    DocumentType.LIENS_CERTIFICATE.value: LiensCertificateData,
    DocumentType.NON_OVERLAP_WITH_PROTECTED_AREAS_CERTIFICATE.value: NonOverlapProtectedAreasCertificateData,
    DocumentType.HR_POLICY_CODE_OF_CONDUCT.value: HRPolicyCodeOfConductData,
    DocumentType.LAND_USE_PERMIT.value: LandUsePermitData,
    # Permits (from categories.py)
    DocumentType.ELECTRICAL_UTILITY_FEASIBILITY_REPORT.value: ElectricalUtilityFeasibilityReportData,
    # Company Experience (from categories.py)
    DocumentType.PROJECT_ACCEPTANCE_CERTIFICATES.value: ProjectAcceptanceCertificatesData,
    DocumentType.OAM_CONTRACTS.value: OAMContractData,
}

# =============================================================================
# Core Functions (All using SDK)
# =============================================================================


class CachedParseResponse:
    """Simple wrapper for cached parse response data."""

    def __init__(self, data: Dict[str, Any], markdown: str):
        self._data = data
        self.markdown = markdown
        self.chunks = data.get("chunks", [])

    def model_dump(self) -> Dict[str, Any]:
        return {**self._data, "markdown": self.markdown}

    def dict(self) -> Dict[str, Any]:
        return self.model_dump()


class LegacyParseResponse:
    """Wrapper for legacy API parse response to match SDK response structure."""

    def __init__(self, markdown: str, chunks: List[Any] = None):
        self.markdown = markdown
        self.chunks = chunks or []

    def model_dump(self) -> Dict[str, Any]:
        return {"markdown": self.markdown, "chunks": self.chunks}

    def dict(self) -> Dict[str, Any]:
        return self.model_dump()


def _find_cached_markdown(stem: str, search_dir: Path) -> Tuple[Optional[Path], Optional[Path]]:
    """
    Find cached markdown and parse.json files for a given document stem.

    Searches recursively in the search_dir (to handle category subfolders).

    Args:
        stem: Document stem (sanitized filename without extension)
        search_dir: Directory to search in

    Returns:
        (markdown_path, parse_json_path) or (None, None) if not found
    """
    if not search_dir.exists():
        return None, None

    # Search in all subdirectories (category folders)
    for md_path in search_dir.rglob(f"{stem}.md"):
        parse_json_path = md_path.parent / f"{stem}.parse.json"
        return md_path, parse_json_path if parse_json_path.exists() else None

    return None, None


def parse_document(
    document_path: Path,
    *,
    model: Optional[str] = None,
    cache_dir: Optional[Path] = None,
    force: bool = False,
) -> Tuple[str, Any, Optional[Path], Optional[Path]]:
    """
    Parse a document using LandingAI SDK with caching support.

    Args:
        document_path: Path to the PDF document
        model: Parse model to use (default: dpt-2-latest)
        cache_dir: Directory to check for cached markdown (optional)
        force: Force re-parsing even if cached markdown exists

    Returns:
        (markdown_content, parse_response, cached_md_path, cached_parse_json_path)
        - If cache was used: cached_md_path and cached_parse_json_path will be set
        - If freshly parsed: cached_md_path and cached_parse_json_path will be None
    """
    stem = _safe_stem(document_path)

    # Check for cached markdown if cache_dir is provided and force is False
    if cache_dir and not force:
        cached_md_path, cached_parse_json_path = _find_cached_markdown(stem, cache_dir)
        if cached_md_path and cached_md_path.exists():
            print(f"  Using cached markdown: {cached_md_path}")
            markdown_content = cached_md_path.read_text(encoding="utf-8")

            # Load cached parse response if available
            parse_response = None
            if cached_parse_json_path and cached_parse_json_path.exists():
                try:
                    parse_data = json.loads(cached_parse_json_path.read_text(encoding="utf-8"))
                    parse_response = CachedParseResponse(parse_data, markdown_content)
                except Exception as e:
                    print(f"  ⚠️  Could not load cached parse.json: {e}")
                    parse_response = CachedParseResponse({}, markdown_content)
            else:
                parse_response = CachedParseResponse({}, markdown_content)

            # Return with cached paths to indicate cache was used
            return markdown_content, parse_response, cached_md_path, cached_parse_json_path

    # No cache found or force=True, call the API
    client = _get_client()
    parse_model = model or os.getenv("LANDING_PARSE_MODEL", "dpt-2-latest")

    print(f"  [SDK] Parsing document with model: {parse_model}")
    response = client.parse(document=document_path, model=parse_model)

    # Return None for cached paths to indicate fresh parse
    return response.markdown or "", response, None, None


def classify_from_markdown(
    markdown_content: str,
    *,
    model: Optional[str] = None,
    max_chars: int = 80000,
) -> Tuple[str, Dict[str, Any]]:
    """
    Classify a document using its markdown content via SDK extract.

    Args:
        markdown_content: Markdown content from parse
        model: Extract model to use
        max_chars: Max characters to use for classification (default: 80k)

    Returns:
        (document_type, raw_response)
    """
    try:
        from landingai_ade.lib import pydantic_to_json_schema
    except ImportError as e:
        raise RuntimeError(
            "Missing dependency 'landingai-ade'. Install with: pip install landingai-ade"
        ) from e

    client = _get_client()
    extract_model = model or os.getenv("LANDING_EXTRACT_MODEL", "extract-latest")

    # Truncate markdown for classification (usually first portion is enough)
    truncated_markdown = markdown_content

    # Convert classification schema to JSON schema
    schema = pydantic_to_json_schema(ClassificationResult)

    print(f"  [SDK] Classifying document with model: {extract_model}")
    response = client.extract(
        schema=schema,
        markdown=BytesIO(truncated_markdown.encode("utf-8")),
        model=extract_model,
    )

    # Extract document type from response
    extraction = getattr(response, "extraction", {}) or {}
    doc_type_value = extraction.get("document_type")

    # Handle enum value or string
    if doc_type_value:
        if isinstance(doc_type_value, str):
            doc_type = doc_type_value
        else:
            doc_type = doc_type_value
    else:
        doc_type = DocumentCategory.UNCATEGORIZED.value

    # Build raw response dict
    raw = {
        "extraction": extraction,
        "extraction_metadata": getattr(response, "extraction_metadata", None),
        "api_used": "sdk",
    }

    return doc_type, raw


def extract_fields(
    markdown_content: str,
    doc_type: str,
    *,
    model: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Extract fields from markdown content using the appropriate schema.

    Always uses SDK for extraction to benefit from latest features.

    Args:
        markdown_content: Markdown content from parse
        doc_type: Document type/category
        model: Extract model to use

    Returns:
        (extracted_data, raw_response)
    """
    try:
        from landingai_ade.lib import pydantic_to_json_schema
    except ImportError as e:
        raise RuntimeError(
            "Missing dependency 'landingai-ade'. Install with: pip install landingai-ade"
        ) from e

    model_cls = PYDANTIC_MODELS.get(doc_type)
    if not model_cls:
        return {}, {"skipped": True, "reason": f"No extraction schema for '{doc_type}'"}

    client = _get_client()
    extract_model = model or os.getenv("LANDING_EXTRACT_MODEL", "extract-latest")

    # Convert Pydantic model to JSON schema
    schema = pydantic_to_json_schema(model_cls)

    # Equipment research-only fields are filled by research enrichment.
    # Excluding them from SDK extraction avoids partial/null extraction values
    # overriding enriched values later in the pipeline.
    if _is_equipment_sheets_document_type(doc_type):
        schema = _remove_schema_fields(schema, _EQUIPMENT_RESEARCH_ONLY_FIELDS)

    print(f"  [SDK] Extracting fields with model: {extract_model}")
    response = client.extract(
        schema=schema,
        markdown=BytesIO(markdown_content.encode("utf-8")),
        model=extract_model,
    )

    # Get extraction result
    extraction = getattr(response, "extraction", {}) or {}

    # Validate with Pydantic model
    try:
        if hasattr(model_cls, "model_validate"):
            validated = model_cls.model_validate(extraction)
        else:
            validated = model_cls.parse_obj(extraction)

        if hasattr(validated, "model_dump"):
            extracted = validated.model_dump()
        else:
            extracted = validated.dict()
    except Exception as e:
        print(f"  ⚠️  Validation warning: {e}")
        extracted = extraction  # Use raw extraction if validation fails

    raw = {
        "extraction": extraction,
        "extraction_metadata": getattr(response, "extraction_metadata", None),
        "metadata": getattr(response, "metadata", None),
    }

    extracted, normalized_metadata = normalize_extracted_document(
        doc_type,
        extracted,
        raw.get("extraction_metadata"),
    )
    raw["extraction_metadata"] = normalized_metadata

    extracted_log = json.dumps(extracted, ensure_ascii=False, default=str)
    if len(extracted_log) > 3000:
        extracted_log = f"{extracted_log[:3000]}...(truncated)"
    print(f"  Extracted variables: {extracted_log}")

    return extracted, raw


def save_parse_outputs(
    markdown_content: str,
    parse_response: Any,
    output_dir: Path,
    stem: str,
) -> Tuple[Path, Path]:
    """
    Save markdown and parse JSON to disk.

    Returns:
        (markdown_path, parse_json_path)
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    md_path = output_dir / f"{stem}.md"
    parse_json_path = output_dir / f"{stem}.parse.json"

    # Save markdown
    md_path.write_text(markdown_content, encoding="utf-8")

    # Save parse response as JSON
    if hasattr(parse_response, "model_dump"):
        payload = parse_response.model_dump()
    elif hasattr(parse_response, "dict"):
        payload = parse_response.dict()
    else:
        payload = {"markdown": markdown_content}

    parse_json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    return md_path, parse_json_path


# =============================================================================
# Helper Functions
# =============================================================================


def _safe_stem(p: Path) -> str:
    """Sanitize filename stem."""
    stem = p.stem.strip().replace(" ", "_")
    return "".join(ch for ch in stem if ch.isalnum() or ch in ("_", "-", ".")) or "document"


def _sanitize_category_name(category: str) -> str:
    """Convert category name to safe folder name."""
    import re

    clean = re.sub(r"\s*\([^)]*\)", "", category)
    clean = re.sub(r"[^\w]+", "_", clean.strip())
    clean = clean.strip("_")
    return clean[:80] or "Unknown_Category"


def _unique_json_path(out_dir: Path, stem: str) -> Path:
    """Get unique JSON path to avoid overwrites."""
    base = out_dir / f"{stem}.json"
    if not base.exists():
        return base
    i = 1
    while True:
        p = out_dir / f"{stem}_{i}.json"
        if not p.exists():
            return p
        i += 1


def get_category_output_dirs(
    base_out_dir: Path,
    base_markdown_dir: Path,
    top_level_category: Optional[str],
    document_type: str,
) -> Tuple[Path, Path]:
    """
    Get category-specific output directories with hierarchical structure.

    Structure: base_dir / top_level_category / document_type /

    Args:
        base_out_dir: Base output directory for records
        base_markdown_dir: Base directory for markdown files
        top_level_category: Top-level category (e.g., "Company Information")
        document_type: Document type (e.g., "Certificate of Legal Existence")

    Returns:
        (records_dir, markdown_dir)
    """
    sanitized_doc_type = _sanitize_category_name(document_type)

    if top_level_category:
        sanitized_top_level = _sanitize_category_name(top_level_category)
        records_dir = base_out_dir / sanitized_top_level / sanitized_doc_type
        markdown_dir = base_markdown_dir / sanitized_top_level / sanitized_doc_type
    else:
        # Fallback: just use document type if no top-level category
        records_dir = base_out_dir / sanitized_doc_type
        markdown_dir = base_markdown_dir / sanitized_doc_type

    records_dir.mkdir(parents=True, exist_ok=True)
    markdown_dir.mkdir(parents=True, exist_ok=True)

    return records_dir, markdown_dir


def _iter_inputs(pdf: Optional[str], pdf_dir: Optional[str]) -> List[Path]:
    """Iterate over input files (pdf, docx, png, jpeg)."""
    if pdf:
        p = Path(pdf).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"Not found: {p}")
        if p.suffix.lower() not in SUPPORTED_INPUT_EXTENSIONS:
            raise ValueError(
                "Unsupported file type. Supported extensions: "
                f"{sorted(SUPPORTED_INPUT_EXTENSIONS)}"
            )
        return [p]

    if pdf_dir:
        d = Path(pdf_dir).expanduser().resolve()
        if not d.exists():
            raise FileNotFoundError(f"Not found: {d}")
        return sorted(
            [
                p
                for p in d.rglob("*")
                if p.is_file() and p.suffix.lower() in SUPPORTED_INPUT_EXTENSIONS
            ]
        )

    raise ValueError("Provide either --pdf or --pdf-dir")


def _is_already_processed(pdf_path: Path, base_out_dir: Path, base_markdown_dir: Path) -> bool:
    """
    Check if a PDF file has already been processed.

    Searches recursively in nested directory structure:
    base_dir / top_level_category / document_type / file

    Args:
        pdf_path: Path to the PDF file to check
        base_out_dir: Base directory for JSON output files
        base_markdown_dir: Base directory for markdown output files

    Returns:
        bool: True if both JSON record and markdown file exist
    """
    stem = _safe_stem(pdf_path)

    record_found = False
    if base_out_dir.exists():
        # Search recursively (handles top_level/doc_type/file structure)
        for json_file in base_out_dir.rglob(f"{stem}*.json"):
            if json_file.stem == stem or json_file.stem.startswith(f"{stem}_"):
                record_found = True
                break

    markdown_found = False
    if base_markdown_dir.exists():
        # Search recursively for markdown file
        for md_file in base_markdown_dir.rglob(f"{stem}.md"):
            markdown_found = True
            break

    return record_found and markdown_found


# =============================================================================
# Main Pipeline
# =============================================================================


def get_document_types_for_category(top_level: TopLevelCategory) -> List[DocumentType]:
    """Get all document types that belong to a top-level category."""
    return [
        doc_type
        for doc_type, category in DOCUMENT_TYPE_TO_TOP_LEVEL.items()
        if category == top_level
    ]


def build_classification_schema_for_category(top_level: TopLevelCategory) -> Type[BaseModel]:
    """
    Dynamically build a classification schema for a specific top-level category.
    Only includes document types that belong to that category.
    """
    doc_types = get_document_types_for_category(top_level)

    # Create enum with only relevant document types
    enum_members = {dt.name: dt.value for dt in doc_types}
    # Always include UNCATEGORIZED as fallback
    enum_members["UNCATEGORIZED"] = DocumentType.UNCATEGORIZED.value

    FilteredDocTypeEnum = Enum("FilteredDocTypeEnum", enum_members, type=str)

    # Build descriptions for the prompt
    descriptions = "\n".join(
        f"- {dt.value}: {DOCUMENT_TYPE_DESCRIPTIONS.get(dt, 'No description')}" for dt in doc_types
    )

    class FilteredClassificationResult(BaseModel):
        """Schema for document classification within a specific category."""

        model_config = ConfigDict(extra="forbid")

        document_type: FilteredDocTypeEnum = Field(
            description=f"The document type. Choose from:\n{descriptions}"
        )
        confidence: float = Field(
            ge=0.0,
            le=1.0,
            description="Confidence score for the classification (0.0 to 1.0)",
        )
        reasoning: str = Field(
            description="Brief explanation of why this classification was chosen"
        )

    return FilteredClassificationResult


def classify_from_markdown_with_category(
    markdown_content: str,
    top_level_category: TopLevelCategory,
    *,
    model: Optional[str] = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    Classify a document within a specific top-level category using SDK.

    Args:
        markdown_content: Markdown content from parse
        top_level_category: The top-level category to classify within
        model: Extract model to use

    Returns:
        (document_type, raw_response)
    """
    try:
        from landingai_ade.lib import pydantic_to_json_schema
    except ImportError as e:
        raise RuntimeError(
            "Missing dependency 'landingai-ade'. Install with: pip install landingai-ade"
        ) from e

    client = _get_client()
    extract_model = model or os.getenv("LANDING_EXTRACT_MODEL", "extract-latest")

    # Build category-specific classification schema
    schema_cls = build_classification_schema_for_category(top_level_category)
    schema = pydantic_to_json_schema(schema_cls)

    print(f"  [SDK] Classifying within '{top_level_category.value}' with model: {extract_model}")
    response = client.extract(
        schema=schema,
        markdown=BytesIO(markdown_content.encode("utf-8")),
        model=extract_model,
    )

    # Extract document type from response
    extraction = getattr(response, "extraction", {}) or {}
    doc_type_value = extraction.get("document_type")

    if doc_type_value:
        doc_type = doc_type_value if isinstance(doc_type_value, str) else str(doc_type_value)
    else:
        doc_type = DocumentType.UNCATEGORIZED.value

    raw = {
        "extraction": extraction,
        "extraction_metadata": getattr(response, "extraction_metadata", None),
        "top_level_category": top_level_category.value,
        "api_used": "sdk",
    }

    return doc_type, raw


def process_document(
    pdf_path: Path,
    base_out_dir: Path,
    base_markdown_dir: Path,
    *,
    top_level_category: Optional[TopLevelCategory] = None,
    parse_model: Optional[str] = None,
    extract_model: Optional[str] = None,
    force_parse: bool = False,
    prefer_legacy_api: bool = False,
    use_eu_endpoint: bool = False,
) -> Dict[str, Any]:
    """
    Process a single document through the full pipeline.

    Smart API routing:
    - ≤50 pages: Legacy API for parse+classify (cost-effective), SDK for extract
    - >50 pages: SDK for all steps (no page limit)

    Pipeline:
    1. Parse PDF → Markdown
    2. Classify from Markdown
    3. Extract fields from Markdown (always SDK)

    Output structure: base_dir / top_level_category / document_type / file

    Args:
        pdf_path: Path to the PDF
        base_out_dir: Base output directory for records
        base_markdown_dir: Base directory for markdown files
        top_level_category: Top-level category to classify within (optional)
        parse_model: Model for parsing (SDK only)
        extract_model: Model for extraction (SDK only)
        force_parse: Force re-parsing even if cached
        prefer_legacy_api: Use legacy API for ≤50 page documents (default: True)
        use_eu_endpoint: Use EU endpoint for legacy API

    Returns:
        Record dict with all results
    """
    record: Dict[str, Any] = {"pdf_path": str(pdf_path)}
    stem = _safe_stem(pdf_path)

    print(f"\nProcessing: {pdf_path.name}")

    if top_level_category:
        print(f"  Top-level category: {top_level_category.value}")
        record["top_level_category"] = top_level_category.value

    # Determine which API to use for parse+classify based on page count
    use_legacy = False
    page_count = -1

    if prefer_legacy_api:
        use_legacy, page_count = should_use_legacy_api(pdf_path)
        if page_count > 0:
            print(f"  Page count: {page_count}")
            record["page_count"] = page_count

        if use_legacy:
            print(f"  → Using Legacy API for parse+classify (≤{LEGACY_API_MAX_PAGES} pages)")
        else:
            print(f"  → Using SDK API for parse+classify (>{LEGACY_API_MAX_PAGES} pages)")

    # Check for cached markdown first (regardless of API choice)
    cached_md_path, cached_parse_json_path = None, None
    markdown_content = None
    doc_type = None
    class_raw = None
    used_cache = False

    if not force_parse:
        cached_md_path, cached_parse_json_path = _find_cached_markdown(stem, base_markdown_dir)
        if cached_md_path and cached_md_path.exists():
            print(f"  Using cached markdown: {cached_md_path}")
            markdown_content = cached_md_path.read_text(encoding="utf-8")
            used_cache = True
            # Need to classify from cached markdown using SDK
            use_legacy = False

    # Step 1 & 2: Parse and Classify
    if use_legacy and markdown_content is None:
        # Use Legacy API for parse + classify in one call
        try:
            doc_type, markdown_content, class_raw = legacy_api_parse_and_classify(
                pdf_path,
                top_level_category=top_level_category,
                use_eu_endpoint=use_eu_endpoint,
            )
            record["parse_api"] = "legacy"
            record["classify_api"] = "legacy"
        except Exception as e:
            print(f"  ⚠️  Legacy API failed ({e}), falling back to SDK")
            use_legacy = False

    if not use_legacy or markdown_content is None:
        # Use SDK for parse
        if markdown_content is None:
            print("  Step 1: Parsing document...")
            markdown_content, parse_response, cached_md_path, cached_parse_json_path = (
                parse_document(
                    pdf_path,
                    model=parse_model,
                    cache_dir=base_markdown_dir,
                    force=force_parse,
                )
            )
            used_cache = cached_md_path is not None
            record["parse_api"] = "sdk" if not used_cache else "cache"

        # Use SDK for classify
        print("  Step 2: Classifying document...")
        if top_level_category:
            doc_type, class_raw = classify_from_markdown_with_category(
                markdown_content,
                top_level_category,
                model=extract_model,
            )
        else:
            doc_type, class_raw = classify_from_markdown(markdown_content, model=extract_model)
        record["classify_api"] = "sdk"

    record["category"] = doc_type
    record["document_type"] = doc_type
    record["classification_raw"] = class_raw
    print(f"  → Classified as: {doc_type}")

    # Step 3: Get hierarchical output directories
    top_level_str = top_level_category.value if top_level_category else None
    cat_records_dir, cat_markdown_dir = get_category_output_dirs(
        base_out_dir, base_markdown_dir, top_level_str, doc_type
    )

    # Step 4: Handle markdown paths
    if used_cache:
        md_path = cached_md_path
        parse_json_path = cached_parse_json_path
        print(f"  → Using existing markdown: {md_path}")
    else:
        # Create a parse response wrapper for legacy API
        if record.get("parse_api") == "legacy":
            parse_response = LegacyParseResponse(
                markdown_content,
                class_raw.get("extraction_metadata", []) if class_raw else [],
            )
        md_path, parse_json_path = save_parse_outputs(
            markdown_content, parse_response, cat_markdown_dir, stem
        )
        print(f"  → Markdown saved: {md_path}")

    record["markdown_path"] = str(md_path)
    record["parse_json_path"] = str(parse_json_path) if parse_json_path else None

    # Step 5: Extract fields from markdown (ALWAYS using SDK)
    print("  Step 3: Extracting fields (SDK)...")
    extracted, extract_raw = extract_fields(markdown_content, doc_type, model=extract_model)
    extracted_keys = sorted(extracted.keys()) if isinstance(extracted, dict) else []
    print(f"  → Extracted variable keys: {extracted_keys}")
    record["extracted"] = extracted
    record["extraction_raw"] = extract_raw
    record["extract_api"] = "sdk"  # Always SDK for extraction

    # Step 6: Save record
    per_file_path = _unique_json_path(cat_records_dir, stem)
    per_file_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"  → Record saved: {per_file_path}")

    return record


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Landing.ai SDK Pipeline: Parse → Classify → Extract (Smart API Routing)"
    )
    ap.add_argument("--pdf", type=str, default=None, help="Single PDF path")
    ap.add_argument(
        "--pdf-dir",
        type=str,
        default=None,
        help="Directory to scan recursively for documents/images (.pdf, .docx, .png, .jpeg)",
    )
    ap.add_argument(
        "--out",
        type=str,
        default=r".\out_new\records",
        help="Base output directory. Category subfolders will be created here.",
    )
    ap.add_argument(
        "--out-jsonl",
        type=str,
        default=None,
        help="Optional path to write combined JSONL index.",
    )
    ap.add_argument(
        "--markdown-dir",
        type=str,
        default=r".\out_new\markdown",
        help="Base directory for markdown files.",
    )
    ap.add_argument(
        "--top-level-category",
        type=str,
        default=None,
        choices=[c.value for c in TopLevelCategory],
        help="Top-level category to classify within (e.g., 'Company Information', 'Technical')",
    )
    ap.add_argument(
        "--parse-model",
        type=str,
        default=None,
        help="Parse model for SDK (default: dpt-2-latest or LANDING_PARSE_MODEL env var)",
    )
    ap.add_argument(
        "--extract-model",
        type=str,
        default=None,
        help="Extract model for SDK (default: extract-latest or LANDING_EXTRACT_MODEL env var)",
    )
    ap.add_argument("--force-parse", action="store_true", help="Re-parse even if cached")
    ap.add_argument(
        "--force-reprocess",
        action="store_true",
        help="Re-process files even if already processed",
    )
    ap.add_argument(
        "--no-legacy-api",
        action="store_true",
        help="Disable legacy API routing (always use SDK for parse+classify)",
    )
    ap.add_argument(
        "--use-eu-endpoint",
        action="store_true",
        help="Use EU endpoint for legacy API",
    )

    args = ap.parse_args()

    # Parse top-level category if provided
    top_level_category: Optional[TopLevelCategory] = None
    if args.top_level_category:
        try:
            top_level_category = TopLevelCategory(args.top_level_category)
        except ValueError:
            print(f"❌ Invalid top-level category: {args.top_level_category}")
            print(f"   Valid options: {[c.value for c in TopLevelCategory]}")
            return 1

    pdfs = _iter_inputs(args.pdf, args.pdf_dir)

    base_out_dir = Path(args.out).expanduser().resolve()
    base_out_dir.mkdir(parents=True, exist_ok=True)

    out_jsonl_path = Path(args.out_jsonl).expanduser().resolve() if args.out_jsonl else None
    if out_jsonl_path:
        out_jsonl_path.parent.mkdir(parents=True, exist_ok=True)

    base_markdown_dir = Path(args.markdown_dir).expanduser().resolve()
    base_markdown_dir.mkdir(parents=True, exist_ok=True)

    # Track stats
    category_counts: Dict[str, int] = {}
    api_stats: Dict[str, Dict[str, int]] = {
        "parse": {"legacy": 0, "sdk": 0, "cache": 0},
        "classify": {"legacy": 0, "sdk": 0},
        "extract": {"sdk": 0},
    }
    skipped_count = 0
    error_count = 0

    print("=" * 60)
    print("Landing.ai Pipeline (Smart API Routing)")
    print("=" * 60)
    print(f"Files to process: {len(pdfs)}")
    if top_level_category:
        print(f"Top-level category: {top_level_category.value}")
        available_types = get_document_types_for_category(top_level_category)
        print(f"Available document types: {[dt.value for dt in available_types]}")
    print(f"Output directory: {base_out_dir}")
    print(f"Markdown directory: {base_markdown_dir}")
    print(
        f"Legacy API: {'Disabled' if args.no_legacy_api else f'Enabled for ≤{LEGACY_API_MAX_PAGES} pages (parse+classify)'}"
    )
    print(f"Extraction: Always SDK (to benefit from latest features)")
    if args.use_eu_endpoint:
        print(f"Using EU endpoint for legacy API")
    print("=" * 60)

    jsonl_f = out_jsonl_path.open("w", encoding="utf-8") if out_jsonl_path else None

    try:
        for pdf_path in pdfs:
            # Check if already processed
            if not args.force_reprocess and _is_already_processed(
                pdf_path, base_out_dir, base_markdown_dir
            ):
                print(f"\nSkipping (already processed): {pdf_path.name}")
                skipped_count += 1
                continue

            try:
                record = process_document(
                    pdf_path,
                    base_out_dir,
                    base_markdown_dir,
                    top_level_category=top_level_category,
                    parse_model=args.parse_model,
                    extract_model=args.extract_model,
                    force_parse=args.force_parse,
                    prefer_legacy_api=False,
                    use_eu_endpoint=args.use_eu_endpoint,
                )

                # Track category counts
                doc_type = record.get("category", "Unknown")
                category_counts[doc_type] = category_counts.get(doc_type, 0) + 1

                # Track API usage
                parse_api = record.get("parse_api", "sdk")
                classify_api = record.get("classify_api", "sdk")
                api_stats["parse"][parse_api] = api_stats["parse"].get(parse_api, 0) + 1
                api_stats["classify"][classify_api] = api_stats["classify"].get(classify_api, 0) + 1
                api_stats["extract"]["sdk"] = api_stats["extract"].get("sdk", 0) + 1

                if jsonl_f:
                    jsonl_f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

            except Exception as e:
                print(f"\n❌ Error processing {pdf_path.name}: {e}")
                error_count += 1

                # Save error record
                error_dir = base_out_dir / "errors"
                error_dir.mkdir(parents=True, exist_ok=True)
                error_record = {
                    "pdf_path": str(pdf_path),
                    "error": f"{type(e).__name__}: {e}",
                }
                stem = _safe_stem(pdf_path)
                error_path = _unique_json_path(error_dir, stem)
                error_path.write_text(
                    json.dumps(error_record, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

    finally:
        if jsonl_f:
            jsonl_f.close()

    # Print summary
    print("\n" + "=" * 60)
    print("PROCESSING SUMMARY")
    print("=" * 60)
    print(f"Total files found: {len(pdfs)}")
    if top_level_category:
        print(f"Top-level category: {top_level_category.value}")
    print(f"Files skipped (already processed): {skipped_count}")
    print(f"Files processed successfully: {sum(category_counts.values())}")
    print(f"Files with errors: {error_count}")

    print(f"\nAPI Usage Breakdown:")
    print(f"  Parse:")
    print(f"    Legacy API (cost-effective): {api_stats['parse'].get('legacy', 0)} file(s)")
    print(f"    SDK API: {api_stats['parse'].get('sdk', 0)} file(s)")
    print(f"    Cache: {api_stats['parse'].get('cache', 0)} file(s)")
    print(f"  Classify:")
    print(f"    Legacy API (cost-effective): {api_stats['classify'].get('legacy', 0)} file(s)")
    print(f"    SDK API: {api_stats['classify'].get('sdk', 0)} file(s)")
    print(f"  Extract:")
    print(f"    SDK API (always): {api_stats['extract'].get('sdk', 0)} file(s)")

    print(f"\nOutput directory: {base_out_dir}")
    print("\nFiles by document type:")
    for cat, count in sorted(category_counts.items()):
        sanitized = _sanitize_category_name(cat)
        print(f"  {sanitized}/: {count} file(s)")

    if out_jsonl_path:
        print(f"\nJSONL index: {out_jsonl_path}")

    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
