#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Analyze classification results with support for single and multi-category classifications."""

import sys
import os
import json
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Any


def load_results(file_path: str = "results.json") -> List[Dict[str, Any]]:
    """Load results from JSON file."""
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def analyze_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Perform static analysis on results using 'correct' field."""

    analysis = {
        "total_files": len(results),
        "correct_classifications": [],
        "incorrect_classifications": [],
        "failed_classifications": [],
        "uncategorized_classifications": [],
        "statistics": {
            "total": 0,
            "correct_count": 0,
            "incorrect_count": 0,
            "failed_count": 0,
            "uncategorized_count": 0,
            "correct_percentage": 0.0,
            "incorrect_percentage": 0.0,
            "failed_percentage": 0.0,
            "uncategorized_percentage": 0.0,
        },
        "categories": defaultdict(
            lambda: {"count": 0, "correct": 0, "incorrect": 0, "uncategorized": 0, "accuracy": 0.0}
        ),
    }

    for result in results:
        analysis["statistics"]["total"] += 1
        file_name = result.get("file_name", "Unknown")

        # Check if there's an error
        if "error" in result:
            analysis["failed_classifications"].append(
                {
                    "file_name": file_name,
                    "file_path": result.get("file_path", "Unknown"),
                    "error": result["error"],
                }
            )
            analysis["statistics"]["failed_count"] += 1
            continue

        # Get classification info
        category = result.get("category", "Unknown")
        confidence = result.get("confidence", 0)
        reasoning = result.get("reasoning", "")
        key_indicators = result.get("key_indicators", [])
        correct = result.get("correct", "unknown")

        # Track by category
        analysis["categories"][category]["count"] += 1

        # Check if uncategorized
        is_uncategorized = category == "Uncategorized Document"

        # Classify as correct, incorrect, or uncategorized
        if is_uncategorized:
            analysis["uncategorized_classifications"].append(
                {
                    "file_name": file_name,
                    "file_path": result.get("file_path", ""),
                    "category": category,
                    "confidence": confidence,
                    "reasoning": reasoning,
                    "key_indicators": key_indicators,
                    "correct": correct,
                }
            )
            analysis["statistics"]["uncategorized_count"] += 1
            analysis["categories"][category]["uncategorized"] += 1

        elif correct == "yes":
            analysis["correct_classifications"].append(
                {
                    "file_name": file_name,
                    "file_path": result.get("file_path", ""),
                    "category": category,
                    "confidence": confidence,
                    "reasoning": reasoning,
                    "key_indicators": key_indicators,
                }
            )
            analysis["statistics"]["correct_count"] += 1
            analysis["categories"][category]["correct"] += 1

        elif correct == "no":
            analysis["incorrect_classifications"].append(
                {
                    "file_name": file_name,
                    "file_path": result.get("file_path", ""),
                    "predicted_category": category,
                    "confidence": confidence,
                    "reasoning": reasoning,
                    "key_indicators": key_indicators,
                }
            )
            analysis["statistics"]["incorrect_count"] += 1
            analysis["categories"][category]["incorrect"] += 1

    # Calculate percentages
    total_processed = (
        analysis["statistics"]["correct_count"]
        + analysis["statistics"]["incorrect_count"]
        + analysis["statistics"]["uncategorized_count"]
    )

    if total_processed > 0:
        analysis["statistics"]["correct_percentage"] = (
            analysis["statistics"]["correct_count"] / total_processed * 100
        )
        analysis["statistics"]["incorrect_percentage"] = (
            analysis["statistics"]["incorrect_count"] / total_processed * 100
        )
        analysis["statistics"]["uncategorized_percentage"] = (
            analysis["statistics"]["uncategorized_count"] / total_processed * 100
        )

    if analysis["statistics"]["total"] > 0:
        analysis["statistics"]["failed_percentage"] = (
            analysis["statistics"]["failed_count"] / analysis["statistics"]["total"] * 100
        )

    # Calculate per-category accuracy
    for category, data in analysis["categories"].items():
        total_in_category = data["correct"] + data["incorrect"]
        if total_in_category > 0:
            data["accuracy"] = data["correct"] / total_in_category

    return analysis


def analyze_multi_category_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze multi-category classification results.

    Handles results where each file can have multiple categories assigned.
    """
    analysis = {
        "total_files": len(results),
        "files_with_multiple_categories": [],
        "files_with_primary_only": [],
        "uncategorized_files": [],
        "failed_files": [],
        "statistics": {
            "total": 0,
            "processed": 0,
            "failed": 0,
            "with_multiple_categories": 0,
            "primary_only": 0,
            "uncategorized": 0,
            "avg_categories_per_file": 0.0,
        },
        "categories": defaultdict(
            lambda: {
                "total_assignments": 0,
                "primary_count": 0,
                "secondary_count": 0,
                "avg_confidence": 0.0,
                "files": [],
            }
        ),
        "category_combinations": defaultdict(int),
    }

    total_categories = 0
    total_confidence = defaultdict(lambda: {"sum": 0.0, "count": 0})

    for result in results:
        analysis["statistics"]["total"] += 1
        file_name = result.get("file_name", "Unknown")
        file_path = result.get("file_path", "")

        # Check if there's an error
        if "error" in result:
            analysis["failed_files"].append(
                {
                    "file_name": file_name,
                    "file_path": file_path,
                    "error": result["error"],
                }
            )
            analysis["statistics"]["failed"] += 1
            continue

        analysis["statistics"]["processed"] += 1

        # Check if uncategorized
        is_uncategorized = result.get("is_uncategorized", False)

        if is_uncategorized:
            analysis["uncategorized_files"].append(
                {
                    "file_name": file_name,
                    "file_path": file_path,
                    "primary_category": result.get("primary_category", "Unknown"),
                    "confidence": (
                        result.get("categories", [{}])[0].get("confidence", 0)
                        if result.get("categories")
                        else 0
                    ),
                    "reasoning": (
                        result.get("categories", [{}])[0].get("reasoning", "")
                        if result.get("categories")
                        else ""
                    ),
                    "key_indicators": result.get("key_indicators", []),
                }
            )
            analysis["statistics"]["uncategorized"] += 1
            continue

        # Get categories
        categories = result.get("categories", [])
        primary_category = result.get("primary_category", "Unknown")

        if not categories:
            continue

        # Track file info
        file_info = {
            "file_name": file_name,
            "file_path": file_path,
            "primary_category": primary_category,
            "num_categories": len(categories),
            "overall_summary": result.get("overall_summary", ""),
            "key_indicators": result.get("key_indicators", []),
            "categories": [],
        }

        # Process each category assignment
        category_names = []
        for idx, cat_info in enumerate(categories):
            cat_name = cat_info.get("name", "Unknown")
            confidence = cat_info.get("confidence", 0)
            reasoning = cat_info.get("reasoning", "")

            category_names.append(cat_name)

            # Track category statistics
            analysis["categories"][cat_name]["total_assignments"] += 1
            analysis["categories"][cat_name]["files"].append(file_name)

            if idx == 0:
                analysis["categories"][cat_name]["primary_count"] += 1
            else:
                analysis["categories"][cat_name]["secondary_count"] += 1

            # Track confidence
            total_confidence[cat_name]["sum"] += confidence
            total_confidence[cat_name]["count"] += 1

            file_info["categories"].append(
                {
                    "name": cat_name,
                    "confidence": confidence,
                    "reasoning": reasoning,
                    "position": "primary" if idx == 0 else f"secondary_{idx}",
                }
            )

            total_categories += 1

        # Track if multiple categories
        if len(categories) > 1:
            analysis["files_with_multiple_categories"].append(file_info)
            analysis["statistics"]["with_multiple_categories"] += 1

            # Track category combinations
            combo = " + ".join(category_names)
            analysis["category_combinations"][combo] += 1
        else:
            analysis["files_with_primary_only"].append(file_info)
            analysis["statistics"]["primary_only"] += 1

    # Calculate averages
    if analysis["statistics"]["processed"] > 0:
        analysis["statistics"]["avg_categories_per_file"] = (
            total_categories / analysis["statistics"]["processed"]
        )

    # Calculate average confidence per category
    for cat_name, data in analysis["categories"].items():
        if total_confidence[cat_name]["count"] > 0:
            data["avg_confidence"] = (
                total_confidence[cat_name]["sum"] / total_confidence[cat_name]["count"]
            )
            # Remove duplicates from files list
            data["files"] = list(set(data["files"]))

    return analysis


def export_json(analysis: Dict[str, Any]) -> None:
    """Export summary to JSON with category labels and reasoning."""
    summary = {
        "summary": {
            "total_files": analysis["statistics"]["total"],
            "correct": analysis["statistics"]["correct_count"],
            "incorrect": analysis["statistics"]["incorrect_count"],
            "uncategorized": analysis["statistics"]["uncategorized_count"],
            "failed": analysis["statistics"]["failed_count"],
            "correct_percentage": round(analysis["statistics"]["correct_percentage"], 2),
            "incorrect_percentage": round(analysis["statistics"]["incorrect_percentage"], 2),
            "uncategorized_percentage": round(
                analysis["statistics"]["uncategorized_percentage"], 2
            ),
            "failed_percentage": round(analysis["statistics"]["failed_percentage"], 2),
        },
        "by_category": {
            category: {
                "total": data["count"],
                "correct": data["correct"],
                "incorrect": data["incorrect"],
                "uncategorized": data["uncategorized"],
                "accuracy": round(data["accuracy"] * 100, 2) if data["accuracy"] > 0 else 0,
            }
            for category, data in analysis["categories"].items()
        },
        "correct_files": [
            {
                "file_name": f["file_name"],
                "category": f["category"],
                "confidence": round(f["confidence"], 3),
                "reasoning": f["reasoning"],
                "key_indicators": f["key_indicators"],
            }
            for f in analysis["correct_classifications"]
        ],
        "incorrect_files": [
            {
                "file_name": f["file_name"],
                "predicted_category": f["predicted_category"],
                "confidence": round(f["confidence"], 3),
                "reasoning": f["reasoning"],
                "key_indicators": f["key_indicators"],
            }
            for f in analysis["incorrect_classifications"]
        ],
        "uncategorized_files": [
            {
                "file_name": f["file_name"],
                "category": f["category"],
                "confidence": round(f["confidence"], 3),
                "correct": f["correct"],
                "reasoning": f["reasoning"],
                "key_indicators": f["key_indicators"],
            }
            for f in analysis["uncategorized_classifications"]
        ],
        "failed_files": [
            {"file_name": f["file_name"], "error": f["error"][:150]}
            for f in analysis["failed_classifications"]
        ],
    }

    with open("analysis_summary_single_category.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print("✅ Single-category analysis saved: analysis_summary_single_category.json\n")


def export_multi_category_json(
    analysis: Dict[str, Any], output_file: str = "analysis_multi_category_summary.json"
) -> None:
    """Export multi-category analysis to JSON with reasoning."""

    summary = {
        "summary": {
            "total_files": analysis["statistics"]["total"],
            "processed": analysis["statistics"]["processed"],
            "failed": analysis["statistics"]["failed"],
            "with_multiple_categories": analysis["statistics"]["with_multiple_categories"],
            "primary_only": analysis["statistics"]["primary_only"],
            "uncategorized": analysis["statistics"]["uncategorized"],
            "avg_categories_per_file": round(analysis["statistics"]["avg_categories_per_file"], 2),
        },
        "categories": {
            category: {
                "total_assignments": data["total_assignments"],
                "as_primary": data["primary_count"],
                "as_secondary": data["secondary_count"],
                "avg_confidence": round(data["avg_confidence"], 3),
                "num_files": len(data["files"]),
            }
            for category, data in analysis["categories"].items()
        },
        "top_category_combinations": [
            {"combination": combo, "count": count}
            for combo, count in sorted(
                analysis["category_combinations"].items(), key=lambda x: x[1], reverse=True
            )[:10]
        ],
        "files_with_multiple_categories": [
            {
                "file_name": f["file_name"],
                "num_categories": f["num_categories"],
                "primary_category": f["primary_category"],
                "categories": [
                    {
                        "name": cat["name"],
                        "confidence": round(cat["confidence"], 3),
                        "reasoning": cat["reasoning"],
                        "position": cat["position"],
                    }
                    for cat in f["categories"]
                ],
                "overall_summary": f["overall_summary"],
            }
            for f in analysis["files_with_multiple_categories"]
        ],
        "files_with_primary_only": [
            {
                "file_name": f["file_name"],
                "primary_category": f["primary_category"],
                "confidence": round(f["categories"][0]["confidence"], 3),
                "reasoning": f["categories"][0]["reasoning"],
                "key_indicators": f["key_indicators"],
            }
            for f in analysis["files_with_primary_only"]
        ],
        "uncategorized_files": [
            {
                "file_name": f["file_name"],
                "primary_category": f["primary_category"],
                "confidence": round(f["confidence"], 3),
                "reasoning": f["reasoning"],
                "key_indicators": f["key_indicators"],
            }
            for f in analysis["uncategorized_files"]
        ],
        "failed_files": [
            {"file_name": f["file_name"], "error": f["error"][:150]}
            for f in analysis["failed_files"]
        ],
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"✅ Multi-category analysis saved: {output_file}\n")


def main():
    """Run analysis."""

    import argparse

    parser = argparse.ArgumentParser(description="Analyze classification results")
    parser.add_argument(
        "--file",
        default="results_with_uncategorized.json",
        help="Path to results file (default: results_with_uncategorized.json)",
    )
    parser.add_argument(
        "--mode",
        choices=["single", "multi", "both"],
        default="both",
        help="Analysis mode: single (single-category), multi (multi-category), or both",
    )
    args = parser.parse_args()

    # Load results
    results = load_results(args.file)
    print(f"\n📂 Loading results from: {args.file}\n")

    # Check if results contain multi-category data
    has_multi_category = any(
        "categories" in r and isinstance(r.get("categories"), list) for r in results
    )

    # Single Category Analysis
    if args.mode in ["single", "both"]:
        print("\n" + "=" * 130)
        print("RUNNING SINGLE CATEGORY ANALYSIS")
        print("=" * 130)

        analysis = analyze_results(results)

        # Export single category JSON
        export_json(analysis)

        print(f"\n📊 Summary Statistics:")
        print(f"  Total Files: {analysis['statistics']['total']}")
        print(
            f"  ✅ Correct: {analysis['statistics']['correct_count']} ({analysis['statistics']['correct_percentage']:.1f}%)"
        )
        print(
            f"  ❌ Incorrect: {analysis['statistics']['incorrect_count']} ({analysis['statistics']['incorrect_percentage']:.1f}%)"
        )
        print(
            f"  ❓ Uncategorized: {analysis['statistics']['uncategorized_count']} ({analysis['statistics']['uncategorized_percentage']:.1f}%)"
        )
        print(
            f"  ⚠️  Failed: {analysis['statistics']['failed_count']} ({analysis['statistics']['failed_percentage']:.1f}%)\n"
        )

    # Multi Category Analysis
    if args.mode in ["multi", "both"] and has_multi_category:
        print("\n" + "=" * 150)
        print("RUNNING MULTI-CATEGORY ANALYSIS")
        print("=" * 150)

        multi_analysis = analyze_multi_category_results(results)

        # Export multi-category JSON
        export_multi_category_json(multi_analysis)

        print(f"\n📊 Summary Statistics:")
        print(f"  Total Files: {multi_analysis['statistics']['total']}")
        print(f"  ✅ Processed: {multi_analysis['statistics']['processed']}")
        print(
            f"  📚 With Multiple Categories: {multi_analysis['statistics']['with_multiple_categories']}"
        )
        print(f"  📄 Primary Only: {multi_analysis['statistics']['primary_only']}")
        print(f"  ❓ Uncategorized: {multi_analysis['statistics']['uncategorized']}")
        print(f"  ⚠️  Failed: {multi_analysis['statistics']['failed']}")
        print(
            f"  📊 Avg Categories per File: {multi_analysis['statistics']['avg_categories_per_file']:.2f}\n"
        )

    elif args.mode in ["multi", "both"] and not has_multi_category:
        print("\n⚠️  No multi-category data found in results file.")
        print("   This file may contain only single-category classifications.\n")

    print("✅ Analysis complete!")


if __name__ == "__main__":
    main()
