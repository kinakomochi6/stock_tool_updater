"""Summarize B/S diagnostic JSON files with absolute residual metrics."""

import argparse
import json
from collections import Counter
from pathlib import Path


THRESHOLDS_OKU = (1, 10, 100, 1000)


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
    warning_count = 0
    failed_codes = []

    for record in records:
        code = str(record.get("code") or Path(record["_path"]).stem[-4:])
        status = record.get("status", "unknown")
        if status != "ok":
            failed_codes.append(code)
            continue

        standards[record.get("doc_type", "unknown")] += 1
        context = record.get("selected_context") or "missing"
        context_type = "nonconsolidated" if "NonConsolidated" in context else "consolidated_or_plain"
        contexts[context_type] += 1
        warnings = record.get("warnings") or []
        warning_count += len(warnings)

        residuals = record.get("other_gap_delta_oku") or {}
        if residuals:
            worst_key, signed_value = max(residuals.items(), key=lambda item: abs(item[1]))
            max_abs_residual = abs(signed_value)
        else:
            worst_key, signed_value, max_abs_residual = "", 0, 0

        rows.append({
            "code": code,
            "doc_type": record.get("doc_type", "unknown"),
            "context_type": context_type,
            "worst_category": worst_key,
            "signed_residual_oku": round(signed_value, 3),
            "max_abs_residual_oku": round(max_abs_residual, 3),
            "warning_count": len(warnings),
        })

    rows.sort(key=lambda row: (-row["max_abs_residual_oku"], row["code"]))
    threshold_counts = {
        f"over_{threshold}_oku": sum(row["max_abs_residual_oku"] > threshold for row in rows)
        for threshold in THRESHOLDS_OKU
    }
    return {
        "file_count": len(records),
        "ok_count": len(rows),
        "failed_codes": sorted(failed_codes),
        "warning_count": warning_count,
        "accounting_standards": dict(sorted(standards.items())),
        "context_types": dict(sorted(contexts.items())),
        "threshold_counts": threshold_counts,
        "max_abs_residual_oku": rows[0]["max_abs_residual_oku"] if rows else 0,
        "rows": rows,
    }


def render_markdown(summary, row_limit=25):
    standards = ", ".join(f"{key}: {value}" for key, value in summary["accounting_standards"].items()) or "none"
    contexts = ", ".join(f"{key}: {value}" for key, value in summary["context_types"].items()) or "none"
    threshold_text = ", ".join(
        f">{threshold} oku: {summary['threshold_counts'][f'over_{threshold}_oku']}"
        for threshold in THRESHOLDS_OKU
    )
    lines = [
        "# B/S diagnostics summary",
        "",
        f"- Files: {summary['file_count']}",
        f"- Successful: {summary['ok_count']}",
        f"- Failed: {len(summary['failed_codes'])}",
        f"- Warnings: {summary['warning_count']}",
        f"- Accounting standards: {standards}",
        f"- Contexts: {contexts}",
        f"- Absolute residual counts: {threshold_text}",
        f"- Maximum absolute residual: {summary['max_abs_residual_oku']:.3f} oku",
        "",
        "| Code | GAAP | Context | Worst category | Signed residual (oku) | Warnings |",
        "|---|---|---|---|---:|---:|",
    ]
    for row in summary["rows"][:row_limit]:
        lines.append(
            f"| {row['code']} | {row['doc_type']} | {row['context_type']} | "
            f"{row['worst_category']} | {row['signed_residual_oku']:.3f} | {row['warning_count']} |"
        )
    if summary["failed_codes"]:
        lines.extend(["", f"Failed codes: {', '.join(summary['failed_codes'])}"])
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

