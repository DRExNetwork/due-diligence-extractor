"""
Service layer for DDX API endpoints.

Orchestrates S3 downloads, calls extraction_api functions,
and transforms results into API response models.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
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
from ddx.classification.landing_ai_poc_sdk import should_disable_cross_document_validation
from ddx.classification.categories import DocumentType, DOCUMENT_TYPE_PARENT_REQUIREMENT
from ddx.api.equipment_research import run_equipment_research_async
from ddx.utils.token_tracker import track_extraction_metrics

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
    SummaryGenerationRequest,
    SummaryGenerationResponse,
    SummarySectionOutput,
    TeaserNarrativeGenerationRequest,
    TeaserNarrativeGenerationResponse,
    TeaserRenderContent,
)

log = logging.getLogger("ddx.api.services")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truncate_for_log(value: Any, max_len: int = 3000) -> str:
    """Serialize and truncate large payloads for logs."""
    try:
        serialized = json.dumps(value, default=str)
    except Exception:
        serialized = str(value)

    if len(serialized) <= max_len:
        return serialized

    return f"{serialized[:max_len]}...(truncated)"


def _persist_summary_trace(
    request_payload: Dict[str, Any],
    response_payload: Dict[str, Any],
    *,
    status: str,
    error: Optional[str] = None,
) -> None:
    """Persist summary request/response to JSONL for debugging and auditability."""
    trace_path = Path(os.getenv("SUMMARY_TRACE_PATH", "logs/summary-generation-trace.jsonl"))
    if not trace_path.is_absolute():
        trace_path = Path.cwd() / trace_path

    trace_path.parent.mkdir(parents=True, exist_ok=True)

    record: Dict[str, Any] = {
        "timestamp": _utc_now_iso(),
        "status": status,
        "error": error,
        "request": request_payload,
        "response": response_payload,
    }

    with trace_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


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


_RESEARCH_FIELDS: List[str] = [
    "module_bloomberg",
    "module_certificate_evidence",
    "module_test_evidence",
    "inverter_bloomberg",
    "inverter_certificate_evidence",
    "inverter_test_evidence",
]

_UNCATEGORIZED_DOCUMENT_TYPE = "Uncategorized Document"


_UNCATEGORIZED_DOCUMENT_TYPE = "Uncategorized Document"


def _is_equipment_sheets_document_type(document_type: Optional[str]) -> bool:
    if not document_type:
        return False
    if _slug_document_type(document_type) == _slug_document_type(
        DocumentType.PROJECT_DATA_EQUIPMENT_SHEETS.value
    ):
        return True
    # Sub-types (cert/bloomberg evidence) map to equipment sheets for research purposes
    try:
        dt = DocumentType(document_type)
        return (
            DOCUMENT_TYPE_PARENT_REQUIREMENT.get(dt) == DocumentType.PROJECT_DATA_EQUIPMENT_SHEETS
        )
    except ValueError:
        return False


def _get_requirement_document_type(doc_type: str) -> str:
    """Return the canonical requirement document type for NestJS DB lookup.

    Sub-types (Module IEC Certificate, Inverter Bloomberg Evidence, etc.) have no
    independent DB entry and must be resolved to their parent requirement type so
    that NestJS can find the correct row in the requirements table.
    """
    try:
        dt = DocumentType(doc_type)
        parent = DOCUMENT_TYPE_PARENT_REQUIREMENT.get(dt)
        if parent:
            return parent.value
    except ValueError:
        pass
    return doc_type


def _clean_brand(value: Any) -> Optional[str]:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def _extract_equipment_brands(
    extracted_data: Dict[str, Any],
) -> Tuple[Optional[str], Optional[str]]:
    module_brand = _clean_brand(extracted_data.get("module_brand"))
    inverter_brand = _clean_brand(extracted_data.get("inverter_brand"))
    return module_brand, inverter_brand


def _has_meaningful_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return len(value) > 0
    if isinstance(value, dict):
        return any(_has_meaningful_value(v) for v in value.values())
    return True


def _merge_research_into_extracted_data(
    extracted_data: Dict[str, Any], research_payload: Dict[str, Any]
) -> None:
    for field in _RESEARCH_FIELDS:
        if field not in research_payload:
            continue
        incoming = research_payload.get(field)
        existing = extracted_data.get(field)
        if _has_meaningful_value(incoming) or field not in extracted_data or existing is None:
            extracted_data[field] = incoming


def _extract_source_hints_from_result(result: Any) -> Tuple[Optional[str], Optional[str]]:
    source_filename = getattr(result, "file_name", None)
    source_file = getattr(result, "file_path", None) or source_filename
    return source_file, source_filename


async def _resolve_research_payload_for_extracted_data(
    extracted_data: Dict[str, Any],
    cache: Dict[Tuple[str, str], Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    module_brand, inverter_brand = _extract_equipment_brands(extracted_data)
    # Always resolve a payload — even when both brands are missing, so that
    # repeated research fields receive placeholder rows (with known anchors
    # such as standard_code / test_name pre-filled) giving NestJS a variableId
    # for each certificate/test slot that users can later edit or re-trigger.
    cache_key = (module_brand or "", inverter_brand or "")
    print("this is cache key", cache_key)
    print("this is cache", cache)
    if cache_key not in cache:
        cache[cache_key] = await run_equipment_research_async(module_brand, inverter_brand)

    return cache[cache_key]


def _build_research_validated_field_with_source(
    field_name: str,
    value: Any,
    source_file: Optional[str],
    source_filename: Optional[str],
) -> Dict[str, Any]:
    confidence = 0.8 if _has_meaningful_value(value) else 0.0
    resolved_source_filename = source_filename or ""
    resolved_source_file = source_file or resolved_source_filename

    return {
        "field_name": field_name,
        "value": value,
        "source_file": resolved_source_file,
        "source_filename": resolved_source_filename,
        "extracted_text": "",
        "locations": [],
        "confidence_score": confidence,
        "justification": "Latest/current-year web research enrichment for equipment sheets.",
        "alternatives": [],
        "flags": [],
    }


def _enrich_serialized_validated_payload(
    validated_payload: Dict[str, Any],
    research_payload: Dict[str, Any],
    source_file: Optional[str] = None,
    source_filename: Optional[str] = None,
) -> None:
    validated_fields = validated_payload.get("validated_fields")
    can_attach_validated_fields = isinstance(validated_fields, dict) and bool(source_filename)

    if can_attach_validated_fields:
        for field in _RESEARCH_FIELDS:
            if field in research_payload:
                validated_fields[field] = _build_research_validated_field_with_source(
                    field,
                    research_payload.get(field),
                    source_file,
                    source_filename,
                )

    validated_payload["research_data"] = {
        field: research_payload.get(field) for field in _RESEARCH_FIELDS
    }


async def _enrich_bulk_equipment_research(
    processed: List[BulkDocumentResult],
    validated: Optional[Dict[str, Any]],
) -> None:
    cache: Dict[Tuple[str, str], Dict[str, Any]] = {}
    validated_research_by_type: Dict[str, Dict[str, Any]] = {}

    for doc in processed:
        if not doc.success or not _is_equipment_sheets_document_type(doc.document_type):
            continue

        extracted_data = doc.extracted_data or {}
        research_payload = await _resolve_research_payload_for_extracted_data(extracted_data, cache)
        if not research_payload:
            continue

        _merge_research_into_extracted_data(extracted_data, research_payload)
        doc.extracted_data = extracted_data

        if doc.document_type not in validated_research_by_type:
            validated_research_by_type[doc.document_type] = {
                "payload": research_payload,
                "source_file": doc.s3_path or doc.file_name,
                "source_filename": doc.file_name,
            }

    if not validated:
        return

    for doc_type, enrich_payload in validated_research_by_type.items():
        validated_payload = validated.get(doc_type)
        if isinstance(validated_payload, dict):
            _enrich_serialized_validated_payload(
                validated_payload,
                enrich_payload["payload"],
                source_file=enrich_payload.get("source_file"),
                source_filename=enrich_payload.get("source_filename"),
            )


async def _enrich_targeted_equipment_research(
    document_type: str,
    results_list: list,
) -> Optional[Dict[str, Any]]:
    if not _is_equipment_sheets_document_type(document_type):
        return None

    cache: Dict[Tuple[str, str], Dict[str, Any]] = {}
    first_research_payload: Optional[Dict[str, Any]] = None
    first_source_file: Optional[str] = None
    first_source_filename: Optional[str] = None

    for result in results_list:
        if not getattr(result, "success", False):
            continue

        extracted_data = getattr(result, "extracted_data", None)
        if not isinstance(extracted_data, dict):
            continue

        research_payload = await _resolve_research_payload_for_extracted_data(extracted_data, cache)
        print("this is research payload", research_payload)
        if not research_payload:
            continue

        _merge_research_into_extracted_data(extracted_data, research_payload)

        if first_research_payload is None:
            first_research_payload = research_payload
            first_source_file, first_source_filename = _extract_source_hints_from_result(result)

    if first_research_payload is None:
        return None

    return {
        "payload": first_research_payload,
        "source_file": first_source_file,
        "source_filename": first_source_filename,
    }


# =============================================================================
# Summary Generation Service
# =============================================================================


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _build_summary_system_prompt() -> str:
    return (
        "You are an investment analyst generating a structured project summary. "
        "Use only values provided in the input payload. "
        "Do not invent numbers, dates, names, percentages, capacities "
        "Return valid JSON matching the requested schema."
    )


def _build_summary_user_payload(req: SummaryGenerationRequest) -> Dict[str, Any]:
    return {
        "schema_version": "summary_v1",
        "project_id": req.project_id,
        "project_name": req.project_name,
        "language": req.language,
        "template_name": req.template_name,
        "sections": [section.model_dump() for section in req.sections],
        "missing_fields": req.missing_fields,
        "style_reference_markdown": req.style_reference_markdown,
    }


def _build_summary_response_schema() -> Dict[str, Any]:
    return {
        "name": "investment_summary_structured_response",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "sections": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "id": {"type": "string"},
                            "title": {"type": "string"},
                            "order": {"type": "integer"},
                            "narrative_intro": {"type": "string"},
                            "narrative_closing": {"type": "string"},
                            "table_rows": {
                                "type": "array",
                                "items": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "kpis": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "label": {"type": "string"},
                                        "value": {"type": "string"},
                                        "available": {"type": "boolean"},
                                    },
                                    "required": ["label", "value", "available"],
                                },
                            },
                            "bullets": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "source_fields": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": [
                            "id",
                            "title",
                            "order",
                            "narrative_intro",
                            "narrative_closing",
                            "table_rows",
                            "kpis",
                            "bullets",
                            "source_fields",
                        ],
                    },
                },
                "final_summary": {"type": "string"},
            },
            "required": ["sections", "final_summary"],
        },
        "strict": True,
    }


def _build_fallback_summary(
    req: SummaryGenerationRequest, reason: str
) -> SummaryGenerationResponse:
    sections: List[SummarySectionOutput] = []
    total_input_fields = 0
    total_non_empty_values = 0

    for section in req.sections:
        table_rows: List[List[str]] = []
        source_fields: List[str] = []

        for variable in section.variables:
            total_input_fields += 1
            value_str = _safe_str(variable.value)
            if value_str.strip():
                total_non_empty_values += 1

            table_rows.append([variable.label, value_str or "N/A"])
            source_fields.append(variable.field_name)

        sections.append(
            SummarySectionOutput(
                id=section.id,
                title=section.title,
                order=section.order,
                narrative_intro=(
                    f"This section summarizes {section.title.lower()} based on mapped project "
                    "variables received from NestJS."
                ),
                narrative_closing="Further narrative enrichment can be generated by the configured LLM.",
                table_rows=table_rows,
                kpis=[],
                bullets=[],
                source_fields=source_fields,
            )
        )

    completeness = 0.0
    if total_input_fields > 0:
        completeness = round((total_non_empty_values / total_input_fields) * 100, 2)

    return SummaryGenerationResponse(
        generated_at=_utc_now_iso(),
        project_id=req.project_id,
        project_name=req.project_name,
        language=req.language,
        model_version="fallback-rule-based",
        sections=sorted(sections, key=lambda s: s.order),
        final_summary=(
            "Structured summary generated from mapped project variables. "
            "Narrative content uses deterministic fallback mode."
        ),
        data_gaps=req.missing_fields,
        quality_checks={
            "required_sections_present": len(sections) == len(req.sections),
            "input_fields_total": total_input_fields,
            "input_fields_non_empty": total_non_empty_values,
            "completeness_pct": completeness,
            "fallback_reason": reason,
        },
        generation_mode="fallback",
    )


def _generate_summary_with_openai(req: SummaryGenerationRequest) -> SummaryGenerationResponse:
    from openai import OpenAI

    model_name = req.model or os.getenv("SUMMARY_MODEL") or os.getenv("LLM_MODEL")
    model_name = model_name or "gpt-5.4-mini-2026-03-17"

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    client = OpenAI(api_key=api_key)

    system_prompt = _build_summary_system_prompt()
    payload = _build_summary_user_payload(req)

    completion = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    "Generate structured investment summary JSON using this payload:\n"
                    f"{json.dumps(payload, ensure_ascii=False)}"
                ),
            },
        ],
        response_format={
            "type": "json_schema",
            "json_schema": _build_summary_response_schema(),
        },
    )

    content = completion.choices[0].message.content if completion.choices else None
    if not content:
        raise RuntimeError("LLM returned empty response for summary generation")

    content = content.encode("utf-8", errors="ignore").decode("utf-8", errors="ignore").strip()
    parsed = json.loads(content)

    output_sections: List[SummarySectionOutput] = []
    for section in parsed.get("sections", []):
        output_sections.append(
            SummarySectionOutput(
                id=section.get("id", ""),
                title=section.get("title", ""),
                order=section.get("order", 0),
                narrative_intro=section.get("narrative_intro", ""),
                narrative_closing=section.get("narrative_closing"),
                table_rows=section.get("table_rows", []),
                kpis=section.get("kpis", []),
                bullets=section.get("bullets", []),
                source_fields=section.get("source_fields", []),
            )
        )

    total_fields = sum(len(section.variables) for section in req.sections)
    total_non_empty = sum(
        1
        for section in req.sections
        for variable in section.variables
        if _safe_str(variable.value).strip()
    )
    completeness = round((total_non_empty / total_fields) * 100, 2) if total_fields > 0 else 0.0

    return SummaryGenerationResponse(
        generated_at=_utc_now_iso(),
        project_id=req.project_id,
        project_name=req.project_name,
        language=req.language,
        model_version=getattr(completion, "model", model_name),
        sections=sorted(output_sections, key=lambda s: s.order),
        final_summary=parsed.get("final_summary", ""),
        data_gaps=req.missing_fields,
        quality_checks={
            "required_sections_present": len(output_sections) > 0,
            "input_fields_total": total_fields,
            "input_fields_non_empty": total_non_empty,
            "completeness_pct": completeness,
        },
        generation_mode="llm",
    )


async def generate_structured_summary(req: SummaryGenerationRequest) -> SummaryGenerationResponse:
    """
    Summary layer endpoint service.

    Receives structured project variables from NestJS and returns a structured
    summary JSON produced by the AI module.
    """
    request_payload = _build_summary_user_payload(req)

    log.info(
        "Summary generation request: project=%s, sections=%d, template=%s",
        req.project_id,
        len(req.sections),
        req.template_name,
    )
    log.debug("Summary payload: %s", _truncate_for_log(request_payload))

    try:
        result = await asyncio.to_thread(_generate_summary_with_openai, req)
        _persist_summary_trace(
            request_payload,
            result.model_dump(),
            status="success",
        )
        log.info(
            "Summary generation done: project=%s, mode=%s, sections=%d",
            req.project_id,
            result.generation_mode,
            len(result.sections),
        )
        return result
    except Exception as e:
        log.warning(
            "Summary generation falling back to deterministic mode for project=%s: %s",
            req.project_id,
            e,
        )
        fallback_result = _build_fallback_summary(req, str(e))
        _persist_summary_trace(
            request_payload,
            fallback_result.model_dump(),
            status="fallback",
            error=str(e),
        )
        return fallback_result


# =============================================================================
# Teaser Narrative Generation Service
# =============================================================================


_TEASER_RENDER_CONTENT_FIELDS: List[str] = [
    "overview_intro",
    "overview_closing",
    "financial_intro",
    "financial_body",
    "financial_closing",
    "technical_intro",
    "technical_closing",
    "regulatory_intro",
    "regulatory_closing",
    "esg_intro",
    "conclusion",
]

_TEASER_RENDER_FIELD_GUIDANCE: Dict[str, Dict[str, Any]] = {
    "overview_intro": {
        "role": "Open the teaser and frame the project as an investment opportunity.",
        "allowed_topics": [
            "project identity",
            "market context",
            "offtaker sector",
            "country",
            "high-level investment thesis",
            "teaser_data.project.description as context",
        ],
        "forbidden_topics": ["CAPEX detail", "DSCR detail", "PPA detail"],
    },
    "overview_closing": {
        "role": "Bridge from the introduction into the key metrics table and broader diligence path.",
        "allowed_topics": ["high-level technical and investment framing"],
        "forbidden_topics": ["detailed financial metrics", "ESG card-state recap"],
    },
    "financial_intro": {
        "role": "Introduce the financial viability of the project.",
        "allowed_topics": [
            "overall profitability framing",
            "capital discipline",
            "financing readiness",
        ],
        "forbidden_topics": ["equipment detail", "ESG detail"],
    },
    "financial_body": {
        "role": "Interpret CAPEX, IRR, DSCR, invested capital, capital structure, and debt/equity posture.",
        "allowed_topics": ["financial metrics from teaser_data.metrics only"],
        "forbidden_topics": ["technical warranties", "regulatory dates", "ESG states"],
    },
    "financial_closing": {
        "role": "Close the financial section and transition into technical robustness.",
        "allowed_topics": ["connection between financial outcomes and technical design quality"],
        "forbidden_topics": ["new numeric invention"],
    },
    "technical_intro": {
        "role": "Explain equipment quality, technical risk mitigation, and performance assumptions.",
        "allowed_topics": ["brands", "models", "warranties", "degradation", "shading losses"],
        "forbidden_topics": ["CAPEX or debt interpretation"],
    },
    "technical_closing": {
        "role": "Bridge from technical quality to execution and regulatory readiness.",
        "allowed_topics": ["technical de-risking", "implementation readiness"],
        "forbidden_topics": ["ESG card-state recap"],
    },
    "regulatory_intro": {
        "role": "Frame permitting maturity and interconnection readiness before the deterministic feasibility callout.",
        "allowed_topics": ["regulatory maturity", "readiness", "permit posture"],
        "forbidden_topics": ["duplicating the deterministic feasibility summary verbatim"],
    },
    "regulatory_closing": {
        "role": "Short bridge from regulatory readiness into ESG discipline.",
        "allowed_topics": ["execution readiness", "governance transition"],
        "forbidden_topics": ["KPI enumeration"],
    },
    "esg_intro": {
        "role": "Explain why ESG quality matters for this project and sector.",
        "allowed_topics": [
            "ESG importance",
            "IFC-style framing",
            "export or supply-chain relevance when supported by context",
        ],
        "forbidden_topics": ["individual card-state recap as a checklist"],
    },
    "conclusion": {
        "role": "Final investor summary of the full project.",
        "allowed_topics": [
            "integrated investment thesis across technical, financial, regulatory, and ESG strengths"
        ],
        "forbidden_topics": ["raw repetition of every prior metric"],
    },
}


def _count_words(value: str) -> int:
    return len(re.findall(r"\b\w+\b", value or ""))


def _build_teaser_narrative_system_prompt() -> str:
    return (
        "You generate render-ready narrative fragments for an Executive Investment Summary teaser. "
        "Use only the supplied structured teaser data and style reference. "
        "Write entirely in the requested language. "
        "Return valid JSON matching schema_version teaser_render_content_v2 exactly. "
        "When teaser_data.project.description is present, treat it as core project context. "
        "Use it to understand what the project does, who the beneficiary or offtaker is, and what commercial or operational problem the project is solving. "
        "Use that context to make the overview and conclusion more specific. "
        "Do not copy the description verbatim. "
        "You are not writing six broad sections. "
        "You are writing the exact text blocks that NestJS will inject into the HTML template. "
        "Each field has a different job and must be written independently. "
        "Do not merge fields. "
        "Do not mention tables, cards, bullets, or HTML explicitly unless the field guidance asks for a transition toward them. "
        "Do not invent numbers, dates, document states, ESG statuses, sector labels, names, or locations. "
        "Do not output markdown, HTML, tables, or extra keys. "
        "Use the style reference for tone, investor framing, and paragraph role. "
        "Do not copy the style reference text verbatim."
    )


def _build_teaser_narrative_user_payload(
    req: TeaserNarrativeGenerationRequest,
) -> Dict[str, Any]:
    return {
        "schema_version": req.schema_version,
        "project_id": req.project_id,
        "project_name": req.project_name,
        "language": req.language,
        "tone": req.tone,
        "style_reference_markdown": req.style_reference_markdown,
        "field_budgets": req.field_budgets.model_dump(),
        "teaser_data": req.teaser_data,
        "field_guidance": _TEASER_RENDER_FIELD_GUIDANCE,
        "hard_rules": {
            "no_html": True,
            "no_markdown": True,
            "no_tables": True,
            "no_numeric_invention": True,
            "use_only_supplied_facts": True,
            "use_project_description_when_present": True,
            "return_render_ready_content_fields": True,
        },
    }


def _find_overview_boundary_violations(
    req: TeaserNarrativeGenerationRequest,
    overview: str,
) -> List[str]:
    violations: List[str] = []
    normalized = overview or ""

    keyword_checks = [
        (r"\bcapex\b", "financial KPI mention (CAPEX)"),
        (r"\bdscr\b", "financial KPI mention (DSCR)"),
        (r"\birr\b", "financial KPI mention (IRR)"),
        (r"\bppa\b", "financial KPI mention (PPA)"),
        (r"\busd\b", "currency-specific financial detail"),
        (r"\biva\b", "VAT-specific financial detail"),
        # NOTE: 'offtaker' is an explicitly allowed topic in overview_intro (offtaker sector),
        # so we do not block it here. 'equity' and 'debt' remain blocked as capital-structure
        # detail that must stay in the financial section.
        (r"\bequity\b", "capital-structure detail"),
        (r"\bdebt\b", "capital-structure detail"),
    ]

    for pattern, reason in keyword_checks:
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            violations.append(reason)

    regulatory_framework = ((req.teaser_data or {}).get("regulatory") or {}).get(
        "regulatoryFramework"
    )
    if isinstance(regulatory_framework, str) and regulatory_framework.strip():
        if regulatory_framework.strip().lower() in normalized.lower():
            violations.append("raw regulatory framework code in overview")

    if re.search(r"\b\d{1,2}/\d{1,2}/\d{4}\b", normalized):
        violations.append("dated regulatory detail in overview")

    if re.search(
        r"\bavailable hosting capacity\b|\bhosting disponible\b", normalized, flags=re.IGNORECASE
    ):
        violations.append("section 4 hosting-capacity detail in overview")

    if re.search(
        r"\bmissing\b|\bdeliver_later\b|\bno disponible\b", normalized, flags=re.IGNORECASE
    ):
        violations.append("section 5 delivery-state recap in overview")

    return sorted(set(violations))


def _validate_teaser_narrative_section_boundaries(
    req: TeaserNarrativeGenerationRequest,
    parsed: Dict[str, Any],
) -> None:
    content = parsed.get("content") or {}
    # Only validate overview_intro for boundary violations. overview_closing is an intentional
    # bridge into the key metrics table and may gesture at financial framing without including
    # raw figures. Checking both fields combined caused excessive false-positives that triggered
    # the lenient-fallback cascade on every generation attempt.
    overview_violations = _find_overview_boundary_violations(
        req,
        str(content.get("overview_intro") or ""),
    )
    if overview_violations:
        raise RuntimeError(
            "Teaser narrative overview violated section boundary: " + "; ".join(overview_violations)
        )


def _build_teaser_narrative_response_schema() -> Dict[str, Any]:
    content_properties = {
        field_name: {"type": "string"} for field_name in _TEASER_RENDER_CONTENT_FIELDS
    }

    return {
        "name": "project_teaser_render_content_response",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "content": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": content_properties,
                    "required": _TEASER_RENDER_CONTENT_FIELDS,
                }
            },
            "required": ["content"],
        },
        "strict": True,
    }


def _extract_teaser_fallback_context(
    req: TeaserNarrativeGenerationRequest,
) -> Dict[str, Any]:
    teaser_data = req.teaser_data or {}
    project = teaser_data.get("project") or {}
    narrative_context = teaser_data.get("narrativeContext") or {}

    return {
        "teaser_data": teaser_data,
        "project_name": project.get("name") or req.project_name,
        "description": project.get("description"),
        "country": narrative_context.get("country") or "el mercado objetivo",
        "industry": narrative_context.get("industry") or "el sector operativo del offtaker",
        "sector": narrative_context.get("offtakerSector")
        or narrative_context.get("industry")
        or "el sector operativo del offtaker",
        "investment_angle": narrative_context.get("investmentAngle")
        or "las métricas del proyecto y la evidencia documental disponible",
    }


def _build_teaser_narrative_lenient_system_prompt() -> str:
    return (
        "You generate render-ready narrative fragments for an executive investment teaser. "
        "Use only the supplied structured teaser data. "
        "Write every content field entirely in the language specified by request.language; when unspecified, default to Spanish ('es'). "
        "When teaser_data.project.description is present, use it as core project context without copying it verbatim. "
        "Do not invent numbers, dates, document states, ESG statuses, names, or locations. "
        "Do not return HTML, markdown, bullet lists, tables, or extra keys. "
        "Word budgets and section-boundary rules are relaxed for this call; focus on producing readable, investor-facing prose. "
        "Return valid JSON matching the requested schema exactly."
    )


def _generate_teaser_narrative_lenient(
    req: TeaserNarrativeGenerationRequest,
    original_failure_reason: str,
) -> TeaserNarrativeGenerationResponse:
    """
    Lenient LLM call used when the strict call fails validation.
    No word-budget or section-boundary enforcement — just produce clean prose.
    Only called when the LLM itself is reachable; network/auth errors skip this.
    """
    from openai import OpenAI

    model_name = req.model or os.getenv("SUMMARY_MODEL") or os.getenv("LLM_MODEL")
    model_name = model_name or "gpt-5-nano-2025-08-07"

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    client = OpenAI(api_key=api_key)

    user_prompt = (
        "Generate teaser render content JSON using this payload. "
        "The previous strict attempt was rejected for: "
        f"{original_failure_reason}\n\n"
        "Produce clean investor-facing prose. "
        "Ignore word budgets and section boundary enforcement for this call.\n\n"
        f"{json.dumps(_build_teaser_narrative_user_payload(req), ensure_ascii=False)}"
    )

    completion = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": _build_teaser_narrative_lenient_system_prompt()},
            {"role": "user", "content": user_prompt},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": _build_teaser_narrative_response_schema(),
        },
    )

    content = completion.choices[0].message.content if completion.choices else None
    if not content:
        raise RuntimeError("LLM returned empty response in lenient fallback call")

    parsed = json.loads(content)
    render_content = TeaserRenderContent.model_validate(parsed.get("content", {}))

    return TeaserNarrativeGenerationResponse(
        generated_at=_utc_now_iso(),
        project_id=req.project_id,
        project_name=req.project_name,
        language=req.language,
        model_version=getattr(completion, "model", model_name),
        content=render_content,
        quality_checks={
            "within_budget": False,
            "lenient_fallback": True,
            "original_failure_reason": original_failure_reason,
        },
        generation_mode="fallback",
    )


def _build_fallback_teaser_narrative(
    req: TeaserNarrativeGenerationRequest, reason: str
) -> TeaserNarrativeGenerationResponse:
    """
    Last-resort fallback used only when the LLM itself is unreachable
    (no API key, network error, auth failure).
    Returns minimal neutral placeholders — never embeds system names or raw errors.
    """
    context = _extract_teaser_fallback_context(req)
    project_name = context["project_name"]
    has_description = bool(_safe_str(context.get("description")).strip())

    overview_intro = (
        f"{project_name} representa una oportunidad de inversión en infraestructura solar fotovoltaica. "
        "Los parámetros técnicos y financieros del proyecto se encuentran disponibles en las secciones estructuradas del teaser."
    )
    if has_description:
        overview_intro += " La descripción del proyecto aporta contexto operativo adicional para orientar la evaluación."

    return TeaserNarrativeGenerationResponse(
        generated_at=_utc_now_iso(),
        project_id=req.project_id,
        project_name=req.project_name,
        language=req.language,
        model_version="unavailable",
        content=TeaserRenderContent(
            overview_intro=overview_intro,
            overview_closing=(
                "La lectura inicial del proyecto debe complementarse con las métricas, tablas y evidencia documental del teaser."
            ),
            financial_intro=(
                "Los aspectos financieros clave del proyecto se detallan en las métricas estructuradas del teaser."
            ),
            financial_body=(
                "La información de CAPEX, retorno, cobertura y estructura comercial debe revisarse directamente en los indicadores financieros disponibles."
            ),
            financial_closing=(
                "La evaluación financiera debe leerse junto con la configuración técnica y el estado documental del proyecto."
            ),
            technical_intro=(
                "Las especificaciones técnicas y de equipamiento se encuentran disponibles en la tabla de datos del teaser."
            ),
            technical_closing=(
                "La información técnica disponible sirve como base para revisar desempeño, garantías y riesgos de ejecución."
            ),
            regulatory_intro=(
                "El estado regulatorio del proyecto se presenta en el resumen de factibilidad eléctrica estructurado."
            ),
            regulatory_closing=(
                "La evidencia regulatoria debe revisarse junto con los documentos de soporte disponibles."
            ),
            esg_intro=(
                f"La evidencia ESG de {project_name} se resume en las tarjetas de estado del teaser."
            ),
            conclusion=(
                f"{project_name} debe evaluarse a través de las métricas estructuradas del teaser y la evidencia documental disponible."
            ),
        ),
        quality_checks={
            "within_budget": False,
            "service_unavailable": True,
        },
        generation_mode="fallback",
    )


def _validate_teaser_narrative_budgets(
    req: TeaserNarrativeGenerationRequest,
    parsed: Dict[str, Any],
) -> Dict[str, int]:
    field_word_counts: Dict[str, int] = {}
    content = parsed.get("content")

    if not isinstance(content, dict):
        raise RuntimeError("Teaser narrative response did not include a content object")

    for field_name in _TEASER_RENDER_CONTENT_FIELDS:
        text = content.get(field_name, "")
        word_count = _count_words(text)
        field_word_counts[field_name] = word_count

        budget = getattr(req.field_budgets, field_name)
        if word_count < budget.min_words or word_count > budget.max_words:
            raise RuntimeError(
                f"Teaser render content field '{field_name}' violated word budget: {word_count} words, expected {budget.min_words}-{budget.max_words}"
            )

    return field_word_counts


def _generate_teaser_narrative_with_openai(
    req: TeaserNarrativeGenerationRequest,
) -> TeaserNarrativeGenerationResponse:
    from openai import OpenAI

    model_name = req.model or os.getenv("SUMMARY_MODEL") or os.getenv("LLM_MODEL")
    model_name = model_name or "gpt-5-nano-2025-08-07"

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    client = OpenAI(api_key=api_key)

    def request_completion(repair_note: Optional[str] = None):
        user_prompt = (
            "Generate teaser render content JSON using this payload:\n"
            f"{json.dumps(_build_teaser_narrative_user_payload(req), ensure_ascii=False)}"
        )
        if repair_note:
            user_prompt += (
                "\n\nThe previous draft was rejected. Regenerate the full response and obey the section guidance exactly. "
                f"Rejected because: {repair_note}"
            )

        return client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": _build_teaser_narrative_system_prompt()},
                {"role": "user", "content": user_prompt},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": _build_teaser_narrative_response_schema(),
            },
        )

    def parse_and_validate(completion) -> Tuple[Dict[str, Any], Dict[str, int]]:
        content = completion.choices[0].message.content if completion.choices else None
        if not content:
            raise RuntimeError("LLM returned empty response for teaser narrative generation")

        parsed = json.loads(content)
        field_word_counts = _validate_teaser_narrative_budgets(req, parsed)
        _validate_teaser_narrative_section_boundaries(req, parsed)
        return parsed, field_word_counts

    completion = request_completion()

    try:
        parsed, field_word_counts = parse_and_validate(completion)
    except RuntimeError as first_error:
        # One strict repair attempt first; if it still fails validation, raise
        # so the caller can escalate to the lenient path.
        completion = request_completion(str(first_error))
        parsed, field_word_counts = parse_and_validate(completion)

    render_content = TeaserRenderContent.model_validate(parsed.get("content", {}))

    return TeaserNarrativeGenerationResponse(
        generated_at=_utc_now_iso(),
        project_id=req.project_id,
        project_name=req.project_name,
        language=req.language,
        model_version=getattr(completion, "model", model_name),
        content=render_content,
        quality_checks={
            "within_budget": True,
            "field_word_counts": field_word_counts,
        },
        generation_mode="llm",
    )


# Errors that indicate the LLM service itself is unreachable or misconfigured.
# For these we skip the lenient LLM retry and go straight to the neutral placeholder.
_LLM_UNREACHABLE_MARKERS = (
    "OPENAI_API_KEY is not configured",
    "Connection error",
    "AuthenticationError",
    "RateLimitError",
    "APIConnectionError",
)


def _is_llm_unreachable_error(exc: Exception) -> bool:
    msg = str(exc)
    return any(marker in msg for marker in _LLM_UNREACHABLE_MARKERS)


async def generate_teaser_narrative(
    req: TeaserNarrativeGenerationRequest,
) -> TeaserNarrativeGenerationResponse:
    """Generate teaser narrative fields from structured teaser data."""

    request_payload = _build_teaser_narrative_user_payload(req)

    log.info(
        "Teaser narrative request: project=%s, language=%s",
        req.project_id,
        req.language,
    )
    log.debug("Teaser narrative payload: %s", _truncate_for_log(request_payload))

    try:
        result = await asyncio.to_thread(_generate_teaser_narrative_with_openai, req)
        _persist_summary_trace(
            request_payload,
            result.model_dump(),
            status="success",
        )
        log.info(
            "Teaser narrative done: project=%s, mode=%s",
            req.project_id,
            result.generation_mode,
        )
        return result
    except Exception as e:
        log.warning(
            "Teaser narrative strict call failed for project=%s: %s",
            req.project_id,
            e,
        )

        # If the LLM is reachable, try a lenient call (no budget/boundary rules).
        if not _is_llm_unreachable_error(e):
            try:
                lenient_result = await asyncio.to_thread(
                    _generate_teaser_narrative_lenient, req, str(e)
                )
                _persist_summary_trace(
                    request_payload,
                    lenient_result.model_dump(),
                    status="lenient_fallback",
                    error=str(e),
                )
                log.info(
                    "Teaser narrative lenient fallback done: project=%s",
                    req.project_id,
                )
                return lenient_result
            except Exception as lenient_e:
                log.warning(
                    "Teaser narrative lenient call also failed for project=%s: %s",
                    req.project_id,
                    lenient_e,
                )

        # LLM is unreachable or both calls failed — use minimal neutral placeholders.
        fallback_result = _build_fallback_teaser_narrative(req, str(e))
        _persist_summary_trace(
            request_payload,
            fallback_result.model_dump(),
            status="fallback",
            error=str(e),
        )
        return fallback_result


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
    processed = _convert_document_results(
        list(best_per_file.values()), resolved.s3_lookup, project_id=req.project_id
    )
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
        if r.success and r.document_type != _UNCATEGORIZED_DOCUMENT_TYPE:
            all_results.append(r)

    if not batch.validated_results:
        return

    for dt, vr in batch.validated_results.items():
        if dt != _UNCATEGORIZED_DOCUMENT_TYPE:
            all_validated[dt] = vr


def _deduplicate_results(results: List[DocumentResult]) -> Dict[str, DocumentResult]:
    """Keep best result per file — prefer non-uncategorized."""
    best: Dict[str, DocumentResult] = {}
    for r in results:
        existing = best.get(r.file_name)
        if existing is None or r.document_type != _UNCATEGORIZED_DOCUMENT_TYPE:
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
            document_type=_UNCATEGORIZED_DOCUMENT_TYPE,
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

        await _enrich_bulk_equipment_research(processed, validated)

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

    processed = _convert_document_results(
        batch_result.results, resolved.s3_lookup, project_id=req.project_id
    )
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
    # Sub-types (e.g. "Module IEC Certificate") have no independent DB entry in NestJS.
    # Resolve to the parent requirement type so callers can look up the correct DB row.
    response_doc_type = _get_requirement_document_type(doc_type)

    temp_dir = None
    try:
        temp_dir, path_mapping = await download_s3_files(req.s3_paths, req.bucket)
        resolved = ResolvedFiles(req.s3_paths, path_mapping)

        if resolved.is_empty:
            return _build_empty_targeted_response(req, top_level_str, response_doc_type)

        enable_validation = True
        if should_disable_cross_document_validation(doc_type):
            log.info(
                "Targeted completion bypassing validation for doc_type='%s' because it "
                "contains additive repeated variables",
                doc_type,
            )
            enable_validation = False
        elif not req.enable_validation:
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
            enable_validation=enable_validation,
            validation_model=req.validation_model,
        )

        research_bundle = await _enrich_targeted_equipment_research(doc_type, results_list)

        return _assemble_targeted_response(
            req,
            top_level_str,
            response_doc_type,
            results_list,
            validated_result,
            resolved,
            research_payload=research_bundle["payload"] if research_bundle else None,
            research_source_file=research_bundle.get("source_file") if research_bundle else None,
            research_source_filename=(
                research_bundle.get("source_filename") if research_bundle else None
            ),
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
    research_payload: Optional[Dict[str, Any]] = None,
    research_source_file: Optional[str] = None,
    research_source_filename: Optional[str] = None,
) -> TargetedCompletionResponse:
    """Convert extraction results into targeted response."""
    individual = []
    for r in results_list:
        # Log extraction metrics for successful extractions
        if r.success and r.api_metadata:
            log.info(
                "Extracted document | file=%s | doc_type=%s | metadata=%s",
                r.file_name,
                r.document_type,
                r.api_metadata,
            )

        individual.append(
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
        )

    consolidated = _serialize_targeted_validated_result(validated_result)
    if consolidated and research_payload:
        _enrich_serialized_validated_payload(
            consolidated,
            research_payload,
            source_file=research_source_file,
            source_filename=research_source_filename,
        )

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

        if fr.success:
            if fr.api_metadata:
                log.info("Extracted fields | file=%s | metadata=%s", fr.file_name, fr.api_metadata)
            if fr.extracted_fields:
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
    project_id: Optional[str] = None,
) -> List[BulkDocumentResult]:
    """Convert internal DocumentResult list to API BulkDocumentResult list."""
    bulk_results = []
    for r in results:
        # Log extraction metrics for successful extractions
        if r.success:
            log.info(
                "Document extraction completed | file=%s | doc_type=%s | api_metadata=%s",
                r.file_name,
                r.document_type,
                r.api_metadata,
            )

            # Track token consumption if project_id is provided
            if project_id and r.api_metadata:
                _extract_and_track_metadata(project_id, r)

        bulk_results.append(
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
        )
    return bulk_results


def _extract_and_track_metadata(project_id: str, document_result: DocumentResult) -> None:
    """Extract metadata from DocumentResult and track token usage."""
    try:
        metadata = document_result.api_metadata
        if not metadata:
            return

        # Handle both string and object representations of metadata
        if isinstance(metadata, str):
            # Try to parse metadata string if it's a Metadata repr
            import re
            match = re.search(r"credit_usage=(\d+\.?\d*)", str(metadata))
            credit_usage = float(match.group(1)) if match else None

            match = re.search(r"duration_ms=(\d+)", str(metadata))
            duration_ms = int(match.group(1)) if match else None

            match = re.search(r"job_id='([^']+)'", str(metadata))
            job_id = match.group(1) if match else None
        else:
            # Assume it's an object with attributes
            credit_usage = getattr(metadata, "credit_usage", None)
            duration_ms = getattr(metadata, "duration_ms", None)
            job_id = getattr(metadata, "job_id", None)

        track_extraction_metrics(
            project_id=project_id,
            file_name=document_result.file_name,
            document_type=document_result.document_type,
            credit_usage=credit_usage,
            duration_ms=duration_ms,
            job_id=job_id,
            success=True,
        )
    except Exception as e:
        log.warning(f"Failed to track metadata for {document_result.file_name}: {e}")


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
