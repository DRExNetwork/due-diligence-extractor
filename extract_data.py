#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract structured data from classified documents."""

import sys
import os

# Set UTF-8 encoding without reassigning stdout (causes I/O errors)
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from ddx.extraction.extractor import ExtractionPipeline
from ddx.llm.client import LLMClient


def flatten_extracted_data(extracted_data: dict) -> dict:
    """Flatten nested extracted data structure."""
    flattened = {}

    def flatten_recursive(data: dict, parent_key: str = ""):
        """Recursively flatten nested dictionaries."""
        for key, value in data.items():
            new_key = f"{parent_key}_{key}" if parent_key else key

            if isinstance(value, dict):
                # Check if this is a field entry (has value, reasoning, confidence, etc.)
                if "value" in value or "reasoning" in value or "confidence" in value:
                    flattened[new_key] = {
                        "value": value.get("value", "Not found"),
                        "unit": value.get("unit", ""),
                        "reasoning": value.get("reasoning", ""),
                        "snippet": value.get("snippet", ""),
                        "confidence": value.get("confidence", "low"),
                        "page_reference": value.get("page_reference", ""),
                    }
                else:
                    # Recursively flatten nested sections
                    flatten_recursive(value, new_key)
            elif isinstance(value, list):
                # Handle lists (e.g., Solar Modules array)
                for idx, item in enumerate(value):
                    if isinstance(item, dict):
                        list_key = f"{new_key}_{idx}"
                        flatten_recursive(item, list_key)

    flatten_recursive(extracted_data)
    return flattened


def print_extraction_result(result: dict) -> None:
    """Pretty print an extraction result with reasoning and snippets."""

    file_name = result.get("file_name", "Unknown")
    category = result.get("category", "Unknown")

    print(f"\n{'='*120}")
    print(f"File: {file_name}")
    print(f"{'='*120}")
    print(f"Category: {category}\n")

    if result.get("skipped"):
        print(f"SKIPPED: {result.get('reason')}\n")
        return

    if not result.get("success"):
        print(f"ERROR: {result.get('error')}\n")
        return

    # Print summary
    summary = result.get("extraction_summary", {})
    classification_confidence = result.get("classification_confidence", 0)

    print(f"EXTRACTION SUMMARY")
    print(f"-" * 120)
    print(f"Classification Confidence: {classification_confidence:.1%}")
    print(f"Total Fields:              {summary.get('total_fields', 0)}")
    print(f"Fields Found:              {summary.get('fields_found', 0)}")
    print(f"Completion Rate:           {summary.get('completion_rate', '0%')}")

    confidence = summary.get("confidence_breakdown", {})
    print(f"\nConfidence Breakdown:")
    print(f"  High:   {confidence.get('high', 0)}")
    print(f"  Medium: {confidence.get('medium', 0)}")
    print(f"  Low:    {confidence.get('low', 0)}\n")

    # Print detailed extraction
    extracted_data = result.get("extracted_data", {})
    print(f"EXTRACTED DATA")
    print(f"-" * 120)

    # Group by section
    sections = {}
    for field_name, field_info in extracted_data.items():
        # Extract section name from field name
        parts = field_name.split("_")
        if len(parts) > 1:
            section = "_".join(parts[:-1])
        else:
            section = "General"

        if section not in sections:
            sections[section] = []
        sections[section].append((field_name, field_info))

    for section, fields in sorted(sections.items()):
        print(f"\n[{section.upper()}]")

        for field_name, field_info in fields:
            value = field_info.get("value", "Not found")
            unit = field_info.get("unit", "")
            confidence = field_info.get("confidence", "")
            reasoning = field_info.get("reasoning", "")
            snippet = field_info.get("snippet", "")
            page_ref = field_info.get("page_reference", "")

            # Skip null values and "Not found"
            if (
                value == "Not found in document"
                or value is None
                or value == "Not found"
                or value == "None"
            ):
                continue

            # Clean up field name
            clean_name = field_name.split("_")[-1]

            # Confidence icon
            confidence_icon = (
                "HIGH" if confidence == "high" else "MED" if confidence == "medium" else "LOW"
            )

            print(f"\n  {clean_name}")
            print(f"    Value:        {value} {unit}".strip())
            print(f"    Confidence:   {confidence_icon}")
            print(f"    Reasoning:    {reasoning}")
            if page_ref and page_ref != "Not available":
                print(f"    Location:     {page_ref}")
            if snippet and snippet != "Not found in document":
                if len(snippet) > 120:
                    snippet = snippet[:120] + "..."
                print(f"    Snippet:      {snippet}")

    print(f"\n")


def print_extraction_summary(results: list) -> None:
    """Print overall extraction summary."""

    print(f"\n{'='*120}")
    print(f"EXTRACTION PIPELINE SUMMARY")
    print(f"{'='*120}\n")

    successful = sum(1 for r in results if r.get("success", False))
    skipped = sum(1 for r in results if r.get("skipped", False))
    failed = sum(1 for r in results if not r.get("success", False) and not r.get("skipped", False))
    total = len(results)

    print(f"Total Documents:  {total}")
    if total > 0:
        print(f"Successful:       {successful} ({successful/total*100:.1f}%)")
        print(f"Skipped:          {skipped} ({skipped/total*100:.1f}%)")
        print(f"Failed:           {failed} ({failed/total*100:.1f}%)")
    else:
        print(f"Successful:       0")
        print(f"Skipped:          0")
        print(f"Failed:           0")

    # Overall completion statistics
    total_fields = sum(len(r.get("extracted_data", {})) for r in results if r.get("success", False))
    found_fields = sum(
        sum(
            1
            for field in r.get("extracted_data", {}).values()
            if field.get("value")
            and field.get("value") not in ["Not found in document", "Not found", "None", None]
        )
        for r in results
        if r.get("success", False)
    )

    if total_fields > 0:
        print(f"\nOverall Data Extraction:")
        print(f"  Total Fields Available: {total_fields}")
        print(f"  Fields Extracted:       {found_fields}")
        print(f"  Overall Completion:     {found_fields/total_fields*100:.1f}%")

    # High confidence fields
    high_confidence_count = sum(
        sum(
            1 for field in r.get("extracted_data", {}).values() if field.get("confidence") == "high"
        )
        for r in results
        if r.get("success", False)
    )

    medium_confidence_count = sum(
        sum(
            1
            for field in r.get("extracted_data", {}).values()
            if field.get("confidence") == "medium"
        )
        for r in results
        if r.get("success", False)
    )

    low_confidence_count = sum(
        sum(1 for field in r.get("extracted_data", {}).values() if field.get("confidence") == "low")
        for r in results
        if r.get("success", False)
    )

    print(f"\nConfidence Distribution:")
    print(f"  High Confidence:   {high_confidence_count}")
    print(f"  Medium Confidence: {medium_confidence_count}")
    print(f"  Low Confidence:    {low_confidence_count}")

    # Category breakdown
    category_stats = {}
    for result in results:
        if result.get("success"):
            category = result.get("category", "Unknown")
            if category not in category_stats:
                category_stats[category] = {"count": 0, "fields_found": 0, "total_fields": 0}

            category_stats[category]["count"] += 1
            category_stats[category]["total_fields"] += len(result.get("extracted_data", {}))
            category_stats[category]["fields_found"] += sum(
                1
                for field in result.get("extracted_data", {}).values()
                if field.get("value")
                and field.get("value") not in ["Not found in document", "Not found", "None", None]
            )

    if category_stats:
        print(f"\nExtraction by Category:")
        for category, stats in sorted(category_stats.items()):
            completion = (
                stats["fields_found"] / stats["total_fields"] * 100
                if stats["total_fields"] > 0
                else 0
            )
            print(f"  {category}")
            print(f"    Documents:   {stats['count']}")
            print(f"    Completion:  {completion:.1f}%")

    print(f"\n{'='*120}\n")


def export_to_csv(results: list, output_file: str = "extraction_results.csv") -> None:
    """Export extraction results to CSV format."""
    import csv

    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "File Name",
                "Category",
                "Field Name",
                "Value",
                "Unit",
                "Confidence",
                "Reasoning",
                "Page Reference",
                "Snippet",
            ]
        )

        for result in results:
            if not result.get("success"):
                continue

            file_name = result.get("file_name", "Unknown")
            category = result.get("category", "Unknown")
            extracted_data = result.get("extracted_data", {})

            for field_name, field_info in extracted_data.items():
                value = field_info.get("value", "")
                if value in ["Not found in document", "Not found", "None", None]:
                    continue

                clean_name = field_name.replace("_", " ").title()

                writer.writerow(
                    [
                        file_name,
                        category,
                        clean_name,
                        value,
                        field_info.get("unit", ""),
                        field_info.get("confidence", ""),
                        field_info.get("reasoning", ""),
                        field_info.get("page_reference", ""),
                        field_info.get("snippet", "")[:100],
                    ]
                )

    print(f"CSV export saved: {output_file}")


def main():
    """Run data extraction pipeline."""

    print("\n" + "=" * 120)
    print("DATA EXTRACTION PIPELINE")
    print("=" * 120 + "\n")

    # Initialize pipeline
    llm_client = LLMClient(provider="openai")
    pipeline = ExtractionPipeline(llm_client)

    # Process classification results
    print("Processing classification results...\n")
    results = pipeline.process_results("results.json")

    # Flatten extracted data for all results
    for result in results:
        if result.get("success"):
            extracted_data = result.get("extracted_data", {})
            if extracted_data and "sections" not in str(result).lower():
                # Already flat or has sections key
                pass
            result["extracted_data"] = (
                flatten_extracted_data(extracted_data) if extracted_data else {}
            )

    # Print detailed results
    print("\n" + "=" * 120)
    print("DETAILED EXTRACTION RESULTS")
    print("=" * 120)

    for result in results:
        print_extraction_result(result)

    # Print overall summary
    print_extraction_summary(results)

    # Save extraction results as JSON
    output_file = "extraction_results.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"JSON results saved: {output_file}")

    # Export to CSV
    export_to_csv(results, "extraction_results.csv")

    print(f"\n{'='*120}")
    print(f"Extraction pipeline completed successfully!")
    print(f"{'='*120}\n")


if __name__ == "__main__":
    main()
