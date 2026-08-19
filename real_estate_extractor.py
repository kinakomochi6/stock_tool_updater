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
MARKET_ROW_EXCLUDES = (
    "金融資産", "金融負債", "その他の包括利益", "を通じて", "測定する",
    "変動", "収益", "費用", "損益",
)
BOOK_EXCLUDES = ("期首", "増減", "償却", "損益", "収益", "費用")
DIRECT_BOOK_EXCLUDES = BOOK_EXCLUDES + (
    "取得原価", "減損", "累計", "売却", "公正価値", "時価",
)
OMISSION_MARKERS = (
    "該当事項はありません",
    "該当ありません",
    "該当なし",
    "記載を省略",
    "重要性が乏しい",
    "重要性がない",
)


def normalize_text(value):
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    return re.sub(r"[\s\u3000]+", "", text)


def find_nearby_omission_markers(text, radius=500):
    normalized = normalize_text(text)
    found = set()
    for real_estate_marker in REAL_ESTATE_MARKERS:
        for match in re.finditer(re.escape(real_estate_marker), normalized):
            start = max(0, match.start() - radius)
            end = min(len(normalized), match.end() + radius)
            nearby = normalized[start:end]
            found.update(
                marker for marker in OMISSION_MARKERS
                if marker in nearby
            )
    return sorted(found)


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


def _is_direct_real_estate_book_label(label):
    if _contains_any(label, DIRECT_BOOK_EXCLUDES):
        return False
    for marker in REAL_ESTATE_MARKERS:
        marker_position = label.rfind(marker)
        if marker_position < 0:
            continue
        suffix = label[marker_position + len(marker):]
        if not suffix or re.fullmatch(r"(?:[（(]?注?\d+[）)]?)?", suffix):
            return True
    return False


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
    opening_rows = []
    for row in range(rows):
        value = parse_numeric_cell(df.iloc[row, column])
        if value is None:
            continue
        label = "".join(normalize_text(df.iloc[row, c]) for c in range(column))
        if "期首" in label and "残高" in label:
            opening_rows.append({"row": row, "label": label, "value": value})
        is_book = (
            ("期末" in label and ("残高" in label or _contains_any(label, BOOK_MARKERS)))
            or (_contains_any(label, BOOK_MARKERS) and not _contains_any(label, BOOK_EXCLUDES))
            or _is_direct_real_estate_book_label(label)
        )
        if is_book and not _contains_any(label, BOOK_EXCLUDES):
            book_rows.append({"row": row, "label": label, "value": value})
        if (
            _contains_any(label, MARKET_MARKERS)
            and not _contains_any(label, MARKET_ROW_EXCLUDES)
        ):
            market_rows.append({"row": row, "label": label, "value": value})

    book, book_resolution = _resolve_rows(book_rows)
    market, market_resolution = _resolve_rows(market_rows)
    opening, opening_resolution = _resolve_rows(opening_rows)
    return {
        "layout": "period_columns",
        "target_column": column,
        "column_candidates": candidates,
        "current_period_explicit": selected_column["current_explicit"],
        "previous_period_explicit": selected_column["previous_explicit"],
        "book_rows": book_rows,
        "market_rows": market_rows,
        "opening_rows": opening_rows,
        "book_raw": book,
        "market_raw": market,
        "opening_raw": opening,
        "book_resolution": book_resolution,
        "market_resolution": market_resolution,
        "opening_resolution": opening_resolution,
    }


def _extract_dated_balance_layout(df, table_text, context_text):
    combined = normalize_text(context_text) + normalize_text(table_text)
    if not _contains_any(combined, REAL_ESTATE_MARKERS):
        return None

    immediate_context = normalize_text(context_text)[-600:]
    normalized_table = normalize_text(table_text)
    if "公正価値" in normalized_table or "公正価値" in immediate_context[-200:]:
        value_kind = "fair_value"
    elif (
        "減価償却累計額" in immediate_context
        or "減損損失累計額" in immediate_context
        or "減価償却累計額" in normalized_table
    ):
        value_kind = "accumulated_depreciation"
    elif "取得原価" in immediate_context or "取得原価" in normalized_table:
        value_kind = "acquisition_cost"
    else:
        return None

    dated_rows = []
    for row in range(df.shape[0]):
        row_text = "".join(normalize_text(df.iloc[row, column]) for column in range(df.shape[1]))
        period = _period_end_hint(row_text)
        if not period or "残高" not in row_text:
            continue
        numeric_values = [
            parse_numeric_cell(df.iloc[row, column])
            for column in range(df.shape[1])
        ]
        numeric_values = [value for value in numeric_values if value is not None]
        if not numeric_values:
            continue
        dated_rows.append({
            "row": row,
            "label": row_text,
            "period": period,
            "value": numeric_values[-1],
        })
    if len(dated_rows) < 2:
        return None

    selected = max(dated_rows, key=lambda row: row["period"])
    value = selected["value"]
    result = {
        "layout": "dated_balance_rows",
        "value_kind": value_kind,
        "current_period_explicit": True,
        "previous_period_explicit": False,
        "selected_period": selected["period"],
        "dated_rows": dated_rows,
        "book_rows": [],
        "market_rows": [],
        "book_raw": 0.0,
        "market_raw": 0.0,
        "gross_raw": 0.0,
        "accumulated_raw": 0.0,
        "book_resolution": "missing",
        "market_resolution": "missing",
    }
    if value_kind == "acquisition_cost" and value > 0:
        result["gross_raw"] = value
    elif value_kind == "accumulated_depreciation" and value < 0:
        result["accumulated_raw"] = value
    elif value_kind == "fair_value" and value > 0:
        result["market_raw"] = value
        result["market_rows"] = [selected]
        result["market_resolution"] = "dated_balance_row"
    return result


def _extract_horizontal_layout(df, table_text, context_text):
    rows, cols = df.shape
    descriptors = []
    for column in range(1, cols):
        descriptor = normalize_text(df.columns[column]) + "".join(
            normalize_text(df.iloc[row, column]) for row in range(min(3, rows))
        )
        descriptors.append((column, descriptor))

    book_columns = [
        (column, descriptor)
        for column, descriptor in descriptors
        if (
            "期末残高" in descriptor
            or "年度末残高" in descriptor
            or _contains_any(descriptor, BOOK_MARKERS)
        )
    ]
    market_columns = [
        (column, descriptor)
        for column, descriptor in descriptors
        if _contains_any(descriptor, MARKET_MARKERS)
    ]
    combined = table_text + context_text
    if (
        not book_columns
        or not market_columns
        or not _contains_any(combined, REAL_ESTATE_MARKERS)
    ):
        return None

    current_book_columns = [
        item for item in book_columns
        if _contains_any(item[1], CURRENT_PERIOD_MARKERS)
    ]
    current_market_columns = [
        item for item in market_columns
        if _contains_any(item[1], CURRENT_PERIOD_MARKERS)
    ]
    selected_book = (current_book_columns or book_columns)[-1]
    selected_market = (current_market_columns or market_columns)[-1]
    book_column, book_descriptor = selected_book
    market_column, market_descriptor = selected_market
    if book_column == market_column:
        return None

    value_rows = []
    label_limit = min(book_column, market_column)
    for row in range(rows):
        book = parse_numeric_cell(df.iloc[row, book_column])
        market = parse_numeric_cell(df.iloc[row, market_column])
        if book is None or market is None:
            continue
        label = "".join(
            normalize_text(df.iloc[row, column]) for column in range(label_limit)
        )
        value_rows.append({
            "row": row,
            "label": label,
            "book": book,
            "market": market,
        })
    if not value_rows:
        return None

    total_rows = [row for row in value_rows if "合計" in row["label"]]
    selected_rows = total_rows[-1:] if total_rows else value_rows
    book = sum(row["book"] for row in selected_rows)
    market = sum(row["market"] for row in selected_rows)
    return {
        "layout": "book_market_columns",
        "book_column": book_column,
        "market_column": market_column,
        "column_descriptors": [
            {"column": column, "text": descriptor}
            for column, descriptor in descriptors
        ],
        "current_period_explicit": all(
            _contains_any(descriptor, CURRENT_PERIOD_MARKERS)
            for descriptor in (book_descriptor, market_descriptor)
        ),
        "previous_period_explicit": any(
            _contains_any(descriptor, PREVIOUS_PERIOD_MARKERS)
            for descriptor in (book_descriptor, market_descriptor)
        ),
        "value_rows": value_rows,
        "selected_rows": selected_rows,
        "book_raw": book,
        "market_raw": market,
        "book_resolution": "explicit_total" if total_rows else "summed_category_rows",
        "market_resolution": "explicit_total" if total_rows else "summed_category_rows",
        "book_rows": [
            {"row": row["row"], "label": row["label"], "value": row["book"]}
            for row in selected_rows
        ],
        "market_rows": [
            {"row": row["row"], "label": row["label"], "value": row["market"]}
            for row in selected_rows
        ],
    }


def _extract_fair_value_model_layout(df, context_text):
    context = normalize_text(context_text)
    if not _contains_any(context, REAL_ESTATE_MARKERS):
        return None
    fair_value_accounting = (
        "公正価値モデル" in context
        or re.search(
            r"公正価値.{0,80}(?:で計上|により測定|によって測定)", context
        )
    )
    if not fair_value_accounting:
        return None

    period_layout = _extract_period_layout(df, context)
    if not period_layout or not period_layout.get("current_period_explicit"):
        return None
    column = period_layout["target_column"]
    closing_rows = []
    for row in range(df.shape[0]):
        value = parse_numeric_cell(df.iloc[row, column])
        if value is None:
            continue
        label = "".join(
            normalize_text(df.iloc[row, cell_column])
            for cell_column in range(column)
        )
        if any(
            marker in label
            for marker in ("期末残高", "報告期間末", "年度末", "3月31日現在", "12月31日現在")
        ):
            closing_rows.append({"row": row, "label": label, "value": value})
    if len(closing_rows) != 1 or closing_rows[0]["value"] <= 0:
        return None

    closing = closing_rows[0]
    return {
        "layout": "fair_value_model",
        "target_column": column,
        "column_candidates": period_layout.get("column_candidates", []),
        "current_period_explicit": True,
        "previous_period_explicit": False,
        "book_rows": [closing],
        "market_rows": [closing],
        "book_raw": closing["value"],
        "market_raw": closing["value"],
        "book_resolution": "fair_value_model",
        "market_resolution": "fair_value_model",
    }


def _period_end_hint(text):
    normalized = unicodedata.normalize("NFKC", str(text))
    dates = []
    for year, month, day in re.findall(
        r"(20\d{2})年(\d{1,2})月(?:(\d{1,2})日|期)", normalized
    ):
        dates.append((int(year), int(month), int(day or 1)))
    return max(dates) if dates else None


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
        "period_end_hint": _period_end_hint(combined),
        "guarantor_section": "保証会社" in combined,
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
    period_layout = _extract_period_layout(df, context)
    horizontal_layout = _extract_horizontal_layout(df, table_text, context)
    fair_value_layout = _extract_fair_value_model_layout(df, context)
    dated_balance_layout = _extract_dated_balance_layout(
        df, table_text, context
    )
    layouts = [
        layout for layout in (
            period_layout, horizontal_layout, fair_value_layout,
            dated_balance_layout,
        ) if layout
    ]
    layout = max(
        layouts,
        key=lambda item: (
            item.get("book_raw", 0) > 0 and item.get("market_raw", 0) > 0,
            sum(bool(item.get(key, 0)) for key in (
                "book_raw", "market_raw", "gross_raw", "accumulated_raw",
            )),
            item.get("current_period_explicit", False),
            item.get("layout") in (
                "book_market_columns", "fair_value_model", "dated_balance_rows",
            ),
        ),
        default=None,
    )
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
    if candidate["guarantor_section"]:
        score -= 200
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
    if candidate["guarantor_section"]:
        candidate["quality_reasons"].append("guarantor_section")

    multiplier = unit["multiplier"]
    if multiplier and layout["book_raw"] > 0 and layout["market_raw"] > 0:
        candidate["book_value_yen"] = int(round(layout["book_raw"] * multiplier))
        candidate["market_value_yen"] = int(round(layout["market_raw"] * multiplier))

    if not candidate["quality_reasons"]:
        candidate["quality_status"] = "verified"
    elif candidate["book_value_yen"] > 0 and candidate["market_value_yen"] > 0:
        candidate["quality_status"] = "partial"
    return candidate


def expand_complementary_candidates(candidates):
    expanded = list(candidates)

    dated_candidates = [
        (index, candidate, candidate.get("layout_result") or {})
        for index, candidate in enumerate(candidates)
        if (candidate.get("layout_result") or {}).get("layout")
        == "dated_balance_rows"
    ]
    for cost_index, cost, cost_layout in dated_candidates:
        if cost_layout.get("gross_raw", 0) <= 0:
            continue
        for accumulated_index, accumulated, accumulated_layout in dated_candidates:
            if accumulated_layout.get("accumulated_raw", 0) >= 0:
                continue
            for fair_index, fair, fair_layout in dated_candidates:
                if fair_layout.get("market_raw", 0) <= 0:
                    continue
                ordered_indices = [
                    cost.get("table_index"), accumulated.get("table_index"),
                    fair.get("table_index"),
                ]
                if not all(isinstance(index, int) for index in ordered_indices):
                    continue
                if not ordered_indices[0] < ordered_indices[1] < ordered_indices[2]:
                    continue
                if ordered_indices[2] - ordered_indices[0] > 5:
                    continue
                if len({
                    cost.get("file"), accumulated.get("file"), fair.get("file")
                }) != 1:
                    continue
                source_candidates = (cost, accumulated, fair)
                if not all(candidate.get("table_relevant") for candidate in source_candidates):
                    continue
                if any(
                    candidate.get(flag)
                    for candidate in source_candidates
                    for flag in ("loss_table", "guarantor_section")
                ):
                    continue
                units = [candidate.get("unit", {}) for candidate in source_candidates]
                if not all(unit.get("explicit") for unit in units):
                    continue
                if len({unit.get("multiplier") for unit in units}) != 1:
                    continue
                periods = [
                    layout.get("selected_period")
                    for layout in (cost_layout, accumulated_layout, fair_layout)
                ]
                if not all(periods) or len(set(periods)) != 1:
                    continue
                if not all(
                    layout.get("current_period_explicit")
                    for layout in (cost_layout, accumulated_layout, fair_layout)
                ):
                    continue

                gross = cost_layout["gross_raw"]
                accumulated_amount = accumulated_layout["accumulated_raw"]
                book = gross + accumulated_amount
                market = fair_layout["market_raw"]
                if book <= 0 or market <= 0:
                    continue
                multiplier = units[0]["multiplier"]
                expanded.append({
                    "file": cost.get("file", ""),
                    "table_index": ordered_indices,
                    "source_candidate_indices": [
                        cost_index, accumulated_index, fair_index,
                    ],
                    "unit": units[0],
                    "table_relevant": True,
                    "loss_table": False,
                    "guarantor_section": False,
                    "score": max(
                        candidate.get("score", 0)
                        for candidate in source_candidates
                    ) + 220,
                    "quality_status": "verified",
                    "quality_reasons": [],
                    "book_value_yen": int(round(book * multiplier)),
                    "market_value_yen": int(round(market * multiplier)),
                    "period_end_hint": periods[0],
                    "layout_result": {
                        "layout": "cost_accumulation_fair_value_tables",
                        "current_period_explicit": True,
                        "previous_period_explicit": False,
                        "gross_raw": gross,
                        "accumulated_raw": accumulated_amount,
                        "book_raw": book,
                        "market_raw": market,
                        "book_rows": cost_layout.get("dated_rows", [])
                        + accumulated_layout.get("dated_rows", []),
                        "market_rows": fair_layout.get("market_rows", []),
                        "book_resolution": "gross_less_accumulated",
                        "market_resolution": "dated_balance_row",
                    },
                })

    for left_index, left in enumerate(candidates):
        left_layout = left.get("layout_result") or {}
        for right_index in range(left_index + 1, len(candidates)):
            right = candidates[right_index]
            right_layout = right.get("layout_result") or {}
            if left.get("file") != right.get("file"):
                continue
            table_gap = abs(
                left.get("table_index", -100) - right.get("table_index", 100)
            )
            if table_gap < 1 or table_gap > 5:
                continue
            if not left.get("table_relevant") or not right.get("table_relevant"):
                continue
            if any(
                candidate.get(flag)
                for candidate in (left, right)
                for flag in ("loss_table", "guarantor_section")
            ):
                continue

            left_unit = left.get("unit", {})
            right_unit = right.get("unit", {})
            if (
                not left_unit.get("explicit")
                or not right_unit.get("explicit")
                or left_unit.get("multiplier") != right_unit.get("multiplier")
            ):
                continue
            if table_gap > 1:
                left_period = left.get("period_end_hint")
                right_period = right.get("period_end_hint")
                if not left_period or left_period != right_period:
                    continue
            if not all(
                layout.get("current_period_explicit")
                and not layout.get("previous_period_explicit", False)
                for layout in (left_layout, right_layout)
            ):
                continue

            left_book = left_layout.get("book_raw", 0)
            left_market = left_layout.get("market_raw", 0)
            right_book = right_layout.get("book_raw", 0)
            right_market = right_layout.get("market_raw", 0)
            if left_book > 0 and left_market == 0 and right_book == 0 and right_market > 0:
                book_candidate, market_candidate = left, right
                book_layout, market_layout = left_layout, right_layout
            elif right_book > 0 and right_market == 0 and left_book == 0 and left_market > 0:
                book_candidate, market_candidate = right, left
                book_layout, market_layout = right_layout, left_layout
            else:
                continue

            multiplier = left_unit["multiplier"]
            period_hints = [
                hint for hint in (
                    left.get("period_end_hint"),
                    right.get("period_end_hint"),
                ) if hint
            ]
            layout_name = (
                "adjacent_book_market_tables"
                if table_gap == 1
                else "nearby_book_market_tables"
            )
            resolution = "adjacent_table" if table_gap == 1 else "nearby_table"
            expanded.append({
                "file": left.get("file", ""),
                "table_index": [
                    left.get("table_index"),
                    right.get("table_index"),
                ],
                "source_candidate_indices": [left_index, right_index],
                "unit": left_unit,
                "table_relevant": True,
                "loss_table": False,
                "guarantor_section": False,
                "score": (
                    max(left.get("score", 0), right.get("score", 0))
                    + 150
                    - (table_gap - 1) * 10
                ),
                "quality_status": "verified",
                "quality_reasons": [],
                "book_value_yen": int(round(book_layout["book_raw"] * multiplier)),
                "market_value_yen": int(round(market_layout["market_raw"] * multiplier)),
                "period_end_hint": max(period_hints) if period_hints else None,
                "layout_result": {
                    "layout": layout_name,
                    "current_period_explicit": True,
                    "previous_period_explicit": False,
                    "book_raw": book_layout["book_raw"],
                    "market_raw": market_layout["market_raw"],
                    "book_rows": book_layout.get("book_rows", []),
                    "market_rows": market_layout.get("market_rows", []),
                    "book_source_table": book_candidate.get("table_index"),
                    "market_source_table": market_candidate.get("table_index"),
                    "book_resolution": resolution,
                    "market_resolution": resolution,
                },
            })

    original_candidates = list(candidates)
    for prior_index, prior in enumerate(original_candidates):
        prior_layout = prior.get("layout_result") or {}
        if prior_layout.get("book_raw", 0) <= 0 or prior_layout.get("market_raw", 0) <= 0:
            continue
        for current_index in range(prior_index + 1, len(original_candidates)):
            current = original_candidates[current_index]
            current_layout = current.get("layout_result") or {}
            if prior.get("file") != current.get("file"):
                continue
            if current.get("table_index", -100) - prior.get("table_index", 100) != 1:
                continue
            if not prior.get("table_relevant") or not current.get("table_relevant"):
                continue
            if any(
                candidate.get(flag)
                for candidate in (prior, current)
                for flag in ("loss_table", "guarantor_section")
            ):
                continue
            prior_unit = prior.get("unit", {})
            current_unit = current.get("unit", {})
            if (
                not prior_unit.get("explicit")
                or not current_unit.get("explicit")
                or prior_unit.get("multiplier") != current_unit.get("multiplier")
            ):
                continue
            if any(
                layout.get("current_period_explicit")
                or layout.get("previous_period_explicit")
                for layout in (prior_layout, current_layout)
            ):
                continue
            opening = current_layout.get("opening_raw", 0)
            if opening <= 0 or not math.isclose(
                prior_layout["book_raw"], opening, rel_tol=0.001, abs_tol=1.0
            ):
                continue

            multiplier = current_unit["multiplier"]
            expanded.append({
                "file": current.get("file", ""),
                "table_index": [
                    prior.get("table_index"),
                    current.get("table_index"),
                ],
                "source_candidate_indices": [prior_index, current_index],
                "unit": current_unit,
                "table_relevant": True,
                "loss_table": False,
                "guarantor_section": False,
                "score": max(prior.get("score", 0), current.get("score", 0)) + 150,
                "quality_status": "verified",
                "quality_reasons": [],
                "book_value_yen": int(round(current_layout["book_raw"] * multiplier)),
                "market_value_yen": int(round(current_layout["market_raw"] * multiplier)),
                "period_end_hint": current.get("period_end_hint"),
                "layout_result": {
                    "layout": "rollforward_continuity",
                    "current_period_explicit": True,
                    "previous_period_explicit": False,
                    "book_raw": current_layout["book_raw"],
                    "market_raw": current_layout["market_raw"],
                    "opening_raw": opening,
                    "book_rows": current_layout.get("book_rows", []),
                    "market_rows": current_layout.get("market_rows", []),
                    "prior_closing_book_raw": prior_layout["book_raw"],
                    "book_resolution": "rollforward_continuity",
                    "market_resolution": "rollforward_continuity",
                },
            })
    return expanded


def classify_real_estate_outcome(candidates, selection, scan_stats=None):
    scan_stats = scan_stats or {}
    quality = selection.get("quality_status", "not_found")
    reasons = list(selection.get("quality_reasons", []))
    if quality == "verified":
        return {
            "classification": "extracted_structural",
            "reasons": [],
        }
    if "competing_tables_with_different_values" in reasons:
        return {
            "classification": "competing_tables",
            "reasons": reasons,
        }
    if "current_period_not_explicit" in reasons:
        return {
            "classification": "current_period_table_missing",
            "reasons": reasons,
        }

    layouts = [candidate.get("layout_result") or {} for candidate in candidates]
    has_book = any(layout.get("book_raw", 0) > 0 for layout in layouts)
    has_market = any(layout.get("market_raw", 0) > 0 for layout in layouts)
    if has_book and has_market:
        classification = "separate_values_not_safely_pairable"
    elif has_book:
        classification = "book_value_only"
    elif has_market:
        classification = "market_value_only"
    elif any(
        "unit_not_explicit" in candidate.get("quality_reasons", [])
        for candidate in candidates
    ):
        classification = "unit_not_explicit"
    elif candidates:
        classification = "unsupported_table_structure"
    elif scan_stats.get("omission_markers"):
        classification = "disclosure_omitted_or_not_applicable"
    elif scan_stats.get("files_with_real_estate_markers", 0) > 0:
        classification = "text_only_or_unsupported_disclosure"
    else:
        classification = "no_relevant_disclosure_detected"
    return {
        "classification": classification,
        "reasons": reasons,
    }


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

    period_hints = [
        candidate.get("period_end_hint")
        for _, candidate in usable
        if candidate.get("period_end_hint")
    ]
    latest_hint = max(period_hints) if period_hints else None
    if latest_hint:
        latest_usable = [
            item for item in usable if item[1].get("period_end_hint") == latest_hint
        ]
        if latest_usable:
            usable = latest_usable
    usable.sort(key=lambda item: item[1].get("score", 0), reverse=True)
    selected_index, selected = usable[0]
    reasons = list(selected.get("quality_reasons", []))
    quality = selected.get("quality_status", "quarantined")
    reasons = [reason for reason in reasons if reason != "guarantor_section"]
    if selected.get("guarantor_section"):
        quality = "quarantined"
        reasons.append("guarantor_section")
    elif (
        selected.get("unit", {}).get("explicit")
        and selected.get("layout_result", {}).get("book_rows")
        and selected.get("layout_result", {}).get("market_rows")
        and not selected.get("layout_result", {}).get(
            "previous_period_explicit", False
        )
        and latest_hint
    ):
        reasons = [
            reason for reason in reasons
            if reason != "current_period_not_explicit"
        ]
        if not reasons:
            quality = "verified"
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


def publishable_real_estate_values(selection):
    if selection.get("quality_status") != "verified":
        return 0, 0
    return (
        selection.get("book_value_yen", 0),
        selection.get("market_value_yen", 0),
    )
