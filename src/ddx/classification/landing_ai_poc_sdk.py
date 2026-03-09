from __future__ import annotations

import argparse
import json
import os
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
    LegalInformation,
    ShareholderStructure,
    LegalRepresentation,
    PYDANTIC_MODELS as COMPANY_PYDANTIC_MODELS,
    DOCUMENT_TYPE_DESCRIPTIONS,
    DOCUMENT_TYPE_TO_TOP_LEVEL,
)


VALIDATION_BYPASS_FIELDS = frozenset(
    {
        "year",
        "monthly_consumption",
        "financial_ratios",
        "annual_filings",
        "annual_cash_flows",
    }
)

VALIDATION_BYPASS_DOCUMENT_TYPES = frozenset(
    {
        DocumentType.ENERGY_CONSUMPTION_BILLS.value,
        DocumentType.FINANCIAL_STATEMENTS.value,
        DocumentType.INCOME_TAX_FILINGS.value,
        DocumentType.CASH_FLOW_STATEMENTS.value,
    }
)


def should_disable_cross_document_validation(
    document_type: DocumentType | str,
    field_names: Optional[List[str]] = None,
) -> bool:
    """Return True for additive time-series payloads that must keep every period."""
    doc_type_value = (
        document_type.value if isinstance(document_type, DocumentType) else document_type
    )
    if doc_type_value in VALIDATION_BYPASS_DOCUMENT_TYPES:
        return True

    if not field_names:
        return False

    return any(field_name in VALIDATION_BYPASS_FIELDS for field_name in field_names)


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
        default=None, description="E_Grid - Energy injected into grid for the month in MWh"
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
        default=None, description='Geographical coordinates (e.g., "-02°06\'03", -080°44\'47"")'
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
    module_certifications: Optional[List[str]] = Field(
        default=None,
        description="Certifications (IEC 61215, IEC 61730, PID test, IEC 62716, IEC 61701)",
    )
    module_factory_test_date: Optional[str] = Field(
        default=None, description="Factory report test date if attached"
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
    inverter_certifications: Optional[List[str]] = Field(
        default=None, description="Inverter certifications"
    )
    inverter_anti_island_test_date: Optional[str] = Field(
        default=None, description="Anti-island test date if attached"
    )

    # Mounting Structure
    structure_material: Optional[str] = Field(
        default=None,
        description="Material of the mounting structure (Anodized Aluminum, Hot deep Galvanized, etc.)",
    )
    structure_warranty_years: Optional[int] = Field(
        default=None, description="Structural warranty against corrosion in years"
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
    project_visitation_report: Optional[ProjectVisitReportData] = Field(
        default=None, description="Site visit information"
    )
    project_layout: Optional[ProjectLayoutData] = Field(
        default=None,
        description="Layout and sizing information",
    )
    grouding_system: Optional[GroundingSystemSingleLineDiagramData] = Field(
        default=None,
        description="Grounding system information",
    )


class KmzPoligonData(BaseModel):
    """Schema for KMZ Polygon (Section 1.11) - Area of Intervention."""

    model_config = ConfigDict(extra="forbid")

    polygon_area_m2: float = Field(description="Polygon surface area in m² from Google Earth")


class CableEntry(BaseModel):
    """Individual cable sizing entry for DC/AC connections."""

    model_config = ConfigDict(extra="forbid")

    connection_type: str = Field(
        description="Connection type (DC solar connection, AC load connection)"
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
        description="Table of cable sizing for DC solar and AC load connections"
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
    DocumentType.CERTIFICATE_OF_LEGAL_EXISTENCE.value: LegalInformation,
    DocumentType.SHAREHOLDERS_DECLARATION.value: ShareholderStructure,
    DocumentType.LEGAL_REPRESENTATIVE_APPOINTMENT.value: LegalRepresentation,
    # Technical (existing)
    DocumentType.PROJECT_SIMULATION_REPORT.value: ProjectSimulationReportData,
    DocumentType.PROJECT_DATA_EQUIPMENT_SHEETS.value: ProjectDataMainEquipmentSheetsData,
    DocumentType.PROJECT_BASIC_ENGINEERING.value: ProjectBasicEngineeringData,
    DocumentType.PROJECT_VISIT_REPORT.value: ProjectVisitReportData,
    DocumentType.PROJECT_LAYOUT.value: ProjectLayoutData,
    DocumentType.KMZ_POLIGON.value: KmzPoligonData,
    DocumentType.CABLE_SIZING_CALCULATION.value: CableSizingCalculationReportData,
    DocumentType.GROUNDING_SYSTEM_DIAGRAM.value: GroundingSystemSingleLineDiagramData,
    DocumentType.UNCATEGORIZED.value: UncategorizedDocumentData,
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

    print(f"  Parsing document with model: {parse_model}")
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
    truncated_markdown = markdown_content[:max_chars]

    # Convert classification schema to JSON schema
    schema = pydantic_to_json_schema(ClassificationResult)

    print(f"  Classifying document with model: {extract_model}")
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

    print(f"  Extracting fields with model: {extract_model}")
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
    """Iterate over input PDFs."""
    if pdf:
        p = Path(pdf).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"Not found: {p}")
        return [p]

    if pdf_dir:
        d = Path(pdf_dir).expanduser().resolve()
        if not d.exists():
            raise FileNotFoundError(f"Not found: {d}")
        return sorted([p for p in d.rglob("*.pdf") if p.is_file()])

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
            ge=0.0, le=1.0, description="Confidence score for the classification (0.0 to 1.0)"
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
    Classify a document within a specific top-level category.

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

    # Truncate markdown for classification

    # Build category-specific classification schema
    schema_cls = build_classification_schema_for_category(top_level_category)
    schema = pydantic_to_json_schema(schema_cls)

    print(f"  Classifying within '{top_level_category.value}' with model: {extract_model}")
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
) -> Dict[str, Any]:
    """
    Process a single document through the full pipeline:
    1. Parse PDF → Markdown (SDK) - with caching support
    2. Classify from Markdown (SDK) - within top-level category if provided
    3. Extract fields from Markdown (SDK)

    Output structure: base_dir / top_level_category / document_type / file

    Args:
        pdf_path: Path to the PDF
        base_out_dir: Base output directory for records
        base_markdown_dir: Base directory for markdown files
        top_level_category: Top-level category to classify within (optional)
        parse_model: Model for parsing
        extract_model: Model for extraction
        force_parse: Force re-parsing even if cached

    Returns:
        Record dict with all results
    """
    record: Dict[str, Any] = {"pdf_path": str(pdf_path)}
    stem = _safe_stem(pdf_path)

    print(f"\nProcessing: {pdf_path.name}")

    if top_level_category:
        print(f"  Top-level category: {top_level_category.value}")
        record["top_level_category"] = top_level_category.value

    # Step 1: Parse document to markdown (with caching)
    print("  Step 1: Parsing document...")
    markdown_content, parse_response, cached_md_path, cached_parse_json_path = parse_document(
        pdf_path,
        model=parse_model,
        cache_dir=base_markdown_dir,
        force=force_parse,
    )

    used_cache = cached_md_path is not None

    # Step 2: Classify from markdown
    print("  Step 2: Classifying document...")
    if top_level_category:
        # Classify within the specified top-level category
        doc_type, class_raw = classify_from_markdown_with_category(
            markdown_content,
            top_level_category,
            model=extract_model,
        )
    else:
        # Original behavior: classify across all categories
        doc_type, class_raw = classify_from_markdown(markdown_content, model=extract_model)

    record["category"] = doc_type
    record["document_type"] = doc_type  # Alias for clarity
    record["classification_raw"] = class_raw
    print(f"  → Classified as: {doc_type}")

    # Step 3: Get hierarchical output directories
    # Structure: top_level_category / document_type / file
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
        md_path, parse_json_path = save_parse_outputs(
            markdown_content, parse_response, cat_markdown_dir, stem
        )
        print(f"  → Markdown saved: {md_path}")

    record["markdown_path"] = str(md_path)
    record["parse_json_path"] = str(parse_json_path) if parse_json_path else None

    # Step 5: Extract fields from markdown
    print("  Step 3: Extracting fields...")
    extracted, extract_raw = extract_fields(markdown_content, doc_type, model=extract_model)
    record["extracted"] = extracted
    record["extraction_raw"] = extract_raw

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
        description="Landing.ai SDK Pipeline: Parse → Classify → Extract (supports large documents)"
    )
    ap.add_argument("--pdf", type=str, default=None, help="Single PDF path")
    ap.add_argument(
        "--pdf-dir", type=str, default=None, help="Directory to scan recursively for PDFs"
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
        help="Parse model (default: dpt-2-latest or LANDING_PARSE_MODEL env var)",
    )
    ap.add_argument(
        "--extract-model",
        type=str,
        default=None,
        help="Extract model (default: extract-latest or LANDING_EXTRACT_MODEL env var)",
    )
    ap.add_argument("--force-parse", action="store_true", help="Re-parse even if cached")
    ap.add_argument(
        "--force-reprocess",
        action="store_true",
        help="Re-process files even if already processed",
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
    skipped_count = 0
    error_count = 0

    print("=" * 60)
    print("Landing.ai SDK Pipeline (No Page Limit)")
    print("=" * 60)
    print(f"PDFs to process: {len(pdfs)}")
    if top_level_category:
        print(f"Top-level category: {top_level_category.value}")
        available_types = get_document_types_for_category(top_level_category)
        print(f"Available document types: {[dt.value for dt in available_types]}")
    print(f"Output directory: {base_out_dir}")
    print(f"Markdown directory: {base_markdown_dir}")
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
                )

                # Track category counts
                doc_type = record.get("category", "Unknown")
                category_counts[doc_type] = category_counts.get(doc_type, 0) + 1

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
    print(f"Total PDFs found: {len(pdfs)}")
    if top_level_category:
        print(f"Top-level category: {top_level_category.value}")
    print(f"PDFs skipped (already processed): {skipped_count}")
    print(f"PDFs processed successfully: {sum(category_counts.values())}")
    print(f"PDFs with errors: {error_count}")
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
