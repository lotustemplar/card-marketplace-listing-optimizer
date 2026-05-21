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


def _infer_base_direct_price(required_direct_price: Any, direct_bump_pct: Any) -> float | None:
    required_price, required_error = base.try_parse_number(required_direct_price)
    if required_error is not None or required_price is None:
        return None
    bump_value, bump_error = base.try_parse_number(direct_bump_pct)
    if bump_error is not None or bump_value is None:
        return round(required_price, 2)
    denominator = 1 + bump_value
    if denominator <= 0:
        return None
    return round(required_price / denominator, 2)


def _build_direct_row_key_dataframe(df: pd.DataFrame, product_name_column: str, set_name_column: str, number_column: str | None) -> pd.Series:
    return df.apply(
        lambda row: base.build_row_key(
            base.safe_text(row.get(product_name_column, "")),
            base.safe_text(row.get(set_name_column, "")),
            base.safe_text(row.get(number_column, "")) if number_column else "",
        ),
        axis=1,
    )


def _remove_reason_part(reason_text: str, part_to_remove: str) -> str:
    parts = [part.strip() for part in str(reason_text).split(";") if part.strip()]
    filtered = [part for part in parts if part != part_to_remove]
    return "; ".join(filtered)


def _apply_global_bump_cap_to_all_rows(
    result: ProcessResult,
    tcgplayer_bytes: bytes,
    settings: OptimizerSettings,
) -> ProcessResult:
    if result.direct_full_df.empty:
        return result

    direct_full_df = result.direct_full_df.copy()
    forced_direct_mask = direct_full_df["Reason"].astype(str).str.contains(FORCED_DIRECT_REASON, na=False)
    bump_series = pd.to_numeric(direct_full_df["Direct Bump %"], errors="coerce")
    rows_to_reroute_mask = forced_direct_mask & (bump_series > settings.max_direct_bump_pct)
    if not rows_to_reroute_mask.any():
        return result

    source_df = base.load_tcgplayer_dataframe(tcgplayer_bytes)
    column_map, _ = base.map_tcgplayer_columns(source_df)
    source_columns = list(source_df.columns)
    product_name_column = column_map.get("Product Name")
    set_name_column = column_map.get("Set Name")
    number_column = column_map.get("Number")
    marketplace_price_column = column_map.get("TCG Marketplace Price")
    if not product_name_column or not set_name_column:
        return result

    direct_csv_df = result.direct_csv_df.copy()
    manapool_csv_df = result.manapool_csv_df.copy()
    manapool_full_df = result.manapool_full_df.copy()
    rows_to_reroute = direct_full_df.loc[rows_to_reroute_mask].copy()

    source_df = source_df.copy()
    source_df["_row_key"] = _build_direct_row_key_dataframe(source_df, product_name_column, set_name_column, number_column)
    direct_csv_df = direct_csv_df.copy()
    direct_csv_df["_row_key"] = _build_direct_row_key_dataframe(direct_csv_df, product_name_column, set_name_column, number_column)
    rows_to_reroute["_row_key"] = rows_to_reroute.apply(
        lambda row: base.build_row_key(
            base.safe_text(row.get("Product Name", "")),
            base.safe_text(row.get("Set Name", "")),
            base.safe_text(row.get("Number", "")),
        ),
        axis=1,
    )

    direct_csv_indices_by_key: dict[str, list[int]] = {}
    for index, row_key in direct_csv_df["_row_key"].items():
        direct_csv_indices_by_key.setdefault(row_key, []).append(index)

    additional_manapool_rows: list[dict[str, Any]] = []
    additional_manapool_csv_rows: list[dict[str, Any]] = []
    moved_direct_csv_indices: list[int] = []

    for _, row in rows_to_reroute.iterrows():
        row_key = row["_row_key"]
        available_csv_indices = direct_csv_indices_by_key.get(row_key, [])
        csv_row = None
        if available_csv_indices:
            csv_index = available_csv_indices.pop(0)
            moved_direct_csv_indices.append(csv_index)
            csv_row = direct_csv_df.loc[csv_index].drop(labels=["_row_key"], errors="ignore").to_dict()

        if csv_row is None:
            matching_source_rows = source_df[source_df["_row_key"] == row_key]
            if matching_source_rows.empty:
                continue
            csv_row = {column: base.safe_text(matching_source_rows.iloc[0].get(column, "")) for column in source_columns}

        if marketplace_price_column:
            csv_row[marketplace_price_column] = f"{float(row['Manapool Price']):.2f}"
        additional_manapool_csv_rows.append(csv_row)

        updated_reason = _remove_reason_part(base.safe_text(row.get("Reason", "")), FORCED_DIRECT_REASON)
        if "Required Direct bump exceeded max allowed %" not in updated_reason:
            updated_reason = "; ".join(part for part in [updated_reason, "Required Direct bump exceeded max allowed %"] if part)
        required_direct_price = base.try_parse_number(row.get("Direct Listing Price"))[0]
        direct_bump_pct = base.try_parse_number(row.get("Direct Bump %"))[0]
        base_direct_price = _infer_base_direct_price(required_direct_price, direct_bump_pct)
        base_direct_net = base.lookup_direct_net(base_direct_price) if base_direct_price is not None else None
        forced_min = "Forced to Manapool minimum" in base.safe_text(row.get("Reason", ""))

        additional_manapool_rows.append(
            {
                "TCGplayer Id": row.get("TCGplayer Id", ""),
                "Product Line": row.get("Product Line", ""),
                "Set Name": row.get("Set Name", ""),
                "Product Name": row.get("Product Name", ""),
                "Number": row.get("Number", ""),
                "Rarity": row.get("Rarity", ""),
                "Condition": row.get("Condition", ""),
                "Quantity": row.get("Quantity", ""),
                "Manapool Price": row.get("Manapool Price", None),
                "Manapool Net": row.get("Manapool Net", None),
                "Base Direct Price": base_direct_price,
                "Base Direct Net": round(base_direct_net, 2) if base_direct_net is not None else None,
                "Required Direct Price": round(required_direct_price, 2) if required_direct_price is not None else None,
                "Direct Bump %": direct_bump_pct,
                "Reason": updated_reason,
                "_forced_min": forced_min,
                "_bump_exceeded": True,
            }
        )

    direct_full_df = direct_full_df.loc[~rows_to_reroute_mask].reset_index(drop=True)
    if moved_direct_csv_indices:
        direct_csv_df = direct_csv_df.drop(index=moved_direct_csv_indices).reset_index(drop=True)
    direct_csv_df = direct_csv_df.drop(columns=["_row_key"], errors="ignore")

    if additional_manapool_rows:
        manapool_full_df = pd.concat(
            [manapool_full_df, pd.DataFrame(additional_manapool_rows)],
            ignore_index=True,
        )
    if additional_manapool_csv_rows:
        manapool_csv_df = pd.concat(
            [manapool_csv_df, pd.DataFrame(additional_manapool_csv_rows, columns=source_columns)],
            ignore_index=True,
        )

    manapool_preview_df = base.sort_preview(manapool_full_df, base.DISPLAY_COLUMNS_MANAPOOL)
    direct_preview_df = base.sort_preview(direct_full_df, base.DISPLAY_COLUMNS_DIRECT)

    manapool_total_net = 0.0
    direct_total_net = 0.0
    if not manapool_full_df.empty:
        manapool_total_net = float((manapool_full_df["Manapool Net"] * pd.to_numeric(manapool_full_df["Quantity"])).sum())
    if not direct_full_df.empty:
        direct_total_net = float((direct_full_df["Direct Net"] * pd.to_numeric(direct_full_df["Quantity"])).sum())

    direct_bump_average = 0.0
    if not direct_full_df.empty:
        direct_bump_series = pd.to_numeric(direct_full_df["Direct Bump %"], errors="coerce").dropna()
        if not direct_bump_series.empty:
            direct_bump_average = float(direct_bump_series.mean())

    tracked_shipping_review_count = 0
    if not manapool_full_df.empty:
        tracked_shipping_review_count = int((manapool_full_df["Manapool Price"] >= settings.tracked_shipping_threshold).sum())

    updated_summary = dict(result.summary)
    updated_summary["total_cards_assigned_manapool"] = int(pd.to_numeric(manapool_full_df["Quantity"], errors="coerce").sum()) if not manapool_full_df.empty else 0
    updated_summary["total_cards_assigned_direct"] = int(pd.to_numeric(direct_full_df["Quantity"], errors="coerce").sum()) if not direct_full_df.empty else 0
    updated_summary["total_estimated_manapool_net"] = round(manapool_total_net, 2)
    updated_summary["total_estimated_direct_net"] = round(direct_total_net, 2)
    updated_summary["combined_estimated_net"] = round(manapool_total_net + direct_total_net, 2)
    updated_summary["average_direct_bump_pct"] = direct_bump_average
    updated_summary["direct_bump_exceeded_count"] = int(updated_summary.get("direct_bump_exceeded_count", 0)) + len(additional_manapool_rows)
    updated_summary["tracked_shipping_review_count"] = tracked_shipping_review_count

    analysis_df = base.build_analysis_dataframe(updated_summary, settings)

    return ProcessResult(
        manapool_full_df=manapool_full_df.sort_values("Product Name", key=lambda series: series.astype(str).str.lower()).reset_index(drop=True),
        direct_full_df=direct_full_df.sort_values("Product Name", key=lambda series: series.astype(str).str.lower()).reset_index(drop=True),
        manapool_preview_df=manapool_preview_df,
        direct_preview_df=direct_preview_df,
        manapool_csv_df=manapool_csv_df.reset_index(drop=True),
        direct_csv_df=direct_csv_df.reset_index(drop=True),
        errors_df=result.errors_df,
        analysis_df=analysis_df,
        summary=updated_summary,
        settings=result.settings,
        missing_columns=result.missing_columns,
        unresolved_options=result.unresolved_options,
        warning_message=result.warning_message,
    )


base.load_manapool_price_lookup = load_manapool_price_lookup


def process_files(
    tcgplayer_bytes: bytes,
    settings: OptimizerSettings,
    manapool_api_key: str | None = None,
    manapool_email: str | None = None,
    manapool_match_overrides: dict[str, dict[str, Any]] | None = None,
) -> ProcessResult:
    initial_result = base.process_files(
        tcgplayer_bytes=tcgplayer_bytes,
        settings=settings,
        manapool_api_key=manapool_api_key,
        manapool_email=manapool_email,
        manapool_match_overrides=manapool_match_overrides,
    )
    return _apply_global_bump_cap_to_all_rows(initial_result, tcgplayer_bytes, settings)
