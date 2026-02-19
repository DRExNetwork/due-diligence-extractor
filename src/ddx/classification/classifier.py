#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Dict, Any, Optional, Union
from pathlib import Path
from enum import Enum
import json
from ..llm.client import LLMClient


class DocumentCategory(Enum):
    """Enumeration of all document categories."""

    PROJECT_SIMULATION_REPORT = "Project Simulation Report"
    PROJECT_DATA_EQUIPMENT_SHEETS = (
        "Project Data Main Equipment Sheets (Solar Modules, Inverters, Mounting Structure)"
    )
    PROJECT_BASIC_ENGINEERING = "Project Basic Engineering"
    PROJECT_VISIT_REPORT = "Project Visit Report (Could also be part of Project Basic Engineering)"
    PROJECT_LAYOUT = "Project Layout"
    KMZ_POLIGON = "KMZ Poligon"
    CABLE_SIZING_CALCULATION = "Cable Sizing Calculation Report"
    GROUNDING_SYSTEM_DIAGRAM = "Grounding System"
    UNCATEGORIZED = "Uncategorized Document"


CATEGORY_DESCRIPTIONS = {
    DocumentCategory.PROJECT_SIMULATION_REPORT: "Technical simulation results and performance analysis for the solar project",
    DocumentCategory.PROJECT_DATA_EQUIPMENT_SHEETS: "Equipment specifications including solar modules, inverters, and mounting structures",
    DocumentCategory.PROJECT_BASIC_ENGINEERING: "Fundamental engineering design and technical specifications",
    DocumentCategory.PROJECT_VISIT_REPORT: "Field visit observations and assessment findings",
    DocumentCategory.PROJECT_LAYOUT: "Spatial arrangement and layout diagrams of the project",
    DocumentCategory.KMZ_POLIGON: "Geographic polygon data in KMZ format",
    DocumentCategory.CABLE_SIZING_CALCULATION: "Cable sizing calculations and electrical specifications",
    DocumentCategory.GROUNDING_SYSTEM_DIAGRAM: "Grounding system design and single line diagram",
    DocumentCategory.UNCATEGORIZED: "Documents that do not fit into any of the predefined categories",
}

# OpenAI supported file formats for Assistants API
SUPPORTED_FORMATS = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".json": "application/json",
}


class DocumentClassifier:
    def __init__(self, llm_client: Optional[LLMClient] = None):
        """Initialize the document classifier."""
        self.llm_client = llm_client or LLMClient(provider="openai")
        self.categories = [cat.value for cat in DocumentCategory]

    @staticmethod
    def is_supported_format(file_path: Union[str, Path]) -> bool:
        """Check if file format is supported by OpenAI Assistants API."""
        ext = Path(file_path).suffix.lower()
        return ext in SUPPORTED_FORMATS

    def classify_document(
        self,
        file_path: Union[str, Path],
        file_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Classify a single document using file upload.

        Args:
            file_path: Path to the document file
            file_name: Optional display name for the file

        Returns:
            Dictionary with classification result and confidence
        """
        file_path = Path(file_path)
        file_name = file_name or file_path.name

        # Check if format is supported
        if not self.is_supported_format(file_path):
            ext = file_path.suffix.lower()
            return {
                "file_name": file_name,
                "file_path": str(file_path),
                "error": f"Unsupported file format: {ext}. Supported formats: {', '.join(SUPPORTED_FORMATS.keys())}",
            }

        prompt = self._build_classification_prompt(file_name)

        response = self.llm_client.chat_with_file(
            file_path=file_path, prompt=prompt, response_format={"type": "json_object"}
        )

        print(response)

        result = json.loads(response)
        return result

    def _build_classification_prompt(self, file_name: str) -> str:
        """Build the classification prompt for the LLM."""
        categories_list = "\n".join(
            f"- {cat}: {CATEGORY_DESCRIPTIONS[DocumentCategory(cat)]}" for cat in self.categories
        )

        prompt = f"""You are a document classification expert for solar project due diligence.

File Name: {file_name}

Available Categories:
{categories_list}

Analyze this document and classify it into ONE of the categories above.

Respond with a JSON object containing:
{{
    "category": "The exact category name",
    "confidence": 0.0-1.0,
    "reasoning": "Brief explanation of why this category was chosen",
    "key_indicators": ["indicator1", "indicator2", "indicator3"]
}}

Only respond with valid JSON, no additional text."""

        return prompt

    def _build_classification_prompt_with_uncategorized(self, file_name: str) -> str:
        """
        Build the classification prompt with option to mark as uncategorized.

        This prompt allows the LLM to classify a document as "Uncategorized Document"
        if it doesn't fit any of the predefined categories.
        """
        categories_list = "\n".join(
            f"- {cat}: {CATEGORY_DESCRIPTIONS[DocumentCategory(cat)]}" for cat in self.categories
        )

        uncategorized_desc = CATEGORY_DESCRIPTIONS[DocumentCategory.UNCATEGORIZED]

        prompt = f"""You are a document classification expert for solar project due diligence.

File Name: {file_name}

Available Categories:
{categories_list}

IMPORTANT INSTRUCTIONS:
1. Carefully analyze the document content
2. Match it to ONE of the available categories above if it fits well (confidence > 0.6)
3. If the document does NOT fit any of the predefined categories, classify it as "Uncategorized Document"
4. Only use "Uncategorized Document" if the document is clearly out of scope or doesn't match any category

Uncategorized Category:
- Uncategorized Document: {uncategorized_desc}

Respond with a JSON object containing:
{{
    "category": "The exact category name (or 'Uncategorized Document' if no match)",
    "confidence": 0.0-1.0,
    "reasoning": "Brief explanation of why this category was chosen. If uncategorized, explain why no other category fits.",
    "key_indicators": ["indicator1", "indicator2", "indicator3"],
    "is_uncategorized": true/false
}}

Only respond with valid JSON, no additional text."""

        return prompt

    def _build_multi_classification_prompt(self, file_name: str) -> str:
        """
        Build the multi-category classification prompt.

        This prompt allows the LLM to assign multiple relevant categories to a document,
        while still allowing uncategorization if the document doesn't fit any category.
        """
        categories_list = "\n".join(
            f"- {cat}: {CATEGORY_DESCRIPTIONS[DocumentCategory(cat)]}" for cat in self.categories
        )

        uncategorized_desc = CATEGORY_DESCRIPTIONS[DocumentCategory.UNCATEGORIZED]

        prompt = f"""You are a document classification expert for solar project due diligence.

File Name: {file_name}

Available Categories:
{categories_list}

IMPORTANT INSTRUCTIONS:
1. Carefully analyze the document content
2. Assign ALL categories that apply to this document (not just one)
3. Each assigned category must have a confidence score > 0.5
4. List categories in order of relevance (primary first)
5. If the document does NOT fit ANY of the predefined categories, mark it as "Uncategorized Document"
6. A document can be both categorized AND uncategorized if it's partially out of scope

Uncategorized Category:
- Uncategorized Document: {uncategorized_desc}

Respond with a JSON object containing:
{{
    "primary_category": "The most relevant category name (or 'Uncategorized Document')",
    "categories": [
        {{
            "name": "Category name",
            "confidence": 0.0-1.0,
            "reasoning": "Why this category applies"
        }},
        {{
            "name": "Another category name",
            "confidence": 0.0-1.0,
            "reasoning": "Why this category applies"
        }}
    ],
    "is_uncategorized": true/false,
    "key_indicators": ["indicator1", "indicator2", "indicator3"],
    "overall_summary": "Brief summary of what the document covers"
}}

Only respond with valid JSON, no additional text."""

        return prompt

    def classify_document(
        self,
        file_path: Union[str, Path],
        file_name: Optional[str] = None,
        allow_uncategorized: bool = False,
    ) -> Dict[str, Any]:
        """
        Classify a single document using file upload.

        Args:
            file_path: Path to the document file
            file_name: Optional display name for the file
            allow_uncategorized: If True, allow classification as "Uncategorized Document"

        Returns:
            Dictionary with classification result and confidence
        """
        file_path = Path(file_path)
        file_name = file_name or file_path.name

        # Check if format is supported
        if not self.is_supported_format(file_path):
            ext = file_path.suffix.lower()
            return {
                "file_name": file_name,
                "file_path": str(file_path),
                "error": f"Unsupported file format: {ext}. Supported formats: {', '.join(SUPPORTED_FORMATS.keys())}",
            }

        # Choose prompt based on flag
        if allow_uncategorized:
            prompt = self._build_classification_prompt_with_uncategorized(file_name)
        else:
            prompt = self._build_classification_prompt(file_name)

        response = self.llm_client.chat_with_file(
            file_path=file_path, prompt=prompt, response_format={"type": "json_object"}
        )

        print(response)

        result = json.loads(response)
        return result

    def classify_batch(
        self,
        file_paths: List[Union[str, Path]],
        allow_uncategorized: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Classify multiple documents.

        Args:
            file_paths: List of file paths to classify
            allow_uncategorized: If True, allow classification as "Uncategorized Document"

        Returns:
            List of classification results
        """
        results = []
        for file_path in file_paths:
            try:
                result = self.classify_document(
                    file_path,
                    allow_uncategorized=allow_uncategorized,
                )
                if "error" not in result:
                    result["file_name"] = Path(file_path).name
                    result["file_path"] = str(file_path)
                results.append(result)
            except Exception as e:
                results.append(
                    {
                        "file_name": Path(file_path).name,
                        "file_path": str(file_path),
                        "error": str(e),
                    }
                )
        return results

    def classify_document_with_file_id(
        self,
        file_id: str,
        file_name: str,
        allow_uncategorized: bool = False,
        allow_multiple_categories: bool = False,
    ) -> Dict[str, Any]:
        """
        Classify a document using an already uploaded file ID.

        Args:
            file_id: The ID of the already uploaded file
            file_name: Display name for the file
            allow_uncategorized: If True, allow classification as "Uncategorized Document"
            allow_multiple_categories: If True, allow assigning multiple categories

        Returns:
            Dictionary with classification result and confidence
        """
        # Choose prompt based on flags
        if allow_multiple_categories:
            prompt = self._build_multi_classification_prompt(file_name)
        elif allow_uncategorized:
            prompt = self._build_classification_prompt_with_uncategorized(file_name)
        else:
            prompt = self._build_classification_prompt(file_name)

        response = self.llm_client.chat_with_file_id(
            file_id=file_id,
            prompt=prompt,
            response_format={"type": "json_object"},
        )

        print(response)

        result = json.loads(response)
        result["file_id"] = file_id
        result["file_name"] = file_name
        return result
