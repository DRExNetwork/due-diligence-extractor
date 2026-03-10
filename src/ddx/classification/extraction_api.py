"""
Extraction API - Three core functions for document processing pipeline.

1. process_documents_by_category() - Batch processing with top-level categories
2. extract_specific_fields() - Human-in-the-loop re-extraction for specific fields
3. extract_document_direct() - Direct extraction with known document type

All functions support async processing for multiple files using AsyncLandingAIADE.
Includes validation layer for resolving conflicts when multiple documents have
the same classification with conflicting field values.

NOTE: top_level_category is now REQUIRED for all batch processing operations.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type, Union

from pydantic import BaseModel, Field, create_model, ConfigDict

from ddx.classification.categories import (
    TopLevelCategory,
    DocumentType,
    ClassificationResult,
    PYDANTIC_MODELS,
    DOCUMENT_TYPE_DESCRIPTIONS,
    DOCUMENT_TYPE_TO_TOP_LEVEL,
    normalize_extracted_document,
)
from ddx.classification.landing_ai_poc_sdk import (
    # Schemas (for type hints)
    ProjectSimulationReportData,
    ProjectDataMainEquipmentSheetsData,
    ProjectBasicEngineeringData,
    ProjectVisitReportData,
    ProjectLayoutData,
    KmzPoligonData,
    CableSizingCalculationReportData,
    GroundingSystemSingleLineDiagramData,
    UncategorizedDocumentData,
    # Helpers
    _safe_stem,
    _sanitize_category_name,
    # Functions
    build_classification_schema_for_category,
    get_document_types_for_category,
    should_disable_cross_document_validation,
)
from dotenv import load_dotenv

load_dotenv()
# Import validation layer components
from ddx.classification.validation_layer import (
    ValidationLayer,
    FieldConflict,
    FieldCandidate,
    BoundingBox,
    EvidenceLocation,
    ValidationResult,
    ValidationReport,
    ValidatedFieldOutput,
    LocationInfo,
)


# =============================================================================
# Category to Document Types Mapping (built from categories.py)
# =============================================================================


def _build_category_document_types() -> Dict[TopLevelCategory, List[str]]:
    """Build mapping from TopLevelCategory to list of document type values."""
    mapping: Dict[TopLevelCategory, List[str]] = {cat: [] for cat in TopLevelCategory}

    for doc_type, top_level in DOCUMENT_TYPE_TO_TOP_LEVEL.items():
        if doc_type != DocumentType.UNCATEGORIZED:  # Exclude uncategorized
            mapping[top_level].append(doc_type.value)

    return mapping


CATEGORY_DOCUMENT_TYPES: Dict[TopLevelCategory, List[str]] = _build_category_document_types()


_EQUIPMENT_RESEARCH_ONLY_FIELDS = {
    "module_bloomberg",
    "module_certificate_evidence",
    "module_factory_test_date",
    "module_test_evidence",
    "inverter_bloomberg",
    "inverter_certificate_evidence",
    "inverter_anti_island_test_date",
    "inverter_test_evidence",
}


def _is_equipment_sheets_document_type(document_type: str) -> bool:
    return (
        document_type or ""
    ).strip().lower() == DocumentType.PROJECT_DATA_EQUIPMENT_SHEETS.value.strip().lower()


def _remove_schema_fields(schema: Any, field_names: set[str]) -> Any:
    """Remove fields from a JSON schema represented as dict or JSON string."""
    if isinstance(schema, str):
        try:
            parsed = json.loads(schema)
        except Exception:
            return schema

        filtered = _remove_schema_fields(parsed, field_names)

        try:
            return json.dumps(filtered)
        except Exception:
            return schema

    if not isinstance(schema, dict):
        return schema

    properties = schema.get("properties")
    if isinstance(properties, dict):
        for field_name in field_names:
            properties.pop(field_name, None)

    required = schema.get("required")
    if isinstance(required, list):
        schema["required"] = [name for name in required if name not in field_names]

    return schema


def _print_extracted_variables(context: str, extracted: Any, max_len: int = 3000) -> None:
    """Print extracted variables in a compact, bounded format."""
    try:
        payload = json.dumps(extracted, ensure_ascii=False, default=str)
    except Exception:
        payload = str(extracted)

    if len(payload) > max_len:
        payload = f"{payload[:max_len]}...(truncated)"

    print(f"  Extracted variables [{context}]: {payload}")


# =============================================================================
# Response Models
# =============================================================================


class DocumentResult(BaseModel):
    """Result for a single document processing."""

    model_config = ConfigDict(extra="forbid")

    file_name: str
    file_path: Optional[str] = None
    document_type: str
    top_level_category: str  # Added: top-level category
    extracted_data: Dict[str, Any]
    extraction_metadata: Optional[Dict[str, Any]] = None
    field_grounding: Optional[Dict[str, Any]] = None
    markdown_content: Optional[str] = None
    success: bool = True
    error: Optional[str] = None


class ValidatedDocumentResult(BaseModel):
    """Result for a document type after validation across multiple source files."""

    model_config = ConfigDict(extra="forbid")

    document_type: str
    top_level_category: str  # Changed from 'category' to 'top_level_category'
    source_files: List[str]
    validated_fields: Dict[str, ValidatedFieldOutput]
    validation_report: Optional[ValidationReport] = None
    overall_confidence: float = 1.0
    validation_summary: str = ""


class BatchProcessingResult(BaseModel):
    """Result for batch document processing."""

    model_config = ConfigDict(extra="forbid")

    top_level_category: str  # Changed from 'category' to 'top_level_category'
    total_documents: int
    successful: int
    failed: int
    results: List[DocumentResult]
    # Validated results grouped by document type (after conflict resolution)
    validated_results: Optional[Dict[str, ValidatedDocumentResult]] = None
    validation_performed: bool = False


class FieldExtractionResult(BaseModel):
    """Result for specific field extraction (human-in-the-loop)."""

    model_config = ConfigDict(extra="forbid")

    file_name: str
    document_type: str
    top_level_category: str  # Added: top-level category
    requested_fields: List[str]
    extracted_fields: Dict[str, Any]
    extraction_metadata: Optional[Dict[str, Any]] = None
    field_grounding: Optional[Dict[str, Any]] = None
    success: bool = True
    error: Optional[str] = None


# =============================================================================
# Grounding Resolver — maps extraction_metadata references → page locations
# =============================================================================


def _build_chunk_lookup(parse_response: Any) -> Dict[str, dict]:
    """
    Build a chunk_id → chunk dict lookup from the parse response.

    Handles both SDK response objects (with `.chunks` attr) and plain dicts.
    Returns an empty dict when chunks are unavailable (e.g. cache hits).
    """
    chunks = getattr(parse_response, "chunks", None)
    if chunks is None and isinstance(parse_response, dict):
        chunks = parse_response.get("chunks", [])
    lookup: Dict[str, dict] = {}

    if chunks:
        for chunk in chunks:
            chunk_dict = chunk if isinstance(chunk, dict) else _chunk_to_dict(chunk)
            cid = chunk_dict.get("chunk_id") or chunk_dict.get("id")
            if cid:
                lookup[cid] = chunk_dict

    # Parse responses also include a top-level grounding map where keys can be
    # table IDs / table-cell IDs (e.g., "0-b"). Include these keys so field
    # references pointing to table cells can resolve to real locations.
    grounding_map = getattr(parse_response, "grounding", None)
    if grounding_map is None and isinstance(parse_response, dict):
        grounding_map = parse_response.get("grounding", {})

    if grounding_map is not None and not isinstance(grounding_map, dict):
        if hasattr(grounding_map, "model_dump"):
            grounding_map = grounding_map.model_dump()
        elif hasattr(grounding_map, "dict"):
            grounding_map = grounding_map.dict()

    if isinstance(grounding_map, dict):
        for ref_id, grounding_entry in grounding_map.items():
            ref_key = str(ref_id)
            if ref_key in lookup:
                continue
            pseudo_chunk = _grounding_entry_to_chunk(ref_key, grounding_entry)
            if pseudo_chunk:
                lookup[ref_key] = pseudo_chunk

    return lookup


def _chunk_to_dict(chunk: Any) -> dict:
    """Convert an SDK chunk object to a plain dict."""
    if hasattr(chunk, "model_dump"):
        return chunk.model_dump()
    grounding = getattr(chunk, "grounding", None)
    if grounding is None:
        grounding = []
    elif isinstance(grounding, dict):
        grounding = [grounding]
    return {
        "chunk_id": getattr(chunk, "chunk_id", None),
        "id": getattr(chunk, "id", None),
        "grounding": grounding,
        "chunk_type": getattr(chunk, "chunk_type", None) or getattr(chunk, "type", None),
        "type": getattr(chunk, "type", None),
    }


def _grounding_entry_to_chunk(ref_id: str, grounding_entry: Any) -> Optional[dict]:
    """Convert a top-level parse grounding entry into a chunk-like lookup item."""
    if not isinstance(grounding_entry, dict):
        if hasattr(grounding_entry, "model_dump"):
            grounding_entry = grounding_entry.model_dump()
        elif hasattr(grounding_entry, "dict"):
            grounding_entry = grounding_entry.dict()

    if not isinstance(grounding_entry, dict):
        return None

    box = grounding_entry.get("box")
    page = grounding_entry.get("page", 0)
    chunk_type = grounding_entry.get("type") or grounding_entry.get("chunk_type")

    grounding_payload = {
        "page": page,
        "box": box if isinstance(box, dict) else {},
    }

    pseudo_chunk = {
        "chunk_id": ref_id,
        "id": ref_id,
        "grounding": [grounding_payload],
        "chunk_type": chunk_type,
        "type": chunk_type,
    }

    position = grounding_entry.get("position")
    if isinstance(position, dict):
        pseudo_chunk["position"] = position

    return pseudo_chunk


def _resolve_references_to_locations(
    references: Any,
    chunk_lookup: Dict[str, dict],
) -> List[Dict[str, Any]]:
    """Resolve one or many chunk IDs to grounding location dicts."""
    if references is None:
        return []
    if isinstance(references, str):
        refs: List[Any] = [references]
    elif isinstance(references, list):
        refs = references
    else:
        refs = [references]

    locations: List[Dict[str, Any]] = []
    for ref in refs:
        ref_key = str(ref)
        chunk = chunk_lookup.get(ref_key)
        if not chunk:
            continue
        chunk_grounding = chunk.get("grounding", [])
        if isinstance(chunk_grounding, dict):
            chunk_grounding = [chunk_grounding]
        if not isinstance(chunk_grounding, list):
            chunk_grounding = []

        for grounding in chunk_grounding:
            if not isinstance(grounding, dict):
                continue
            locations.append(
                {
                    "chunk_id": ref_key,
                    "page": grounding.get("page", 0),
                    "bounding_box": grounding.get("box", {}),
                    "chunk_type": chunk.get("chunk_type") or chunk.get("type"),
                }
            )
    return locations


def _resolve_meta_entry(
    meta: Any,
    chunk_lookup: Dict[str, dict],
) -> Any:
    """
    Resolve a single extraction_metadata entry.

    Flat field:  ``{"value": ..., "references": [...]}``  → list of locations.
    Array field: ``[{"sub_field": {"value": ..., "references": [...]}, ...}]``
                 → list of dicts, each mapping sub-field → locations.
    """
    if isinstance(meta, dict) and "references" in meta:
        return _resolve_references_to_locations(meta["references"], chunk_lookup)
    if isinstance(meta, list):
        scalar_items = [item for item in meta if isinstance(item, dict) and "references" in item]
        if scalar_items and len(scalar_items) == len(meta):
            combined: List[Dict[str, Any]] = []
            for item in scalar_items:
                combined.extend(
                    _resolve_references_to_locations(item.get("references", []), chunk_lookup)
                )
            return combined

        return [_resolve_meta_dict(item, chunk_lookup) for item in meta if isinstance(item, dict)]
    return None


def _resolve_meta_dict(
    item: Dict[str, Any],
    chunk_lookup: Dict[str, dict],
) -> Dict[str, Any]:
    """Resolve all sub-fields within a single array element dict."""
    resolved: Dict[str, Any] = {}
    for sub_field, sub_meta in item.items():
        entry = _resolve_meta_entry(sub_meta, chunk_lookup)
        if entry is not None:
            resolved[sub_field] = entry
    return resolved


def _resolve_field_grounding(
    extraction_metadata: Optional[Dict[str, Any]],
    parse_response: Any,
) -> Optional[Dict[str, Any]]:
    """
    Resolve all extraction_metadata references to grounding locations.

    Returns a dict mapping each field name to a list of
    ``{"chunk_id", "page", "bounding_box", "chunk_type"}`` objects,
    or ``None`` when no grounding data is available.
    """

    if not extraction_metadata:
        return None

    chunk_lookup = _build_chunk_lookup(parse_response)
    if not chunk_lookup:
        return None

    grounding: Dict[str, Any] = {}
    for field_name, meta in extraction_metadata.items():
        entry = _resolve_meta_entry(meta, chunk_lookup)
        if entry is not None:
            grounding[field_name] = entry

    return grounding or None


# =============================================================================
# Async Client Setup
# =============================================================================


def _get_async_client():
    """Get AsyncLandingAIADE client with API key from environment."""
    try:
        from landingai_ade import AsyncLandingAIADE
    except ImportError as e:
        raise RuntimeError(_MISSING_LANDINGAI_MSG) from e

    api_key = os.environ.get("VISION_AGENT_API_KEY") or os.environ.get("VA_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing API key. Set VISION_AGENT_API_KEY or VA_API_KEY environment variable."
        )

    return AsyncLandingAIADE(apikey=api_key)


def _get_sync_client():
    """Get synchronous LandingAIADE client."""
    try:
        from landingai_ade import LandingAIADE
    except ImportError as e:
        raise RuntimeError(_MISSING_LANDINGAI_MSG) from e

    api_key = os.environ.get("VISION_AGENT_API_KEY") or os.environ.get("VA_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing API key. Set VISION_AGENT_API_KEY or VA_API_KEY environment variable."
        )

    return LandingAIADE(apikey=api_key)


# =============================================================================
# Rate Limiter Setup
# =============================================================================


def _get_rate_limiter(max_rate: float = 10.0, time_period: float = 1.0):
    """
    Get an async rate limiter to avoid 429 errors.

    Args:
        max_rate: Maximum number of requests per time_period
        time_period: Time period in seconds

    Returns:
        AsyncLimiter instance or None if aiolimiter not installed
    """
    try:
        from aiolimiter import AsyncLimiter

        return AsyncLimiter(max_rate, time_period)
    except ImportError:
        print("⚠️  aiolimiter not installed. Rate limiting disabled.")
        print("   Install with: pip install aiolimiter")
        return None


# =============================================================================
# Validation Layer Integration
# =============================================================================


def _get_field_descriptions_for_doc_type(doc_type: str) -> Dict[str, str]:
    """Get field descriptions for a document type from its Pydantic model."""
    model_cls = PYDANTIC_MODELS.get(doc_type)
    if not model_cls:
        return {}

    descriptions = {}
    for field_name, field_info in model_cls.model_fields.items():
        descriptions[field_name] = field_info.description or f"Field: {field_name}"

    return descriptions


def _parse_field_meta_list(
    field_meta: list, fallback_value: Any
) -> Tuple[str, List, Optional[float]]:
    """Extract (extracted_text, references, confidence) from list-style metadata."""
    references: List = []
    extracted_texts: List[str] = []
    for item_meta in field_meta:
        if not isinstance(item_meta, dict):
            continue
        item_refs = item_meta.get("references", [])
        if isinstance(item_refs, list):
            references.extend(item_refs)
        elif item_refs is not None:
            references.append(item_refs)
        item_text = item_meta.get("extracted_text") or item_meta.get("value", "")
        if item_text:
            extracted_texts.append(str(item_text))
    extracted_text = ", ".join(extracted_texts) if extracted_texts else str(fallback_value)
    return extracted_text, references, None


def _parse_field_meta(field_meta: Any, fallback_value: Any) -> Tuple[str, List, Optional[float]]:
    """Normalize field metadata into (extracted_text, references, confidence)."""
    if isinstance(field_meta, list):
        return _parse_field_meta_list(field_meta, fallback_value)
    if isinstance(field_meta, dict):
        references = field_meta.get("references", [])
        if isinstance(references, list):
            normalized_refs = references
        elif references is None:
            normalized_refs = []
        else:
            normalized_refs = [references]
        return (
            field_meta.get("extracted_text", str(fallback_value)),
            normalized_refs,
            field_meta.get("confidence"),
        )
    return str(fallback_value), [], None


def _build_candidate(
    result: DocumentResult, _field_name: str, value: Any, field_meta: Any
) -> FieldCandidate:
    """Build a FieldCandidate from a result and its field metadata."""
    extracted_text, references, confidence = _parse_field_meta(field_meta, value)
    return FieldCandidate(
        value=value,
        source_file=result.file_path or result.file_name,
        source_filename=result.file_name,
        extracted_text=extracted_text,
        confidence=confidence,
        chunk_ids=references,
        evidence_locations=[],
    )


def _collect_candidates_from_result(
    result: DocumentResult, doc_type: str
) -> Dict[str, FieldCandidate]:
    """Collect field candidates from a single result."""
    if not result.success or result.document_type != doc_type:
        return {}
    extraction_meta = result.extraction_metadata or {}
    candidates: Dict[str, FieldCandidate] = {}
    for field_name, value in result.extracted_data.items():
        if value is None:
            continue
        field_meta = extraction_meta.get(field_name, {})
        candidates[field_name] = _build_candidate(result, field_name, value, field_meta)
    return candidates


def _find_conflicting_fields(
    field_candidates: Dict[str, List[FieldCandidate]],
    field_descriptions: Dict[str, str],
    top_level_category: TopLevelCategory,
    doc_type: str,
) -> List[FieldConflict]:
    """Return FieldConflict objects for fields with multiple distinct values."""
    conflicts: List[FieldConflict] = []
    for field_name, candidates in field_candidates.items():
        unique_values = {json.dumps(c.value, sort_keys=True, default=str) for c in candidates}
        if len(unique_values) > 1:
            conflicts.append(
                FieldConflict(
                    field_name=field_name,
                    field_description=field_descriptions.get(field_name, f"Field: {field_name}"),
                    candidates=candidates,
                    top_level_category=top_level_category.value,
                    document_type=doc_type,
                )
            )
    return conflicts


def _collect_conflicts_from_results(
    results: List[DocumentResult],
    doc_type: str,
    top_level_category: TopLevelCategory,
) -> Tuple[List[FieldConflict], List[str]]:
    """
    Collect field conflicts from extraction results of the same document type.

    Returns:
        Tuple of (list of FieldConflict objects, list of source files)
    """
    field_descriptions = _get_field_descriptions_for_doc_type(doc_type)
    field_candidates: Dict[str, List[FieldCandidate]] = {}
    source_files: List[str] = []

    for result in results:
        per_result = _collect_candidates_from_result(result, doc_type)
        if not per_result:
            continue
        source_files.append(result.file_path or result.file_name)
        for field_name, candidate in per_result.items():
            field_candidates.setdefault(field_name, []).append(candidate)

    conflicts = _find_conflicting_fields(
        field_candidates, field_descriptions, top_level_category, doc_type
    )
    return conflicts, source_files


def _extract_text_from_meta(meta: Any, fallback: str) -> str:
    """Extract a human-readable text string from field metadata."""
    if isinstance(meta, dict):
        return meta.get("extracted_text", fallback)
    if isinstance(meta, list):
        texts = [m.get("extracted_text", "") for m in meta if isinstance(m, dict)]
        return ", ".join(filter(None, texts)) or fallback
    return fallback


def _find_extracted_text_for_source(
    results: List[DocumentResult],
    field_name: str,
    selected_source: str,
    fallback: str,
) -> str:
    """Find extracted_text for a field from the result matching selected_source."""
    for r in results:
        if (r.file_path or r.file_name) == selected_source:
            meta = (r.extraction_metadata or {}).get(field_name, {})
            return _extract_text_from_meta(meta, fallback)
    return ""


def _build_field_from_validation(
    field_name: str,
    validation: ValidationResult,
    results: List[DocumentResult],
) -> ValidatedFieldOutput:
    """Build a ValidatedFieldOutput from a resolved validation result."""
    extracted_text = _find_extracted_text_for_source(
        results, field_name, validation.selected_source, str(validation.selected_value)
    )
    return ValidatedFieldOutput(
        field_name=field_name,
        value=validation.selected_value,
        source_file=validation.selected_source,
        source_filename=validation.selected_source_filename,
        extracted_text=extracted_text,
        locations=validation.locations,
        confidence_score=validation.confidence_score,
        justification=validation.justification,
        alternatives=validation.alternative_values,
        flags=validation.flags,
    )


def _build_field_first_value(
    field_name: str,
    results: List[DocumentResult],
) -> Optional[ValidatedFieldOutput]:
    """Build a ValidatedFieldOutput from the first non-null value across results."""
    for r in results:
        if not r.success:
            continue
        val = r.extracted_data.get(field_name)
        if val is None:
            continue
        meta = (r.extraction_metadata or {}).get(field_name, {})
        extracted_text = _extract_text_from_meta(meta, str(val))
        return ValidatedFieldOutput(
            field_name=field_name,
            value=val,
            source_file=r.file_path or r.file_name,
            source_filename=r.file_name,
            extracted_text=extracted_text,
            locations=[],
            confidence_score=1.0,
            justification="Single source value - no conflict resolution needed.",
            alternatives=[],
            flags=[],
        )
    return None


def _build_validated_output(
    results: List[DocumentResult],
    doc_type: str,
    top_level_category: TopLevelCategory,
    validation_report: Optional[ValidationReport],
) -> ValidatedDocumentResult:
    """
    Build validated output for a document type, merging results and applying validation.

    Returns:
        ValidatedDocumentResult with merged and validated fields
    """
    source_files = [r.file_path or r.file_name for r in results if r.success]

    validated_fields_lookup: Dict[str, ValidationResult] = {}
    if validation_report:
        validated_fields_lookup = {v.field_name: v for v in validation_report.validations}

    all_fields: set = set()
    for r in results:
        if r.success:
            all_fields.update(r.extracted_data.keys())

    validated_fields: Dict[str, ValidatedFieldOutput] = {}
    for field_name in sorted(all_fields):
        if field_name in validated_fields_lookup:
            validated_fields[field_name] = _build_field_from_validation(
                field_name, validated_fields_lookup[field_name], results
            )
        else:
            field_output = _build_field_first_value(field_name, results)
            if field_output:
                validated_fields[field_name] = field_output

    overall_confidence = validation_report.overall_confidence if validation_report else 1.0
    summary = validation_report.summary if validation_report else "No conflicts detected."

    return ValidatedDocumentResult(
        document_type=doc_type,
        top_level_category=top_level_category.value,
        source_files=source_files,
        validated_fields=validated_fields,
        validation_report=validation_report,
        overall_confidence=overall_confidence,
        validation_summary=summary,
    )


def validate_batch_results(
    results: List[DocumentResult],
    top_level_category: TopLevelCategory,
    validation_model: str = "gpt-5-nano-2025-08-07",
) -> Dict[str, ValidatedDocumentResult]:
    """
    Validate batch results by grouping by document type and resolving conflicts.

    Args:
        results: List of DocumentResult from batch processing
        top_level_category: Top-level category for all results
        validation_model: Model to use for validation reasoning

    Returns:
        Dict mapping document_type to ValidatedDocumentResult
    """
    # Group results by document type
    results_by_type: Dict[str, List[DocumentResult]] = {}
    for r in results:
        if r.success:
            results_by_type.setdefault(r.document_type, []).append(r)

    validated_results: Dict[str, ValidatedDocumentResult] = {}

    # Initialize validator (only if we have conflicts)
    validator: Optional[ValidationLayer] = None

    for doc_type, type_results in results_by_type.items():
        field_names = sorted(
            {field_name for result in type_results for field_name in result.extracted_data.keys()}
        )
        if should_disable_cross_document_validation(doc_type, field_names):
            print(
                "  Skipping validation for "
                f"{doc_type}: additive time-series fields must remain per source document"
            )
            continue

        if len(type_results) <= 1:
            # Single document, no conflicts possible
            validated_results[doc_type] = _build_validated_output(
                type_results, doc_type, top_level_category, None
            )
            continue

        # Check for conflicts
        conflicts, source_files = _collect_conflicts_from_results(
            type_results, doc_type, top_level_category
        )

        if not conflicts:
            # No conflicts found
            validated_results[doc_type] = _build_validated_output(
                type_results, doc_type, top_level_category, None
            )
            continue

        # Initialize validator lazily
        if validator is None:
            try:
                validator = ValidationLayer(model=validation_model)
            except RuntimeError as e:
                print(f"  ⚠️  Could not initialize validator: {e}")
                validated_results[doc_type] = _build_validated_output(
                    type_results, doc_type, top_level_category, None
                )
                continue

        print(f"  Validating {len(conflicts)} conflicts for {doc_type}...")

        # Validate conflicts
        validation_report = validator.validate_all_conflicts(
            conflicts=conflicts,
            top_level_category=top_level_category.value,
            document_type=doc_type,
            source_files=source_files,
        )

        validated_results[doc_type] = _build_validated_output(
            type_results, doc_type, top_level_category, validation_report
        )

    return validated_results


# =============================================================================
# Async Core Functions
# =============================================================================


async def _async_parse_document(
    client,
    document_path: Path,
    model: Optional[str] = None,
    rate_limiter=None,
) -> Tuple[str, Any]:
    """
    Async parse a document using LandingAI SDK.

    Args:
        client: AsyncLandingAIADE client
        document_path: Path to the PDF document
        model: Parse model to use
        rate_limiter: Optional rate limiter

    Returns:
        (markdown_content, parse_response)
    """
    parse_model = model or os.getenv("LANDING_PARSE_MODEL", "dpt-2-latest")

    if rate_limiter:
        async with rate_limiter:
            response = await client.parse(document=document_path, model=parse_model)
    else:
        response = await client.parse(document=document_path, model=parse_model)

    return response.markdown or "", response


async def _async_parse_from_bytes(
    client,
    pdf_bytes: bytes,
    _file_name: str,
    model: Optional[str] = None,
    rate_limiter=None,
) -> Tuple[str, Any]:
    """
    Async parse PDF from bytes content.

    Args:
        client: AsyncLandingAIADE client
        pdf_bytes: PDF file bytes
        file_name: Name for the file
        model: Parse model to use
        rate_limiter: Optional rate limiter

    Returns:
        (markdown_content, parse_response)
    """
    # Write to temp file and parse
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = Path(tmp.name)

    try:
        markdown_content, parse_response = await _async_parse_document(
            client, tmp_path, model=model, rate_limiter=rate_limiter
        )
        return markdown_content, parse_response
    finally:
        # Clean up temp file
        if tmp_path.exists():
            tmp_path.unlink()


# =============================================================================
# S3 Markdown Cache Layer
# =============================================================================

_cache_log = logging.getLogger("ddx.markdown_cache")

_DEFAULT_CACHE_PREFIX = "ddx-cache/markdown"
_MISSING_LANDINGAI_MSG = (
    "Missing dependency 'landingai-ade'. Install with: pip install landingai-ade"
)


def _sha256_of_bytes(data: bytes) -> str:
    """Compute SHA-256 hex digest of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def _sha256_of_path(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Compute SHA-256 hex digest of a file on disk."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _compute_document_hash(
    file_path: Optional[Path],
    pdf_bytes: Optional[bytes],
) -> Optional[str]:
    """Compute a stable content hash for cache keying. Returns None on failure."""
    try:
        if file_path and file_path.exists():
            return _sha256_of_path(file_path)
        if pdf_bytes:
            return _sha256_of_bytes(pdf_bytes)
    except Exception:
        return None
    return None


def _markdown_cache_key(prefix: str, doc_hash: str) -> str:
    """Build S3 object key for the cached markdown."""
    prefix = (prefix or "").strip("/")
    return f"{prefix}/{doc_hash}.md" if prefix else f"{doc_hash}.md"


def _markdown_meta_key(prefix: str, doc_hash: str) -> str:
    """Build S3 object key for the cache metadata JSON."""
    prefix = (prefix or "").strip("/")
    return f"{prefix}/{doc_hash}.meta.json" if prefix else f"{doc_hash}.meta.json"


def _parse_json_cache_key(prefix: str, doc_hash: str) -> str:
    """Build S3 object key for the cached parse.json."""
    prefix = (prefix or "").strip("/")
    return f"{prefix}/{doc_hash}.parse.json" if prefix else f"{doc_hash}.parse.json"


def _resolve_cache_config(
    markdown_cache: bool,
    markdown_cache_bucket: Optional[str],
    markdown_cache_prefix: str,
) -> Tuple[bool, Optional[str], str]:
    """Resolve effective cache config using environment fallbacks."""
    if not markdown_cache:
        return False, None, markdown_cache_prefix

    bucket = (
        markdown_cache_bucket
        or os.getenv("DDX_MARKDOWN_CACHE_BUCKET")
        or os.getenv("S3_BUCKET")
        or "drex-network"
    )
    if not bucket:
        _cache_log.warning("Markdown cache enabled but no bucket configured — disabling.")
        return False, None, markdown_cache_prefix

    prefix = markdown_cache_prefix or os.getenv("DDX_MARKDOWN_CACHE_PREFIX", _DEFAULT_CACHE_PREFIX)
    return True, bucket, prefix


async def _get_s3_client_cm():
    """Create an aioboto3 S3 client context manager. Returns None if unavailable."""
    try:
        import aioboto3
        from botocore.config import Config

        region = os.getenv("AWS_REGION", "us-east-1")
        cfg = Config(max_pool_connections=int(os.getenv("S3_MAX_POOL", "50")))
        return aioboto3.Session().client("s3", region_name=region, config=cfg)
    except Exception as e:
        _cache_log.warning("Cannot create S3 client for cache: %s", e)
        return None


async def _try_load_markdown_from_s3(s3_client, bucket: str, key: str) -> Optional[str]:
    """Return cached markdown if present in S3, else None."""
    try:
        obj = await s3_client.get_object(Bucket=bucket, Key=key)
        body = await obj["Body"].read()
        return body.decode("utf-8", errors="replace")
    except Exception:
        return None


async def _try_load_parse_json_from_s3(
    s3_client,
    bucket: str,
    key: str,
) -> Optional[Dict[str, Any]]:
    """Return cached parse.json dict if present in S3, else None."""
    try:
        obj = await s3_client.get_object(Bucket=bucket, Key=key)
        body = await obj["Body"].read()
        return json.loads(body.decode("utf-8", errors="replace"))
    except Exception:
        return None


def _serialize_parse_response(parse_response: Any) -> Optional[Dict[str, Any]]:
    """Serialize an SDK parse response object to a JSON-safe dict."""
    if parse_response is None:
        return None
    if isinstance(parse_response, dict):
        return parse_response
    if hasattr(parse_response, "model_dump"):
        return parse_response.model_dump()
    if hasattr(parse_response, "dict"):
        return parse_response.dict()
    return None


async def _save_markdown_to_s3(
    s3_client,
    bucket: str,
    key: str,
    markdown: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Best-effort upload of markdown + metadata JSON to S3."""
    await s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=markdown.encode("utf-8"),
        ContentType="text/markdown; charset=utf-8",
    )
    if metadata:
        meta_key = key.replace(".md", ".meta.json")
        await s3_client.put_object(
            Bucket=bucket,
            Key=meta_key,
            Body=json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8"),
            ContentType="application/json; charset=utf-8",
        )


async def _save_parse_json_to_s3(
    s3_client,
    bucket: str,
    key: str,
    parse_response: Any,
) -> None:
    """Best-effort upload of serialized parse response to S3."""
    serialized = _serialize_parse_response(parse_response)
    if serialized is None:
        return
    await s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(serialized, ensure_ascii=False, default=str).encode("utf-8"),
        ContentType="application/json; charset=utf-8",
    )


async def _parse_with_cache(
    client,
    file_path: Optional[Path],
    pdf_bytes: Optional[bytes],
    file_name: str,
    parse_model: Optional[str],
    rate_limiter=None,
    *,
    cache_enabled: bool = False,
    cache_bucket: Optional[str] = None,
    cache_prefix: str = _DEFAULT_CACHE_PREFIX,
    s3_client=None,
) -> Tuple[str, Any]:
    """
    Parse a document to markdown with optional S3 caching.

    If cache is enabled and a cached markdown exists for the document's
    content hash, returns the cached version (skipping the expensive parse).
    Otherwise parses normally and uploads the result to S3 for future use.

    This is the SINGLE entry point for parsing across all three endpoints.
    """
    doc_hash = _compute_document_hash(file_path, pdf_bytes)
    cache_key = (
        _markdown_cache_key(cache_prefix, doc_hash) if (cache_enabled and doc_hash) else None
    )

    # --- Try cache hit ---
    parse_json_key = (
        _parse_json_cache_key(cache_prefix, doc_hash) if (cache_enabled and doc_hash) else None
    )
    if cache_enabled and s3_client and cache_bucket and cache_key:
        cached = await _try_load_markdown_from_s3(s3_client, cache_bucket, cache_key)
        if cached:
            _cache_log.info("Cache HIT for %s (hash=%s)", file_name, doc_hash[:12])
            cached_parse = (
                await _try_load_parse_json_from_s3(s3_client, cache_bucket, parse_json_key)
                if parse_json_key
                else None
            )
            parse_response = cached_parse or {
                "cache_hit": True,
                "cache_bucket": cache_bucket,
                "cache_key": cache_key,
            }
            return cached, parse_response

    # --- Parse normally ---
    print(f"  Parsing: {file_name}")
    if file_path and file_path.exists():
        markdown_content, parse_response = await _async_parse_document(
            client, file_path, model=parse_model, rate_limiter=rate_limiter
        )
    elif pdf_bytes:
        markdown_content, parse_response = await _async_parse_from_bytes(
            client, pdf_bytes, file_name, model=parse_model, rate_limiter=rate_limiter
        )
    else:
        raise ValueError(f"No valid file content for: {file_name}")

    # --- Best-effort upload to cache ---
    if cache_enabled and s3_client and cache_bucket and cache_key:
        try:
            await _save_markdown_to_s3(
                s3_client,
                cache_bucket,
                cache_key,
                markdown_content,
                metadata={
                    "file_name": file_name,
                    "parse_model": parse_model or os.getenv("LANDING_PARSE_MODEL", "dpt-2-latest"),
                    "doc_hash": doc_hash,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            if parse_json_key:
                await _save_parse_json_to_s3(
                    s3_client,
                    cache_bucket,
                    parse_json_key,
                    parse_response,
                )
            _cache_log.info("Cache SAVE for %s (hash=%s)", file_name, doc_hash[:12])
        except Exception as e:
            _cache_log.warning("Cache upload failed for %s: %s", file_name, e)

    return markdown_content, parse_response


async def _async_extract(
    client,
    markdown_content: str,
    schema: Dict[str, Any],
    model: Optional[str] = None,
    rate_limiter=None,
) -> Dict[str, Any]:
    """
    Async extract fields from markdown using a schema.

    Args:
        client: AsyncLandingAIADE client
        markdown_content: Markdown content
        schema: JSON schema for extraction
        model: Extract model to use
        rate_limiter: Optional rate limiter

    Returns:
        Raw response dict with extraction and metadata
    """
    extract_model = model or os.getenv("LANDING_EXTRACT_MODEL", "extract-latest")

    if rate_limiter:
        async with rate_limiter:
            response = await client.extract(
                schema=schema,
                markdown=BytesIO(markdown_content.encode("utf-8")),
                model=extract_model,
            )
    else:
        response = await client.extract(
            schema=schema,
            markdown=BytesIO(markdown_content.encode("utf-8")),
            model=extract_model,
        )

    return {
        "extraction": getattr(response, "extraction", {}) or {},
        "extraction_metadata": getattr(response, "extraction_metadata", None),
    }


async def _async_classify_from_markdown(
    client,
    markdown_content: str,
    top_level_category: TopLevelCategory,
    model: Optional[str] = None,
    max_chars: int = 80000,
    rate_limiter=None,
) -> Tuple[str, Dict[str, Any]]:
    """
    Async classify a document using its markdown content within a specific category.

    Args:
        client: AsyncLandingAIADE client
        markdown_content: Markdown content from parse
        top_level_category: Top-level category to classify within
        model: Extract model to use
        max_chars: Max characters to use for classification
        rate_limiter: Optional rate limiter

    Returns:
        (document_type, raw_response)
    """
    try:
        from landingai_ade.lib import pydantic_to_json_schema
    except ImportError as e:
        raise RuntimeError(_MISSING_LANDINGAI_MSG) from e

    # Truncate markdown for classification
    truncated_markdown = markdown_content[:max_chars]

    # Build category-specific classification schema
    schema_cls = build_classification_schema_for_category(top_level_category)
    schema = pydantic_to_json_schema(schema_cls)

    raw = await _async_extract(
        client, truncated_markdown, schema, model=model, rate_limiter=rate_limiter
    )

    # Extract document type from response
    extraction = raw.get("extraction", {})
    doc_type_value = extraction.get("document_type")

    if doc_type_value:
        doc_type = doc_type_value if isinstance(doc_type_value, str) else str(doc_type_value)
    else:
        doc_type = DocumentType.UNCATEGORIZED.value

    # Add top-level category to raw response
    raw["top_level_category"] = top_level_category.value

    return doc_type, raw


async def _async_extract_fields(
    client,
    markdown_content: str,
    doc_type: str,
    model: Optional[str] = None,
    rate_limiter=None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Async extract fields from markdown using the appropriate schema.

    Args:
        client: AsyncLandingAIADE client
        markdown_content: Markdown content from parse
        doc_type: Document type/category
        model: Extract model to use
        rate_limiter: Optional rate limiter

    Returns:
        (extracted_data, raw_response)
    """
    try:
        from landingai_ade.lib import pydantic_to_json_schema
    except ImportError as e:
        raise RuntimeError(_MISSING_LANDINGAI_MSG) from e

    model_cls = PYDANTIC_MODELS.get(doc_type)
    if not model_cls:
        return {}, {"skipped": True, "reason": f"No extraction schema for '{doc_type}'"}

    # Convert Pydantic model to JSON schema
    schema = pydantic_to_json_schema(model_cls)

    # Equipment research-only fields are populated by the research module.
    # Excluding them here avoids SDK extraction returning partial/null values
    # that can conflict with enriched research values downstream.
    if _is_equipment_sheets_document_type(doc_type):
        schema = _remove_schema_fields(schema, _EQUIPMENT_RESEARCH_ONLY_FIELDS)

    raw = await _async_extract(
        client, markdown_content, schema, model=model, rate_limiter=rate_limiter
    )

    extraction = raw.get("extraction", {})

    # Validate with Pydantic model
    try:
        if hasattr(model_cls, "model_validate"):
            validated = model_cls.model_validate(extraction)
        else:
            validated = model_cls.parse_obj(extraction)

        extracted = validated.model_dump() if hasattr(validated, "model_dump") else validated.dict()
    except Exception as e:
        print(f"  ⚠️  Validation warning: {e}")
        extracted = extraction

    extracted, normalized_metadata = normalize_extracted_document(
        doc_type,
        extracted,
        raw.get("extraction_metadata"),
    )
    raw["extraction_metadata"] = normalized_metadata

    return extracted, raw


# =============================================================================
# Function 1: Batch Processing by Category (Async)
# =============================================================================


def _resolve_file_input(
    file_input: Union[Path, bytes, Dict[str, Any]],
    file_name: Optional[str],
    idx: int = 0,
) -> Tuple[Optional[Path], Optional[bytes], str]:
    """
    Normalize the various file input formats into (file_path, pdf_bytes, file_name).

    Returns:
        (file_path or None, pdf_bytes or None, resolved_file_name)
    """
    if isinstance(file_input, Path):
        return file_input, None, file_input.name
    if isinstance(file_input, bytes):
        return None, file_input, file_name or f"document_{idx}.pdf"
    if isinstance(file_input, dict):
        path = file_input.get("path")
        fp = Path(path) if path else None
        name = file_name or file_input.get("name", f"document_{idx}.pdf")
        return fp, file_input.get("content"), name
    raise ValueError(f"Unsupported file input type: {type(file_input)}")


async def _process_single_document(
    client,
    file_input: Union[Path, bytes, Dict[str, Any]],
    file_name: Optional[str],
    idx: int,
    top_level_category: TopLevelCategory,
    parse_model: Optional[str],
    extract_model: Optional[str],
    rate_limiter=None,
    save_markdown: bool = True,
    *,
    cache_enabled: bool = True,
    cache_bucket: Optional[str] = "drex-network",
    cache_prefix: str = _DEFAULT_CACHE_PREFIX,
    s3_client=None,
) -> DocumentResult:
    """Process a single document (internal async helper)."""
    try:
        file_path, pdf_bytes, file_name = _resolve_file_input(file_input, file_name, idx)

        # Step 1: Parse document (with optional S3 markdown cache)
        markdown_content, parse_response = await _parse_with_cache(
            client,
            file_path,
            pdf_bytes,
            file_name,
            parse_model,
            rate_limiter,
            cache_enabled=cache_enabled,
            cache_bucket=cache_bucket,
            cache_prefix=cache_prefix,
            s3_client=s3_client,
        )

        # Step 2: Classify document within the top-level category
        print(f"  Classifying: {file_name}")
        doc_type, _ = await _async_classify_from_markdown(
            client,
            markdown_content,
            top_level_category,
            model=extract_model,
            rate_limiter=rate_limiter,
        )
        # doc_type = "Tax Compliance Certificate"
        print(f"  → {file_name}: {doc_type}")

        # Step 3: Extract fields
        print(f"  Extracting: {file_name}")
        extracted, extract_raw = await _async_extract_fields(
            client, markdown_content, doc_type, model=extract_model, rate_limiter=rate_limiter
        )
        _print_extracted_variables(file_name, extracted)

        # Step 4: Resolve grounding locations from extraction references
        ext_meta = extract_raw.get("extraction_metadata")
        grounding = _resolve_field_grounding(ext_meta, parse_response)

        return DocumentResult(
            file_name=file_name,
            file_path=str(file_path) if file_path else None,
            document_type=doc_type,
            top_level_category=top_level_category.value,
            extracted_data=extracted,
            extraction_metadata=ext_meta,
            field_grounding=grounding,
            markdown_content=markdown_content if save_markdown else None,
            success=True,
        )

    except Exception as e:
        return DocumentResult(
            file_name=file_name or f"document_{idx}",
            document_type="unknown",
            top_level_category=top_level_category.value,
            extracted_data={},
            success=False,
            error=f"{type(e).__name__}: {str(e)}",
        )


def _print_validation_summary(
    validated_results: Dict[str, ValidatedDocumentResult],
) -> None:
    """Print a human-readable summary of validation outcomes."""
    for doc_type, validated in validated_results.items():
        if validated.validation_report:
            report = validated.validation_report
            print(f"  {doc_type}: {report.total_fields_validated} conflicts resolved")
            print(f"    Overall confidence: {report.overall_confidence:.2f}")
        else:
            print(f"  {doc_type}: No conflicts detected")


def _run_optional_validation(
    results: list,
    enable_validation: bool,
    top_level_category: TopLevelCategory,
    validation_model: str,
) -> Tuple[Optional[Dict[str, ValidatedDocumentResult]], bool]:
    """Run validation if enabled and there are enough successful results."""
    successful = sum(1 for r in results if r.success)
    if not (enable_validation and successful > 1):
        return None, False

    print("\n" + "=" * 60)
    print("Running validation layer for conflict resolution...")
    print("=" * 60)

    validated_results = validate_batch_results(
        list(results),
        top_level_category=top_level_category,
        validation_model=validation_model,
    )
    if not validated_results:
        print("No eligible document types for validation in this batch.")
        return None, False

    _print_validation_summary(validated_results)
    return validated_results, True


async def process_documents_by_category_async(
    files: Union[List[Path], List[bytes], List[Dict[str, Any]]],
    top_level_category: TopLevelCategory,
    *,
    file_names: Optional[List[str]] = None,
    parse_model: Optional[str] = None,
    extract_model: Optional[str] = None,
    save_markdown: bool = False,
    max_concurrent: int = 5,
    rate_limit: float = 10.0,
    enable_validation: bool = True,
    validation_model: str = "gpt-5-nano-2025-08-07",
    markdown_cache: bool = True,
    markdown_cache_bucket: Optional[str] = None,
    markdown_cache_prefix: str = _DEFAULT_CACHE_PREFIX,
) -> BatchProcessingResult:
    """
    Async process a list of documents for a given top-level category.

    This function:
    1. Parses each document to markdown (concurrently)
    2. Classifies it to determine the specific document type within the category
    3. Extracts fields using the appropriate schema
    4. Validates and resolves conflicts when multiple documents have the same type

    Args:
        files: List of file paths, bytes, or dicts with 'content' and 'name' keys
        top_level_category: Top-level category (REQUIRED - e.g., TopLevelCategory.TECHNICAL)
        file_names: Optional list of file names (required if files are bytes)
        parse_model: Model for parsing (default: dpt-2-latest)
        extract_model: Model for extraction (default: extract-latest)
        save_markdown: Whether to include markdown in results
        max_concurrent: Maximum concurrent requests (default: 5)
        rate_limit: Max requests per second (default: 10.0)
        enable_validation: Whether to run validation layer for conflicts (default: True)
        validation_model: Model for validation reasoning (default: gpt-5-nano-2025-08-07)

    Returns:
        BatchProcessingResult with all document results and validated results

    Example:
        from ddx.classification.categories import TopLevelCategory

        result = await process_documents_by_category_async(
            files=[Path("doc1.pdf"), Path("doc2.pdf")],
            top_level_category=TopLevelCategory.TECHNICAL,
            max_concurrent=5,
            enable_validation=True
        )
    """
    # Setup client and rate limiter
    client = _get_async_client()
    rate_limiter = _get_rate_limiter(rate_limit, 1.0)

    # Resolve cache config
    cache_enabled, cache_bucket, cache_prefix = _resolve_cache_config(
        markdown_cache, markdown_cache_bucket, markdown_cache_prefix
    )

    # Create semaphore for concurrency control
    semaphore = asyncio.Semaphore(max_concurrent)

    # Optionally create a shared S3 client for the whole batch
    s3_cm = await _get_s3_client_cm() if cache_enabled else None

    async def _run_batch(s3_client_instance):
        async def process_with_semaphore(file_input, file_name, idx):
            async with semaphore:
                return await _process_single_document(
                    client=client,
                    file_input=file_input,
                    file_name=file_name,
                    idx=idx,
                    top_level_category=top_level_category,
                    parse_model=parse_model,
                    extract_model=extract_model,
                    rate_limiter=rate_limiter,
                    save_markdown=save_markdown,
                    cache_enabled=cache_enabled,
                    cache_bucket=cache_bucket,
                    cache_prefix=cache_prefix,
                    s3_client=s3_client_instance,
                )

        tasks = []
        for idx, file_input in enumerate(files):
            name = file_names[idx] if file_names and idx < len(file_names) else None
            tasks.append(process_with_semaphore(file_input, name, idx))
        return await asyncio.gather(*tasks)

    # Execute all tasks concurrently
    print(f"\nProcessing {len(files)} documents for category: {top_level_category.value}")
    print(f"Max concurrent: {max_concurrent}, Rate limit: {rate_limit}/sec")
    if cache_enabled:
        print(f"Markdown cache: s3://{cache_bucket}/{cache_prefix}/")
    print("=" * 60)

    if s3_cm is not None:
        async with s3_cm as s3_client:
            results = await _run_batch(s3_client)
    else:
        results = await _run_batch(None)

    successful = sum(1 for r in results if r.success)

    validated_results, validation_performed = _run_optional_validation(
        list(results), enable_validation, top_level_category, validation_model
    )

    return BatchProcessingResult(
        top_level_category=top_level_category.value,
        total_documents=len(files),
        successful=successful,
        failed=len(files) - successful,
        results=list(results),
        validated_results=validated_results,
        validation_performed=validation_performed,
    )


def process_documents_by_category(
    files: Union[List[Path], List[bytes], List[Dict[str, Any]]],
    top_level_category: TopLevelCategory,
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
    """
    Sync wrapper for process_documents_by_category_async.

    See process_documents_by_category_async for full documentation.
    """
    return asyncio.run(
        process_documents_by_category_async(
            files=files,
            top_level_category=top_level_category,
            file_names=file_names,
            parse_model=parse_model,
            extract_model=extract_model,
            save_markdown=save_markdown,
            max_concurrent=max_concurrent,
            rate_limit=rate_limit,
            enable_validation=enable_validation,
            validation_model=validation_model,
        )
    )


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
    """
    Async process multiple arrays of documents, each with its own top-level category.

    Args:
        files_by_category: Dict mapping TopLevelCategory to list of files
        file_names_by_category: Optional dict mapping category to file names
        parse_model: Model for parsing
        extract_model: Model for extraction
        max_concurrent: Maximum concurrent requests
        rate_limit: Max requests per second
        enable_validation: Whether to run validation layer (default: True)
        validation_model: Model for validation reasoning

    Returns:
        Dict mapping TopLevelCategory to BatchProcessingResult

    Example:
        from ddx.classification.categories import TopLevelCategory

        results = await process_documents_multi_category_async(
            files_by_category={
                TopLevelCategory.TECHNICAL: [Path("sim_report.pdf"), Path("equipment.pdf")],
                TopLevelCategory.COMPANY_INFORMATION: [Path("ruc.pdf")],
            },
            enable_validation=True
        )
    """
    results: Dict[TopLevelCategory, BatchProcessingResult] = {}

    # Process categories sequentially to avoid overwhelming the API
    for category, files in files_by_category.items():
        file_names = None
        if file_names_by_category:
            file_names = file_names_by_category.get(category)

        results[category] = await process_documents_by_category_async(
            files=files,
            top_level_category=category,
            file_names=file_names,
            parse_model=parse_model,
            extract_model=extract_model,
            max_concurrent=max_concurrent,
            rate_limit=rate_limit,
            enable_validation=enable_validation,
            validation_model=validation_model,
        )

    return results


def process_documents_multi_category(
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
    """Sync wrapper for process_documents_multi_category_async."""
    return asyncio.run(
        process_documents_multi_category_async(
            files_by_category=files_by_category,
            file_names_by_category=file_names_by_category,
            parse_model=parse_model,
            extract_model=extract_model,
            max_concurrent=max_concurrent,
            rate_limit=rate_limit,
            enable_validation=enable_validation,
            validation_model=validation_model,
        )
    )


# =============================================================================
# Function 2: Human-in-the-Loop Field Re-extraction (Async)
# =============================================================================


def _create_partial_schema(
    full_schema: Type[BaseModel],
    fields: List[str],
) -> Type[BaseModel]:
    """Create a partial Pydantic schema with only specified fields."""
    field_definitions = {}

    for field_name in fields:
        if field_name in full_schema.model_fields:
            field_info = full_schema.model_fields[field_name]
            # Make all fields optional for partial extraction
            field_definitions[field_name] = (
                Optional[field_info.annotation],
                Field(default=None, description=field_info.description),
            )

    # Create dynamic model
    partial_model = create_model(
        f"Partial{full_schema.__name__}",
        **field_definitions,
    )

    return partial_model


def _get_top_level_for_document_type(document_type: str) -> Optional[TopLevelCategory]:
    """Get top-level category for a document type."""
    for doc_type, top_level in DOCUMENT_TYPE_TO_TOP_LEVEL.items():
        if doc_type.value == document_type:
            return top_level
    return None


def _resolve_schema_cls(document_type: str) -> Optional[Type[BaseModel]]:
    """Resolve a schema class by document type string, supporting enum or string keyed registries."""
    schema_cls = PYDANTIC_MODELS.get(document_type)
    if schema_cls:
        return schema_cls

    try:
        doc_enum = DocumentType(document_type)
    except ValueError:
        return None

    schema_cls = PYDANTIC_MODELS.get(doc_enum)
    if schema_cls:
        return schema_cls

    return PYDANTIC_MODELS.get(doc_enum.value)


def _valid_document_types() -> List[str]:
    """Return normalized list of valid document type strings for error messages."""
    values: List[str] = []
    for key in PYDANTIC_MODELS.keys():
        values.append(key.value if hasattr(key, "value") else str(key))
    return sorted(set(values))


def _resolve_file_name(file: Union[Path, bytes, Dict[str, Any]], file_name: Optional[str]) -> str:
    """Determine a display/file name from various input types."""
    if file_name:
        return file_name
    if isinstance(file, Path):
        return file.name
    if isinstance(file, dict):
        return file.get("name", "document.pdf")
    return "document.pdf"


def _validate_document_type_fields(document_type: str, fields: List[str]) -> Type[BaseModel]:
    """Validate document_type exists and requested fields are valid. Returns schema class."""
    schema_cls = _resolve_schema_cls(document_type)
    if not schema_cls:
        raise ValueError(
            f"Unknown document type: {document_type}. " f"Valid types: {_valid_document_types()}"
        )
    schema_fields = set(schema_cls.model_fields.keys())
    invalid_fields = set(fields) - schema_fields
    if invalid_fields:
        raise ValueError(
            f"Invalid fields for {document_type}: {invalid_fields}. "
            f"Valid fields: {schema_fields}"
        )
    return schema_cls


async def _parse_or_use_existing(
    client,
    file: Union[Path, bytes, Dict[str, Any]],
    file_name: str,
    parse_model: Optional[str],
    rate_limiter,
    existing_markdown: Optional[str],
    markdown_cache: bool,
    markdown_cache_bucket: Optional[str],
    markdown_cache_prefix: str,
) -> Tuple[str, Any]:
    """Parse a document (with optional caching) or return pre-existing markdown.

    Returns:
        (markdown_content, parse_response)  — parse_response is ``None``
        when *existing_markdown* is supplied.
    """
    if existing_markdown:
        return existing_markdown, None

    file_path, pdf_bytes, file_name = _resolve_file_input(file, file_name)
    cache_on, cache_bkt, cache_pfx = _resolve_cache_config(
        markdown_cache, markdown_cache_bucket, markdown_cache_prefix
    )

    s3_cm = (await _get_s3_client_cm()) if cache_on else None
    if s3_cm:
        async with s3_cm as s3_client:
            md, parse_resp = await _parse_with_cache(
                client,
                file_path,
                pdf_bytes,
                file_name,
                parse_model,
                rate_limiter,
                cache_enabled=True,
                cache_bucket=cache_bkt,
                cache_prefix=cache_pfx,
                s3_client=s3_client,
            )
    else:
        md, parse_resp = await _parse_with_cache(
            client,
            file_path,
            pdf_bytes,
            file_name,
            parse_model,
            rate_limiter,
        )
    return md, parse_resp


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
    markdown_cache: bool = False,
    markdown_cache_bucket: Optional[str] = None,
    markdown_cache_prefix: str = _DEFAULT_CACHE_PREFIX,
) -> FieldExtractionResult:
    """
    Async extract specific fields from a document (human-in-the-loop re-extraction).

    Use this when a user uploads a new document to correct/update specific fields.
    No classification is performed - the document type is already known.

    Args:
        file: File path, bytes, or dict with content
        document_type: Known document type (e.g., "Project Simulation Report")
        fields: List of field names to extract
        file_name: Optional file name (required if file is bytes)
        parse_model: Model for parsing
        extract_model: Model for extraction
        existing_markdown: Pre-parsed markdown content (skip parsing if provided)
        rate_limit: Max requests per second

    Returns:
        FieldExtractionResult with extracted field values

    Example:
        result = await extract_specific_fields_async(
            file=Path("updated_simulation.pdf"),
            document_type="Project Simulation Report",
            fields=["performance_ratio_pct", "total_pv_energy_mwh"]
        )
    """
    try:
        from landingai_ade.lib import pydantic_to_json_schema
    except ImportError as e:
        raise RuntimeError(_MISSING_LANDINGAI_MSG) from e

    top_level = _get_top_level_for_document_type(document_type)
    top_level_str = top_level.value if top_level else "unknown"
    file_name = _resolve_file_name(file, file_name)

    print(f"\nExtracting specific fields from {file_name} (type: {document_type})")

    try:
        full_schema_cls = _validate_document_type_fields(document_type, fields)

        client = _get_async_client()
        rate_limiter_obj = _get_rate_limiter(rate_limit, 1.0)

        markdown_content, parse_response = await _parse_or_use_existing(
            client,
            file,
            file_name,
            parse_model,
            rate_limiter_obj,
            existing_markdown,
            markdown_cache,
            markdown_cache_bucket,
            markdown_cache_prefix,
        )

        partial_schema_cls = _create_partial_schema(full_schema_cls, fields)
        schema = pydantic_to_json_schema(partial_schema_cls)

        raw = await _async_extract(
            client, markdown_content, schema, model=extract_model, rate_limiter=rate_limiter_obj
        )
        extracted = raw.get("extraction", {})
        extracted, ext_meta = normalize_extracted_document(
            document_type,
            extracted,
            raw.get("extraction_metadata"),
        )
        raw["extraction_metadata"] = ext_meta
        _print_extracted_variables(file_name, extracted)

        grounding = _resolve_field_grounding(ext_meta, parse_response)

        return FieldExtractionResult(
            file_name=file_name,
            document_type=document_type,
            top_level_category=top_level_str,
            requested_fields=fields,
            extracted_fields=extracted,
            extraction_metadata=ext_meta,
            field_grounding=grounding,
            success=True,
        )

    except Exception as e:
        return FieldExtractionResult(
            file_name=file_name or "unknown",
            document_type=document_type,
            top_level_category=top_level_str,
            requested_fields=fields,
            extracted_fields={},
            success=False,
            error=f"{type(e).__name__}: {str(e)}",
        )


def extract_specific_fields(
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
    """Sync wrapper for extract_specific_fields_async."""
    return asyncio.run(
        extract_specific_fields_async(
            file=file,
            document_type=document_type,
            fields=fields,
            file_name=file_name,
            parse_model=parse_model,
            extract_model=extract_model,
            existing_markdown=existing_markdown,
            rate_limit=rate_limit,
        )
    )


async def extract_specific_fields_batch_async(
    files: List[Union[Path, bytes, Dict[str, Any]]],
    document_type: str,
    fields: List[str],
    *,
    file_names: Optional[List[str]] = None,
    parse_model: Optional[str] = None,
    extract_model: Optional[str] = None,
    max_concurrent: int = 5,
    rate_limit: float = 10.0,
    markdown_cache: bool = True,
    markdown_cache_bucket: Optional[str] = "drex-network",
    markdown_cache_prefix: str = _DEFAULT_CACHE_PREFIX,
) -> List[FieldExtractionResult]:
    """
    Async extract specific fields from multiple documents (batch human-in-the-loop).

    Args:
        files: List of files to process
        document_type: Known document type for all files
        fields: List of field names to extract
        file_names: Optional list of file names
        parse_model: Model for parsing
        extract_model: Model for extraction
        max_concurrent: Maximum concurrent requests
        rate_limit: Max requests per second
        markdown_cache: Enable S3 markdown caching
        markdown_cache_bucket: S3 bucket for cache
        markdown_cache_prefix: S3 key prefix for cached markdowns

    Returns:
        List of FieldExtractionResult
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    async def process_with_semaphore(file, name, _idx):
        async with semaphore:
            return await extract_specific_fields_async(
                file=file,
                document_type=document_type,
                fields=fields,
                file_name=name,
                parse_model=parse_model,
                extract_model=extract_model,
                rate_limit=rate_limit,
                markdown_cache=markdown_cache,
                markdown_cache_bucket=markdown_cache_bucket,
                markdown_cache_prefix=markdown_cache_prefix,
            )

    tasks = []
    for idx, file in enumerate(files):
        name = file_names[idx] if file_names and idx < len(file_names) else None
        tasks.append(process_with_semaphore(file, name, idx))

    results = await asyncio.gather(*tasks)
    for result in results:
        if result.success and result.extracted_data:
            _print_extracted_variables(result.file_name, result.extracted_data)
    return list(results)


def extract_specific_fields_batch(
    files: List[Union[Path, bytes, Dict[str, Any]]],
    document_type: str,
    fields: List[str],
    *,
    file_names: Optional[List[str]] = None,
    parse_model: Optional[str] = None,
    extract_model: Optional[str] = None,
    max_concurrent: int = 5,
    rate_limit: float = 10.0,
) -> List[FieldExtractionResult]:
    """Sync wrapper for extract_specific_fields_batch_async."""
    return asyncio.run(
        extract_specific_fields_batch_async(
            files=files,
            document_type=document_type,
            fields=fields,
            file_names=file_names,
            parse_model=parse_model,
            extract_model=extract_model,
            max_concurrent=max_concurrent,
            rate_limit=rate_limit,
        )
    )


# =============================================================================
# Function 3: Direct Extraction (No Classification) - Async
# =============================================================================


async def extract_document_direct_async(
    file: Union[Path, bytes, Dict[str, Any]],
    document_type: str,
    *,
    file_name: Optional[str] = None,
    parse_model: Optional[str] = None,
    extract_model: Optional[str] = None,
    existing_markdown: Optional[str] = None,
    rate_limit: float = 10.0,
    markdown_cache: bool = True,
    markdown_cache_bucket: Optional[str] = None,
    markdown_cache_prefix: str = _DEFAULT_CACHE_PREFIX,
) -> DocumentResult:
    """
    Async extract all fields from a document with known type (skip classification).

    Use this when you already know the document type and want to extract
    all fields without running classification.

    Args:
        file: File path, bytes, or dict with content
        document_type: Known document type
        file_name: Optional file name
        parse_model: Model for parsing
        extract_model: Model for extraction
        existing_markdown: Pre-parsed markdown (skip parsing)
        rate_limit: Max requests per second
        markdown_cache: Enable S3 markdown caching
        markdown_cache_bucket: S3 bucket for cache (falls back to env vars)
        markdown_cache_prefix: S3 key prefix for cached markdowns

    Returns:
        DocumentResult with all extracted fields

    Example:
        result = await extract_document_direct_async(
            file=Path("simulation_report.pdf"),
            document_type="Project Simulation Report"
        )
    """
    # Determine top-level category from document type
    top_level = _get_top_level_for_document_type(document_type)
    top_level_str = top_level.value if top_level else "unknown"
    file_name = _resolve_file_name(file, file_name)

    try:
        file_path_obj, _, _ = _resolve_file_input(file, file_name)
        file_path_str = str(file_path_obj) if file_path_obj else None

        # Validate document type
        schema_cls = _resolve_schema_cls(document_type)
        if not schema_cls:
            raise ValueError(
                f"Unknown document type: {document_type}. "
                f"Valid types: {_valid_document_types()}"
            )

        # Setup client and rate limiter
        client = _get_async_client()
        rate_limiter_obj = _get_rate_limiter(rate_limit, 1.0)

        markdown_content, parse_response = await _parse_or_use_existing(
            client,
            file,
            file_name,
            parse_model,
            rate_limiter_obj,
            existing_markdown,
            markdown_cache,
            markdown_cache_bucket,
            markdown_cache_prefix,
        )

        # Extract all fields (no classification)
        print(f"  Extracting: {file_name}")
        extracted, extract_raw = await _async_extract_fields(
            client,
            markdown_content,
            document_type,
            model=extract_model,
            rate_limiter=rate_limiter_obj,
        )

        ext_meta = extract_raw.get("extraction_metadata")
        grounding = _resolve_field_grounding(ext_meta, parse_response)

        return DocumentResult(
            file_name=file_name,
            file_path=file_path_str,
            document_type=document_type,
            top_level_category=top_level_str,
            extracted_data=extracted,
            extraction_metadata=ext_meta,
            field_grounding=grounding,
            success=True,
        )

    except Exception as e:
        return DocumentResult(
            file_name=file_name or "unknown",
            document_type=document_type,
            top_level_category=top_level_str,
            extracted_data={},
            success=False,
            error=f"{type(e).__name__}: {str(e)}",
        )


def extract_document_direct(
    file: Union[Path, bytes, Dict[str, Any]],
    document_type: str,
    *,
    file_name: Optional[str] = None,
    parse_model: Optional[str] = None,
    extract_model: Optional[str] = None,
    existing_markdown: Optional[str] = None,
    rate_limit: float = 10.0,
) -> DocumentResult:
    """Sync wrapper for extract_document_direct_async."""
    return asyncio.run(
        extract_document_direct_async(
            file=file,
            document_type=document_type,
            file_name=file_name,
            parse_model=parse_model,
            extract_model=extract_model,
            existing_markdown=existing_markdown,
            rate_limit=rate_limit,
        )
    )


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
    markdown_cache: bool = True,
    markdown_cache_bucket: Optional[str] = "drex-network",
    markdown_cache_prefix: str = _DEFAULT_CACHE_PREFIX,
) -> Tuple[List[DocumentResult], Optional[ValidatedDocumentResult]]:
    """
    Async batch extract all fields from multiple documents with known type.
    Includes validation to resolve conflicts when multiple documents have different values.

    Args:
        files: List of files to process
        document_type: Known document type for all files
        file_names: Optional list of file names
        parse_model: Model for parsing
        extract_model: Model for extraction
        max_concurrent: Maximum concurrent requests
        rate_limit: Max requests per second
        enable_validation: Whether to run validation layer (default: True)
        validation_model: Model for validation reasoning
        markdown_cache: Enable S3 markdown caching
        markdown_cache_bucket: S3 bucket for cache
        markdown_cache_prefix: S3 key prefix for cached markdowns

    Returns:
        Tuple of (List of DocumentResult, Optional ValidatedDocumentResult)
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    async def process_with_semaphore(file, name, _idx):
        async with semaphore:
            return await extract_document_direct_async(
                file=file,
                document_type=document_type,
                file_name=name,
                parse_model=parse_model,
                extract_model=extract_model,
                rate_limit=rate_limit,
                markdown_cache=markdown_cache,
                markdown_cache_bucket=markdown_cache_bucket,
                markdown_cache_prefix=markdown_cache_prefix,
            )

    tasks = []
    for idx, file in enumerate(files):
        name = file_names[idx] if file_names and idx < len(file_names) else None
        tasks.append(process_with_semaphore(file, name, idx))

    results = await asyncio.gather(*tasks)
    results_list = list(results)

    for result in results_list:
        if result.success and result.extracted_data:
            _print_extracted_variables(result.file_name, result.extracted_data)

    # Run validation if enabled
    validated_result = None
    if enable_validation and len(results_list) > 1:
        successful_results = [r for r in results_list if r.success]
        if len(successful_results) > 1:
            field_names = sorted(
                {
                    field_name
                    for result in successful_results
                    for field_name in result.extracted_data.keys()
                }
            )
            if should_disable_cross_document_validation(document_type, field_names):
                print(
                    "  Skipping validation for "
                    f"{document_type}: additive time-series fields must remain per source document"
                )
                return results_list, None

            top_level = _get_top_level_for_document_type(document_type)
            if top_level:
                validated_dict = validate_batch_results(
                    successful_results,
                    top_level_category=top_level,
                    validation_model=validation_model,
                )
                validated_result = validated_dict.get(document_type)

    return results_list, validated_result


def extract_documents_direct_batch(
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
    """Sync wrapper for extract_documents_direct_batch_async."""
    return asyncio.run(
        extract_documents_direct_batch_async(
            files=files,
            document_type=document_type,
            file_names=file_names,
            parse_model=parse_model,
            extract_model=extract_model,
            max_concurrent=max_concurrent,
            rate_limit=rate_limit,
            enable_validation=enable_validation,
            validation_model=validation_model,
        )
    )


# =============================================================================
# Convenience Functions for API Endpoints
# =============================================================================


def get_supported_categories() -> List[str]:
    """Get list of supported top-level categories."""
    return [cat.value for cat in TopLevelCategory]


def get_document_types_for_category_api(category: str) -> List[str]:
    """
    Get list of document types for a category (API-friendly version).

    Args:
        category: Category value string (e.g., "Company Information")

    Returns:
        List of document type values
    """
    try:
        top_level = TopLevelCategory(category)
    except ValueError:
        raise ValueError(
            f"Unknown category: {category}. "
            f"Valid categories: {[c.value for c in TopLevelCategory]}"
        )

    return CATEGORY_DOCUMENT_TYPES.get(top_level, [])


def get_fields_for_document_type(document_type: str) -> Dict[str, Dict[str, Any]]:
    """Get schema fields for a document type."""
    schema_cls = _resolve_schema_cls(document_type)
    if not schema_cls:
        raise ValueError(f"Unknown document type: {document_type}")
    fields_info = {}

    for field_name, field_info in schema_cls.model_fields.items():
        fields_info[field_name] = {
            "type": str(field_info.annotation),
            "description": field_info.description,
            "required": field_info.is_required(),
        }

    return fields_info


def get_all_schemas_info() -> Dict[str, Dict[str, Any]]:
    """Get information about all available schemas."""
    result = {}
    for category in TopLevelCategory:
        result[category.value] = {}
        doc_types = CATEGORY_DOCUMENT_TYPES.get(category, [])
        for doc_type in doc_types:
            if _resolve_schema_cls(doc_type):
                result[category.value][doc_type] = get_fields_for_document_type(doc_type)
    return result


def parse_top_level_category(category_str: str) -> TopLevelCategory:
    """
    Parse a string to TopLevelCategory enum.

    Args:
        category_str: Category value string (e.g., "Company Information" or "technical")

    Returns:
        TopLevelCategory enum value

    Raises:
        ValueError: If category string is invalid
    """
    # Try direct value match
    try:
        return TopLevelCategory(category_str)
    except ValueError:
        pass

    # Try case-insensitive match
    category_lower = category_str.lower().replace(" ", "_").replace("-", "_")
    for cat in TopLevelCategory:
        if cat.value.lower().replace(" ", "_") == category_lower:
            return cat
        if cat.name.lower() == category_lower:
            return cat

    raise ValueError(
        f"Unknown category: {category_str}. "
        f"Valid categories: {[c.value for c in TopLevelCategory]}"
    )
