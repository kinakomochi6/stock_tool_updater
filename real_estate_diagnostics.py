import argparse
import collections
import datetime
import json
from pathlib import Path

from firebase_master_test import (
    EDINET_API_KEY,
    EdinetSearcher,
    analyze_real_estate_and_securities_html,
    load_edinet_code_map,
    parse_codes_arg,
)
from real_estate_test_sets import (
    REAL_ESTATE_TEST_SETS,
    get_real_estate_test_set_codes,
)
from real_estate_verifier import compare_prior_year_continuity


VALUE_FIELDS = (
    "book_value_oku",
    "market_value_oku",
    "hidden_gain_oku",
)
DEFAULT_TOLERANCE_OKU = 0.01


def load_baseline(path):
    if not path:
        return {"records": {}, "tolerance_oku": DEFAULT_TOLERANCE_OKU}
    baseline_path = Path(path)
    if not baseline_path.exists():
        return {"records": {}, "tolerance_oku": DEFAULT_TOLERANCE_OKU}
    with baseline_path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    data.setdefault("records", {})
    data.setdefault("tolerance_oku", DEFAULT_TOLERANCE_OKU)
    return data


def normalize_extraction_result(result):
    if not isinstance(result, dict):
        return {
            "extraction_status": "extraction_failed",
            "book_value_oku": 0.0,
            "market_value_oku": 0.0,
            "hidden_gain_oku": 0.0,
            "real_estate_quality": "unknown",
            "real_estate_outcome": "extraction_failed",
            "real_estate_reasons": [],
        }

    expected_keys = (
        "不動産_簿価_億",
        "不動産_時価_億",
        "不動産_含み益_億",
    )
    if not any(key in result for key in expected_keys):
        return {
            "extraction_status": "extraction_failed",
            "book_value_oku": 0.0,
            "market_value_oku": 0.0,
            "hidden_gain_oku": 0.0,
            "real_estate_quality": "unknown",
            "real_estate_outcome": "extraction_failed",
            "real_estate_reasons": [],
        }

    book = float(result.get("不動産_簿価_億", 0) or 0)
    market = float(result.get("不動産_時価_億", 0) or 0)
    gain = float(result.get("不動産_含み益_億", 0) or 0)
    status = "extracted" if book != 0 or market != 0 else "no_values"
    return {
        "extraction_status": status,
        "book_value_oku": book,
        "market_value_oku": market,
        "hidden_gain_oku": gain,
        "real_estate_quality": result.get("不動産_検証状態", "unknown"),
        "real_estate_outcome": result.get("不動産_取得分類", "unknown"),
        "real_estate_reasons": result.get("不動産_検証理由", []),
    }


def compare_with_baseline(record, expected, mode, tolerance_oku):
    if not expected:
        status = record.get("extraction_status")
        if status == "extracted":
            return "baseline_missing", {}
        if status == "no_values":
            return "unverified_no_values", {}
        if status == "document_not_found":
            return "source_unavailable", {}
        return "unverified_extraction_failure", {
            "reason": status or "extraction_failed",
        }
    if record.get("extraction_status") != "extracted":
        return "regression", {
            "reason": record.get("extraction_status", "extraction_failed"),
        }

    if mode == "latest" and record.get("doc_id") != expected.get("doc_id"):
        return "review_required", {
            "reason": "latest_document_changed",
            "expected_doc_id": expected.get("doc_id"),
            "observed_doc_id": record.get("doc_id"),
        }

    differences = {
        field: round(float(record.get(field, 0)) - float(expected.get(field, 0)), 6)
        for field in VALUE_FIELDS
    }
    mismatches = {
        field: difference
        for field, difference in differences.items()
        if abs(difference) > tolerance_oku
    }
    if mismatches:
        return "regression", {
            "reason": "value_changed",
            "differences_oku": differences,
            "mismatches_oku": mismatches,
        }
    return "matched", {"differences_oku": differences}


def _document_metadata(searcher, doc_id):
    matches = searcher.df_docs[searcher.df_docs["docID"] == doc_id]
    if matches.empty:
        return {}
    row = matches.iloc[0]
    return {
        "period_end": str(row.get("periodEnd", "") or ""),
        "submitted_at": str(row.get("submitDateTime", "") or ""),
        "document_description": str(row.get("docDescription", "") or ""),
        "filer_name": str(row.get("filerName", "") or ""),
    }


def _extract_record(code, doc_id, metadata, expected, mode, tolerance_oku):
    record = {
        "code": code,
        "doc_id": doc_id,
        "mode": mode,
        "period_end": "",
        "submitted_at": "",
        "document_description": "",
        "filer_name": "",
        **metadata,
    }
    if not doc_id:
        record.update({
            "extraction_status": "document_not_found",
            "book_value_oku": 0.0,
            "market_value_oku": 0.0,
            "hidden_gain_oku": 0.0,
            "real_estate_quality": "not_found",
            "real_estate_outcome": "document_not_found",
            "real_estate_reasons": [],
        })
    else:
        try:
            source_diagnostics = {}
            result = analyze_real_estate_and_securities_html(
                doc_id, real_estate_diagnostics=source_diagnostics
            )
            record.update(normalize_extraction_result(result))
            record["source_diagnostics"] = source_diagnostics
            current_double = source_diagnostics.get(
                "independent_comparison", {}
            )
            record["automated_verification"] = {
                "status": (
                    "current_double_matched"
                    if current_double.get("status") == "matched"
                    else "current_extraction_mismatch"
                    if current_double.get("status") == "mismatch"
                    else "not_fully_verifiable"
                ),
                "current_double_extraction": current_double,
                "prior_year_continuity": {
                    "status": "not_available",
                    "reason": "previous_document_not_loaded",
                },
            }
        except Exception as exc:
            record.update({
                "extraction_status": "extraction_failed",
                "book_value_oku": 0.0,
                "market_value_oku": 0.0,
                "hidden_gain_oku": 0.0,
                "real_estate_quality": "unknown",
                "real_estate_outcome": "extraction_failed",
                "real_estate_reasons": [],
                "error": f"{type(exc).__name__}: {exc}",
            })

    comparison, details = compare_with_baseline(
        record, expected, mode, tolerance_oku
    )
    record["comparison_status"] = comparison
    record["comparison"] = details
    return record


def _extract_previous_document(doc_id, metadata):
    if not doc_id:
        return None
    diagnostics = {}
    try:
        result = analyze_real_estate_and_securities_html(
            doc_id, real_estate_diagnostics=diagnostics
        )
        normalized = normalize_extraction_result(result)
        return {
            "doc_id": doc_id,
            **metadata,
            **normalized,
            "independent_selection": diagnostics.get(
                "independent_selection", {}
            ),
            "independent_comparison": diagnostics.get(
                "independent_comparison", {}
            ),
        }
    except Exception as exc:
        return {
            "doc_id": doc_id,
            **metadata,
            "extraction_status": "extraction_failed",
            "error": f"{type(exc).__name__}: {exc}",
            "independent_selection": {},
        }


def _attach_automated_verification(record, previous_document):
    source = record.get("source_diagnostics", {})
    current_double = source.get("independent_comparison", {
        "status": "not_available",
        "reason": "independent_extraction_not_run",
    })
    latest_independent = source.get("independent_selection", {})
    previous_independent = (
        previous_document or {}
    ).get("independent_selection", {})
    continuity = compare_prior_year_continuity(
        latest_independent.get("previous"),
        previous_independent.get("current"),
    )
    if current_double.get("status") == "mismatch":
        overall = "current_extraction_mismatch"
    elif current_double.get("status") == "matched" and continuity.get("status") == "matched":
        overall = "strongly_verified"
    elif current_double.get("status") == "matched":
        overall = "current_double_matched"
    elif continuity.get("status") == "matched":
        overall = "prior_continuity_only"
    else:
        overall = "not_fully_verifiable"
    record["automated_verification"] = {
        "status": overall,
        "current_double_extraction": current_double,
        "prior_year_continuity": continuity,
    }
    record["previous_document"] = previous_document


def run_latest(codes, baseline, days_back):
    searcher = EdinetSearcher(load_edinet_code_map())
    searcher.fetch_list(
        codes, days_back=days_back, real_estate_periods=2
    )
    tolerance = float(baseline.get("tolerance_oku", DEFAULT_TOLERANCE_OKU))
    records = []
    for code in codes:
        doc_ids = searcher.find_re_docs(code, limit=2)
        doc_id = doc_ids[0] if doc_ids else None
        record = _extract_record(
            code,
            doc_id,
            _document_metadata(searcher, doc_id) if doc_id else {},
            baseline.get("records", {}).get(code),
            "latest",
            tolerance,
        )
        previous_doc_id = doc_ids[1] if len(doc_ids) > 1 else None
        previous_document = _extract_previous_document(
            previous_doc_id,
            _document_metadata(searcher, previous_doc_id)
            if previous_doc_id else {},
        )
        _attach_automated_verification(record, previous_document)
        records.append(record)
    return records


def run_pinned(codes, baseline):
    tolerance = float(baseline.get("tolerance_oku", DEFAULT_TOLERANCE_OKU))
    records = []
    for code in codes:
        expected = baseline.get("records", {}).get(code)
        doc_id = expected.get("doc_id") if expected else None
        metadata = {
            key: expected.get(key, "")
            for key in (
                "period_end",
                "submitted_at",
                "document_description",
                "filer_name",
            )
        } if expected else {}
        records.append(_extract_record(
            code, doc_id, metadata, expected, "pinned", tolerance
        ))
    return records


def summarize_records(records):
    extraction = collections.Counter(
        record.get("extraction_status", "unknown") for record in records
    )
    comparisons = collections.Counter(
        record.get("comparison_status", "unknown") for record in records
    )
    outcomes = collections.Counter(
        record.get("real_estate_outcome", "unknown") for record in records
    )
    verification = collections.Counter(
        record.get("automated_verification", {}).get("status", "not_run")
        for record in records
    )
    return {
        "record_count": len(records),
        "extraction_statuses": dict(sorted(extraction.items())),
        "comparison_statuses": dict(sorted(comparisons.items())),
        "real_estate_outcomes": dict(sorted(outcomes.items())),
        "automated_verification_statuses": dict(sorted(verification.items())),
        "regression_codes": [
            record["code"] for record in records
            if record.get("comparison_status") == "regression"
        ],
        "review_required_codes": [
            record["code"] for record in records
            if record.get("comparison_status") == "review_required"
        ],
        "rows": records,
    }


def build_candidate_baseline(records, tolerance_oku=DEFAULT_TOLERANCE_OKU):
    baseline_records = {}
    for record in records:
        if record.get("extraction_status") != "extracted":
            continue
        baseline_records[record["code"]] = {
            key: record.get(key, "")
            for key in (
                "doc_id",
                "period_end",
                "submitted_at",
                "document_description",
                "filer_name",
                *VALUE_FIELDS,
            )
        }
    return {
        "version": 1,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "tolerance_oku": tolerance_oku,
        "records": baseline_records,
    }


def render_markdown(summary, title):
    extraction = ", ".join(
        f"{key}: {value}"
        for key, value in summary["extraction_statuses"].items()
    ) or "none"
    comparisons = ", ".join(
        f"{key}: {value}"
        for key, value in summary["comparison_statuses"].items()
    ) or "none"
    outcomes = ", ".join(
        f"{key}: {value}"
        for key, value in summary["real_estate_outcomes"].items()
    ) or "none"
    verification = ", ".join(
        f"{key}: {value}"
        for key, value in summary["automated_verification_statuses"].items()
    ) or "none"
    lines = [
        f"# {title}",
        "",
        f"- Records: {summary['record_count']}",
        f"- Extraction: {extraction}",
        f"- Comparison: {comparisons}",
        f"- Outcomes: {outcomes}",
        f"- Automated verification: {verification}",
        "",
        "| Code | Document | Period | Extraction | Outcome | Verification | Comparison | Book (oku) | Market (oku) | Gain (oku) |",
        "|---|---|---|---|---|---|---|---:|---:|---:|",
    ]
    for row in summary["rows"]:
        lines.append(
            "| {code} | {doc_id} | {period_end} | {extraction_status} | {real_estate_outcome} | "
            "{verification} | {comparison_status} | {book_value_oku:.2f} | {market_value_oku:.2f} | "
            "{hidden_gain_oku:.2f} |".format(
                verification=row.get("automated_verification", {}).get(
                    "status", "not_run"
                ),
                **row,
            )
        )
    if summary["regression_codes"]:
        lines.extend(["", "Regression codes: " + ", ".join(summary["regression_codes"])])
    if summary["review_required_codes"]:
        lines.extend([
            "",
            "Latest document changed; manual review required: "
            + ", ".join(summary["review_required_codes"]),
        ])
    return "\n".join(lines) + "\n"


def write_outputs(records, output_dir, mode, candidate_baseline_path=None):
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    for record in records:
        path = output_path / f"real_estate_{mode}_{record['code']}.json"
        path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    summary = summarize_records(records)
    summary_json = output_path / f"real_estate_{mode}_summary.json"
    summary_md = output_path / f"real_estate_{mode}_summary.md"
    summary_json.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    summary_md.write_text(
        render_markdown(summary, f"Real-estate diagnostics ({mode})"),
        encoding="utf-8",
    )

    if candidate_baseline_path:
        candidate_path = Path(candidate_baseline_path)
        candidate_path.parent.mkdir(parents=True, exist_ok=True)
        candidate_path.write_text(
            json.dumps(build_candidate_baseline(records), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return summary


def main():
    parser = argparse.ArgumentParser(description="Real-estate extraction diagnostics")
    parser.add_argument("--codes", default="", help="Comma-separated security codes")
    parser.add_argument(
        "--test-set",
        choices=sorted(REAL_ESTATE_TEST_SETS),
        default="regression-5",
    )
    parser.add_argument("--mode", choices=("latest", "pinned"), default="latest")
    parser.add_argument("--days-back", type=int, default=730)
    parser.add_argument("--baseline", default="real_estate_baseline.json")
    parser.add_argument("--output-dir", default="real_estate_diagnostics")
    parser.add_argument("--write-candidate-baseline")
    parser.add_argument("--fail-on-regression", action="store_true")
    args = parser.parse_args()

    if not EDINET_API_KEY:
        raise RuntimeError("EDINET_API_KEY is required")

    codes = sorted(set(parse_codes_arg(args.codes) or []) | set(
        get_real_estate_test_set_codes(args.test_set)
    ))
    baseline = load_baseline(args.baseline)
    if args.mode == "pinned" and not baseline.get("records"):
        raise ValueError("Pinned mode requires a populated baseline file")

    if args.mode == "latest":
        records = run_latest(codes, baseline, args.days_back)
    else:
        records = run_pinned(codes, baseline)

    summary = write_outputs(
        records,
        args.output_dir,
        args.mode,
        args.write_candidate_baseline,
    )
    print(render_markdown(summary, f"Real-estate diagnostics ({args.mode})"))

    if args.fail_on_regression and summary["regression_codes"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
