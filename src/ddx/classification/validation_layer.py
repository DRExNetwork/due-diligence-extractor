"""
Validation Layer for Multi-Source Field Resolution

This module provides reasoning-based validation when the same field has multiple
values extracted from different source files. Uses GPT-5-nano (reasoning model)
to determine which value is most reliable and provides justification.

Output includes:
- Selected value with justification
- Source file name
- Coordinates (bounding box) where the value was found
- Page number
- Evidence image path (if available)

Directory Structure Expected (produced by landing_ai_poc_sdk.py):
    out/
    ├── records/
    │   ├── Company_Information/                    ← Top-level category
    │   │   ├── Certificate_of_Legal_Existence/    ← Document type
    │   │   │   ├── file1.json
    │   │   │   └── file2.json
    │   │   ├── Shareholders_Declaration/
    │   │   │   └── shareholders.json
    │   │   └── Legal_Representative_Appointment/
    │   │       └── legal_rep.json
    │   ├── Technical/
    │   │   ├── Project_Simulation_Report/
    │   │   │   ├── sim1.json
    │   │   │   └── sim2.json
    │   │   └── Project_Layout/
    │   │       └── layout.json
    │   └── errors/
    │       └── failed.json
    ├── markdown/
    │   ├── Company_Information/
    │   │   ├── Certificate_of_Legal_Existence/
    │   │   │   ├── file1.md
    │   │   │   └── file1.parse.json
    │   │   └── ...
    │   └── Technical/
    │       └── ...
    └── validated/                                  ← Output from this script
        ├── Company_Information/
        │   ├── Certificate_of_Legal_Existence/
        │   │   ├── validation_report.json
        │   │   └── final_extraction.json
        │   └── Shareholders_Declaration/
        │       └── final_extraction.json
        └── Technical/
            ├── Project_Simulation_Report/
            │   ├── validation_report.json
            │   └── final_extraction.json
            └── Project_Layout/
                └── final_extraction.json

Validation Logic:
- Validation ONLY happens when multiple files exist in the same document_type folder
- Files in the same document_type folder are assumed to contain the same type of information
- The validator resolves conflicts when the same field has different values across files
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI
from pydantic import BaseModel, Field

# =============================================================================
# Utility Functions
# =============================================================================


def _sanitize_category_name(category: str) -> str:
    """
    Convert a category name to a safe folder name.
    Must match the same logic used in landing_ai_poc_sdk.py.

    Args:
        category: Raw category name (e.g., "Project Simulation Report")

    Returns:
        Sanitized folder name (e.g., "Project_Simulation_Report")
    """
    clean = re.sub(r"\s*\([^)]*\)", "", category)
    clean = re.sub(r"[^\w]+", "_", clean.strip())
    clean = clean.strip("_")
    return clean[:80] or "Unknown_Category"


def _folder_name_to_display(folder_name: str) -> str:
    """
    Convert a folder name back to a display name.

    Args:
        folder_name: Sanitized folder name (e.g., "Project_Simulation_Report")

    Returns:
        Display name (e.g., "Project Simulation Report")
    """
    return folder_name.replace("_", " ")


# =============================================================================
# Data Structures
# =============================================================================


@dataclass
class BoundingBox:
    """Bounding box coordinates (normalized 0-1)."""

    left: float
    top: float
    right: float
    bottom: float

    def to_dict(self) -> Dict[str, float]:
        return {
            "left": self.left,
            "top": self.top,
            "right": self.right,
            "bottom": self.bottom,
        }


@dataclass
class EvidenceLocation:
    """Location evidence for an extracted value."""

    page: int
    box: Optional[BoundingBox] = None
    chunk_id: Optional[str] = None
    image_path: Optional[str] = None


@dataclass
class FieldCandidate:
    """A single candidate value for a field from a specific source file."""

    value: Any
    source_file: str  # Full path to source PDF
    source_filename: str  # Just the filename
    extracted_text: str  # The raw text from markdown that was used for extraction
    confidence: Optional[float] = None  # If available from extraction metadata
    chunk_ids: List[str] = field(default_factory=list)  # Reference chunk IDs
    evidence_locations: List[EvidenceLocation] = field(default_factory=list)  # Coordinates/pages


@dataclass
class FieldConflict:
    """Represents a field with multiple conflicting values from different sources."""

    field_name: str
    field_description: str
    candidates: List[FieldCandidate]
    top_level_category: str
    document_type: str


class LocationInfo(BaseModel):
    """Location information for a value in the source document."""

    page: int = Field(description="Page number (0-indexed)")
    box: Optional[Dict[str, float]] = Field(
        default=None,
        description="Bounding box with left, top, right, bottom (normalized 0-1)",
    )
    chunk_id: Optional[str] = Field(default=None, description="Reference chunk ID")
    image_path: Optional[str] = Field(default=None, description="Path to cropped evidence image")


class ValidatedFieldOutput(BaseModel):
    """Output structure for a single validated field."""

    field_name: str = Field(description="Name of the field")
    value: Any = Field(description="The validated/selected value")
    source_file: str = Field(description="Full path to the source file")
    source_filename: str = Field(description="Filename of the source")
    extracted_text: str = Field(
        default="", description="Raw text extracted from the document that was used for this field"
    )
    locations: List[LocationInfo] = Field(
        default_factory=list,
        description="Locations where this value was found in the document",
    )
    confidence_score: float = Field(
        description="Confidence in the selection (0.0 to 1.0)", ge=0.0, le=1.0
    )
    justification: str = Field(
        description="Detailed reasoning for why this value was selected or validated"
    )
    alternatives: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Other candidate values that were not selected (if any)",
    )
    flags: List[str] = Field(
        default_factory=list,
        description="Any red flags or inconsistencies detected",
    )


class ValidationResult(BaseModel):
    """Result of the validation reasoning process."""

    field_name: str = Field(description="Name of the field being validated")
    selected_value: Any = Field(description="The value selected as most reliable")
    selected_source: str = Field(description="Full path to source file of selected value")
    selected_source_filename: str = Field(description="Filename of the selected source")
    locations: List[LocationInfo] = Field(
        default_factory=list,
        description="Locations where the selected value was found",
    )
    confidence_score: float = Field(
        description="Confidence in the selection (0.0 to 1.0)", ge=0.0, le=1.0
    )
    justification: str = Field(description="Detailed reasoning for why this value was selected")
    alternative_values: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Other candidate values that were not selected",
    )
    flags: List[str] = Field(
        default_factory=list,
        description="Any red flags or inconsistencies detected",
    )


class ValidationReport(BaseModel):
    """Complete validation report for all conflicting fields."""

    top_level_category: str = Field(description="Top-level category (e.g., 'Company Information')")
    top_level_folder: str = Field(description="Folder name for top-level category")
    document_type: str = Field(description="Document type being validated")
    document_type_folder: str = Field(description="Folder name for document type")
    total_fields_validated: int = Field(description="Total number of fields with conflicts")
    total_files_processed: int = Field(
        description="Total number of files processed in this document type"
    )
    source_files: List[str] = Field(
        default_factory=list, description="List of source files processed"
    )
    validations: List[ValidationResult] = Field(
        default_factory=list, description="Validation results for each field"
    )
    overall_confidence: float = Field(
        description="Average confidence across all validations", ge=0.0, le=1.0
    )
    summary: str = Field(description="Summary of the validation process")


class FinalExtractionOutput(BaseModel):
    """Final output structure matching the required format."""

    pdf_path: str = Field(description="Path to the source PDF (or merged sources)")
    top_level_category: str = Field(description="Top-level category")
    top_level_folder: str = Field(description="Folder name for top-level category")
    document_type: str = Field(description="Document type")
    document_type_folder: str = Field(description="Folder name for document type")
    sources: List[str] = Field(default_factory=list, description="List of all source files used")
    extracted: Dict[str, ValidatedFieldOutput] = Field(
        default_factory=dict,
        description="Extracted fields with values, justifications, and locations",
    )
    validation_summary: str = Field(description="Summary of validation process")
    overall_confidence: float = Field(description="Overall confidence score", ge=0.0, le=1.0)


# =============================================================================
# Validation Layer
# =============================================================================


class ValidationLayer:
    """
    Validation layer that uses GPT-5-nano to reason about conflicting field values
    from multiple source files and select the most appropriate one.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-5-nano-2025-08-07",
        base_url: Optional[str] = None,
    ):
        """
        Initialize the validation layer.

        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: Model to use for reasoning (default: gpt-5-nano-2025-08-07)
            base_url: Optional custom base URL for API
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise RuntimeError("Missing OPENAI_API_KEY environment variable.")

        self.model = model
        self.client = OpenAI(api_key=self.api_key, base_url=base_url)

    def _build_reasoning_prompt(self, conflict: FieldConflict) -> str:
        """Build the prompt for the reasoning model."""
        candidates_text_parts = []
        for i, c in enumerate(conflict.candidates):
            location_info = ""
            if c.evidence_locations:
                loc_strs = []
                for loc in c.evidence_locations[:3]:  # Limit to 3 locations
                    loc_str = f"Page {loc.page}"
                    if loc.box:
                        loc_str += f", Box: ({loc.box.left:.3f}, {loc.box.top:.3f}, {loc.box.right:.3f}, {loc.box.bottom:.3f})"
                    loc_strs.append(loc_str)
                location_info = f"\nLocations Found: {'; '.join(loc_strs)}"

            candidates_text_parts.append(
                f"--- Candidate {i + 1} ---\n"
                f"Source File: {c.source_filename}\n"
                f"Full Path: {c.source_file}\n"
                f"Extracted Value: {json.dumps(c.value, ensure_ascii=False)}\n"
                f"Raw Extracted Text:\n```\n{c.extracted_text[:500]}\n```"
                + (f"\nConfidence: {c.confidence}" if c.confidence is not None else "")
                + location_info
            )

        candidates_text = "\n\n".join(candidates_text_parts)

        prompt = f"""You are a technical document validation expert specializing in solar energy project documentation.

## Task
Analyze the following conflicting values for a field extracted from multiple source documents.
Select the most reliable and accurate value, and provide detailed justification.

## Document Classification
- Top-Level Category: {conflict.top_level_category}
- Document Type: {conflict.document_type}

## Field Information
- Field Name: {conflict.field_name}
- Field Description: {conflict.field_description}

## Candidate Values from Different Sources
{candidates_text}

## Instructions
1. Analyze each candidate value and its source context
2. Consider factors like:
   - Completeness and specificity of the extracted text
   - Consistency with expected format/units for this field type
   - Whether the source document type is appropriate for this field
   - Any signs of OCR errors or extraction artifacts
   - Technical plausibility of the values
   - Number of locations where the value appears (more occurrences = higher confidence)
3. Select the most reliable value
4. Provide detailed justification for your selection
5. Note any red flags or inconsistencies found

## Response Format
Respond with a JSON object containing:
- "selected_index": (0-based index of the selected candidate)
- "confidence_score": (0.0 to 1.0, your confidence in this selection)
- "justification": (detailed reasoning for your selection, including why other candidates were rejected)
- "flags": (list of any red flags or concerns identified)

Respond ONLY with the JSON object, no additional text."""

        return prompt

    def _parse_reasoning_response(
        self, response_text: str, conflict: FieldConflict
    ) -> ValidationResult:
        """Parse the model's response into a ValidationResult."""
        try:
            # Try to extract JSON from the response
            response_text = response_text.strip()
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.startswith("```"):
                response_text = response_text[3:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]

            result = json.loads(response_text.strip())

            selected_idx = int(result.get("selected_index", 0))
            if selected_idx < 0 or selected_idx >= len(conflict.candidates):
                selected_idx = 0

            selected_candidate = conflict.candidates[selected_idx]

            # Convert evidence locations to LocationInfo
            locations = [
                LocationInfo(
                    page=loc.page,
                    box=loc.box.to_dict() if loc.box else None,
                    chunk_id=loc.chunk_id,
                    image_path=loc.image_path,
                )
                for loc in selected_candidate.evidence_locations
            ]

            alternative_values = [
                {
                    "value": c.value,
                    "source_file": c.source_file,
                    "source_filename": c.source_filename,
                    "locations": [
                        {
                            "page": loc.page,
                            "box": loc.box.to_dict() if loc.box else None,
                            "chunk_id": loc.chunk_id,
                            "image_path": loc.image_path,
                        }
                        for loc in c.evidence_locations
                    ],
                }
                for i, c in enumerate(conflict.candidates)
                if i != selected_idx
            ]

            return ValidationResult(
                field_name=conflict.field_name,
                selected_value=selected_candidate.value,
                selected_source=selected_candidate.source_file,
                selected_source_filename=selected_candidate.source_filename,
                locations=locations,
                confidence_score=float(result.get("confidence_score", 0.5)),
                justification=str(result.get("justification", "No justification provided")),
                alternative_values=alternative_values,
                flags=result.get("flags", []),
            )

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            # Fallback: select first candidate with low confidence
            first = conflict.candidates[0]
            locations = [
                LocationInfo(
                    page=loc.page,
                    box=loc.box.to_dict() if loc.box else None,
                    chunk_id=loc.chunk_id,
                    image_path=loc.image_path,
                )
                for loc in first.evidence_locations
            ]

            return ValidationResult(
                field_name=conflict.field_name,
                selected_value=first.value,
                selected_source=first.source_file,
                selected_source_filename=first.source_filename,
                locations=locations,
                confidence_score=0.3,
                justification=f"Failed to parse model response: {e}. Defaulting to first candidate.",
                alternative_values=[
                    {
                        "value": c.value,
                        "source_file": c.source_file,
                        "source_filename": c.source_filename,
                    }
                    for c in conflict.candidates[1:]
                ],
                flags=["PARSE_ERROR: Model response could not be parsed"],
            )

    def validate_field(self, conflict: FieldConflict) -> ValidationResult:
        """
        Validate a single field with conflicting values.

        Args:
            conflict: FieldConflict containing all candidate values

        Returns:
            ValidationResult with selected value and justification
        """
        if len(conflict.candidates) == 0:
            raise ValueError("No candidates provided for validation")

        if len(conflict.candidates) == 1:
            # No conflict, return the single value
            candidate = conflict.candidates[0]
            locations = [
                LocationInfo(
                    page=loc.page,
                    box=loc.box.to_dict() if loc.box else None,
                    chunk_id=loc.chunk_id,
                    image_path=loc.image_path,
                )
                for loc in candidate.evidence_locations
            ]

            return ValidationResult(
                field_name=conflict.field_name,
                selected_value=candidate.value,
                selected_source=candidate.source_file,
                selected_source_filename=candidate.source_filename,
                locations=locations,
                confidence_score=1.0,
                justification="Single source value - no conflict resolution needed.",
                alternative_values=[],
                flags=[],
            )

        prompt = self._build_reasoning_prompt(conflict)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert at validating and reconciling data extracted from technical documents. Always respond with valid JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
            )

            response_text = response.choices[0].message.content or ""
            return self._parse_reasoning_response(response_text, conflict)

        except Exception as e:
            # On API error, return first candidate with error flag
            print(f"  API Error: {e}")
            first = conflict.candidates[0]
            locations = [
                LocationInfo(
                    page=loc.page,
                    box=loc.box.to_dict() if loc.box else None,
                    chunk_id=loc.chunk_id,
                    image_path=loc.image_path,
                )
                for loc in first.evidence_locations
            ]

            return ValidationResult(
                field_name=conflict.field_name,
                selected_value=first.value,
                selected_source=first.source_file,
                selected_source_filename=first.source_filename,
                locations=locations,
                confidence_score=0.2,
                justification=f"API error during validation: {e}. Defaulting to first candidate.",
                alternative_values=[
                    {
                        "value": c.value,
                        "source_file": c.source_file,
                        "source_filename": c.source_filename,
                    }
                    for c in conflict.candidates[1:]
                ],
                flags=[f"API_ERROR: {type(e).__name__}: {e}"],
            )

    def validate_all_conflicts(
        self,
        conflicts: List[FieldConflict],
        top_level_category: str,
        document_type: str,
        source_files: List[str],
    ) -> ValidationReport:
        """
        Validate all field conflicts and produce a comprehensive report.

        Args:
            conflicts: List of FieldConflict objects
            top_level_category: Top-level category name
            document_type: Document type name
            source_files: List of all source files in this document type folder

        Returns:
            ValidationReport with all validation results
        """
        validations: List[ValidationResult] = []

        for conflict in conflicts:
            print(f"    Validating field: {conflict.field_name}")
            result = self.validate_field(conflict)
            validations.append(result)

        # Calculate overall confidence
        if validations:
            overall_confidence = sum(v.confidence_score for v in validations) / len(validations)
        else:
            overall_confidence = 1.0

        # Generate summary
        high_confidence = sum(1 for v in validations if v.confidence_score >= 0.8)
        low_confidence = sum(1 for v in validations if v.confidence_score < 0.5)
        total_flags = sum(len(v.flags) for v in validations)

        summary = (
            f"Validated {len(validations)} fields with conflicts from {len(source_files)} files. "
            f"{high_confidence} high confidence selections, "
            f"{low_confidence} low confidence selections. "
            f"{total_flags} total flags/warnings raised."
        )

        return ValidationReport(
            top_level_category=top_level_category,
            top_level_folder=_sanitize_category_name(top_level_category),
            document_type=document_type,
            document_type_folder=_sanitize_category_name(document_type),
            total_fields_validated=len(validations),
            total_files_processed=len(source_files),
            source_files=source_files,
            validations=validations,
            overall_confidence=overall_confidence,
            summary=summary,
        )


# =============================================================================
# Helper Functions for Integration
# =============================================================================


def discover_document_type_folders(records_dir: Path) -> List[Tuple[Path, str, str]]:
    """
    Discover all document type folders in the hierarchical structure.

    Structure: records_dir / top_level_category / document_type /

    Args:
        records_dir: Base records directory (e.g., ./out/records)

    Returns:
        List of tuples: (folder_path, top_level_category_name, document_type_name)
    """
    document_type_folders = []

    if not records_dir.exists():
        return document_type_folders

    # Iterate through top-level category folders
    for top_level_folder in records_dir.iterdir():
        if not top_level_folder.is_dir():
            continue

        # Skip special folders like 'errors'
        if top_level_folder.name.lower() in ("errors", "error", "__pycache__"):
            continue

        top_level_name = _folder_name_to_display(top_level_folder.name)

        # Iterate through document type folders
        for doc_type_folder in top_level_folder.iterdir():
            if not doc_type_folder.is_dir():
                continue

            # Check if folder contains any JSON files
            json_files = list(doc_type_folder.glob("*.json"))
            if json_files:
                doc_type_name = _folder_name_to_display(doc_type_folder.name)
                document_type_folders.append((doc_type_folder, top_level_name, doc_type_name))

    return sorted(document_type_folders, key=lambda x: (x[1], x[2]))


def load_records_from_document_type_folder(
    doc_type_folder: Path,
) -> List[Dict[str, Any]]:
    """
    Load all extraction records from a document type folder.

    Args:
        doc_type_folder: Path to document type folder
            (e.g., ./out/records/Company_Information/Certificate_of_Legal_Existence)

    Returns:
        List of records
    """
    records: List[Dict[str, Any]] = []

    for json_file in sorted(doc_type_folder.glob("*.json")):
        try:
            record = json.loads(json_file.read_text(encoding="utf-8"))
            if isinstance(record, dict):
                records.append(record)
        except Exception as e:
            print(f"    Warning: Failed to load {json_file.name}: {e}")

    return records


def collect_conflicts_from_records(
    records: List[Dict[str, Any]],
    top_level_category: str,
    document_type: str,
    field_descriptions: Dict[str, str],
) -> List[FieldConflict]:
    """
    Collect field conflicts from extraction records of a single document type.

    Args:
        records: List of extraction records (all from same document type)
        top_level_category: Top-level category name
        document_type: Document type name
        field_descriptions: Mapping of field names to their descriptions

    Returns:
        List of FieldConflict objects
    """
    conflicts: List[FieldConflict] = []
    field_candidates: Dict[str, List[FieldCandidate]] = {}

    for rec in records:
        extracted = rec.get("extracted", {})
        extraction_meta = rec.get("extraction_raw", {}).get("extraction_metadata", {})
        pdf_path = rec.get("pdf_path", "unknown")
        pdf_filename = Path(pdf_path).name if pdf_path else "unknown"

        # Load parse.json to get bounding boxes
        parse_json_path = rec.get("parse_json_path")
        parse_data = None
        if parse_json_path and Path(parse_json_path).exists():
            try:
                parse_data = json.loads(Path(parse_json_path).read_text(encoding="utf-8"))
            except Exception as e:
                print(f"    Warning: Failed to load parse.json from {parse_json_path}: {e}")

        for field_name, value in extracted.items():
            if value is None:
                continue

            # Get field metadata - handle both dict and list formats
            field_meta = extraction_meta.get(field_name, {})

            # Handle array fields where metadata is a list of objects
            if isinstance(field_meta, list):
                references = []
                extracted_texts = []
                for item_meta in field_meta:
                    if isinstance(item_meta, dict):
                        item_refs = item_meta.get("references", [])
                        references.extend(item_refs)
                        item_text = item_meta.get("extracted_text") or item_meta.get("value", "")
                        if item_text:
                            extracted_texts.append(str(item_text))

                extracted_text = ", ".join(extracted_texts) if extracted_texts else str(value)
                confidence = None

            elif isinstance(field_meta, dict):
                extracted_text = field_meta.get("extracted_text", str(value))
                references = field_meta.get("references", [])
                confidence = field_meta.get("confidence")
            else:
                extracted_text = str(value)
                references = []
                confidence = None

            # Get evidence locations from parse.json using references
            evidence_locations: List[EvidenceLocation] = []
            if parse_data and references:
                chunk_lookup = {chunk["id"]: chunk for chunk in parse_data.get("chunks", [])}

                for ref_id in references:
                    chunk = chunk_lookup.get(ref_id)
                    if chunk and "grounding" in chunk:
                        grounding = chunk["grounding"]
                        box_data = grounding.get("box")
                        box = None
                        if box_data:
                            box = BoundingBox(
                                left=box_data["left"],
                                top=box_data["top"],
                                right=box_data["right"],
                                bottom=box_data["bottom"],
                            )
                        evidence_locations.append(
                            EvidenceLocation(
                                page=grounding.get("page", 0),
                                box=box,
                                chunk_id=ref_id,
                                image_path=None,
                            )
                        )

            candidate = FieldCandidate(
                value=value,
                source_file=pdf_path,
                source_filename=pdf_filename,
                extracted_text=extracted_text,
                confidence=confidence,
                chunk_ids=references,
                evidence_locations=evidence_locations,
            )

            field_candidates.setdefault(field_name, []).append(candidate)

    # Create conflicts only for fields with multiple different values
    for field_name, candidates in field_candidates.items():
        unique_values = set(json.dumps(c.value, sort_keys=True, default=str) for c in candidates)
        if len(unique_values) > 1:
            conflicts.append(
                FieldConflict(
                    field_name=field_name,
                    field_description=field_descriptions.get(field_name, f"Field: {field_name}"),
                    candidates=candidates,
                    top_level_category=top_level_category,
                    document_type=document_type,
                )
            )

    return conflicts


def build_final_output(
    records: List[Dict[str, Any]],
    top_level_category: str,
    document_type: str,
    validation_report: Optional[ValidationReport],
) -> FinalExtractionOutput:
    """
    Build the final output structure with all fields, justifications, and locations.

    Args:
        records: Original extraction records
        top_level_category: Top-level category name
        document_type: Document type name
        validation_report: Validation report with selected values (if any conflicts)

    Returns:
        FinalExtractionOutput with the required format
    """
    if not records:
        return FinalExtractionOutput(
            pdf_path="",
            top_level_category=top_level_category,
            top_level_folder=_sanitize_category_name(top_level_category),
            document_type=document_type,
            document_type_folder=_sanitize_category_name(document_type),
            sources=[],
            extracted={},
            validation_summary="No records to process",
            overall_confidence=0.0,
        )

    sources = [r.get("pdf_path", "") for r in records]

    # Build lookup of validated fields
    validated_fields: Dict[str, ValidationResult] = {}
    if validation_report:
        validated_fields = {v.field_name: v for v in validation_report.validations}

    # Collect all field names from all records
    all_fields: set = set()
    for r in records:
        all_fields.update(r.get("extracted", {}).keys())

    extracted_output: Dict[str, ValidatedFieldOutput] = {}

    for field_name in sorted(all_fields):
        if field_name in validated_fields:
            # Use validated result
            validation = validated_fields[field_name]

            # Find the selected candidate's extracted text
            extracted_text = ""
            for rec in records:
                if rec.get("pdf_path") == validation.selected_source:
                    extraction_meta = rec.get("extraction_raw", {}).get("extraction_metadata", {})
                    field_meta = extraction_meta.get(field_name, {})

                    if isinstance(field_meta, list):
                        extracted_texts = []
                        for item_meta in field_meta:
                            if isinstance(item_meta, dict):
                                item_text = item_meta.get("extracted_text") or item_meta.get(
                                    "value", ""
                                )
                                if item_text:
                                    extracted_texts.append(str(item_text))
                        extracted_text = ", ".join(extracted_texts)
                    elif isinstance(field_meta, dict):
                        extracted_text = field_meta.get(
                            "extracted_text", str(validation.selected_value)
                        )
                    else:
                        extracted_text = str(validation.selected_value)
                    break

            extracted_output[field_name] = ValidatedFieldOutput(
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
        else:
            # No conflict - find first non-null value
            for rec in records:
                val = rec.get("extracted", {}).get(field_name)
                if val is not None:
                    pdf_path = rec.get("pdf_path", "")
                    pdf_filename = Path(pdf_path).name if pdf_path else "unknown"

                    extraction_meta = rec.get("extraction_raw", {}).get("extraction_metadata", {})
                    field_meta = extraction_meta.get(field_name, {})

                    # Get extracted text
                    extracted_text = ""
                    if isinstance(field_meta, list):
                        extracted_texts = []
                        for item_meta in field_meta:
                            if isinstance(item_meta, dict):
                                item_text = item_meta.get("extracted_text") or item_meta.get(
                                    "value", ""
                                )
                                if item_text:
                                    extracted_texts.append(str(item_text))
                        extracted_text = ", ".join(extracted_texts) if extracted_texts else str(val)
                    elif isinstance(field_meta, dict):
                        extracted_text = field_meta.get("extracted_text", str(val))
                    else:
                        extracted_text = str(val)

                    # Get evidence locations from parse.json
                    locations: List[LocationInfo] = []
                    parse_json_path = rec.get("parse_json_path")
                    if parse_json_path and Path(parse_json_path).exists():
                        try:
                            parse_data = json.loads(
                                Path(parse_json_path).read_text(encoding="utf-8")
                            )

                            references = []
                            if isinstance(field_meta, list):
                                for item_meta in field_meta:
                                    if isinstance(item_meta, dict):
                                        item_refs = item_meta.get("references", [])
                                        references.extend(item_refs)
                            elif isinstance(field_meta, dict):
                                references = field_meta.get("references", [])

                            if references:
                                chunk_lookup = {
                                    chunk["id"]: chunk for chunk in parse_data.get("chunks", [])
                                }
                                for ref_id in references:
                                    chunk = chunk_lookup.get(ref_id)
                                    if chunk and "grounding" in chunk:
                                        grounding = chunk["grounding"]
                                        box_data = grounding.get("box")
                                        locations.append(
                                            LocationInfo(
                                                page=grounding.get("page", 0),
                                                box=box_data,
                                                chunk_id=ref_id,
                                                image_path=None,
                                            )
                                        )
                        except Exception as e:
                            print(f"    Warning: Failed to load locations for {field_name}: {e}")

                    extracted_output[field_name] = ValidatedFieldOutput(
                        field_name=field_name,
                        value=val,
                        source_file=pdf_path,
                        source_filename=pdf_filename,
                        extracted_text=extracted_text,
                        locations=locations,
                        confidence_score=1.0,
                        justification="Single source value - no conflict resolution needed.",
                        alternatives=[],
                        flags=[],
                    )
                    break

    overall_confidence = validation_report.overall_confidence if validation_report else 1.0
    summary = validation_report.summary if validation_report else "No conflicts detected."

    return FinalExtractionOutput(
        pdf_path=sources[0] if len(sources) == 1 else f"[{len(sources)} sources]",
        top_level_category=top_level_category,
        top_level_folder=_sanitize_category_name(top_level_category),
        document_type=document_type,
        document_type_folder=_sanitize_category_name(document_type),
        sources=sources,
        extracted=extracted_output,
        validation_summary=summary,
        overall_confidence=overall_confidence,
    )


def process_document_type_folder(
    doc_type_folder: Path,
    top_level_category: str,
    document_type: str,
    validator: ValidationLayer,
    field_descriptions: Dict[str, str],
    out_base_dir: Path,
) -> Optional[ValidationReport]:
    """
    Process a single document type folder: load records, detect conflicts, validate, and save outputs.

    Args:
        doc_type_folder: Path to document type folder with extraction JSONs
        top_level_category: Top-level category name
        document_type: Document type name
        validator: ValidationLayer instance
        field_descriptions: Field name to description mapping
        out_base_dir: Base output directory for validated results

    Returns:
        ValidationReport if conflicts were found and validated, None otherwise
    """
    records = load_records_from_document_type_folder(doc_type_folder)

    if not records:
        print(f"    No records found")
        return None

    print(f"    Loaded {len(records)} records")

    # Check if validation is needed (only when multiple files exist)
    if len(records) < 2:
        print(f"    Single file - no validation needed")
        # Still create output but skip validation
        final_output = build_final_output(records, top_level_category, document_type, None)

        # Create output folder mirroring input structure
        top_level_folder = _sanitize_category_name(top_level_category)
        doc_type_folder_name = _sanitize_category_name(document_type)
        out_dir = out_base_dir / top_level_folder / doc_type_folder_name
        out_dir.mkdir(parents=True, exist_ok=True)

        out_path = out_dir / "final_extraction.json"
        out_path.write_text(final_output.model_dump_json(indent=2), encoding="utf-8")
        print(f"    Wrote: {out_path}")
        return None

    # Create output folder mirroring input structure
    top_level_folder = _sanitize_category_name(top_level_category)
    doc_type_folder_name = _sanitize_category_name(document_type)
    out_dir = out_base_dir / top_level_folder / doc_type_folder_name
    out_dir.mkdir(parents=True, exist_ok=True)

    # Collect conflicts
    conflicts = collect_conflicts_from_records(
        records, top_level_category, document_type, field_descriptions
    )

    source_files = [r.get("pdf_path", "") for r in records]

    if not conflicts:
        print(f"    No field conflicts detected")
        final_output = build_final_output(records, top_level_category, document_type, None)
        out_path = out_dir / "final_extraction.json"
        out_path.write_text(final_output.model_dump_json(indent=2), encoding="utf-8")
        print(f"    Wrote: {out_path}")
        return None

    print(f"    Found {len(conflicts)} field conflicts to validate")

    # Validate conflicts
    report = validator.validate_all_conflicts(
        conflicts, top_level_category, document_type, source_files
    )

    # Save validation report
    report_path = out_dir / "validation_report.json"
    report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(f"    Wrote: {report_path}")

    # Build and save final extraction
    final_output = build_final_output(records, top_level_category, document_type, report)
    final_path = out_dir / "final_extraction.json"
    final_path.write_text(final_output.model_dump_json(indent=2), encoding="utf-8")
    print(f"    Wrote: {final_path}")

    return report


# =============================================================================
# CLI Entry Point
# =============================================================================


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Validate and reconcile conflicting field values from multiple extraction records.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Directory Structure:
  This script expects records organized hierarchically (as produced by landing_ai_poc_sdk.py):

  records-dir/
  ├── Company_Information/              ← Top-level category
  │   ├── Certificate_of_Legal_Existence/  ← Document type
  │   │   ├── file1.json
  │   │   └── file2.json                ← Validation runs here (2 files)
  │   └── Shareholders_Declaration/
  │       └── shareholders.json          ← No validation (1 file)
  └── Technical/
      ├── Project_Simulation_Report/
      │   ├── sim1.json
      │   └── sim2.json                  ← Validation runs here (2 files)
      └── Project_Layout/
          └── layout.json                ← No validation (1 file)

  Output mirrors this structure:
  
  out/
  ├── Company_Information/
  │   ├── Certificate_of_Legal_Existence/
  │   │   ├── validation_report.json     ← Only if conflicts found
  │   │   └── final_extraction.json
  │   └── Shareholders_Declaration/
  │       └── final_extraction.json
  └── Technical/
      └── ...

Examples:
  # Process all categories and document types
  python validation_layer.py --records-dir ./out_sdk/records --out ./out_sdk/validated

  # Filter by top-level category
  python validation_layer.py --records-dir ./out_sdk/records --top-level-filter Company_Information

  # Filter by document type
  python validation_layer.py --records-dir ./out_sdk/records --doc-type-filter Certificate_of_Legal_Existence
""",
    )
    ap.add_argument(
        "--records-dir",
        type=str,
        required=True,
        help="Base directory containing top_level/doc_type subfolders with extraction JSON files.",
    )
    ap.add_argument(
        "--out",
        type=str,
        default=r".\out_sdk\validated",
        help="Base output directory (creates top_level/doc_type subfolders).",
    )
    ap.add_argument(
        "--model",
        type=str,
        default="gpt-5-nano-2025-08-07",
        help="Model to use for reasoning (default: gpt-5-nano-2025-08-07).",
    )
    ap.add_argument(
        "--top-level-filter",
        type=str,
        default=None,
        help="Only process this top-level category folder (folder name, e.g., 'Company_Information').",
    )
    ap.add_argument(
        "--doc-type-filter",
        type=str,
        default=None,
        help="Only process this document type folder (folder name, e.g., 'Certificate_of_Legal_Existence').",
    )

    args = ap.parse_args()

    records_dir = Path(args.records_dir).expanduser().resolve()
    if not records_dir.exists():
        print(f"❌ Records directory not found: {records_dir}")
        return 1

    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build field descriptions from schemas
    field_descriptions: Dict[str, str] = {}
    try:
        from ddx.classification.landing_ai_poc_sdk2 import PYDANTIC_MODELS

        for model_cls in PYDANTIC_MODELS.values():
            if hasattr(model_cls, "model_fields"):
                for fname, finfo in model_cls.model_fields.items():
                    if finfo.description:
                        field_descriptions[fname] = finfo.description
    except ImportError:
        print("  Warning: Could not import PYDANTIC_MODELS, field descriptions will be limited.")

    print(f"Starting validation with model: {args.model}")
    print(f"Records directory: {records_dir}")
    print(f"Output directory: {out_dir}")

    # Discover document type folders
    doc_type_folders = discover_document_type_folders(records_dir)

    if not doc_type_folders:
        print(f"❌ No document type folders found in {records_dir}")
        return 0

    # Apply filters
    if args.top_level_filter:
        doc_type_folders = [
            (p, tl, dt)
            for p, tl, dt in doc_type_folders
            if _sanitize_category_name(tl) == args.top_level_filter or tl == args.top_level_filter
        ]
        if not doc_type_folders:
            print(f"❌ Top-level category not found: {args.top_level_filter}")
            return 1

    if args.doc_type_filter:
        doc_type_folders = [
            (p, tl, dt)
            for p, tl, dt in doc_type_folders
            if _sanitize_category_name(dt) == args.doc_type_filter or dt == args.doc_type_filter
        ]
        if not doc_type_folders:
            print(f"❌ Document type not found: {args.doc_type_filter}")
            return 1

    print(f"\nFound {len(doc_type_folders)} document type folder(s) to process:")
    for folder_path, top_level, doc_type in doc_type_folders:
        json_count = len(list(folder_path.glob("*.json")))
        print(f"  - {top_level} / {doc_type} ({json_count} files)")

    # Initialize validation layer
    try:
        validator = ValidationLayer(model=args.model)
    except RuntimeError as e:
        print(f"❌ Error: {e}")
        return 1

    # Process each document type folder
    total_validated = 0
    total_skipped = 0

    for folder_path, top_level_category, document_type in doc_type_folders:
        print(f"\n{'='*60}")
        print(f"Processing: {top_level_category} / {document_type}")
        print(f"{'='*60}")

        report = process_document_type_folder(
            doc_type_folder=folder_path,
            top_level_category=top_level_category,
            document_type=document_type,
            validator=validator,
            field_descriptions=field_descriptions,
            out_base_dir=out_dir,
        )

        if report:
            total_validated += 1
        else:
            total_skipped += 1

    print(f"\n{'='*60}")
    print(f"Validation complete!")
    print(f"  Document types processed: {len(doc_type_folders)}")
    print(f"  Document types with validation: {total_validated}")
    print(f"  Document types skipped (single file or no conflicts): {total_skipped}")
    print(f"  Output directory: {out_dir}")
    print(f"{'='*60}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
