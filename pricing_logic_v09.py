from __future__ import annotations

from typing import Any

import pricing_logic_v08 as base
from pricing_logic_v08 import *  # noqa: F401,F403


USER_AGENT = "CardMarketplaceListingOptimizer/0.9 (+https://github.com/lotustemplar/card-marketplace-listing-optimizer)"
base.USER_AGENT = USER_AGENT


def _normalize_set_code(value: Any) -> str:
    return "".join(char for char in base.safe_text(value).strip().lower() if char.isalnum())


def _dedupe_variant_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
        current_price, _ = base.try_parse_number(candidate.get("low_price"))
        existing_price, _ = base.try_parse_number(existing.get("low_price"))
        if current_price is not None and (existing_price is None or current_price < existing_price):
            deduped[key] = candidate
    return list(deduped.values())


def _candidate_price_from_variant(candidate: dict[str, Any]) -> float | None:
    cents_value, parse_error = base.try_parse_number(candidate.get("low_price"))
    if parse_error is not None or cents_value is None:
        return None
    return round(cents_value / 100.0, 2)


def _build_refined_option(candidate: dict[str, Any], source: str) -> dict[str, Any] | None:
    if source == "variant":
        price = _candidate_price_from_variant(candidate)
        if price is None:
            return None
        set_code = base.safe_text(candidate.get("set_code", ""))
        card_number = base.safe_text(candidate.get("number", ""))
        url = base.safe_text(candidate.get("url", ""))
        label = f"{base.safe_text(candidate.get('name', 'Unknown card'))} | {set_code or 'Unknown set'}"
        if card_number:
            label += f" | #{card_number}"
        label += f" | ${price:.2f}"
        if url:
            label += f" | {url}"
        return {
            "label": label,
            "price": price,
            "name": base.safe_text(candidate.get("name", "")),
            "set_name": "",
            "set_code": set_code,
            "card_number": card_number,
            "reason": f"Mana Pool manual override via variant prices: {label}",
        }
    return base.build_candidate_option(candidate, source)


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
    if not product_name_column or not set_name_column:
        return {}, {}, None, [], 0

    overrides = manapool_match_overrides or {}
    unique_keys = sorted(
        {
            (
                base.safe_text(row.get(product_name_column, "")),
                base.safe_text(row.get(set_name_column, "")),
                base.safe_text(row.get(number_column, "")) if number_column else "",
            )
            for _, row in tcg_df.iterrows()
            if base.safe_text(row.get(product_name_column, "")) and base.safe_text(row.get(set_name_column, ""))
        }
    )
    if not unique_keys:
        return {}, {}, None, [], 0

    unique_names = sorted({product_name for product_name, _, _ in unique_keys})
    try:
        cards_by_name = {}
        for start in range(0, len(unique_names), base.MANAPOOL_BATCH_SIZE):
            batch = unique_names[start : start + base.MANAPOOL_BATCH_SIZE]
            cards_by_name.update(base.fetch_manapool_cards_by_names(batch, manapool_api_key, manapool_email))
    except Exception as exc:
        return {}, {}, f"Mana Pool API lookup was unavailable, so TCG fallback pricing was used instead. Details: {exc}", [], 0

    variant_candidates_by_name: dict[str, list[dict[str, Any]]] | None = None
    variant_warning: str | None = None

    price_lookup: dict[tuple[str, str, str], float] = {}
    source_lookup: dict[tuple[str, str, str], str] = {}
    unresolved_options: list[dict[str, Any]] = []
    misses = 0
    manual_override_count = 0

    for product_name, set_name, card_number in unique_keys:
        row_tuple = (
            base.normalize_header(product_name),
            base.normalize_header(set_name),
            base.normalize_identifier(card_number),
        )
        row_key = base.build_row_key(product_name, set_name, card_number)

        if row_key in overrides:
            override = overrides[row_key]
            override_price, parse_error = base.try_parse_number(override.get("price"))
            if parse_error is None and override_price is not None:
                price_lookup[row_tuple] = round(override_price, 2)
                source_lookup[row_tuple] = base.safe_text(override.get("reason", "Mana Pool manual override"))
                manual_override_count += 1
                continue

        card_info_candidates = cards_by_name.get(base.normalize_header(product_name), [])
        direct_match = base.choose_manapool_match(card_info_candidates, product_name, set_name, card_number)
        if direct_match:
            cents_value, parse_error = base.try_parse_number(direct_match.get("from_price_cents"))
            if parse_error is None and cents_value is not None:
                price_lookup[row_tuple] = round(cents_value / 100.0, 2)
                source_lookup[row_tuple] = "Mana Pool API floor"
                continue

        if variant_candidates_by_name is None:
            try:
                variant_candidates_by_name, variant_warning = base.fetch_manapool_variant_candidates(manapool_api_key, manapool_email)
            except Exception as exc:
                variant_candidates_by_name = {}
                variant_warning = f"Mana Pool variant price lookup was unavailable for unresolved rows. Details: {exc}"

        variant_candidates = _dedupe_variant_candidates(variant_candidates_by_name.get(base.normalize_header(product_name), []))
        normalized_row_set_name = base.normalize_header(set_name)
        normalized_row_number = base.normalize_identifier(card_number)

        target_set_codes = {
            _normalize_set_code(candidate.get("set_code", ""))
            for candidate in card_info_candidates
            if base.normalize_header(candidate.get("set_name", "")) == normalized_row_set_name and _normalize_set_code(candidate.get("set_code", ""))
        }

        same_set_variants = [
            candidate for candidate in variant_candidates if _normalize_set_code(candidate.get("set_code", "")) in target_set_codes
        ] if target_set_codes else []

        exact_same_set_same_number = [
            candidate for candidate in same_set_variants if base.normalize_identifier(candidate.get("number", "")) == normalized_row_number
        ]

        if len(exact_same_set_same_number) == 1:
            chosen = exact_same_set_same_number[0]
            price = _candidate_price_from_variant(chosen)
            if price is not None:
                price_lookup[row_tuple] = price
                source_lookup[row_tuple] = "Mana Pool variant price exact printing"
                continue

        options: list[dict[str, Any]] = []
        seen_labels: set[str] = set()

        preferred_card_info = [
            candidate for candidate in card_info_candidates
            if base.normalize_header(candidate.get("set_name", "")) == normalized_row_set_name
            and (not normalized_row_number or base.normalize_identifier(candidate.get("card_number", "")) == normalized_row_number)
        ]

        preferred_variants = exact_same_set_same_number or same_set_variants
        if not preferred_variants and normalized_row_number:
            preferred_variants = [
                candidate for candidate in variant_candidates if base.normalize_identifier(candidate.get("number", "")) == normalized_row_number
            ]
        if not preferred_variants:
            preferred_variants = variant_candidates

        for candidate in preferred_card_info:
            option = _build_refined_option(candidate, "card_info")
            if not option or option["label"] in seen_labels:
                continue
            seen_labels.add(option["label"])
            options.append(option)

        for candidate in preferred_variants:
            option = _build_refined_option(candidate, "variant")
            if not option or option["label"] in seen_labels:
                continue
            seen_labels.add(option["label"])
            options.append(option)

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
    if variant_warning:
        warnings.append(variant_warning)

    return price_lookup, source_lookup, "\n\n".join(warnings) if warnings else None, unresolved_options, manual_override_count


base.load_manapool_price_lookup = load_manapool_price_lookup
process_files = base.process_files
