#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test script for document classification with smart file ID management."""

import sys
import json
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).parent / "src"))

from ddx.classification.classifier import DocumentClassifier, SUPPORTED_FORMATS
from ddx.llm.client import LLMClient


def sync_file_ids_from_openai(llm_client: LLMClient) -> Dict[str, str]:
    """
    Fetch all uploaded files from OpenAI and map them by filename.

    Returns:
        Dictionary mapping filename to file_id
    """
    print("📡 Fetching uploaded files from OpenAI...\n")

    file_ids_map = {}

    try:
        # List all files uploaded to OpenAI
        openai_files = llm_client.list_files(purpose="user_data")

        print(f"Found {len(openai_files)} files in OpenAI:\n")

        for file_obj in openai_files:
            file_id = file_obj.get("id")
            filename = file_obj.get("filename")
            created_at = file_obj.get("created_at")
            size = file_obj.get("size")

            if filename and file_id:
                file_ids_map[filename] = file_id
                print(f"  ✅ {filename}")
                print(f"     ID: {file_id}")
                print(f"     Size: {size} bytes")
                print(f"     Created: {created_at}\n")

        return file_ids_map

    except Exception as e:
        print(f"❌ Error fetching files from OpenAI: {e}\n")
        return {}


def save_file_ids_locally(
    file_ids: Dict[str, str], file_path: str = "uploaded_file_ids.json"
) -> None:
    """Save file IDs to local JSON file for reference."""
    with open(file_path, "w") as f:
        json.dump(file_ids, f, indent=2)
    print(f"✅ File IDs saved locally: {file_path}\n")


def load_file_ids_locally(file_path: str = "uploaded_file_ids.json") -> Dict[str, str]:
    """Load previously saved file IDs from local file."""
    if Path(file_path).exists():
        with open(file_path, "r") as f:
            return json.load(f)
    return {}


def match_local_files_to_openai_ids(
    local_files: List[Path], openai_file_ids: Dict[str, str]
) -> Dict[str, str]:
    """
    Match local files to OpenAI file IDs.

    Returns:
        Dictionary mapping local file path to OpenAI file_id
    """
    matched = {}
    unmatched = []

    for file_path in local_files:
        filename = file_path.name

        # Try exact match
        if filename in openai_file_ids:
            matched[str(file_path)] = openai_file_ids[filename]
        else:
            unmatched.append(filename)

    if unmatched:
        print(f"⚠️  Files not found in OpenAI (will be uploaded):")
        for filename in unmatched:
            print(f"   • {filename}")
        print()

    return matched


def classify_with_mode(
    files: List[Path],
    mode: str = "single",
    file_ids_map: Dict[str, str] = None,
    llm_client: LLMClient = None,
) -> tuple:
    """
    Classify documents in specified mode using file IDs when available.

    Args:
        files: List of file paths
        mode: "single" or "multi"
        file_ids_map: Dictionary mapping file path to file_id
        llm_client: LLMClient instance

    Returns:
        Tuple of (results list, uploaded_file_ids dict)
    """
    file_ids_map = file_ids_map or {}

    classifier = DocumentClassifier(llm_client)
    results = []
    uploaded_file_ids = {}

    for file_path in files:
        file_path = Path(file_path)
        file_name = file_path.name
        file_id = file_ids_map.get(str(file_path))

        try:
            if file_id:
                # Use existing file ID
                print(f"📄 {file_name} (using file ID: {file_id})")

                result = classifier.classify_document_with_file_id(
                    file_id=file_id,
                    file_name=file_name,
                    allow_uncategorized=True,
                    allow_multiple_categories=(mode == "multi"),
                )

                if "error" not in result:
                    result["file_path"] = str(file_path)
                    result["file_id"] = file_id
                    result["classification_mode"] = mode
                    result["source"] = "openai_file_id"
            else:
                # Upload new file
                print(f"📄 {file_name} (uploading...)")

                result = classifier.classify_document(
                    file_path=file_path,
                    allow_uncategorized=True,
                    allow_multiple_categories=(mode == "multi"),
                )

                if "error" not in result:
                    result["file_path"] = str(file_path)
                    result["classification_mode"] = mode
                    result["source"] = "new_upload"

                    # Track newly uploaded file ID
                    if hasattr(classifier.llm_client, "_last_uploaded_file_id"):
                        uploaded_file_ids[file_name] = classifier.llm_client._last_uploaded_file_id

            results.append(result)

        except Exception as e:
            results.append(
                {
                    "file_name": file_name,
                    "file_path": str(file_path),
                    "error": str(e),
                    "classification_mode": mode,
                }
            )

    return results, uploaded_file_ids


def print_single_category_result(result: Dict) -> None:
    """Print single category classification result."""
    if "error" in result:
        print(f"   ❌ Error: {result['error']}")
        return

    category = result.get("category", "Unknown")
    confidence = result.get("confidence", 0)
    is_uncategorized = result.get("is_uncategorized", False)
    reasoning = result.get("reasoning", "N/A")
    source = result.get("source", "unknown")

    status = "⚠️" if is_uncategorized else "✅"
    print(f"   {status} Category: {category}")
    print(f"   📊 Confidence: {confidence:.1%}")
    print(f"   💬 Reason: {reasoning}")
    print(f"   🔄 Source: {source}")


def print_multi_category_result(result: Dict) -> None:
    """Print multi-category classification result."""
    if "error" in result:
        print(f"   ❌ Error: {result['error']}")
        return

    primary = result.get("primary_category", "Unknown")
    is_uncategorized = result.get("is_uncategorized", False)
    categories = result.get("categories", [])
    summary = result.get("overall_summary", "")
    source = result.get("source", "unknown")

    status = "⚠️" if is_uncategorized else "✅"
    print(f"   {status} Primary Category: {primary}")
    print(f"   📊 Total Categories: {len(categories)}")

    if categories:
        print(f"   📋 Categories:")
        for cat in categories:
            name = cat.get("name", "Unknown")
            conf = cat.get("confidence", 0)
            reason = cat.get("reasoning", "")
            print(f"      • {name} ({conf:.1%})")
            if reason:
                print(f"        └─ {reason}")

    if summary:
        print(f"   📝 Summary: {summary}")

    print(f"   🔄 Source: {source}")


def run_single_category_classification(
    test_dir: Path, llm_client: LLMClient, openai_file_ids: Dict[str, str]
) -> tuple:
    """
    Run single category classification.

    Returns:
        Tuple of (results, updated_file_ids)
    """
    print("\n" + "=" * 90)
    print("SINGLE CATEGORY CLASSIFICATION")
    print("=" * 90 + "\n")

    # Get all supported files
    files = []
    for ext in SUPPORTED_FORMATS.keys():
        files.extend(test_dir.glob(f"*{ext}"))

    if not files:
        print(f"❌ No supported documents found in: {test_dir}")
        return [], openai_file_ids

    print(f"📁 Found {len(files)} supported documents\n")

    # Match local files to OpenAI IDs
    file_ids_map = match_local_files_to_openai_ids(files, openai_file_ids)

    print(f"✅ Matched {len(file_ids_map)} local files to OpenAI file IDs")
    print(f"⬆️  Will upload {len(files) - len(file_ids_map)} new files\n")

    print("Classifying documents (single category with uncategorized option)...\n")

    single_results, new_single_ids = classify_with_mode(
        files=files,
        mode="single",
        file_ids_map=file_ids_map,
        llm_client=llm_client,
    )

    # Track new file IDs
    openai_file_ids.update(new_single_ids)

    # Print results
    successful_single = 0
    failed_single = 0

    for result in single_results:
        print(f"📄 {result.get('file_name', 'Unknown')}")
        if "error" in result:
            print(f"   ❌ Error: {result['error']}")
            failed_single += 1
        else:
            print_single_category_result(result)
            successful_single += 1
        print()

    # Save single category results
    with open("results_single_category.json", "w") as f:
        json.dump(single_results, f, indent=2)

    print(f"✅ Single category results saved: results_single_category.json\n")

    # Print summary
    print("\n" + "=" * 90)
    print("SINGLE CATEGORY SUMMARY")
    print("=" * 90)
    print(f"\n✅ Successful: {successful_single}")
    print(f"❌ Failed: {failed_single}")
    if len(single_results) > 0:
        print(f"📊 Success Rate: {successful_single / len(single_results) * 100:.1f}%")
    print(f"\n{'=' * 90}\n")

    return single_results, openai_file_ids


def run_multi_category_classification(
    test_dir: Path, llm_client: LLMClient, openai_file_ids: Dict[str, str]
) -> tuple:
    """
    Run multi-category classification.

    Returns:
        Tuple of (results, updated_file_ids)
    """
    print("\n" + "=" * 90)
    print("MULTI CATEGORY CLASSIFICATION")
    print("=" * 90 + "\n")

    # Get all supported files
    files = []
    for ext in SUPPORTED_FORMATS.keys():
        files.extend(test_dir.glob(f"*{ext}"))

    if not files:
        print(f"❌ No supported documents found in: {test_dir}")
        return [], openai_file_ids

    print(f"📁 Found {len(files)} supported documents\n")

    # Match local files to OpenAI IDs
    file_ids_map = match_local_files_to_openai_ids(files, openai_file_ids)

    print(f"✅ Matched {len(file_ids_map)} local files to OpenAI file IDs")
    print(f"⬆️  Will upload {len(files) - len(file_ids_map)} new files\n")

    print("Classifying documents (multiple categories with uncategorized option)...\n")

    multi_results, new_multi_ids = classify_with_mode(
        files=files,
        mode="multi",
        file_ids_map=file_ids_map,
        llm_client=llm_client,
    )

    # Track new file IDs
    openai_file_ids.update(new_multi_ids)

    # Print results
    successful_multi = 0
    failed_multi = 0

    for result in multi_results:
        print(f"📄 {result.get('file_name', 'Unknown')}")
        if "error" in result:
            print(f"   ❌ Error: {result['error']}")
            failed_multi += 1
        else:
            print_multi_category_result(result)
            successful_multi += 1
        print()

    # Save multi-category results
    with open("results_multi_category.json", "w") as f:
        json.dump(multi_results, f, indent=2)

    print(f"✅ Multi-category results saved: results_multi_category.json\n")

    # Print summary
    print("\n" + "=" * 90)
    print("MULTI CATEGORY SUMMARY")
    print("=" * 90)
    print(f"\n✅ Successful: {successful_multi}")
    print(f"❌ Failed: {failed_multi}")
    if len(multi_results) > 0:
        print(f"📊 Success Rate: {successful_multi / len(multi_results) * 100:.1f}%")
    print(f"\n{'=' * 90}\n")

    return multi_results, openai_file_ids


def show_menu():
    """Display menu and get user choice."""
    print("\n" + "=" * 90)
    print("DOCUMENT CLASSIFICATION WITH SMART FILE ID MANAGEMENT")
    print("=" * 90)
    print("\nChoose classification mode:\n")
    print("  1️⃣  Single Category Classification")
    print("  2️⃣  Multi Category Classification")
    print("  3️⃣  Both (Single then Multi)")
    print("  0️⃣  Exit\n")

    while True:
        try:
            choice = input("Enter your choice (0-3): ").strip()
            if choice in ["0", "1", "2", "3"]:
                return choice
            else:
                print("❌ Invalid choice. Please enter 0, 1, 2, or 3.")
        except KeyboardInterrupt:
            print("\n\n❌ Cancelled by user.")
            return "0"


def main():
    """Main function with user menu."""

    test_dir = r"d:\due-diligence-extractor\examples\tech_docs"
    test_dir = Path(test_dir)

    if not test_dir.exists():
        print(f"❌ Directory not found: {test_dir}")
        return

    # Initialize LLM client
    llm_client = LLMClient(provider="openai")

    # ========================================================================
    # STEP 1: Sync file IDs from OpenAI
    # ========================================================================
    print("\n" + "=" * 90)
    print("STEP 1: SYNCING FILE IDs FROM OPENAI")
    print("=" * 90 + "\n")

    openai_file_ids = sync_file_ids_from_openai(llm_client)

    if openai_file_ids:
        save_file_ids_locally(openai_file_ids)

    # ========================================================================
    # STEP 2: Show menu and get user choice
    # ========================================================================
    choice = show_menu()

    if choice == "0":
        print("\n👋 Goodbye!\n")
        return

    elif choice == "1":
        # Single Category Classification
        single_results, openai_file_ids = run_single_category_classification(
            test_dir, llm_client, openai_file_ids
        )
        save_file_ids_locally(openai_file_ids)

    elif choice == "2":
        # Multi Category Classification
        multi_results, openai_file_ids = run_multi_category_classification(
            test_dir, llm_client, openai_file_ids
        )
        save_file_ids_locally(openai_file_ids)

    elif choice == "3":
        # Both Single and Multi
        single_results, openai_file_ids = run_single_category_classification(
            test_dir, llm_client, openai_file_ids
        )

        multi_results, openai_file_ids = run_multi_category_classification(
            test_dir, llm_client, openai_file_ids
        )

        save_file_ids_locally(openai_file_ids)

        # Show comparison summary
        print("\n" + "=" * 90)
        print("COMPARISON SUMMARY")
        print("=" * 90)
        print(f"\n📊 File Management:")
        print(f"   Files in OpenAI: {len(openai_file_ids)}")
        print(f"\n✅ Single Category Classification:")
        print(f"   Results saved: results_single_category.json")
        print(f"\n✅ Multi Category Classification:")
        print(f"   Results saved: results_multi_category.json")
        print(f"\n{'=' * 90}\n")


if __name__ == "__main__":
    main()
