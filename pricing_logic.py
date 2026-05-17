from __future__ import annotations

from dataclasses import asdict, dataclass
from io import BytesIO
import base64
import json
import re
from typing import Any
from urllib import error, parse, request

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
}

USER_AGENT = "CardMarketplaceListingOptimizer/0.5 (+https://github.com/lotustemplar/card-marketplace-listing-optimizer)"
MANAPOOL_BASE_URL = "https://manapool.com"
MANAPOOL_OPENAPI_URL = "https://manapool.com/api/docs/v1/openapi.json"
MANAPOOL_TIMEOUT_SECONDS = 20
MANAPOOL_BATCH_SIZE = 40


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
        rows.append(
            {
                "Metric": "Mana Pool price source",
                "Value": "Mana Pool API only, using API returned floor pricing when a match is found, otherwise TCG fallback pricing",
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


def normalize_identifier(value: Any) -> str:
    text = "" if value is None else str(value).strip().lower()
    return "".join(char for char in text if char.isalnum())


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
    rounded_target = round(target_net, 2)
    for cents in range(1, 500001):
        listing_price = cents / 100
        if calculate_direct_net(listing_price) >= rounded_target:
            return round(listing_price, 2)
    return None


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


def request_json(url: str, *, method: str = "GET", headers: dict[str, str] | None = None, payload: Any | None = None) -> Any:
    final_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        final_headers.update(headers)
    data = None
    if payload is not None:
        final_headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, headers=final_headers, method=method, data=data)
    try:
        with request.urlopen(req, timeout=MANAPOOL_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"Request failed ({exc.code}): {body[:400]}") from exc
    except error.URLError as exc:
        raise ValueError(f"Request failed: {exc.reason}") from exc


def get_auth_header_variants(manapool_api_key: str | None, manapool_email: str | None) -> list[dict[str, str]]:
    variants: list[dict[str, str]] = [{}]
    token = safe_text(manapool_api_key)
    email = safe_text(manapool_email)
    if token:
        variants.append({"Authorization": f"Bearer {token}"})
        variants.append({"X-API-Key": token})
        variants.append({"api-key": token})
        variants.append({"x-api-token": token})
    if token and email:
        basic = base64.b64encode(f"{email}:{token}".encode("utf-8")).decode("ascii")
        variants.append({"Authorization": f"Basic {basic}"})
        variants.append({"X-User-Email": email, "X-API-Key": token})
        variants.append({"x-user-email": email, "x-api-token": token})
    unique: list[dict[str, str]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for variant in variants:
        key = tuple(sorted(variant.items()))
        if key not in seen:
            seen.add(key)
            unique.append(variant)
    return unique


def schema_mentions_card_names(schema: Any) -> bool:
    if isinstance(schema, dict):
        if "card_names" in schema.get("properties", {}):
            return True
        return any(schema_mentions_card_names(value) for value in schema.values())
    if isinstance(schema, list):
        return any(schema_mentions_card_names(value) for value in schema)
    return False


def schema_mentions_from_price(schema: Any) -> bool:
    if isinstance(schema, dict):
        if "from_price_cents" in schema.get("properties", {}):
            return True
        return any(schema_mentions_from_price(value) for value in schema.values())
    if isinstance(schema, list):
        return any(schema_mentions_from_price(value) for value in schema)
    return False


def discover_manapool_cards_endpoint() -> tuple[str, str]:
    spec = request_json(MANAPOOL_OPENAPI_URL)
    paths = spec.get("paths", {}) if isinstance(spec, dict) else {}
    best_score = -1
    best_method = "POST"
    best_path = ""

    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in {"post", "get"}:
                continue
            if not isinstance(operation, dict):
                continue

            score = 0
            request_body = operation.get("requestBody", {})
            content = request_body.get("content", {}) if isinstance(request_body, dict) else {}
            for content_value in content.values():
                schema = content_value.get("schema", {}) if isinstance(content_value, dict) else {}
                if schema_mentions_card_names(schema):
                    score += 5

            responses = operation.get("responses", {})
            for response_value in responses.values():
                response_content = response_value.get("content", {}) if isinstance(response_value, dict) else {}
                for content_value in response_content.values():
                    schema = content_value.get("schema", {}) if isinstance(content_value, dict) else {}
                    if schema_mentions_from_price(schema):
                        score += 5

            flattened = json.dumps(operation).lower()
            if "card_names" in flattened:
                score += 3
            if "from_price_cents" in flattened:
                score += 3
            if "not_found" in flattened:
                score += 2
            if re.search(r"/card|/cards", path.lower()):
                score += 1

            if score > best_score:
                best_score = score
                best_method = method.upper()
                best_path = path

    if not best_path:
        raise ValueError("Unable to discover Mana Pool card-price endpoint from OpenAPI spec.")

    return best_method, parse.urljoin(f"{MANAPOOL_BASE_URL}/", best_path.lstrip("/"))


def choose_manapool_match(cards: list[dict[str, Any]], product_name: str, set_name: str, card_number: str) -> dict[str, Any] | None:
    if not cards:
        return None

    normalized_name = normalize_header(product_name)
    normalized_set_name = normalize_header(set_name)
    normalized_number = normalize_identifier(card_number)

    def score(card: dict[str, Any]) -> tuple[int, int, int, int]:
        name_match = 1 if normalize_header(card.get("name", "")) == normalized_name else 0
        set_match = 1 if normalize_header(card.get("set_name", "")) == normalized_set_name else 0
        number_match = 1 if normalized_number and normalize_identifier(card.get("card_number", "")) == normalized_number else 0
        has_price = 1 if try_parse_number(card.get("from_price_cents"))[0] is not None else 0
        return (set_match, number_match, name_match, has_price)

    best = max(cards, key=score)
    best_score = score(best)
    if best_score[0] == 0:
        return None
    if normalized_number and best_score[1] == 0:
        return None
    return best


def fetch_manapool_cards_by_names(
    card_names: list[str],
    manapool_api_key: str | None,
    manapool_email: str | None,
) -> tuple[dict[str, list[dict[str, Any]]], str | None]:
    if not card_names:
        return {}, None

    method, endpoint_url = discover_manapool_cards_endpoint()
    auth_variants = get_auth_header_variants(manapool_api_key, manapool_email)
    cards_by_name: dict[str, list[dict[str, Any]]] = {}
    auth_warning: str | None = None

    for start in range(0, len(card_names), MANAPOOL_BATCH_SIZE):
        batch = card_names[start : start + MANAPOOL_BATCH_SIZE]
        payload = {"card_names": batch}
        last_error: Exception | None = None
        response_payload: Any = None

        for headers in auth_variants:
            try:
                response_payload = request_json(endpoint_url, method=method, headers=headers, payload=payload)
                auth_warning = None
                break
            except Exception as exc:
                last_error = exc
                if "401" not in str(exc) and "403" not in str(exc):
                    break

        if response_payload is None:
            raise ValueError(str(last_error) if last_error else "Mana Pool API request failed.")

        cards = response_payload.get("cards", []) if isinstance(response_payload, dict) else []
        for card in cards:
            if not isinstance(card, dict):
                continue
            normalized_name = normalize_header(card.get("name", ""))
            if normalized_name:
                cards_by_name.setdefault(normalized_name, []).append(card)

    return cards_by_name, auth_warning


def load_manapool_price_lookup(
    tcg_df: pd.DataFrame,
    column_map: dict[str, str],
    manapool_api_key: str | None,
    manapool_email: str | None,
) -> tuple[dict[tuple[str, str, str], float], dict[tuple[str, str, str], str], str | None]:
    product_name_column = column_map.get("Product Name")
    set_name_column = column_map.get("Set Name")
    number_column = column_map.get("Number")
    if not product_name_column or not set_name_column:
        return {}, {}, None

    unique_keys = sorted(
        {
            (
                safe_text(row.get(product_name_column, "")),
                safe_text(row.get(set_name_column, "")),
                safe_text(row.get(number_column, "")) if number_column else "",
            )
            for _, row in tcg_df.iterrows()
            if safe_text(row.get(product_name_column, "")) and safe_text(row.get(set_name_column, ""))
        }
    )
    if not unique_keys:
        return {}, {}, None

    unique_names = sorted({product_name for product_name, _, _ in unique_keys})
    try:
        cards_by_name, auth_warning = fetch_manapool_cards_by_names(unique_names, manapool_api_key, manapool_email)
    except Exception as exc:
        return {}, {}, f"Mana Pool API lookup was unavailable, so TCG fallback pricing was used instead. Details: {exc}"

    price_lookup: dict[tuple[str, str, str], float] = {}
    source_lookup: dict[tuple[str, str, str], str] = {}
    misses = 0

    for product_name, set_name, card_number in unique_keys:
        row_key = (normalize_header(product_name), normalize_header(set_name), normalize_identifier(card_number))
        match = choose_manapool_match(cards_by_name.get(normalize_header(product_name), []), product_name, set_name, card_number)
        if not match:
            misses += 1
            continue

        cents_value, parse_error = try_parse_number(match.get("from_price_cents"))
        if parse_error or cents_value is None:
            misses += 1
            continue

        price_lookup[row_key] = round(cents_value / 100.0, 2)
        source_lookup[row_key] = "Mana Pool API floor"

    warnings: list[str] = []
    if misses:
        warnings.append(f"Mana Pool API lookup matched {len(price_lookup)} row key(s). {misses} row key(s) fell back to TCG pricing.")
    if auth_warning:
        warnings.append(auth_warning)

    return price_lookup, source_lookup, "\n\n".join(warnings) if warnings else None


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
        {"Metric": "Cards priced from Mana Pool API", "Value": summary["manapool_api_price_count"]},
        {"Metric": "Cards priced from TCG fallback", "Value": summary["manapool_fallback_price_count"]},
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
    settings: OptimizerSettings,
    manapool_api_key: str | None = None,
    manapool_email: str | None = None,
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
            "manapool_api_price_count": 0,
            "manapool_fallback_price_count": 0,
            "tracked_shipping_review_count": 0,
        }
        analysis_df = build_analysis_dataframe(summary, settings)
        return ProcessResult(
            manapool_full_df=pd.DataFrame(columns=DISPLAY_COLUMNS_MANAPOOL + ["_forced_min", "_bump_exceeded"]),
            direct_full_df=pd.DataFrame(columns=DISPLAY_COLUMNS_DIRECT + ["_bump_exceeded"]),
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

    manapool_price_lookup, manapool_source_lookup, manapool_lookup_warning = load_manapool_price_lookup(
        tcg_df,
        column_map,
        manapool_api_key,
        manapool_email,
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
    manapool_api_price_count = 0
    manapool_fallback_price_count = 0

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
        quantity = add_quantity if add_quantity is not None and add_quantity > 0 else total_quantity
        if quantity is None or quantity <= 0:
            row_errors.append("Missing quantity")

        market_price = parsed_values.get("market_price")
        direct_low = parsed_values.get("direct_low")
        low_price = parsed_values.get("low_price")
        if low_price is None and market_price is None and not manapool_price_lookup:
            row_errors.append("Missing both TCG Low Price and TCG Market Price")
        if direct_low is None and market_price is None:
            row_errors.append("Missing both TCG Direct Low and TCG Market Price")

        if row_errors:
            if any("Missing both TCG" in item for item in row_errors):
                missing_price_data_count += 1
            error_rows.append(build_error_row(row, "; ".join(dict.fromkeys(row_errors)), source_columns))
            continue

        assert quantity is not None
        total_quantity_imported += quantity

        product_name = safe_text(row.get(column_map["Product Name"], ""))
        set_name = safe_text(row.get(column_map["Set Name"], ""))
        card_number = safe_text(row.get(column_map.get("Number", ""), "")) if column_map.get("Number") else ""
        row_key = (
            normalize_header(product_name),
            normalize_header(set_name),
            normalize_identifier(card_number),
        )

        api_manapool_price = manapool_price_lookup.get(row_key)
        if api_manapool_price is not None:
            chosen_manapool_base = api_manapool_price
            manapool_price_source = manapool_source_lookup.get(row_key, "Mana Pool API floor")
            manapool_api_price_count += 1
        else:
            chosen_manapool_base = low_price if low_price is not None else market_price
            manapool_price_source = "TCG fallback pricing"
            manapool_fallback_price_count += 1

        if chosen_manapool_base is None:
            missing_price_data_count += 1
            error_rows.append(build_error_row(row, "Missing both Mana Pool API price and TCG fallback price", source_columns))
            continue

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

        direct_listing_price = required_direct_price
        direct_net = lookup_direct_net(direct_listing_price) if direct_listing_price is not None else None
        direct_bump_pct = None
        bump_exceeded = False
        reason_parts = [manapool_price_source]

        if forced_min:
            reason_parts.append("Forced to Manapool minimum")

        if direct_listing_price is None or direct_net is None:
            destination = "manapool"
            bump_exceeded = True
            direct_bump_exceeded_count += 1
            reason_parts.append("Required Direct Price not found")
        else:
            direct_bump_pct = calculate_direct_bump_pct(base_direct_price, direct_listing_price)
            if direct_bump_pct is None:
                destination = "manapool"
                bump_exceeded = True
                direct_bump_exceeded_count += 1
                reason_parts.append("Unable to calculate Direct bump %")
            elif direct_bump_pct > settings.max_direct_bump_pct:
                destination = "manapool"
                bump_exceeded = True
                direct_bump_exceeded_count += 1
                reason_parts.append("Required Direct bump exceeded max allowed %")
            else:
                destination = "direct"
                reason_parts.append("Direct net meets or beats Manapool within bump limit")

        row_base = {
            "TCGplayer Id": safe_text(row.get(column_map["TCGplayer Id"], "")),
            "Product Line": safe_text(row.get(column_map["Product Line"], "")),
            "Set Name": set_name,
            "Product Name": product_name,
            "Number": card_number,
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
                    "Required Direct Price": round(direct_listing_price, 2) if direct_listing_price is not None else None,
                    "Direct Bump %": direct_bump_pct,
                    "Reason": "; ".join(reason_parts),
                    "_forced_min": forced_min,
                    "_bump_exceeded": bump_exceeded,
                }
            )

    manapool_full_df = pd.DataFrame(manapool_rows, columns=DISPLAY_COLUMNS_MANAPOOL + ["_forced_min", "_bump_exceeded"])
    direct_full_df = pd.DataFrame(direct_rows, columns=DISPLAY_COLUMNS_DIRECT + ["_bump_exceeded"])
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
        "manapool_api_price_count": manapool_api_price_count,
        "manapool_fallback_price_count": manapool_fallback_price_count,
        "tracked_shipping_review_count": tracked_shipping_review_count,
    }

    analysis_df = build_analysis_dataframe(summary, settings)
    warnings: list[str] = []
    if manapool_lookup_warning:
        warnings.append(manapool_lookup_warning)
    if tracked_shipping_review_count:
        warnings.append(
            f"{tracked_shipping_review_count} Manapool listing(s) are at or above ${settings.tracked_shipping_threshold:.2f} and may need manual tracked-shipping review."
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
        warning_message="\n\n".join(warnings) if warnings else None,
    )
