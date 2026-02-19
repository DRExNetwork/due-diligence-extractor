# Validation Layer - Multi-Source Field Resolution

A reasoning-based validation module that resolves conflicting field values extracted from multiple source documents using GPT-4o-mini.

## Table of Contents

- [Overview](#overview)
- [Problem Statement](#problem-statement)
- [Two-Level Hierarchy Support](#two-level-hierarchy-support)
- [How It Works](#how-it-works)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Directory Structure](#directory-structure)
- [Data Structures](#data-structures)
- [Output Format](#output-format)
- [Integration](#integration)
- [API Reference](#api-reference)
- [Error Handling](#error-handling)
- [Best Practices](#best-practices)
- [End-to-End Workflow](#end-to-end-workflow)

---

## Overview

When processing multiple PDF documents of the same document type (e.g., multiple "Certificate of Legal Existence" documents), the same field may have different values extracted from different files. The **Validation Layer** uses a reasoning model (GPT-4o-mini) to:

1. **Discover** document type folders produced by `landing_ai_poc_sdk.py` (organized hierarchically by top-level category)
2. **Analyze** all candidate values for conflicting fields
3. **Select** the most reliable value based on context and evidence
4. **Provide** detailed justification for each selection
5. **Flag** any inconsistencies or concerns
6. **Output** validated extractions organized by top-level category and document type

**Key Features:**
- **Two-level hierarchy support**: Works with `top_level_category/document_type/` folder structure
- **Direct bounding box extraction**: Reads from `parse.json` files using `references` field
- **Flexible filtering**: Filter by `--top-level-filter` or `--doc-type-filter`
- **No separate evidence generation needed**

---

## Problem Statement

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Document A     │     │  Document B     │     │  Document C     │
│  project_name:  │     │  project_name:  │     │  project_name:  │
│  "Solar Farm"   │     │  "Solar Farm A" │     │  "SolarFarm"    │
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │   VALIDATION LAYER     │
                    │   (GPT-4o-mini)        │
                    │                        │
                    │   Analyzes context,    │
                    │   selects best value,  │
                    │   provides reasoning   │
                    └────────────┬───────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │  Selected Value:       │
                    │  "Solar Farm A"        │
                    │                        │
                    │  Justification:        │
                    │  "Most complete name,  │
                    │  found in header..."   │
                    └────────────────────────┘
```

---

## Two-Level Hierarchy Support

The validation layer works with the two-level classification system:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                   HIERARCHICAL VALIDATION                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   records-dir/                                                          │
│   ├── Company_Information/        ← Top-Level Category (Level 1)        │
│   │   ├── Certificate_of_Legal_Existence/  ← Document Type (Level 2)  │
│   │   │   ├── file1.json             ← Validation runs here          │
│   │   │   └── file2.json                (when 2+ files exist)         │
│   │   └── Shareholders_Declaration/                                     │
│   │       └── shareholders.json      ← Single file = no validation    │
│   └── Technical/                                                        │
│       ├── Project_Simulation_Report/                                    │
│       │   ├── sim1.json              ← Validation runs here          │
│       │   └── sim2.json                                                 │
│       └── Project_Layout/                                               │
│           └── layout.json                                               │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Concepts

| Concept | Description |
|---------|-------------|
| **Top-Level Category** | First level folder (e.g., `Company_Information`, `Technical`) |
| **Document Type** | Second level folder (e.g., `Certificate_of_Legal_Existence`) |
| **Validation Scope** | Only within same document type folder (files with same schema) |
| **Conflict Detection** | Compares field values across files in same document_type folder |

### Validation Logic

- Validation **ONLY** happens when **2+ files** exist in the same `document_type` folder
- Files in the same `document_type` folder share the same extraction schema
- The validator resolves conflicts when the same field has different values across files
- Single-file document types are passed through with confidence 1.0

---

## How It Works

### Step 1: Document Type Folder Discovery

The system automatically discovers document type folders in the hierarchical structure:
- Scans `--records-dir` for top-level category folders (first level)
- Within each top-level, scans for document type folders (second level)
- Only processes folders containing `.json` files at the document type level
- Can filter by `--top-level-filter` or `--doc-type-filter`

### Step 2: Conflict Detection

For each category folder, the system:
- Loads all extraction records (`.json` files)
- Identifies fields where multiple source files provide different values
- Creates a `FieldConflict` object for each conflicting field

### Step 3: Evidence Collection (Direct from parse.json)

For each conflicting field, the system now **directly extracts** evidence from the extraction record:

1. **Reads `parse_json_path`** from the extraction record
2. **Loads the `parse.json` file** which contains all chunk data
3. **Uses `references`** field from `extraction_metadata` to locate relevant chunks
4. **Extracts bounding boxes** and page numbers from chunk `grounding` data

**Example Flow:**
```python
# From extraction record (1719458255520.json)
"extraction_metadata": {
  "module_brand": {
    "references": ["4ab994ee-1537-493a-885b-7eb2533c4738"]
  }
}

# System loads parse.json and finds:
"chunks": [
  {
    "id": "4ab994ee-1537-493a-885b-7eb2533c4738",
    "grounding": {
      "page": 0,
      "box": {"left": 0.0906, "top": 0.0549, "right": 0.3220, "bottom": 0.1384}
    }
  }
]

# Creates EvidenceLocation with this data
```

**No separate evidence generation step needed!**

For each conflicting field, the system collects:
- **Extracted value** from each source
- **Source file** name and path
- **Raw extracted text** context from markdown
- **Page number** and **bounding box** coordinates (from parse.json)
- **Chunk IDs** (reference IDs)
- **Confidence score** from extraction metadata

### Step 4: Reasoning Prompt

A detailed prompt is sent to GPT-5-nano containing:
```
Document Category: Project Simulation Report
Field: project_name
Field Description: Name of the solar project

Candidate 1:
  Source: simulation_report_a.pdf
  Value: "Solar Farm Alpha"
  Extracted Text: "Project: Solar Farm Alpha\nLocation: ..."
  Locations: Page 0, Box: (0.09, 0.05, 0.32, 0.14)

Candidate 2:
  Source: simulation_report_b.pdf
  Value: "Solar Farm"
  Extracted Text: "Solar Farm\n..."
  Locations: Page 1, Box: (0.15, 0.20, 0.28, 0.25)
```

### Step 5: Selection & Justification

The model returns:
- **Selected candidate index** (0-based)
- **Confidence score** (0.0 to 1.0)
- **Detailed justification** explaining the choice
- **Red flags** or concerns identified

### Reasoning Factors

The model considers:
- **Completeness**: Is the value complete or truncated?
- **Format consistency**: Does it match expected format/units?
- **Source appropriateness**: Is this the right document type for this field?
- **OCR quality**: Any signs of extraction errors?
- **Technical plausibility**: Does the value make sense technically?
- **Occurrence frequency**: Values appearing in multiple locations are more reliable
- **Context richness**: More surrounding text provides better confidence

---

## Installation

### Prerequisites

```bash
pip install openai pydantic
```

### Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `openai` | ≥1.0 | GPT-5-nano API client |
| `pydantic` | ≥2.0 | Data validation and serialization |

---

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | **Yes** | - | OpenAI API key for GPT-5-nano |

### Setting the API Key

```bash
# Windows (PowerShell)
$env:OPENAI_API_KEY = "your-api-key-here"

# Windows (CMD)
set OPENAI_API_KEY=your-api-key-here

# Linux/macOS
export OPENAI_API_KEY="your-api-key-here"
```

---

## Usage

### Command Line Interface

```bash
python validation_layer.py [OPTIONS]
```

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--records-dir` | string | **Required** | Base directory containing top_level/doc_type subfolders with extraction JSON files |
| `--out` | string | `.\out_sdk\validated` | Base output directory (creates `top_level/doc_type/` subfolders) |
| `--model` | string | `gpt-5-nano-2025-08-07` | Model to use for reasoning |
| `--top-level-filter` | string | None | Only process this top-level category folder (folder name) |
| `--doc-type-filter` | string | None | Only process this document type folder (folder name) |

### Examples

**Process all categories and document types:**
```bash
python validation_layer.py \
  --records-dir ./out/records \
  --out ./out/validated
```

**Filter by top-level category:**
```bash
python validation_layer.py \
  --records-dir ./out/records \
  --top-level-filter "Company_Information" \
  --out ./out/validated
```

**Filter by document type:**
```bash
python validation_layer.py \
  --records-dir ./out/records \
  --doc-type-filter "Certificate_of_Legal_Existence" \
  --out ./out/validated
```

**Combine filters (specific document type in specific category):**
```bash
python validation_layer.py \
  --records-dir ./out/records \
  --top-level-filter "Technical" \
  --doc-type-filter "Project_Simulation_Report" \
  --out ./out/validated
```

**Use different reasoning model:**
```bash
python validation_layer.py \
  --records-dir ./out/records \
  --model gpt-4o
```

---

## Directory Structure

### Input Structure (from landing_ai_poc_sdk.py)

```
out/
├── records/                                    ← --records-dir input
│   ├── Company_Information/                    ← Top-level category
│   │   ├── Certificate_of_Legal_Existence/    ← Document type
│   │   │   ├── tax_cert_001.json              ← Contains parse_json_path
│   │   │   └── tax_cert_002.json              ← Validation runs here (2 files)
│   │   ├── Shareholders_Declaration/
│   │   │   └── shareholders.json              ← No validation (1 file)
│   │   └── Legal_Representative_Appointment/
│   │       └── legal_rep.json
│   ├── Technical/
│   │   ├── Project_Simulation_Report/
│   │   │   ├── simulation_001.json
│   │   │   ├── simulation_002.json
│   │   │   └── simulation_003.json            ← Validation runs here (3 files)
│   │   └── Project_Data_Main_Equipment_Sheets/
│   │       ├── datasheet_001.json
│   │       └── datasheet_002.json
│   └── errors/
│       └── failed.json
│
└── markdown/                                   ← Referenced by records
    ├── Company_Information/
    │   ├── Certificate_of_Legal_Existence/
    │   │   ├── tax_cert_001.md
    │   │   ├── tax_cert_001.parse.json        ← Bounding boxes read from here
    │   │   └── tax_cert_002.md
    │   └── Shareholders_Declaration/
    │       └── shareholders.md
    └── Technical/
        ├── Project_Simulation_Report/
        │   ├── simulation_001.md
        │   ├── simulation_001.parse.json
        │   └── simulation_002.md
        └── Project_Data_Main_Equipment_Sheets/
            └── datasheet_001.md
```

### Output Structure (from validation_layer.py)

```
out/validated/                                  ← --out directory
├── Company_Information/                        ← Top-level category
│   ├── Certificate_of_Legal_Existence/        ← Document type
│   │   ├── validation_report.json             ← Detailed reasoning (if conflicts)
│   │   └── final_extraction.json              ← Merged validated data
│   ├── Shareholders_Declaration/
│   │   └── final_extraction.json              ← No conflicts, passed through
│   └── Legal_Representative_Appointment/
│       └── final_extraction.json
├── Technical/
│   ├── Project_Simulation_Report/
│   │   ├── validation_report.json
│   │   └── final_extraction.json
│   └── Project_Data_Main_Equipment_Sheets/
│       ├── validation_report.json
│       └── final_extraction.json
└── errors/
    └── final_extraction.json
```

---

## Data Structures

### Input: Extraction Records

Location: `./out/records/<TopLevelCategory>/<DocumentType>/<filename>.json`

```json
{
  "pdf_path": "D:/documents/tax_certificate_001.pdf",
  "top_level_category": "Company Information",
  "document_type": "Certificate of Legal Existence",
  "parse_json_path": "D:/out/markdown/Company_Information/Certificate_of_Legal_Existence/tax_certificate_001.parse.json",
  "extracted": {
    "company_name": "Solar Energy Corp",
    "tax_id": "12345678901",
    "registration_date": "2020-01-15"
  },
  "extraction_raw": {
    "mode": "va_ade_extract",
    "extraction_metadata": {
      "company_name": {
        "extracted_text": "Company Name: Solar Energy Corp\nTax ID: 12345678901",
        "references": [
          "4ab994ee-1537-493a-885b-7eb2533c4738",
          "0b7c2090-f726-414e-a998-cd2f0d2f72d9"
        ],
        "confidence": 0.95
      }
    }
  }
}
```

### Input: Parse.json (Auto-loaded)

Location: Referenced by `parse_json_path` in extraction record

```json
{
  "chunks": [
    {
      "id": "4ab994ee-1537-493a-885b-7eb2533c4738",
      "text": "Project Name: Solar Farm Alpha",
      "grounding": {
        "page": 0,
        "box": {
          "left": 0.0905836671590805,
          "top": 0.0549488365650177,
          "right": 0.3220455050468445,
          "bottom": 0.13841994106769562
        }
      }
    },
    {
      "id": "0b7c2090-f726-414e-a998-cd2f0d2f72d9",
      "text": "Location: Ecuador",
      "grounding": {
        "page": 0,
        "box": {
          "left": 0.0906,
          "top": 0.1500,
          "right": 0.2500,
          "bottom": 0.1800
        }
      }
    }
  ]
}
```

### Core Data Classes

| Class | Purpose |
|-------|---------|
| `BoundingBox` | Normalized coordinates (0-1) for value location in PDF |
| `EvidenceLocation` | Page number, bounding box, chunk ID |
| `FieldCandidate` | A single candidate value with all its evidence and metadata |
| `FieldConflict` | Groups all conflicting candidates for one field (includes `top_level_category`, `document_type`) |
| `ValidationResult` | Result of validating a single field conflict |
| `ValidationReport` | Complete report for all conflicts (includes `top_level_category`, `document_type`) |
| `ValidatedFieldOutput` | Final output structure for one field with provenance |
| `FinalExtractionOutput` | Complete merged extraction (includes `top_level_category`, `document_type`) |

---

## Output Format

### Final Extraction Output

Location: `./out/validated/<TopLevelCategory>/<DocumentType>/final_extraction.json`

```json
{
  "pdf_path": "[2 sources]",
  "top_level_category": "Company Information",
  "top_level_folder": "Company_Information",
  "document_type": "Certificate of Legal Existence",
  "document_type_folder": "Certificate_of_Legal_Existence",
  "sources": [
    "D:/documents/tax_certificate_001.pdf",
    "D:/documents/tax_certificate_002.pdf"
  ],
  "extracted": {
    "company_name": {
      "field_name": "company_name",
      "value": "Solar Energy Corporation",
      "source_file": "D:/documents/tax_certificate_001.pdf",
      "source_filename": "tax_certificate_001.pdf",
      "locations": [
        {
          "page": 0,
          "box": {
            "left": 0.09058366715908,
            "top": 0.054948836565018,
            "right": 0.322045505046845,
            "bottom": 0.138419941067696
          },
          "chunk_id": "4ab994ee-1537-493a-885b-7eb2533c4738",
          "image_path": null
        }
      ],
      "confidence_score": 0.95,
      "justification": "Selected 'Solar Energy Corporation' from tax_certificate_001.pdf because:\n1. It appears in the official certificate header\n2. The full legal name includes 'Corporation' suffix\n3. Alternative value 'Solar Energy Corp' appears to be truncated",
      "alternatives": [
        {
          "value": "Solar Energy Corp",
          "source_file": "D:/documents/tax_certificate_002.pdf",
          "source_filename": "tax_certificate_002.pdf",
          "locations": [{"page": 1, "box": {...}}]
        }
      ],
      "flags": []
    },
    "tax_id": {
      "field_name": "tax_id",
      "value": "12345678901",
      "source_file": "D:/documents/tax_certificate_001.pdf",
      "source_filename": "tax_certificate_001.pdf",
      "locations": [{"page": 0, "box": {...}}],
      "confidence_score": 1.0,
      "justification": "Single source value - no conflict resolution needed.",
      "alternatives": [],
      "flags": []
    }
  },
  "validation_summary": "Validated 2 fields with conflicts from 2 files. 1 high confidence selections, 1 single-source values. 0 total flags/warnings raised.",
  "overall_confidence": 0.975
}
```

### Validation Report Output

Location: `./out/validated/<TopLevelCategory>/<DocumentType>/validation_report.json`

```json
{
  "top_level_category": "Company Information",
  "top_level_folder": "Company_Information",
  "document_type": "Certificate of Legal Existence",
  "document_type_folder": "Certificate_of_Legal_Existence",
  "total_fields_validated": 2,
  "total_files_processed": 2,
  "source_files": [
    "D:/documents/tax_certificate_001.pdf",
    "D:/documents/tax_certificate_002.pdf"
  ],
  "validations": [
    {
      "field_name": "company_name",
      "selected_value": "Solar Energy Corporation",
      "selected_source": "D:/documents/tax_certificate_001.pdf",
      "selected_source_filename": "tax_certificate_001.pdf",
      "locations": [
        {
          "page": 0,
          "box": {
            "left": 0.09,
            "top": 0.05,
            "right": 0.32,
            "bottom": 0.14
          },
          "chunk_id": "4ab994ee-1537-493a-885b-7eb2533c4738",
          "image_path": null
        }
      ],
      "confidence_score": 0.95,
      "justification": "Selected 'Solar Energy Corporation' because: [detailed reasoning]",
      "alternative_values": [
        {
          "value": "Solar Energy Corp",
          "source_file": "D:/documents/tax_certificate_002.pdf",
          "source_filename": "tax_certificate_002.pdf",
          "locations": [...]
        }
      ],
      "flags": []
    }
  ],
  "overall_confidence": 0.95,
  "summary": "Validated 2 fields with conflicts from 2 files. 1 high confidence selections. 0 total flags/warnings raised."
}
```

---

## Integration

### Programmatic Usage

```python
from pathlib import Path
from ddx.classification.validation_layer import (
    ValidationLayer,
    discover_document_type_folders,
    load_records_from_document_type_folder,
    collect_conflicts_from_records,
    build_final_output,
)

# Initialize validator
validator = ValidationLayer(model="gpt-5-nano-2025-08-07")

# Discover document type folders (returns tuples of: folder_path, top_level_name, doc_type_name)
records_dir = Path("./out/records")
doc_type_folders = discover_document_type_folders(records_dir)

for doc_type_folder, top_level_name, doc_type_name in doc_type_folders:
    print(f"Processing {top_level_name}/{doc_type_name}")
    
    # Load records from this document type folder
    records = load_records_from_document_type_folder(doc_type_folder)
    
    if len(records) < 2:
        print(f"  Skipping - only {len(records)} file(s), no validation needed")
        continue
    
    # Collect conflicts
    field_descriptions = {...}  # Load from PYDANTIC_MODELS
    conflicts = collect_conflicts_from_records(
        records,
        top_level_name,
        doc_type_name,
        field_descriptions,
    )
    
    if not conflicts:
        print(f"  No conflicts found")
        continue
    
    # Validate conflicts
    source_files = [r["pdf_path"] for r in records]
    report = validator.validate_all_conflicts(
        conflicts,
        top_level_name,
        doc_type_name,
        source_files
    )
    
    # Build final output
    final = build_final_output(
        records,
        top_level_name,
        doc_type_name,
        report,
    )
    
    # Save outputs
    out_dir = Path("./out/validated") / top_level_name / doc_type_name
    out_dir.mkdir(parents=True, exist_ok=True)
    
    (out_dir / "validation_report.json").write_text(
        report.model_dump_json(indent=2)
    )
    (out_dir / "final_extraction.json").write_text(
        final.model_dump_json(indent=2)
    )
```
        print(f"  No conflicts in {category_name}")
        continue
    
    # Validate conflicts
    source_files = [r["pdf_path"] for r in records]
    report = validator.validate_all_conflicts(
        conflicts,
        category_name,
        source_files
    )
    
    # Build final output (directly from parse.json)
    final = build_final_output(
        records,
        category_name,
        report,
    )
    
    # Save outputs
    out_dir = Path("./out/validated") / category_folder.name
    out_dir.mkdir(parents=True, exist_ok=True)
    
    (out_dir / "validation_report.json").write_text(
        report.model_dump_json(indent=2)
    )
    (out_dir / "final_extraction.json").write_text(
        final.model_dump_json(indent=2)
    )
```

### Integration with Landing AI SDK Pipeline

```python
from pathlib import Path
from ddx.classification.landing_ai_poc_sdk import PYDANTIC_MODELS
from ddx.classification.validation_layer import (
    ValidationLayer,
    discover_document_type_folders,
    process_document_type_folder,
)

# Extract field descriptions from schemas
field_descriptions = {}
for model_cls in PYDANTIC_MODELS.values():
    if hasattr(model_cls, "model_fields"):
        for fname, finfo in model_cls.model_fields.items():
            if finfo.description:
                field_descriptions[fname] = finfo.description

# Initialize validator
validator = ValidationLayer(model="gpt-5-nano-2025-08-07")

# Discover and process all document type folders
records_dir = Path("./out/records")
out_dir = Path("./out/validated")

doc_type_folders = discover_document_type_folders(records_dir)

for doc_type_folder, top_level_name, doc_type_name in doc_type_folders:
    print(f"\nProcessing: {top_level_name}/{doc_type_name}")
    
    report = process_document_type_folder(
        doc_type_folder=doc_type_folder,
        top_level_category=top_level_name,
        document_type=doc_type_name,
        validator=validator,
        field_descriptions=field_descriptions,
        out_base_dir=out_dir,
    )
    
    if report:
        print(f"  Validated {report.total_fields_validated} conflicts")
        print(f"  Confidence: {report.overall_confidence:.2f}")
```

---

## API Reference

### ValidationLayer

```python
class ValidationLayer:
    """Main validation class using GPT-4o-mini for reasoning."""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-5-nano-2025-08-07",
        base_url: Optional[str] = None,
    )
    
    def validate_field(self, conflict: FieldConflict) -> ValidationResult:
        """Validate a single field conflict."""
    
    def validate_all_conflicts(
        self,
        conflicts: List[FieldConflict],
        top_level_category: str,
        document_type: str,
        source_files: List[str],
    ) -> ValidationReport:
        """Validate all conflicts for a document type."""
```

### Helper Functions

| Function | Description |
|----------|-------------|
| `discover_document_type_folders(records_dir)` | Find all document type subfolders (2 levels deep) in records directory |
| `load_records_from_document_type_folder(doc_type_folder)` | Load all JSON records from a document type folder |
| `collect_conflicts_from_records(records, top_level, doc_type, field_descriptions)` | Find field conflicts within a document type (reads parse.json directly) |
| `build_final_output(records, top_level, doc_type, validation_report)` | Build final extraction output with validated values |
| `process_document_type_folder(doc_type_folder, top_level, doc_type, validator, field_descriptions, out_base_dir)` | Complete processing for one document type folder |

### Utility Functions

| Function | Description |
|----------|-------------|
| `_sanitize_category_name(category)` | Convert category to safe folder name (matches landing_ai_poc_sdk.py) |
| `_folder_name_to_display(folder_name)` | Convert folder name back to display name |

---

## Error Handling

### API Errors

If the OpenAI API call fails:
1. Falls back to the **first candidate**
2. Sets confidence to **0.2**
3. Adds `API_ERROR: <error_type>: <message>` to flags
4. Continues processing other fields

### Parse Errors

If the model response cannot be parsed as JSON:
1. Falls back to the **first candidate**
2. Sets confidence to **0.3**
3. Adds `PARSE_ERROR: Model response could not be parsed` to flags
4. Continues processing

### Missing Parse.json

If `parse.json` file referenced in extraction record is not found:
- System continues with extraction metadata only
- Location info limited to chunk IDs
- Warning printed to console
- No impact on validation reasoning

### No Conflicts

If a category has no field conflicts:
1. All values passed through with confidence **1.0**
2. Justification: "Single source value - no conflict resolution needed."
3. Only `final_extraction.json` is created (no validation report)

### Empty Category Folders

If a category folder contains no JSON files:
- Folder is skipped with a warning
- No output files created for that category

---

## Best Practices

1. **Run after landing_ai_poc_sdk.py**: Ensure extraction has organized records by top-level category and document type first
2. **Ensure parse.json files exist**: The `parse_json_path` in records must point to valid files
3. **Use field descriptions**: Script automatically imports from `PYDANTIC_MODELS` for better reasoning
4. **Review low confidence**: Manually verify fields with confidence < 0.5
5. **Check flags**: Investigate any flagged fields for potential issues
6. **Use filters for testing**: Use `--top-level-filter` or `--doc-type-filter` during development to process one folder at a time
7. **Monitor API costs**: GPT-4o-mini calls are made per field conflict; filter categories if budget-conscious
8. **Verify justifications**: Review the reasoning in validation reports to ensure quality
9. **Preserve folder structure**: Don't rename category folders between extraction and validation
10. **Keep records and markdown together**: The validation layer relies on `parse_json_path` references
11. **Understand validation scope**: Validation only happens when 2+ files exist in the same document_type folder

---

## End-to-End Workflow

This script is designed to work with `landing_ai_poc_sdk.py` for complete document processing:

```bash
# Step 1: Classify and extract documents (outputs organized hierarchically)
# With top-level category filtering for improved accuracy
python landing_ai_poc_sdk.py \
  --pdf-dir ./company_documents \
  --top-level-category "Company Information" \
  --out ./out/records \
  --markdown-dir ./out/markdown

# Or without filtering (classifies across all document types)
python landing_ai_poc_sdk.py \
  --pdf-dir ./documents \
  --out ./out/records \
  --markdown-dir ./out/markdown

# Step 2: Validate and merge multi-source extractions
# Process all categories and document types
python validation_layer.py \
  --records-dir ./out/records \
  --out ./out/validated

# Or filter by top-level category
python validation_layer.py \
  --records-dir ./out/records \
  --top-level-filter Company_Information \
  --out ./out/validated

# Or filter by specific document type
python validation_layer.py \
  --records-dir ./out/records \
  --doc-type-filter Certificate_of_Legal_Existence \
  --out ./out/validated
```

**Complete Processing Flow:**
```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        landing_ai_poc_sdk.py                                 │
│  ┌─────────┐   ┌──────────────┐   ┌──────────────┐   ┌────────────────────┐  │
│  │   PDF   │──▶│   Classify   │──▶│   Parse MD   │──▶│ Extract by Schema  │  │
│  └─────────┘   └──────────────┘   └──────────────┘   └────────────────────┘  │
│                      │                    │                    │             │
│                      ▼                    ▼                    ▼             │
│           top_level_category +    Markdown + parse.json   Structured JSON  │
│                document_type              │                    │             │
│                      │                    │                    │             │
│                      └────────────────────┴────────────────────┘             │
│                                          │                                   │
│          out/records/<TopLevel>/<DocType>/<file>.json (with parse_json_path) │
│          out/markdown/<TopLevel>/<DocType>/<file>.md                         │
│          out/markdown/<TopLevel>/<DocType>/<file>.parse.json                 │
└──────────────────────────────────────────────────────────────────────────────┘
                                          │
                                          ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                           validation_layer.py                                │
│  ┌────────────────────┐   ┌─────────────────┐   ┌──────────────────────────┐ │
│  │ Discover Doc Type  │──▶│ Detect Conflicts│──▶│ GPT-4o-mini Reasoning     │ │
│  │ Folders            │   │ Per Doc Type   │   │ Select Best Value        │ │
│  └────────────────────┘   └─────────────────┘   └──────────────────────────┘ │
│           │                       │                        │                 │
│           │                       ▼                        ▼                 │
│           │            Read parse.json via         validation_report.json   │
│           │            parse_json_path             final_extraction.json    │
│           │            Extract bounding boxes      with justifications       │
│           │                       │                        │                 │
│           └───────────────────────┴────────────────────────┘                 │
│                                   │                                          │
│          out/validated/<TopLevel>/<DocType>/final_extraction.json            │
│          out/validated/<TopLevel>/<DocType>/validation_report.json           │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Final Output Structure:**
```
out/
├── records/                          ← Input from landing_ai_poc_sdk.py
│   └── <TopLevelCategory>/
│       └── <DocumentType>/
│           └── *.json (contains parse_json_path)
├── markdown/                         ← Input from landing_ai_poc_sdk.py
│   └── <TopLevelCategory>/
│       └── <DocumentType>/
│           └── *.md, *.parse.json (read directly for bounding boxes)
└── validated/                        ← Output from validation_layer.py
    └── <TopLevelCategory>/
        └── <DocumentType>/
            ├── validation_report.json    ← Reasoning details (if conflicts)
            └── final_extraction.json     ← Final validated data with locations
```


