# Extraction API - Document Processing Pipeline

A comprehensive async document processing API using the **LandingAI ADE SDK** for parsing, classifying, and extracting structured data from PDF documents. Designed for solar energy project documentation with support for batch processing, human-in-the-loop corrections, direct extraction, and **automatic conflict resolution** when multiple documents contain the same field.

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Two-Level Classification System](#two-level-classification-system)
- [Architecture](#architecture)
- [Installation](#installation)
- [Configuration](#configuration)
- [API Functions](#api-functions)
  - [Function 1: Batch Processing by Category](#function-1-batch-processing-by-category)
  - [Function 2: Human-in-the-Loop Re-extraction](#function-2-human-in-the-loop-re-extraction)
  - [Function 3: Direct Extraction](#function-3-direct-extraction)
- [Validation Layer](#validation-layer)
- [Response Models](#response-models)
- [Categories and Document Types](#categories-and-document-types)
- [Rate Limiting and Concurrency](#rate-limiting-and-concurrency)
- [Usage Examples](#usage-examples)
- [Convenience Functions](#convenience-functions)
- [Error Handling](#error-handling)
- [Integration Guide](#integration-guide)

---

## Overview

The `extraction_api.py` module provides three core functions for document processing:

| Function | Use Case | Classification | Parsing | Validation |
|----------|----------|----------------|---------|------------|
| `process_documents_by_category()` | Batch processing with top-level categories | ✅ Yes | ✅ Yes | ✅ Yes |
| `extract_specific_fields()` | Human-in-the-loop field corrections | ❌ No | ✅ Yes | ❌ No |
| `extract_document_direct()` | Direct extraction with known document type | ❌ No | ✅ Yes | ✅ Yes (batch) |

All functions support both **synchronous** and **asynchronous** execution with built-in rate limiting, concurrency control, and **automatic validation** for resolving conflicts when multiple documents have the same classification.

> **⚠️ IMPORTANT:** `top_level_category` is now **REQUIRED** for all batch processing operations. You must import and use the `TopLevelCategory` enum from `ddx.classification.categories`.

---

## Key Features

| Feature | Description |
|---------|-------------|
| **Two-Level Classification** | Top-level category → Document type hierarchy |
| **Async Processing** | Concurrent document processing using `AsyncLandingAIADE` |
| **Rate Limiting** | Built-in rate limiter using `aiolimiter` to prevent 429 errors |
| **Concurrency Control** | Semaphore-based limiting of simultaneous requests |
| **Flexible Input** | Accept file paths, bytes, or dict inputs |
| **Partial Extraction** | Extract specific fields without full schema |
| **Multi-Category** | Process documents across multiple categories in one call |
| **Sync Wrappers** | All async functions have synchronous equivalents |
| **Validation Layer** | AI-powered conflict resolution when multiple documents have conflicting values |
| **Source Tracking** | Track which document each field value came from |
| **Hierarchical Output** | Organized output structure: `top_level/document_type/file` |

---

## Two-Level Classification System

The system uses a **hierarchical classification approach**:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    TWO-LEVEL CLASSIFICATION                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Level 1: Top-Level Category (PROVIDED BY USER - REQUIRED)              │
│  ──────────────────────────────────────────────────────────             │
│                                                                         │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐          │
│  │ Company         │  │ Technical       │  │ Financial       │          │
│  │ Information     │  │                 │  │                 │          │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘          │
│           │                    │                    │                   │
│           ▼                    ▼                    ▼                   │
│                                                                         │
│  Level 2: Document Type (CLASSIFIED BY AI)                              │
│  ─────────────────────────────────────────                              │
│                                                                         │
│  Company Information:          Technical:                               │
│  ├─ Certificate of Legal       ├─ Project Simulation Report             │
│  │  Existence / Tax ID         ├─ Project Data Equipment Sheets         │
│  ├─ Shareholders Declaration   ├─ Project Basic Engineering             │
│  └─ Legal Representative       ├─ Project Visit Report                  │
│     Appointment                ├─ Project Layout                        │
│                                ├─ KMZ Poligon                           │
│                                ├─ Cable Sizing Calculation              │
│                                └─ Grounding System Diagram              │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Why Two Levels?

1. **User provides context**: The top-level category tells the system what kind of documents to expect
2. **Focused classification**: The AI only chooses from document types within that category (fewer choices = higher accuracy)
3. **Appropriate schemas**: Each document type has its own Pydantic extraction schema
4. **Organized output**: Files are stored hierarchically: `top_level_category/document_type/file`

---

## Architecture

### Processing Flow with Validation

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    EXTRACTION API ARCHITECTURE (WITH VALIDATION)                │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌─────────────┐                                                                │
│  │   INPUT     │                                                                │
│  │  - Path     │                                                                │
│  │  - bytes    │                                                                │
│  │  - Dict     │                                                                │
│  └──────┬──────┘                                                                │
│         │                                                                       │
│         ▼                                                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐        │
│  │                     FUNCTION SELECTION                              │        │
│  ├─────────────────┬─────────────────────┬─────────────────────────────┤        │
│  │                 │                     │                             │        │
│  │  Function 1     │    Function 2       │    Function 3               │        │
│  │  Batch by       │    Human-in-Loop    │    Direct                   │        │
│  │  Category       │    Re-extraction    │    Extraction               │        │
│  │                 │                     │                             │        │
│  └────────┬────────┴──────────┬──────────┴──────────────┬──────────────┘        │
│           │                   │                         │                       │
│           ▼                   ▼                         ▼                       │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐                  │
│  │  Parse → Classify│  │  Parse Only     │  │  Parse Only     │                  │
│  │  → Extract       │  │  → Extract      │  │  → Extract      │                  │
│  │  (Full Pipeline) │  │  (Partial)      │  │  (Full Schema)  │                  │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘                  │
│           │                    │                    │                           │
│           ▼                    │                    ▼                           │
│  ┌─────────────────────────────┴────────────────────────────────────┐           │
│  │                      DOCUMENT RESULTS                            │           │
│  │         (Multiple documents may have same classification)        │           │
│  └─────────────────────────────┬────────────────────────────────────┘           │
│                                │                                                │
│                                ▼                                                │
│  ┌──────────────────────────────────────────────────────────────────┐           │
│  │                    VALIDATION LAYER                              │           │
│  │  ┌────────────────────────────────────────────────────────────┐  │           │
│  │  │  1. Group results by document_type                         │  │           │
│  │  │  2. Detect conflicts (same field, different values)        │  │           │
│  │  │  3. Use GPT-4o-mini to resolve conflicts                   │  │           │
│  │  │  4. Provide justification + source tracking                │  │           │
│  │  └────────────────────────────────────────────────────────────┘  │           │
│  └─────────────────────────────┬────────────────────────────────────┘           │
│                                │                                                │
│                                ▼                                                │
│  ┌──────────────────────────────────────────────────────────────────┐           │
│  │                    VALIDATED RESULTS                             │           │
│  │  - Single value per field (conflict resolved)                    │           │
│  │  - Source file tracking                                          │           │
│  │  - Confidence scores                                             │           │
│  │  - Justification for selections                                  │           │
│  │  - Alternative values preserved                                  │           │
│  └──────────────────────────────────────────────────────────────────┘           │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Validation Flow Detail

```
┌────────────────────────────────────────────────────────────────────────────┐
│                         VALIDATION LAYER FLOW                              │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│   SCENARIO: 3 documents classified as "Project Simulation Report"          │
│                                                                            │
│   ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐            │
│   │   sim_v1.pdf    │  │   sim_v2.pdf    │  │   sim_final.pdf │            │
│   │                 │  │                 │  │                 │            │
│   │ performance_    │  │ performance_    │  │ performance_    │            │
│   │ ratio: 78.5%    │  │ ratio: 79.2%    │  │ ratio: 79.2%    │            │
│   │                 │  │                 │  │                 │            │
│   │ total_energy:   │  │ total_energy:   │  │ total_energy:   │            │
│   │ 1250 MWh        │  │ 1280 MWh        │  │ 1280 MWh        │            │
│   └────────┬────────┘  └────────┬────────┘  └────────┬────────┘            │
│            │                    │                    │                     │
│            └────────────────────┼────────────────────┘                     │
│                                 │                                          │
│                                 ▼                                          │
│   ┌─────────────────────────────────────────────────────────────────┐      │
│   │                    CONFLICT DETECTION                           │      │
│   │                                                                 │      │
│   │   performance_ratio: [78.5%, 79.2%, 79.2%] → CONFLICT!          │      │
│   │   total_energy: [1250, 1280, 1280] → CONFLICT!                  │      │
│   │                                                                 │      │
│   └─────────────────────────────┬───────────────────────────────────┘      │
│                                 │                                          │
│                                 ▼                                          │
│   ┌─────────────────────────────────────────────────────────────────┐      │
│   │                    GPT-4o-mini REASONING                        │      │
│   │                                                                 │      │
│   │   "Analyzing 3 candidates for 'performance_ratio'..."           │      │
│   │                                                                 │      │
│   │   Decision: 79.2% from sim_final.pdf                            │      │
│   │   Justification: "Two sources agree on 79.2%. The file          │      │
│   │   'sim_final.pdf' appears to be the final version based on      │      │
│   │   filename convention, and its value matches sim_v2.pdf."       │      │
│   │   Confidence: 0.95                                              │      │
│   │                                                                 │      │
│   └─────────────────────────────┬───────────────────────────────────┘      │
│                                 │                                          │
│                                 ▼                                          │
│   ┌─────────────────────────────────────────────────────────────────┐      │
│   │                    VALIDATED OUTPUT                             │      │
│   │                                                                 │      │
│   │   performance_ratio:                                            │      │
│   │     value: 79.2%                                                │      │
│   │     source_file: "sim_final.pdf"                                │      │
│   │     confidence: 0.95                                            │      │
│   │     justification: "Two sources agree..."                       │      │
│   │     alternatives: [{value: 78.5%, source: "sim_v1.pdf"}]        │      │
│   │                                                                 │      │
│   └─────────────────────────────────────────────────────────────────┘      │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

### Concurrency Model

```
┌────────────────────────────────────────────────────────────────┐
│                    CONCURRENCY CONTROL                         │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│   Documents: [Doc1, Doc2, Doc3, Doc4, Doc5, Doc6, Doc7]        │
│                                                                │
│   Semaphore (max_concurrent=3):                                │
│   ┌─────────────────────────────────────────────────────┐      │
│   │  Slot 1: Doc1 ████████░░░░░░░░ Doc4 ████████░░░░    │      │
│   │  Slot 2: Doc2 ██████████████░░ Doc5 ██████████      │      │
│   │  Slot 3: Doc3 ████████████░░░░ Doc6 ████████████    │      │
│   └─────────────────────────────────────────────────────┘      │
│                                                                │
│   Rate Limiter (10 req/sec):                                   │
│   ┌─────────────────────────────────────────────────────┐      │
│   │  Second 1: ▓▓▓▓▓▓▓▓▓▓ (10 requests)                 │      │
│   │  Second 2: ▓▓▓▓▓▓▓▓▓▓ (10 requests)                 │      │
│   │  Second 3: ▓▓▓▓░░░░░░ (4 requests)                  │      │
│   └─────────────────────────────────────────────────────┘      │
│                                                                │
│   Combined Effect:                                             │
│   - Max 3 documents processing simultaneously                  │
│   - Max 10 API requests per second across all documents        │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

---

## Installation

### Prerequisites

```bash
pip install landingai-ade pydantic aiolimiter openai
```

### Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `landingai-ade` | Latest | SDK for parse and extract (sync + async) |
| `pydantic` | v2.x | Schema definition and validation |
| `aiolimiter` | Latest | Async rate limiting |
| `openai` | Latest | Validation layer reasoning (GPT-4o-mini) |

### Verify Installation

```python
from landingai_ade import AsyncLandingAIADE, LandingAIADE
from aiolimiter import AsyncLimiter
from openai import OpenAI
print("All dependencies installed successfully!")
```

---

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `VISION_AGENT_API_KEY` | **Yes*** | - | LandingAI API key (primary) |
| `VA_API_KEY` | **Yes*** | - | LandingAI API key (fallback) |
| `OPENAI_API_KEY` | **Yes**** | - | OpenAI API key for validation |
| `LANDING_PARSE_MODEL` | No | `dpt-2-latest` | Model for PDF parsing |
| `LANDING_EXTRACT_MODEL` | No | `extract-latest` | Model for extraction |

*One of `VISION_AGENT_API_KEY` or `VA_API_KEY` must be set.
**Required only if `enable_validation=True` (default).

### Setting the API Keys

```powershell
# Windows (PowerShell)
$env:VISION_AGENT_API_KEY = "your-landingai-key"
$env:OPENAI_API_KEY = "your-openai-key"

# Windows (CMD)
set VISION_AGENT_API_KEY=your-landingai-key
set OPENAI_API_KEY=your-openai-key

# Linux/macOS
export VISION_AGENT_API_KEY="your-landingai-key"
export OPENAI_API_KEY="your-openai-key"
```

---

## API Functions

### Function 1: Batch Processing by Category

Process multiple documents for a given top-level category with automatic classification and validation.

> **Note:** `top_level_category` is **REQUIRED** and must be a `TopLevelCategory` enum value.

#### `process_documents_by_category_async()`

```python
from ddx.classification.categories import TopLevelCategory

async def process_documents_by_category_async(
    files: Union[List[Path], List[bytes], List[Dict[str, Any]]],
    top_level_category: TopLevelCategory,  # REQUIRED - enum value
    *,
    file_names: Optional[List[str]] = None,
    parse_model: Optional[str] = None,
    extract_model: Optional[str] = None,
    save_markdown: bool = False,
    max_concurrent: int = 5,
    rate_limit: float = 10.0,
    enable_validation: bool = True,
    validation_model: str = "gpt-5-nano-2025-08-07",
) -> BatchProcessingResult:
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `files` | `List[Path\|bytes\|Dict]` | Required | List of files to process |
| `top_level_category` | `TopLevelCategory` | **Required** | Top-level category enum (e.g., `TopLevelCategory.TECHNICAL`) |
| `file_names` | `List[str]` | `None` | File names (required if files are bytes) |
| `parse_model` | `str` | `dpt-2-latest` | Model for parsing |
| `extract_model` | `str` | `extract-latest` | Model for extraction |
| `save_markdown` | `bool` | `False` | Include markdown in results |
| `max_concurrent` | `int` | `5` | Maximum concurrent requests |
| `rate_limit` | `float` | `10.0` | Max requests per second |
| `enable_validation` | `bool` | `True` | Run validation layer for conflicts |
| `validation_model` | `str` | `gpt-5-nano-2025-08-07` | Model for validation reasoning |

**Returns:** `BatchProcessingResult` (includes `validated_results`)

**Pipeline:**
1. Parse each document to Markdown (concurrently)
2. Classify to determine specific document type **within the provided category**
3. Extract fields using appropriate schema
4. **Validate** - Group by document type, detect conflicts, resolve with AI reasoning

#### `process_documents_by_category()` (Sync)

Synchronous wrapper using `asyncio.run()`.

```python
from ddx.classification.categories import TopLevelCategory

def process_documents_by_category(
    files: Union[List[Path], List[bytes], List[Dict[str, Any]]],
    top_level_category: TopLevelCategory,  # REQUIRED
    **kwargs
) -> BatchProcessingResult:
```

#### `process_documents_multi_category_async()`

Process documents across multiple categories in one call.

```python
from ddx.classification.categories import TopLevelCategory

async def process_documents_multi_category_async(
    files_by_category: Dict[TopLevelCategory, List[Union[Path, bytes, Dict[str, Any]]]],
    *,
    file_names_by_category: Optional[Dict[TopLevelCategory, List[str]]] = None,
    parse_model: Optional[str] = None,
    extract_model: Optional[str] = None,
    max_concurrent: int = 5,
    rate_limit: float = 10.0,
    enable_validation: bool = True,
    validation_model: str = "gpt-5-nano-2025-08-07",
) -> Dict[TopLevelCategory, BatchProcessingResult]:
```

---

### Function 2: Human-in-the-Loop Re-extraction

Extract specific fields from a document when the user wants to correct or update values.

> **Note:** This function does NOT run validation since it's designed for single-document corrections where the user provides the authoritative source.

#### `extract_specific_fields_async()`

```python
async def extract_specific_fields_async(
    file: Union[Path, bytes, Dict[str, Any]],
    document_type: str,
    fields: List[str],
    *,
    file_name: Optional[str] = None,
    parse_model: Optional[str] = None,
    extract_model: Optional[str] = None,
    existing_markdown: Optional[str] = None,
    rate_limit: float = 10.0,
) -> FieldExtractionResult:
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file` | `Path\|bytes\|Dict` | Required | File to process |
| `document_type` | `str` | Required | Known document type |
| `fields` | `List[str]` | Required | List of field names to extract |
| `file_name` | `str` | `None` | File name (required if file is bytes) |
| `existing_markdown` | `str` | `None` | Pre-parsed markdown (skip parsing) |
| `rate_limit` | `float` | `10.0` | Max requests per second |

**Returns:** `FieldExtractionResult`

**Key Features:**
- **No classification** - document type is already known
- **Partial schema** - only extracts requested fields
- **Skip parsing** - can use existing markdown
- **No validation** - user-provided document is authoritative

---

### Function 3: Direct Extraction

Extract all fields from a document when you already know its type.

#### `extract_document_direct_async()`

```python
async def extract_document_direct_async(
    file: Union[Path, bytes, Dict[str, Any]],
    document_type: str,
    *,
    file_name: Optional[str] = None,
    parse_model: Optional[str] = None,
    extract_model: Optional[str] = None,
    existing_markdown: Optional[str] = None,
    rate_limit: float = 10.0,
) -> DocumentResult:
```

**Returns:** `DocumentResult`

#### `extract_documents_direct_batch_async()`

Batch direct extraction with validation support.

```python
async def extract_documents_direct_batch_async(
    files: List[Union[Path, bytes, Dict[str, Any]]],
    document_type: str,
    *,
    file_names: Optional[List[str]] = None,
    parse_model: Optional[str] = None,
    extract_model: Optional[str] = None,
    max_concurrent: int = 5,
    rate_limit: float = 10.0,
    enable_validation: bool = True,
    validation_model: str = "gpt-5-nano-2025-08-07",
) -> Tuple[List[DocumentResult], Optional[ValidatedDocumentResult]]:
```

**Returns:** `Tuple[List[DocumentResult], Optional[ValidatedDocumentResult]]`

- First element: List of individual extraction results
- Second element: Validated result with conflicts resolved (if `enable_validation=True` and multiple docs)

---

## Validation Layer

### Overview

The validation layer automatically resolves conflicts when multiple documents are classified as the same type but contain different values for the same field.

### When Validation Runs

| Function | Validation | Condition |
|----------|------------|-----------|
| `process_documents_by_category()` | ✅ Yes | `enable_validation=True` AND >1 successful result |
| `extract_specific_fields()` | ❌ No | Never (single document, user authoritative) |
| `extract_document_direct()` | ❌ No | Single document |
| `extract_documents_direct_batch()` | ✅ Yes | `enable_validation=True` AND >1 successful result |

### How It Works

1. **Group by Document Type**: Results are grouped by their classified `document_type`
2. **Detect Conflicts**: For each field, check if multiple documents have different values
3. **AI Reasoning**: Use GPT-4o-mini to analyze candidates and select the best value
4. **Output**: Provide selected value, source file, confidence score, and justification

### Validation Data Structures

#### `FieldConflict`

```python
@dataclass
class FieldConflict:
    field_name: str              # Name of the conflicting field
    field_description: str       # Description from schema
    candidates: List[FieldCandidate]  # All candidate values
    top_level_category: str      # Top-level category (e.g., "Company Information")
    document_type: str           # Document type (e.g., "Certificate of Legal Existence")
```

#### `FieldCandidate`

```python
@dataclass
class FieldCandidate:
    value: Any                   # Extracted value
    source_file: str             # Full file path
    source_filename: str         # Just the filename
    extracted_text: str          # Raw text that was extracted
    confidence: Optional[float]  # Extraction confidence
    chunk_ids: List[str]         # Reference IDs in markdown
    evidence_locations: List[EvidenceLocation]  # Page/bbox info
```

#### `ValidationResult`

```python
class ValidationResult(BaseModel):
    field_name: str
    selected_value: Any
    selected_source: str
    selected_source_filename: str
    confidence_score: float      # 0.0 to 1.0
    justification: str           # AI explanation
    alternative_values: List[Dict[str, Any]]
    locations: List[LocationInfo]
    flags: List[str]             # Warning flags
```

### Validation Output

After validation, `BatchProcessingResult` includes:

```python
class BatchProcessingResult(BaseModel):
    top_level_category: str      # Top-level category (e.g., "Company Information")
    total_documents: int
    successful: int
    failed: int
    results: List[DocumentResult]  # Individual results
    validated_results: Optional[Dict[str, ValidatedDocumentResult]]  # Grouped by document_type
    validation_performed: bool
```

#### `ValidatedDocumentResult`

```python
class ValidatedDocumentResult(BaseModel):
    document_type: str           # e.g., "Certificate of Legal Existence"
    top_level_category: str      # e.g., "Company Information"
    source_files: List[str]      # All files that contributed
    validated_fields: Dict[str, ValidatedFieldOutput]  # Resolved fields
    validation_report: Optional[ValidationReport]
    overall_confidence: float    # Average confidence
    validation_summary: str      # Human-readable summary
```

#### `ValidatedFieldOutput`

```python
class ValidatedFieldOutput(BaseModel):
    field_name: str
    value: Any                   # Final selected value
    source_file: str             # File it came from
    source_filename: str
    extracted_text: str
    locations: List[LocationInfo]
    confidence_score: float
    justification: str           # Why this value was selected
    alternatives: List[Dict]     # Other candidate values
    flags: List[str]             # Warning flags
```

### Disabling Validation

If you don't need validation or don't have an OpenAI API key:

```python
from ddx.classification.categories import TopLevelCategory

result = process_documents_by_category(
    files=[...],
    top_level_category=TopLevelCategory.TECHNICAL,
    enable_validation=False,  # Disable validation
)
```

---

## Response Models

### `DocumentResult`

Result for a single document processing.

```python
class DocumentResult(BaseModel):
    file_name: str                              # Name of the processed file
    file_path: Optional[str] = None             # Original file path
    document_type: str                          # Classified document type
    top_level_category: str                     # Top-level category (e.g., "Company Information")
    extracted_data: Dict[str, Any]              # Extracted field values
    extraction_metadata: Optional[Dict] = None  # Metadata from API
    markdown_content: Optional[str] = None      # Markdown (if save_markdown=True)
    success: bool = True                        # Whether processing succeeded
    error: Optional[str] = None                 # Error message (if failed)
```

### `BatchProcessingResult`

Result for batch document processing with validation.

```python
class BatchProcessingResult(BaseModel):
    top_level_category: str          # Top-level category processed (e.g., "Technical")
    total_documents: int             # Total number of documents
    successful: int                  # Number of successful extractions
    failed: int                      # Number of failed extractions
    results: List[DocumentResult]    # Individual document results
    validated_results: Optional[Dict[str, ValidatedDocumentResult]]  # Grouped by document_type
    validation_performed: bool       # Whether validation was run
```

### `FieldExtractionResult`

Result for specific field extraction.

```python
class FieldExtractionResult(BaseModel):
    file_name: str                              # Name of the processed file
    document_type: str                          # Document type used
    top_level_category: str                     # Top-level category
    requested_fields: List[str]                 # Fields that were requested
    extracted_fields: Dict[str, Any]            # Extracted field values
    extraction_metadata: Optional[Dict] = None  # Metadata from API
    success: bool = True                        # Whether extraction succeeded
    error: Optional[str] = None                 # Error message (if failed)
```

---

## Categories and Document Types

### Top-Level Categories (TopLevelCategory Enum)

| Category | Enum Value | Description |
|----------|------------|-------------|
| Company Information | `TopLevelCategory.COMPANY_INFORMATION` | Company legal and ownership documentation |
| Technical | `TopLevelCategory.TECHNICAL` | Technical project documentation |
| ESG | `TopLevelCategory.ESG` | Environmental, Social, Governance |
| Financial | `TopLevelCategory.FINANCIAL` | Financial statements and models |
| Legal | `TopLevelCategory.LEGAL` | Legal documents and contracts |
| Regulatory | `TopLevelCategory.REGULATORY` | Regulatory compliance documents |

### Company Information Document Types

| Document Type | Description | Pydantic Model |
|---------------|-------------|----------------|
| `Certificate of Legal Existence` | Certificate with legal name, RUC, commercial activity, incorporation date | `LegalInformation` |
| `Shareholders Declaration` | Shareholder ownership structure (>10% stake) | `ShareholderStructure` |
| `Legal Representative Appointment` | Legal representative appointment with validity period | `LegalRepresentation` |

### Technical Document Types

| Document Type | Description | Pydantic Model |
|---------------|-------------|----------------|
| `Project Simulation Report` | PVsyst/Helioscope simulation outputs | `ProjectSimulationReportData` |
| `Project Data Main Equipment Sheets` | Module/inverter datasheets | `ProjectDataMainEquipmentSheetsData` |
| `Project Basic Engineering` | Memoria Técnica documents | `ProjectBasicEngineeringData` |
| `Project Visit Report` | Site visit documentation | `ProjectVisitReportData` |
| `Project Layout` | Technology sizing plans | `ProjectLayoutData` |
| `KMZ Poligon` | Google Earth area data | `KmzPoligonData` |
| `Cable Sizing Calculation Report` | Cable calculations | `CableSizingCalculationReportData` |
| `Grounding System` | Grounding system diagrams | `GroundingSystemSingleLineDiagramData` |

### Importing Categories

```python
from ddx.classification.categories import (
    TopLevelCategory,
    DocumentType,
    DOCUMENT_TYPE_TO_TOP_LEVEL,
    DOCUMENT_TYPE_DESCRIPTIONS,
    PYDANTIC_MODELS,
)

# Get all top-level categories
for cat in TopLevelCategory:
    print(f"{cat.name}: {cat.value}")

# Get document types for a category
from ddx.classification.extraction_api import get_document_types_for_category_api
types = get_document_types_for_category_api("Company Information")
```

---

## Rate Limiting and Concurrency

### Why Both Are Needed

| Control | Purpose | Prevents |
|---------|---------|----------|
| **Semaphore** | Limits simultaneous in-flight requests | Memory exhaustion, connection pool issues |
| **Rate Limiter** | Limits requests per time window | 429 Too Many Requests errors |

### Recommended Settings

| Use Case | `max_concurrent` | `rate_limit` |
|----------|------------------|--------------|
| Small documents (<10 pages) | 5-10 | 10.0 |
| Medium documents (10-50 pages) | 3-5 | 5.0 |
| Large documents (50+ pages) | 2-3 | 2.0 |
| Rate limit concerns | 2 | 2.0 |

---

## Usage Examples

### Example 1: Batch Processing with Validation

```python
from pathlib import Path
from ddx.classification.categories import TopLevelCategory
from ddx.classification.extraction_api import process_documents_by_category

# Process multiple documents - validation runs automatically
result = process_documents_by_category(
    files=[
        Path("simulation_v1.pdf"),
        Path("simulation_v2.pdf"),
        Path("simulation_final.pdf"),
        Path("equipment_datasheet.pdf"),
    ],
    top_level_category=TopLevelCategory.TECHNICAL,  # REQUIRED - enum value
    enable_validation=True,  # Default
    validation_model="gpt-5-nano-2025-08-07",
)

# Access individual results
print(f"Processed: {result.successful}/{result.total_documents}")
for doc in result.results:
    print(f"  {doc.file_name}: {doc.document_type}")

# Access validated results (conflicts resolved)
if result.validation_performed and result.validated_results:
    for doc_type, validated in result.validated_results.items():
        print(f"\n{doc_type}:")
        print(f"  Sources: {validated.source_files}")
        print(f"  Confidence: {validated.overall_confidence:.2f}")
        
        for field_name, field in validated.validated_fields.items():
            print(f"  {field_name}: {field.value}")
            print(f"    Source: {field.source_filename}")
            if field.alternatives:
                print(f"    Alternatives: {field.alternatives}")
```
```

### Example 2: Accessing Validation Details

```python
from ddx.classification.categories import TopLevelCategory

result = process_documents_by_category(
    files=[Path("sim1.pdf"), Path("sim2.pdf")],
    top_level_category=TopLevelCategory.TECHNICAL,
)

if result.validated_results:
    sim_report = result.validated_results.get("Project Simulation Report")
    if sim_report:
        # Check specific field
        pr_field = sim_report.validated_fields.get("performance_ratio_pct")
        if pr_field:
            print(f"Performance Ratio: {pr_field.value}%")
            print(f"Source: {pr_field.source_filename}")
            print(f"Confidence: {pr_field.confidence_score}")
            print(f"Justification: {pr_field.justification}")
            
            if pr_field.flags:
                print(f"⚠️ Warnings: {pr_field.flags}")
```

### Example 3: Company Information Processing

```python
from pathlib import Path
from ddx.classification.categories import TopLevelCategory
from ddx.classification.extraction_api import process_documents_by_category

# Process company information documents
result = process_documents_by_category(
    files=[
        Path("ruc_certificate.pdf"),
        Path("shareholders_declaration.pdf"),
        Path("legal_representative.pdf"),
    ],
    top_level_category=TopLevelCategory.COMPANY_INFORMATION,  # REQUIRED
    enable_validation=True,
)

# Access legal information
if result.validated_results:
    legal_info = result.validated_results.get("Certificate of Legal Existence")
    if legal_info:
        fields = legal_info.validated_fields
        print(f"Company: {fields['legal_name'].value}")
        print(f"RUC: {fields['tax_id_ruc'].value}")
        print(f"Incorporated: {fields['incorporation_date'].value}")
```

### Example 4: Batch Direct Extraction with Validation

```python
from ddx.classification.extraction_api import extract_documents_direct_batch

# Multiple simulation reports - all same type, validation will resolve conflicts
results, validated = extract_documents_direct_batch(
    files=[
        Path("sim_draft.pdf"),
        Path("sim_revised.pdf"),
        Path("sim_final.pdf"),
    ],
    document_type="Project Simulation Report",
    enable_validation=True,
)

# Individual results
for r in results:
    print(f"{r.file_name}: {r.extracted_data.get('performance_ratio_pct')}%")

# Validated (single source of truth)
if validated:
    print(f"\nValidated Performance Ratio: {validated.validated_fields['performance_ratio_pct'].value}%")
    print(f"From: {validated.validated_fields['performance_ratio_pct'].source_filename}")
```

### Example 5: Human-in-the-Loop Correction

```python
from ddx.classification.extraction_api import extract_specific_fields

# User uploads a corrected document for specific fields
# No validation - user document is authoritative
result = extract_specific_fields(
    file=Path("corrected_simulation.pdf"),
    document_type="Project Simulation Report",
    fields=["performance_ratio_pct", "total_pv_energy_mwh"],
)

if result.success:
    print("Corrected values:")
    for field, value in result.extracted_fields.items():
        print(f"  {field}: {value}")
```

### Example 6: Disabling Validation

```python
from ddx.classification.categories import TopLevelCategory

# If you don't need validation or don't have OpenAI key
result = process_documents_by_category(
    files=[Path("doc1.pdf"), Path("doc2.pdf")],
    top_level_category=TopLevelCategory.TECHNICAL,
    enable_validation=False,
)

# Only individual results available
print(result.validation_performed)  # False
print(result.validated_results)     # None
```

### Example 7: Multi-Category with Validation

```python
from ddx.classification.categories import TopLevelCategory
from ddx.classification.extraction_api import process_documents_multi_category

results = process_documents_multi_category(
    files_by_category={
        TopLevelCategory.TECHNICAL: [
            Path("sim1.pdf"),
            Path("sim2.pdf"),
            Path("equipment.pdf"),
        ],
        TopLevelCategory.COMPANY_INFORMATION: [
            Path("ruc.pdf"),
            Path("shareholders.pdf"),
        ],
    },
    enable_validation=True,
)

for category, batch_result in results.items():
    print(f"\n{category.value.upper()}:")
    print(f"  Processed: {batch_result.successful}/{batch_result.total_documents}")
    print(f"  Validation: {batch_result.validation_performed}")
    
    if batch_result.validated_results:
        for doc_type, validated in batch_result.validated_results.items():
            print(f"  {doc_type}: {len(validated.validated_fields)} fields validated")
```

### Example 8: FastAPI Integration with Validation

```python
from fastapi import FastAPI, UploadFile, File, Form
from typing import List
from ddx.classification.categories import TopLevelCategory
from ddx.classification.extraction_api import (
    process_documents_by_category,
    parse_top_level_category,
)

app = FastAPI()

@app.post("/api/process")
async def process_documents(
    files: List[UploadFile] = File(...),
    category: str = Form(...),  # e.g., "Company Information" or "Technical"
    enable_validation: bool = Form(True),
):
    # Parse category string to enum
    try:
        top_level_category = parse_top_level_category(category)
    except ValueError as e:
        return {"error": str(e)}
    
    file_inputs = []
    for f in files:
        content = await f.read()
        file_inputs.append({"content": content, "name": f.filename})
    
    result = process_documents_by_category(
        files=file_inputs,
        top_level_category=top_level_category,
        enable_validation=enable_validation,
    )
    
    response = {
        "top_level_category": result.top_level_category,
        "total": result.total_documents,
        "successful": result.successful,
        "failed": result.failed,
        "validation_performed": result.validation_performed,
    }
    
    # Include validated results if available
    if result.validated_results:
        response["validated"] = {
            doc_type: {
                "source_files": v.source_files,
                "confidence": v.overall_confidence,
                "fields": {
                    name: {
                        "value": f.value,
                        "source": f.source_filename,
                        "confidence": f.confidence_score,
                    }
                    for name, f in v.validated_fields.items()
                }
            }
            for doc_type, v in result.validated_results.items()
        }
    
    return response
```

---

## Convenience Functions

### `get_supported_categories()`

Get list of all supported top-level categories as strings.

```python
from ddx.classification.extraction_api import get_supported_categories
categories = get_supported_categories()
# ['Company Information', 'Technical', 'ESG', 'Financial', 'Legal', 'Regulatory']
```

### `get_document_types_for_category_api()`

Get list of document types for a category (API-friendly, accepts string).

```python
from ddx.classification.extraction_api import get_document_types_for_category_api
doc_types = get_document_types_for_category_api("Company Information")
# ['Certificate of Legal Existence', 'Shareholders Declaration', 'Legal Representative Appointment']

doc_types = get_document_types_for_category_api("Technical")
# ['Project Simulation Report', 'Project Data Main Equipment Sheets', ...]
```

### `parse_top_level_category()`

Parse a string to `TopLevelCategory` enum (case-insensitive).

```python
from ddx.classification.extraction_api import parse_top_level_category

# All of these work:
cat = parse_top_level_category("Company Information")
cat = parse_top_level_category("company_information")
cat = parse_top_level_category("COMPANY_INFORMATION")
# Returns: TopLevelCategory.COMPANY_INFORMATION
```

### `get_fields_for_document_type()`

Get schema fields for a document type.

```python
from ddx.classification.extraction_api import get_fields_for_document_type
fields = get_fields_for_document_type("Certificate of Legal Existence")
# {
#   'legal_name': {'type': 'str', 'description': '...', 'required': True},
#   'tax_id_ruc': {'type': 'str', 'description': '...', 'required': True},
#   ...
# }
```

### `get_all_schemas_info()`

Get information about all available schemas, organized by category.

```python
from ddx.classification.extraction_api import get_all_schemas_info
all_schemas = get_all_schemas_info()
# {
#   'Company Information': {
#     'Certificate of Legal Existence': {...},
#     'Shareholders Declaration': {...},
#     ...
#   },
#   'Technical': {
#     'Project Simulation Report': {...},
#     ...
#   },
#   ...
# }
```

### `validate_batch_results()`

Manually run validation on existing results.

```python
from ddx.classification.categories import TopLevelCategory
from ddx.classification.extraction_api import validate_batch_results

# If you have DocumentResult objects from elsewhere
validated = validate_batch_results(
    results=list_of_document_results,
    top_level_category=TopLevelCategory.TECHNICAL,
    validation_model="gpt-5-nano-2025-08-07",
)
```

---

## Error Handling

### Common Errors

| Error | Cause | Solution |
|-------|-------|----------|
| `RuntimeError: Missing API key` | No LandingAI API key | Set `VISION_AGENT_API_KEY` |
| `RuntimeError: Missing OpenAI API key` | Validation enabled but no key | Set `OPENAI_API_KEY` or `enable_validation=False` |
| `ValueError: Unknown category` | Invalid category string | Use valid category from `get_supported_categories()` or `TopLevelCategory` enum |
| `ValueError: Unknown document type` | Invalid document type | Check `PYDANTIC_MODELS` keys |
| `429 Too Many Requests` | Rate limit exceeded | Reduce `rate_limit` and `max_concurrent` |

### Validation Warnings

Validation may produce flags in the output:

```python
if validated_field.flags:
    for flag in validated_field.flags:
        print(f"⚠️ {flag}")
```

Common flags:
- `"low_confidence"` - AI was uncertain about selection
- `"significant_variance"` - Large difference between candidate values
- `"single_source"` - Only one document had this field

---

## Output Directory Structure

When using `landing_ai_poc_sdk.py` CLI, outputs are organized hierarchically:

```
out_sdk/
├── records/
│   ├── Company_Information/                    ← Top-level category
│   │   ├── Certificate_of_Legal_Existence_Tax_ID/  ← Document type
│   │   │   ├── company_cert.json
│   │   │   └── company_cert_2.json
│   │   ├── Shareholders_Declaration/
│   │   │   └── shareholders.json
│   │   └── Legal_Representative_Appointment/
│   │       └── legal_rep.json
│   └── Technical/
│       ├── Project_Simulation_Report/
│       │   ├── sim_v1.json
│       │   └── sim_v2.json
│       └── Project_Layout/
│           └── layout.json
├── markdown/
│   ├── Company_Information/
│   │   ├── Certificate_of_Legal_Existence_Tax_ID/
│   │   │   ├── company_cert.md
│   │   │   └── company_cert.parse.json
│   │   └── ...
│   └── Technical/
│       └── ...
└── validated/                                  ← Output from validation_layer.py
    ├── Company_Information/
    │   ├── Certificate_of_Legal_Existence_Tax_ID/
    │   │   ├── validation_report.json
    │   │   └── final_extraction.json
    │   └── ...
    └── Technical/
        └── ...
```

---

## Function Comparison

| Aspect | `process_documents_by_category` | `extract_specific_fields` | `extract_document_direct` |
|--------|--------------------------------|---------------------------|---------------------------|
| **Use Case** | Batch processing | Human-in-the-loop | Known document type |
| **Classification** | ✅ Yes (within category) | ❌ No | ❌ No |
| **top_level_category** | ✅ **Required** | ❌ Not needed | ❌ Not needed |
| **Validation** | ✅ Yes (optional) | ❌ No | ✅ Yes (batch only) |
| **Fields Extracted** | All (full schema) | Specified only | All (full schema) |
| **Input** | Multiple files | Single file | Single/Multiple files |
| **API Calls/Doc** | Parse + Classify + Extract | Parse + Extract | Parse + Extract |

---

## Migration from Previous Version

If you were using the old API with string `category` parameter:

### Before (Old API)
```python
# OLD - No longer works
result = process_documents_by_category(
    files=[...],
    category="technical",  # String
)
```

### After (New API)
```python
from ddx.classification.categories import TopLevelCategory

# NEW - Use enum
result = process_documents_by_category(
    files=[...],
    top_level_category=TopLevelCategory.TECHNICAL,  # Enum
)

# Or use parse helper for dynamic strings (e.g., from user input)
from ddx.classification.extraction_api import parse_top_level_category

category_str = "Technical"  # From user input
top_level = parse_top_level_category(category_str)
result = process_documents_by_category(
    files=[...],
    top_level_category=top_level,
)
```

### Key Changes
1. `category` parameter renamed to `top_level_category`
2. `top_level_category` is now **required** (not optional)
3. Must use `TopLevelCategory` enum (not string)
4. Response models use `top_level_category` field instead of `category`
