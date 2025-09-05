from __future__ import annotations

import os
import logging
import shutil
import uuid
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, field_validator

from ddx.config.fields import (
    load_field_config,
    build_registry_from_field_config,
    index_registry,
)
from ddx.orchestrator import run_for_fields
from ddx.storage.json_store import save_json_outputs
from ddx.evaluator.brand_compliance import (
    evaluate_brand_compliance,
    evaluate_inverter_compliance,
)

# ---------------------------------------------------------------------------
# Settings / Environment
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FIELD_CONFIG = PROJECT_ROOT / "config" / "fields.json"
DEFAULT_STORE_DIR = PROJECT_ROOT / "store"

APP_VERSION = "0.1.0"


class Settings(BaseModel):
    field_config: Path = Path(os.getenv("FIELD_CONFIG", DEFAULT_FIELD_CONFIG))
    store_dir: Path = Path(os.getenv("STORE_DIR", DEFAULT_STORE_DIR))
    default_provider: str = os.getenv("DEFAULT_PROVIDER", "openai")
    default_model: str = os.getenv("DEFAULT_MODEL", "gpt-4o-mini")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    s3_bucket: str = os.getenv("S3_BUCKET", "")  # Default bucket name if not provided in request


settings = Settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("ddx.api")

# ---------------------------------------------------------------------------
# Registry Cache
# ---------------------------------------------------------------------------

_REGISTRY_IDX: Optional[Dict[str, Dict[str, Any]]] = None
_REGISTRY_FIELD_COUNT: int = 0


def ensure_registry_loaded() -> Dict[str, Dict[str, Any]]:
    global _REGISTRY_IDX, _REGISTRY_FIELD_COUNT
    if _REGISTRY_IDX is not None:
        return _REGISTRY_IDX
    cfg_path = settings.field_config
    if not cfg_path.exists():
        raise RuntimeError(f"Field config not found at {cfg_path}")
    log.info("Loading field config: %s", cfg_path)
    field_cfg = load_field_config(cfg_path)
    registry = build_registry_from_field_config(field_cfg)
    _REGISTRY_IDX = index_registry(registry)
    _REGISTRY_FIELD_COUNT = len(_REGISTRY_IDX)
    log.info("Registry loaded with %d fields", _REGISTRY_FIELD_COUNT)
    return _REGISTRY_IDX


def get_registry_idx():
    return ensure_registry_loaded()


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


class ParseFieldsRequest(BaseModel):
    fields: List[str] = Field(..., description="Field keys to extract")
    file_paths: List[str] = Field(..., description="List of S3 file paths")
    bucket: Optional[str] = Field(None, description="S3 bucket name (overrides env default)")
    provider: Optional[str] = None
    model: Optional[str] = None
    ocr: bool = False
    ocr_lang: str = "spa+eng"
    ocr_dpi: int = 300
    project_id: str = "default_project"
    run_id: Optional[str] = None

    @field_validator("fields")
    @classmethod
    def _non_empty_fields(cls, v):
        if not v:
            raise ValueError("fields list must not be empty")
        return v

    @field_validator("file_paths")
    @classmethod
    def _non_empty_paths(cls, v):
        if not v:
            raise ValueError("file_paths must not be empty")
        return v


class BrandRequest(BaseModel):
    brand: str = Field(..., min_length=1, max_length=128)


class HealthResponse(BaseModel):
    status: str
    registry_loaded: bool
    registry_fields: int
    version: str
    timestamp: str


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Due Diligence Extraction API",
    version=APP_VERSION,
    description="API exposing field extraction and brand compliance checks.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    req_id = f"{datetime.now().isoformat()}-{id(request)}"
    log.debug("REQ %s %s %s", req_id, request.method, request.url.path)
    try:
        response = await call_next(request)
        log.debug("RES %s %s %s", req_id, response.status_code, request.url.path)
        return response
    except Exception as e:
        log.exception("Unhandled error for req %s: %s", req_id, e)
        raise


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_fields(requested: List[str], registry_idx: Dict[str, Any]):
    print(registry_idx)
    unknown = [f for f in requested if f not in registry_idx]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown field keys: {unknown}",
        )


def download_s3_files(file_paths: List[str], bucket: Optional[str]) -> Path:
    """Download files from S3 to a temporary directory."""
    try:
        import boto3
    except ImportError:
        raise HTTPException(status_code=500, detail="boto3 not installed")

    # Use provided bucket or fall back to env setting
    bucket_name = bucket or settings.s3_bucket
    if not bucket_name:
        raise HTTPException(status_code=400, detail="No S3 bucket specified")

    s3 = boto3.client("s3")

    # Create temporary directory
    temp_dir = settings.store_dir / "_temp" / str(uuid.uuid4())
    temp_dir.mkdir(parents=True, exist_ok=True)

    for file_path in file_paths:
        # Clean the path (remove leading slash if present)
        clean_path = file_path.lstrip("/")
        filename = Path(clean_path).name
        local_path = temp_dir / filename

        try:
            s3.download_file(bucket_name, clean_path, str(local_path))
            log.debug(f"Downloaded s3://{bucket_name}/{clean_path} to {local_path}")
        except Exception as e:
            # Clean up on failure
            print(e)
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise HTTPException(
                status_code=500, detail=f"Failed to download {clean_path}: {str(e)}"
            )

    return temp_dir


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
def health():
    loaded = _REGISTRY_IDX is not None
    return HealthResponse(
        status="ok",
        registry_loaded=loaded,
        registry_fields=_REGISTRY_FIELD_COUNT if loaded else 0,
        version=APP_VERSION,
        timestamp=datetime.utcnow().isoformat(),
    )


@app.post("/parse-fields")
async def parse_fields(req: ParseFieldsRequest, registry_idx=Depends(get_registry_idx)):
    temp_dir = None

    try:
        # Download files to temporary directory
        temp_dir = download_s3_files(req.file_paths, req.bucket)

        # Validate requested fields
        _validate_fields(req.fields, registry_idx)

        provider = req.provider or settings.default_provider
        model = req.model or settings.default_model

        # Run extraction
        extraction = await run_in_threadpool(
            run_for_fields,
            registry_idx,
            req.fields,
            temp_dir,
            provider,
            model,
            False,
            ocr=req.ocr,
            ocr_lang=req.ocr_lang,
            ocr_dpi=req.ocr_dpi,
        )
        return extraction

    except HTTPException:
        raise
    except Exception as e:
        log.exception("Extraction failed")
        raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")
    finally:
        # Always clean up temporary files
        if temp_dir and temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
            log.debug(f"Cleaned up temporary directory: {temp_dir}")


@app.post("/compliance/pv")
async def pv_compliance(req: BrandRequest):
    try:
        result = await run_in_threadpool(evaluate_brand_compliance, req.brand)
    except Exception as e:
        log.exception("PV compliance evaluation failed")
        raise HTTPException(status_code=500, detail=f"PV compliance failed: {e}")
    return result


@app.post("/compliance/inverter")
async def inverter_compliance(req: BrandRequest):
    try:
        result = await run_in_threadpool(evaluate_inverter_compliance, req.brand)
    except Exception as e:
        log.exception("Inverter compliance evaluation failed")
        raise HTTPException(status_code=500, detail=f"Inverter compliance failed: {e}")
    return result


# ---------------------------------------------------------------------------
# Local Dev Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    log.info("Starting API (version %s)", APP_VERSION)
    uvicorn.run(
        "ddx.api.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=bool(os.getenv("RELOAD", "1") == "1"),
    )
