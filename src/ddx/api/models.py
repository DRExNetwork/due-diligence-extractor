"""
Request and Response models for the DDX API endpoints.

Three interaction types:
  Type 1 - Bulk Ingestion (unknown requirement, unknown value)
  Type 2 - Targeted Completion (known requirement, unknown value)
  Type 3 - Validation/Correction (known requirement, known value)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


# =============================================================================
# Grounding / Location Models
# =============================================================================


class GroundingBox(BaseModel):
    """Normalized bounding box for a chunk on a page (values 0.0–1.0)."""

    l: float = Field(..., description="Left edge (0.0–1.0)")
    t: float = Field(..., description="Top edge (0.0–1.0)")
    r: float = Field(..., description="Right edge (0.0–1.0)")
    b: float = Field(..., description="Bottom edge (0.0–1.0)")


class FieldLocation(BaseModel):
    """
    Resolved source location for an extracted field value.

    Maps an extraction_metadata reference (chunk ID) to its physical
    position in the original document.
    """

    chunk_id: str = Field(..., description="Chunk ID from the parse response")
    page: int = Field(..., description="0-indexed page number in the source document")
    bounding_box: GroundingBox = Field(..., description="Normalized bounding box on the page")
    chunk_type: Optional[str] = Field(
        None, description="Chunk type: 'text', 'table', 'figure', 'marginalia'"
    )


# =============================================================================
# Shared / Common Models
# =============================================================================


class S3FileReference(BaseModel):
    """Reference to a file stored in S3."""

    s3_path: str = Field(..., description="S3 object key (e.g., 'projects/abc/doc.pdf')")
    file_name: Optional[str] = Field(None, description="Optional display name override")


class ProcessingConfig(BaseModel):
    """Common processing configuration shared across endpoints."""

    parse_model: Optional[str] = Field(
        None, description="Model for PDF parsing (default: dpt-2-latest)"
    )
    extract_model: Optional[str] = Field(
        None, description="Model for field extraction (default: extract-latest)"
    )
    rate_limit: float = Field(10.0, ge=1.0, le=50.0, description="Max API requests per second")


class FieldResultDetail(BaseModel):
    """Detailed result for a single extracted field."""

    value: Any = Field(None, description="The extracted value")
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0, description="Confidence score")
    source_file: Optional[str] = Field(None, description="Source file the value was extracted from")
    extracted_text: Optional[str] = Field(None, description="Raw text from which value was derived")
    evidence: Optional[List[Dict[str, Any]]] = Field(
        None, description="Evidence locations (page, bbox)"
    )
    validation_status: Optional[str] = Field(
        None, description="Validation status: 'match', 'mismatch', 'uncertain', or None"
    )


class DocumentProcessingError(BaseModel):
    """Error detail for a failed document."""

    file_name: str
    error_type: str
    error_message: str


# =============================================================================
# Type 1: Bulk Ingestion — Request & Response
# =============================================================================


class BulkIngestionRequest(BaseModel):
    """
    Type 1 — Unknown requirement, unknown value.

    User uploads documents without specifying requirement.
    AI classifies and extracts everything.
    """

    s3_paths: List[str] = Field(
        ...,
        min_length=1,
        description="List of S3 object keys to process",
    )
    bucket: Optional[str] = Field(None, description="S3 bucket name (overrides env default)")
    project_id: str = Field("default_project", description="Project identifier for grouping")
    top_level_category: Optional[str] = Field(
        None,
        description=(
            "Optional top-level category hint to narrow classification scope. "
            "If not provided, documents will be classified across ALL categories. "
            "Valid values: 'Company Information', 'Company Financials', 'Financial', "
            "'Company Experience', 'Technical', 'ESG', 'Permits', 'Legal', 'Regulatory'"
        ),
    )
    max_concurrent: int = Field(5, ge=1, le=20, description="Maximum concurrent processing tasks")
    enable_validation: bool = Field(
        True, description="Resolve conflicts when multiple docs classify as same type"
    )
    validation_model: str = Field(
        "gpt-5-nano-2025-08-07", description="Model for conflict resolution reasoning"
    )
    config: ProcessingConfig = Field(default_factory=ProcessingConfig)

    @field_validator("s3_paths")
    @classmethod
    def _validate_s3_paths(cls, v):
        if not v:
            raise ValueError("s3_paths must not be empty")
        return v


class BulkDocumentResult(BaseModel):
    """Result for a single document in bulk processing."""

    file_name: str
    s3_path: Optional[str] = None
    document_type: str
    top_level_category: str
    extracted_data: Dict[str, Any]
    extraction_metadata: Optional[Dict[str, Any]] = None
    field_grounding: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Resolved source locations per field. "
            "Maps field_name -> list of FieldLocation objects. "
            "For array fields, maps field_name -> list of dicts (one per array element) "
            "where each dict maps sub-field -> list of FieldLocation objects."
        ),
    )
    success: bool = True
    error: Optional[str] = None


class BulkIngestionResponse(BaseModel):
    """Response for Type 1 — Bulk Ingestion."""

    project_id: str
    total_documents: int
    successful: int
    failed: int
    processed_documents: List[BulkDocumentResult]
    validated_results: Optional[Dict[str, Any]] = Field(
        None,
        description="Conflict-resolved results grouped by document type (when validation enabled)",
    )
    classification_summary: Dict[str, int] = Field(
        default_factory=dict,
        description="Count of documents per document type",
    )
    errors: List[DocumentProcessingError] = Field(default_factory=list)


# =============================================================================
# Type 2: Targeted Completion — Request & Response
# =============================================================================


class TargetedCompletionRequest(BaseModel):
    """
    Type 2 — Known requirement, unknown value.

    User uploads documents for a specific requirement/document type.
    AI skips classification and extracts all variables for that type.
    """

    s3_paths: List[str] = Field(
        ...,
        min_length=1,
        description="List of S3 object keys to process",
    )
    bucket: Optional[str] = Field(None, description="S3 bucket name (overrides env default)")
    document_type: str = Field(
        ...,
        description=(
            "The known document type/requirement. "
            "e.g., 'Project Simulation Report', 'Financial Statements', etc."
        ),
    )
    project_id: str = Field("default_project", description="Project identifier")
    max_concurrent: int = Field(5, ge=1, le=20, description="Maximum concurrent processing tasks")
    enable_validation: bool = Field(
        True,
        description=(
            "Validation flag for compatibility. Type 2 always enforces validation "
            "and returns consolidated_result when available."
        ),
    )
    validation_model: str = Field(
        "gpt-5-nano-2025-08-07", description="Model for conflict resolution"
    )
    config: ProcessingConfig = Field(default_factory=ProcessingConfig)

    @field_validator("s3_paths")
    @classmethod
    def _validate_s3_paths(cls, v):
        if not v:
            raise ValueError("s3_paths must not be empty")
        return v


class TargetedDocumentResult(BaseModel):
    """Result for a single document in targeted completion."""

    file_name: str
    s3_path: Optional[str] = None
    document_type: str
    top_level_category: str
    extracted_data: Dict[str, Any]
    extraction_metadata: Optional[Dict[str, Any]] = None
    field_grounding: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Resolved source locations per field. "
            "Maps field_name -> list of FieldLocation objects."
        ),
    )
    success: bool = True
    error: Optional[str] = None


class TargetedCompletionResponse(BaseModel):
    """Response for Type 2 — Targeted Completion."""

    document_type: str
    top_level_category: str
    project_id: str
    total_documents: int
    successful: int
    failed: int
    individual_results: List[TargetedDocumentResult]
    consolidated_result: Optional[Dict[str, Any]] = Field(
        None,
        description="Merged/validated result across all files (when validation enabled)",
    )
    extraction_metadata: Optional[Dict[str, Any]] = None
    errors: List[DocumentProcessingError] = Field(default_factory=list)


# =============================================================================
# Type 3: Validation / Correction — Request & Response
# =============================================================================


class ValidationCorrectionRequest(BaseModel):
    """
    Type 3 — Known requirement, known value.

    User uploads document(s) for a specific variable within a known requirement.
    AI extracts ONLY the targeted fields and optionally validates against expected values.
    """

    s3_paths: List[str] = Field(
        ...,
        min_length=1,
        max_length=5,
        description="S3 object key(s) — typically a single file, max 5 for cross-validation",
    )
    bucket: Optional[str] = Field(None, description="S3 bucket name (overrides env default)")
    document_type: str = Field(
        ...,
        description="The known document type/requirement context",
    )
    target_fields: List[str] = Field(
        ...,
        min_length=1,
        description="Specific field names to extract (e.g., ['performance_ratio_pct', 'total_pv_energy_mwh'])",
    )
    expected_values: Optional[Dict[str, Any]] = Field(
        None,
        description="Expected values for validation comparison (field_name -> expected_value)",
    )
    project_id: str = Field("default_project", description="Project identifier")
    config: ProcessingConfig = Field(default_factory=ProcessingConfig)

    @field_validator("s3_paths")
    @classmethod
    def _validate_s3_paths(cls, v):
        if not v:
            raise ValueError("s3_paths must not be empty")
        return v

    @field_validator("target_fields")
    @classmethod
    def _validate_target_fields(cls, v):
        if not v:
            raise ValueError("target_fields must not be empty")
        return v


class FieldValidationResult(BaseModel):
    """Result for a single field in validation/correction."""

    field_name: str
    value: Any = None
    confidence: Optional[float] = None
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    grounding: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Resolved source locations (page, bounding_box) for this field",
    )
    extracted_text: Optional[str] = None
    validation_status: Optional[str] = Field(
        None,
        description="'match', 'mismatch', or 'uncertain' — only present when expected_values provided",
    )
    expected_value: Optional[Any] = Field(None, description="The expected value (if provided)")
    source_file: Optional[str] = None


class ValidationCorrectionResponse(BaseModel):
    """Response for Type 3 — Validation/Correction."""

    document_type: str
    top_level_category: str
    project_id: str
    requested_fields: List[str]
    extracted_fields: Dict[str, FieldValidationResult]
    overall_validation_status: Optional[str] = Field(
        None,
        description="'all_match', 'some_mismatch', 'all_mismatch', or None if no expected values",
    )
    file_results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Per-file extraction details when multiple files provided",
    )
    errors: List[DocumentProcessingError] = Field(default_factory=list)


# =============================================================================
# Summary Generation — Request & Response
# =============================================================================


class SummaryVariableInput(BaseModel):
    """Input variable sent by NestJS for summary generation."""

    field_name: str
    label: str
    value: Any = None
    value_type: Optional[str] = None
    state: Optional[str] = None
    mapped: Optional[bool] = None
    category: Optional[str] = None


class SummarySectionInput(BaseModel):
    """Section payload sent by NestJS."""

    id: str
    title: str
    order: int
    variables: List[SummaryVariableInput] = Field(default_factory=list)
    hints: Optional[Dict[str, Any]] = None


class SummaryGenerationRequest(BaseModel):
    """Request contract for structured investment summary generation."""

    project_id: str
    project_name: str
    language: str = Field("en", description="Output language code")
    template_name: str = Field("investment_summary_v1", description="Target summary template name")
    sections: List[SummarySectionInput] = Field(
        ...,
        min_length=1,
        description="Ordered summary sections with mapped variables",
    )
    missing_fields: List[Dict[str, Any]] = Field(default_factory=list)
    style_reference_markdown: Optional[str] = Field(
        None,
        description="Optional style reference markdown for tone/structure guidance",
    )
    html_template: Optional[str] = Field(
        None,
        description="Optional HTML template string used downstream by renderer",
    )
    model: Optional[str] = Field(None, description="Optional model override for summary generation")


class SummarySectionOutput(BaseModel):
    """Structured output for one summary section."""

    id: str
    title: str
    order: int
    narrative_intro: str
    narrative_closing: Optional[str] = None
    table_rows: List[List[str]] = Field(default_factory=list)
    kpis: List[Dict[str, Any]] = Field(default_factory=list)
    bullets: List[str] = Field(default_factory=list)
    source_fields: List[str] = Field(default_factory=list)


class SummaryGenerationResponse(BaseModel):
    """Structured summary response consumed by NestJS and renderer."""

    schema_version: str = "summary_v1"
    status: str = "success"
    generated_at: str
    project_id: str
    project_name: str
    language: str
    model_version: str
    sections: List[SummarySectionOutput]
    final_summary: str
    data_gaps: List[Dict[str, Any]] = Field(default_factory=list)
    quality_checks: Dict[str, Any] = Field(default_factory=dict)
    generation_mode: str = Field(
        "llm",
        description="llm when generated by model, fallback when deterministic fallback is used",
    )


# =============================================================================
# Schema Discovery Models
# =============================================================================


class CategoryInfo(BaseModel):
    """Information about a top-level category."""

    name: str
    document_types: List[str]
    document_count: int


class DocumentTypeInfo(BaseModel):
    """Information about a document type and its fields."""

    name: str
    top_level_category: str
    fields: Dict[str, Dict[str, Any]]
    field_count: int


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str
    supported_categories: List[str]
    total_document_types: int
    timestamp: str
