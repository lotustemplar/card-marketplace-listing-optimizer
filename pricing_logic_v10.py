from __future__ import annotations

from typing import Any

import pandas as pd

import pricing_logic_v08 as base
from pricing_logic_v08 import *  # noqa: F401,F403


USER_AGENT = "CardMarketplaceListingOptimizer/1.1 (+https://github.com/lotustemplar/card-marketplace-listing-optimizer)"
base.USER_AGENT = USER_AGENT
MANAPOOL_SINGLES_PRICES_ENDPOINT = "prices/singles"


def _normalize_set_code(value: Any) -> str:
    return "".join(char for char in base.safe_text(value).strip().lower() if char.isalnum())


def _row_is_foil(condition_text: str) -> bool:
    return "foil" in base.safe_text(condition_text).lower()


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
    codes = {
        _normalize_set_code(candidate.get("set_code", ""))
        for candidate in card_info_candidates
        if base.normalize_header(candidate.get("set_name", "")) == normalized_set_name
        and (not normalized_number or base.normalize_identifier(candidate.get("card_number", "")) == normalized_number)
        and _normalize_set_code(candidate.get("set_code", ""))
    }
    if codes:
        return codes
    return {
        _normalize_set_code(candidate.get("set_code", ""))
        for candidate in card_info_candidates
        if base.normalize_header(candidate.get("set_name", "")) == normalized_set_name
        and _normalize_set_code(candidate.get("set_code", ""))
    }


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


base.load_manapool_price_lookup = load_manapool_price_lookup
process_files = base.process_files
