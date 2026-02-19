"""
Service layer for DDX API endpoints.

Orchestrates S3 downloads, calls extraction_api functions,
and transforms results into API response models.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from ddx.classification.extraction_api import (
    # Core async functions
    process_documents_by_category_async,
    extract_specific_fields_async,
    extract_specific_fields_batch_async,
    extract_documents_direct_batch_async,
    # Validation
    validate_batch_results,
    # Helpers
    get_supported_categories,
    get_document_types_for_category_api,
    get_fields_for_document_type,
    get_all_schemas_info,
    parse_top_level_category,
    _get_top_level_for_document_type,
    # Models
    DocumentResult,
    BatchProcessingResult,
    FieldExtractionResult,
    ValidatedDocumentResult,
    # Constants & types
    CATEGORY_DOCUMENT_TYPES,
    PYDANTIC_MODELS,
)
from ddx.classification.categories import TopLevelCategory

from ddx.api.models import (
    BulkIngestionRequest,
    BulkIngestionResponse,
    BulkDocumentResult,
    TargetedCompletionRequest,
    TargetedCompletionResponse,
    TargetedDocumentResult,
    ValidationCorrectionRequest,
    ValidationCorrectionResponse,
    FieldValidationResult,
    DocumentProcessingError,
)

log = logging.getLogger("ddx.api.services")


def _truncate_for_log(value: Any, max_len: int = 3000) -> str:
    """Serialize and truncate large payloads for logs."""
    try:
        serialized = json.dumps(value, default=str)
    except Exception:
        serialized = str(value)

    if len(serialized) <= max_len:
        return serialized

    return f"{serialized[:max_len]}...(truncated)"


def _slug_document_type(value: str) -> str:
    """Normalize document type strings for tolerant matching."""
    normalized = re.sub(r"[^a-z0-9]+", "_", (value or "").strip().lower())
    return re.sub(r"_+", "_", normalized).strip("_")


def _normalize_document_type(document_type: str) -> str:
    """Resolve user-provided document type to canonical PYDANTIC_MODELS key."""
    if document_type in PYDANTIC_MODELS:
        return document_type

    aliases = {_slug_document_type(canonical): canonical for canonical in PYDANTIC_MODELS.keys()}
    normalized = aliases.get(_slug_document_type(document_type))
    if normalized:
        return normalized

    raise ValueError(
        f"Unknown document type: '{document_type}'. "
        f"Valid types: {sorted(PYDANTIC_MODELS.keys())}"
    )


# =============================================================================
# S3 Download Utilities
# =============================================================================


async def _download_single_file(s3_client, bucket: str, s3_path: str, temp_dir: Path) -> Path:
    """Download a single file from S3, handling duplicate filenames."""
    clean_path = s3_path.lstrip("/")
    local_path = temp_dir / Path(clean_path).name
    local_path = _deduplicate_path(local_path)

    await s3_client.download_file(bucket, clean_path, str(local_path))
    log.info("  Downloaded: %s -> %s", clean_path, local_path.name)
    return local_path


def _deduplicate_path(local_path: Path) -> Path:
    """Add numeric suffix if file already exists."""
    if not local_path.exists():
        return local_path

    stem = local_path.stem
    suffix = local_path.suffix
    counter = 1
    while local_path.exists():
        local_path = local_path.parent / f"{stem}_{counter}{suffix}"
        counter += 1
    return local_path


async def download_s3_files(
    s3_paths: List[str],
    bucket: Optional[str] = None,
) -> Tuple[Path, Dict[str, Path]]:
    """
    Download files from S3 to a temporary directory.

    Returns:
        Tuple of (temp_dir_path, mapping of s3_path -> local_path)
    """
    try:
        import aioboto3
        from botocore.config import Config
    except ImportError:
        raise RuntimeError(
            "aioboto3 is required for S3 downloads. Install with: pip install aioboto3"
        )

    bucket_name = bucket or os.getenv("S3_BUCKET", "drex-network")
    if not bucket_name:
        raise RuntimeError("No S3 bucket specified. Set S3_BUCKET env var or pass bucket param.")

    region = os.getenv("AWS_REGION", "us-east-1")
    temp_dir = Path(tempfile.mkdtemp(prefix="ddx_api_"))
    path_mapping: Dict[str, Path] = {}

    log.info("Downloading %d files from s3://%s to %s", len(s3_paths), bucket_name, temp_dir)

    session = aioboto3.Session()
    cfg = Config(max_pool_connections=int(os.getenv("S3_MAX_POOL", "50")))

    async with session.client("s3", region_name=region, config=cfg) as s3:
        tasks = [
            _download_and_track(s3, bucket_name, s3_path, temp_dir, path_mapping)
            for s3_path in s3_paths
        ]
        await asyncio.gather(*tasks)

    return temp_dir, path_mapping


async def _download_and_track(
    s3_client, bucket: str, s3_path: str, temp_dir: Path, path_mapping: Dict[str, Path]
) -> None:
    """Download one file and record it in path_mapping."""
    try:
        local_path = await _download_single_file(s3_client, bucket, s3_path, temp_dir)
        path_mapping[s3_path] = local_path
    except Exception as e:
        log.error("Failed to download %s: %s", s3_path, e)
        raise RuntimeError(f"Failed to download s3://{bucket}/{s3_path.lstrip('/')}: {e}")


def cleanup_temp_dir(temp_dir: Path) -> None:
    """Safely remove a temporary directory."""
    try:
        if temp_dir and temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
            log.info("Cleaned up temp dir: %s", temp_dir)
    except Exception as e:
        log.warning("Failed to clean up %s: %s", temp_dir, e)


# =============================================================================
# Shared Helpers: File Resolution & Error Building
# =============================================================================


class ResolvedFiles:
    """Resolved local file paths from S3 download mapping."""

    def __init__(self, s3_paths: List[str], path_mapping: Dict[str, Path]):
        self.file_paths: List[Path] = []
        self.file_names: List[str] = []
        self.s3_lookup: Dict[str, str] = {}  # local filename -> s3 path

        for s3_path in s3_paths:
            local_path = path_mapping.get(s3_path)
            if local_path and local_path.exists():
                self.file_paths.append(local_path)
                self.file_names.append(local_path.name)
                self.s3_lookup[local_path.name] = s3_path

    @property
    def is_empty(self) -> bool:
        return len(self.file_paths) == 0


def _build_download_errors(s3_paths: List[str]) -> List[DocumentProcessingError]:
    """Build error list when all S3 downloads failed."""
    return [
        DocumentProcessingError(
            file_name=p,
            error_type="DownloadError",
            error_message="Failed to download file from S3",
        )
        for p in s3_paths
    ]


def _build_extraction_errors(results: list) -> List[DocumentProcessingError]:
    """Extract errors from a list of result objects with .success and .error attrs."""
    return [
        DocumentProcessingError(
            file_name=r.file_name,
            error_type="ExtractionError",
            error_message=r.error or "Unknown error",
        )
        for r in results
        if not r.success
    ]


# =============================================================================
# Type 1: Bulk Ingestion Service
# =============================================================================


async def _process_with_category(
    file_paths: List[Path],
    top_level: TopLevelCategory,
    req: BulkIngestionRequest,
) -> BatchProcessingResult:
    """Run batch processing with a specific top-level category."""
    return await process_documents_by_category_async(
        files=file_paths,
        top_level_category=top_level,
        parse_model=req.config.parse_model,
        extract_model=req.config.extract_model,
        max_concurrent=req.max_concurrent,
        rate_limit=req.config.rate_limit,
        enable_validation=req.enable_validation,
        validation_model=req.validation_model,
        markdown_cache=True,
        markdown_cache_bucket=req.bucket,
    )


async def _process_all_categories(
    file_paths: List[Path],
    req: BulkIngestionRequest,
    path_mapping: Dict[str, Path],
) -> Tuple[List[BulkDocumentResult], Optional[Dict[str, Any]]]:
    """
    Process files across ALL categories when no hint is provided.
    Returns (processed_documents, validated_results).
    """
    all_results: List[DocumentResult] = []
    all_validated: Dict[str, ValidatedDocumentResult] = {}

    for category in TopLevelCategory:
        batch = await _try_process_category(file_paths, category, req)
        if batch is None:
            continue
        _collect_non_uncategorized(batch, all_results, all_validated)

    best_per_file = _deduplicate_results(all_results)
    _fill_missing_files(best_per_file, req.s3_paths, path_mapping)

    resolved = ResolvedFiles(req.s3_paths, path_mapping)
    processed = _convert_document_results(list(best_per_file.values()), resolved.s3_lookup)
    validated = _serialize_validated_results(all_validated)

    return processed, validated


async def _try_process_category(
    file_paths: List[Path],
    category: TopLevelCategory,
    req: BulkIngestionRequest,
) -> Optional[BatchProcessingResult]:
    """Try processing files for a category; return None on failure."""
    try:
        return await _process_with_category(file_paths, category, req)
    except Exception as e:
        log.warning("Failed processing category %s: %s", category.value, e)
        return None


def _collect_non_uncategorized(
    batch: BatchProcessingResult,
    all_results: List[DocumentResult],
    all_validated: Dict[str, ValidatedDocumentResult],
) -> None:
    """Collect successful, non-uncategorized results from a batch."""
    for r in batch.results:
        if r.success and r.document_type != "Uncategorized Document":
            all_results.append(r)

    if not batch.validated_results:
        return

    for dt, vr in batch.validated_results.items():
        if dt != "Uncategorized Document":
            all_validated[dt] = vr


def _deduplicate_results(results: List[DocumentResult]) -> Dict[str, DocumentResult]:
    """Keep best result per file — prefer non-uncategorized."""
    best: Dict[str, DocumentResult] = {}
    for r in results:
        existing = best.get(r.file_name)
        if existing is None or r.document_type != "Uncategorized Document":
            best[r.file_name] = r
    return best


def _fill_missing_files(
    best: Dict[str, DocumentResult],
    s3_paths: List[str],
    path_mapping: Dict[str, Path],
) -> None:
    """Add placeholder results for files that got no classification."""
    for s3_path in s3_paths:
        local_path = path_mapping.get(s3_path)
        if not local_path or local_path.name in best:
            continue
        best[local_path.name] = DocumentResult(
            file_name=local_path.name,
            file_path=str(local_path),
            document_type="Uncategorized Document",
            top_level_category="unknown",
            extracted_data={},
            success=True,
        )


async def bulk_ingest(req: BulkIngestionRequest) -> BulkIngestionResponse:
    """
    Type 1 — Unknown requirement, unknown value.

    Downloads files from S3, classifies each document, extracts all fields,
    and optionally validates conflicts across documents of the same type.
    """
    temp_dir = None
    try:
        temp_dir, path_mapping = await download_s3_files(req.s3_paths, req.bucket)
        resolved = ResolvedFiles(req.s3_paths, path_mapping)

        if resolved.is_empty:
            return _build_empty_bulk_response(req)

        if req.top_level_category:
            processed, validated = await _bulk_ingest_with_category(resolved, req)
        else:
            processed, validated = await _process_all_categories(
                resolved.file_paths, req, path_mapping
            )

        return _assemble_bulk_response(req, processed, validated)

    finally:
        if temp_dir:
            cleanup_temp_dir(temp_dir)


async def _bulk_ingest_with_category(
    resolved: ResolvedFiles,
    req: BulkIngestionRequest,
) -> Tuple[List[BulkDocumentResult], Optional[Dict[str, Any]]]:
    """Bulk ingest with a user-provided category hint."""
    top_level = parse_top_level_category(req.top_level_category)
    batch_result = await _process_with_category(resolved.file_paths, top_level, req)

    processed = _convert_document_results(batch_result.results, resolved.s3_lookup)
    validated = _serialize_validated_results(batch_result.validated_results)
    return processed, validated


def _build_empty_bulk_response(req: BulkIngestionRequest) -> BulkIngestionResponse:
    """Response when no files could be downloaded."""
    return BulkIngestionResponse(
        project_id=req.project_id,
        total_documents=len(req.s3_paths),
        successful=0,
        failed=len(req.s3_paths),
        processed_documents=[],
        errors=_build_download_errors(req.s3_paths),
    )


def _assemble_bulk_response(
    req: BulkIngestionRequest,
    processed: List[BulkDocumentResult],
    validated: Optional[Dict[str, Any]],
) -> BulkIngestionResponse:
    """Assemble final bulk response from processed results."""
    successful = sum(1 for d in processed if d.success)
    classification_summary = dict(Counter(d.document_type for d in processed))
    errors = [
        DocumentProcessingError(
            file_name=d.file_name,
            error_type="ExtractionError",
            error_message=d.error or "Unknown error",
        )
        for d in processed
        if not d.success
    ]

    extracted_variables = {
        d.file_name: d.extracted_data for d in processed if d.success and d.extracted_data
    }
    if extracted_variables:
        log.info(
            "Bulk extracted variables for project=%s: %s",
            req.project_id,
            _truncate_for_log(extracted_variables),
        )

    return BulkIngestionResponse(
        project_id=req.project_id,
        total_documents=len(req.s3_paths),
        successful=successful,
        failed=len(req.s3_paths) - successful,
        processed_documents=processed,
        validated_results=validated,
        classification_summary=classification_summary,
        errors=errors,
    )


# =============================================================================
# Type 2: Targeted Completion Service
# =============================================================================


def _resolve_document_type(document_type: str) -> Tuple[str, str]:
    """Validate document type and return (doc_type, top_level_category_str)."""
    canonical_document_type = _normalize_document_type(document_type)
    top_level = _get_top_level_for_document_type(canonical_document_type)
    return canonical_document_type, top_level.value if top_level else "unknown"


async def targeted_completion(req: TargetedCompletionRequest) -> TargetedCompletionResponse:
    """
    Type 2 — Known requirement, unknown value.

    Downloads files from S3, skips classification, and extracts ALL variables
    for the given document type.
    """
    doc_type, top_level_str = _resolve_document_type(req.document_type)

    temp_dir = None
    try:
        temp_dir, path_mapping = await download_s3_files(req.s3_paths, req.bucket)
        resolved = ResolvedFiles(req.s3_paths, path_mapping)

        if resolved.is_empty:
            return _build_empty_targeted_response(req, top_level_str, doc_type)

        if not req.enable_validation:
            log.info(
                "Targeted completion received enable_validation=False; enforcing validation for Type 2"
            )

        results_list, validated_result = await extract_documents_direct_batch_async(
            files=resolved.file_paths,
            document_type=doc_type,
            file_names=resolved.file_names,
            parse_model=req.config.parse_model,
            extract_model=req.config.extract_model,
            max_concurrent=req.max_concurrent,
            rate_limit=req.config.rate_limit,
            enable_validation=True,
            validation_model=req.validation_model,
        )

        return _assemble_targeted_response(
            req, top_level_str, doc_type, results_list, validated_result, resolved
        )

    finally:
        if temp_dir:
            cleanup_temp_dir(temp_dir)


def _build_empty_targeted_response(
    req: TargetedCompletionRequest, top_level_str: str, document_type: str
) -> TargetedCompletionResponse:
    return TargetedCompletionResponse(
        document_type=document_type,
        top_level_category=top_level_str,
        project_id=req.project_id,
        total_documents=len(req.s3_paths),
        successful=0,
        failed=len(req.s3_paths),
        individual_results=[],
        errors=_build_download_errors(req.s3_paths),
    )


def _assemble_targeted_response(
    req: TargetedCompletionRequest,
    top_level_str: str,
    document_type: str,
    results_list: list,
    validated_result: Any,
    resolved: ResolvedFiles,
) -> TargetedCompletionResponse:
    """Convert extraction results into targeted response."""
    individual = [
        TargetedDocumentResult(
            file_name=r.file_name,
            s3_path=resolved.s3_lookup.get(r.file_name),
            document_type=r.document_type,
            top_level_category=r.top_level_category,
            extracted_data=r.extracted_data,
            extraction_metadata=r.extraction_metadata,
            field_grounding=r.field_grounding,
            success=r.success,
            error=r.error,
        )
        for r in results_list
    ]

    consolidated = _serialize_targeted_validated_result(validated_result)

    extracted_variables = {
        r.file_name: r.extracted_data for r in individual if r.success and r.extracted_data
    }
    if extracted_variables:
        log.info(
            "Targeted extracted variables for project=%s doc_type='%s': %s",
            req.project_id,
            req.document_type,
            _truncate_for_log(extracted_variables),
        )

    successful = sum(1 for r in results_list if r.success)

    return TargetedCompletionResponse(
        document_type=document_type,
        top_level_category=top_level_str,
        project_id=req.project_id,
        total_documents=len(req.s3_paths),
        successful=successful,
        failed=len(req.s3_paths) - successful,
        individual_results=individual,
        consolidated_result=consolidated,
        errors=_build_extraction_errors(results_list),
    )


def _serialize_targeted_validated_result(validated_result: Any) -> Optional[Dict[str, Any]]:
    """Serialize targeted consolidated validation result for JSON response."""
    if not validated_result:
        return None

    if isinstance(validated_result, dict):
        return validated_result
    if hasattr(validated_result, "model_dump"):
        return validated_result.model_dump()
    if hasattr(validated_result, "dict"):
        return validated_result.dict()

    return {"value": str(validated_result)}


# =============================================================================
# Type 3: Validation / Correction Service
# =============================================================================


def _validate_target_fields(document_type: str, target_fields: List[str]) -> None:
    """Validate that all target fields exist in the document type schema."""
    schema_cls = PYDANTIC_MODELS[document_type]
    valid_fields = set(schema_cls.model_fields.keys())
    invalid_fields = set(target_fields) - valid_fields
    if invalid_fields:
        raise ValueError(
            f"Invalid fields for '{document_type}': {sorted(invalid_fields)}. "
            f"Valid fields: {sorted(valid_fields)}"
        )


async def _extract_targeted_fields(
    resolved: ResolvedFiles,
    req: ValidationCorrectionRequest,
    document_type: str,
) -> list:
    """Run field extraction for single or multiple files."""
    if len(resolved.file_paths) == 1:
        result = await extract_specific_fields_async(
            file=resolved.file_paths[0],
            document_type=document_type,
            fields=req.target_fields,
            file_name=resolved.file_names[0],
            parse_model=req.config.parse_model,
            extract_model=req.config.extract_model,
            rate_limit=req.config.rate_limit,
        )
        return [result]

    return await extract_specific_fields_batch_async(
        files=resolved.file_paths,
        document_type=document_type,
        fields=req.target_fields,
        file_names=resolved.file_names,
        parse_model=req.config.parse_model,
        extract_model=req.config.extract_model,
        max_concurrent=len(resolved.file_paths),
        rate_limit=req.config.rate_limit,
    )


def _build_file_level_results(
    field_results: list,
    s3_lookup: Dict[str, str],
) -> Tuple[List[Dict[str, Any]], List[DocumentProcessingError]]:
    """Build per-file detail dicts and collect errors."""
    details: List[Dict[str, Any]] = []
    errors: List[DocumentProcessingError] = []

    for fr in field_results:
        detail: Dict[str, Any] = {
            "file_name": fr.file_name,
            "s3_path": s3_lookup.get(fr.file_name),
            "success": fr.success,
            "extracted_fields": fr.extracted_fields,
        }
        if fr.error:
            detail["error"] = fr.error
            errors.append(
                DocumentProcessingError(
                    file_name=fr.file_name,
                    error_type="ExtractionError",
                    error_message=fr.error,
                )
            )
        details.append(detail)

        if fr.success and fr.extracted_fields:
            log.info(
                "Validation extracted variables for file=%s: %s",
                fr.file_name,
                _truncate_for_log(fr.extracted_fields),
            )

    return details, errors


def _find_best_field_value(
    field_name: str, field_results: list
) -> Tuple[
    Any, Optional[str], Optional[float], Optional[str], List[Dict[str, Any]], List[Dict[str, Any]]
]:
    """
    Find the best value for a field across multiple file results.

    Returns: (value, source_file, confidence, extracted_text, evidence_list, grounding_list)
    """
    for fr in field_results:
        if not fr.success:
            continue

        value = fr.extracted_fields.get(field_name)
        if value is None:
            continue

        confidence, extracted_text, evidence = _extract_field_metadata(fr, field_name)
        grounding = _extract_field_grounding(fr, field_name)
        return value, fr.file_name, confidence, extracted_text, evidence, grounding

    return None, None, None, None, [], []


def _extract_field_grounding(fr: Any, field_name: str) -> List[Dict[str, Any]]:
    """Extract resolved grounding locations for a field from a FieldExtractionResult."""
    if not getattr(fr, "field_grounding", None) or not isinstance(fr.field_grounding, dict):
        return []
    locations = fr.field_grounding.get(field_name)
    if isinstance(locations, list):
        return locations
    return []


def _extract_field_metadata(
    fr: Any, field_name: str
) -> Tuple[Optional[float], Optional[str], List[Dict[str, Any]]]:
    """Extract confidence, text, and evidence from field metadata."""
    if not fr.extraction_metadata or not isinstance(fr.extraction_metadata, dict):
        return None, None, []

    field_meta = fr.extraction_metadata.get(field_name)
    if not isinstance(field_meta, dict):
        return None, None, []

    confidence = field_meta.get("confidence")
    extracted_text = field_meta.get("extracted_text")
    evidence = [
        ref if isinstance(ref, dict) else {"reference": ref}
        for ref in field_meta.get("references", [])
    ]
    return confidence, extracted_text, evidence


def _merge_field_results(
    target_fields: List[str],
    field_results: list,
    expected_values: Optional[Dict[str, Any]],
) -> Dict[str, FieldValidationResult]:
    """Merge field extraction results across files into FieldValidationResult dict."""
    extracted: Dict[str, FieldValidationResult] = {}

    for field_name in target_fields:
        value, source, confidence, text, evidence, grounding = _find_best_field_value(
            field_name, field_results
        )

        validation_status, expected_value = _validate_single_field(
            field_name, value, expected_values
        )

        extracted[field_name] = FieldValidationResult(
            field_name=field_name,
            value=value,
            confidence=confidence,
            evidence=evidence,
            grounding=grounding,
            extracted_text=text,
            validation_status=validation_status,
            expected_value=expected_value,
            source_file=source,
        )

    return extracted


def _validate_single_field(
    field_name: str,
    extracted_value: Any,
    expected_values: Optional[Dict[str, Any]],
) -> Tuple[Optional[str], Optional[Any]]:
    """Compute validation status for a single field."""
    if not expected_values or field_name not in expected_values:
        return None, None

    expected = expected_values[field_name]
    if extracted_value is None:
        return "uncertain", expected

    return _compare_values(extracted_value, expected), expected


async def validation_correction(
    req: ValidationCorrectionRequest,
) -> ValidationCorrectionResponse:
    """
    Type 3 — Known requirement, known value.

    Downloads file(s) from S3, extracts ONLY the targeted fields,
    and optionally validates against expected values.
    """
    doc_type, top_level_str = _resolve_document_type(req.document_type)
    _validate_target_fields(doc_type, req.target_fields)

    temp_dir = None
    try:
        temp_dir, path_mapping = await download_s3_files(req.s3_paths, req.bucket)
        resolved = ResolvedFiles(req.s3_paths, path_mapping)

        if resolved.is_empty:
            return _build_empty_validation_response(req, top_level_str, doc_type)

        field_results = await _extract_targeted_fields(resolved, req, doc_type)
        file_details, errors = _build_file_level_results(field_results, resolved.s3_lookup)
        extracted_fields = _merge_field_results(
            req.target_fields, field_results, req.expected_values
        )
        merged_values = {
            field_name: field_result.value for field_name, field_result in extracted_fields.items()
        }
        if merged_values:
            log.info(
                "Validation merged extracted variables for project=%s doc_type='%s': %s",
                req.project_id,
                req.document_type,
                _truncate_for_log(merged_values),
            )
        overall_status = _compute_overall_validation_status(extracted_fields, req.expected_values)

        return ValidationCorrectionResponse(
            document_type=doc_type,
            top_level_category=top_level_str,
            project_id=req.project_id,
            requested_fields=req.target_fields,
            extracted_fields=extracted_fields,
            overall_validation_status=overall_status,
            file_results=file_details,
            errors=errors,
        )

    finally:
        if temp_dir:
            cleanup_temp_dir(temp_dir)


def _build_empty_validation_response(
    req: ValidationCorrectionRequest, top_level_str: str, document_type: str
) -> ValidationCorrectionResponse:
    return ValidationCorrectionResponse(
        document_type=document_type,
        top_level_category=top_level_str,
        project_id=req.project_id,
        requested_fields=req.target_fields,
        extracted_fields={},
        errors=_build_download_errors(req.s3_paths),
    )


# =============================================================================
# Result Conversion Helpers
# =============================================================================


def _convert_document_results(
    results: List[DocumentResult],
    s3_path_lookup: Dict[str, str],
) -> List[BulkDocumentResult]:
    """Convert internal DocumentResult list to API BulkDocumentResult list."""
    return [
        BulkDocumentResult(
            file_name=r.file_name,
            s3_path=s3_path_lookup.get(r.file_name),
            document_type=r.document_type,
            top_level_category=r.top_level_category,
            extracted_data=r.extracted_data,
            extraction_metadata=r.extraction_metadata,
            field_grounding=r.field_grounding,
            success=r.success,
            error=r.error,
        )
        for r in results
    ]


def _serialize_validated_results(
    validated: Optional[Dict[str, ValidatedDocumentResult]],
) -> Optional[Dict[str, Any]]:
    """Serialize ValidatedDocumentResult dict for JSON response."""
    if not validated:
        return None

    serialized = {}
    for doc_type, vr in validated.items():
        if hasattr(vr, "model_dump"):
            serialized[doc_type] = vr.model_dump()
        elif hasattr(vr, "dict"):
            serialized[doc_type] = vr.dict()
        else:
            serialized[doc_type] = str(vr)
    return serialized


# =============================================================================
# Value Comparison Helpers
# =============================================================================


def _compare_values(extracted: Any, expected: Any) -> str:
    """
    Compare extracted value against expected value.

    Returns: 'match', 'mismatch', or 'uncertain'
    """
    if extracted is None:
        return "uncertain"

    ext_str = str(extracted).strip().lower()
    exp_str = str(expected).strip().lower()

    if ext_str == exp_str:
        return "match"

    numeric_result = _compare_numeric(ext_str, exp_str)
    if numeric_result is not None:
        return numeric_result

    if ext_str in exp_str or exp_str in ext_str:
        return "uncertain"

    return "mismatch"


def _compare_numeric(ext_str: str, exp_str: str) -> Optional[str]:
    """Attempt numeric comparison with 1% tolerance. Returns None if non-numeric."""
    try:
        ext_num = float(ext_str.replace(",", "").replace("%", ""))
        exp_num = float(exp_str.replace(",", "").replace("%", ""))
        if abs(ext_num - exp_num) / max(abs(exp_num), 1e-9) < 0.01:
            return "match"
        return "mismatch"
    except (ValueError, TypeError):
        return None


def _compute_overall_validation_status(
    extracted_fields: Dict[str, FieldValidationResult],
    expected_values: Optional[Dict[str, Any]],
) -> Optional[str]:
    """Compute overall validation status from individual field results."""
    if not expected_values:
        return None

    statuses = [
        f.validation_status for f in extracted_fields.values() if f.validation_status is not None
    ]

    if not statuses:
        return None
    if all(s == "match" for s in statuses):
        return "all_match"
    if all(s == "mismatch" for s in statuses):
        return "all_mismatch"
    return "some_mismatch"
