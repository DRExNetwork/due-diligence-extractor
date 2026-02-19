# Landing AI POC - Document Classification & Extraction

A proof-of-concept tool for **document classification and structured data extraction** using Landing AI's Vision Agent (VA) and Agentic Document Extraction (ADE) APIs. Designed for processing solar energy project documentation.

## Table of Contents

- [Overview](#overview)
- [How It Works](#how-it-works)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Document Categories](#document-categories)
- [Extraction Schemas](#extraction-schemas)
- [Output Format](#output-format)
- [Key Functions](#key-functions)

---

## Overview

The `landing_ai_poc.py` script automates the processing of PDF documents by:

1. **Classifying** documents into predefined categories using Landing AI VA
2. **Parsing** PDFs to Markdown for better text extraction
3. **Extracting** structured data based on the document type using Pydantic models

---

## How It Works

### Pipeline Flow

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐     ┌──────────────┐
│   PDF File  │ ──▶ │   Classification │ ──▶ │  Parse to MD    │ ──▶ │  Extraction  │
└─────────────┘     │   (VA API)       │     │  (LandingAIADE) │     │  (SDK/VA)    │
                    └──────────────────┘     └─────────────────┘     └──────────────┘
                            │                        │                       │
                            ▼                        ▼                       ▼
                    Document Category         .md + .parse.json      Structured JSON
```

### Step 1: Document Classification

The script sends the PDF to Landing AI's VA endpoint with a classification schema containing all possible document categories. The API returns the detected document type.

### Step 2: Document Parsing

Using the `LandingAIADE` SDK, the PDF is converted to Markdown format. This step:
- Creates `<filename>.md` - Markdown representation of the document
- Creates `<filename>.parse.json` - Full parse metadata
- Supports caching to avoid re-parsing existing documents

### Step 3: Data Extraction

Based on the classified category, structured data is extracted using one of two modes:

| Mode | Description |
|------|-------------|
| **SDK** (default) | Uses `LandingAIADE.extract()` with Pydantic schema validation |
| **VA** | Uses VA ADE Extract API endpoint directly |

---

## Installation

### Prerequisites

```bash
pip install landingai-ade requests pydantic
```

### Dependencies

- `landingai-ade` - Landing AI SDK for document parsing and extraction
- `requests` - HTTP client for API calls
- `pydantic` - Data validation using Python type annotations

---

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `VA_API_KEY` | **Yes** | - | Landing AI API key for authentication |
| `LANDING_PARSE_MODEL` | No | `dpt-2-latest-latest` | Model for PDF parsing |
| `LANDING_EXTRACT_MODEL` | No | `extract-latest` | Model for SDK extraction |
| `VA_EXTRACT_MODEL` | No | `extract-latest` | Model for VA extraction mode |

### Setting the API Key

```bash
# Windows (PowerShell)
$env:VA_API_KEY = "your-api-key-here"

# Windows (CMD)
set VA_API_KEY=your-api-key-here

# Linux/macOS
export VA_API_KEY="your-api-key-here"
```

---

## Usage

### Command Line Interface

```bash
python landing_ai_poc.py [OPTIONS]
```

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--pdf` | string | None | Path to a single PDF file |
| `--pdf-dir` | string | None | Directory to scan recursively for PDFs |
| `--out` | string | `.\out\records` | Base output directory (creates `<Category>/` subfolders) |
| `--out-jsonl` | string | None | Optional path for combined JSONL index |
| `--markdown-dir` | string | `.\out\markdown` | Base markdown directory (creates `<Category>/` subfolders) |
| `--force-parse` | flag | False | Re-parse even if markdown exists |
| `--extract-mode` | choice | `sdk` | Extraction mode: `sdk` or `va` |

### Examples

**Process a single PDF:**
```bash
python landing_ai_poc.py --pdf ./documents/simulation_report.pdf
```

**Process all PDFs in a directory:**
```bash
python landing_ai_poc.py --pdf-dir ./documents --out ./results
```

**Force re-parsing of documents:**
```bash
python landing_ai_poc.py --pdf-dir ./documents --force-parse
```

**Use VA extraction mode:**
```bash
python landing_ai_poc.py --pdf-dir ./documents --extract-mode va
```

**Generate JSONL index file:**
```bash
python landing_ai_poc.py --pdf-dir ./documents --out-jsonl ./results/index.jsonl
```

---

## Document Categories

The script classifies documents into the following **Technical** categories (Sections 1.5-1.13):

| Section | Category | Pydantic Model | Description |
|---------|----------|----------------|-------------|
| 1.5 | Project Simulation Report | `ProjectSimulationReportData` | PVsyst/Helioscope simulation outputs |
| 1.7 | Project Data Main Equipment Sheets | `ProjectDataMainEquipmentSheetsData` | Module/inverter/mounting datasheets |
| 1.8 | Project Basic Engineering | `ProjectBasicEngineeringData` | Memoria Técnica - electrical parameters |
| 1.9 | Project Visit Report | `ProjectVisitReportData` | Site characteristics documentation |
| 1.10 | Project Layout | `ProjectLayoutData` | Technology sizing and layout plans |
| 1.11 | KMZ Polygon | `KmzPoligonData` | Google Earth polygon area data |
| 1.12 | Cable Sizing Calculation | `CableSizingCalculationReportData` | Cable sizing calculations |
| 1.13 | Grounding System Diagram | `GroundingSystemSingleLineDiagramData` | Grounding criteria |
| - | Uncategorized | `UncategorizedDocumentData` | Documents not matching other categories |

---

## Extraction Schemas

### Section 1.5: Project Simulation Report

Extracts data from PVsyst/Helioscope simulation reports.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `project_name` | string | Yes | Project name (e.g., 'Biogemar - Santa Elena') |
| `geographical_coordinates` | string | - | Coordinates (e.g., "-02°06'03", -080°44'47"") |
| `elevation_m` | number | - | Elevation in meters |
| `land_cover` | string | - | Land cover type (water bodies, land, rooftop) |
| `specific_pv_output_kwh_kwp` | number | - | Annual Specific PV Output in kWh/kWp |
| `total_pv_energy_mwh` | number | Yes | Total PV energy output in MWh |
| `performance_ratio_pct` | number | Yes | Performance ratio in % |
| `air_temperature_c` | number | - | Air temperature in Celsius |
| `total_pv_power_mwp` | number | Yes | Total PV power output in MWp |
| `monthly_statistics` | array | - | Monthly stats (12 months) with PVOUT and PR |
| `degradation_rate_year1_pct` | number | - | Degradation Rate year 1 in % |
| `degradation_rate_year2_onwards_pct` | number | - | Degradation Rate year 2+ in % |
| `cumulative_degradation_pct` | number | - | Cumulative Degradation Rate in % |
| `shadow_loss_pct` | number | - | Shadow loss in % (should not exceed 5%) |

**Monthly Statistics Structure:**
| Field | Type | Description |
|-------|------|-------------|
| `month` | string | Month name |
| `pvout_daily_avg_wh_kwp` | number | PVOUT Specific Daily average in Wh/kWp |
| `pvout_monthly_mwh` | number | PVOUT Total Monthly sum in MWh |
| `pr_pct` | number | Performance Ratio in % |

---

### Section 1.7: Project Data Main Equipment Sheets

Extracts specifications for solar modules, inverters, and mounting structures.

**Solar Modules:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `module_brand` | string | Yes | Brand (e.g., JA Solar) |
| `module_model` | string | Yes | Model (e.g., JAM72S30-540/MR) |
| `module_capacity_wdc` | number | - | Capacity in Wdc (e.g., 540) |
| `module_efficiency_pct` | number | - | Efficiency in % (e.g., 20.9) |
| `module_dimensions_mm` | string | - | Dimensions (e.g., '2279 x 1134 mm') |
| `module_technical_warranty_years` | integer | - | Technical warranty in years |
| `module_linear_degradation_warranty_years` | integer | - | Linear degradation warranty in years |
| `module_certifications` | array | - | Certifications (IEC 61215, IEC 61730, etc.) |
| `module_factory_test_date` | string | - | Factory test date if attached |

**Inverter:**
| Field | Type | Description |
|-------|------|-------------|
| `inverter_brand` | string | Brand (e.g., Huawei) |
| `inverter_model` | string | Model (e.g., SUN2000-100KTL-M1) |
| `inverter_ac_capacity_kw` | number | AC capacity in kW |
| `inverter_dc_capacity_kw` | number | DC capacity in kW |
| `inverter_efficiency_pct` | number | Efficiency in % |
| `inverter_mppt_voltage_range_v` | string | MPPT voltage range (e.g., '480-850V') |
| `inverter_mppt_current_range_a` | string | MPPT current range (e.g., '5-20A') |
| `inverter_type` | string | Type (On grid, Off grid, Hybrid) |
| `inverter_technical_warranty_years` | integer | Warranty in years |
| `inverter_certifications` | array | Certifications (IEC 62109, IEC 61727, etc.) |
| `inverter_anti_island_test_date` | string | Anti-island test date if attached |

**Mounting Structure:**
| Field | Type | Description |
|-------|------|-------------|
| `structure_type` | string | Type (coplanar, land mounting, carports, etc.) |
| `structure_material` | string | Material (Anodized Aluminum, Hot deep Galvanized) |
| `structure_warranty_years` | integer | Warranty against corrosion in years |

---

### Section 1.8: Project Basic Engineering

Extracts electrical parameters from Memoria Técnica documents.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `system_type` | string | Yes | Type of system (three-phase 3F, one-phase 1F) |
| `voltage_mains_v` | number | Yes | Voltage mains in V (220, 440, etc.) |
| `load_description` | string | Yes | Description (Industrial, commercial, motors) |
| `load_capacity_kw` | number | Yes | Load capacity in kW |
| `annual_load_energy_kwh` | number | - | Annual energy consumed in kWh |

---

### Section 1.9: Project Visit Report

Extracts site characteristics from visit reports.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `site_description` | string | Yes | Site description (access, obstructions, slope) |
| `installation_area_m2` | number | Yes | Area for installation in m² |
| `installation_location` | string | Yes | Location type (Rooftop, Land, Floating) |

---

### Section 1.10: Project Layout

Extracts technology sizing from layout documents.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `nominal_capacity_kw` | number | Yes | Nominal capacity in kW |
| `peak_capacity_kwp` | number | Yes | Peak capacity in kWp |
| `solar_modules_quantity` | integer | Yes | Number of solar modules |
| `inverters_quantity` | integer | Yes | Number of inverters |
| `strings_per_inverter` | integer | - | Strings per inverter |
| `module_orientation` | string | - | Orientation (e.g., 'Southeast, 15° tilt') |

---

### Section 1.11: KMZ Polygon

Extracts area of intervention from KMZ/KML documents.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `polygon_area_m2` | number | Yes | Polygon surface area in m² from Google Earth |

---

### Section 1.12: Cable Sizing Calculation

Extracts cable sizing table for DC/AC connections.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `cable_entries` | array | Yes | Table of cable sizing entries |

**Cable Entry Structure:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `connection_type` | string | Yes | DC solar connection or AC load connection |
| `sizing` | string | Yes | Conductor sizing (e.g., '35 mm²' or '10 AWG') |
| `cable_type` | string | Yes | Cable type (e.g., 'XLPE type') |
| `voltage_drop_pct` | number | Yes | Voltage drop in % |
| `installation` | string | - | Installation method (underground, etc.) |
| `total_length_m` | number | - | Total length in meters |

---

### Section 1.13: Grounding System Diagram

Extracts grounding criteria from single-line diagrams.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `system_type` | string | Yes | Type (e.g., 'TT system with 3 grounding rods') |
| `resistance_value_ohm` | number | Yes | Resistance value in Ohm |

---

### Uncategorized Documents

For documents that don't match any predefined category.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `summary` | string | Yes | Brief summary of document contents |
| `why_uncategorized` | string | Yes | Reason for not matching categories |

---

## Output Format

### Directory Structure

The script organizes outputs by document category:

```
out/
├── records/
│   ├── Project_Simulation_Report/
│   │   ├── simulation_report_001.json
│   │   └── simulation_report_002.json
│   ├── Project_Data_Main_Equipment_Sheets/
│   │   └── equipment_datasheet.json
│   ├── Project_Basic_Engineering/
│   │   └── memoria_tecnica.json
│   └── Uncategorized/
│       └── unknown_doc.json
├── markdown/
│   ├── Project_Simulation_Report/
│   │   ├── simulation_report_001.md
│   │   ├── simulation_report_001.parse.json
│   │   └── simulation_report_002.md
│   ├── Project_Data_Main_Equipment_Sheets/
│   │   ├── equipment_datasheet.md
│   │   └── equipment_datasheet.parse.json
│   └── ...
```

Category folder names are sanitized (spaces → underscores, special characters removed).

### Per-File JSON Structure

Each processed PDF generates a JSON file with the following structure:

```json
{
  "pdf_path": "/path/to/document.pdf",
  "category": "Project Simulation Report",
  "classification_raw": {
    "data": {
      "extracted_schema": {
        "document_type": "Project Simulation Report"
      }
    }
  },
  "markdown_path": "./out/markdown/Project_Simulation_Report/document.md",
  "parse_json_path": "./out/markdown/Project_Simulation_Report/document.parse.json",
  "extracted": {
    "project_name": "Biogemar - Santa Elena",
    "geographical_coordinates": "-02°06'03\", -080°44'47\"",
    "elevation_m": 5,
    "land_cover": "land",
    "specific_pv_output_kwh_kwp": 1348,
    "total_pv_energy_mwh": 1349,
    "performance_ratio_pct": 78.8,
    "air_temperature_c": 23.7,
    "total_pv_power_mwp": 10,
    "monthly_statistics": [
      {
        "month": "January",
        "pvout_daily_avg_wh_kwp": 4000,
        "pvout_monthly_mwh": 120,
        "pr_pct": 78.9
      }
    ],
    "degradation_rate_year1_pct": 1,
    "degradation_rate_year2_onwards_pct": 0.4,
    "cumulative_degradation_pct": 9,
    "shadow_loss_pct": 1
  },
  "extraction_raw": {
    "mode": "sdk_markdown_extract_pydantic",
    "extraction_metadata": {}
  }
}
```

### JSONL Index Format

When `--out-jsonl` is specified, a JSONL file is created with one JSON record per line, useful for streaming processing or data pipelines.

---

## Key Functions

| Function | Purpose |
|----------|---------|
| `classify(pdf_path)` | Classifies a PDF into a document category |
| `parse_to_markdown(document_path, markdown_dir)` | Converts PDF to Markdown with caching |
| `extract_via_sdk_from_markdown(markdown_path, model_cls)` | SDK-based extraction with Pydantic validation |
| `extract_via_va(pdf_path, doc_type, markdown_path)` | VA API-based extraction |
| `_post(pdf_path, schema)` | HTTP POST to VA endpoint |
| `_post_ade_extract_markdown(markdown_path, schema)` | HTTP POST to ADE Extract endpoint |
| `_sanitize_category_name(category)` | Convert category to safe folder name |
| `get_category_output_dirs(category, out_dir, markdown_dir)` | Get category-specific output paths |

---

## Error Handling

Errors during processing are captured in the output JSON:

```json
{
  "pdf_path": "/path/to/document.pdf",
  "error": "RuntimeError: Missing VA_API_KEY environment variable."
}
```

The script continues processing remaining files even if individual files fail.

---

## API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `https://api.va.landing.ai/v1/tools/agentic-document-analysis` | Classification + PDF-based extraction |
| `https://api.va.landing.ai/v1/ade/extract` | Markdown-based extraction |

---

## End-to-End Workflow

This script is designed to work with `validation_layer.py` for complete document processing:

```bash
# Step 1: Classify and extract documents (outputs organized by category)
python landing_ai_poc.py --pdf-dir ./documents --out ./out/records --markdown-dir ./out/markdown

# Step 2: Validate and merge multi-source extractions
python validation_layer.py --records-dir ./out/records --out ./out/validated
```

**Result:**
```
out/
├── records/                     # Per-file extraction records by category
│   ├── Project_Simulation_Report/
│   └── ...
├── markdown/                    # Parsed markdown files by category
│   ├── Project_Simulation_Report/
│   └── ...
└── validated/                   # Validated/merged extractions by category
    ├── Project_Simulation_Report/
    │   ├── validation_report.json
    │   └── final_extraction.json
    └── ...
```

---

## License

Part of the DDX (Due Diligence Extractor) project.