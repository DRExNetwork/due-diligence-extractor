import json
import csv
from pathlib import Path
from typing import List, Dict, Any


def extract_classification_results(json_file: str, output_file: str):
    """Convert classification results JSON to CSV."""
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    rows = []

    for item in data:
        file_name = item.get("file_name", "")
        file_path = item.get("file_path", "")

        # Handle error entries
        if "error" in item:
            rows.append(
                {
                    "file_name": file_name,
                    "category": "Error",
                    "confidence": "",
                    "reasoning": item.get("error", ""),
                    "is_uncategorized": False,
                }
            )
        # Handle categorized documents (including uncategorized)
        else:
            category = item.get("category", "")
            is_uncategorized = category == "Uncategorized Document"

            rows.append(
                {
                    "file_name": file_name,
                    "category": category,
                    "confidence": item.get("confidence", ""),
                    "reasoning": item.get("reasoning", ""),
                    "is_uncategorized": is_uncategorized,
                }
            )

    # Write to CSV
    if rows:
        fieldnames = ["file_name", "category", "confidence", "reasoning", "is_uncategorized"]
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"✅ Saved {len(rows)} rows to {output_file}")
    else:
        print(f"⚠️  No data found in {json_file}")


def extract_extraction_results(json_file: str, output_file: str):
    """Convert extraction results JSON to CSV."""
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    rows = []
    for item in data:
        file_name = item.get("file_name", "")

        # Handle different result structures
        if "sections" in item:
            # Structured sections (Solar Modules, Inverter, Mounting Structure)
            for section_name, fields in item["sections"].items():
                if isinstance(fields, dict):
                    for field_name, field_data in fields.items():
                        if isinstance(field_data, dict) and "value" in field_data:
                            rows.append(
                                {
                                    "file_name": file_name,
                                    "section": section_name,
                                    "field": field_name,
                                    "value": field_data.get("value", ""),
                                    "unit": field_data.get("unit", ""),
                                    "confidence": field_data.get("confidence", ""),
                                    "reasoning": field_data.get("reasoning", ""),
                                    "snippet": field_data.get("snippet", ""),
                                    "page_reference": field_data.get("page_reference", ""),
                                }
                            )
                elif isinstance(fields, list):
                    for idx, field_obj in enumerate(fields):
                        for field_name, field_data in field_obj.items():
                            if isinstance(field_data, dict) and "value" in field_data:
                                rows.append(
                                    {
                                        "file_name": file_name,
                                        "section": section_name,
                                        "index": idx,
                                        "field": field_name,
                                        "value": field_data.get("value", ""),
                                        "unit": field_data.get("unit", ""),
                                        "confidence": field_data.get("confidence", ""),
                                        "reasoning": field_data.get("reasoning", ""),
                                        "snippet": field_data.get("snippet", ""),
                                        "page_reference": field_data.get("page_reference", ""),
                                    }
                                )
        else:
            # Flat field structure (Simulation, Grounding)
            for field_name, field_data in item.items():
                if field_name != "file_name" and isinstance(field_data, dict):
                    if "value" in field_data:
                        rows.append(
                            {
                                "file_name": file_name,
                                "field": field_name,
                                "value": field_data.get("value", ""),
                                "unit": field_data.get("unit", ""),
                                "confidence": field_data.get("confidence", ""),
                                "reasoning": field_data.get("reasoning", ""),
                                "snippet": field_data.get("snippet", ""),
                                "page_reference": field_data.get("page_reference", ""),
                            }
                        )

    # Write to CSV
    if rows:
        fieldnames = list(rows[0].keys())
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        print(f"✅ Saved {len(rows)} rows to {output_file}")
    else:
        print(f"⚠️  No data found in {json_file}")


def main():
    """Main conversion function."""
    base_dir = Path("./classification_results")
    output_dir = Path("./csv_exports")
    output_dir.mkdir(exist_ok=True)

    # Convert classification results with uncategorized
    if (base_dir / "results_with_uncategorized.json").exists():
        print("Converting results_with_uncategorized.json...")
        try:
            extract_classification_results(
                str(base_dir / "results_with_uncategorized.json"),
                str(output_dir / "classification_results.csv"),
            )
        except Exception as e:
            print(f"❌ Error: {e}")

    # Convert extraction results
    extraction_file = base_dir.parent / "extraction_results.json"
    if extraction_file.exists():
        print("Converting extraction_results.json...")
        try:
            extract_extraction_results(
                str(extraction_file), str(output_dir / "extraction_results.csv")
            )
        except Exception as e:
            print(f"❌ Error: {e}")
    else:
        print(f"⚠️  extraction_results.json not found")

    print(f"\n✅ All conversions complete! Files saved to {output_dir}/")


if __name__ == "__main__":
    main()
