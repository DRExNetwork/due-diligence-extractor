#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract structured data from classified documents."""

from __future__ import annotations
import json
import sys
import io
from typing import List, Dict, Any, Optional
from pathlib import Path
from enum import Enum

from ..llm.client import LLMClient


class ExtractionTemplates:
    """Extraction templates for each document category."""

    PROJECT_SIMULATION_REPORT = {
        "section": "Simulation Overview",
        "fields": [
            {
                "name": "Annual Specific Photovoltaic Power Output",
                "unit": "kWh/kWp",
                "required": True,
                "example": "1348 kWh/kWp",
            },
            {
                "name": "Total photovoltaic energy output",
                "unit": "GWh or MWh",
                "required": True,
                "example": "1.35 GWh or 1349 MWh",
            },
            {"name": "Performance ratio", "unit": "%", "required": True, "example": "78.8%"},
            {"name": "Air temperature", "unit": "°C", "required": False, "example": "23.7°C"},
            {
                "name": "Total photovoltaic power output",
                "unit": "GWp or MWp",
                "required": True,
                "example": "10 GWp or 10000 MWp",
            },
            {"name": "Shadow loss", "unit": "%", "required": False, "example": "1%"},
        ],
        "monthly_statistics": [
            "PVOUT Specific Daily average (Wh/kWp)",
            "PVOUT Total Monthly sum (GWh or MWh)",
            "PR (%)",
        ],
    }

    PROJECT_DATA_EQUIPMENT_SHEETS = {
        "sections": {
            "Solar Modules": [
                {"name": "Brand", "required": True, "example": "JA Solar"},
                {"name": "Model", "required": True, "example": "JAM72S30-540/MR"},
                {"name": "Capacity", "unit": "Wdc", "required": True, "example": "540 Wdc"},
                {"name": "Efficiency", "unit": "%", "required": True, "example": "20.9%"},
                {
                    "name": "Dimensions",
                    "unit": "mm",
                    "required": False,
                    "example": "2279 x 1134 mm",
                },
                {
                    "name": "Technical Warranty",
                    "unit": "years",
                    "required": True,
                    "example": "12 years",
                },
                {
                    "name": "Linear Degradation Warranty",
                    "unit": "years",
                    "required": True,
                    "example": "25 years",
                },
                {
                    "name": "Certificates",
                    "required": False,
                    "note": "IEC 61215, IEC 61730, PID test, IEC 62716, IEC 61701",
                },
            ],
            "Inverter": [
                {"name": "Brand", "required": True, "example": "Huawei"},
                {"name": "Model", "required": True, "example": "SUN2000-100KTL-M1"},
                {"name": "AC Capacity", "unit": "kW AC", "required": True, "example": "100 kW"},
                {"name": "DC Capacity", "unit": "kW DC", "required": True, "example": "120 kW"},
                {"name": "Efficiency", "unit": "%", "required": True, "example": "98.6%"},
                {"name": "Vppt Range", "unit": "V", "required": False, "example": "480–850V"},
                {"name": "Ippt Range", "unit": "A", "required": False, "example": "5-20 A"},
                {"name": "Type", "required": True, "example": "On grid, Off grid, Hybrid"},
                {
                    "name": "Technical Warranty",
                    "unit": "years",
                    "required": True,
                    "example": "10 years",
                },
                {
                    "name": "Certificates",
                    "required": False,
                    "note": "IEC 62109, IEC 61727, IEC 61000",
                },
            ],
            "Mounting Structure": [
                {
                    "name": "Structure Type",
                    "required": True,
                    "example": "Anodized aluminum structure, coplanar, land mounting",
                },
                {
                    "name": "Material",
                    "required": True,
                    "example": "Anodized Aluminum, Hot deep Galvanized",
                },
                {
                    "name": "Structural warranty against corrosion",
                    "unit": "years",
                    "required": False,
                    "example": "15 years",
                },
            ],
        }
    }

    PROJECT_BASIC_ENGINEERING = {
        "sections": {
            "Electrical Parameters": [
                {
                    "name": "Type of System",
                    "required": True,
                    "example": "three-phase 3F, one-phase 1F",
                },
                {"name": "Voltage Mains", "unit": "V", "required": True, "example": "220, 440"},
                {
                    "name": "Description of the load",
                    "required": True,
                    "example": "Industrial load, commercial load, motors",
                },
                {"name": "Load Capacity", "unit": "kW", "required": True, "example": "300 kW"},
                {
                    "name": "Annual Load Consumed Energy",
                    "unit": "kWh",
                    "required": True,
                    "example": "1000 kWh",
                },
            ],
            "Technology Sizing": [
                {
                    "name": "Nominal Capacity",
                    "unit": "kW or MW",
                    "required": True,
                    "example": "1500 kW or 1.5 MW",
                },
                {
                    "name": "Peak Capacity",
                    "unit": "kWp or MWp",
                    "required": True,
                    "example": "3500 kWp or 3.5 MWp",
                },
                {"name": "Solar Modules Quantity", "required": True, "example": "8504 units"},
                {"name": "Inverters Quantity", "required": True, "example": "20 units"},
                {"name": "Strings per Inverter", "required": False, "example": "5"},
                {
                    "name": "Solar Module Orientation",
                    "required": False,
                    "example": "Southeast, 15° tilt",
                },
            ],
            "Cable Sizing": [
                {
                    "name": "Sizing",
                    "unit": "mm² or AWG",
                    "required": False,
                    "example": "35 mm² or 10 AWG",
                },
                {"name": "Type", "required": False, "example": "XLPE type"},
                {"name": "Voltage Drop", "unit": "%", "required": False, "example": "2.9%"},
                {"name": "Installation", "required": False, "example": "underground installation"},
                {"name": "Total Length", "unit": "m", "required": False, "example": "134,500 m"},
            ],
            "Grounding Criteria": [
                {
                    "name": "Type of system",
                    "required": False,
                    "example": "TT system with 3 grounding rods",
                },
                {
                    "name": "Resistance Value",
                    "unit": "Ohm",
                    "required": False,
                    "example": "3.8 Ohm",
                },
            ],
        }
    }

    PROJECT_VISIT_REPORT = {
        "sections": {
            "Site Characteristics": [
                {
                    "name": "Description",
                    "required": True,
                    "example": "Site with vehicle access, no obstructions, slope < 5%",
                },
                {
                    "name": "Area for projects installation",
                    "unit": "m²",
                    "required": True,
                    "example": "1350 m²",
                },
                {
                    "name": "Location of area available for installation",
                    "required": True,
                    "example": "Rooftop, Land, floating",
                },
            ]
        }
    }

    PROJECT_LAYOUT = {
        "sections": {
            "Technology Sizing": [
                {
                    "name": "Nominal Capacity",
                    "unit": "kW or MW",
                    "required": True,
                    "example": "1500 kW or 1.5 MW",
                },
                {
                    "name": "Peak Capacity",
                    "unit": "kWp or MWp",
                    "required": True,
                    "example": "3500 kWp or 3.5 MWp",
                },
                {"name": "Solar Modules Quantity", "required": True, "example": "8504 units"},
                {"name": "Inverters Quantity", "required": True, "example": "20 units"},
                {"name": "Strings per Inverter", "required": False, "example": "5"},
                {
                    "name": "Solar Module Orientation",
                    "required": False,
                    "example": "Southeast, 15° tilt",
                },
            ]
        }
    }

    GROUNDING_SYSTEM = {
        "sections": {
            "Grounding Criteria": [
                {
                    "name": "Type of system",
                    "required": True,
                    "example": "TT system with 3 grounding rods",
                },
                {"name": "Resistance Value", "unit": "Ohm", "required": True, "example": "3.8 Ohm"},
            ]
        }
    }

    CABLE_SIZING = {
        "sections": {
            "Cable Sizing": [
                {
                    "name": "Sizing",
                    "unit": "mm² or AWG",
                    "required": True,
                    "example": "35 mm² or 10 AWG",
                },
                {"name": "Type", "required": True, "example": "XLPE type"},
                {"name": "Voltage Drop", "unit": "%", "required": True, "example": "2.9%"},
                {"name": "Installation", "required": True, "example": "underground installation"},
                {"name": "Total Length", "unit": "m", "required": True, "example": "134,500 m"},
            ]
        }
    }


class DataExtractor:
    """Extract structured data from classified documents."""

    CATEGORY_TO_TEMPLATE = {
        "Project Simulation Report": ExtractionTemplates.PROJECT_SIMULATION_REPORT,
        "Project Data Main Equipment Sheets (Solar Modules, Inverters, Mounting Structure)": ExtractionTemplates.PROJECT_DATA_EQUIPMENT_SHEETS,
        "Project Basic Engineering": ExtractionTemplates.PROJECT_BASIC_ENGINEERING,
        "Project Visit Report": ExtractionTemplates.PROJECT_VISIT_REPORT,
        "Project Layout": ExtractionTemplates.PROJECT_LAYOUT,
        "Grounding System in the Single Line Diagram Report": ExtractionTemplates.GROUNDING_SYSTEM,
        "Cable Sizing Calculation Report": ExtractionTemplates.CABLE_SIZING,
    }

    def __init__(self, llm_client: Optional[LLMClient] = None):
        """Initialize extractor."""
        self.llm_client = llm_client or LLMClient(provider="openai")

    def extract_from_file(
        self,
        file_id: str,
        category: str,
    ) -> Dict[str, Any]:
        """
        Extract structured data from a classified document.

        Args:
            file_id: OpenAI file ID
            category: Document category

        Returns:
            Extracted data dictionary with reasoning and snippets
        """
        template = self.CATEGORY_TO_TEMPLATE.get(category)

        if not template:
            return {
                "file_id": file_id,
                "category": category,
                "error": f"No extraction template for category: {category}",
            }

        # Build extraction prompt
        prompt = self._build_extraction_prompt(category, template)

        # Call LLM with file
        try:
            response = self.llm_client.chat_with_file_id(
                file_id=file_id, prompt=prompt, response_format={"type": "json_object"}
            )

            extracted_data = json.loads(response)

            print(extracted_data)

            # Process and structure the response
            structured_data = self._structure_extraction_response(extracted_data)

            return {
                "file_id": file_id,
                "category": category,
                "extracted_data": structured_data,
                "success": True,
                "extraction_summary": self._generate_summary(structured_data),
            }
        except Exception as e:
            return {"file_id": file_id, "category": category, "error": str(e), "success": False}

    def _build_extraction_prompt(self, category: str, template: Dict[str, Any]) -> str:
        """Build extraction prompt based on category and template."""

        template_json = json.dumps(template, indent=2)

        prompt = f"""You are a data extraction expert for solar project due diligence documents.

Document Category: {category}

Your task is to extract the following data from this document in JSON format:

{template_json}

IMPORTANT INSTRUCTIONS:
1. Extract ONLY data that is explicitly mentioned in the document
2. For missing data, use null or "Not found in document"
3. Preserve units exactly as they appear
4. If multiple values exist for one field, list them all
5. For required fields marked as true, prioritize finding them
6. Return valid JSON only, no additional text

For EACH extracted field, provide a JSON object with:
- value: The actual extracted value
- unit: The unit of measurement (if applicable)
- reasoning: Brief explanation of why this value was selected and where it comes from (e.g., "Found in section X on page Y", "Calculated from...", "Inferred from context")
- snippet: The exact text snippet from the document where this data was found (maximum 200 characters)
- confidence: Your confidence level in the extraction (high/medium/low)
  - high: Explicitly stated in document with clear context
  - medium: Found but requires some interpretation
  - low: Inferred from surrounding context or partially found
- page_reference: Page number or section name where found (if available)

Return a JSON object with this structure for each field:

{{
    "field_name": {{
        "value": "extracted_value",
        "unit": "unit_if_applicable_or_empty_string",
        "reasoning": "Detailed explanation of where this came from",
        "snippet": "Exact text from document",
        "confidence": "high|medium|low",
        "page_reference": "Page X or Section Y or Not available"
    }},
    ...
}}

EXAMPLE RESPONSE:
{{
    "Annual Specific Photovoltaic Power Output": {{
        "value": "1348",
        "unit": "kWh/kWp",
        "reasoning": "Found in the Simulation Overview section on page 2, explicitly stated as the annual specific photovoltaic power output",
        "snippet": "Annual Specific Photovoltaic Power Output: 1348 kWh/kWp",
        "confidence": "high",
        "page_reference": "Page 2, Section 3.1"
    }},
    "Performance ratio": {{
        "value": "78.8",
        "unit": "%",
        "reasoning": "Found in the performance summary table in section 3.2",
        "snippet": "Performance Ratio: 78.8%",
        "confidence": "high",
        "page_reference": "Page 3, Table 1"
    }}
}}

Only respond with valid JSON, no additional text."""

        return prompt

    def _structure_extraction_response(self, raw_response: Dict[str, Any]) -> Dict[str, Any]:
        """
        Structure the raw extraction response with validation.

        Args:
            raw_response: Raw response from LLM

        Returns:
            Structured extraction data
        """
        structured = {}

        for field_name, field_data in raw_response.items():
            if isinstance(field_data, dict):
                structured[field_name] = {
                    "value": field_data.get("value", "Not found"),
                    "unit": field_data.get("unit", ""),
                    "reasoning": field_data.get("reasoning", ""),
                    "snippet": field_data.get("snippet", ""),
                    "confidence": field_data.get("confidence", "low"),
                    "page_reference": field_data.get("page_reference", ""),
                }
            else:
                # Handle cases where response is simple value
                structured[field_name] = {
                    "value": field_data,
                    "unit": "",
                    "reasoning": "Extracted from document",
                    "snippet": "",
                    "confidence": "medium",
                    "page_reference": "",
                }

        return structured

    def _generate_summary(self, structured_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate a summary of extraction quality.

        Args:
            structured_data: Structured extraction response

        Returns:
            Summary statistics
        """
        total_fields = len(structured_data)
        found_fields = sum(
            1
            for field in structured_data.values()
            if field.get("value") and field.get("value") != "Not found in document"
        )
        high_confidence = sum(
            1 for field in structured_data.values() if field.get("confidence") == "high"
        )
        medium_confidence = sum(
            1 for field in structured_data.values() if field.get("confidence") == "medium"
        )
        low_confidence = sum(
            1 for field in structured_data.values() if field.get("confidence") == "low"
        )

        return {
            "total_fields": total_fields,
            "fields_found": found_fields,
            "completion_rate": (
                f"{(found_fields / total_fields * 100):.1f}%" if total_fields > 0 else "0%"
            ),
            "confidence_breakdown": {
                "high": high_confidence,
                "medium": medium_confidence,
                "low": low_confidence,
            },
        }


class ExtractionPipeline:
    """Pipeline to classify and extract from documents."""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        """Initialize pipeline."""
        self.llm_client = llm_client or LLMClient(provider="openai")
        self.extractor = DataExtractor(llm_client)

    def process_results(self, results_file: str = "results.json") -> List[Dict[str, Any]]:
        """
        Process classification results and extract data from uploaded files.

        Reuses already uploaded files from OpenAI by matching filenames.

        Args:
            results_file: Path to results.json from classification

        Returns:
            List of extraction results
        """
        # Load classification results
        results_file = Path(results_file)
        with open(results_file, "r") as f:
            results = json.load(f)

        # Get all uploaded files from OpenAI
        uploaded_files = self.llm_client.list_files(purpose="user_data", limit=1000)

        # Create a mapping of filename to file_id
        file_name_to_id = {}
        for file_obj in uploaded_files:
            file_name_to_id[file_obj["filename"]] = file_obj["id"]

        print(f"\Found {len(uploaded_files)} uploaded files on OpenAI")
        print(f"Processing {len(results)} classification results\n")

        extraction_results = []

        for result in results:
            # Skip errors and uncategorized
            if "error" in result or result.get("category") == "Uncategorized Document":
                extraction_results.append(
                    {
                        "file_name": result.get("file_name", "Unknown"),
                        "category": result.get("category", "Unknown"),
                        "skipped": True,
                        "reason": result.get("error", "Uncategorized or failed classification"),
                    }
                )
                continue

            file_name = result.get("file_name")
            category = result.get("category")

            if not file_name or not category:
                continue

            # Look up file_id from uploaded files
            file_id = file_name_to_id.get(file_name)

            if not file_id:
                extraction_results.append(
                    {
                        "file_name": file_name,
                        "category": category,
                        "skipped": True,
                        "reason": f"File not found in uploaded files on OpenAI",
                    }
                )
                continue

            print(f"Extracting from: {file_name}")

            try:
                # Extract data using existing file_id
                extraction_result = self.extractor.extract_from_file(file_id, category)
                extraction_result["file_name"] = file_name
                extraction_result["file_path"] = result.get("file_path", "")
                extraction_result["classification_confidence"] = result.get("confidence", 0)

                extraction_results.append(extraction_result)

            except Exception as e:
                extraction_results.append(
                    {
                        "file_name": file_name,
                        "category": category,
                        "error": str(e),
                        "success": False,
                    }
                )

        return extraction_results
