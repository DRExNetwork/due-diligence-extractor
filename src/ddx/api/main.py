"""
DDX API — Document Due Diligence Extraction API.

Three endpoints mapping to the three AI interaction types:

  POST /api/v1/extract/bulk       — Type 1: Unknown requirement, unknown value
  POST /api/v1/extract/targeted   — Type 2: Known requirement, unknown value
  POST /api/v1/extract/validate   — Type 3: Known requirement, known value

Plus discovery/health endpoints:

  GET  /health
  GET  /api/v1/schemas/categories
  GET  /api/v1/schemas/categories/{category}
    GET  /api/v1/schemas/document-types/{document_type:path}
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ddx.api.models import (
    # Type 1
    BulkIngestionRequest,
    BulkIngestionResponse,
    # Type 2
    TargetedCompletionRequest,
    TargetedCompletionResponse,
    # Type 3
    ValidationCorrectionRequest,
    ValidationCorrectionResponse,
    # Summary
    SummaryGenerationRequest,
    SummaryGenerationResponse,
    # Discovery
    HealthResponse,
    CategoryInfo,
    DocumentTypeInfo,
)
from ddx.api.services import (
    bulk_ingest,
    targeted_completion,
    validation_correction,
    generate_structured_summary,
)
from ddx.classification.extraction_api import (
    get_supported_categories,
    get_document_types_for_category_api,
    get_fields_for_document_type,
    get_all_schemas_info,
    PYDANTIC_MODELS,
    CATEGORY_DOCUMENT_TYPES,
    _get_top_level_for_document_type,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

APP_VERSION = "2.0.0"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("ddx.api")


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="DDX — Document Due Diligence Extraction API",
    version=APP_VERSION,
    description=(
        "AI-powered document processing API with three interaction modes:\n\n"
        "- **Bulk Ingestion** — Upload documents, AI classifies & extracts everything\n"
        "- **Targeted Completion** — Upload to a known requirement, extract all fields\n"
        "- **Validation/Correction** — Extract specific fields, validate against expected values\n"
    ),
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request Logging Middleware
# ---------------------------------------------------------------------------


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all incoming requests with timing."""
    req_id = f"{datetime.now(timezone.utc).strftime('%H%M%S')}-{id(request) % 10000}"
    log.info("[%s] %s %s", req_id, request.method, request.url.path)
    start = datetime.now(timezone.utc)

    try:
        response = await call_next(request)
        duration = (datetime.now(timezone.utc) - start).total_seconds()

        if response.status_code >= 400:
            log.warning(
                "[%s] %s %s -> %d (%.3fs)",
                req_id,
                request.method,
                request.url.path,
                response.status_code,
                duration,
            )
        else:
            log.info(
                "[%s] %s %s -> %d (%.3fs)",
                req_id,
                request.method,
                request.url.path,
                response.status_code,
                duration,
            )

        return response
    except Exception as e:
        duration = (datetime.now(timezone.utc) - start).total_seconds()
        log.exception("[%s] Unhandled error (%.3fs): %s", req_id, duration, e)
        raise


# ---------------------------------------------------------------------------
# Global Exception Handler
# ---------------------------------------------------------------------------


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    """Convert ValueError to 400 Bad Request."""
    return JSONResponse(
        status_code=400,
        content={"detail": str(exc)},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """Catch-all handler for any unhandled exceptions."""
    log.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error: {type(exc).__name__}: {str(exc)}"},
    )


@app.exception_handler(RuntimeError)
async def runtime_error_handler(request: Request, exc: RuntimeError):
    """Convert RuntimeError to 500 Internal Server Error."""
    log.exception("RuntimeError: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
    )


# =============================================================================
# Health & Discovery Endpoints
# =============================================================================


@app.get("/health", response_model=HealthResponse, tags=["Health"])
def health():
    """Health check endpoint."""
    categories = get_supported_categories()
    total_doc_types = sum(len(doc_types) for doc_types in CATEGORY_DOCUMENT_TYPES.values())

    return HealthResponse(
        status="ok",
        version=APP_VERSION,
        supported_categories=categories,
        total_document_types=total_doc_types,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.get(
    "/api/v1/schemas/categories",
    response_model=List[CategoryInfo],
    tags=["Schema Discovery"],
    summary="List all supported categories and their document types",
)
def list_categories():
    """
    Get all supported top-level categories with their document types.

    Useful for building UI dropdowns and understanding the classification taxonomy.
    """
    result = []
    for cat_value in get_supported_categories():
        try:
            doc_types = get_document_types_for_category_api(cat_value)
            result.append(
                CategoryInfo(
                    name=cat_value,
                    document_types=doc_types,
                    document_count=len(doc_types),
                )
            )
        except ValueError:
            continue

    return result


@app.get(
    "/api/v1/schemas/categories/{category}",
    response_model=CategoryInfo,
    tags=["Schema Discovery"],
    summary="Get document types for a specific category",
)
def get_category(category: str):
    """
    Get document types for a specific top-level category.

    Path parameter `category` should be URL-encoded if it contains spaces.
    Example: `/api/v1/schemas/categories/Company%20Information`
    """
    try:
        doc_types = get_document_types_for_category_api(category)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return CategoryInfo(
        name=category,
        document_types=doc_types,
        document_count=len(doc_types),
    )


@app.get(
    "/api/v1/schemas/document-types/{document_type:path}",
    response_model=DocumentTypeInfo,
    tags=["Schema Discovery"],
    summary="Get field schema for a specific document type",
)
def get_document_type_schema(document_type: str):
    """
    Get the full extraction schema (fields) for a specific document type.

    Returns all available fields with their types and descriptions.
    This is useful for:
    - Knowing what `target_fields` to pass to the validation endpoint
    - Understanding what data will be extracted for a document type

    This endpoint accepts document type names containing `/`.
    Example: `/api/v1/schemas/document-types/Economical%20Offer%20/%20BOQ`
    """
    try:
        fields = get_fields_for_document_type(document_type)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    top_level = _get_top_level_for_document_type(document_type)
    top_level_str = top_level.value if top_level else "unknown"

    return DocumentTypeInfo(
        name=document_type,
        top_level_category=top_level_str,
        fields=fields,
        field_count=len(fields),
    )


@app.get(
    "/api/v1/schemas/document-types",
    response_model=Dict[str, Any],
    tags=["Schema Discovery"],
    summary="Get all document types and their schemas",
)
def list_all_document_types():
    """
    Get all document types grouped by category with their field schemas.
    """
    return get_all_schemas_info()


# =============================================================================
# Type 1: Bulk Ingestion Endpoint
# =============================================================================


@app.post(
    "/api/v1/extract/bulk",
    response_model=BulkIngestionResponse,
    tags=["Extraction"],
    summary="Type 1 — Bulk Ingestion (unknown requirement, unknown value)",
    description=(
        "Upload documents without selecting a requirement. AI will:\n\n"
        "1. **Classify** each document into its respective requirement/document type\n"
        "2. **Extract** all possible variables within those requirements\n"
        "3. **Validate** and resolve conflicts when multiple docs classify as same type\n\n"
        "This is the primary path for initial data room population."
    ),
)
async def endpoint_bulk_ingest(req: BulkIngestionRequest):
    """
    Bulk ingestion — classify and extract everything from uploaded documents.

    **When to use:** First-time project setup, initial data room population.

    **AI Responsibility:**
    - Classify documents into their respective requirements
    - Extract all possible variables within those requirements
    - Resolve conflicts when multiple docs have same classification
    """
    try:
        log.info(
            "Bulk ingestion: %d files, project=%s, category=%s",
            len(req.s3_paths),
            req.project_id,
            req.top_level_category or "ALL",
        )
        result = await bulk_ingest(req)
        log.info(
            "Bulk ingestion complete: %d/%d successful",
            result.successful,
            result.total_documents,
        )
        return result

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        log.exception("Bulk ingestion failed")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        log.exception("Unexpected error in bulk ingestion")
        raise HTTPException(status_code=500, detail=f"Internal error: {type(e).__name__}: {str(e)}")


# =============================================================================
# Type 2: Targeted Completion Endpoint
# =============================================================================


@app.post(
    "/api/v1/extract/targeted",
    response_model=TargetedCompletionResponse,
    tags=["Extraction"],
    summary="Type 2 — Targeted Completion (known requirement, unknown value)",
    description=(
        "Upload documents for a specific, known requirement. AI will:\n\n"
        "1. **Skip** requirement classification (intent is pre-defined)\n"
        "2. **Extract** all variables associated with that specific requirement template\n"
        "3. **Always validate** and produce a consolidated validation result\n"
        "4. Accept `document_type` in canonical, snake_case, kebab-case, or case-insensitive form\n\n"
        "Higher precision path for fulfilling known data gaps."
    ),
)
async def endpoint_targeted_completion(req: TargetedCompletionRequest):
    """
    Targeted completion — extract all fields for a known document type.

    **When to use:** User uploads documents inside a specific requirement
    sidebar or bucket. The requirement is already known.

    **AI Responsibility:**
    - Skip requirement classification
    - Extract all variables associated with the requirement template
    """
    try:
        log.info(
            "Targeted completion: %d files, doc_type='%s', project=%s",
            len(req.s3_paths),
            req.document_type,
            req.project_id,
        )
        result = await targeted_completion(req)
        log.info(
            "Targeted completion done: %d/%d successful for '%s'",
            result.successful,
            result.total_documents,
            req.document_type,
        )
        return result

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        log.exception("Targeted completion failed")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        log.exception("Unexpected error in targeted completion")
        raise HTTPException(status_code=500, detail=f"Internal error: {type(e).__name__}: {str(e)}")


# =============================================================================
# Type 3: Validation / Correction Endpoint
# =============================================================================


@app.post(
    "/api/v1/extract/validate",
    response_model=ValidationCorrectionResponse,
    tags=["Extraction"],
    summary="Type 3 — Validation / Correction (known requirement, known value)",
    description=(
        "Upload document(s) to extract and validate specific fields. AI will:\n\n"
        "1. **Skip** requirement classification\n"
        "2. **Extract** only the specific variable(s) requested\n"
        "3. **Validate** against expected values if provided\n"
        "4. Return precise confidence and evidence for each field\n"
        "5. Accept `document_type` in canonical, snake_case, kebab-case, or case-insensitive form\n\n"
        "Precision correction path — user leads, AI provides supporting evidence."
    ),
)
async def endpoint_validation_correction(req: ValidationCorrectionRequest):
    """
    Validation/correction — extract and validate specific fields.

    **When to use:** User uploads a document from a specific variable
    context/editor. Human-in-the-loop correction or verification.

    **AI Responsibility:**
    - Skip requirement classification
    - Extract only the specific variable(s) requested
    - Validate against user-entered expected values
    - Return confidence and evidence locations
    """
    try:
        log.info(
            "Validation: %d files, doc_type='%s', fields=%s, project=%s",
            len(req.s3_paths),
            req.document_type,
            req.target_fields,
            req.project_id,
        )
        result = await validation_correction(req)

        status_msg = (
            f"status={result.overall_validation_status}"
            if result.overall_validation_status
            else "no validation"
        )
        log.info(
            "Validation done: %d fields extracted, %s",
            len(result.extracted_fields),
            status_msg,
        )
        return result

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        log.exception("Validation failed")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        log.exception("Unexpected error in validation")
        raise HTTPException(status_code=500, detail=f"Internal error: {type(e).__name__}: {str(e)}")


# =============================================================================
# Summary Generation Endpoint
# =============================================================================


@app.post(
    "/api/v1/summary/generate",
    response_model=SummaryGenerationResponse,
    tags=["Summary"],
    summary="Generate structured investment summary from NestJS payload",
    description=(
        "Receives a sectioned, mapped variable payload from NestJS and returns "
        "a structured summary JSON for template rendering."
    ),
)
async def endpoint_generate_summary(req: SummaryGenerationRequest):
    """
    Summary generation for Data Room investment overview.

    **When to use:** NestJS has already mapped canonical project variables and
    needs AI-generated narrative blocks in a structured response.

    **AI Responsibility:**
    - Generate section narratives from provided variables
    - Preserve source values without fabricating new numeric facts
    - Return structured JSON for HTML renderer mapping
    """
    try:
        log.info(
            "Summary generate: project=%s, sections=%d, template=%s",
            req.project_id,
            len(req.sections),
            req.template_name,
        )
        result = await generate_structured_summary(req)
        log.info(
            "Summary generated: project=%s, mode=%s, sections=%d",
            req.project_id,
            result.generation_mode,
            len(result.sections),
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        log.exception("Summary generation failed")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        log.exception("Unexpected error in summary generation")
        raise HTTPException(status_code=500, detail=f"Internal error: {type(e).__name__}: {str(e)}")


# =============================================================================
# Local Dev Runner
# =============================================================================

if __name__ == "__main__":
    import uvicorn

    log.info("Starting DDX API v%s", APP_VERSION)
    uvicorn.run(
        "ddx.api.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=bool(os.getenv("RELOAD", "")),
    )
