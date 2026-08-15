import io
import math
import re
import unicodedata

import pandas as pd


CURRENT_PERIOD_MARKERS = (
    "当連結会計年度",
    "当事業年度",
    "当会計年度",
    "当年度",
    "当期",
)
PREVIOUS_PERIOD_MARKERS = (
    "前連結会計年度",
    "前事業年度",
    "前会計年度",
    "前年度",
    "前期",
)
REAL_ESTATE_MARKERS = ("賃貸等不動産", "投資不動産")
BOOK_MARKERS = ("貸借対照表計上額", "財政状態計算書計上額", "帳簿価額")
MARKET_MARKERS = ("期末時価", "公正価値", "時価")
BOOK_EXCLUDES = ("期首", "増減", "償却", "損益", "収益", "費用")


def normalize_text(value):
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    return re.sub(r"[\s\u3000]+", "", text)


def parse_numeric_cell(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        return float(value)

    text = unicodedata.normalize("NFKC", str(value)).strip()
    if not text or text.lower() == "nan" or text in ("-", "―", "—"):
        return None
    negative_parentheses = text.startswith("(") and text.endswith(")")
    text = text.replace("△", "-").replace("▲", "-").replace(",", "")
    text = re.sub(r"※\d+", "", text)
    text = re.sub(r"\(注\d*\)", "", text)
    text = text.replace("円", "").replace("千", "").replace("百万", "")
    text = text.strip()
    if negative_parentheses:
        text = "-" + text[1:-1]
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        return None
    return float(text)


def detect_unit(table_text, context_text):
    for source_name, source_text in (
        ("table", table_text),
        ("context", context_text),
    ):
        text = normalize_text(source_text)
        if re.search(r"(?:単位[:：]?)?[（(]?百万円[）)]?", text):
            return {
                "multiplier": 1000000,
                "label": "百万円",
                "source": source_name,
                "explicit": True,
            }
        if re.search(r"(?:単位[:：]?)?[（(]?千円[）)]?", text):
            return {
                "multiplier": 1000,
                "label": "千円",
                "source": source_name,
                "explicit": True,
            }
        if re.search(r"単位[:：]?円", text):
            return {
                "multiplier": 1,
                "label": "円",
                "source": source_name,
                "explicit": True,
            }
    return {
        "multiplier": None,
        "label": "unknown",
        "source": None,
        "explicit": False,
    }


def _contains_any(text, markers):
    return any(marker in text for marker in markers)


def _column_period_score(header_text, context_text, column_index):
    score = column_index
    current_explicit = _contains_any(header_text, CURRENT_PERIOD_MARKERS)
    previous_explicit = _contains_any(header_text, PREVIOUS_PERIOD_MARKERS)
    if current_explicit:
        score += 200
    if previous_explicit:
        score -= 200
    if not current_explicit and _contains_any(context_text, CURRENT_PERIOD_MARKERS):
        score += 10
    return score, current_explicit, previous_explicit


def _resolve_rows(rows):
    if not rows:
        return 0.0, "missing"
    unique = []
    seen = set()
    for row in rows:
        key = (row["label"], row["value"])
        if key not in seen:
            seen.add(key)
            unique.append(row)

    total_rows = [row for row in unique if "合計" in row["label"]]
    if total_rows:
        return max(total_rows, key=lambda row: abs(row["value"]))["value"], "explicit_total"
    if len(unique) == 1:
        return unique[0]["value"], "single_row"

    values = [row["value"] for row in unique]
    largest = max(values)
    rest = sum(values) - largest
    if largest > 0 and rest > 0 and abs(largest - rest) <= max(1.0, largest * 0.001):
        return largest, "parent_matches_details"
    return sum(values), "summed_distinct_rows"


def _extract_period_layout(df, context_text):
    rows, cols = df.shape
    candidates = []
    for column in range(1, cols):
        column_name = normalize_text(df.columns[column])
        header_text = column_name + "".join(
            normalize_text(df.iloc[row, column]) for row in range(min(8, rows))
        )
        numeric_count = sum(
            parse_numeric_cell(df.iloc[row, column]) is not None for row in range(rows)
        )
        if numeric_count == 0:
            continue
        score, current_explicit, previous_explicit = _column_period_score(
            header_text, context_text, column
        )
        candidates.append({
            "column": column,
            "header": header_text,
            "score": score,
            "current_explicit": current_explicit,
            "previous_explicit": previous_explicit,
            "numeric_count": numeric_count,
        })
    if not candidates:
        return None

    selected_column = max(candidates, key=lambda item: item["score"])
    column = selected_column["column"]
    book_rows = []
    market_rows = []
    for row in range(rows):
        value = parse_numeric_cell(df.iloc[row, column])
        if value is None:
            continue
        label = "".join(normalize_text(df.iloc[row, c]) for c in range(column))
        is_book = (
            ("期末" in label and ("残高" in label or _contains_any(label, BOOK_MARKERS)))
            or (_contains_any(label, BOOK_MARKERS) and not _contains_any(label, BOOK_EXCLUDES))
        )
        if is_book and not _contains_any(label, BOOK_EXCLUDES):
            book_rows.append({"row": row, "label": label, "value": value})
        if _contains_any(label, MARKET_MARKERS) and "損益" not in label:
            market_rows.append({"row": row, "label": label, "value": value})

    book, book_resolution = _resolve_rows(book_rows)
    market, market_resolution = _resolve_rows(market_rows)
    return {
        "layout": "period_columns",
        "target_column": column,
        "column_candidates": candidates,
        "current_period_explicit": selected_column["current_explicit"],
        "book_rows": book_rows,
        "market_rows": market_rows,
        "book_raw": book,
        "market_raw": market,
        "book_resolution": book_resolution,
        "market_resolution": market_resolution,
    }


def extract_table_candidate(table_soup, context_text, file_name="", table_index=0):
    table_text = normalize_text(table_soup.get_text(" "))
    context = normalize_text(context_text)
    combined = context + table_text
    unit = detect_unit(table_soup.get_text(" "), context_text)
    candidate = {
        "file": file_name,
        "table_index": table_index,
        "unit": unit,
        "table_relevant": _contains_any(combined, REAL_ESTATE_MARKERS),
        "loss_table": (
            "賃貸収益" in table_text
            and "賃貸費用" in table_text
            and "期末時価" not in table_text
        ),
        "score": 0,
        "quality_status": "quarantined",
        "quality_reasons": [],
        "book_value_yen": 0,
        "market_value_yen": 0,
    }
    try:
        frames = pd.read_html(io.StringIO(str(table_soup)), header=None)
        if not frames:
            candidate["quality_reasons"].append("table_parse_empty")
            return candidate
        df = frames[0]
    except Exception as exc:
        candidate["quality_reasons"].append(
            f"table_parse_failed:{type(exc).__name__}"
        )
        return candidate

    candidate["shape"] = [int(df.shape[0]), int(df.shape[1])]
    layout = _extract_period_layout(df, context)
    candidate["layout_result"] = layout
    if not layout:
        candidate["quality_reasons"].append("period_value_columns_not_found")
        return candidate

    score = 0
    if candidate["table_relevant"]:
        score += 100
    if candidate["loss_table"]:
        score -= 500
    if layout["book_raw"] > 0 and layout["market_raw"] > 0:
        score += 500
    if layout["current_period_explicit"]:
        score += 100
    if unit["explicit"]:
        score += 80
    if layout["book_rows"]:
        score += 40
    if layout["market_rows"]:
        score += 40
    if "連結" in combined:
        score += 20
    candidate["score"] = score

    if not unit["explicit"]:
        candidate["quality_reasons"].append("unit_not_explicit")
    if not layout["current_period_explicit"]:
        candidate["quality_reasons"].append("current_period_not_explicit")
    if not layout["book_rows"]:
        candidate["quality_reasons"].append("book_row_not_found")
    if not layout["market_rows"]:
        candidate["quality_reasons"].append("market_row_not_found")
    if candidate["loss_table"]:
        candidate["quality_reasons"].append("rental_profit_table_excluded")

    multiplier = unit["multiplier"]
    if multiplier and layout["book_raw"] > 0 and layout["market_raw"] > 0:
        candidate["book_value_yen"] = int(round(layout["book_raw"] * multiplier))
        candidate["market_value_yen"] = int(round(layout["market_raw"] * multiplier))

    if not candidate["quality_reasons"]:
        candidate["quality_status"] = "verified"
    elif candidate["book_value_yen"] > 0 and candidate["market_value_yen"] > 0:
        candidate["quality_status"] = "partial"
    return candidate


def select_real_estate_candidate(candidates):
    usable = [
        (index, candidate)
        for index, candidate in enumerate(candidates)
        if candidate.get("book_value_yen", 0) > 0
        and candidate.get("market_value_yen", 0) > 0
        and not candidate.get("loss_table", False)
    ]
    if not usable:
        return {
            "quality_status": "not_found",
            "quality_reasons": ["no_table_with_book_and_market_values"],
            "selected_candidate": None,
            "book_value_yen": 0,
            "market_value_yen": 0,
        }

    usable.sort(key=lambda item: item[1].get("score", 0), reverse=True)
    selected_index, selected = usable[0]
    reasons = list(selected.get("quality_reasons", []))
    quality = selected.get("quality_status", "quarantined")
    if len(usable) > 1:
        _, second = usable[1]
        values_differ = (
            selected["book_value_yen"] != second["book_value_yen"]
            or selected["market_value_yen"] != second["market_value_yen"]
        )
        if values_differ and selected.get("score", 0) - second.get("score", 0) < 50:
            quality = "quarantined"
            reasons.append("competing_tables_with_different_values")

    return {
        "quality_status": quality,
        "quality_reasons": reasons,
        "selected_candidate": selected_index,
        "book_value_yen": selected["book_value_yen"],
        "market_value_yen": selected["market_value_yen"],
        "hidden_gain_yen": selected["market_value_yen"] - selected["book_value_yen"],
        "score": selected.get("score", 0),
    }
