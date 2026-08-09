"""Summarize B/S diagnostic JSON files with absolute residual metrics."""

import argparse
import json
from collections import Counter
from pathlib import Path


THRESHOLDS_OKU = (1, 10, 100, 1000)
NON_FAILURE_STATUSES = {"source_not_applicable"}


def load_diagnostics(directory):
    records = []
    for path in sorted(Path(directory).glob("debug_bs_*.json")):
        with path.open(encoding="utf-8") as source:
            record = json.load(source)
        record["_path"] = str(path)
        records.append(record)
    return records


def summarize_diagnostics(records):
    rows = []
    standards = Counter()
    contexts = Counter()
    failure_statuses = Counter()
    worst_categories = Counter()
    candidate_tags = {}
    semantic_tags = Counter()
    semantic_inference_count = 0
    semantic_company_count = 0
    taxonomy_inference_count = 0
    taxonomy_company_count = 0
    definition_inference_count = 0
    definition_company_count = 0
    label_inference_count = 0
    label_company_count = 0
    warning_count = 0
    quality_statuses = Counter()
    failed_codes = []
    skipped_codes = []
    skipped_statuses = Counter()

    for record in records:
        code = str(record.get("code") or Path(record["_path"]).stem[-4:])
        status = record.get("status", "unknown")
        if status in NON_FAILURE_STATUSES:
            skipped_codes.append(code)
            skipped_statuses[status] += 1
            continue
        if status != "ok":
            failed_codes.append(code)
            failure_statuses[status] += 1
            continue

        standards[record.get("doc_type", "unknown")] += 1
        context = record.get("selected_context") or "missing"
        context_type = "nonconsolidated" if "NonConsolidated" in context else "consolidated_or_plain"
        contexts[context_type] += 1
        warnings = record.get("warnings") or []
        warning_count += len(warnings)
        quality_status = record.get("quality_status") or record.get("quality", {}).get("status") or "unknown"
        quality_statuses[quality_status] += 1
        semantic_inferences = record.get("semantic_inferences") or []
        if semantic_inferences:
            semantic_company_count += 1
        semantic_inference_count += len(semantic_inferences)
        for inference in semantic_inferences:
            if inference.get("tag"):
                semantic_tags[inference["tag"]] += 1
        taxonomy_inferences = record.get("taxonomy_inferences") or []
        if taxonomy_inferences:
            taxonomy_company_count += 1
        taxonomy_inference_count += len(taxonomy_inferences)
        definition_inferences = [
            item for item in taxonomy_inferences
            if "definition" in (item.get("taxonomy_link_types") or [])
        ]
        label_inferences = [
            item for item in taxonomy_inferences
            if item.get("taxonomy_label")
        ]
        if definition_inferences:
            definition_company_count += 1
        if label_inferences:
            label_company_count += 1
        definition_inference_count += len(definition_inferences)
        label_inference_count += len(label_inferences)

        residuals = record.get("other_gap_delta_oku") or {}
        if residuals:
            worst_key, signed_value = max(residuals.items(), key=lambda item: abs(item[1]))
            max_abs_residual = abs(signed_value)
        else:
            worst_key, signed_value, max_abs_residual = "", 0, 0
        if worst_key:
            worst_categories[worst_key] += 1

        for candidate in record.get("mapping_candidate_unmapped_tags_over_1oku") or []:
            tag = candidate.get("tag")
            if not tag:
                continue
            value = float(candidate.get("value_oku") or 0)
            stats = candidate_tags.setdefault(tag, {
                "tag": tag,
                "company_count": 0,
                "total_abs_value_oku": 0.0,
                "max_abs_value_oku": 0.0,
                "example_codes": [],
            })
            stats["company_count"] += 1
            stats["total_abs_value_oku"] += abs(value)
            stats["max_abs_value_oku"] = max(stats["max_abs_value_oku"], abs(value))
            if len(stats["example_codes"]) < 5:
                stats["example_codes"].append(code)

        rows.append({
            "code": code,
            "doc_type": record.get("doc_type", "unknown"),
            "context_type": context_type,
            "worst_category": worst_key,
            "signed_residual_oku": round(signed_value, 3),
            "max_abs_residual_oku": round(max_abs_residual, 3),
            "warning_count": len(warnings),
            "quality_status": quality_status,
            "semantic_inference_count": len(semantic_inferences),
        })

    rows.sort(key=lambda row: (-row["max_abs_residual_oku"], row["code"]))
    threshold_counts = {
        f"over_{threshold}_oku": sum(row["max_abs_residual_oku"] > threshold for row in rows)
        for threshold in THRESHOLDS_OKU
    }
    candidate_tag_rows = sorted(
        candidate_tags.values(),
        key=lambda item: (-item["company_count"], -item["total_abs_value_oku"], item["tag"]),
    )
    for item in candidate_tag_rows:
        item["total_abs_value_oku"] = round(item["total_abs_value_oku"], 3)
        item["max_abs_value_oku"] = round(item["max_abs_value_oku"], 3)
    return {
        "file_count": len(records),
        "ok_count": len(rows),
        "failed_codes": sorted(failed_codes),
        "failure_statuses": dict(sorted(failure_statuses.items())),
        "skipped_codes": sorted(skipped_codes),
        "skipped_statuses": dict(sorted(skipped_statuses.items())),
        "warning_count": warning_count,
        "quality_statuses": dict(sorted(quality_statuses.items())),
        "semantic_company_count": semantic_company_count,
        "semantic_inference_count": semantic_inference_count,
        "taxonomy_company_count": taxonomy_company_count,
        "taxonomy_inference_count": taxonomy_inference_count,
        "definition_company_count": definition_company_count,
        "definition_inference_count": definition_inference_count,
        "label_company_count": label_company_count,
        "label_inference_count": label_inference_count,
        "semantic_tags": dict(semantic_tags.most_common()),
        "accounting_standards": dict(sorted(standards.items())),
        "context_types": dict(sorted(contexts.items())),
        "threshold_counts": threshold_counts,
        "max_abs_residual_oku": rows[0]["max_abs_residual_oku"] if rows else 0,
        "worst_category_counts": dict(worst_categories.most_common()),
        "candidate_unmapped_tags": candidate_tag_rows,
        "rows": rows,
    }


def render_markdown(summary, row_limit=25):
    standards = ", ".join(f"{key}: {value}" for key, value in summary["accounting_standards"].items()) or "none"
    contexts = ", ".join(f"{key}: {value}" for key, value in summary["context_types"].items()) or "none"
    quality = ", ".join(f"{key}: {value}" for key, value in summary["quality_statuses"].items()) or "none"
    threshold_text = ", ".join(
        f">{threshold} oku: {summary['threshold_counts'][f'over_{threshold}_oku']}"
        for threshold in THRESHOLDS_OKU
    )
    lines = [
        "# B/S diagnostics summary",
        "",
        f"- Files: {summary['file_count']}",
        f"- Successful: {summary['ok_count']}",
        f"- Not applicable: {len(summary['skipped_codes'])}",
        f"- Failed: {len(summary['failed_codes'])}",
        f"- Warnings: {summary['warning_count']}",
        f"- Quality: {quality}",
        f"- Semantic fallback: {summary['semantic_inference_count']} tags in "
        f"{summary['semantic_company_count']} companies",
        f"- Taxonomy fallback: {summary['taxonomy_inference_count']} tags in "
        f"{summary['taxonomy_company_count']} companies",
        f"- Definition-backed fallback: {summary['definition_inference_count']} tags in "
        f"{summary['definition_company_count']} companies",
        f"- Label-backed fallback: {summary['label_inference_count']} tags in "
        f"{summary['label_company_count']} companies",
        f"- Accounting standards: {standards}",
        f"- Contexts: {contexts}",
        f"- Absolute residual counts: {threshold_text}",
        f"- Maximum absolute residual: {summary['max_abs_residual_oku']:.3f} oku",
        "",
        "| Code | GAAP | Context | Quality | Worst category | Signed residual (oku) | Warnings |",
        "|---|---|---|---|---|---:|---:|",
    ]
    for row in summary["rows"][:row_limit]:
        lines.append(
            f"| {row['code']} | {row['doc_type']} | {row['context_type']} | {row['quality_status']} | "
            f"{row['worst_category']} | {row['signed_residual_oku']:.3f} | {row['warning_count']} |"
        )
    if summary["failed_codes"]:
        failure_text = ", ".join(
            f"{status}: {count}" for status, count in summary["failure_statuses"].items()
        )
        lines.extend(["", f"Failed codes: {', '.join(summary['failed_codes'])}"])
        lines.append(f"Failure statuses: {failure_text}")
    if summary["skipped_codes"]:
        skipped_text = ", ".join(
            f"{status}: {count}" for status, count in summary["skipped_statuses"].items()
        )
        lines.extend(["", f"Not applicable codes: {', '.join(summary['skipped_codes'])}"])
        lines.append(f"Not applicable statuses: {skipped_text}")

    candidate_tags = summary.get("candidate_unmapped_tags") or []
    if candidate_tags:
        lines.extend([
            "",
            "## Repeated mapping candidates",
            "",
            "| Tag | Companies | Total absolute value (oku) | Maximum (oku) | Examples |",
            "|---|---:|---:|---:|---|",
        ])
        for item in candidate_tags[:15]:
            lines.append(
                f"| {item['tag']} | {item['company_count']} | "
                f"{item['total_abs_value_oku']:.3f} | {item['max_abs_value_oku']:.3f} | "
                f"{', '.join(item['example_codes'])} |"
            )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Summarize B/S diagnostic JSON files")
    parser.add_argument("directory", nargs="?", default="diagnostics")
    parser.add_argument("--json-output")
    parser.add_argument("--markdown-output")
    parser.add_argument("--fail-over-oku", type=float)
    args = parser.parse_args()

    records = load_diagnostics(args.directory)
    if not records:
        raise SystemExit(f"No debug_bs_*.json files found in {args.directory}")

    summary = summarize_diagnostics(records)
    markdown = render_markdown(summary)
    print(markdown, end="")

    if args.json_output:
        path = Path(args.json_output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.markdown_output:
        path = Path(args.markdown_output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding="utf-8")

    if summary["failed_codes"]:
        raise SystemExit(1)
    if args.fail_over_oku is not None and summary["max_abs_residual_oku"] > args.fail_over_oku:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
