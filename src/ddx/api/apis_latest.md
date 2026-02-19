# DDX — Document Due Diligence Extraction API

**Version:** 2.0.0  
**Base URL:** `http://<host>:8000`  
**Docs:** `/docs` (Swagger UI) · `/redoc` (ReDoc)

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [S3 Usage Overview](#s3-usage-overview)
- [Environment Variables](#environment-variables)
- [Health & Discovery Endpoints](#health--discovery-endpoints)
  - [GET /health](#get-health)
  - [GET /api/v1/schemas/categories](#get-apiv1schemascategories)
  - [GET /api/v1/schemas/categories/{category}](#get-apiv1schemascategoriescategory)
  - [GET /api/v1/schemas/document-types/{document_type}](#get-apiv1schemasdocument-typesdocument_type)
  - [GET /api/v1/schemas/document-types](#get-apiv1schemasdocument-types)
- [Extraction Endpoints](#extraction-endpoints)
  - [POST /api/v1/extract/bulk](#post-apiv1extractbulk)
  - [POST /api/v1/extract/targeted](#post-apiv1extracttargeted)
  - [POST /api/v1/extract/validate](#post-apiv1extractvalidate)
- [NestJS Request Mapping](#nestjs-request-mapping)
  - [Contract Matrix](#contract-matrix)
  - [Field Ownership Map](#field-ownership-map)
- [Validation Matching Logic](#validation-matching-logic)
- [Shared Models](#shared-models)
- [Field Grounding](#field-grounding)
- [Error Handling](#error-handling)

---

## Architecture Overview

```
Request ──► main.py (FastAPI routes)
               │
               ▼
           services.py (S3 download, orchestration, response assembly)
               │
               ▼
           extraction_api.py (parse, classify, extract, validate, S3 cache)
               │
               ▼
           LandingAI SDK (dpt-2-latest / extract-latest)
```

| Layer               | File                                        | Responsibility                                                        |
|---------------------|---------------------------------------------|-----------------------------------------------------------------------|
| **Routes**          | `src/ddx/api/main.py`                       | FastAPI endpoint definitions, request logging, error handling         |
| **Models**          | `src/ddx/api/models.py`                     | Pydantic request/response schemas                                     |
| **Services**        | `src/ddx/api/services.py`                   | S3 file download, result transformation, validation orchestration    |
| **Extraction Core** | `src/ddx/classification/extraction_api.py`  | Document parsing, classification, extraction, S3 caching, grounding  |

---

## S3 Usage Overview

S3 is used in **two distinct ways** across the API:

### 1. Document Download (services.py)

All three extraction endpoints accept `s3_paths` — S3 object keys pointing to PDF documents. The service layer downloads these to a local temp directory before processing.

| Step | Function | Description |
|------|----------|-------------|
| Download | `download_s3_files()` | Downloads all S3 paths concurrently via `aioboto3` to a temp directory |
| Track | `ResolvedFiles` | Maps S3 paths → local paths and builds lookup tables |
| Cleanup | `cleanup_temp_dir()` | Removes temp directory in `finally` block after processing |

**Config:** Bucket from `req.bucket` field or `S3_BUCKET` env var (default: `drex-network`). Region from `AWS_REGION` (default: `us-east-1`).

### 2. Parse Cache (extraction_api.py)

After parsing a document via the LandingAI SDK, both the **markdown output** and the **parse.json** (chunk data with bounding boxes) are cached to S3. On subsequent requests for the same document (matched by SHA-256 content hash), the cached versions are returned — skipping the expensive parse call.

| Artifact | S3 Key Pattern | Content Type |
|----------|----------------|--------------|
| Markdown | `{prefix}/{sha256}.md` | `text/markdown; charset=utf-8` |
| Parse metadata | `{prefix}/{sha256}.meta.json` | `application/json; charset=utf-8` |
| Parse response (chunks) | `{prefix}/{sha256}.parse.json` | `application/json; charset=utf-8` |

**Cache flow:**

```
Document ──► SHA-256 hash ──► Check S3 for {hash}.md
                                 │
                    ┌────────────┴────────────┐
                    ▼                         ▼
               Cache HIT                 Cache MISS
          Load .md + .parse.json      Parse via SDK
          Return cached data          Upload .md + .meta.json + .parse.json
                                      Return fresh data
```

**Why cache parse.json?**  
The parse response contains chunk-level bounding boxes (`grounding` data). By caching it alongside the markdown, **field grounding** (source locations) remains available even on cache hits, avoiding the need to re-parse.

**Config:** Cache is enabled via `markdown_cache=True` parameter. Bucket from `DDX_MARKDOWN_CACHE_BUCKET` or `S3_BUCKET`. Prefix from `DDX_MARKDOWN_CACHE_PREFIX` (default: `ddx-cache/markdown`).

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `S3_BUCKET` | `drex-network` | Default S3 bucket for document downloads |
| `AWS_REGION` | `us-east-1` | AWS region for S3 operations |
| `S3_MAX_POOL` | `50` | Max connection pool size for S3 clients |
| `DDX_MARKDOWN_CACHE_BUCKET` | Falls back to `S3_BUCKET` | S3 bucket for parse cache |
| `DDX_MARKDOWN_CACHE_PREFIX` | `ddx-cache/markdown` | S3 key prefix for cached artifacts |
| `LANDING_PARSE_MODEL` | `dpt-2-latest` | LandingAI parse model |
| `LANDING_EXTRACT_MODEL` | `extract-latest` | LandingAI extraction model |
| `LOG_LEVEL` | `INFO` | Logging level |
| `PORT` | `8000` | Server port |
| `RELOAD` | _(empty)_ | Enable auto-reload for development |

---

## Health & Discovery Endpoints

### GET /health

Health check — returns API status, version, and supported categories.

**Tags:** `Health`

**Internal call chain:**
```
main.health() → get_supported_categories(), CATEGORY_DOCUMENT_TYPES
```

**S3 usage:** None.

**Response model:** `HealthResponse`

```json
{
  "status": "ok",
  "version": "2.0.0",
  "supported_categories": ["Company Information", "Technical", ...],
  "total_document_types": 12,
  "timestamp": "2026-02-09T14:30:00+00:00"
}
```

---

### GET /api/v1/schemas/categories

List all supported top-level categories with their document types.

**Tags:** `Schema Discovery`

**Internal call chain:**
```
main.list_categories() → get_supported_categories()
                        → get_document_types_for_category_api()
```

**S3 usage:** None.

**Response model:** `List[CategoryInfo]`

```json
[
  {
    "name": "Technical",
    "document_types": ["Project Simulation Report", "Project Layout", ...],
    "document_count": 5
  }
]
```

---

### GET /api/v1/schemas/categories/{category}

Get document types for a specific top-level category.

**Tags:** `Schema Discovery`

**Path parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `category` | `string` | URL-encoded category name (e.g., `Company%20Information`) |

**Internal call chain:**
```
main.get_category() → get_document_types_for_category_api(category)
```

**S3 usage:** None.

**Response model:** `CategoryInfo`

**Error responses:**
| Status | Condition |
|--------|-----------|
| `404` | Category not found |

```json
{
  "name": "Technical",
  "document_types": ["Project Simulation Report", "Project Layout"],
  "document_count": 2
}
```

---

### GET /api/v1/schemas/document-types/{document_type}

Get the field schema for a specific document type. Useful for knowing which `target_fields` to pass to the validation endpoint.

**Tags:** `Schema Discovery`

**Path parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `document_type` | `string` | URL-encoded document type name |

**Internal call chain:**
```
main.get_document_type_schema() → get_fields_for_document_type(document_type)
                                 → _get_top_level_for_document_type(document_type)
```

**S3 usage:** None.

**Response model:** `DocumentTypeInfo`

**Error responses:**
| Status | Condition |
|--------|-----------|
| `404` | Document type not found |

```json
{
  "name": "Project Simulation Report",
  "top_level_category": "Technical",
  "fields": {
    "performance_ratio_pct": { "type": "float", "description": "..." },
    "total_pv_energy_mwh": { "type": "float", "description": "..." }
  },
  "field_count": 15
}
```

---

### GET /api/v1/schemas/document-types

Get all document types grouped by category with their field schemas.

**Tags:** `Schema Discovery`

**Internal call chain:**
```
main.list_all_document_types() → get_all_schemas_info()
```

**S3 usage:** None.

**Response model:** `Dict[str, Any]`

```json
{
  "Technical": {
    "document_types": {
      "Project Simulation Report": {
        "fields": { ... },
        "field_count": 15
      }
    }
  }
}
```

---

## Extraction Endpoints

### POST /api/v1/extract/bulk

**Type 1 — Bulk Ingestion (unknown requirement, unknown value)**

Upload documents without selecting a requirement. AI classifies each document into its document type and extracts all fields. Optionally validates and resolves conflicts when multiple documents classify as the same type.

**Tags:** `Extraction`

**Internal call chain:**
```
main.endpoint_bulk_ingest(req)
  → services.bulk_ingest(req)
      → download_s3_files(req.s3_paths, req.bucket)          # S3 download
      → ResolvedFiles(s3_paths, path_mapping)                 # Resolve local paths
      │
      ├─ [with category hint]:
      │    → _bulk_ingest_with_category(resolved, req)
      │        → _process_with_category(file_paths, top_level, req)
      │            → extraction_api.process_documents_by_category_async(...)
      │                → _process_single_document() per file
      │                    → _parse_with_cache()              # S3 cache read/write
      │                    → _async_classify_from_markdown()
      │                    → _async_extract_fields()
      │                    → _resolve_field_grounding()
      │                → validate_batch_results()             # Optional validation
      │        → _convert_document_results()
      │
      ├─ [without category hint]:
      │    → _process_all_categories(file_paths, req, path_mapping)
      │        → for each TopLevelCategory:
      │            → _try_process_category()
      │        → _deduplicate_results()                       # Best result per file
      │        → _fill_missing_files()                        # Uncategorized placeholders
      │        → _convert_document_results()
      │
      → _assemble_bulk_response()
      → cleanup_temp_dir()
```

**S3 usage:**
1. **Document download** — All `s3_paths` are downloaded to a temp directory via `aioboto3`
2. **Parse cache** — Each document's parse result (markdown + parse.json) is cached to S3 for reuse. On cache hit, the parse step is skipped entirely.
3. **Temp cleanup** — Temp directory is removed after processing (in `finally` block)

#### Request Body

**Model:** `BulkIngestionRequest`

```json
{
  "s3_paths": [
    "projects/solar-1/simulation_report.pdf",
    "projects/solar-1/equipment_sheet.pdf"
  ],
  "bucket": "my-bucket",
  "project_id": "solar-project-1",
  "top_level_category": "Technical",
  "max_concurrent": 5,
  "enable_validation": true,
  "validation_model": "gpt-5-nano-2025-08-07",
  "config": {
    "parse_model": "dpt-2-latest",
    "extract_model": "extract-latest",
    "rate_limit": 10.0
  }
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `s3_paths` | `List[str]` | **Yes** | — | S3 object keys to process (min 1) |
| `bucket` | `string` | No | env `S3_BUCKET` | S3 bucket name |
| `project_id` | `string` | No | `"default_project"` | Project identifier for grouping |
| `top_level_category` | `string` | No | `null` | Category hint to narrow classification. If omitted, classifies across ALL categories |
| `max_concurrent` | `int` | No | `5` | Max concurrent processing tasks (1–20) |
| `enable_validation` | `bool` | No | `true` | Resolve conflicts when multiple docs classify as same type |
| `validation_model` | `string` | No | `"gpt-5-nano-2025-08-07"` | Model for conflict resolution |
| `config` | `ProcessingConfig` | No | defaults | Parse/extract model and rate limit config |

#### Response Body

**Model:** `BulkIngestionResponse`

```json
{
  "project_id": "solar-project-1",
  "total_documents": 2,
  "successful": 2,
  "failed": 0,
  "processed_documents": [
    {
      "file_name": "simulation_report.pdf",
      "s3_path": "projects/solar-1/simulation_report.pdf",
      "document_type": "Project Simulation Report",
      "top_level_category": "Technical",
      "extracted_data": {
        "performance_ratio_pct": 81.5,
        "total_pv_energy_mwh": 12500.0
      },
      "extraction_metadata": { ... },
      "field_grounding": {
        "performance_ratio_pct": [
          {
            "chunk_id": "chunk_abc123",
            "page": 3,
            "bounding_box": { "l": 0.1, "t": 0.45, "r": 0.6, "b": 0.48 },
            "chunk_type": "text"
          }
        ]
      },
      "success": true,
      "error": null
    }
  ],
  "validated_results": {
    "Project Simulation Report": {
      "document_type": "Project Simulation Report",
      "validated_fields": {
        "performance_ratio_pct": {
          "value": 81.5,
          "confidence_score": 0.95,
          "justification": "Selected from executive summary table with complete project signature.",
          "source_file": "projects/solar-1/simulation_report.pdf",
          "source_filename": "simulation_report.pdf",
          "locations": [
            {
              "page": 3,
              "chunk_id": "chunk_abc123",
              "box": { "l": 0.1, "t": 0.45, "r": 0.6, "b": 0.48 }
            }
          ]
        },
        "total_pv_energy_mwh": {
          "value": 12500.0,
          "confidence_score": 0.92,
          "justification": "Consistent with annual production line item in validated source document.",
          "source_file": "projects/solar-1/simulation_report.pdf",
          "source_filename": "simulation_report.pdf",
          "locations": [
            {
              "page": 4,
              "chunk_id": "chunk_def456",
              "box": { "l": 0.12, "t": 0.52, "r": 0.7, "b": 0.56 }
            }
          ]
        }
      }
    }
  },
  "classification_summary": {
    "Project Simulation Report": 1,
    "Main Equipment Sheets": 1
  },
  "errors": []
}
```

| Field | Type | Description |
|-------|------|-------------|
| `project_id` | `string` | Echo of request project_id |
| `total_documents` | `int` | Total number of S3 paths submitted |
| `successful` | `int` | Count of successfully processed documents |
| `failed` | `int` | Count of failed documents |
| `processed_documents` | `List[BulkDocumentResult]` | Per-document results |
| `validated_results` | `Dict` / `null` | Conflict-resolved results grouped by document type |
| `classification_summary` | `Dict[str, int]` | Count of docs per document type |
| `errors` | `List[DocumentProcessingError]` | Error details for failed documents |

**Error responses:**
| Status | Condition |
|--------|-----------|
| `400` | Invalid request (empty s3_paths, bad category) |
| `500` | Internal processing error |

**Request received from NestJS (Data Room ingestion unknown):**

NestJS calls this endpoint via `DueDiligenceApiServiceClient.extractBulk(...)` from `app-drex-projects`.

Typical payload sent from NestJS:

```json
{
  "s3_paths": ["s3://.../doc1.pdf", "s3://.../doc2.pdf"],
  "project_id": "101",
  "top_level_category": "Technical",
  "enable_validation": true,
  "config": {
    "parse_model": "dpt-2-latest",
    "extract_model": "extract-latest",
    "rate_limit": 10.0
  }
}
```

---

### POST /api/v1/extract/targeted

**Type 2 — Targeted Completion (known requirement, unknown value)**

Upload documents for a specific, known document type. AI skips classification and extracts all variables for that type. Optionally validates across multiple files.

**Tags:** `Extraction`

**Internal call chain:**
```
main.endpoint_targeted_completion(req)
  → services.targeted_completion(req)
      → _resolve_document_type(req.document_type)            # Validate doc type
      → download_s3_files(req.s3_paths, req.bucket)          # S3 download
      → ResolvedFiles(...)
      → extraction_api.extract_documents_direct_batch_async(...)
          → extract_document_direct_async() per file
              → _parse_or_use_existing()
                  → _parse_with_cache()                      # S3 cache read/write
              → _async_extract_fields()
              → _resolve_field_grounding()
          → validate_batch_results()                         # Optional validation
      → _assemble_targeted_response()
      → cleanup_temp_dir()
```

**S3 usage:**
1. **Document download** — All `s3_paths` downloaded to temp directory
2. **Parse cache** — Markdown + parse.json cached to S3 per document
3. **Temp cleanup** — Temp directory removed after processing

#### Request Body

**Model:** `TargetedCompletionRequest`

```json
{
  "s3_paths": [
    "projects/solar-1/simulation_report.pdf"
  ],
  "bucket": "my-bucket",
  "document_type": "Project Simulation Report",
  "project_id": "solar-project-1",
  "max_concurrent": 5,
  "enable_validation": true,
  "validation_model": "gpt-5-nano-2025-08-07",
  "config": {
    "parse_model": "dpt-2-latest",
    "extract_model": "extract-latest",
    "rate_limit": 10.0
  }
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `s3_paths` | `List[str]` | **Yes** | — | S3 object keys to process (min 1) |
| `bucket` | `string` | No | env `S3_BUCKET` | S3 bucket name |
| `document_type` | `string` | **Yes** | — | Known document type (e.g., `"Project Simulation Report"`) |
| `project_id` | `string` | No | `"default_project"` | Project identifier |
| `max_concurrent` | `int` | No | `5` | Max concurrent tasks (1–20) |
| `enable_validation` | `bool` | No | `true` | Resolve conflicts across files |
| `validation_model` | `string` | No | `"gpt-5-nano-2025-08-07"` | Conflict resolution model |
| `config` | `ProcessingConfig` | No | defaults | Parse/extract model config |

#### Response Body

**Model:** `TargetedCompletionResponse`

```json
{
  "document_type": "Project Simulation Report",
  "top_level_category": "Technical",
  "project_id": "solar-project-1",
  "total_documents": 1,
  "successful": 1,
  "failed": 0,
  "individual_results": [
    {
      "file_name": "simulation_report.pdf",
      "s3_path": "projects/solar-1/simulation_report.pdf",
      "document_type": "Project Simulation Report",
      "top_level_category": "Technical",
      "extracted_data": {
        "performance_ratio_pct": 81.5,
        "total_pv_energy_mwh": 12500.0,
        "annual_degradation_pct": 0.5
      },
      "extraction_metadata": { ... },
      "field_grounding": { ... },
      "success": true,
      "error": null
    }
  ],
  "consolidated_result": {
    "document_type": "Project Simulation Report",
    "validated_fields": {
      "performance_ratio_pct": {
        "value": 81.5,
        "confidence_score": 0.95,
        "justification": "Best-supported value selected from final signed simulation section.",
        "source_file": "projects/solar-1/simulation_report.pdf",
        "source_filename": "simulation_report.pdf",
        "locations": [
          {
            "page": 3,
            "chunk_id": "chunk_abc123",
            "box": { "l": 0.1, "t": 0.45, "r": 0.6, "b": 0.48 }
          }
        ]
      },
      "total_pv_energy_mwh": {
        "value": 12500.0,
        "confidence_score": 0.92,
        "justification": "Selected from the same source document to keep field consistency.",
        "source_file": "projects/solar-1/simulation_report.pdf",
        "source_filename": "simulation_report.pdf",
        "locations": [
          {
            "page": 4,
            "chunk_id": "chunk_def456",
            "box": { "l": 0.12, "t": 0.52, "r": 0.7, "b": 0.56 }
          }
        ]
      }
    }
  },
  "extraction_metadata": null,
  "errors": []
}
```

| Field | Type | Description |
|-------|------|-------------|
| `document_type` | `string` | Canonical resolved document type (may differ from snake_case input) |
| `top_level_category` | `string` | Resolved parent category |
| `project_id` | `string` | Echo of project_id |
| `total_documents` | `int` | Total S3 paths submitted |
| `successful` / `failed` | `int` | Success/fail counts |
| `individual_results` | `List[TargetedDocumentResult]` | Per-document results with extracted data and grounding |
| `consolidated_result` | `Dict` / `null` | Validated/merged result across all files (when `enable_validation=true`) |
| `extraction_metadata` | `Dict` / `null` | Merged extraction metadata |
| `errors` | `List[DocumentProcessingError]` | Error details |

**Error responses:**
| Status | Condition |
|--------|-----------|
| `400` | Unknown document type, empty s3_paths |
| `500` | Internal processing error |

**Request received from NestJS (Data Room ingest requirement):**

NestJS calls this endpoint via `DueDiligenceApiServiceClient.extractTargeted(...)`.

Typical payload sent from NestJS:

```json
{
  "s3_paths": ["s3://.../known-requirement-doc.pdf"],
  "project_id": "101",
  "document_type": "energy_bills",
  "enable_validation": true,
  "config": {
    "parse_model": "dpt-2-latest",
    "extract_model": "extract-latest",
    "rate_limit": 10.0
  }
}
```

`services.py` normalizes `document_type` through `_resolve_document_type(...)`, so snake_case / kebab-case / case-insensitive values are accepted when they map to a known canonical type.

Contract note:
- **Request (`document_type`)** may be snake_case from NestJS (for example, `tax_compliance_certificate`).
- **Response (`document_type`)** is canonical (for example, `Tax Compliance Certificate`).

---

### POST /api/v1/extract/validate

**Type 3 — Validation / Correction (known requirement, known value)**

Upload document(s) to extract and validate specific fields. AI extracts only the targeted fields and optionally validates against expected values. Returns confidence and evidence for each field.

**Tags:** `Extraction`

**Internal call chain:**
```
main.endpoint_validation_correction(req)
  → services.validation_correction(req)
      → _resolve_document_type(req.document_type)                # Validate doc type
      → _validate_target_fields(doc_type, req.target_fields)     # Validate field names
      → download_s3_files(req.s3_paths, req.bucket)              # S3 download
      → ResolvedFiles(...)
      → _extract_targeted_fields(resolved, req, doc_type)
          │
          ├─ [single file]:
          │    → extraction_api.extract_specific_fields_async(...)
          │        → _parse_or_use_existing()
          │            → _parse_with_cache()                     # S3 cache read/write
          │        → _async_extract() with partial schema
          │        → _resolve_field_grounding()
          │
          ├─ [multiple files]:
          │    → extraction_api.extract_specific_fields_batch_async(...)
          │        → extract_specific_fields_async() per file
          │
      → _build_file_level_results()
      → _merge_field_results()                                   # Best value per field
          → _find_best_field_value()                             # Includes grounding
          → _validate_single_field()                             # Compare vs expected
      → _compute_overall_validation_status()
      → cleanup_temp_dir()
```

**S3 usage:**
1. **Document download** — S3 paths downloaded to temp directory (max 5 files)
2. **Parse cache** — Markdown + parse.json cached to S3 per document
3. **Temp cleanup** — Temp directory removed after processing

#### Request Body

**Model:** `ValidationCorrectionRequest`

```json
{
  "s3_paths": [
    "projects/solar-1/simulation_report.pdf"
  ],
  "bucket": "my-bucket",
  "document_type": "Project Simulation Report",
  "target_fields": [
    "performance_ratio_pct",
    "total_pv_energy_mwh"
  ],
  "expected_values": {
    "performance_ratio_pct": 81.5,
    "total_pv_energy_mwh": 12500
  },
  "project_id": "solar-project-1",
  "config": {
    "parse_model": "dpt-2-latest",
    "extract_model": "extract-latest",
    "rate_limit": 10.0
  }
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `s3_paths` | `List[str]` | **Yes** | — | S3 object keys (min 1, max 5) |
| `bucket` | `string` | No | env `S3_BUCKET` | S3 bucket name |
| `document_type` | `string` | **Yes** | — | Known document type context |
| `target_fields` | `List[str]` | **Yes** | — | Specific field names to extract (min 1) |
| `expected_values` | `Dict[str, Any]` | No | `null` | Expected values for validation (field_name → expected_value) |
| `project_id` | `string` | No | `"default_project"` | Project identifier |
| `config` | `ProcessingConfig` | No | defaults | Parse/extract model config |

#### Response Body

**Model:** `ValidationCorrectionResponse`

```json
{
  "document_type": "Project Simulation Report",
  "top_level_category": "Technical",
  "project_id": "solar-project-1",
  "requested_fields": ["performance_ratio_pct", "total_pv_energy_mwh"],
  "extracted_fields": {
    "performance_ratio_pct": {
      "field_name": "performance_ratio_pct",
      "value": 81.5,
      "confidence": 0.95,
      "evidence": [
        { "reference": "chunk_abc123" }
      ],
      "grounding": [
        {
          "chunk_id": "chunk_abc123",
          "page": 3,
          "bounding_box": { "l": 0.1, "t": 0.45, "r": 0.6, "b": 0.48 },
          "chunk_type": "text"
        }
      ],
      "extracted_text": "Performance Ratio: 81.5%",
      "validation_status": "match",
      "expected_value": 81.5,
      "source_file": "simulation_report.pdf"
    },
    "total_pv_energy_mwh": {
      "field_name": "total_pv_energy_mwh",
      "value": 12500.0,
      "confidence": 0.92,
      "evidence": [],
      "grounding": [
        {
          "chunk_id": "chunk_def456",
          "page": 4,
          "bounding_box": { "l": 0.12, "t": 0.52, "r": 0.7, "b": 0.56 },
          "chunk_type": "table"
        }
      ],
      "extracted_text": "Total PV Energy: 12,500 MWh",
      "validation_status": "match",
      "expected_value": 12500,
      "source_file": "simulation_report.pdf"
    }
  },
  "overall_validation_status": "all_match",
  "file_results": [
    {
      "file_name": "simulation_report.pdf",
      "s3_path": "projects/solar-1/simulation_report.pdf",
      "success": true,
      "extracted_fields": {
        "performance_ratio_pct": 81.5,
        "total_pv_energy_mwh": 12500.0
      }
    }
  ],
  "errors": []
}
```

| Field | Type | Description |
|-------|------|-------------|
| `document_type` | `string` | Canonical resolved document type (may differ from snake_case input) |
| `top_level_category` | `string` | Resolved parent category |
| `project_id` | `string` | Echo of project_id |
| `requested_fields` | `List[str]` | Echo of target_fields |
| `extracted_fields` | `Dict[str, FieldValidationResult]` | Per-field results with value, confidence, grounding, and validation status |
| `overall_validation_status` | `string` / `null` | `"all_match"`, `"some_mismatch"`, `"all_mismatch"`, or `null` if no expected values |
| `file_results` | `List[Dict]` | Per-file extraction details |
| `errors` | `List[DocumentProcessingError]` | Error details |

**Validation status values:**

| Field-level | Overall-level | Meaning |
|-------------|---------------|---------|
| `"match"` | `"all_match"` | Extracted value matches expected (numeric: within 1% tolerance) |
| `"mismatch"` | `"all_mismatch"` | Values differ |
| `"uncertain"` | `"some_mismatch"` | Could not extract or partial match |
| `null` | `null` | No expected value provided |

**Error responses:**
| Status | Condition |
|--------|-----------|
| `400` | Unknown document type, invalid field names, empty s3_paths or target_fields |
| `500` | Internal processing error |

**Request received from NestJS (Type-3 + edit-with-doc validation):**

NestJS calls this endpoint via `DueDiligenceApiServiceClient.extractValidate(...)`.

Typical payload sent from NestJS:

```json
{
  "s3_paths": ["s3://.../proof.pdf"],
  "project_id": "101",
  "document_type": "tax_compliance_certificate",
  "target_fields": ["issuance_date"],
  "expected_values": {
   "issuance_date": "2025-12-31"
  },
  "config": {
   "parse_model": "dpt-2-latest",
   "extract_model": "extract-latest",
   "rate_limit": 10.0
  }
}
```

Important:
- `document_type` is normalized first (`_resolve_document_type`) to canonical form (e.g., `Tax Compliance Certificate`).
- Field extraction now uses that canonical type (`_extract_targeted_fields(..., doc_type)`), which prevents failures caused by snake_case names.

---

## NestJS Request Mapping

This API is invoked by NestJS service client methods in `app-drex-projects/src/projects/proxy/due-diligence-api-service.client.ts`:

- `extractBulk(...)` → `POST /api/v1/extract/bulk`
- `extractTargeted(...)` → `POST /api/v1/extract/targeted`
- `extractValidate(...)` → `POST /api/v1/extract/validate`

### Mapping by Data Room flow

1. **Unknown requirement ingestion** (`ingest/unknown`)  
  NestJS builds `s3_paths`, `project_id`, optional `top_level_category`, and model config, then calls `extractBulk`.

2. **Known requirement ingestion** (`ingest/requirement`)  
  NestJS maps requirement name/context to `document_type`, then calls `extractTargeted`.

3. **Known field ingestion** (`ingest/field`) and **edit-with-doc async validation**  
  NestJS calls `extractValidate` with `document_type`, `target_fields`, and optionally `expected_values`.

### Contract Matrix

| DDX endpoint | NestJS request fields | DDX response fields consumed by NestJS |
|---|---|---|
| `POST /api/v1/extract/bulk` | `s3_paths`, `project_id`, optional `top_level_category`, `enable_validation`, optional `config` | `processed_documents[]`, `validated_results.*.validated_fields.*` |
| `POST /api/v1/extract/targeted` | `s3_paths`, `project_id`, `document_type` (snake_case accepted), `enable_validation`, optional `config` | `individual_results[]`, `consolidated_result.validated_fields.*`, canonical response `document_type` |
| `POST /api/v1/extract/validate` | `s3_paths`, `project_id`, `document_type` (snake_case accepted), `target_fields`, optional `expected_values`, optional `config` | `extracted_fields.*` (`value`, `confidence`, `grounding`, `validation_status`), `overall_validation_status`, `file_results[]`, canonical response `document_type` |

### Field Ownership Map

| DDX endpoint | Response field(s) | NestJS consumer | Consumption purpose |
|---|---|---|---|
| `POST /api/v1/extract/bulk` | `processed_documents[]` | `DataroomIngestionService.callAiAndProcessResults` | Per-document extraction iteration, requirement resolution, append-only extraction inserts |
| `POST /api/v1/extract/bulk` | `validated_results.*.validated_fields.*` | `DataroomIngestionService.callAiAndProcessResults` | Source selection/value-confidence-justification for canonical write decision |
| `POST /api/v1/extract/targeted` | `individual_results[]` | `DataroomIngestionService.callAiAndProcessResults` | Known-requirement per-document extraction iteration and inserts |
| `POST /api/v1/extract/targeted` | `consolidated_result.validated_fields.*` | `DataroomIngestionService.callAiAndProcessResults` | Multi-doc validation-selected source application (value/confidence/locations) |
| `POST /api/v1/extract/validate` | `extracted_fields[field].value` | `DataroomIngestionService.callAiForFieldAndProcess`; `DataroomUserActionService.runAiValidationForEditWithDocument` | Field-level extraction persistence and canonical value/link logic |
| `POST /api/v1/extract/validate` | `extracted_fields[field].confidence`, `grounding`, `extracted_text` | Same as above | Confidence and grounding persistence for audit trails and UI evidence |
| `POST /api/v1/extract/validate` | `extracted_fields[field].validation_status`, `overall_validation_status` | `DataroomUserActionService.runAiValidationForEditWithDocument` | Async edit-with-doc AI outcome (`passed`/`failed`) and source-link update gating |

---

## Validation Matching Logic

Matching is computed in `src/ddx/api/services.py` in these functions:

1. `_validate_single_field(field_name, extracted_value, expected_values)`
  - If no expected value is provided for that field, returns `(None, None)`.
  - If extracted value is missing (`None`) but expected exists, returns `("uncertain", expected)`.
  - Otherwise delegates comparison to `_compare_values(...)`.

2. `_compare_values(extracted, expected)`
  - Normalizes both values to lowercase strings and checks exact equality → `"match"`.
  - If not exact, attempts numeric comparison via `_compare_numeric(...)`.
  - If one string contains the other, returns `"uncertain"`.
  - Else returns `"mismatch"`.

3. `_compare_numeric(ext_str, exp_str)`
  - Parses both values as numbers (commas and `%` removed).
  - Returns `"match"` when relative difference is less than 1%.
  - Returns `"mismatch"` otherwise.
  - Returns `None` when values are non-numeric.

4. `_compute_overall_validation_status(extracted_fields, expected_values)`
  - `all_match` when all field statuses are `match`.
  - `all_mismatch` when all are `mismatch`.
  - `some_mismatch` for mixed statuses (`match`/`mismatch`/`uncertain`).
  - `None` when no expected values are provided.

### Where user-provided value is compared

Comparison happens during `validation_correction(...)` after extraction:

1. Extract targeted fields from LandingAI.
2. Build merged field results (`_merge_field_results(...)`).
3. For each requested field, compare extracted value against `expected_values[field]` via `_validate_single_field(...)`.
4. Return per-field `validation_status` and aggregated `overall_validation_status` in response.

This is the same comparison path used by NestJS edit-with-doc async validation when it sends `expected_values` from the user input.

---

## Shared Models

### ProcessingConfig

Shared configuration included in all extraction request bodies.

```json
{
  "parse_model": "dpt-2-latest",
  "extract_model": "extract-latest",
  "rate_limit": 10.0
}
```

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `parse_model` | `string` | `"dpt-2-latest"` | — | LandingAI parse model |
| `extract_model` | `string` | `"extract-latest"` | — | LandingAI extraction model |
| `rate_limit` | `float` | `10.0` | 1.0–50.0 | Max API requests per second |

### DocumentProcessingError

Returned in the `errors` array of all extraction responses.

```json
{
  "file_name": "broken.pdf",
  "error_type": "ExtractionError",
  "error_message": "Failed to parse document"
}
```

---

## Field Grounding

Field grounding provides the physical source location in the original document for each extracted value. It is included in all extraction endpoint responses.

### How it works

1. **Parse** — LandingAI SDK parses the PDF and produces chunks, each with a `chunk_id` and `grounding` array (page number + bounding box)
2. **Extract** — The extraction produces `extraction_metadata` mapping each field to the chunk IDs it was derived from (`references`)
3. **Resolve** — The grounding resolver maps each reference to its chunk's page and bounding box

### Grounding structure

**Flat fields** — `field_name → list of locations`:

```json
{
  "field_grounding": {
    "performance_ratio_pct": [
      {
        "chunk_id": "chunk_abc123",
        "page": 3,
        "bounding_box": { "l": 0.1, "t": 0.45, "r": 0.6, "b": 0.48 },
        "chunk_type": "text"
      }
    ]
  }
}
```

**Array fields** — `field_name → list of dicts per array element`:

```json
{
  "field_grounding": {
    "financial_ratios": [
      {
        "year": [
          { "chunk_id": "chunk_001", "page": 5, "bounding_box": { ... }, "chunk_type": "table" }
        ],
        "ratio_value": [
          { "chunk_id": "chunk_002", "page": 5, "bounding_box": { ... }, "chunk_type": "table" }
        ]
      }
    ]
  }
}
```

**Bounding box coordinates** are normalized (0.0–1.0) relative to the page dimensions:
| Field | Description |
|-------|-------------|
| `l` | Left edge |
| `t` | Top edge |
| `r` | Right edge |
| `b` | Bottom edge |

**When grounding is `null`:**  
Grounding may be `null` when pre-existing markdown is supplied (no parse response available) or when the parse cache does not have a stored `parse.json` (legacy cached entries before this feature was added).

---

## Error Handling

All endpoints use consistent error responses:

| Status | Trigger | Response |
|--------|---------|----------|
| `400` | `ValueError` — invalid input | `{"detail": "error message"}` |
| `404` | Resource not found (schema endpoints) | `{"detail": "error message"}` |
| `500` | `RuntimeError` or unhandled exception | `{"detail": "Internal server error: ..."} ` |

Global exception handlers in `main.py` catch `ValueError` (→ 400), `RuntimeError` (→ 500), and a generic catch-all for any unhandled exception (→ 500). All errors are logged with the request ID and duration.
