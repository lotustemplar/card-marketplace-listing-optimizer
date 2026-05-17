from __future__ import annotations

from dataclasses import asdict, dataclass
from io import BytesIO
from typing import Any

import pandas as pd


DISPLAY_COLUMNS_MANAPOOL = [
    "TCGplayer Id",
    "Product Line",
    "Set Name",
    "Product Name",
    "Number",
    "Rarity",
    "Condition",
    "Quantity",
    "Manapool Price",
    "Manapool Net",
    "Base Direct Price",
    "Base Direct Net",
    "Required Direct Price",
    "Direct Bump %",
    "Reason",
]

DISPLAY_COLUMNS_DIRECT = [
    "TCGplayer Id",
    "Product Line",
    "Set Name",
    "Product Name",
    "Number",
    "Rarity",
    "Condition",
    "Quantity",
    "Direct Listing Price",
    "Direct Net",
    "Manapool Price",
    "Manapool Net",
    "Direct Bump %",
    "Reason",
]


COLUMN_ALIASES = {
    "TCGplayer Id": ["tcgplayer id", "tcgplayerid"],
    "Product Line": ["product line", "productline"],
    "Set Name": ["set name", "setname"],
    "Product Name": ["product name", "productname", "title"],
    "Number": ["number"],
    "Rarity": ["rarity"],
    "Condition": ["condition"],
    "TCG Market Price": ["tcg market price", "tcgmarketprice"],
    "TCG Direct Low": ["tcg direct low", "tcgdirectlow"],
    "TCG Low Price": ["tcg low price", "tcglowprice"],
    "TCG Marketplace Price": ["tcg marketplace price", "tcgmarketplaceprice"],
    "Total Quantity": ["total quantity", "totalquantity"],
    "Add to Quantity": ["add to quantity", "addtoquantity"],
}


REQUIRED_COLUMNS = [
    "TCGplayer Id",
    "Product Line",
    "Set Name",
    "Product Name",
    "TCG Market Price",
    "TCG Direct Low",
    "TCG Low Price",
    "Total Quantity",
]


@dataclass
class OptimizerSettings:
    manapool_min_price: float = 0.25
    manapool_platform_fee: float = 0.05
    credit_card_fee: float = 0.029
    processing_fee: float = 0.30
    buyer_shipping_charged: float = 1.31
    stamp_cost: float = 0.75
    toploader_cost: float = 0.10
    envelope_cost: float = 0.03
    team_bag_cost: float = 0.03
    max_direct_bump_pct: float = 0.20
    direct_cliff_start: float = 3.00
    direct_cliff_end: float = 3.40
    tracked_shipping_threshold: float = 50.00
    tracked_shipping_cost: float = 6.00

    @property
    def shipping_supply_cost(self) -> float:
        return self.stamp_cost + self.toploader_cost + self.envelope_cost + self.team_bag_cost

    def as_display_rows(self) -> list[dict[str, Any]]:
        rows = []
        for key, value in asdict(self).items():
            label = key.replace("_", " ").title()
            if "pct" in key or "fee" in key:
                display = f"{value:.2%}" if value <= 1 else f"{value:.2f}"
            else:
                display = f"{value:.2f}" if isinstance(value, float) else value
            rows.append({"Metric": label, "Value": display})
        rows.append(
            {
                "Metric": "Actual Shipping/Supply Cost",
                "Value": f"${self.shipping_supply_cost:.2f}",
            }
        )
        return rows


@dataclass
class ProcessResult:
    manapool_full_df: pd.DataFrame
    direct_full_df: pd.DataFrame
    manapool_preview_df: pd.DataFrame
    direct_preview_df: pd.DataFrame
    manapool_csv_df: pd.DataFrame
    direct_csv_df: pd.DataFrame
    errors_df: pd.DataFrame
    analysis_df: pd.DataFrame
    summary: dict[str, Any]
    settings: OptimizerSettings
    missing_columns: list[str]
    warning_message: str | None = None


def normalize_header(value: Any) -> str:
    text = "" if value is None else str(value).strip().lower()
    compact = []
    last_space = False
    for char in text:
        if char.isalnum():
            compact.append(char)
            last_space = False
        elif not last_space:
            compact.append(" ")
            last_space = True
    return "".join(compact).strip()


def parse_uploaded_csv(file_bytes: bytes) -> pd.DataFrame:
    encodings = ["utf-8-sig", "utf-8", "cp1252", "latin-1"]
    last_error: Exception | None = None
    for encoding in encodings:
        try:
            return pd.read_csv(BytesIO(file_bytes), dtype=str, keep_default_na=False, encoding=encoding)
        except Exception as exc:
            last_error = exc
    raise ValueError(f"Unable to read CSV file: {last_error}") from last_error


def load_tcgplayer_dataframe(file_bytes: bytes) -> pd.DataFrame:
    df = parse_uploaded_csv(file_bytes)
    df.columns = [str(column).strip() for column in df.columns]
    return df


def map_tcgplayer_columns(df: pd.DataFrame) -> tuple[dict[str, str], list[str]]:
    normalized_lookup = {normalize_header(column): column for column in df.columns}
    mapped: dict[str, str] = {}
    missing: list[str] = []

    for canonical, aliases in COLUMN_ALIASES.items():
        found = None
        for alias in aliases:
            if alias in normalized_lookup:
                found = normalized_lookup[alias]
                break
        if found is None:
            if canonical in REQUIRED_COLUMNS:
                missing.append(canonical)
        else:
            mapped[canonical] = found

    return mapped, missing


def try_parse_number(value: Any) -> tuple[float | None, str | None]:
    if value is None:
        return None, None
    if isinstance(value, (int, float)) and not pd.isna(value):
        return float(value), None

    text = str(value).strip()
    if text == "" or text.lower() in {"nan", "none", "null", "n/a", "na", "--"}:
        return None, None

    cleaned = text.replace("$", "").replace(",", "")
    try:
        return float(cleaned), None
    except ValueError:
        return None, "Invalid numeric value"


def safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def normalize_quantity(quantity: float) -> int | float:
    if abs(quantity - round(quantity)) < 1e-9:
        return int(round(quantity))
    return round(quantity, 2)


def calculate_manapool_net(card_price: float, settings: OptimizerSettings) -> float:
    gross = card_price + settings.buyer_shipping_charged
    fees = gross * (settings.manapool_platform_fee + settings.credit_card_fee) + settings.processing_fee
    net = gross - fees - settings.shipping_supply_cost
    return round(net, 2)


def calculate_direct_net(listing_price: float) -> float:
    if listing_price < 2.50:
        return round(listing_price * 0.50, 2)
    fees = 1.12 + (listing_price * 0.0895) + (listing_price * 0.025)
    return round(listing_price - fees, 2)


def lookup_direct_net(proposed_price: float | None) -> float | None:
    if proposed_price is None:
        return None
    return calculate_direct_net(round(proposed_price, 2))


def find_required_direct_price(target_net: float) -> float | None:
    if target_net <= 0:
        return 0.01

    for cents in range(1, 500001):
        listing_price = cents / 100
        if calculate_direct_net(listing_price) >= round(target_net, 2):
            return round(listing_price, 2)
    return None


def find_next_direct_price_above(threshold: float) -> float | None:
    return round(threshold + 0.01, 2)


def calculate_direct_bump_pct(base_price: float | None, required_price: float | None) -> float | None:
    if base_price is None or required_price is None or base_price <= 0:
        return None
    return (required_price - base_price) / base_price


def build_error_row(row: pd.Series | None, error_reason: str, source_columns: list[str]) -> dict[str, Any]:
    payload = {column: "" for column in source_columns}
    if row is not None:
        payload.update({column: safe_text(row.get(column, "")) for column in source_columns})
    payload["Error reason"] = error_reason
    return payload


def build_upload_row(
    row: pd.Series,
    source_columns: list[str],
    column_map: dict[str, str],
    quantity: int | float,
    listing_price: float,
) -> dict[str, Any]:
    upload_row = {column: safe_text(row.get(column, "")) for column in source_columns}
    formatted_price = f"{listing_price:.2f}"
    formatted_quantity = str(normalize_quantity(float(quantity)))

    marketplace_price_column = column_map.get("TCG Marketplace Price")
    if marketplace_price_column:
        upload_row[marketplace_price_column] = formatted_price

    add_to_quantity_column = column_map.get("Add to Quantity")
    total_quantity_column = column_map.get("Total Quantity")
    if add_to_quantity_column:
        upload_row[add_to_quantity_column] = formatted_quantity
    elif total_quantity_column:
        upload_row[total_quantity_column] = formatted_quantity

    return upload_row


def sort_preview(df: pd.DataFrame, display_columns: list[str]) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=display_columns)
    sorted_df = df.sort_values("Product Name", key=lambda series: series.astype(str).str.lower()).reset_index(drop=True)
    return sorted_df[display_columns]


def build_analysis_dataframe(summary: dict[str, Any], settings: OptimizerSettings) -> pd.DataFrame:
    rows = [
        {"Metric": "Total rows imported", "Value": summary["total_rows_imported"]},
        {"Metric": "Total quantity imported", "Value": summary["total_quantity_imported"]},
        {"Metric": "Total cards assigned to Manapool", "Value": summary["total_cards_assigned_manapool"]},
        {"Metric": "Total cards assigned to TCGPlayer Direct", "Value": summary["total_cards_assigned_direct"]},
        {"Metric": "Total estimated Manapool net", "Value": round(summary["total_estimated_manapool_net"], 2)},
        {"Metric": "Total estimated Direct net", "Value": round(summary["total_estimated_direct_net"], 2)},
        {"Metric": "Combined estimated net", "Value": round(summary["combined_estimated_net"], 2)},
        {"Metric": "Average Direct bump %", "Value": summary["average_direct_bump_pct"]},
        {"Metric": "Number of skipped/error rows", "Value": summary["skipped_error_rows"]},
        {"Metric": "Number of cards with missing price data", "Value": summary["missing_price_data_count"]},
        {
            "Metric": f"Number of cards forced to Manapool ${settings.manapool_min_price:.2f} minimum",
            "Value": summary["forced_manapool_min_count"],
        },
        {"Metric": "Number of cards where Direct bump exceeded max allowed %", "Value": summary["direct_bump_exceeded_count"]},
        {
            "Metric": (
                f"Number of cards affected by the ${settings.direct_cliff_start:.2f}-${settings.direct_cliff_end:.2f} Direct cliff"
            ),
            "Value": summary["direct_cliff_affected_count"],
        },
        {"Metric": "Manapool listings at or above tracked shipping threshold", "Value": summary["tracked_shipping_review_count"]},
        {
            "Metric": "Tracked shipping review warning",
            "Value": (
                f"Review Manapool cards at or above ${settings.tracked_shipping_threshold:.2f}; "
                f"tracked shipping can add about ${settings.tracked_shipping_cost:.2f} to fulfillment."
            ),
        },
        {"Metric": "", "Value": ""},
        {"Metric": "Current settings used for the run", "Value": ""},
    ]
    rows.extend(settings.as_display_rows())
    return pd.DataFrame(rows)


def process_files(
    tcgplayer_bytes: bytes,
    direct_fee_bytes: bytes | None,
    direct_fee_filename: str | None,
    settings: OptimizerSettings,
) -> ProcessResult:
    tcg_df = load_tcgplayer_dataframe(tcgplayer_bytes)

    column_map, missing_columns = map_tcgplayer_columns(tcg_df)
    source_columns = list(tcg_df.columns)

    if missing_columns:
        errors_df = pd.DataFrame(
            [
                build_error_row(
                    None,
                    f"Required CSV column missing: {', '.join(missing_columns)}",
                    source_columns if source_columns else ["Original row data"],
                )
            ]
        )
        summary = {
            "total_rows_imported": int(len(tcg_df)),
            "total_quantity_imported": 0,
            "total_cards_assigned_manapool": 0,
            "total_cards_assigned_direct": 0,
            "total_estimated_manapool_net": 0.0,
            "total_estimated_direct_net": 0.0,
            "combined_estimated_net": 0.0,
            "average_direct_bump_pct": 0.0,
            "skipped_error_rows": int(len(tcg_df)),
            "missing_price_data_count": 0,
            "forced_manapool_min_count": 0,
            "direct_bump_exceeded_count": 0,
            "direct_cliff_affected_count": 0,
            "tracked_shipping_review_count": 0,
        }
        analysis_df = build_analysis_dataframe(summary, settings)
        return ProcessResult(
            manapool_full_df=pd.DataFrame(columns=DISPLAY_COLUMNS_MANAPOOL + ["_forced_min", "_bump_exceeded", "_cliff_affected"]),
            direct_full_df=pd.DataFrame(columns=DISPLAY_COLUMNS_DIRECT + ["_bump_exceeded", "_cliff_affected"]),
            manapool_preview_df=pd.DataFrame(columns=DISPLAY_COLUMNS_MANAPOOL),
            direct_preview_df=pd.DataFrame(columns=DISPLAY_COLUMNS_DIRECT),
            manapool_csv_df=pd.DataFrame(columns=source_columns),
            direct_csv_df=pd.DataFrame(columns=source_columns),
            errors_df=errors_df,
            analysis_df=analysis_df,
            summary=summary,
            settings=settings,
            missing_columns=missing_columns,
            warning_message="Required columns are missing from the TCGPlayer export.",
        )

    manapool_rows: list[dict[str, Any]] = []
    direct_rows: list[dict[str, Any]] = []
    manapool_csv_rows: list[dict[str, Any]] = []
    direct_csv_rows: list[dict[str, Any]] = []
    error_rows: list[dict[str, Any]] = []

    total_quantity_imported = 0.0
    missing_price_data_count = 0
    forced_manapool_min_count = 0
    direct_bump_exceeded_count = 0
    direct_cliff_affected_count = 0

    for _, row in tcg_df.iterrows():
        row_errors: list[str] = []
        numeric_fields = {
            "market_price": "TCG Market Price",
            "direct_low": "TCG Direct Low",
            "low_price": "TCG Low Price",
            "total_quantity": "Total Quantity",
        }
        if "Add to Quantity" in column_map:
            numeric_fields["add_quantity"] = "Add to Quantity"

        parsed_values: dict[str, float | None] = {}
        for key, canonical in numeric_fields.items():
            actual_column = column_map.get(canonical)
            raw_value = row.get(actual_column, "") if actual_column else ""
            parsed_value, parse_error = try_parse_number(raw_value)
            parsed_values[key] = parsed_value
            if parse_error:
                row_errors.append(f"Invalid numeric value in {canonical}")

        add_quantity = parsed_values.get("add_quantity")
        total_quantity = parsed_values.get("total_quantity")
        if add_quantity is not None and add_quantity > 0:
            quantity = add_quantity
        else:
            quantity = total_quantity

        if quantity is None or quantity <= 0:
            row_errors.append("Missing quantity")

        market_price = parsed_values.get("market_price")
        direct_low = parsed_values.get("direct_low")
        low_price = parsed_values.get("low_price")

        if low_price is None and market_price is None:
            row_errors.append("Missing both TCG Low Price and TCG Market Price")
        if direct_low is None and market_price is None:
            row_errors.append("Missing both TCG Direct Low and TCG Market Price")

        if row_errors:
            if any("Missing both TCG" in error for error in row_errors):
                missing_price_data_count += 1
            error_rows.append(build_error_row(row, "; ".join(dict.fromkeys(row_errors)), source_columns))
            continue

        assert quantity is not None
        total_quantity_imported += quantity

        chosen_manapool_base = low_price if low_price is not None else market_price
        assert chosen_manapool_base is not None
        forced_min = chosen_manapool_base < settings.manapool_min_price
        manapool_price = max(chosen_manapool_base, settings.manapool_min_price)
        if forced_min:
            forced_manapool_min_count += 1

        manapool_net = calculate_manapool_net(manapool_price, settings)

        if direct_low is None:
            base_direct_price = market_price
        elif market_price is None:
            base_direct_price = direct_low
        else:
            base_direct_price = max(market_price, direct_low)

        base_direct_net = lookup_direct_net(base_direct_price)
        required_direct_price = find_required_direct_price(manapool_net)
        if base_direct_price is not None and base_direct_net is not None and base_direct_net >= manapool_net:
            required_direct_price = round(base_direct_price, 2)

        cliff_affected = False
        bump_exceeded = False
        direct_bump_pct = None
        reason_parts: list[str] = []

        if forced_min:
            reason_parts.append("Forced to Manapool minimum")

        direct_listing_price = required_direct_price
        display_required_direct_price = required_direct_price
        direct_net = lookup_direct_net(direct_listing_price) if direct_listing_price is not None else None

        if direct_listing_price is None or direct_net is None:
            reason_parts.append("Required Direct Price not found")
            destination = "manapool"
        else:
            if settings.direct_cliff_start <= direct_listing_price <= settings.direct_cliff_end:
                cliff_affected = True
                direct_cliff_affected_count += 1
                pre_cliff_price = round(max(settings.direct_cliff_start - 0.01, 0.01), 2)
                pre_cliff_net = lookup_direct_net(pre_cliff_price)
                if pre_cliff_net is not None and pre_cliff_net >= manapool_net:
                    direct_listing_price = pre_cliff_price
                    display_required_direct_price = pre_cliff_price
                    direct_net = pre_cliff_net
                    reason_parts.append("Adjusted to avoid Direct pricing cliff")
                else:
                    post_cliff_price = find_next_direct_price_above(settings.direct_cliff_end)
                    if post_cliff_price is None:
                        reason_parts.append("No valid Direct price above pricing cliff")
                        destination = "manapool"
                        direct_listing_price = None
                        direct_net = None
                    else:
                        direct_listing_price = post_cliff_price
                        display_required_direct_price = post_cliff_price
                        direct_net = lookup_direct_net(post_cliff_price)
                        reason_parts.append("Bumped above Direct pricing cliff")

            if direct_listing_price is None or direct_net is None:
                destination = "manapool"
            else:
                direct_bump_pct = calculate_direct_bump_pct(base_direct_price, direct_listing_price)
                if direct_bump_pct is None:
                    bump_exceeded = True
                    direct_bump_exceeded_count += 1
                    reason_parts.append("Unable to calculate Direct bump %")
                    destination = "manapool"
                elif direct_bump_pct > settings.max_direct_bump_pct:
                    bump_exceeded = True
                    direct_bump_exceeded_count += 1
                    if base_direct_price is not None and base_direct_price < settings.direct_cliff_start:
                        reason_parts.append("Base Direct price below cliff and required bump exceeded max")
                    else:
                        reason_parts.append("Required Direct bump exceeded max allowed %")
                    destination = "manapool"
                else:
                    destination = "direct"
                    reason_parts.append("Direct net meets or beats Manapool within bump limit")

        row_base = {
            "TCGplayer Id": safe_text(row.get(column_map["TCGplayer Id"], "")),
            "Product Line": safe_text(row.get(column_map["Product Line"], "")),
            "Set Name": safe_text(row.get(column_map["Set Name"], "")),
            "Product Name": safe_text(row.get(column_map["Product Name"], "")),
            "Number": safe_text(row.get(column_map.get("Number", ""), "")) if column_map.get("Number") else "",
            "Rarity": safe_text(row.get(column_map.get("Rarity", ""), "")) if column_map.get("Rarity") else "",
            "Condition": safe_text(row.get(column_map.get("Condition", ""), "")) if column_map.get("Condition") else "",
            "Quantity": normalize_quantity(quantity),
        }

        if destination == "direct":
            direct_csv_rows.append(build_upload_row(row, source_columns, column_map, quantity, direct_listing_price))
            direct_rows.append(
                {
                    **row_base,
                    "Direct Listing Price": round(direct_listing_price, 2) if direct_listing_price is not None else None,
                    "Direct Net": round(direct_net, 2) if direct_net is not None else None,
                    "Manapool Price": round(manapool_price, 2),
                    "Manapool Net": round(manapool_net, 2),
                    "Direct Bump %": direct_bump_pct,
                    "Reason": "; ".join(reason_parts),
                    "_bump_exceeded": bump_exceeded,
                    "_cliff_affected": cliff_affected,
                }
            )
        else:
            if manapool_price >= settings.tracked_shipping_threshold:
                reason_parts.append("Review for tracked shipping threshold")
            manapool_csv_rows.append(build_upload_row(row, source_columns, column_map, quantity, manapool_price))
            manapool_rows.append(
                {
                    **row_base,
                    "Manapool Price": round(manapool_price, 2),
                    "Manapool Net": round(manapool_net, 2),
                    "Base Direct Price": round(base_direct_price, 2) if base_direct_price is not None else None,
                    "Base Direct Net": round(base_direct_net, 2) if base_direct_net is not None else None,
                    "Required Direct Price": round(display_required_direct_price, 2) if display_required_direct_price is not None else None,
                    "Direct Bump %": direct_bump_pct,
                    "Reason": "; ".join(reason_parts),
                    "_forced_min": forced_min,
                    "_bump_exceeded": bump_exceeded,
                    "_cliff_affected": cliff_affected,
                }
            )

    manapool_full_df = pd.DataFrame(
        manapool_rows,
        columns=DISPLAY_COLUMNS_MANAPOOL + ["_forced_min", "_bump_exceeded", "_cliff_affected"],
    )
    direct_full_df = pd.DataFrame(
        direct_rows,
        columns=DISPLAY_COLUMNS_DIRECT + ["_bump_exceeded", "_cliff_affected"],
    )
    errors_df = pd.DataFrame(error_rows)

    manapool_preview_df = sort_preview(manapool_full_df, DISPLAY_COLUMNS_MANAPOOL)
    direct_preview_df = sort_preview(direct_full_df, DISPLAY_COLUMNS_DIRECT)
    manapool_csv_df = pd.DataFrame(manapool_csv_rows, columns=source_columns)
    direct_csv_df = pd.DataFrame(direct_csv_rows, columns=source_columns)

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

    summary = {
        "total_rows_imported": int(len(tcg_df)),
        "total_quantity_imported": normalize_quantity(total_quantity_imported) if total_quantity_imported else 0,
        "total_cards_assigned_manapool": int(pd.to_numeric(manapool_full_df["Quantity"], errors="coerce").sum()) if not manapool_full_df.empty else 0,
        "total_cards_assigned_direct": int(pd.to_numeric(direct_full_df["Quantity"], errors="coerce").sum()) if not direct_full_df.empty else 0,
        "total_estimated_manapool_net": round(manapool_total_net, 2),
        "total_estimated_direct_net": round(direct_total_net, 2),
        "combined_estimated_net": round(manapool_total_net + direct_total_net, 2),
        "average_direct_bump_pct": direct_bump_average,
        "skipped_error_rows": int(len(errors_df)),
        "missing_price_data_count": missing_price_data_count,
        "forced_manapool_min_count": forced_manapool_min_count,
        "direct_bump_exceeded_count": direct_bump_exceeded_count,
        "direct_cliff_affected_count": direct_cliff_affected_count,
        "tracked_shipping_review_count": tracked_shipping_review_count,
    }

    analysis_df = build_analysis_dataframe(summary, settings)
    warning_message = None
    if tracked_shipping_review_count:
        warning_message = (
            f"{tracked_shipping_review_count} Manapool listing(s) are at or above "
            f"${settings.tracked_shipping_threshold:.2f} and may need manual tracked-shipping review."
        )

    return ProcessResult(
        manapool_full_df=manapool_full_df.sort_values("Product Name", key=lambda series: series.astype(str).str.lower()).reset_index(drop=True),
        direct_full_df=direct_full_df.sort_values("Product Name", key=lambda series: series.astype(str).str.lower()).reset_index(drop=True),
        manapool_preview_df=manapool_preview_df,
        direct_preview_df=direct_preview_df,
        manapool_csv_df=manapool_csv_df,
        direct_csv_df=direct_csv_df,
        errors_df=errors_df,
        analysis_df=analysis_df,
        summary=summary,
        settings=settings,
        missing_columns=missing_columns,
        warning_message=warning_message,
    )
