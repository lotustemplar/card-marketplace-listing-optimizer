from __future__ import annotations

from typing import Any

import pandas as pd

import pricing_logic_v08 as base
from pricing_logic_v08 import *  # noqa: F401,F403


USER_AGENT = "CardMarketplaceListingOptimizer/1.3 (+https://github.com/lotustemplar/card-marketplace-listing-optimizer)"
base.USER_AGENT = USER_AGENT
MANAPOOL_SINGLES_PRICES_ENDPOINT = "prices/singles"
SET_NAME_CODE_ALIASES = {
    "the list reprints": {"plst"},
}
FORCED_DIRECT_REASON = "Forced to TCGPlayer Direct because Rarity = T"


def _normalize_set_code(value: Any) -> str:
    return "".join(char for char in base.safe_text(value).strip().lower() if char.isalnum())


def _row_is_foil(condition_text: str) -> bool:
    return "foil" in base.safe_text(condition_text).lower()


def _alias_set_codes(set_name: str) -> set[str]:
    return set(SET_NAME_CODE_ALIASES.get(base.normalize_header(set_name), set()))


def _relevant_nm_price(candidate: dict[str, Any], is_foil: bool) -> float | None:
    price_field = "price_cents_nm_foil" if is_foil else "price_cents_nm"
    cents_value, parse_error = base.try_parse_number(candidate.get(price_field))
    if parse_error is not None or cents_value is None:
        return None
    return round(cents_value / 100.0, 2)


def _dedupe_single_candidates(candidates: list[dict[str, Any]], is_foil: bool) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for candidate in candidates:
        key = (
            base.normalize_header(candidate.get("name", "")),
            _normalize_set_code(candidate.get("set_code", "")),
            base.normalize_identifier(candidate.get("number", "")),
            base.safe_text(candidate.get("url", "")),
        )
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = candidate
            continue
        current_price = _relevant_nm_price(candidate, is_foil)
        existing_price = _relevant_nm_price(existing, is_foil)
        if current_price is not None and (existing_price is None or current_price < existing_price):
            deduped[key] = candidate
    return list(deduped.values())


def _build_single_option(candidate: dict[str, Any], is_foil: bool) -> dict[str, Any] | None:
    price = _relevant_nm_price(candidate, is_foil)
    if price is None:
        return None
    set_code = base.safe_text(candidate.get("set_code", ""))
    card_number = base.safe_text(candidate.get("number", ""))
    url = base.safe_text(candidate.get("url", ""))
    finish_label = "NM Foil" if is_foil else "NM"
    label = f"{base.safe_text(candidate.get('name', 'Unknown card'))} | {set_code or 'Unknown set'}"
    if card_number:
        label += f" | #{card_number}"
    label += f" | {finish_label} | ${price:.2f}"
    if url:
        label += f" | {url}"
    return {
        "label": label,
        "price": price,
        "name": base.safe_text(candidate.get("name", "")),
        "set_name": "",
        "set_code": set_code,
        "card_number": card_number,
        "reason": f"Mana Pool manual override via singles prices: {label}",
    }


def fetch_manapool_singles_candidates(
    manapool_api_key: str | None,
    manapool_email: str | None,
) -> dict[str, list[dict[str, Any]]]:
    endpoint_url = f"{base.MANAPOOL_API_BASE_URL}{MANAPOOL_SINGLES_PRICES_ENDPOINT}"
    headers = base.build_manapool_headers(manapool_api_key, manapool_email)
    response_payload = base.request_json(endpoint_url, headers=headers)
    data = response_payload.get("data", []) if isinstance(response_payload, dict) else []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        normalized_name = base.normalize_header(item.get("name", ""))
        if normalized_name:
            grouped.setdefault(normalized_name, []).append(item)
    return grouped


def _infer_target_set_codes(card_info_candidates: list[dict[str, Any]], set_name: str, card_number: str) -> set[str]:
    normalized_set_name = base.normalize_header(set_name)
    normalized_number = base.normalize_identifier(card_number)
    alias_codes = _alias_set_codes(set_name)
    codes = {
        _normalize_set_code(candidate.get("set_code", ""))
        for candidate in card_info_candidates
        if base.normalize_header(candidate.get("set_name", "")) == normalized_set_name
        and (not normalized_number or base.normalize_identifier(candidate.get("card_number", "")) == normalized_number)
        and _normalize_set_code(candidate.get("set_code", ""))
    }
    if codes:
        return codes | alias_codes
    fallback_codes = {
        _normalize_set_code(candidate.get("set_code", ""))
        for candidate in card_info_candidates
        if base.normalize_header(candidate.get("set_name", "")) == normalized_set_name
        and _normalize_set_code(candidate.get("set_code", ""))
    }
    return fallback_codes | alias_codes


def load_manapool_price_lookup(
    tcg_df: pd.DataFrame,
    column_map: dict[str, str],
    manapool_api_key: str | None,
    manapool_email: str | None,
    manapool_match_overrides: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[tuple[str, str, str], float], dict[tuple[str, str, str], str], str | None, list[dict[str, Any]], int]:
    product_name_column = column_map.get("Product Name")
    set_name_column = column_map.get("Set Name")
    number_column = column_map.get("Number")
    condition_column = column_map.get("Condition")
    if not product_name_column or not set_name_column:
        return {}, {}, None, [], 0

    overrides = manapool_match_overrides or {}
    unique_keys = sorted(
        {
            (
                base.safe_text(row.get(product_name_column, "")),
                base.safe_text(row.get(set_name_column, "")),
                base.safe_text(row.get(number_column, "")) if number_column else "",
                base.safe_text(row.get(condition_column, "")) if condition_column else "",
            )
            for _, row in tcg_df.iterrows()
            if base.safe_text(row.get(product_name_column, "")) and base.safe_text(row.get(set_name_column, ""))
        }
    )
    if not unique_keys:
        return {}, {}, None, [], 0

    unique_names = sorted({product_name for product_name, _, _, _ in unique_keys})
    try:
        cards_by_name = {}
        for start in range(0, len(unique_names), base.MANAPOOL_BATCH_SIZE):
            batch = unique_names[start : start + base.MANAPOOL_BATCH_SIZE]
            cards_by_name.update(base.fetch_manapool_cards_by_names(batch, manapool_api_key, manapool_email))
        singles_by_name = fetch_manapool_singles_candidates(manapool_api_key, manapool_email)
    except Exception as exc:
        return {}, {}, f"Mana Pool API lookup was unavailable, so TCG fallback pricing was used instead. Details: {exc}", [], 0

    price_lookup: dict[tuple[str, str, str], float] = {}
    source_lookup: dict[tuple[str, str, str], str] = {}
    unresolved_options: list[dict[str, Any]] = []
    misses = 0
    manual_override_count = 0

    for product_name, set_name, card_number, condition_text in unique_keys:
        row_tuple = (
            base.normalize_header(product_name),
            base.normalize_header(set_name),
            base.normalize_identifier(card_number),
        )
        row_key = base.build_row_key(product_name, set_name, card_number)
        is_foil = _row_is_foil(condition_text)

        if row_key in overrides:
            override = overrides[row_key]
            override_price, parse_error = base.try_parse_number(override.get("price"))
            if parse_error is None and override_price is not None:
                price_lookup[row_tuple] = round(override_price, 2)
                source_lookup[row_tuple] = base.safe_text(override.get("reason", "Mana Pool manual override"))
                manual_override_count += 1
                continue

        card_info_candidates = cards_by_name.get(base.normalize_header(product_name), [])
        target_set_codes = _infer_target_set_codes(card_info_candidates, set_name, card_number)
        single_candidates = _dedupe_single_candidates(singles_by_name.get(base.normalize_header(product_name), []), is_foil)
        single_candidates = [candidate for candidate in single_candidates if _relevant_nm_price(candidate, is_foil) is not None]

        exact_same_set_same_number = [
            candidate
            for candidate in single_candidates
            if _normalize_set_code(candidate.get("set_code", "")) in target_set_codes
            and (not card_number or base.normalize_identifier(candidate.get("number", "")) == base.normalize_identifier(card_number))
        ]

        if len(exact_same_set_same_number) == 1:
            chosen = exact_same_set_same_number[0]
            chosen_price = _relevant_nm_price(chosen, is_foil)
            if chosen_price is not None:
                price_lookup[row_tuple] = chosen_price
                source_lookup[row_tuple] = "Mana Pool singles exact NM printing"
                continue

        if not exact_same_set_same_number and len(target_set_codes) == 1:
            same_set_candidates = [
                candidate for candidate in single_candidates if _normalize_set_code(candidate.get("set_code", "")) in target_set_codes
            ]
            if len(same_set_candidates) == 1:
                chosen = same_set_candidates[0]
                chosen_price = _relevant_nm_price(chosen, is_foil)
                if chosen_price is not None:
                    price_lookup[row_tuple] = chosen_price
                    source_lookup[row_tuple] = "Mana Pool singles inferred NM printing"
                    continue

        options: list[dict[str, Any]] = []
        seen_labels: set[str] = set()

        preferred_candidates = exact_same_set_same_number
        if not preferred_candidates and target_set_codes:
            preferred_candidates = [
                candidate for candidate in single_candidates if _normalize_set_code(candidate.get("set_code", "")) in target_set_codes
            ]
        if not preferred_candidates and card_number:
            preferred_candidates = [
                candidate for candidate in single_candidates if base.normalize_identifier(candidate.get("number", "")) == base.normalize_identifier(card_number)
            ]
        if not preferred_candidates:
            preferred_candidates = single_candidates

        for candidate in preferred_candidates:
            option = _build_single_option(candidate, is_foil)
            if not option or option["label"] in seen_labels:
                continue
            seen_labels.add(option["label"])
            options.append(option)

        if len(options) == 1:
            chosen_option = options[0]
            chosen_price, parse_error = base.try_parse_number(chosen_option.get("price"))
            if parse_error is None and chosen_price is not None:
                price_lookup[row_tuple] = round(chosen_price, 2)
                source_lookup[row_tuple] = chosen_option.get("reason", "Mana Pool single-option auto match")
                continue

        if options:
            unresolved_options.append(
                {
                    "row_key": row_key,
                    "product_name": product_name,
                    "set_name": set_name,
                    "number": card_number,
                    "options": options,
                }
            )

        misses += 1

    warnings: list[str] = []
    if misses:
        warnings.append(f"Mana Pool API lookup matched {len(price_lookup)} row key(s). {misses} row key(s) fell back to TCG pricing.")
    if manual_override_count:
        warnings.append(f"Applied {manual_override_count} manual Mana Pool match override(s).")

    return price_lookup, source_lookup, "\n\n".join(warnings) if warnings else None, unresolved_options, manual_override_count


def _result_row_key(id_value: Any, product_name: Any, set_name: Any, number: Any, condition: Any) -> tuple[str, str, str, str, str]:
    return (
        base.safe_text(id_value),
        base.normalize_header(product_name),
        base.normalize_header(set_name),
        base.normalize_identifier(number),
        base.normalize_header(condition),
    )


def _source_row_key(row: pd.Series, column_map: dict[str, str]) -> tuple[str, str, str, str, str]:
    return _result_row_key(
        row.get(column_map.get("TCGplayer Id", ""), "") if column_map.get("TCGplayer Id") else "",
        row.get(column_map.get("Product Name", ""), "") if column_map.get("Product Name") else "",
        row.get(column_map.get("Set Name", ""), "") if column_map.get("Set Name") else "",
        row.get(column_map.get("Number", ""), "") if column_map.get("Number") else "",
        row.get(column_map.get("Condition", ""), "") if column_map.get("Condition") else "",
    )


def _preview_row_key(row: pd.Series) -> tuple[str, str, str, str, str]:
    return _result_row_key(
        row.get("TCGplayer Id", ""),
        row.get("Product Name", ""),
        row.get("Set Name", ""),
        row.get("Number", ""),
        row.get("Condition", ""),
    )


def _raw_base_direct_price_from_source(row: pd.Series, column_map: dict[str, str]) -> float | None:
    market_price = None
    direct_low = None
    if column_map.get("TCG Market Price"):
        market_price, _ = base.try_parse_number(row.get(column_map["TCG Market Price"], ""))
    if column_map.get("TCG Direct Low"):
        direct_low, _ = base.try_parse_number(row.get(column_map["TCG Direct Low"], ""))
    if direct_low is None:
        return market_price
    if market_price is None:
        return direct_low
    return max(market_price, direct_low)


def _append_reason(reason_text: Any, extra_reason: str) -> str:
    parts = [part for part in str(reason_text).split("; ") if part]
    if extra_reason not in parts:
        parts.append(extra_reason)
    return "; ".join(parts)


def _rebuild_summary(result: ProcessResult, settings: OptimizerSettings) -> None:
    manapool_full_df = result.manapool_full_df
    direct_full_df = result.direct_full_df

    manapool_total_net = 0.0
    direct_total_net = 0.0
    if not manapool_full_df.empty:
        manapool_total_net = float((pd.to_numeric(manapool_full_df["Manapool Net"], errors="coerce").fillna(0) * pd.to_numeric(manapool_full_df["Quantity"], errors="coerce").fillna(0)).sum())
    if not direct_full_df.empty:
        direct_total_net = float((pd.to_numeric(direct_full_df["Direct Net"], errors="coerce").fillna(0) * pd.to_numeric(direct_full_df["Quantity"], errors="coerce").fillna(0)).sum())

    direct_bump_average = 0.0
    if not direct_full_df.empty:
        direct_bump_series = pd.to_numeric(direct_full_df["Direct Bump %"], errors="coerce").dropna()
        if not direct_bump_series.empty:
            direct_bump_average = float(direct_bump_series.mean())

    tracked_shipping_review_count = 0
    if not manapool_full_df.empty:
        tracked_shipping_review_count = int((pd.to_numeric(manapool_full_df["Manapool Price"], errors="coerce").fillna(0) >= settings.tracked_shipping_threshold).sum())

    summary = dict(result.summary)
    summary.update(
        {
            "total_cards_assigned_manapool": int(pd.to_numeric(manapool_full_df["Quantity"], errors="coerce").fillna(0).sum()) if not manapool_full_df.empty else 0,
            "total_cards_assigned_direct": int(pd.to_numeric(direct_full_df["Quantity"], errors="coerce").fillna(0).sum()) if not direct_full_df.empty else 0,
            "total_estimated_manapool_net": round(manapool_total_net, 2),
            "total_estimated_direct_net": round(direct_total_net, 2),
            "combined_estimated_net": round(manapool_total_net + direct_total_net, 2),
            "average_direct_bump_pct": direct_bump_average,
            "forced_manapool_min_count": int(manapool_full_df.get("_forced_min", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()) if not manapool_full_df.empty else 0,
            "direct_bump_exceeded_count": int(manapool_full_df.get("_bump_exceeded", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()) if not manapool_full_df.empty else 0,
            "tracked_shipping_review_count": tracked_shipping_review_count,
        }
    )
    result.summary = summary
    result.analysis_df = base.build_analysis_dataframe(summary, settings)
    result.manapool_preview_df = base.sort_preview(manapool_full_df, base.DISPLAY_COLUMNS_MANAPOOL)
    result.direct_preview_df = base.sort_preview(direct_full_df, base.DISPLAY_COLUMNS_DIRECT)


def process_files(
    tcgplayer_bytes: bytes,
    settings: OptimizerSettings,
    manapool_api_key: str | None = None,
    manapool_email: str | None = None,
    manapool_match_overrides: dict[str, dict[str, Any]] | None = None,
) -> ProcessResult:
    result = base.process_files(
        tcgplayer_bytes=tcgplayer_bytes,
        settings=settings,
        manapool_api_key=manapool_api_key,
        manapool_email=manapool_email,
        manapool_match_overrides=manapool_match_overrides,
    )

    if result.direct_full_df.empty:
        return result

    source_df = base.load_tcgplayer_dataframe(tcgplayer_bytes)
    column_map, missing_columns = base.map_tcgplayer_columns(source_df)
    if missing_columns:
        return result

    source_columns = list(source_df.columns)
    source_lookup = {_source_row_key(row, column_map): row for _, row in source_df.iterrows()}

    adjusted_direct_rows: list[dict[str, Any]] = []
    rerouted_manapool_rows: list[dict[str, Any]] = []
    new_direct_csv_rows: list[dict[str, Any]] = []
    rerouted_manapool_csv_rows: list[dict[str, Any]] = []

    for _, direct_row in result.direct_full_df.iterrows():
        preview_key = _preview_row_key(direct_row)
        source_row = source_lookup.get(preview_key)
        if source_row is None:
            adjusted_direct_rows.append(direct_row.to_dict())
            continue

        raw_base_direct_price = _raw_base_direct_price_from_source(source_row, column_map)
        current_listing_price, _ = base.try_parse_number(direct_row.get("Direct Listing Price"))

        if (
            raw_base_direct_price is None
            or raw_base_direct_price >= base.DIRECT_MIN_LISTING_PRICE
            or current_listing_price is None
            or current_listing_price <= base.DIRECT_MIN_LISTING_PRICE
        ):
            adjusted_direct_rows.append(direct_row.to_dict())
            new_direct_csv_rows.append(
                base.build_upload_row(
                    source_row,
                    source_columns,
                    column_map,
                    float(pd.to_numeric(direct_row.get("Quantity"), errors="coerce")),
                    float(current_listing_price) if current_listing_price is not None else base.DIRECT_MIN_LISTING_PRICE,
                )
            )
            continue

        floored_direct_price = base.DIRECT_MIN_LISTING_PRICE
        floored_direct_net = base.lookup_direct_net(floored_direct_price)
        direct_bump_pct = base.calculate_direct_bump_pct(raw_base_direct_price, floored_direct_price)

        if direct_bump_pct is None or direct_bump_pct > settings.max_direct_bump_pct:
            reroute_reason = _append_reason(direct_row.get("Reason", ""), "Direct floor enforced at $0.40")
            reroute_reason = _append_reason(reroute_reason, "Required Direct bump exceeded max allowed %")
            rerouted_manapool_rows.append(
                {
                    "TCGplayer Id": direct_row.get("TCGplayer Id", ""),
                    "Product Line": direct_row.get("Product Line", ""),
                    "Set Name": direct_row.get("Set Name", ""),
                    "Product Name": direct_row.get("Product Name", ""),
                    "Number": direct_row.get("Number", ""),
                    "Rarity": direct_row.get("Rarity", ""),
                    "Condition": direct_row.get("Condition", ""),
                    "Quantity": direct_row.get("Quantity", ""),
                    "Manapool Price": direct_row.get("Manapool Price", ""),
                    "Manapool Net": direct_row.get("Manapool Net", ""),
                    "Base Direct Price": round(base.normalize_direct_listing_price(raw_base_direct_price), 2) if raw_base_direct_price is not None else None,
                    "Base Direct Net": round(floored_direct_net, 2) if floored_direct_net is not None else None,
                    "Required Direct Price": floored_direct_price,
                    "Direct Bump %": direct_bump_pct,
                    "Reason": reroute_reason,
                    "_forced_min": "Forced to Manapool minimum" in str(direct_row.get("Reason", "")),
                    "_bump_exceeded": True,
                }
            )
            rerouted_manapool_csv_rows.append(
                base.build_upload_row(
                    source_row,
                    source_columns,
                    column_map,
                    float(pd.to_numeric(direct_row.get("Quantity"), errors="coerce")),
                    float(pd.to_numeric(direct_row.get("Manapool Price"), errors="coerce")),
                )
            )
            continue

        adjusted_reason = _append_reason(direct_row.get("Reason", ""), "Direct floor enforced at $0.40")
        adjusted_direct_row = direct_row.to_dict()
        adjusted_direct_row["Direct Listing Price"] = floored_direct_price
        adjusted_direct_row["Direct Net"] = round(floored_direct_net, 2) if floored_direct_net is not None else None
        adjusted_direct_row["Direct Bump %"] = direct_bump_pct
        adjusted_direct_row["Reason"] = adjusted_reason
        adjusted_direct_rows.append(adjusted_direct_row)
        new_direct_csv_rows.append(
            base.build_upload_row(
                source_row,
                source_columns,
                column_map,
                float(pd.to_numeric(direct_row.get("Quantity"), errors="coerce")),
                floored_direct_price,
            )
        )

    if not rerouted_manapool_rows and len(new_direct_csv_rows) == len(result.direct_full_df):
        result.direct_csv_df = pd.DataFrame(new_direct_csv_rows, columns=source_columns)
        return result

    result.direct_full_df = pd.DataFrame(adjusted_direct_rows, columns=base.DISPLAY_COLUMNS_DIRECT + ["_bump_exceeded"])
    if rerouted_manapool_rows:
        reroute_df = pd.DataFrame(rerouted_manapool_rows, columns=base.DISPLAY_COLUMNS_MANAPOOL + ["_forced_min", "_bump_exceeded"])
        if result.manapool_full_df.empty:
            result.manapool_full_df = reroute_df
        else:
            result.manapool_full_df = pd.concat([result.manapool_full_df, reroute_df], ignore_index=True)
        result.manapool_full_df = result.manapool_full_df.sort_values("Product Name", key=lambda series: series.astype(str).str.lower()).reset_index(drop=True)
        existing_manapool_csv_df = result.manapool_csv_df if not result.manapool_csv_df.empty else pd.DataFrame(columns=source_columns)
        rerouted_csv_df = pd.DataFrame(rerouted_manapool_csv_rows, columns=source_columns)
        result.manapool_csv_df = pd.concat([existing_manapool_csv_df, rerouted_csv_df], ignore_index=True)

    result.direct_full_df = result.direct_full_df.sort_values("Product Name", key=lambda series: series.astype(str).str.lower()).reset_index(drop=True)
    result.direct_csv_df = pd.DataFrame(new_direct_csv_rows, columns=source_columns)

    _rebuild_summary(result, settings)
    result.warning_message = "\n\n".join(
        [message for message in [result.warning_message, "Direct listings with a raw TCG base below $0.40 now use $0.40 as the only Direct floor candidate; they are no longer auto-bumped to $0.45."] if message]
    )
    return result


base.load_manapool_price_lookup = load_manapool_price_lookup
