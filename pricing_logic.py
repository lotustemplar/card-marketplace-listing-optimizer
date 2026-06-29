from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from io import BytesIO
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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

EXPORT_COLUMNS = [
    "TCGplayer Id",
    "Product Line",
    "Set Name",
    "Product Name",
    "Title",
    "Number",
    "Rarity",
    "Condition",
    "TCG Market Price",
    "TCG Direct Low",
    "TCG Low Price With Shipping",
    "TCG Low Price",
    "Total Quantity",
    "Add to Quantity",
    "TCG Marketplace Price",
    "Photo URL",
]

TCG_COLUMN_ALIASES = {
    "TCGplayer Id": ["tcgplayer id", "tcgplayerid"],
    "Product Line": ["product line", "productline"],
    "Set Name": ["set name", "setname"],
    "Product Name": ["product name", "productname"],
    "Title": ["title"],
    "Number": ["number"],
    "Rarity": ["rarity"],
    "Condition": ["condition"],
    "TCG Market Price": ["tcg market price", "tcgmarketprice"],
    "TCG Direct Low": ["tcg direct low", "tcgdirectlow"],
    "TCG Low Price With Shipping": ["tcg low price with shipping", "tcglowpricewithshipping"],
    "TCG Low Price": ["tcg low price", "tcglowprice"],
    "TCG Marketplace Price": ["tcg marketplace price", "tcgmarketplaceprice"],
    "Total Quantity": ["total quantity", "totalquantity"],
    "Add to Quantity": ["add to quantity", "addtoquantity"],
    "Photo URL": ["photo url", "photourl"],
}

TCG_REQUIRED_COLUMNS = [
    "Product Line",
    "Set Name",
    "Product Name",
    "TCG Market Price",
    "Total Quantity",
]

MANABOX_COLUMN_ALIASES = {
    "Name": ["name"],
    "Set code": ["set code", "setcode"],
    "Set name": ["set name", "setname"],
    "Collector number": ["collector number", "collectornumber", "number"],
    "Foil": ["foil"],
    "Rarity": ["rarity"],
    "Quantity": ["quantity", "qty"],
    "Scryfall ID": ["scryfall id", "scryfallid"],
    "Purchase price": ["purchase price", "purchaseprice", "purchase_price"],
    "Condition": ["condition"],
    "Language": ["language"],
}

MANABOX_REQUIRED_COLUMNS = [
    "Name",
    "Set code",
    "Set name",
    "Collector number",
    "Foil",
    "Rarity",
    "Quantity",
    "Purchase price",
    "Condition",
]

SCAN_EXPORT_COLUMN_ALIASES = {
    "game": ["game"],
    "set": ["set"],
    "card_name": ["card name", "card_name", "cardname"],
    "card_number": ["card number", "card_number", "cardnumber"],
    "variant": ["variant"],
    "condition": ["condition"],
    "language": ["language"],
    "tcgplayer_id": ["tcgplayer id", "tcgplayer_id", "tcgplayerid"],
    "manapool_id": ["manapool id", "manapool_id", "manapoolid"],
    "market_price": ["market price", "market_price", "marketprice"],
    "manapool_price": ["manapool price", "manapool_price", "manapoolprice"],
}

SCAN_EXPORT_REQUIRED_COLUMNS = [
    "game",
    "set",
    "card_name",
    "card_number",
    "variant",
    "condition",
    "language",
    "tcgplayer_id",
]

SCRYFALL_CARD_API_TEMPLATE = "https://api.scryfall.com/cards/{scryfall_id}"
SCRYFALL_HEADERS = {
    "User-Agent": "CardMarketplaceListingOptimizer/3.2",
    "Accept": "application/json;q=0.9,*/*;q=0.8",
}

PERCENT_SETTING_FIELDS = {
    "manapool_platform_fee",
    "credit_card_fee",
    "max_direct_bump_pct",
}

CURRENCY_SETTING_FIELDS = {
    "manapool_min_price",
    "processing_fee",
    "buyer_shipping_charged",
    "stamp_cost",
    "toploader_cost",
    "envelope_cost",
    "team_bag_cost",
    "tracked_shipping_threshold",
    "tracked_shipping_cost",
    "direct_min_listing_price",
}

SETTING_LABELS = {
    "manapool_min_price": "Manapool minimum price",
    "manapool_platform_fee": "Manapool platform fee",
    "credit_card_fee": "Credit card fee",
    "processing_fee": "Processing fee",
    "buyer_shipping_charged": "Buyer shipping charged",
    "stamp_cost": "Stamp cost",
    "toploader_cost": "Toploader cost",
    "envelope_cost": "Envelope cost",
    "team_bag_cost": "Team bag cost",
    "max_direct_bump_pct": "Maximum Direct bump percentage",
    "tracked_shipping_threshold": "Manapool free tracked shipping threshold",
    "tracked_shipping_cost": "Tracked shipping cost",
    "direct_min_listing_price": "Direct minimum listing price",
}


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
    tracked_shipping_threshold: float = 50.00
    tracked_shipping_cost: float = 6.00
    direct_min_listing_price: float = 0.40

    @property
    def shipping_supply_cost(self) -> float:
        return self.stamp_cost + self.toploader_cost + self.envelope_cost + self.team_bag_cost

    def as_display_rows(self) -> list[dict[str, Any]]:
        rows = []
        for key, value in asdict(self).items():
            label = SETTING_LABELS.get(key, key.replace("_", " ").title())
            if key in PERCENT_SETTING_FIELDS:
                display = f"{value:.2%}"
            elif key in CURRENCY_SETTING_FIELDS:
                display = f"${value:.2f}"
            else:
                display = str(value)
            rows.append({"Metric": label, "Value": display})
        rows.append({"Metric": "Actual shipping/supply cost", "Value": f"${self.shipping_supply_cost:.2f}"})
        rows.append(
            {
                "Metric": "TCGPlayer Direct fee model",
                "Value": "< $2.50 = 50% of item value; >= $2.50 = $1.12 + 8.95% + 2.5%",
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
    source_mode: str = "tcgplayer"


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


def normalize_identifier(value: Any) -> str:
    return "".join(char for char in safe_text(value).lower() if char.isalnum())


def safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def try_parse_number(value: Any) -> tuple[float | None, str | None]:
    if value is None:
        return None, None
    if isinstance(value, (int, float)) and not pd.isna(value):
        return float(value), None
    text = safe_text(value)
    if text == "" or text.lower() in {"nan", "none", "null", "n/a", "na", "--"}:
        return None, None
    cleaned = text.replace("$", "").replace(",", "")
    try:
        return float(cleaned), None
    except ValueError:
        return None, "Invalid numeric value"


def parse_csv_bytes(file_bytes: bytes) -> pd.DataFrame:
    encodings = ["utf-8-sig", "utf-8", "cp1252", "latin-1"]
    last_error: Exception | None = None
    for encoding in encodings:
        try:
            df = pd.read_csv(BytesIO(file_bytes), dtype=str, keep_default_na=False, encoding=encoding)
            df.columns = [str(column).strip() for column in df.columns]
            return df
        except Exception as exc:
            last_error = exc
    raise ValueError(f"Unable to read CSV file: {last_error}") from last_error


def map_columns(df: pd.DataFrame, aliases: dict[str, list[str]], required: list[str]) -> tuple[dict[str, str], list[str]]:
    normalized_lookup = {normalize_header(column): column for column in df.columns}
    mapped: dict[str, str] = {}
    missing: list[str] = []
    for canonical, options in aliases.items():
        found = None
        for alias in options:
            if alias in normalized_lookup:
                found = normalized_lookup[alias]
                break
        if found is None:
            if canonical in required:
                missing.append(canonical)
        else:
            mapped[canonical] = found
    return mapped, missing


def normalize_quantity(quantity: float) -> int | float:
    if abs(quantity - round(quantity)) < 1e-9:
        return int(round(quantity))
    return round(quantity, 2)


def normalize_condition(condition_value: Any, foil_value: Any = None) -> str:
    condition_text = safe_text(condition_value).replace("_", " ").strip()
    normalized_condition = normalize_header(condition_text)
    condition_map = {
        "nm": "Near Mint",
        "near mint": "Near Mint",
        "lp": "Lightly Played",
        "lightly played": "Lightly Played",
        "mp": "Moderately Played",
        "moderately played": "Moderately Played",
        "hp": "Heavily Played",
        "heavily played": "Heavily Played",
        "dmg": "Damaged",
        "damaged": "Damaged",
        "unopened": "Unopened",
    }
    condition = condition_map.get(normalized_condition, condition_text.title())
    if condition == "":
        condition = "Near Mint"
    foil_text = safe_text(foil_value).lower()
    is_foil = foil_text in {"foil", "true", "1", "yes", "y"}
    if is_foil and "foil" not in condition.lower():
        return f"{condition} Foil"
    return condition


def normalize_tcg_rarity(rarity_value: Any) -> str:
    rarity_text = safe_text(rarity_value).strip()
    if rarity_text == "":
        return ""

    normalized = normalize_header(rarity_text)
    rarity_map = {
        "common": "C",
        "uncommon": "U",
        "rare": "R",
        "mythic": "M",
        "mythic rare": "M",
        "token": "T",
        "land": "L",
        "basic land": "L",
    }
    if normalized in rarity_map:
        return rarity_map[normalized]

    if len(rarity_text) == 1:
        return rarity_text.upper()

    return rarity_text.upper()


def normalize_tcg_set_name(set_name_value: Any) -> str:
    set_name = safe_text(set_name_value)
    normalized = normalize_header(set_name)
    set_name_map = {
        "secret lair drop": "Secret Lair Drop Series",
        "the list reprints": "The List",
    }
    return set_name_map.get(normalized, set_name)


def normalize_product_line(product_line_value: Any) -> str:
    product_line = safe_text(product_line_value)
    normalized = normalize_header(product_line)
    if normalized == "magic the gathering":
        return "Magic"
    return product_line


def is_manapool_supported_product_line(product_line_value: Any) -> bool:
    return normalize_header(normalize_product_line(product_line_value)) == "magic"


def infer_tcg_rarity_from_scryfall(payload: dict[str, Any]) -> str:
    layout = normalize_header(payload.get("layout"))
    type_line = normalize_header(payload.get("type_line"))
    promo_types = {normalize_header(value) for value in (payload.get("promo_types") or [])}

    if layout == "token" or type_line.startswith("token "):
        return "T"

    # Some Secret Lair helper inserts are represented in Scryfall as "Card"
    # even though TCGPlayer catalogs them under Token.
    if type_line == "card" and "poster" in promo_types:
        return "T"

    return normalize_tcg_rarity(payload.get("rarity", ""))


def infer_tcg_product_name_from_scryfall(payload: dict[str, Any], rarity_code: str) -> str:
    product_name = safe_text(payload.get("name"))
    layout = normalize_header(payload.get("layout"))
    type_line = normalize_header(payload.get("type_line"))

    if rarity_code == "T" and (layout == "token" or type_line.startswith("token ")):
        if not product_name.lower().endswith(" token"):
            return f"{product_name} Token"

    return product_name


def build_row_key(name: Any, set_code: Any, collector_number: Any, condition: Any, language: Any = "") -> str:
    parts = [
        normalize_header(name),
        normalize_identifier(set_code),
        normalize_identifier(collector_number),
        normalize_header(condition),
        normalize_header(language),
    ]
    return "||".join(parts)


def fetch_tcgplayer_ids_from_scryfall(scryfall_ids: list[str]) -> tuple[dict[str, str], list[str]]:
    resolved_ids: dict[str, str] = {}
    unresolved_ids: list[str] = []

    unique_ids = []
    seen_ids: set[str] = set()
    for value in scryfall_ids:
        scryfall_id = safe_text(value)
        if not scryfall_id or scryfall_id in seen_ids:
            continue
        seen_ids.add(scryfall_id)
        unique_ids.append(scryfall_id)

    for scryfall_id in unique_ids:
        request = Request(
            SCRYFALL_CARD_API_TEMPLATE.format(scryfall_id=scryfall_id),
            headers=SCRYFALL_HEADERS,
            method="GET",
        )
        try:
            with urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
            unresolved_ids.append(scryfall_id)
            continue

        tcgplayer_id = payload.get("tcgplayer_id")
        if tcgplayer_id in {None, ""}:
            unresolved_ids.append(scryfall_id)
            continue
        resolved_ids[scryfall_id] = str(tcgplayer_id)

    return resolved_ids, unresolved_ids


def fetch_tcgplayer_metadata_from_scryfall(scryfall_ids: list[str]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    resolved_metadata: dict[str, dict[str, Any]] = {}
    unresolved_ids: list[str] = []

    unique_ids = []
    seen_ids: set[str] = set()
    for value in scryfall_ids:
        scryfall_id = safe_text(value)
        if not scryfall_id or scryfall_id in seen_ids:
            continue
        seen_ids.add(scryfall_id)
        unique_ids.append(scryfall_id)

    for scryfall_id in unique_ids:
        request = Request(
            SCRYFALL_CARD_API_TEMPLATE.format(scryfall_id=scryfall_id),
            headers=SCRYFALL_HEADERS,
            method="GET",
        )
        try:
            with urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
            unresolved_ids.append(scryfall_id)
            continue

        tcgplayer_id = payload.get("tcgplayer_id")
        if tcgplayer_id in {None, ""}:
            unresolved_ids.append(scryfall_id)
            continue

        rarity_code = infer_tcg_rarity_from_scryfall(payload)
        resolved_metadata[scryfall_id] = {
            "TCGplayer Id": str(tcgplayer_id),
            "Set Name": normalize_tcg_set_name(payload.get("set_name", "")),
            "Product Name": infer_tcg_product_name_from_scryfall(payload, rarity_code),
            "Number": safe_text(payload.get("collector_number", "")),
            "Rarity": rarity_code,
        }

    return resolved_metadata, unresolved_ids


def calculate_manapool_net(card_price: float, settings: OptimizerSettings) -> float:
    gross = card_price + settings.buyer_shipping_charged
    fees = gross * (settings.manapool_platform_fee + settings.credit_card_fee) + settings.processing_fee
    net = gross - fees - settings.shipping_supply_cost
    return round(net, 2)


def normalize_direct_listing_price(listing_price: float | None, settings: OptimizerSettings | None = None) -> float | None:
    if listing_price is None:
        return None
    floor = settings.direct_min_listing_price if settings else 0.40
    return round(max(float(listing_price), floor), 2)


def calculate_direct_net(listing_price: float, settings: OptimizerSettings | None = None) -> float:
    normalized_price = normalize_direct_listing_price(listing_price, settings)
    assert normalized_price is not None
    if normalized_price < 2.50:
        return round(normalized_price * 0.50, 2)
    fees = 1.12 + (normalized_price * 0.0895) + (normalized_price * 0.025)
    return round(normalized_price - fees, 2)


def lookup_direct_net(proposed_price: float | None, settings: OptimizerSettings | None = None) -> float | None:
    normalized_price = normalize_direct_listing_price(proposed_price, settings)
    if normalized_price is None:
        return None
    return calculate_direct_net(normalized_price, settings)


def find_required_direct_price(target_net: float, settings: OptimizerSettings | None = None) -> float | None:
    floor = settings.direct_min_listing_price if settings else 0.40
    if target_net <= 0:
        return round(floor, 2)
    rounded_target = round(target_net, 2)
    for cents in range(int(round(floor * 100)), 500001):
        listing_price = cents / 100
        if calculate_direct_net(listing_price, settings) >= rounded_target:
            return round(listing_price, 2)
    return None


def calculate_direct_bump_pct(base_price: float | None, required_price: float | None) -> float | None:
    if base_price is None or required_price is None or base_price <= 0:
        return None
    return (required_price - base_price) / base_price


def build_error_row(payload: dict[str, Any], error_reason: str) -> dict[str, Any]:
    row = {key: safe_text(value) for key, value in payload.items()}
    row["Error reason"] = error_reason
    return row


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
        {"Metric": "Hypothetical net if everything went to Mana Pool", "Value": round(summary["all_manapool_estimated_net"], 2)},
        {"Metric": "Hypothetical net if everything went to TCGPlayer Direct", "Value": round(summary["all_direct_estimated_net"], 2)},
        {"Metric": "Average Direct bump %", "Value": summary["average_direct_bump_pct"]},
        {"Metric": "Number of skipped/error rows", "Value": summary["skipped_error_rows"]},
        {"Metric": "Number of cards with missing price data", "Value": summary["missing_price_data_count"]},
        {"Metric": f"Number of cards forced to Manapool ${settings.manapool_min_price:.2f} minimum", "Value": summary["forced_manapool_min_count"]},
        {"Metric": "Number of cards where Direct bump exceeded max allowed %", "Value": summary["direct_bump_exceeded_count"]},
        {"Metric": "Manapool listings at or above tracked shipping threshold", "Value": summary["tracked_shipping_review_count"]},
        {"Metric": "", "Value": ""},
        {"Metric": "Current settings used for the run", "Value": ""},
    ]
    rows.extend(settings.as_display_rows())
    return pd.DataFrame(rows)


def build_standard_export_row(
    *,
    tcgplayer_id: Any,
    product_line: Any,
    set_name: Any,
    product_name: Any,
    title: Any,
    number: Any,
    rarity: Any,
    condition: Any,
    tcg_market_price: float | None,
    tcg_direct_low: float | None,
    tcg_low_price_with_shipping: float | None,
    tcg_low_price: float | None,
    quantity: float,
    listing_price: float,
    photo_url: Any,
) -> dict[str, Any]:
    quantity_text = str(normalize_quantity(quantity))
    return {
        "TCGplayer Id": safe_text(tcgplayer_id),
        "Product Line": safe_text(product_line),
        "Set Name": safe_text(set_name),
        "Product Name": safe_text(product_name),
        "Title": safe_text(title),
        "Number": safe_text(number),
        "Rarity": safe_text(rarity),
        "Condition": safe_text(condition),
        "TCG Market Price": f"{tcg_market_price:.2f}" if tcg_market_price is not None else "",
        "TCG Direct Low": f"{tcg_direct_low:.2f}" if tcg_direct_low is not None else "",
        "TCG Low Price With Shipping": f"{tcg_low_price_with_shipping:.4f}" if tcg_low_price_with_shipping is not None else "",
        "TCG Low Price": f"{tcg_low_price:.2f}" if tcg_low_price is not None else "",
        "Total Quantity": quantity_text,
        "Add to Quantity": quantity_text,
        "TCG Marketplace Price": f"{listing_price:.2f}",
        "Photo URL": safe_text(photo_url),
    }


def build_tcg_upload_row(row: pd.Series, column_map: dict[str, str], quantity: float, listing_price: float) -> dict[str, Any]:
    market_price, _ = try_parse_number(row.get(column_map.get("TCG Market Price", ""), ""))
    direct_low, _ = try_parse_number(row.get(column_map.get("TCG Direct Low", ""), ""))
    low_price_with_shipping, _ = try_parse_number(row.get(column_map.get("TCG Low Price With Shipping", ""), ""))
    low_price, _ = try_parse_number(row.get(column_map.get("TCG Low Price", ""), ""))
    effective_market_price = market_price
    if effective_market_price is None:
        effective_market_price = direct_low if direct_low is not None else low_price
    return build_standard_export_row(
        tcgplayer_id=row.get(column_map.get("TCGplayer Id", ""), ""),
        product_line=row.get(column_map.get("Product Line", ""), ""),
        set_name=row.get(column_map.get("Set Name", ""), ""),
        product_name=row.get(column_map.get("Product Name", ""), ""),
        title=row.get(column_map.get("Title", ""), ""),
        number=row.get(column_map.get("Number", ""), ""),
        rarity=row.get(column_map.get("Rarity", ""), ""),
        condition=row.get(column_map.get("Condition", ""), ""),
        tcg_market_price=effective_market_price,
        tcg_direct_low=direct_low,
        tcg_low_price_with_shipping=low_price_with_shipping,
        tcg_low_price=low_price,
        quantity=quantity,
        listing_price=listing_price,
        photo_url=row.get(column_map.get("Photo URL", ""), ""),
    )


def build_manabox_export_row(row: dict[str, Any], listing_price: float) -> dict[str, Any]:
    return build_standard_export_row(
        tcgplayer_id=row.get("TCGplayer Id", ""),
        product_line=row.get("Product Line", "Magic"),
        set_name=row.get("Set Name", ""),
        product_name=row.get("Product Name", ""),
        title=row.get("Title", ""),
        number=row.get("Number", ""),
        rarity=row.get("Rarity", ""),
        condition=row.get("Condition", ""),
        tcg_market_price=row.get("TCG Market Price"),
        tcg_direct_low=row.get("TCG Direct Low"),
        tcg_low_price_with_shipping=row.get("TCG Low Price With Shipping"),
        tcg_low_price=row.get("Manapool Base Price"),
        quantity=float(row["Quantity"]),
        listing_price=listing_price,
        photo_url=row.get("Photo URL", ""),
    )


def _prepare_tcg_rows(tcgplayer_bytes: bytes) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    df = parse_csv_bytes(tcgplayer_bytes)
    source_columns = list(df.columns)
    column_map, missing_columns = map_columns(df, TCG_COLUMN_ALIASES, TCG_REQUIRED_COLUMNS)
    if missing_columns:
        error = build_error_row({"Source": "TCGPlayer CSV"}, f"Required CSV column missing: {', '.join(missing_columns)}")
        return [], [error], missing_columns

    standard_rows: list[dict[str, Any]] = []
    error_rows: list[dict[str, Any]] = []

    for _, row in df.iterrows():
        parsed_values: dict[str, float | None] = {}
        row_errors: list[str] = []
        for key, canonical in {
            "market_price": "TCG Market Price",
            "direct_low": "TCG Direct Low",
            "low_price": "TCG Low Price",
            "total_quantity": "Total Quantity",
            "add_quantity": "Add to Quantity",
        }.items():
            actual_column = column_map.get(canonical)
            if not actual_column:
                parsed_values[key] = None
                continue
            parsed_value, parse_error = try_parse_number(row.get(actual_column, ""))
            parsed_values[key] = parsed_value
            if parse_error:
                row_errors.append(f"Invalid numeric value in {canonical}")

        quantity = parsed_values.get("add_quantity") if parsed_values.get("add_quantity") and parsed_values["add_quantity"] > 0 else parsed_values.get("total_quantity")
        if quantity is None or quantity <= 0:
            row_errors.append("Missing quantity")

        market_price = parsed_values.get("market_price")
        direct_low = parsed_values.get("direct_low")
        low_price = parsed_values.get("low_price")

        effective_market_price = market_price
        if effective_market_price is None:
            effective_market_price = direct_low if direct_low is not None else low_price

        if effective_market_price is None:
            row_errors.append("Missing TCG Market Price, TCG Direct Low, and TCG Low Price")

        if row_errors:
            error_rows.append(build_error_row({column: row.get(column, "") for column in source_columns}, "; ".join(dict.fromkeys(row_errors))))
            continue

        standard_rows.append(
            {
                "TCGplayer Id": safe_text(row.get(column_map.get("TCGplayer Id", ""), "")),
                "Product Line": safe_text(row.get(column_map["Product Line"], "")),
                "Set Name": safe_text(row.get(column_map["Set Name"], "")),
                "Product Name": safe_text(row.get(column_map["Product Name"], "")),
                "Number": safe_text(row.get(column_map.get("Number", ""), "")),
                "Rarity": safe_text(row.get(column_map.get("Rarity", ""), "")),
                "Condition": safe_text(row.get(column_map.get("Condition", ""), "")),
                "Quantity": float(quantity),
                "TCG Market Price": effective_market_price,
                "TCG Direct Low": direct_low,
                "Manapool Base Price": low_price if low_price is not None else effective_market_price,
                "source_payload": {
                    "row": row.copy(),
                    "column_map": column_map,
                },
            }
        )

    return standard_rows, error_rows, []


def _prepare_scan_export_rows(scan_bytes: bytes) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    df = parse_csv_bytes(scan_bytes)
    column_map, missing_columns = map_columns(df, SCAN_EXPORT_COLUMN_ALIASES, SCAN_EXPORT_REQUIRED_COLUMNS)
    if missing_columns:
        error = build_error_row({"Source": "Scan export CSV"}, f"Required CSV column missing: {', '.join(missing_columns)}")
        return [], [error], missing_columns

    prepared_rows: list[dict[str, Any]] = []
    error_rows: list[dict[str, Any]] = []

    for _, row in df.iterrows():
        market_price, market_error = try_parse_number(row.get(column_map.get("market_price", ""), ""))
        manapool_price, manapool_error = try_parse_number(row.get(column_map.get("manapool_price", ""), ""))
        if market_error:
            error_rows.append(build_error_row(dict(row), "Invalid numeric value in market_price"))
            continue
        if manapool_error:
            error_rows.append(build_error_row(dict(row), "Invalid numeric value in manapool_price"))
            continue
        if market_price is None and manapool_price is None:
            error_rows.append(build_error_row(dict(row), "Missing both market_price and manapool_price"))
            continue

        prepared_rows.append(
            {
                "Product Line": normalize_product_line(row.get(column_map["game"], "")),
                "Set Name": safe_text(row.get(column_map["set"], "")),
                "Product Name": safe_text(row.get(column_map["card_name"], "")),
                "Number": safe_text(row.get(column_map["card_number"], "")),
                "Rarity": "",
                "Condition": normalize_condition(row.get(column_map["condition"], ""), row.get(column_map["variant"], "")),
                "Language": safe_text(row.get(column_map["language"], "")),
                "TCGplayer Id": safe_text(row.get(column_map["tcgplayer_id"], "")),
                "Manapool Id": safe_text(row.get(column_map.get("manapool_id", ""), "")),
                "Quantity": 1.0,
                "TCG Market Price": market_price,
                "TCG Direct Low": None,
                "Manapool Base Price": manapool_price,
                "variant": safe_text(row.get(column_map["variant"], "")),
                "source_payload": dict(row),
            }
        )

    if not prepared_rows:
        return [], error_rows, []

    prepared_df = pd.DataFrame(prepared_rows)
    aggregated_rows: list[dict[str, Any]] = []
    group_columns = ["Product Line", "Set Name", "Product Name", "Number", "Condition", "Language", "TCGplayer Id", "Manapool Id"]
    for _, group in prepared_df.groupby(group_columns, dropna=False, sort=False):
        first = group.iloc[0]
        market_series = pd.to_numeric(group["TCG Market Price"], errors="coerce")
        mana_series = pd.to_numeric(group["Manapool Base Price"], errors="coerce")
        aggregated_rows.append(
            {
                "Product Line": first["Product Line"],
                "Set Name": first["Set Name"],
                "Product Name": first["Product Name"],
                "Number": first["Number"],
                "Rarity": first["Rarity"],
                "Condition": first["Condition"],
                "Language": first["Language"],
                "TCGplayer Id": first["TCGplayer Id"],
                "Manapool Id": first["Manapool Id"],
                "Quantity": float(group["Quantity"].sum()),
                "TCG Market Price": float(market_series.dropna().iloc[0]) if not market_series.dropna().empty else None,
                "TCG Direct Low": None,
                "Manapool Base Price": float(mana_series.dropna().iloc[0]) if not mana_series.dropna().empty else None,
                "source_payload": first["source_payload"],
            }
        )

    return aggregated_rows, error_rows, []


def _prepare_manabox_price_rows(file_bytes: bytes, price_label: str) -> tuple[pd.DataFrame, list[dict[str, Any]], list[str]]:
    df = parse_csv_bytes(file_bytes)
    column_map, missing_columns = map_columns(df, MANABOX_COLUMN_ALIASES, MANABOX_REQUIRED_COLUMNS)
    if missing_columns:
        error = build_error_row({"Source": price_label}, f"Required CSV column missing: {', '.join(missing_columns)}")
        return pd.DataFrame(), [error], missing_columns

    prepared_rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        quantity, quantity_error = try_parse_number(row.get(column_map["Quantity"], ""))
        purchase_price, price_error = try_parse_number(row.get(column_map["Purchase price"], ""))
        if quantity_error or quantity is None or quantity <= 0:
            errors.append(build_error_row({"Source": price_label, "Name": row.get(column_map["Name"], "")}, "Missing quantity"))
            continue
        if price_error or purchase_price is None:
            errors.append(build_error_row({"Source": price_label, "Name": row.get(column_map["Name"], "")}, "Missing or invalid purchase price"))
            continue

        condition = normalize_condition(row.get(column_map["Condition"], ""), row.get(column_map["Foil"], ""))
        prepared_rows.append(
            {
                "row_key": build_row_key(
                    row.get(column_map["Name"], ""),
                    row.get(column_map["Set code"], ""),
                    row.get(column_map["Collector number"], ""),
                    condition,
                    row.get(column_map.get("Language", ""), ""),
                ),
                "Product Name": safe_text(row.get(column_map["Name"], "")),
                "Set Code": safe_text(row.get(column_map["Set code"], "")),
                "Set Name": normalize_tcg_set_name(row.get(column_map["Set name"], "")),
                "Number": safe_text(row.get(column_map["Collector number"], "")),
                "Rarity": normalize_tcg_rarity(row.get(column_map["Rarity"], "")),
                "Condition": condition,
                "Language": safe_text(row.get(column_map.get("Language", ""), "")),
                "Scryfall ID": safe_text(row.get(column_map.get("Scryfall ID", ""), "")),
                "Quantity": float(quantity),
                "Price": purchase_price,
            }
        )

    if not prepared_rows:
        return pd.DataFrame(), errors, []

    prepared_df = pd.DataFrame(prepared_rows)
    aggregated_rows: list[dict[str, Any]] = []
    for _, group in prepared_df.groupby("row_key", dropna=False):
        aggregated_rows.append(
            {
                "row_key": group.iloc[0]["row_key"],
                "Product Name": group.iloc[0]["Product Name"],
                "Set Code": group.iloc[0]["Set Code"],
                "Set Name": group.iloc[0]["Set Name"],
                "Number": group.iloc[0]["Number"],
                "Rarity": group.iloc[0]["Rarity"],
                "Condition": group.iloc[0]["Condition"],
                "Language": group.iloc[0]["Language"],
                "Scryfall ID": group.iloc[0]["Scryfall ID"],
                "Quantity": float(group["Quantity"].sum()),
                "Price": float(group.iloc[0]["Price"]),
            }
        )

    return pd.DataFrame(aggregated_rows), errors, []


def _prepare_dual_manabox_rows(
    tcg_market_bytes: bytes,
    manapool_market_bytes: bytes,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], str | None]:
    tcg_df, tcg_errors, tcg_missing = _prepare_manabox_price_rows(tcg_market_bytes, "ManaBox TCG pricing CSV")
    mana_df, mana_errors, mana_missing = _prepare_manabox_price_rows(manapool_market_bytes, "ManaBox Manapool pricing CSV")
    if tcg_missing or mana_missing:
        return [], tcg_errors + mana_errors, sorted(set(tcg_missing + mana_missing)), None

    scryfall_metadata_lookup, unresolved_scryfall_ids = fetch_tcgplayer_metadata_from_scryfall(
        tcg_df["Scryfall ID"].tolist() if not tcg_df.empty else []
    )
    enrichment_warning = None
    if unresolved_scryfall_ids:
        enrichment_warning = (
            f"Scryfall could not resolve {len(unresolved_scryfall_ids)} TCGplayer ID(s) in Dual ManaBox mode. "
            "Those export rows were left blank in TCGplayer Id."
        )

    merged = tcg_df.merge(
        mana_df,
        on="row_key",
        how="outer",
        suffixes=("_tcg", "_manapool"),
        indicator=True,
    )

    standard_rows: list[dict[str, Any]] = []
    error_rows = tcg_errors + mana_errors

    for _, row in merged.iterrows():
        if row["_merge"] != "both":
            missing_side = "TCG pricing CSV" if row["_merge"] == "right_only" else "Manapool pricing CSV"
            payload = {
                "Product Name": row.get("Product Name_tcg") or row.get("Product Name_manapool"),
                "Set Name": row.get("Set Name_tcg") or row.get("Set Name_manapool"),
                "Number": row.get("Number_tcg") or row.get("Number_manapool"),
                "Condition": row.get("Condition_tcg") or row.get("Condition_manapool"),
            }
            error_rows.append(build_error_row(payload, f"Card missing from {missing_side}"))
            continue

        quantity_tcg = float(row["Quantity_tcg"])
        quantity_manapool = float(row["Quantity_manapool"])
        if abs(quantity_tcg - quantity_manapool) > 1e-9:
            payload = {
                "Product Name": row["Product Name_tcg"],
                "Set Name": row["Set Name_tcg"],
                "Number": row["Number_tcg"],
                "Condition": row["Condition_tcg"],
            }
            error_rows.append(build_error_row(payload, "Quantity mismatch between ManaBox pricing files"))
            continue

        scryfall_metadata = scryfall_metadata_lookup.get(safe_text(row["Scryfall ID_tcg"]), {})

        standard_rows.append(
            {
                "TCGplayer Id": scryfall_metadata.get("TCGplayer Id", ""),
                "Product Line": "Magic",
                "Set Name": scryfall_metadata.get("Set Name", row["Set Name_tcg"]),
                "Product Name": scryfall_metadata.get("Product Name", row["Product Name_tcg"]),
                "Number": scryfall_metadata.get("Number", row["Number_tcg"]),
                "Rarity": scryfall_metadata.get("Rarity", row["Rarity_tcg"]),
                "Condition": row["Condition_tcg"],
                "Quantity": quantity_tcg,
                "TCG Market Price": float(row["Price_tcg"]),
                "TCG Direct Low": None,
                "Manapool Base Price": float(row["Price_manapool"]),
                "Set Code": row["Set Code_tcg"],
                "Scryfall ID": row["Scryfall ID_tcg"],
                "Language": row["Language_tcg"],
                "source_payload": None,
            }
        )

    return standard_rows, error_rows, [], enrichment_warning


def _build_output_rows(
    standard_rows: list[dict[str, Any]],
    settings: OptimizerSettings,
    source_mode: str,
    warning_message: str | None = None,
) -> ProcessResult:
    manapool_rows: list[dict[str, Any]] = []
    direct_rows: list[dict[str, Any]] = []
    manapool_csv_rows: list[dict[str, Any]] = []
    direct_csv_rows: list[dict[str, Any]] = []
    error_rows: list[dict[str, Any]] = []

    total_quantity_imported = 0.0
    missing_price_data_count = 0
    forced_manapool_min_count = 0
    direct_bump_exceeded_count = 0
    all_manapool_estimated_net = 0.0
    all_direct_estimated_net = 0.0

    for standard_row in standard_rows:
        quantity = float(standard_row["Quantity"])
        total_quantity_imported += quantity

        manapool_base_price = standard_row.get("Manapool Base Price")
        market_price = standard_row.get("TCG Market Price")
        direct_low = standard_row.get("TCG Direct Low")

        if source_mode == "scan_export" and manapool_base_price is None and market_price is None and direct_low is None:
            missing_price_data_count += 1
            error_rows.append(build_error_row(standard_row, "Missing Manapool price and TCG price"))
            continue
        if source_mode != "scan_export" and manapool_base_price is None:
            missing_price_data_count += 1
            error_rows.append(build_error_row(standard_row, "Missing Manapool price"))
            continue
        if source_mode != "scan_export" and market_price is None and direct_low is None:
            missing_price_data_count += 1
            error_rows.append(build_error_row(standard_row, "Missing both TCG Market Price and TCG Direct Low"))
            continue

        forced_min = manapool_base_price is not None and manapool_base_price < settings.manapool_min_price
        manapool_price = max(float(manapool_base_price), settings.manapool_min_price) if manapool_base_price is not None else None
        if forced_min:
            forced_manapool_min_count += 1

        manapool_net = calculate_manapool_net(manapool_price, settings) if manapool_price is not None else None
        if manapool_net is not None:
            all_manapool_estimated_net += manapool_net * quantity
        manapool_supported = is_manapool_supported_product_line(standard_row.get("Product Line", ""))

        if direct_low is None:
            raw_base_direct_price = market_price
        elif market_price is None:
            raw_base_direct_price = direct_low
        else:
            raw_base_direct_price = max(float(market_price), float(direct_low))

        base_direct_price = normalize_direct_listing_price(raw_base_direct_price, settings)
        base_direct_net = lookup_direct_net(base_direct_price, settings)
        if base_direct_net is not None:
            all_direct_estimated_net += base_direct_net * quantity

        if raw_base_direct_price is not None and raw_base_direct_price < settings.direct_min_listing_price:
            required_direct_price = settings.direct_min_listing_price
        elif base_direct_net is not None and base_direct_net >= manapool_net:
            required_direct_price = base_direct_price
        else:
            required_direct_price = find_required_direct_price(manapool_net, settings)

        direct_listing_price = normalize_direct_listing_price(required_direct_price, settings)
        direct_net = lookup_direct_net(direct_listing_price, settings) if direct_listing_price is not None else None
        direct_bump_pct = calculate_direct_bump_pct(raw_base_direct_price, direct_listing_price)

        reason_parts = []
        if source_mode == "dual_manabox":
            reason_parts.append("Dual ManaBox pricing comparison")
        elif source_mode == "scan_export":
            reason_parts.append("Scan export pricing comparison")
        if forced_min:
            reason_parts.append("Forced to Manapool minimum")

        if source_mode == "scan_export" and raw_base_direct_price is None and manapool_net is not None:
            destination = "manapool"
            reason_parts.append("No TCG price was available, so the card defaulted to Manapool")
            bump_exceeded = False
        elif source_mode == "scan_export" and manapool_net is None and direct_listing_price is not None and direct_net is not None:
            destination = "direct"
            reason_parts.append("No Manapool price was available, so the card defaulted to TCGPlayer")
            if raw_base_direct_price is not None and raw_base_direct_price < settings.direct_min_listing_price:
                reason_parts.append("Direct floor enforced at minimum price")
            bump_exceeded = False
        elif not manapool_supported:
            destination = "direct"
            reason_parts.append("Non-MTG product line routed to TCGPlayer because Manapool only supports Magic")
            if raw_base_direct_price is not None and raw_base_direct_price < settings.direct_min_listing_price:
                reason_parts.append("Direct floor enforced at minimum price")
            bump_exceeded = False
        elif direct_listing_price is None or direct_net is None or direct_bump_pct is None:
            destination = "manapool"
            direct_bump_exceeded_count += 1
            reason_parts.append("Unable to price Direct listing")
            bump_exceeded = True
        elif direct_bump_pct > settings.max_direct_bump_pct:
            destination = "manapool"
            direct_bump_exceeded_count += 1
            reason_parts.append("Required Direct bump exceeded max allowed %")
            bump_exceeded = True
        else:
            destination = "direct"
            reason_parts.append("Direct net meets or beats Manapool within bump limit")
            if raw_base_direct_price is not None and raw_base_direct_price < settings.direct_min_listing_price:
                reason_parts.append("Direct floor enforced at minimum price")
            bump_exceeded = False

        row_base = {
            "TCGplayer Id": safe_text(standard_row.get("TCGplayer Id", "")),
            "Product Line": safe_text(standard_row.get("Product Line", "Magic")),
            "Set Name": safe_text(standard_row.get("Set Name", "")),
            "Product Name": safe_text(standard_row.get("Product Name", "")),
            "Number": safe_text(standard_row.get("Number", "")),
            "Rarity": safe_text(standard_row.get("Rarity", "")),
            "Condition": safe_text(standard_row.get("Condition", "")),
            "Quantity": normalize_quantity(quantity),
        }

        if destination == "direct":
            direct_rows.append(
                {
                    **row_base,
                    "Direct Listing Price": round(direct_listing_price, 2),
                    "Direct Net": round(direct_net, 2),
                    "Manapool Price": round(manapool_price, 2) if manapool_price is not None else None,
                    "Manapool Net": round(manapool_net, 2) if manapool_net is not None else None,
                    "Direct Bump %": direct_bump_pct,
                    "Reason": "; ".join(reason_parts),
                    "_bump_exceeded": bump_exceeded,
                }
            )
            if source_mode == "tcgplayer":
                payload = standard_row["source_payload"]
                direct_csv_rows.append(
                    build_tcg_upload_row(
                        payload["row"],
                        payload["column_map"],
                        quantity,
                        direct_listing_price,
                    )
                )
            else:
                direct_csv_rows.append(build_manabox_export_row(standard_row, direct_listing_price))
        else:
            if manapool_price is not None and manapool_price >= settings.tracked_shipping_threshold:
                reason_parts.append("Review for tracked shipping threshold")
            manapool_rows.append(
                {
                    **row_base,
                    "Manapool Price": round(manapool_price, 2) if manapool_price is not None else None,
                    "Manapool Net": round(manapool_net, 2) if manapool_net is not None else None,
                    "Base Direct Price": round(base_direct_price, 2) if base_direct_price is not None else None,
                    "Base Direct Net": round(base_direct_net, 2) if base_direct_net is not None else None,
                    "Required Direct Price": round(direct_listing_price, 2) if direct_listing_price is not None else None,
                    "Direct Bump %": direct_bump_pct,
                    "Reason": "; ".join(reason_parts),
                    "_forced_min": forced_min,
                    "_bump_exceeded": bump_exceeded,
                }
            )
            if source_mode == "tcgplayer":
                payload = standard_row["source_payload"]
                manapool_csv_rows.append(
                    build_tcg_upload_row(
                        payload["row"],
                        payload["column_map"],
                        quantity,
                        manapool_price,
                    )
                )
            else:
                manapool_csv_rows.append(build_manabox_export_row(standard_row, manapool_price))

    manapool_csv_df = pd.DataFrame(manapool_csv_rows, columns=EXPORT_COLUMNS)
    direct_csv_df = pd.DataFrame(direct_csv_rows, columns=EXPORT_COLUMNS)

    manapool_full_df = pd.DataFrame(manapool_rows, columns=DISPLAY_COLUMNS_MANAPOOL + ["_forced_min", "_bump_exceeded"])
    direct_full_df = pd.DataFrame(direct_rows, columns=DISPLAY_COLUMNS_DIRECT + ["_bump_exceeded"])
    errors_df = pd.DataFrame(error_rows)

    manapool_total_net = 0.0
    direct_total_net = 0.0
    if not manapool_full_df.empty:
        manapool_total_net = float((pd.to_numeric(manapool_full_df["Manapool Net"], errors="coerce").fillna(0) * pd.to_numeric(manapool_full_df["Quantity"], errors="coerce").fillna(0)).sum())
    if not direct_full_df.empty:
        direct_total_net = float((pd.to_numeric(direct_full_df["Direct Net"], errors="coerce").fillna(0) * pd.to_numeric(direct_full_df["Quantity"], errors="coerce").fillna(0)).sum())

    direct_bump_average = 0.0
    if not direct_full_df.empty:
        bump_series = pd.to_numeric(direct_full_df["Direct Bump %"], errors="coerce").dropna()
        if not bump_series.empty:
            direct_bump_average = float(bump_series.mean())

    tracked_shipping_review_count = 0
    if not manapool_full_df.empty:
        tracked_shipping_review_count = int((pd.to_numeric(manapool_full_df["Manapool Price"], errors="coerce").fillna(0) >= settings.tracked_shipping_threshold).sum())

    summary = {
        "total_rows_imported": len(standard_rows),
        "total_quantity_imported": normalize_quantity(total_quantity_imported) if total_quantity_imported else 0,
        "total_cards_assigned_manapool": int(pd.to_numeric(manapool_full_df["Quantity"], errors="coerce").fillna(0).sum()) if not manapool_full_df.empty else 0,
        "total_cards_assigned_direct": int(pd.to_numeric(direct_full_df["Quantity"], errors="coerce").fillna(0).sum()) if not direct_full_df.empty else 0,
        "total_estimated_manapool_net": round(manapool_total_net, 2),
        "total_estimated_direct_net": round(direct_total_net, 2),
        "combined_estimated_net": round(manapool_total_net + direct_total_net, 2),
        "all_manapool_estimated_net": round(all_manapool_estimated_net, 2),
        "all_direct_estimated_net": round(all_direct_estimated_net, 2),
        "average_direct_bump_pct": direct_bump_average,
        "skipped_error_rows": int(len(errors_df)),
        "missing_price_data_count": missing_price_data_count,
        "forced_manapool_min_count": forced_manapool_min_count,
        "direct_bump_exceeded_count": direct_bump_exceeded_count,
        "tracked_shipping_review_count": tracked_shipping_review_count,
    }

    combined_warning_message = warning_message
    if source_mode == "dual_manabox":
        dual_mode_message = (
            "Dual ManaBox mode compares Purchase price from your TCG-priced export against "
            "Purchase price from your Manapool-priced export."
        )
        combined_warning_message = dual_mode_message if combined_warning_message is None else f"{combined_warning_message}\n\n{dual_mode_message}"
    if tracked_shipping_review_count:
        tracked_warning = f"{tracked_shipping_review_count} Manapool listing(s) are at or above ${settings.tracked_shipping_threshold:.2f} and may need manual tracked-shipping review."
        combined_warning_message = tracked_warning if combined_warning_message is None else f"{combined_warning_message}\n\n{tracked_warning}"

    analysis_df = build_analysis_dataframe(summary, settings)

    return ProcessResult(
        manapool_full_df=manapool_full_df.sort_values("Product Name", key=lambda series: series.astype(str).str.lower()).reset_index(drop=True),
        direct_full_df=direct_full_df.sort_values("Product Name", key=lambda series: series.astype(str).str.lower()).reset_index(drop=True),
        manapool_preview_df=sort_preview(manapool_full_df, DISPLAY_COLUMNS_MANAPOOL),
        direct_preview_df=sort_preview(direct_full_df, DISPLAY_COLUMNS_DIRECT),
        manapool_csv_df=manapool_csv_df.reset_index(drop=True),
        direct_csv_df=direct_csv_df.reset_index(drop=True),
        errors_df=errors_df.reset_index(drop=True),
        analysis_df=analysis_df,
        summary=summary,
        settings=settings,
        missing_columns=[],
        warning_message=combined_warning_message,
        source_mode=source_mode,
    )


def process_files(
    *,
    settings: OptimizerSettings,
    tcgplayer_bytes: bytes | None = None,
    manabox_tcg_bytes: bytes | None = None,
    manabox_manapool_bytes: bytes | None = None,
) -> ProcessResult:
    if tcgplayer_bytes:
        standard_rows, error_rows, missing_columns = _prepare_tcg_rows(tcgplayer_bytes)
        source_mode = "tcgplayer"
        warning_message = None
        if missing_columns:
            standard_rows, error_rows, scan_missing_columns = _prepare_scan_export_rows(tcgplayer_bytes)
            if not scan_missing_columns:
                missing_columns = []
                source_mode = "scan_export"
                warning_message = "Scan export mode detected. Quantity is derived from duplicate scanned rows."
        if missing_columns:
            empty_summary = {
                "total_rows_imported": 0,
                "total_quantity_imported": 0,
                "total_cards_assigned_manapool": 0,
                "total_cards_assigned_direct": 0,
                "total_estimated_manapool_net": 0.0,
                "total_estimated_direct_net": 0.0,
                "combined_estimated_net": 0.0,
                "all_manapool_estimated_net": 0.0,
                "all_direct_estimated_net": 0.0,
                "average_direct_bump_pct": 0.0,
                "skipped_error_rows": len(error_rows),
                "missing_price_data_count": 0,
                "forced_manapool_min_count": 0,
                "direct_bump_exceeded_count": 0,
                "tracked_shipping_review_count": 0,
            }
            return ProcessResult(
                manapool_full_df=pd.DataFrame(columns=DISPLAY_COLUMNS_MANAPOOL + ["_forced_min", "_bump_exceeded"]),
                direct_full_df=pd.DataFrame(columns=DISPLAY_COLUMNS_DIRECT + ["_bump_exceeded"]),
                manapool_preview_df=pd.DataFrame(columns=DISPLAY_COLUMNS_MANAPOOL),
                direct_preview_df=pd.DataFrame(columns=DISPLAY_COLUMNS_DIRECT),
                manapool_csv_df=pd.DataFrame(),
                direct_csv_df=pd.DataFrame(),
                errors_df=pd.DataFrame(error_rows),
                analysis_df=build_analysis_dataframe(empty_summary, settings),
                summary=empty_summary,
                settings=settings,
                missing_columns=missing_columns,
                warning_message="Required columns are missing from the TCGPlayer CSV.",
                source_mode="tcgplayer",
            )
        result = _build_output_rows(standard_rows, settings, source_mode, warning_message)
        if error_rows:
            result.errors_df = pd.concat([result.errors_df, pd.DataFrame(error_rows)], ignore_index=True)
            result.summary["skipped_error_rows"] = len(result.errors_df)
            result.analysis_df = build_analysis_dataframe(result.summary, settings)
        return result

    if manabox_tcg_bytes and manabox_manapool_bytes:
        standard_rows, error_rows, missing_columns, enrichment_warning = _prepare_dual_manabox_rows(manabox_tcg_bytes, manabox_manapool_bytes)
        if missing_columns:
            empty_summary = {
                "total_rows_imported": 0,
                "total_quantity_imported": 0,
                "total_cards_assigned_manapool": 0,
                "total_cards_assigned_direct": 0,
                "total_estimated_manapool_net": 0.0,
                "total_estimated_direct_net": 0.0,
                "combined_estimated_net": 0.0,
                "all_manapool_estimated_net": 0.0,
                "all_direct_estimated_net": 0.0,
                "average_direct_bump_pct": 0.0,
                "skipped_error_rows": len(error_rows),
                "missing_price_data_count": 0,
                "forced_manapool_min_count": 0,
                "direct_bump_exceeded_count": 0,
                "tracked_shipping_review_count": 0,
            }
            return ProcessResult(
                manapool_full_df=pd.DataFrame(columns=DISPLAY_COLUMNS_MANAPOOL + ["_forced_min", "_bump_exceeded"]),
                direct_full_df=pd.DataFrame(columns=DISPLAY_COLUMNS_DIRECT + ["_bump_exceeded"]),
                manapool_preview_df=pd.DataFrame(columns=DISPLAY_COLUMNS_MANAPOOL),
                direct_preview_df=pd.DataFrame(columns=DISPLAY_COLUMNS_DIRECT),
                manapool_csv_df=pd.DataFrame(),
                direct_csv_df=pd.DataFrame(),
                errors_df=pd.DataFrame(error_rows),
                analysis_df=build_analysis_dataframe(empty_summary, settings),
                summary=empty_summary,
                settings=settings,
                missing_columns=missing_columns,
                warning_message="Required columns are missing from one or both ManaBox CSV files.",
                source_mode="dual_manabox",
            )
        result = _build_output_rows(standard_rows, settings, "dual_manabox", enrichment_warning)
        if error_rows:
            result.errors_df = pd.concat([result.errors_df, pd.DataFrame(error_rows)], ignore_index=True)
            result.summary["skipped_error_rows"] = len(result.errors_df)
            result.analysis_df = build_analysis_dataframe(result.summary, settings)
        return result

    raise ValueError("Please provide either one TCGPlayer CSV or both ManaBox pricing CSVs.")
