#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate confusion matrix using scikit-learn with Uncategorized category."""

import json
import numpy as np
from sklearn.metrics import confusion_matrix, classification_report, accuracy_score
import matplotlib.pyplot as plt
import seaborn as sns


def load_analysis(file_path: str = "analysis_summary_uncat.json") -> dict:
    """Load analysis summary JSON."""
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def prepare_data(analysis: dict) -> tuple:
    """
    Prepare ground truth (y_true) and predictions (y_pred).

    Ground truth: What we know for certain
    - Correct files: We know the actual category
    - Incorrect files: We DON'T know actual, treat as unknown/uncategorized
    - Uncategorized files: Actual is "Uncategorized Document"

    Returns:
        (y_true, y_pred, categories)
    """

    # Get all categories including Uncategorized
    all_categories = sorted(analysis["by_category"].keys())
    categories = all_categories

    y_true = []
    y_pred = []

    # ========================================================================
    # CORRECT FILES: We know both actual and predicted are correct
    # ========================================================================
    for file_info in analysis["correct_files"]:
        cat = file_info.get("category", "")
        if cat in categories:
            y_true.append(cat)
            y_pred.append(cat)

    # ========================================================================
    # INCORRECT FILES: We don't know actual category
    # Treat actual as "Uncategorized Document" (unknown)
    # Predicted is what the classifier said
    # ========================================================================
    for file_info in analysis["incorrect_files"]:
        pred_cat = file_info.get("predicted_category", "")
        if pred_cat in categories:
            y_true.append("Uncategorized Document")  # Actual is unknown
            y_pred.append(pred_cat)  # What classifier predicted

    # ========================================================================
    # UNCATEGORIZED FILES: Actual is "Uncategorized Document"
    # Predicted is also "Uncategorized Document"
    # ========================================================================
    for file_info in analysis["uncategorized_files"]:
        cat = file_info.get("category", "")
        if cat in categories:
            y_true.append(cat)  # "Uncategorized Document"
            y_pred.append(cat)  # "Uncategorized Document"

    return np.array(y_true), np.array(y_pred), categories


def print_confusion_matrix_ascii(cm: np.ndarray, categories: list) -> None:
    """Print confusion matrix as ASCII table."""

    print("\n" + "=" * 150)
    print("CONFUSION MATRIX")
    print("=" * 150)
    print("\nRows (Actual) vs Columns (Predicted)\n")

    # Shorten names
    short_names = [cat[:25] + "..." if len(cat) > 25 else cat for cat in categories]

    # Header
    print(f"{'Actual/Predicted':<30}", end="")
    for name in short_names:
        print(f"{name:>15}", end="")
    print(" | Total")
    print("-" * 150)

    # Rows
    for i, actual_cat in enumerate(categories):
        short_name = short_names[i]
        print(f"{short_name:<30}", end="")

        row_total = 0
        for j in range(len(categories)):
            count = int(cm[i, j])
            print(f"{count:>15}", end="")
            row_total += count

        print(f" | {row_total:>6}")

    # Totals
    print("-" * 150)
    print(f"{'Total':<30}", end="")
    for j in range(len(categories)):
        col_total = int(np.sum(cm[:, j]))
        print(f"{col_total:>15}", end="")
    print(f" | {int(np.sum(cm)):>6}\n")


def main():
    """Generate confusion matrix using sklearn."""

    print("\n" + "=" * 150)
    print("CONFUSION MATRIX GENERATOR (with Uncategorized Category)")
    print("=" * 150 + "\n")

    # Load analysis
    analysis = load_analysis()

    # Prepare data
    y_true, y_pred, categories = prepare_data(analysis)

    print(f"📊 Processing {len(y_true)} samples...\n")
    print("Data Composition:")
    print(f"  ✅ Correct files: {len(analysis['correct_files'])}")
    print(f"  ❌ Incorrect files (treated as unknown actual): {len(analysis['incorrect_files'])}")
    print(f"  ❓ Uncategorized files: {len(analysis['uncategorized_files'])}")
    print(f"  ⚠️  Failed files: {len(analysis['failed_files'])} (excluded)\n")

    # Generate confusion matrix
    cm = confusion_matrix(y_true, y_pred, labels=categories)

    # Print ASCII confusion matrix
    print_confusion_matrix_ascii(cm, categories)

    # Print classification report
    print("=" * 150)
    print("CLASSIFICATION REPORT")
    print("=" * 150)
    print(classification_report(y_true, y_pred, labels=categories, zero_division=0, digits=3))

    # Overall accuracy
    accuracy = accuracy_score(y_true, y_pred)
    print(f"Overall Accuracy: {accuracy:.3f} ({accuracy*100:.1f}%)\n")

    # Calculate per-category metrics
    print("=" * 150)
    print("PER-CATEGORY BREAKDOWN")
    print("=" * 150 + "\n")

    for i, cat in enumerate(categories):
        tp = cm[i, i]
        fp = np.sum(cm[:, i]) - tp
        fn = np.sum(cm[i, :]) - tp
        tn = np.sum(cm) - tp - fp - fn

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0

        print(f"{cat}")
        print(f"  TP (True Positives):   {int(tp):>5}  ✅ Correctly classified as this category")
        print(f"  FP (False Positives):  {int(fp):>5}  ❌ Incorrectly classified as this category")
        print(
            f"  FN (False Negatives):  {int(fn):>5}  ❌ Actually this category but classified as other"
        )
        print(f"  Precision: {precision:.3f}  (Of all predicted as this, how many were correct)")
        print(f"  Recall:    {recall:.3f}  (Of all actual this category, how many were found)")
        print(f"  F1-Score:  {f1:.3f}\n")

    # Plot confusion matrix
    plt.figure(figsize=(14, 12))

    # Shorten labels for plot
    short_labels = [cat[:20] + "..." if len(cat) > 20 else cat for cat in categories]

    sns.heatmap(
        cm,
        annot=True,
        fmt="d",
        cmap="Blues",
        xticklabels=short_labels,
        yticklabels=short_labels,
        cbar_kws={"label": "Count"},
        linewidths=1,
        linecolor="gray",
    )
    plt.title(
        "Confusion Matrix - Document Classification\n(including Uncategorized)",
        fontsize=14,
        fontweight="bold",
    )
    plt.ylabel("Actual Category", fontsize=12)
    plt.xlabel("Predicted Category", fontsize=12)
    plt.xticks(rotation=45, ha="right")
    plt.yticks(rotation=0)
    plt.tight_layout()
    plt.savefig("confusion_matrix.png", dpi=300, bbox_inches="tight")
    print("✅ Saved: confusion_matrix.png\n")
    plt.close()

    # Export to JSON
    export_data = {
        "summary": {
            "total_samples": len(y_true),
            "accuracy": float(accuracy),
            "correct_files": len(analysis["correct_files"]),
            "incorrect_files": len(analysis["incorrect_files"]),
            "uncategorized_files": len(analysis["uncategorized_files"]),
            "failed_files": len(analysis["failed_files"]),
        },
        "confusion_matrix": cm.tolist(),
        "categories": list(categories),
        "per_category_metrics": {
            cat: {
                "true_positives": int(cm[i, i]),
                "false_positives": int(np.sum(cm[:, i]) - cm[i, i]),
                "false_negatives": int(np.sum(cm[i, :]) - cm[i, i]),
            }
            for i, cat in enumerate(categories)
        },
    }

    with open("confusion_matrix.json", "w", encoding="utf-8") as f:
        json.dump(export_data, f, indent=2, ensure_ascii=False)

    print("✅ Saved: confusion_matrix.json")
    print("\n" + "=" * 150 + "\n")


if __name__ == "__main__":
    main()
