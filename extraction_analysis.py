#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract and list all values for correctly classified documents."""

import sys
import os

# Set UTF-8 encoding
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import json
from pathlib import Path
from typing import Dict, List, Any
from collections import defaultdict


def load_json_file(filepath: str) -> Any:
    """Load JSON file safely."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {filepath}: {e}")
        return []


def get_correct_files(results_file: str = "results.json") -> Dict[str, Dict[str, Any]]:
    """Extract only the correctly classified files from results.json."""
    results = load_json_file(results_file)
    correct_files = {}

    for result in results:
        if isinstance(result, dict):
            # Only include files marked as correct
            if result.get("correct") == "yes":
                file_name = result.get("file_name")
                if file_name:
                    correct_files[file_name] = {
                        "category": result.get("category", "Unknown"),
                        "confidence": result.get("confidence", 0),
                    }

    return correct_files


def flatten_value(obj: Any, prefix: str = "") -> Dict[str, Any]:
    """Recursively flatten and extract all values."""
    result = {}

    if isinstance(obj, dict):
        for key, value in obj.items():
            new_key = f"{prefix}_{key}" if prefix else key

            # Check if this looks like a field entry
            if isinstance(value, dict) and (
                "value" in value or "reasoning" in value or "confidence" in value
            ):
                # This is a field entry - extract it
                val = value.get("value", "")

                # Skip "Not found" entries
                if val and val not in ["Not found in document", "Not found", "None", None]:
                    result[new_key] = {
                        "value": val,
                        "unit": value.get("unit", ""),
                        "confidence": value.get("confidence", ""),
                        "reasoning": value.get("reasoning", ""),
                        "page_reference": value.get("page_reference", ""),
                    }
            elif isinstance(value, dict):
                # Recurse into nested dict
                result.update(flatten_value(value, new_key))
            elif isinstance(value, list):
                # Handle lists (e.g., [{"Brand": {...}}, ...])
                for idx, item in enumerate(value):
                    if isinstance(item, dict):
                        result.update(flatten_value(item, f"{new_key}_{idx}"))

    return result


def get_extracted_data_for_file(
    file_name: str, extraction_file: str = "extraction_results.json"
) -> Dict[str, Any]:
    """Get extracted data for a specific file."""
    results = load_json_file(extraction_file)

    for result in results:
        if isinstance(result, dict) and result.get("file_name") == file_name:
            # Get the extracted_data section
            extracted_data = result.get("extracted_data", {})

            # Check if there's a 'sections' key (nested structure)
            if not extracted_data or (
                isinstance(extracted_data, dict)
                and not any(
                    isinstance(v, dict) and ("value" in v or "reasoning" in v)
                    for v in extracted_data.values()
                )
            ):
                # Try looking at the whole result object
                extracted_data = {
                    k: v
                    for k, v in result.items()
                    if k
                    not in [
                        "file_name",
                        "category",
                        "confidence",
                        "reasoning",
                        "correct",
                        "file_path",
                        "key_indicators",
                    ]
                }

            # Flatten the data
            return flatten_value(extracted_data)

    return {}


def main():
    """Extract all values for correct files."""

    print("\n" + "=" * 150)
    print("EXTRACTED VALUES FOR CORRECTLY CLASSIFIED FILES")
    print("=" * 150 + "\n")

    # Load correct files
    correct_files = get_correct_files("results.json")
    print(f"Found {len(correct_files)} correctly classified files\n")

    if not correct_files:
        print("No correctly classified files found!")
        return

    # Organize by category
    by_category = defaultdict(list)
    all_results = {"categories": {}}

    for file_name in sorted(correct_files.keys()):
        category = correct_files[file_name]["category"]
        classification_conf = correct_files[file_name]["confidence"]
        extracted_data = get_extracted_data_for_file(file_name, "extraction_results.json")

        by_category[category].append(
            {
                "file_name": file_name,
                "confidence": classification_conf,
                "extracted_data": extracted_data,
            }
        )

    # Print by category
    for category in sorted(by_category.keys()):
        print(f"\n{'='*150}")
        print(f"CATEGORY: {category}")
        print(f"{'='*150}\n")

        category_data = {"files": {}}

        for file_info in by_category[category]:
            file_name = file_info["file_name"]
            confidence = file_info["confidence"]
            extracted_data = file_info["extracted_data"]

            print(f"\nFile: {file_name}")
            print(
                f"Classification Confidence: {confidence:.1%}"
                if isinstance(confidence, (int, float))
                else f"Classification Confidence: {confidence}"
            )
            print(f"-" * 150)

            file_data = {}

            if not extracted_data:
                print("  [No extracted data found]")
            else:
                for field_name in sorted(extracted_data.keys()):
                    field_info = extracted_data[field_name]
                    value = field_info.get("value", "")
                    unit = field_info.get("unit", "")
                    confidence_level = field_info.get("confidence", "")
                    reasoning = field_info.get("reasoning", "")
                    page_ref = field_info.get("page_reference", "")

                    # Format value with unit
                    display_value = f"{value} {unit}".strip() if unit else value

                    print(f"\n  {field_name}")
                    print(f"    Value:      {display_value}")
                    if confidence_level:
                        print(f"    Confidence: {confidence_level}")
                    if reasoning:
                        print(f"    Reasoning:  {reasoning}")
                    if page_ref and page_ref != "Not available":
                        print(f"    Location:   {page_ref}")

                    # Store in file data
                    file_data[field_name] = {
                        "value": display_value,
                        "confidence": confidence_level,
                        "reasoning": reasoning,
                        "page_reference": page_ref,
                    }

            category_data["files"][file_name] = file_data

        all_results["categories"][category] = category_data

    # Save detailed JSON
    print(f"\n\n{'='*150}")
    print("SAVING RESULTS")
    print(f"{'='*150}\n")

    with open("correct_files_extracted_values.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    print("Saved: correct_files_extracted_values.json")

    print(f"\n{'='*150}")
    print("Complete!")
    print(f"{'='*150}\n")


if __name__ == "__main__":
    main()
