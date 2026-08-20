import math
import re
import unicodedata


CURRENT_MARKERS = (
    "当連結会計年度", "当事業年度", "当会計年度", "当年度", "当期",
)
PREVIOUS_MARKERS = (
    "前連結会計年度", "前事業年度", "前会計年度", "前年度", "前期",
)
REAL_ESTATE_MARKERS = ("賃貸等不動産", "投資不動産")
BOOK_MARKERS = ("貸借対照表計上額", "財政状態計算書計上額", "帳簿価額")
MARKET_MARKERS = ("期末時価", "公正価値", "時価")
BOOK_EXCLUDES = ("期首", "増減", "償却", "損益", "収益", "費用", "取得原価", "累計")
MARKET_EXCLUDES = (
    "金融資産", "金融負債", "その他の包括利益", "を通じて", "測定する",
    "変動", "収益", "費用", "損益",
)


def _normalize(value):
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"[\s\u3000]+", "", text)


def _contains(text, markers):
    return any(marker in text for marker in markers)


def _number(value):
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not text or text in ("-", "―", "—"):
        return None
    parenthesized = text.startswith("(") and text.endswith(")")
    text = text.replace("△", "-").replace("▲", "-").replace(",", "")
    text = re.sub(r"※\d+", "", text)
    text = re.sub(r"\(注\d*\)", "", text).strip()
    if parenthesized:
        text = "-" + text[1:-1]
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        return None
    return float(text)


def _unit_multiplier(table_text, context_text):
    for source, value in (("table", table_text), ("context", context_text)):
        text = _normalize(value)
        if "百万円" in text:
            return 1_000_000, source
        if "千円" in text:
            return 1_000, source
        if re.search(r"単位[:：]?円", text):
            return 1, source
    return None, None


def _dates(text):
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    found = set()
    patterns = (
        r"(20\d{2})年(\d{1,2})月(?:(\d{1,2})日|末)",
        r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})",
    )
    for pattern in patterns:
        for year, month, day in re.findall(pattern, normalized):
            found.add((int(year), int(month), int(day or 1)))
    return sorted(found)


def _fact_value_yen(cell):
    facts = []
    for node in cell.find_all(True):
        if not str(node.name).lower().endswith("nonfraction"):
            continue
        value = _number(node.get_text("", strip=True))
        if value is None:
            continue
        sign = str(node.get("sign", ""))
        if sign == "-" and value > 0:
            value = -value
        scale = node.get("scale")
        unit_ref = str(node.get("unitref", node.get("unitRef", ""))).lower()
        if scale not in (None, "") and ("jpy" in unit_ref or "yen" in unit_ref):
            try:
                facts.append(value * (10 ** int(scale)))
            except (TypeError, ValueError):
                pass
    if len(facts) == 1:
        return facts[0]
    return None


def _cell(cell):
    return {
        "text": _normalize(cell.get_text(" ", strip=True)),
        "raw": _number(cell.get_text("", strip=True)),
        "fact_yen": _fact_value_yen(cell),
        "header": str(cell.name).lower() == "th",
    }


def _table_grid(table):
    rows = [
        row for row in table.find_all("tr")
        if row.find_parent("table") is table
    ]
    pending = {}
    grid = []
    for row in rows:
        output = []
        column = 0

        def fill_pending():
            nonlocal column
            while column in pending:
                remaining, value = pending[column]
                output.append(value)
                if remaining <= 1:
                    del pending[column]
                else:
                    pending[column] = (remaining - 1, value)
                column += 1

        fill_pending()
        cells = [
            cell for cell in row.find_all(("th", "td"), recursive=False)
            if cell.find_parent("tr") is row
        ]
        for source in cells:
            fill_pending()
            value = _cell(source)
            try:
                colspan = max(1, int(source.get("colspan", 1)))
                rowspan = max(1, int(source.get("rowspan", 1)))
            except (TypeError, ValueError):
                colspan = rowspan = 1
            for _ in range(colspan):
                output.append(value)
                if rowspan > 1:
                    pending[column] = (rowspan - 1, value)
                column += 1
        fill_pending()
        grid.append(output)
    width = max((len(row) for row in grid), default=0)
    empty = {"text": "", "raw": None, "fact_yen": None, "header": False}
    return [row + [empty] * (width - len(row)) for row in grid]


def _value_yen(cell, multiplier):
    if cell["fact_yen"] is not None:
        return cell["fact_yen"]
    if cell["raw"] is None or multiplier is None:
        return None
    return cell["raw"] * multiplier


def _period_descriptor(text, all_dates):
    normalized = _normalize(text)
    dates = _dates(normalized)
    if _contains(normalized, CURRENT_MARKERS):
        return "current", dates[-1] if dates else None, True
    if _contains(normalized, PREVIOUS_MARKERS):
        return "previous", dates[-1] if dates else None, True
    if dates:
        date = dates[-1]
        if all_dates and date == all_dates[-1]:
            return "current", date, True
        if len(all_dates) > 1 and date == all_dates[-2]:
            return "previous", date, True
        return "dated", date, True
    return None, None, False


def _resolve(values):
    unique = []
    seen = set()
    for item in values:
        key = (item["label"], item["value_yen"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    totals = [item for item in unique if "合計" in item["label"]]
    if totals:
        return max(totals, key=lambda item: abs(item["value_yen"]))["value_yen"], totals
    if len(unique) == 1:
        return unique[0]["value_yen"], unique
    if not unique:
        return 0, []
    values_only = [item["value_yen"] for item in unique]
    largest = max(values_only)
    rest = sum(values_only) - largest
    if largest > 0 and rest > 0 and math.isclose(largest, rest, rel_tol=0.001, abs_tol=1):
        selected = max(unique, key=lambda item: item["value_yen"])
        return selected["value_yen"], [selected]
    return sum(values_only), unique


def _column_descriptors(grid):
    descriptors = []
    width = max((len(row) for row in grid), default=0)
    for column in range(width):
        parts = []
        for row_index, row in enumerate(grid):
            cell = row[column]
            if cell["header"] or row_index < 4:
                parts.append(cell["text"])
        descriptors.append(_normalize("".join(parts)))
    return descriptors


def _row_period_candidates(
    grid, descriptors, multiplier, context_text, table_text
):
    descriptor_dates = sorted({
        date for descriptor in descriptors for date in _dates(descriptor)
    })
    numeric_columns = []
    for column, descriptor in enumerate(descriptors[1:], start=1):
        count = sum(_value_yen(row[column], multiplier) is not None for row in grid)
        if count:
            numeric_columns.append((column, descriptor))
    results = []
    book_rollforward = _contains(
        _normalize(context_text) + _normalize(table_text), BOOK_MARKERS
    )
    for column, descriptor in numeric_columns:
        role, date, explicit = _period_descriptor(descriptor, descriptor_dates)
        if not role and len(numeric_columns) == 1 and _contains(_normalize(context_text), CURRENT_MARKERS):
            role, explicit = "current", True
        if not role:
            continue
        books = []
        markets = []
        for row_index, row in enumerate(grid):
            value = _value_yen(row[column], multiplier)
            if value is None:
                continue
            label = _normalize("".join(cell["text"] for cell in row[:column]))
            item = {"row": row_index, "label": label, "value_yen": value}
            is_closing_book = (
                book_rollforward
                and any(marker in label for marker in (
                    "期末残高", "年度末残高", "報告期間末残高",
                ))
                and "期首" not in label
                and not _contains(label, MARKET_MARKERS)
            )
            if (
                (_contains(label, BOOK_MARKERS) or is_closing_book)
                and not _contains(label, BOOK_EXCLUDES)
            ):
                books.append(item)
            if _contains(label, MARKET_MARKERS) and not _contains(label, MARKET_EXCLUDES):
                markets.append(item)
        book, book_rows = _resolve(books)
        market, market_rows = _resolve(markets)
        if book > 0 or market > 0:
            results.append({
                "period_role": role,
                "period_end": date,
                "book_value_yen": int(round(book)) if book > 0 else 0,
                "market_value_yen": int(round(market)) if market > 0 else 0,
                "gross_value_yen": 0,
                "accumulated_value_yen": 0,
                "evidence": {"column": column, "book_rows": book_rows, "market_rows": market_rows},
                "explicit_period": explicit,
                "method": "dom_period_column",
            })
    return results


def _fair_value_model_candidates(grid, descriptors, multiplier, context_text):
    context = _normalize(context_text)
    if not (
        "公正価値モデル" in context
        or re.search(r"公正価値.{0,80}(?:で計上|により測定|によって測定)", context)
    ):
        return []
    descriptor_dates = sorted({
        date for descriptor in descriptors for date in _dates(descriptor)
    })
    results = []
    for column, descriptor in enumerate(descriptors[1:], start=1):
        role, date, explicit = _period_descriptor(descriptor, descriptor_dates)
        if not role:
            continue
        closing = []
        for row_index, row in enumerate(grid):
            value = _value_yen(row[column], multiplier)
            if value is None:
                continue
            label = _normalize("".join(cell["text"] for cell in row[:column]))
            if "期首" in label or "変動" in label:
                continue
            if any(marker in label for marker in (
                "期末残高", "年度末残高", "報告期間末", "3月31日現在",
                "12月31日現在",
            )):
                closing.append({
                    "row": row_index, "label": label, "value_yen": value,
                })
        value, selected = _resolve(closing)
        if value <= 0:
            continue
        value = int(round(value))
        results.append({
            "period_role": role,
            "period_end": date,
            "book_value_yen": value,
            "market_value_yen": value,
            "gross_value_yen": 0,
            "accumulated_value_yen": 0,
            "evidence": {"closing_rows": selected},
            "explicit_period": explicit,
            "method": "dom_fair_value_model",
        })
    return results


def _horizontal_candidates(grid, descriptors, multiplier):
    descriptor_dates = sorted({
        date for descriptor in descriptors for date in _dates(descriptor)
    })
    semantic_columns = []
    for column, descriptor in enumerate(descriptors[1:], start=1):
        if _contains(descriptor, BOOK_MARKERS):
            kind = "book_value_yen"
        elif _contains(descriptor, MARKET_MARKERS) and not _contains(descriptor, MARKET_EXCLUDES):
            kind = "market_value_yen"
        else:
            continue
        role, date, explicit = _period_descriptor(descriptor, descriptor_dates)
        if role:
            semantic_columns.append((column, kind, role, date, explicit))
    results = {}
    for column, kind, role, date, explicit in semantic_columns:
        rows = []
        for row_index, row in enumerate(grid):
            value = _value_yen(row[column], multiplier)
            if value is None:
                continue
            label = _normalize("".join(cell["text"] for cell in row[:column]))
            if _contains(label, MARKET_EXCLUDES + BOOK_EXCLUDES):
                continue
            rows.append({"row": row_index, "label": label, "value_yen": value})
        direct = [item for item in rows if _contains(item["label"], REAL_ESTATE_MARKERS)]
        selected_source = direct or rows
        value, selected = _resolve(selected_source)
        if value <= 0:
            continue
        key = (role, date)
        result = results.setdefault(key, {
            "period_role": role,
            "period_end": date,
            "book_value_yen": 0,
            "market_value_yen": 0,
            "gross_value_yen": 0,
            "accumulated_value_yen": 0,
            "evidence": {},
            "explicit_period": explicit,
            "method": "dom_book_market_columns",
        })
        result[kind] = int(round(value))
        result["evidence"][kind] = {"column": column, "rows": selected}
    return list(results.values())


def _dated_candidates(grid, table_text, context_text, multiplier):
    combined = _normalize(context_text) + _normalize(table_text)
    if not _contains(combined, REAL_ESTATE_MARKERS):
        return []
    immediate = _normalize(context_text)[-600:] + _normalize(table_text)[:600]
    if "公正価値" in immediate:
        kind = "market_value_yen"
    elif "減価償却累計額" in immediate or "減損損失累計額" in immediate:
        kind = "accumulated_value_yen"
    elif "取得原価" in immediate:
        kind = "gross_value_yen"
    else:
        return []
    dated = []
    for row_index, row in enumerate(grid):
        row_text = _normalize("".join(cell["text"] for cell in row))
        dates = _dates(row_text)
        if not dates or "残高" not in row_text:
            continue
        values = [_value_yen(cell, multiplier) for cell in row]
        values = [value for value in values if value is not None]
        if values:
            dated.append((dates[-1], row_index, values[-1], row_text))
    all_dates = sorted({item[0] for item in dated})
    results = []
    for date, row_index, value, label in dated:
        role = "current" if date == all_dates[-1] else "previous" if len(all_dates) > 1 and date == all_dates[-2] else "dated"
        result = {
            "period_role": role,
            "period_end": date,
            "book_value_yen": 0,
            "market_value_yen": 0,
            "gross_value_yen": 0,
            "accumulated_value_yen": 0,
            "evidence": {"row": row_index, "label": label},
            "explicit_period": True,
            "method": "dom_dated_balance",
        }
        if kind == "accumulated_value_yen" and value > 0:
            value = -value
        result[kind] = int(round(value))
        results.append(result)
    return results


def extract_dom_table_candidate(table, context_text, file_name="", table_index=0):
    table_text = table.get_text(" ", strip=True)
    combined = _normalize(context_text) + _normalize(table_text)
    result = {
        "file": file_name,
        "table_index": table_index,
        "relevant": _contains(combined, REAL_ESTATE_MARKERS) or "期末時価" in combined,
        "values": [],
        "reasons": [],
    }
    if not result["relevant"]:
        result["reasons"].append("not_real_estate_table")
        return result
    if "保証会社" in combined:
        result["reasons"].append("guarantor_section")
        return result
    grid = _table_grid(table)
    if not grid:
        result["reasons"].append("empty_dom_grid")
        return result
    multiplier, unit_source = _unit_multiplier(table_text, context_text)
    has_fact_values = any(cell["fact_yen"] is not None for row in grid for cell in row)
    if multiplier is None and not has_fact_values:
        result["reasons"].append("unit_not_explicit")
        return result
    descriptors = _column_descriptors(grid)
    values = []
    values.extend(_row_period_candidates(
        grid, descriptors, multiplier, context_text, table_text
    ))
    values.extend(_horizontal_candidates(grid, descriptors, multiplier))
    values.extend(_fair_value_model_candidates(
        grid, descriptors, multiplier, context_text
    ))
    values.extend(_dated_candidates(grid, table_text, context_text, multiplier))
    unique = []
    seen = set()
    for value in values:
        key = (
            value["period_role"], value["period_end"], value["book_value_yen"],
            value["market_value_yen"], value["gross_value_yen"],
            value["accumulated_value_yen"], value["method"],
        )
        if key not in seen:
            seen.add(key)
            value["unit_source"] = "ix_fact" if has_fact_values else unit_source
            unique.append(value)
    result["values"] = unique
    if not unique:
        result["reasons"].append("dom_values_not_resolved")
    return result


def _period_token(value):
    if value.get("period_end"):
        return tuple(value["period_end"])
    return value.get("period_role")


def _pair_values(candidates):
    flattened = []
    for candidate_index, candidate in enumerate(candidates):
        if candidate.get("reasons"):
            continue
        for value in candidate.get("values", []):
            flattened.append({
                **value,
                "file": candidate.get("file", ""),
                "table_index": candidate.get("table_index", 0),
                "candidate_index": candidate_index,
            })
    pairs = []
    for value in flattened:
        if value["book_value_yen"] > 0 and value["market_value_yen"] > 0:
            pairs.append({**value, "score": 500, "source": "single_dom_table"})

    tokens = {_period_token(value) for value in flattened}
    for token in tokens:
        period_values = [value for value in flattened if _period_token(value) == token]
        for left in period_values:
            for right in period_values:
                if left is right or left["file"] != right["file"]:
                    continue
                if abs(left["table_index"] - right["table_index"]) > 5:
                    continue
                book = left["book_value_yen"] or right["book_value_yen"]
                market = left["market_value_yen"] or right["market_value_yen"]
                if book > 0 and market > 0:
                    pairs.append({
                        **left,
                        "book_value_yen": book,
                        "market_value_yen": market,
                        "score": 420,
                        "source": "paired_dom_tables",
                        "source_tables": sorted({left["table_index"], right["table_index"]}),
                    })
        gross = [value for value in period_values if value["gross_value_yen"] > 0]
        accumulated = [value for value in period_values if value["accumulated_value_yen"] < 0]
        markets = [value for value in period_values if value["market_value_yen"] > 0]
        for gross_value in gross:
            for accumulated_value in accumulated:
                for market_value in markets:
                    sources = (gross_value, accumulated_value, market_value)
                    if len({source["file"] for source in sources}) != 1:
                        continue
                    tables = [source["table_index"] for source in sources]
                    if max(tables) - min(tables) > 5:
                        continue
                    book = gross_value["gross_value_yen"] + accumulated_value["accumulated_value_yen"]
                    if book <= 0:
                        continue
                    pairs.append({
                        **market_value,
                        "book_value_yen": book,
                        "market_value_yen": market_value["market_value_yen"],
                        "score": 460,
                        "source": "dom_cost_accumulation_fair_value",
                        "source_tables": sorted(set(tables)),
                    })
    return pairs


def select_dom_period_values(candidates):
    pairs = _pair_values(candidates)
    result = {"status": "not_available", "current": None, "previous": None, "pairs": pairs}
    if not pairs:
        return result
    dated = sorted({pair["period_end"] for pair in pairs if pair.get("period_end")})
    for role in ("current", "previous"):
        target_date = None
        if dated:
            target_date = dated[-1] if role == "current" else dated[-2] if len(dated) > 1 else None
        eligible = [
            pair for pair in pairs
            if (target_date and pair.get("period_end") == target_date)
            or (not target_date and pair.get("period_role") == role)
        ]
        if not eligible:
            continue
        eligible.sort(key=lambda pair: (pair.get("score", 0), pair["table_index"]), reverse=True)
        selected = eligible[0]
        competing = [
            pair for pair in eligible[1:]
            if (pair["book_value_yen"], pair["market_value_yen"])
            != (selected["book_value_yen"], selected["market_value_yen"])
            and selected.get("score", 0) - pair.get("score", 0) < 50
        ]
        result[role] = {
            "status": "ambiguous" if competing else "resolved",
            "book_value_yen": selected["book_value_yen"],
            "market_value_yen": selected["market_value_yen"],
            "hidden_gain_yen": selected["market_value_yen"] - selected["book_value_yen"],
            "period_end": selected.get("period_end"),
            "method": selected.get("source"),
            "source_tables": selected.get("source_tables", [selected["table_index"]]),
            "competing_count": len(competing),
        }
    if result["current"]:
        result["status"] = result["current"]["status"]
    return result


def compare_primary_with_dom(primary_selection, dom_selection, tolerance_yen=1_000_000):
    current = (dom_selection or {}).get("current")
    if not current or current.get("status") != "resolved":
        return {"status": "not_available", "reason": "independent_current_not_resolved"}
    primary_book = int(primary_selection.get("book_value_yen", 0) or 0)
    primary_market = int(primary_selection.get("market_value_yen", 0) or 0)
    if primary_book <= 0 or primary_market <= 0:
        return {"status": "not_available", "reason": "primary_current_not_resolved"}
    differences = {
        "book_value_yen": current["book_value_yen"] - primary_book,
        "market_value_yen": current["market_value_yen"] - primary_market,
    }
    matched = all(abs(value) <= tolerance_yen for value in differences.values())
    return {
        "status": "matched" if matched else "mismatch",
        "tolerance_yen": tolerance_yen,
        "differences_yen": differences,
        "primary": {"book_value_yen": primary_book, "market_value_yen": primary_market},
        "independent": {
            "book_value_yen": current["book_value_yen"],
            "market_value_yen": current["market_value_yen"],
        },
    }


def compare_prior_year_continuity(latest_previous, previous_current, absolute_tolerance_yen=1_000_000, relative_tolerance=0.001):
    if not latest_previous or not previous_current:
        return {"status": "not_available", "reason": "one_or_both_periods_missing"}
    if latest_previous.get("status") != "resolved" or previous_current.get("status") != "resolved":
        return {"status": "not_available", "reason": "one_or_both_periods_ambiguous"}
    differences = {}
    tolerances = {}
    for field in ("book_value_yen", "market_value_yen"):
        left = latest_previous[field]
        right = previous_current[field]
        differences[field] = left - right
        tolerances[field] = max(absolute_tolerance_yen, int(max(abs(left), abs(right)) * relative_tolerance))
    matched = all(abs(differences[field]) <= tolerances[field] for field in differences)
    return {
        "status": "matched" if matched else "mismatch_or_restatement",
        "differences_yen": differences,
        "tolerances_yen": tolerances,
        "latest_filing_previous": {
            field: latest_previous[field] for field in ("book_value_yen", "market_value_yen")
        },
        "previous_filing_current": {
            field: previous_current[field] for field in ("book_value_yen", "market_value_yen")
        },
    }
