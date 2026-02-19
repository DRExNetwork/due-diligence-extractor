from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type

import requests
from pydantic import BaseModel, Field

from ddx.classification.classifier import DocumentCategory  # absolute import
from agentic_doc.parse import parse

LANDING_VA_URL = "https://api.va.landing.ai/v1/tools/agentic-document-analysis"
LANDING_ADE_EXTRACT_URL = "https://api.va.landing.ai/v1/ade/extract"  # NEW
LANDING_ADE_PARSE_URL = "https://api.va.landing.ai/v1/ade/parse"  # NEW


def _headers() -> Dict[str, str]:
    api_key = os.getenv("VA_API_KEY")
    if not api_key:
        raise RuntimeError("Missing VA_API_KEY environment variable.")
    return {"Authorization": f"Bearer {api_key}"}


def _post(
    pdf_path: Path,
    schema: Dict[str, Any],
    timeout_s: int = 180,
    *,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    with pdf_path.open("rb") as f:
        files = [("pdf", (pdf_path.name, f, "application/pdf"))]
        payload: Dict[str, Any] = {
            "fields_schema": json.dumps(schema),
            "model": model or os.getenv("LANDING_PARSE_MODEL", "dpt-2-latest-latest"),
        }
        resp = requests.post(
            LANDING_ADE_PARSE_URL,
            headers=_headers(),
            files=files,
            data=payload,
            timeout=timeout_s,
        )
    resp.raise_for_status()
    return resp.json()


def _post(pdf_path: Path, schema: Dict[str, Any], timeout_s: int = 180) -> Dict[str, Any]:
    # existing PDF tool post (classification + optional PDF-based extraction)
    with pdf_path.open("rb") as f:
        files = [("pdf", (pdf_path.name, f, "application/pdf"))]
        payload = {"fields_schema": json.dumps(schema)}
        resp = requests.post(
            LANDING_VA_URL,
            headers=_headers(),
            files=files,
            data=payload,
            timeout=timeout_s,
        )
    resp.raise_for_status()
    return resp.json()


def _post_ade_extract_markdown(
    markdown_path: Path,
    schema: Dict[str, Any],
    *,
    model: Optional[str] = None,
    timeout_s: int = 180,
) -> Dict[str, Any]:
    """
    Calls VA ADE Extract endpoint using an existing local Markdown file.

    POST /v1/ade/extract (multipart/form-data)
      - schema: string (JSON)
      - model: optional (e.g. extract-latest)
      - markdown: file upload
    """

    print("Posting to ADE Extract:", markdown_path)
    if not markdown_path.exists():
        raise FileNotFoundError(f"Markdown not found: {markdown_path}")

    data: Dict[str, Any] = {"schema": json.dumps(schema)}
    if model:
        data["model"] = model

    with markdown_path.open("rb") as f:
        files = [("markdown", (markdown_path.name, f, "text/markdown"))]
        resp = requests.post(
            LANDING_ADE_EXTRACT_URL,
            headers=_headers(),
            files=files,
            data=data,
            timeout=timeout_s,
        )

    print("Response ", resp.json())

    resp.raise_for_status()
    return resp.json()


def _class_schema() -> Dict[str, Any]:
    categories = [c.value for c in DocumentCategory]
    print("Classification categories:", categories)
    return {
        "type": "object",
        "properties": {"document_type": {"type": "string", "enum": categories}},
        "required": ["document_type"],
    }


# ---------------------------
# Pydantic extraction models
# (All fields required by default: no Optional, no defaults)
# ---------------------------


class MonthlyStatistic(BaseModel):
    """Monthly production statistics from simulation report."""

    month: str = Field(description="Month name (January, February, etc.)")
    pvout_daily_avg_wh_kwp: Optional[float] = Field(
        default=None, description="PVOUT Specific Daily average in Wh/kWp"
    )
    pvout_monthly_mwh: Optional[float] = Field(
        default=None, description="PVOUT Total Monthly sum in MWh"
    )
    pr_pct: Optional[float] = Field(
        default=None, description="Performance Ratio for the month in %"
    )


class ProjectSimulationReportData(BaseModel):
    """Schema for Project Simulation Report (Section 1.5) - PVsyst/Helioscope."""

    # Project Info
    project_name: str = Field(description="Project name (e.g., 'Biogemar - Santa Elena')")
    geographical_coordinates: Optional[str] = Field(
        default=None, description='Geographical coordinates (e.g., "-02°06\'03", -080°44\'47"")'
    )
    elevation_m: Optional[float] = Field(default=None, description="Elevation in meters (e.g., 5)")
    land_cover: Optional[str] = Field(
        default=None, description="Land cover type (water bodies, land, rooftop, etc.)"
    )

    # Simulation Overview
    specific_pv_output_kwh_kwp: Optional[float] = Field(
        default=None,
        description="Annual Specific Photovoltaic Power Output in kWh/kWp (also called 'Producción especifica')",
    )
    total_pv_energy_mwh: float = Field(
        description="Total photovoltaic energy output in MWh (e.g., 1349)"
    )
    performance_ratio_pct: float = Field(description="Performance ratio in % (e.g., 78.8)")
    air_temperature_c: Optional[float] = Field(
        default=None, description="Air temperature in Celsius (e.g., 23.7)"
    )
    total_pv_power_mwp: float = Field(
        description="Total photovoltaic power output in MWp (e.g., 10)"
    )

    # Monthly Statistics
    monthly_statistics: Optional[List[MonthlyStatistic]] = Field(
        default=None,
        description="Monthly statistics for 12 months with PVOUT daily avg, monthly sum, and PR",
    )

    # PV Performance
    degradation_rate_year1_pct: Optional[float] = Field(
        default=None, description="Degradation Rate for year 1 in % (e.g., 1)"
    )
    degradation_rate_year2_onwards_pct: Optional[float] = Field(
        default=None, description="Degradation Rate for year 2 onwards in % (e.g., 0.4)"
    )
    cumulative_degradation_pct: Optional[float] = Field(
        default=None, description="Cumulative Degradation Rate in % (e.g., 9)"
    )
    shadow_loss_pct: Optional[float] = Field(
        default=None, description="Shadow loss in % (should not exceed 5%)"
    )


class ProjectDataMainEquipmentSheetsData(BaseModel):
    """Schema for Project Data Main Equipment Sheets (Section 1.7)."""

    # Solar Modules
    module_brand: str = Field(description="Solar module brand (e.g., JA Solar)")
    module_model: str = Field(description="Solar module model (e.g., JAM72S30-540/MR)")
    module_capacity_wdc: Optional[float] = Field(
        default=None, description="Module capacity in Wdc (e.g., 540)"
    )
    module_efficiency_pct: Optional[float] = Field(
        default=None, description="Module efficiency in % (e.g., 20.9)"
    )
    module_dimensions_mm: Optional[str] = Field(
        default=None, description="Module dimensions in mm (e.g., '2279 x 1134 mm')"
    )
    module_technical_warranty_years: Optional[int] = Field(
        default=None, description="Technical warranty in years (e.g., 12)"
    )
    module_linear_degradation_warranty_years: Optional[int] = Field(
        default=None, description="Linear degradation warranty in years (e.g., 25)"
    )
    module_certifications: Optional[List[str]] = Field(
        default=None,
        description="Certifications found (IEC 61215, IEC 61730, PID test, IEC 62716, IEC 61701)",
    )
    module_factory_test_date: Optional[str] = Field(
        default=None, description="Factory report test date if attached"
    )

    # Inverter
    inverter_brand: Optional[str] = Field(default=None, description="Inverter brand (e.g., Huawei)")
    inverter_model: Optional[str] = Field(
        default=None, description="Inverter model (e.g., SUN2000-100KTL-M1)"
    )
    inverter_ac_capacity_kw: Optional[float] = Field(
        default=None, description="AC capacity in kW (e.g., 100)"
    )
    inverter_dc_capacity_kw: Optional[float] = Field(
        default=None, description="DC capacity in kW (e.g., 120)"
    )
    inverter_efficiency_pct: Optional[float] = Field(
        default=None, description="Inverter efficiency in % (e.g., 98.6)"
    )
    inverter_mppt_voltage_range_v: Optional[str] = Field(
        default=None, description="MPPT voltage range in V (e.g., '480-850V')"
    )
    inverter_mppt_current_range_a: Optional[str] = Field(
        default=None, description="MPPT current range in A (e.g., '5-20A')"
    )
    inverter_type: Optional[str] = Field(
        default=None, description="Inverter type (On grid, Off grid, Hybrid)"
    )
    inverter_technical_warranty_years: Optional[int] = Field(
        default=None, description="Inverter warranty in years (e.g., 10)"
    )
    inverter_certifications: Optional[List[str]] = Field(
        default=None, description="Inverter certifications (IEC 62109, IEC 61727, IEC 61000)"
    )
    inverter_anti_island_test_date: Optional[str] = Field(
        default=None, description="Anti-island test date if attached"
    )

    # Mounting Structure
    structure_type: Optional[str] = Field(
        default=None,
        description="Structure type (Anodized aluminum, coplanar, land mounting, carports, etc.)",
    )
    structure_material: Optional[str] = Field(
        default=None, description="Material (Anodized Aluminum, Hot deep Galvanized, etc.)"
    )
    structure_warranty_years: Optional[int] = Field(
        default=None, description="Structural warranty against corrosion in years (e.g., 15)"
    )


class ProjectBasicEngineeringData(BaseModel):
    """Schema for Project Basic Engineering (Section 1.8) - Memoria Técnica."""

    # Electrical Parameters of the Load
    system_type: str = Field(description="Type of system (three-phase 3F, one-phase 1F)")
    voltage_mains_v: float = Field(description="Voltage mains in V (220, 440, etc.)")
    load_description: str = Field(
        description="Description of the load (Industrial load, commercial load, motors, etc.)"
    )
    load_capacity_kw: float = Field(description="Load capacity in kW (e.g., 300)")
    annual_load_energy_kwh: Optional[float] = Field(
        default=None, description="Annual load consumed energy in kWh (e.g., 1000)"
    )


class ProjectVisitReportData(BaseModel):
    """Schema for Project Visit Report (Section 1.9) - Site Characteristics."""

    # Site Characteristics
    site_description: str = Field(
        description="Site description (e.g., 'Site with vehicle access, no obstructions, slope <5%')"
    )
    installation_area_m2: float = Field(
        description="Area for project installation in m² (e.g., 1350)"
    )
    installation_location: str = Field(
        description="Location of area available for installation (Rooftop, Land, Floating, etc.)"
    )


class ProjectLayoutData(BaseModel):
    """Schema for Project Layout (Section 1.10) - Technology Sizing."""

    # Technology Sizing
    nominal_capacity_kw: float = Field(description="Nominal capacity in kW (e.g., 1500)")
    peak_capacity_kwp: float = Field(description="Peak capacity in kWp (e.g., 3500)")
    solar_modules_quantity: int = Field(description="Solar modules quantity (e.g., 8504)")
    inverters_quantity: int = Field(description="Inverters quantity (e.g., 20)")
    strings_per_inverter: Optional[int] = Field(
        default=None, description="Strings per inverter quantity (e.g., 5)"
    )
    module_orientation: Optional[str] = Field(
        default=None, description="Solar module orientation (e.g., 'Southeast, 15° tilt')"
    )


class KmzPoligonData(BaseModel):
    """Schema for KMZ Polygon (Section 1.11) - Area of Intervention."""

    # Area of Intervention
    polygon_area_m2: float = Field(description="Polygon surface area in m² from Google Earth")


class CableEntry(BaseModel):
    """Individual cable sizing entry for DC/AC connections."""

    connection_type: str = Field(
        description="Connection type (DC solar connection, AC load connection)"
    )
    sizing: str = Field(description="Conductor sizing (e.g., '35 mm²' or '10 AWG')")
    cable_type: str = Field(description="Cable type (e.g., 'XLPE type')")
    voltage_drop_pct: float = Field(description="Voltage drop in % (e.g., 2.9)")
    installation: Optional[str] = Field(
        default=None, description="Installation method (underground installation, etc.)"
    )
    total_length_m: Optional[float] = Field(default=None, description="Total length in meters")


class CableSizingCalculationReportData(BaseModel):
    """Schema for Cable Sizing Calculation Report (Section 1.12)."""

    # Cable Sizing - Table format for DC and AC connections
    cable_entries: List[CableEntry] = Field(
        description="Table of cable sizing for DC solar and AC load connections"
    )


class GroundingSystemSingleLineDiagramData(BaseModel):
    """Schema for Grounding System (Section 1.13) - Grounding Criteria."""

    # Grounding Criteria
    system_type: str = Field(
        description="Type of grounding system (e.g., 'TT system with 3 grounding rods')"
    )
    resistance_value_ohm: float = Field(description="Resistance value in Ohm (e.g., 3.8)")


class UncategorizedDocumentData(BaseModel):
    """Schema for documents that don't match any predefined category."""

    summary: str = Field(description="Brief summary of what the document contains")
    why_uncategorized: str = Field(
        description="Why the document does not match any predefined category"
    )


PYDANTIC_MODELS: Dict[str, Type[BaseModel]] = {
    DocumentCategory.PROJECT_SIMULATION_REPORT.value: ProjectSimulationReportData,
    DocumentCategory.PROJECT_DATA_EQUIPMENT_SHEETS.value: ProjectDataMainEquipmentSheetsData,
    DocumentCategory.PROJECT_BASIC_ENGINEERING.value: ProjectBasicEngineeringData,
    DocumentCategory.PROJECT_VISIT_REPORT.value: ProjectVisitReportData,
    DocumentCategory.PROJECT_LAYOUT.value: ProjectLayoutData,
    DocumentCategory.KMZ_POLIGON.value: KmzPoligonData,
    DocumentCategory.CABLE_SIZING_CALCULATION.value: CableSizingCalculationReportData,
    DocumentCategory.GROUNDING_SYSTEM_DIAGRAM.value: GroundingSystemSingleLineDiagramData,
    DocumentCategory.UNCATEGORIZED.value: UncategorizedDocumentData,
}


# =============================================================================
# EXTRACTION_SCHEMAS - JSON Schemas for VA mode extraction
# (Matching EXACTLY the Output Structure from requirements)
# =============================================================================

EXTRACTION_SCHEMAS: Dict[str, Dict[str, Any]] = {
    DocumentCategory.PROJECT_SIMULATION_REPORT.value: {
        "title": "Project Simulation Report Extraction Schema",
        "description": "Schema for extracting key fields from a Project Simulation Report (PVsyst/Helioscope). Section 1.5.",
        "type": "object",
        "properties": {
            # Project Info
            "project_name": {
                "type": "string",
                "description": "Project name (e.g., 'Biogemar - Santa Elena')",
            },
            "geographical_coordinates": {
                "type": ["string", "null"],
                "description": 'Geographical coordinates (e.g., "-02°06\'03", -080°44\'47"")',
            },
            "elevation_m": {
                "type": ["number", "null"],
                "description": "Elevation in meters (e.g., 5)",
            },
            "land_cover": {
                "type": ["string", "null"],
                "description": "Land cover type (water bodies, land, rooftop, etc.)",
            },
            # Simulation Overview
            "specific_pv_output_kwh_kwp": {
                "type": ["number", "null"],
                "description": "Annual Specific Photovoltaic Power Output in kWh/kWp (also called 'Producción especifica')",
            },
            "total_pv_energy_mwh": {
                "type": "number",
                "description": "Total photovoltaic energy output in MWh (e.g., 1349)",
            },
            "performance_ratio_pct": {
                "type": "number",
                "description": "Performance ratio in % (e.g., 78.8)",
            },
            "air_temperature_c": {
                "type": ["number", "null"],
                "description": "Air temperature in Celsius (e.g., 23.7)",
            },
            "total_pv_power_mwp": {
                "type": "number",
                "description": "Total photovoltaic power output in MWp (e.g., 10)",
            },
            # Monthly Statistics
            "monthly_statistics": {
                # CHANGED: Landing ADE Extract does not allow type ["array","null"] when array items are object/array.
                "anyOf": [
                    {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "month": {"type": "string", "description": "Month name"},
                                "pvout_daily_avg_wh_kwp": {
                                    "type": ["number", "null"],
                                    "description": "PVOUT Specific Daily average in Wh/kWp",
                                },
                                "pvout_monthly_mwh": {
                                    "type": ["number", "null"],
                                    "description": "PVOUT Total Monthly sum in MWh",
                                },
                                "pr_pct": {"type": ["number", "null"], "description": "PR in %"},
                            },
                            "required": ["month"],
                        },
                    },
                    {"type": "null"},
                ],
                "description": "Monthly statistics for 12 months",
            },
            # PV Performance
            "degradation_rate_year1_pct": {
                "type": ["number", "null"],
                "description": "Degradation Rate for year 1 in % (e.g., 1)",
            },
            "degradation_rate_year2_onwards_pct": {
                "type": ["number", "null"],
                "description": "Degradation Rate for year 2 onwards in % (e.g., 0.4)",
            },
            "cumulative_degradation_pct": {
                "type": ["number", "null"],
                "description": "Cumulative Degradation Rate in % (e.g., 9)",
            },
            "shadow_loss_pct": {
                "type": ["number", "null"],
                "description": "Shadow loss in % (should not exceed 5%)",
            },
        },
        "required": [
            "project_name",
            "total_pv_energy_mwh",
            "performance_ratio_pct",
            "total_pv_power_mwp",
        ],
    },
    DocumentCategory.PROJECT_DATA_EQUIPMENT_SHEETS.value: {
        "title": "Project Data Main Equipment Sheets Extraction Schema",
        "description": "Schema for extracting Solar Modules, Inverters, and Mounting Structure data. Section 1.7.",
        "type": "object",
        "properties": {
            # Solar Modules
            "module_brand": {
                "type": "string",
                "description": "Solar module brand (e.g., JA Solar)",
            },
            "module_model": {
                "type": "string",
                "description": "Solar module model (e.g., JAM72S30-540/MR)",
            },
            "module_capacity_wdc": {
                "type": ["number", "null"],
                "description": "Module capacity in Wdc (e.g., 540)",
            },
            "module_efficiency_pct": {
                "type": ["number", "null"],
                "description": "Module efficiency in % (e.g., 20.9)",
            },
            "module_dimensions_mm": {
                "type": ["string", "null"],
                "description": "Module dimensions in mm (e.g., '2279 x 1134 mm')",
            },
            "module_technical_warranty_years": {
                "type": ["integer", "null"],
                "description": "Technical warranty in years (e.g., 12)",
            },
            "module_linear_degradation_warranty_years": {
                "type": ["integer", "null"],
                "description": "Linear degradation warranty in years (e.g., 25)",
            },
            "module_certifications": {
                # CHANGED: replace type ["array","null"] with anyOf
                "anyOf": [
                    {"type": "array", "items": {"type": "string"}},
                    {"type": "null"},
                ],
                "description": "Certifications (IEC 61215, IEC 61730, PID test, IEC 62716, IEC 61701)",
            },
            "module_factory_test_date": {
                "type": ["string", "null"],
                "description": "Factory report test date if attached",
            },
            # Inverter
            "inverter_brand": {
                "type": ["string", "null"],
                "description": "Inverter brand (e.g., Huawei)",
            },
            "inverter_model": {
                "type": ["string", "null"],
                "description": "Inverter model (e.g., SUN2000-100KTL-M1)",
            },
            "inverter_ac_capacity_kw": {
                "type": ["number", "null"],
                "description": "AC capacity in kW (e.g., 100)",
            },
            "inverter_dc_capacity_kw": {
                "type": ["number", "null"],
                "description": "DC capacity in kW (e.g., 120)",
            },
            "inverter_efficiency_pct": {
                "type": ["number", "null"],
                "description": "Inverter efficiency in % (e.g., 98.6)",
            },
            "inverter_mppt_voltage_range_v": {
                "type": ["string", "null"],
                "description": "MPPT voltage range in V (e.g., '480-850V')",
            },
            "inverter_mppt_current_range_a": {
                "type": ["string", "null"],
                "description": "MPPT current range in A (e.g., '5-20A')",
            },
            "inverter_type": {
                "type": ["string", "null"],
                "description": "Inverter type (On grid, Off grid, Hybrid)",
            },
            "inverter_technical_warranty_years": {
                "type": ["integer", "null"],
                "description": "Inverter warranty in years (e.g., 10)",
            },
            "inverter_certifications": {
                # CHANGED: replace type ["array","null"] with anyOf
                "anyOf": [
                    {"type": "array", "items": {"type": "string"}},
                    {"type": "null"},
                ],
                "description": "Inverter certifications (IEC 62109, IEC 61727, IEC 61000)",
            },
            "inverter_anti_island_test_date": {
                "type": ["string", "null"],
                "description": "Anti-island test date if attached",
            },
            # Mounting Structure
            "structure_type": {
                "type": ["string", "null"],
                "description": "Structure type (Anodized aluminum, coplanar, land mounting, carports, etc.)",
            },
            "structure_material": {
                "type": ["string", "null"],
                "description": "Material (Anodized Aluminum, Hot deep Galvanized, etc.)",
            },
            "structure_warranty_years": {
                "type": ["integer", "null"],
                "description": "Structural warranty against corrosion in years (e.g., 15)",
            },
        },
        "required": ["module_brand", "module_model"],
    },
    DocumentCategory.PROJECT_BASIC_ENGINEERING.value: {
        "title": "Project Basic Engineering Extraction Schema",
        "description": "Schema for extracting Electrical Parameters of the Load. Section 1.8 - Memoria Técnica.",
        "type": "object",
        "properties": {
            "system_type": {
                "type": "string",
                "description": "Type of system (three-phase 3F, one-phase 1F)",
            },
            "voltage_mains_v": {
                "type": "number",
                "description": "Voltage mains in V (220, 440, etc.)",
            },
            "load_description": {
                "type": "string",
                "description": "Description of the load (Industrial load, commercial load, motors, etc.)",
            },
            "load_capacity_kw": {
                "type": "number",
                "description": "Load capacity in kW (e.g., 300)",
            },
            "annual_load_energy_kwh": {
                "type": ["number", "null"],
                "description": "Annual load consumed energy in kWh (e.g., 1000)",
            },
        },
        "required": ["system_type", "voltage_mains_v", "load_description", "load_capacity_kw"],
    },
    DocumentCategory.PROJECT_VISIT_REPORT.value: {
        "title": "Project Visit Report Extraction Schema",
        "description": "Schema for extracting Site Characteristics. Section 1.9.",
        "type": "object",
        "properties": {
            "site_description": {
                "type": "string",
                "description": "Site description (e.g., 'Site with vehicle access, no obstructions, slope <5%')",
            },
            "installation_area_m2": {
                "type": "number",
                "description": "Area for project installation in m² (e.g., 1350)",
            },
            "installation_location": {
                "type": "string",
                "description": "Location of area available for installation (Rooftop, Land, Floating, etc.)",
            },
        },
        "required": ["site_description", "installation_area_m2", "installation_location"],
    },
    DocumentCategory.PROJECT_LAYOUT.value: {
        "title": "Project Layout Extraction Schema",
        "description": "Schema for extracting Technology Sizing. Section 1.10.",
        "type": "object",
        "properties": {
            "nominal_capacity_kw": {
                "type": "number",
                "description": "Nominal capacity in kW (e.g., 1500)",
            },
            "peak_capacity_kwp": {
                "type": "number",
                "description": "Peak capacity in kWp (e.g., 3500)",
            },
            "solar_modules_quantity": {
                "type": "integer",
                "description": "Solar modules quantity (e.g., 8504)",
            },
            "inverters_quantity": {
                "type": "integer",
                "description": "Inverters quantity (e.g., 20)",
            },
            "strings_per_inverter": {
                "type": ["integer", "null"],
                "description": "Strings per inverter quantity (e.g., 5)",
            },
            "module_orientation": {
                "type": ["string", "null"],
                "description": "Solar module orientation (e.g., 'Southeast, 15° tilt')",
            },
        },
        "required": [
            "nominal_capacity_kw",
            "peak_capacity_kwp",
            "solar_modules_quantity",
            "inverters_quantity",
        ],
    },
    DocumentCategory.KMZ_POLIGON.value: {
        "title": "KMZ Polygon Extraction Schema",
        "description": "Schema for extracting Area of Intervention. Section 1.11.",
        "type": "object",
        "properties": {
            "polygon_area_m2": {
                "type": "number",
                "description": "Polygon surface area in m² from Google Earth",
            },
        },
        "required": ["polygon_area_m2"],
    },
    DocumentCategory.CABLE_SIZING_CALCULATION.value: {
        "title": "Cable Sizing Calculation Report Extraction Schema",
        "description": "Schema for extracting Cable Sizing table for DC/AC connections. Section 1.12.",
        "type": "object",
        "properties": {
            "cable_entries": {
                "type": "array",
                "description": "Table of cable sizing for DC solar and AC load connections",
                "items": {
                    "type": "object",
                    "properties": {
                        "connection_type": {
                            "type": "string",
                            "description": "Connection type (DC solar connection, AC load connection)",
                        },
                        "sizing": {
                            "type": "string",
                            "description": "Conductor sizing (e.g., '35 mm²' or '10 AWG')",
                        },
                        "cable_type": {
                            "type": "string",
                            "description": "Cable type (e.g., 'XLPE type')",
                        },
                        "voltage_drop_pct": {
                            "type": "number",
                            "description": "Voltage drop in % (e.g., 2.9)",
                        },
                        "installation": {
                            "type": ["string", "null"],
                            "description": "Installation method (underground installation, etc.)",
                        },
                        "total_length_m": {
                            "type": ["number", "null"],
                            "description": "Total length in meters",
                        },
                    },
                    "required": ["connection_type", "sizing", "cable_type", "voltage_drop_pct"],
                },
            },
        },
        "required": ["cable_entries"],
    },
    DocumentCategory.GROUNDING_SYSTEM_DIAGRAM.value: {
        "title": "Grounding System Extraction Schema",
        "description": "Schema for extracting Grounding Criteria. Section 1.13.",
        "type": "object",
        "properties": {
            "system_type": {
                "type": "string",
                "description": "Type of grounding system (e.g., 'TT system with 3 grounding rods')",
            },
            "resistance_value_ohm": {
                "type": "number",
                "description": "Resistance value in Ohm (e.g., 3.8)",
            },
        },
        "required": ["system_type", "resistance_value_ohm"],
    },
    DocumentCategory.UNCATEGORIZED.value: {
        "title": "Uncategorized Document Extraction Schema",
        "description": "Schema for documents that do not fit a predefined category.",
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "Brief summary of what the document contains",
            },
            "why_uncategorized": {
                "type": "string",
                "description": "Why the document does not match any predefined category",
            },
        },
        "required": ["summary", "why_uncategorized"],
    },
}


def classify(pdf_path: Path) -> Tuple[str, Dict[str, Any]]:
    raw = _post(pdf_path, _class_schema())
    doc_type = raw.get("data", {}).get("extracted_schema", {}).get("document_type")
    if not doc_type:
        doc_type = DocumentCategory.UNCATEGORIZED.value
    return doc_type, raw


def extract_via_va(
    pdf_path: Path,
    doc_type: str,
    *,
    markdown_path: Optional[Path] = None,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """
    VA extraction.
    - If markdown_path is provided, uses VA ADE Extract (markdown -> extraction + extraction_metadata).
    - Otherwise, falls back to the PDF tool endpoint (agentic-document-analysis).
    """
    schema = EXTRACTION_SCHEMAS.get(doc_type)
    if not schema:
        return None, {"skipped": True, "reason": f"No extraction schema defined for '{doc_type}'"}

    if markdown_path is not None:
        model = os.getenv("VA_EXTRACT_MODEL", "extract-latest")
        raw = _post_ade_extract_markdown(markdown_path, schema, model=model)
        extracted = raw.get("extraction", {})  # ADE Extract response shape
        return extracted, raw

    # fallback: PDF tool (older behavior)
    raw = _post(pdf_path, schema)
    extracted = raw.get("data", {}).get("extracted_schema", {})
    return extracted, raw


def _iter_inputs(pdf: Optional[str], pdf_dir: Optional[str]) -> List[Path]:
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


def _safe_stem(p: Path) -> str:
    stem = p.stem.strip().replace(" ", "_")
    return "".join(ch for ch in stem if ch.isalnum() or ch in ("_", "-", ".")) or "document"


def _sanitize_category_name(category: str) -> str:
    """
    Convert a category name to a safe folder name.
    E.g., 'Project Data Main Equipment Sheets (Solar Modules, Inverters, Mounting Structure)'
    -> 'Project_Data_Main_Equipment_Sheets'
    """
    # Remove content in parentheses
    import re

    clean = re.sub(r"\s*\([^)]*\)", "", category)
    # Replace spaces and special chars with underscores
    clean = re.sub(r"[^\w]+", "_", clean.strip())
    # Remove leading/trailing underscores
    clean = clean.strip("_")
    # Limit length
    return clean[:80] or "Unknown_Category"


def parse_to_markdown(
    document_path: Path,
    markdown_dir: Path,
    *,
    force: bool = False,
    parse_model: Optional[str] = None,
) -> Tuple[Path, Path]:
    """
    Parse a document using LandingAIADE and persist:
      - markdown: <pdf_stem>.md
      - parse json: <pdf_stem>.parse.json
    Returns: (md_path, parse_json_path)
    """
    try:
        from landingai_ade import LandingAIADE  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "Missing dependency 'landingai-ade'. Install with: pip install landingai-ade"
        ) from e

    markdown_dir.mkdir(parents=True, exist_ok=True)

    stem = _safe_stem(document_path)
    md_path = markdown_dir / f"{stem}.md"
    parse_json_path = markdown_dir / f"{stem}.parse.json"

    print(md_path, parse_json_path)

    # CHANGED: reuse cached outputs if markdown exists (parse.json is nice-to-have)
    if not force and md_path.exists():
        return md_path, parse_json_path

    client = LandingAIADE()
    model = parse_model or os.getenv("LANDING_PARSE_MODEL", "dpt-2-latest-latest")
    response = client.parse(document=document_path, model=model)

    # Save markdown
    md_path.write_text(response.markdown or "", encoding="utf-8")

    # Save full parse response JSON
    if hasattr(response, "model_dump"):
        payload = response.model_dump()  # pydantic v2 style
    elif hasattr(response, "dict"):
        payload = response.dict()  # pydantic v1 style
    else:
        payload = {"markdown": getattr(response, "markdown", None)}

    parse_json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    return md_path, parse_json_path


def _pydantic_validate(model_cls: Type[BaseModel], data: Dict[str, Any]) -> BaseModel:
    # Pydantic v2: model_validate; v1: parse_obj
    if hasattr(model_cls, "model_validate"):
        return model_cls.model_validate(data)  # type: ignore[attr-defined]
    return model_cls.parse_obj(data)  # type: ignore[attr-defined]


def extract_via_sdk_from_markdown(
    markdown_path: Path,
    model_cls: Type[BaseModel],
    *,
    extract_model: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Extract using LandingAIADE.extract() with schema from Pydantic, then validate output against the model.
    Returns: (validated_extracted_dict, raw_meta)
    """
    try:
        from landingai_ade import LandingAIADE  # type: ignore
        from landingai_ade.lib import pydantic_to_json_schema  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "Missing dependency 'landingai-ade'. Install with: pip install landingai-ade"
        ) from e

    client = LandingAIADE()
    model = extract_model or os.getenv("LANDING_EXTRACT_MODEL", "extract-latest")

    schema = pydantic_to_json_schema(model_cls)
    resp = client.extract(schema=schema, markdown=markdown_path, model=model)

    print("this is the response")
    print(resp)

    extracted = getattr(resp, "extraction", {}) or {}
    validated_model = _pydantic_validate(model_cls, extracted)

    if hasattr(validated_model, "model_dump"):
        validated = validated_model.model_dump()  # type: ignore[attr-defined]
    else:
        validated = validated_model.dict()  # type: ignore[attr-defined]

    return validated, {
        "mode": "sdk_markdown_extract_pydantic",
        "extraction_metadata": getattr(resp, "extraction_metadata", None),
    }


def _unique_json_path(out_dir: Path, stem: str) -> Path:
    """
    Ensure we don't overwrite if two PDFs share the same stem.
    Produces: <stem>.json, <stem>_1.json, <stem>_2.json, ...
    """
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
    category: str,
) -> Tuple[Path, Path]:
    """
    Get the category-specific output directories for records and markdown.
    Creates them if they don't exist.

    Returns: (records_dir, markdown_dir)
    """
    sanitized = _sanitize_category_name(category)

    records_dir = base_out_dir / sanitized
    markdown_dir = base_markdown_dir / sanitized

    records_dir.mkdir(parents=True, exist_ok=True)
    markdown_dir.mkdir(parents=True, exist_ok=True)

    return records_dir, markdown_dir


def _is_already_processed(pdf_path: Path, base_out_dir: Path, base_markdown_dir: Path) -> bool:
    """
    Check if a PDF has already been processed by looking for its output files.

    Args:
        pdf_path: Path to the PDF file
        base_out_dir: Base output directory for records
        base_markdown_dir: Base markdown directory

    Returns:
        True if the PDF has already been processed (has record + markdown), False otherwise
    """
    stem = _safe_stem(pdf_path)

    # Check all category folders in both records and markdown directories
    # We need at least one record JSON and one markdown file to consider it processed

    # Check for any existing record JSON with this stem (in any category folder)
    record_found = False
    if base_out_dir.exists():
        for category_dir in base_out_dir.iterdir():
            if category_dir.is_dir():
                # Check for exact match or numbered variants (stem.json, stem_1.json, etc.)
                for json_file in category_dir.glob(f"{stem}*.json"):
                    if json_file.stem == stem or json_file.stem.startswith(f"{stem}_"):
                        record_found = True
                        break
            if record_found:
                break

    # Check for existing markdown with this stem (in any category folder)
    markdown_found = False
    if base_markdown_dir.exists():
        for category_dir in base_markdown_dir.iterdir():
            if category_dir.is_dir():
                md_file = category_dir / f"{stem}.md"
                if md_file.exists():
                    markdown_found = True
                    break

    # Consider processed if both record and markdown exist
    return record_found and markdown_found


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Landing.ai POC: VA classify + SDK extract (markdown + pydantic)"
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
        help="Optional path to also write a combined JSONL index (one line per PDF).",
    )

    ap.add_argument(
        "--markdown-dir",
        type=str,
        default=r".\out_new\markdown",
        help="Base directory for markdown files. Category subfolders will be created here.",
    )
    ap.add_argument(
        "--force-parse", action="store_true", help="Re-parse even if markdown file already exists"
    )
    ap.add_argument(
        "--force-reprocess",
        action="store_true",
        help="Re-process files even if they've already been analyzed (overrides skip check)",
    )
    ap.add_argument(
        "--extract-mode",
        choices=["sdk", "va"],
        default="va",
        help="Extraction mode: 'sdk' (SDK extract from markdown) or 'va' (VA ADE Extract from markdown).",
    )

    args = ap.parse_args()

    pdfs = _iter_inputs(args.pdf, args.pdf_dir)

    base_out_dir = Path(args.out).expanduser().resolve()
    base_out_dir.mkdir(parents=True, exist_ok=True)

    out_jsonl_path = Path(args.out_jsonl).expanduser().resolve() if args.out_jsonl else None
    if out_jsonl_path:
        out_jsonl_path.parent.mkdir(parents=True, exist_ok=True)

    base_markdown_dir = Path(args.markdown_dir).expanduser().resolve()
    base_markdown_dir.mkdir(parents=True, exist_ok=True)

    # Track processed files by category for summary
    category_counts: Dict[str, int] = {}
    skipped_count = 0

    jsonl_f = out_jsonl_path.open("w", encoding="utf-8") if out_jsonl_path else None
    try:
        for pdf_path in pdfs:
            # Check if already processed (unless --force-reprocess is set)
            if not args.force_reprocess and _is_already_processed(
                pdf_path, base_out_dir, base_markdown_dir
            ):
                print(f"Skipping (already processed): {pdf_path}")
                skipped_count += 1
                continue

            record: Dict[str, Any] = {"pdf_path": str(pdf_path)}

            try:
                # Step 1: Classify the document
                doc_type, class_raw = classify(pdf_path)
                record["category"] = doc_type
                record["classification_raw"] = class_raw

                # Step 2: Get category-specific output directories
                cat_records_dir, cat_markdown_dir = get_category_output_dirs(
                    base_out_dir, base_markdown_dir, doc_type
                )

                # Step 3: Parse to markdown (in category-specific folder)
                md_path, parse_json_path = parse_to_markdown(
                    pdf_path, cat_markdown_dir, force=args.force_parse
                )

                print(f"Processing PDF: {pdf_path}")
                print(f"  Classified as: {doc_type}")
                print(f"  Markdown path: {md_path}")
                print(f"  Parse JSON path: {parse_json_path}")

                record["markdown_path"] = str(md_path)
                record["parse_json_path"] = (
                    str(parse_json_path) if parse_json_path.exists() else None
                )

                # Step 4: Extract data
                if args.extract_mode == "sdk":
                    model_cls = PYDANTIC_MODELS.get(doc_type, UncategorizedDocumentData)
                    extracted, meta = extract_via_sdk_from_markdown(md_path, model_cls)
                    record["extracted"] = extracted
                    record["extraction_raw"] = meta
                else:
                    # VA mode: ADE Extract FROM MARKDOWN (no PDF upload for extraction)
                    extracted, extract_raw = extract_via_va(
                        pdf_path,
                        doc_type,
                        markdown_path=md_path,
                    )
                    record["extracted"] = extracted
                    record["extraction_raw"] = extract_raw

                # Track category counts
                category_counts[doc_type] = category_counts.get(doc_type, 0) + 1

            except Exception as e:
                record["error"] = f"{type(e).__name__}: {e}"
                # Still try to save to a default folder
                cat_records_dir = base_out_dir / "errors"
                cat_records_dir.mkdir(parents=True, exist_ok=True)

            # Step 5: Save record to category-specific folder
            stem = _safe_stem(pdf_path)
            per_file_path = _unique_json_path(cat_records_dir, stem)
            per_file_path.write_text(
                json.dumps(record, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"  Saved record to: {per_file_path}")

            if jsonl_f:
                jsonl_f.write(json.dumps(record, ensure_ascii=False) + "\n")

    finally:
        if jsonl_f:
            jsonl_f.close()

    # Print summary
    print("\n" + "=" * 60)
    print("PROCESSING SUMMARY")
    print("=" * 60)
    print(f"Total PDFs found: {len(pdfs)}")
    print(f"PDFs skipped (already processed): {skipped_count}")
    print(f"PDFs processed: {len(pdfs) - skipped_count}")
    print(f"Output directory structure: {base_out_dir}")
    print("\nFiles by category:")
    for cat, count in sorted(category_counts.items()):
        sanitized = _sanitize_category_name(cat)
        print(f"  {sanitized}/: {count} file(s)")

    if out_jsonl_path:
        print(f"\nJSONL index: {out_jsonl_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
