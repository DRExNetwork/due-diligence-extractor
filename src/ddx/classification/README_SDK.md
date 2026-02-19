# Landing AI SDK Pipeline - Document Classification & Extraction

A document processing pipeline using the **LandingAI ADE SDK** for parsing, classifying, and extracting structured data from PDF documents. Designed for processing solar energy project documentation with **no page limits**.

## Table of Contents

- [Overview](#overview)
- [Key Advantages](#key-advantages)
- [Two-Level Classification System](#two-level-classification-system)
- [How It Works](#how-it-works)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Caching](#caching)
- [Document Categories](#document-categories)
- [Extraction Schemas](#extraction-schemas)
- [Output Format](#output-format)
- [API Reference](#api-reference)
- [Troubleshooting](#troubleshooting)

---

## Overview

The `landing_ai_poc_sdk.py` script processes PDF documents through a three-stage pipeline:

1. **Parse** - Convert PDF to Markdown using `client.parse()` (with caching)
2. **Classify** - Determine document type from Markdown using `client.extract()`
3. **Extract** - Pull structured fields based on category using `client.extract()`

**All operations use the LandingAI SDK**, eliminating the 50-page limit of the legacy `agentic-document-analysis` endpoint.

> **NEW:** The script now supports a **two-level classification system** with Top-Level Categories (e.g., "Company Information", "Technical") and Document Types (e.g., "Certificate of Legal Existence", "Project Simulation Report"). When a top-level category is specified, classification is filtered to only relevant document types for improved accuracy.

---

## Key Advantages

| Feature | Legacy Endpoint | SDK Pipeline |
|---------|-----------------|--------------|
| **Page Limit** | 50 pages  | **Unlimited**  |
| **Classification** | Direct PDF upload | From parsed Markdown |
| **Two-Level Classification** | Not supported | **TopLevelCategory → DocumentType** |
| **Extraction** | Single API call | Schema-based extraction |
| **Caching** | Not supported | **Markdown cached locally**  |
| **Validation** | None | Pydantic model validation |
| **Output Structure** | Flat | **Hierarchical (top_level/doc_type/file)** |

---

## Two-Level Classification System

The pipeline implements a hierarchical classification system:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     TWO-LEVEL CLASSIFICATION                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Level 1: Top-Level Category (User-provided or auto-detected)              │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │ • Company Information    • Technical    • ESG                       │   │
│   │ • Financial              • Legal        • Regulatory                │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                              │
│                              ▼                                              │
│   Level 2: Document Type (AI-classified within the category)                │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │ Company Information:                                                │   │
│   │   • Certificate of Legal Existence                         │   │
│   │   • Shareholders / Beneficial Owners Declaration                    │   │
│   │   • Legal Representative / Power of Attorney                        │   │
│   │                                                                     │   │
│   │ Technical:                                                          │   │
│   │   • Project Simulation Report                                       │   │
│   │   • Project Data Main Equipment Sheets                              │   │
│   │   • Project Basic Engineering                                       │   │
│   │   • Project Layout, etc.                                            │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Top-Level Categories

| Category | Description |
|----------|-------------|
| `Company Information` | Legal entity documents, ownership, representatives |
| `Technical` | Engineering, simulation, equipment documentation |
| `ESG` | Environmental, Social, Governance documents |
| `Financial` | Financial statements, projections, budgets |
| `Legal` | Contracts, agreements, legal opinions |
| `Regulatory` | Permits, licenses, compliance documents |

### Benefits of Two-Level Classification

1. **Improved Accuracy**: When a top-level category is specified, the AI only considers relevant document types
2. **Organized Output**: Files are stored in `top_level/document_type/` hierarchy
3. **Easier Validation**: Related documents are grouped together for conflict resolution
4. **Scalable**: Easy to add new document types under existing categories

---

## How It Works

### Pipeline Flow

```
┌─────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   PDF File  │────▶│  client.parse() │────▶│    Markdown     │────▶│ client.extract()│
│ (any size)  │     │  (with cache)   │     │    Content      │     │ (classification)│
└─────────────┘     └────────┬────────┘     └────────┬────────┘     └────────┬────────┘
                             │                       │                       │
                             ▼                       │                       ▼
                    ┌─────────────────┐              │              ┌─────────────────┐
                    │  Cache Check    │              │              │  Document Type  │
                    │ (.md exists?)   │              │              │   (category)    │
                    └─────────────────┘              │              └────────┬────────┘
                             │                       │                       │
                    ┌────────┴────────┐              ▼                       ▼
                    │                 │     ┌─────────────────┐     ┌─────────────────┐
               Use Cache         Call API   │ client.extract()│◀────│  Select Schema  │
                    │                 │     │ (field extract) │     │  by Category    │
                    └────────┬────────┘     └────────┬────────┘     └─────────────────┘
                             │                       │
                             ▼                       ▼
                    ┌─────────────────┐     ┌─────────────────┐
                    │  Skip Saving    │     │ Extracted Data  │
                    │  (if cached)    │     │   (validated)   │
                    └─────────────────┘     └─────────────────┘
```

### Step-by-Step Process

#### Step 1: Parse Document (with Caching)
```python
from landingai_ade import LandingAIADE

# The function automatically checks for cached markdown
markdown_content, parse_response, cached_md_path, cached_parse_json_path = parse_document(
    Path("document.pdf"),
    model="dpt-2-latest",
    cache_dir=Path("./out_new/markdown"),  # Directory to search for cache
    force=False  # Set to True to bypass cache
)

# If cached_md_path is not None, cache was used (no API call made)
if cached_md_path:
    print("Used cached markdown - no API call!")
```
- **First run**: Calls API, saves markdown to disk
- **Subsequent runs**: Uses cached markdown, skips API call
- Preserves tables, images, and document structure
- **No page limit** - works with documents of any size

#### Step 2: Classify from Markdown
```python
from landingai_ade.lib import pydantic_to_json_schema

class ClassificationResult(BaseModel):
    document_type: DocumentTypeEnum

schema = pydantic_to_json_schema(ClassificationResult)
response = client.extract(
    schema=schema,
    markdown=BytesIO(markdown_content.encode("utf-8")),
)
doc_type = response.extraction.get("document_type")
```
- Uses first ~80k characters of Markdown for classification
- Returns one of the predefined document categories
- **No page limit** - classification runs on text, not PDF

#### Step 3: Extract Structured Fields
```python
# Select schema based on document type
model_cls = PYDANTIC_MODELS[doc_type]
schema = pydantic_to_json_schema(model_cls)

response = client.extract(
    schema=schema,
    markdown=BytesIO(markdown_content.encode("utf-8")),
)
extracted_data = response.extraction
```
- Uses category-specific Pydantic schema
- Validates extracted data against schema
- Returns structured JSON with all fields

---

## Installation

### Prerequisites

```bash
pip install landingai-ade pydantic
```

### Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `landingai-ade` | Latest | SDK for parse and extract |
| `pydantic` | v2.x | Schema definition and validation |

### Verify Installation

```python
from landingai_ade import LandingAIADE
from landingai_ade.lib import pydantic_to_json_schema
print("SDK installed successfully!")
```

---

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `VISION_AGENT_API_KEY` | **Yes*** | - | LandingAI API key (primary) |
| `VA_API_KEY` | **Yes*** | - | LandingAI API key (fallback) |
| `LANDING_PARSE_MODEL` | No | `dpt-2-latest` | Model for PDF parsing |
| `LANDING_EXTRACT_MODEL` | No | `extract-latest` | Model for extraction |

*One of `VISION_AGENT_API_KEY` or `VA_API_KEY` must be set.

### Setting the API Key

```powershell
# Windows (PowerShell)
$env:VISION_AGENT_API_KEY = "your-api-key-here"

# Windows (CMD)
set VISION_AGENT_API_KEY=your-api-key-here

# Linux/macOS
export VISION_AGENT_API_KEY="your-api-key-here"
```

---

## Usage

### Command Line Interface

```bash
python landing_ai_poc_sdk.py [OPTIONS]
```

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--pdf` | string | None | Path to a single PDF file |
| `--pdf-dir` | string | None | Directory to scan recursively for PDFs |
| `--out` | string | `.\out_new\records` | Base output directory for JSON records |
| `--markdown-dir` | string | `.\out_new\markdown` | Base directory for Markdown files |
| `--top-level-category` | string | None | **Top-level category for filtered classification** |
| `--out-jsonl` | string | None | Optional path for combined JSONL index |
| `--parse-model` | string | `dpt-2-latest` | Model for parsing |
| `--extract-model` | string | `extract-latest` | Model for extraction |
| `--force-parse` | flag | False | **Re-parse even if cached Markdown exists** |
| `--force-reprocess` | flag | False | Re-process already processed files |

**Valid `--top-level-category` values:**
- `Company Information`
- `Technical`
- `ESG`
- `Financial`
- `Legal`
- `Regulatory`

### Examples

**Process a single PDF:**
```bash
python landing_ai_poc_sdk.py --pdf ./documents/simulation_report.pdf
```

**Process all PDFs in a directory:**
```bash
python landing_ai_poc_sdk.py --pdf-dir ./documents --out ./results/records --markdown-dir ./results/markdown
```

**Process with a specific top-level category (filtered classification):**
```bash
# Only classify within Company Information document types
python landing_ai_poc_sdk.py --pdf-dir ./company_docs --top-level-category "Company Information"

# Only classify within Technical document types
python landing_ai_poc_sdk.py --pdf-dir ./tech_docs --top-level-category "Technical"
```

**Process a large document (100+ pages):**
```bash
# No special flags needed - SDK handles large documents automatically
python landing_ai_poc_sdk.py --pdf ./large_technical_manual.pdf
```

**Force re-processing of all documents:**
```bash
python landing_ai_poc_sdk.py --pdf-dir ./documents --force-reprocess
```

**Force re-parsing (bypass cache):**
```bash
python landing_ai_poc_sdk.py --pdf-dir ./documents --force-parse
```

**Generate JSONL index:**
```bash
python landing_ai_poc_sdk.py --pdf-dir ./documents --out-jsonl ./results/index.jsonl
```

**Use specific models:**
```bash
python landing_ai_poc_sdk.py --pdf-dir ./documents --parse-model dpt-2-latest --extract-model extract-latest
```

---

## Caching

The pipeline implements intelligent caching for parsed markdown files to avoid redundant API calls.

### How Caching Works

```
┌─────────────────────────────────────────────────────────────┐
│                      CACHING FLOW                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  PDF Input ──▶ Check for cached .md file                    │
│                     │                                       │
│           ┌─────────┴─────────┐                             │
│           │                   │                             │
│      Cache Found         No Cache                           │
│           │                   │                             │
│           ▼                   ▼                             │
│   ┌───────────────┐   ┌───────────────┐                     │
│   │ Load from disk│   │ Call Parse API│                     │
│   │ (no API call) │   │ Save to disk  │                     │
│   └───────────────┘   └───────────────┘                     │
│           │                   │                             │
│           └─────────┬─────────┘                             │
│                     │                                       │
│                     ▼                                       │
│           Continue with Classification                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Cache Behavior

| Scenario | `--force-parse` | Action | API Call |
|----------|-----------------|--------|----------|
| No cache exists | N/A | Parse via API, save files |  Yes |
| Cache exists | `False` (default) | Use cached markdown |  No |
| Cache exists | `True` | Re-parse via API, overwrite |  Yes |

### Cache File Structure

When a document is parsed, two files are created:

```
markdown/
└── Top_Level_Category/
    └── Document_Type/
        ├── document_name.md          # Parsed markdown content
        └── document_name.parse.json  # Parse metadata (chunks, bounding boxes)
```

**Example with two-level structure:**
```
markdown/
├── Company_Information/
│   ├── Certificate_of_Legal_Existence/
│   │   ├── tax_certificate.md
│   │   └── tax_certificate.parse.json
│   └── Shareholders_Declaration/
│       ├── shareholders.md
│       └── shareholders.parse.json
└── Technical/
    └── Project_Simulation_Report/
        ├── pvsyst_report.md
        └── pvsyst_report.parse.json
```

### Cache Search

The caching system searches recursively in the `--markdown-dir` directory, which means:
- It finds cached files even if they're in category subfolders
- A document parsed as "Project Simulation Report" can be found when re-processing

### Benefits of Caching

| Benefit | Description |
|---------|-------------|
| **Cost Savings** | Avoid repeated API calls for the same document |
| **Speed** | Local file reads are much faster than API calls |
| **Reliability** | Work offline with previously parsed documents |
| **Iterative Development** | Re-run classification/extraction without re-parsing |

### Console Output with Caching

**When using cache:**
```
Processing: simulation_report.pdf
  Step 1: Parsing document...
  Using cached markdown: D:\out_new\markdown\Project_Simulation_Report\simulation_report.md
  Step 2: Classifying document...
  Classifying document with model: extract-latest
  → Classified as: Project Simulation Report
  → Using existing markdown: D:\out_new\markdown\Project_Simulation_Report\simulation_report.md
  Step 3: Extracting fields...
  → Record saved: D:\out_new\records\Project_Simulation_Report\simulation_report.json
```

**When parsing fresh:**
```
Processing: new_document.pdf
  Step 1: Parsing document...
  Parsing document with model: dpt-2-latest
  Step 2: Classifying document...
  Classifying document with model: extract-latest
  → Classified as: Project Simulation Report
  → Markdown saved: D:\out_new\markdown\Project_Simulation_Report\new_document.md
  Step 3: Extracting fields...
  → Record saved: D:\out_new\records\Project_Simulation_Report\new_document.json
```

### Force Re-parsing

To force the system to re-parse documents (ignoring cache):

```bash
# Re-parse a single document
python landing_ai_poc_sdk.py --pdf ./document.pdf --force-parse

# Re-parse all documents in a directory
python landing_ai_poc_sdk.py --pdf-dir ./documents --force-parse
```

---

## Document Categories

The script uses a two-level classification system. When `--top-level-category` is provided, classification is filtered to only relevant document types.

### Top-Level Categories

| Top-Level Category | Enum Value |
|--------------------|------------|
| Company Information | `COMPANY_INFORMATION` |
| Technical | `TECHNICAL` |
| ESG | `ESG` |
| Financial | `FINANCIAL` |
| Legal | `LEGAL` |
| Regulatory | `REGULATORY` |

### Document Types by Category

**Company Information:**

| Document Type | Enum Value | Description |
|---------------|------------|-------------|
| Certificate of Legal Existence | `CERTIFICATE_OF_LEGAL_EXISTENCE` | Legal entity certificates |
| Shareholders / Beneficial Owners Declaration | `SHAREHOLDERS_DECLARATION` | Ownership structure |
| Legal Representative / Power of Attorney | `LEGAL_REPRESENTATIVE_APPOINTMENT` | Authority documents |

**Technical:**

| Document Type | Enum Value | Description |
|---------------|------------|-------------|
| Project Simulation Report | `PROJECT_SIMULATION_REPORT` | PVsyst/Helioscope outputs |
| Project Data Main Equipment Sheets | `PROJECT_DATA_EQUIPMENT_SHEETS` | Module/inverter datasheets |
| Project Basic Engineering | `PROJECT_BASIC_ENGINEERING` | Memoria Técnica documents |
| Project Visit Report | `PROJECT_VISIT_REPORT` | Site visit documentation |
| Project Layout | `PROJECT_LAYOUT` | Technology sizing plans |
| KMZ Polygon | `KMZ_POLIGON` | Google Earth area data |
| Cable Sizing Calculation Report | `CABLE_SIZING_CALCULATION` | Cable calculations |
| Grounding System / Single Line Diagram | `GROUNDING_SYSTEM_DIAGRAM` | Electrical diagrams |
| Uncategorized Document | `UNCATEGORIZED` | Unmatched documents |

---

## Extraction Schemas

Each document type has a dedicated Pydantic model defining the fields to extract.

### Company Information Schemas

#### Certificate of Legal Existence

```python
class LegalInformation(BaseModel):
    company_name: str
    tax_id: str
    company_type: Optional[str]       # e.g., "Sociedad Anónima", "LLC"
    registration_number: Optional[str]
    registration_date: Optional[str]
    registered_address: Optional[str]
    legal_status: Optional[str]       # "Active", "Inactive"
    capital_stock: Optional[str]
    business_purpose: Optional[str]
    certificate_date: Optional[str]
    issuing_authority: Optional[str]
```

#### Shareholders / Beneficial Owners Declaration

```python
class ShareholderEntry(BaseModel):
    name: str
    ownership_percentage: Optional[float]
    shareholder_type: Optional[str]   # "Individual", "Corporate"
    nationality: Optional[str]
    id_number: Optional[str]

class ShareholderStructure(BaseModel):
    company_name: str
    shareholders: List[ShareholderEntry]
    total_shares: Optional[int]
    declaration_date: Optional[str]
    beneficial_owner_declared: Optional[bool]
```

#### Legal Representative / Power of Attorney

```python
class LegalRepresentation(BaseModel):
    company_name: str
    representative_name: str
    representative_role: Optional[str]  # "General Manager", "CEO"
    id_number: Optional[str]
    nationality: Optional[str]
    appointment_date: Optional[str]
    powers_granted: Optional[List[str]]
    limitations: Optional[str]
    document_date: Optional[str]
    notary_info: Optional[str]
```

### Technical Schemas

#### Project Simulation Report

```python
class ProjectSimulationReportData(BaseModel):
    project_name: str
    geographical_coordinates: Optional[str]
    elevation_m: Optional[float]
    land_cover: Optional[str]
    specific_pv_output_kwh_kwp: Optional[float]
    total_pv_energy_mwh: float
    performance_ratio_pct: float
    air_temperature_c: Optional[float]
    total_pv_power_mwp: float
    monthly_statistics: Optional[List[MonthlyStatistic]]
    degradation_rate_year1_pct: Optional[float]
    degradation_rate_year2_onwards_pct: Optional[float]
    cumulative_degradation_pct: Optional[float]
    shadow_loss_pct: Optional[float]
```

### Project Data Main Equipment Sheets

```python
class ProjectDataMainEquipmentSheetsData(BaseModel):
    # Solar Modules
    module_brand: str
    module_model: str
    module_capacity_wdc: Optional[float]
    module_efficiency_pct: Optional[float]
    module_dimensions_mm: Optional[str]
    module_technical_warranty_years: Optional[int]
    module_certifications: Optional[List[str]]
    
    # Inverter
    inverter_brand: Optional[str]
    inverter_model: Optional[str]
    inverter_ac_capacity_kw: Optional[float]
    inverter_dc_capacity_kw: Optional[float]
    inverter_efficiency_pct: Optional[float]
    
    # Mounting Structure
    structure_type: Optional[str]
    structure_material: Optional[str]
    structure_warranty_years: Optional[int]
```

### Cable Sizing Calculation Report

```python
class CableEntry(BaseModel):
    connection_type: str
    sizing: str
    cable_type: str
    voltage_drop_pct: float
    installation: Optional[str]
    total_length_m: Optional[float]

class CableSizingCalculationReportData(BaseModel):
    cable_entries: List[CableEntry]
```

*See the source code for complete schema definitions.*

---

## Output Format

### Directory Structure

Output files are organized in a **two-level hierarchy**: `top_level_category/document_type/`

```
out_new/
├── records/                              # JSON extraction records
│   ├── Company_Information/              # Top-level category
│   │   ├── Certificate_of_Legal_Existence/   # Document type
│   │   │   └── tax_cert_001.json
│   │   ├── Shareholders_Declaration/
│   │   │   └── shareholders.json
│   │   └── Legal_Representative_Appointment/
│   │       └── legal_rep.json
│   ├── Technical/
│   │   ├── Project_Simulation_Report/
│   │   │   ├── simulation_001.json
│   │   │   └── simulation_002.json
│   │   ├── Project_Data_Main_Equipment_Sheets/
│   │   │   └── datasheet_001.json
│   │   └── Cable_Sizing_Calculation_Report/
│   │       └── cable_calc.json
│   └── errors/
│       └── failed_document.json
│
└── markdown/                             # Parsed Markdown files (CACHE)
    ├── Company_Information/
    │   ├── Certificate_of_Legal_Existence/
    │   │   ├── tax_cert_001.md
    │   │   └── tax_cert_001.parse.json
    │   └── Shareholders_Declaration/
    │       ├── shareholders.md
    │       └── shareholders.parse.json
    └── Technical/
        ├── Project_Simulation_Report/
        │   ├── simulation_001.md
        │   ├── simulation_001.parse.json
        │   └── simulation_002.md
        └── Project_Data_Main_Equipment_Sheets/
            ├── datasheet_001.md
            └── datasheet_001.parse.json
```

### Per-File JSON Structure

```json
{
  "pdf_path": "D:/documents/simulation_report.pdf",
  "top_level_category": "Technical",
  "document_type": "Project Simulation Report",
  "classification_raw": {
    "extraction": {
      "document_type": "Project Simulation Report"
    },
    "extraction_metadata": {...}
  },
  "markdown_path": "D:/out_new/markdown/Technical/Project_Simulation_Report/simulation_report.md",
  "parse_json_path": "D:/out_new/markdown/Technical/Project_Simulation_Report/simulation_report.parse.json",
  "extracted": {
    "project_name": "Solar Plant Alpha",
    "total_pv_energy_mwh": 1500.5,
    "performance_ratio_pct": 82.3,
    "total_pv_power_mwp": 1.2,
    "monthly_statistics": [
      {
        "month": "January",
        "pvout_daily_avg_wh_kwp": 4200,
        "pvout_monthly_mwh": 130.2,
        "pr_pct": 81.5
      }
    ]
  },
  "extraction_raw": {
    "extraction": {...},
    "extraction_metadata": {...},
    "metadata": {...}
  }
}
```

---

## API Reference

### Core Functions

#### `parse_document(document_path, *, model=None, cache_dir=None, force=False)`
Parse a PDF to Markdown using the SDK with caching support.

```python
markdown_content, parse_response, cached_md_path, cached_parse_json_path = parse_document(
    Path("document.pdf"),
    model="dpt-2-latest",
    cache_dir=Path("./out_new/markdown"),
    force=False
)

# Check if cache was used
if cached_md_path is not None:
    print("Used cache - no API call made!")
```

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `document_path` | `Path` | Required | Path to the PDF document |
| `model` | `str` | `dpt-2-latest` | Parse model to use |
| `cache_dir` | `Path` | `None` | Directory to search for cached markdown |
| `force` | `bool` | `False` | Force re-parsing even if cache exists |

**Returns:** `Tuple[str, Any, Optional[Path], Optional[Path]]`
- `markdown_content`: The parsed markdown text
- `parse_response`: Parse response object (or `CachedParseResponse` if from cache)
- `cached_md_path`: Path to cached .md file (or `None` if freshly parsed)
- `cached_parse_json_path`: Path to cached .parse.json file (or `None` if freshly parsed)

---

#### `classify_from_markdown(markdown_content, *, model=None, max_chars=80000)`
Classify document type from Markdown content.

```python
doc_type, raw_response = classify_from_markdown(
    markdown_content,
    model="extract-latest",
    max_chars=80000
)
```

**Returns:** `Tuple[str, Dict[str, Any]]`

---

#### `classify_from_markdown_with_category(markdown_content, top_level_category, *, model=None)`
Classify document type from Markdown content within a specific top-level category.

```python
from ddx.classification.categories import TopLevelCategory

doc_type, raw_response = classify_from_markdown_with_category(
    markdown_content,
    TopLevelCategory.COMPANY_INFORMATION,
    model="extract-latest"
)
```

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `markdown_content` | `str` | Required | Markdown content from parse |
| `top_level_category` | `TopLevelCategory` | Required | Top-level category enum |
| `model` | `str` | `extract-latest` | Extract model to use |

**Returns:** `Tuple[str, Dict[str, Any]]`

---

#### `get_document_types_for_category(top_level: TopLevelCategory)`
Get all document types that belong to a top-level category.

```python
from ddx.classification.categories import TopLevelCategory

doc_types = get_document_types_for_category(TopLevelCategory.COMPANY_INFORMATION)
# Returns: [DocumentType.CERTIFICATE_OF_LEGAL_EXISTENCE, DocumentType.SHAREHOLDERS_DECLARATION, ...]
```

---

#### `build_classification_schema_for_category(top_level: TopLevelCategory)`
Dynamically build a classification schema for a specific top-level category.

```python
from ddx.classification.categories import TopLevelCategory

schema_cls = build_classification_schema_for_category(TopLevelCategory.TECHNICAL)
# Returns: A Pydantic BaseModel class with filtered DocumentType enum
```

---

#### `extract_fields(markdown_content, doc_type, *, model=None)`
Extract structured fields based on document type.

```python
extracted_data, raw_response = extract_fields(
    markdown_content,
    "Project Simulation Report",
    model="extract-latest"
)
```

**Returns:** `Tuple[Dict[str, Any], Dict[str, Any]]`

---

#### `process_document(pdf_path, base_out_dir, base_markdown_dir, **kwargs)`
Process a single document through the full pipeline with caching.

```python
from ddx.classification.categories import TopLevelCategory

record = process_document(
    Path("document.pdf"),
    Path("./out/records"),
    Path("./out/markdown"),
    top_level_category=TopLevelCategory.COMPANY_INFORMATION,  # Optional
    parse_model="dpt-2-latest",
    extract_model="extract-latest",
    force_parse=False  # Set to True to bypass cache
)
```

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `pdf_path` | `Path` | Required | Path to the PDF document |
| `base_out_dir` | `Path` | Required | Base output directory for records |
| `base_markdown_dir` | `Path` | Required | Base directory for markdown |
| `top_level_category` | `TopLevelCategory` | `None` | Optional top-level category for filtered classification |
| `parse_model` | `str` | `dpt-2-latest` | Parse model to use |
| `extract_model` | `str` | `extract-latest` | Extract model to use |
| `force_parse` | `bool` | `False` | Force re-parsing even if cache exists |

**Returns:** `Dict[str, Any]`

---

### Helper Functions

| Function | Purpose |
|----------|---------|
| `_get_client()` | Get authenticated LandingAI SDK client |
| `_find_cached_markdown()` | Search for cached .md and .parse.json files |
| `save_parse_outputs()` | Save Markdown and parse JSON to disk |
| `get_category_output_dirs()` | Get hierarchical output paths (top_level/doc_type) |
| `get_document_types_for_category()` | Get document types for a top-level category |
| `build_classification_schema_for_category()` | Build filtered classification schema |
| `_safe_stem()` | Sanitize filename for output |
| `_sanitize_category_name()` | Convert category to safe folder name |
| `_is_already_processed()` | Check if PDF was already processed (recursive search) |

### Helper Classes

#### `CachedParseResponse`
Wrapper class for cached parse response data, providing the same interface as the SDK response.

```python
class CachedParseResponse:
    def __init__(self, data: Dict[str, Any], markdown: str):
        self._data = data
        self.markdown = markdown
        self.chunks = data.get("chunks", [])
    
    def model_dump(self) -> Dict[str, Any]: ...
    def dict(self) -> Dict[str, Any]: ...
```

---

## Troubleshooting

### Common Errors

#### Missing API Key
```
RuntimeError: Missing API key. Set VISION_AGENT_API_KEY or VA_API_KEY environment variable.
```
**Solution:** Set the environment variable with your LandingAI API key.

#### Missing SDK
```
RuntimeError: Missing dependency 'landingai-ade'. Install with: pip install landingai-ade
```
**Solution:** Install the SDK: `pip install landingai-ade`

#### Pydantic Validation Warnings
```
⚠️  Validation warning: 1 validation error for ProjectSimulationReportData
```
**Note:** This is a warning, not an error. The raw extraction data is still saved.

#### Cache Not Being Used
If caching doesn't seem to work:
1. Verify the `--markdown-dir` path is correct
2. Check that the .md file exists with the expected stem name
3. Use `--force-parse` to explicitly bypass cache and re-parse

### Debug Mode

Enable verbose output by checking the console during processing:

**With caching (no API call):**
```
============================================================
Landing.ai SDK Pipeline (No Page Limit)
============================================================
PDFs to process: 5
Output directory: D:\out_new\records
Markdown directory: D:\out_new\markdown
============================================================

Processing: simulation_report.pdf
  Step 1: Parsing document...
  Using cached markdown: D:\out_new\markdown\Project_Simulation_Report\simulation_report.md
  Step 2: Classifying document...
  Classifying document with model: extract-latest
  → Classified as: Project Simulation Report
  → Using existing markdown: D:\out_new\markdown\Project_Simulation_Report\simulation_report.md
  Step 3: Extracting fields...
  Extracting fields with model: extract-latest
  → Record saved: D:\out_new\records\Project_Simulation_Report\simulation_report.json
```

**Without caching (API call):**
```
Processing: new_document.pdf
  Step 1: Parsing document...
  Parsing document with model: dpt-2-latest
  Step 2: Classifying document...
  Classifying document with model: extract-latest
  → Classified as: Project Simulation Report
  → Markdown saved: D:\out_new\markdown\Project_Simulation_Report\new_document.md
  Step 3: Extracting fields...
  Extracting fields with model: extract-latest
  → Record saved: D:\out_new\records\Project_Simulation_Report\new_document.json
```

---

## Integration with Validation Layer

This script works with `validation_layer.py` for complete document processing:

```bash
# Step 1: Parse, classify, and extract (SDK pipeline)
# With top-level category filtering
python landing_ai_poc_sdk.py \
    --pdf-dir ./company_documents \
    --top-level-category "Company Information" \
    --out ./out_new/records \
    --markdown-dir ./out_new/markdown

# Or without filtering (classifies across all document types)
python landing_ai_poc_sdk.py \
    --pdf-dir ./documents \
    --out ./out_new/records \
    --markdown-dir ./out_new/markdown

# Step 2: Validate and merge multi-source extractions
# Filter by top-level category
python validation_layer.py \
    --records-dir ./out_new/records \
    --top-level-filter Company_Information \
    --out ./out_new/validated

# Or filter by document type
python validation_layer.py \
    --records-dir ./out_new/records \
    --doc-type-filter Certificate_of_Legal_Existence \
    --out ./out_new/validated
```

---

## Comparison: Legacy vs SDK Pipeline

| Aspect | Legacy (`landing_ai_poc.py`) | SDK (`landing_ai_poc_sdk.py`) |
|--------|------------------------------|-------------------------------|
| Classification | `POST /v1/tools/agentic-document-analysis` | `client.extract()` on Markdown |
| Page Limit | **50 pages** | **None** |
| Parsing | `LandingAIADE.parse()` | `client.parse()` |
| Extraction | HTTP endpoint or SDK | `client.extract()` |
| **Caching** | Not supported | **Markdown cached locally**  |
| Dependencies | `requests`, `landingai-ade` | `landingai-ade` only |

---

## License

Part of the DDX (Due Diligence Extractor) project.