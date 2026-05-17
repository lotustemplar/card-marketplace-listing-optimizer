from __future__ import annotations

from dataclasses import asdict, dataclass
from io import BytesIO
import base64
import json
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

MANAPOOL_OPENAPI_URL = "https://manapool.com/api/docs/v1/openapi.json"
MANAPOOL_DEFAULT_BASE_URL = "https://manapool.com"


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
                "Value": "Live Mana Pool API floor when available, otherwise TCG fallback pricing",
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


def resolve_json_ref(spec: dict[str, Any], ref: str) -> dict[str, Any]:
    target: Any = spec
    for part in ref.lstrip("#/").split("/"):
        target = target[part]
    if isinstance(target, dict):
        return target
    return {}


def resolve_schema(spec: dict[str, Any], schema: dict[str, Any] | None) -> dict[str, Any]:
    if not schema:
        return {}
    if "$ref" in schema:
        return resolve_schema(spec, resolve_json_ref(spec, schema["$ref"]))
    return schema


def schema_has_top_level_property(spec: dict[str, Any], schema: dict[str, Any] | None, property_name: str) -> bool:
    resolved = resolve_schema(spec, schema)
    return property_name in resolved.get("properties", {})


def response_has_cards_with_prices(spec: dict[str, Any], schema: dict[str, Any] | None) -> bool:
    resolved = resolve_schema(spec, schema)
    cards_property = resolve_schema(spec, resolved.get("properties", {}).get("cards"))
    if not cards_property:
        return False
    items_schema = resolve_schema(spec, cards_property.get("items"))
    return "from_price_cents" in items_schema.get("properties", {})


def find_json_schema(content_block: dict[str, Any]) -> dict[str, Any] | None:
    for mime_type in ["application/json", "application/*+json"]:
        schema = content_block.get(mime_type, {}).get("schema")
        if schema:
            return schema
    for payload in content_block.values():
        if isinstance(payload, dict) and payload.get("schema"):
            return payload["schema"]
    return None


def discover_manapool_card_lookup() -> tuple[str, str, str, list[dict[str, Any]], list[dict[str, Any]]]:
    spec = fetch_json(MANAPOOL_OPENAPI_URL)
    servers = spec.get("servers") or [{"url": MANAPOOL_DEFAULT_BASE_URL}]
    base_url = servers[0].get("url", MANAPOOL_DEFAULT_BASE_URL)
    paths = spec.get("paths", {})
    security_schemes = spec.get("components", {}).get("securitySchemes", {})

    for path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method, operation in methods.items():
            if method.lower() not in {"post", "get"} or not isinstance(operation, dict):
                continue

            request_schema = None
            request_body = operation.get("requestBody")
            if request_body:
                request_schema = find_json_schema(resolve_schema(spec, request_body).get("content", {}))
            if not schema_has_top_level_property(spec, request_schema, "card_names"):
                continue

            responses = operation.get("responses", {})
            matched_response_schema = None
            for status_code, response in responses.items():
                if not str(status_code).startswith(("2", "default")):
                    continue
                response_schema = find_json_schema(resolve_schema(spec, response).get("content", {}))
                if response_has_cards_with_prices(spec, response_schema):
                    matched_response_schema = response_schema
                    break
            if not matched_response_schema:
                continue

            operation_security = operation.get("security", spec.get("security", []))
            return base_url, path, method.upper(), operation_security, security_schemes

    raise ValueError("Unable to locate Mana Pool card lookup endpoint in the OpenAPI spec.")


def build_auth_attempts(
    operation_security: list[dict[str, Any]],
    security_schemes: dict[str, Any],
    api_key: str,
    manapool_email: str | None = None,
) -> list[tuple[dict[str, str], dict[str, str], str]]:
    base_headers = {"Accept": "application/json", "Content-Type": "application/json"}
    attempts: list[tuple[dict[str, str], dict[str, str], str]] = []
    seen: set[tuple[tuple[str, str], tuple[str, str]]] = set()

    def add_attempt(headers: dict[str, str], query: dict[str, str], label: str) -> None:
        header_key = tuple(sorted(headers.items()))
        query_key = tuple(sorted(query.items()))
        dedupe_key = (header_key, query_key)
        if dedupe_key in seen:
            return
        seen.add(dedupe_key)
        attempts.append((headers, query, label))

    if manapool_email:
        basic_value = base64.b64encode(f"{manapool_email}:{api_key}".encode("utf-8")).decode("ascii")
        add_attempt({**base_headers, "Authorization": f"Basic {basic_value}"}, {}, "basic-email-token")
        add_attempt({**base_headers, "X-User-Email": manapool_email, "X-API-Key": api_key}, {}, "x-user-email-x-api-key")
        add_attempt({**base_headers, "X-User-Email": manapool_email, "Authorization": f"Bearer {api_key}"}, {}, "x-user-email-bearer")
        add_attempt({**base_headers, "email": manapool_email, "Authorization": f"Bearer {api_key}"}, {}, "email-bearer")
        add_attempt({**base_headers, "email": manapool_email, "X-API-Key": api_key}, {}, "email-x-api-key")

    for security_requirement in operation_security:
        for scheme_name in security_requirement.keys():
            scheme = security_schemes.get(scheme_name, {})
            scheme_type = scheme.get("type")
            if scheme_type == "http":
                auth_scheme = scheme.get("scheme", "").lower()
                if auth_scheme == "bearer":
                    add_attempt({**base_headers, "Authorization": f"Bearer {api_key}"}, {}, "openapi-bearer")
                elif auth_scheme == "basic" and manapool_email:
                    basic_value = base64.b64encode(f"{manapool_email}:{api_key}".encode("utf-8")).decode("ascii")
                    add_attempt({**base_headers, "Authorization": f"Basic {basic_value}"}, {}, "openapi-basic")
            elif scheme_type == "apiKey":
                location = scheme.get("in")
                parameter_name = scheme.get("name", "X-API-Key")
                if location == "header":
                    add_attempt({**base_headers, parameter_name: api_key}, {}, f"openapi-header-{parameter_name}")
                elif location == "query":
                    add_attempt(base_headers.copy(), {parameter_name: api_key}, f"openapi-query-{parameter_name}")

    add_attempt({**base_headers, "Authorization": f"Bearer {api_key}"}, {}, "fallback-bearer")
    add_attempt({**base_headers, "X-API-Key": api_key}, {}, "fallback-x-api-key")
    add_attempt({**base_headers, "Authorization": f"Token {api_key}"}, {}, "fallback-token")
    add_attempt({**base_headers, "Authorization": f"Api-Key {api_key}"}, {}, "fallback-api-key")
    add_attempt({**base_headers, "api-key": api_key}, {}, "fallback-lower-api-key")
    add_attempt(base_headers.copy(), {"api_key": api_key}, "fallback-query-api_key")
    add_attempt(base_headers.copy(), {"token": api_key}, "fallback-query-token")

    return attempts


def fetch_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, headers=headers or {}, method=method.upper())
    try:
        with request.urlopen(req, timeout=25) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"Mana Pool API request failed ({exc.code}): {response_body[:300]}") from exc
    except error.URLError as exc:
        raise ValueError(f"Mana Pool API request failed: {exc.reason}") from exc


def fetch_json_with_attempts(
    url: str,
    *,
    method: str,
    auth_attempts: list[tuple[dict[str, str], dict[str, str], str]],
    payload: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    last_error: Exception | None = None
    for headers, query_params, label in auth_attempts:
        request_url = url
        if query_params:
            request_url = f"{url}?{parse.urlencode(query_params)}"
        try:
            return fetch_json(request_url, method=method, headers=headers, payload=payload), label
        except Exception as exc:
            last_error = exc
    raise ValueError(str(last_error) if last_error else "Mana Pool API authentication failed.")


def chunked(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def choose_manapool_candidate(card_candidates: list[dict[str, Any]], set_name: str, card_number: str) -> dict[str, Any] | None:
    if not card_candidates:
        return None

    normalized_set_name = normalize_header(set_name)
    normalized_card_number = normalize_identifier(card_number)

    def candidate_sort_key(candidate: dict[str, Any]) -> tuple[int, int, int, int]:
        candidate_set_name = normalize_header(candidate.get("set_name", ""))
        candidate_card_number = normalize_identifier(candidate.get("card_number", ""))
        set_match = 1 if normalized_set_name and candidate_set_name == normalized_set_name else 0
        number_match = 1 if normalized_card_number and candidate_card_number == normalized_card_number else 0
        quantity_available = int(candidate.get("quantity_available") or 0)
        from_price_cents = int(candidate.get("from_price_cents") or 0)
        return (set_match, number_match, quantity_available > 0, -from_price_cents)

    return max(card_candidates, key=candidate_sort_key)


def load_manapool_price_lookup(
    tcg_df: pd.DataFrame,
    column_map: dict[str, str],
    manapool_api_key: str | None,
    manapool_email: str | None = None,
) -> tuple[dict[tuple[str, str, str], float], dict[tuple[str, str, str], str], str | None]:
    if not manapool_api_key:
        return {}, {}, None

    product_name_column = column_map.get("Product Name")
    set_name_column = column_map.get("Set Name")
    number_column = column_map.get("Number")
    if not product_name_column or not set_name_column:
        return {}, {}, None

    unique_names = sorted(
        {
            safe_text(row.get(product_name_column, ""))
            for _, row in tcg_df.iterrows()
            if safe_text(row.get(product_name_column, ""))
        }
    )
    if not unique_names:
        return {}, {}, None

    try:
        base_url, path, method, operation_security, security_schemes = discover_manapool_card_lookup()
        endpoint_url = parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
        auth_attempts = build_auth_attempts(operation_security, security_schemes, manapool_api_key, manapool_email)
        cards_by_name: dict[str, list[dict[str, Any]]] = {}
        successful_auth_label = None

        for name_batch in chunked(unique_names, 100):
            response, used_auth_label = fetch_json_with_attempts(
                endpoint_url,
                method=method,
                auth_attempts=auth_attempts,
                payload={"card_names": name_batch},
            )
            if successful_auth_label is None:
                successful_auth_label = used_auth_label
            for card in response.get("cards", []):
                if int(card.get("quantity_available") or 0) <= 0:
                    continue
                if int(card.get("from_price_cents") or 0) <= 0:
                    continue
                cards_by_name.setdefault(normalize_header(card.get("name", "")), []).append(card)

        price_lookup: dict[tuple[str, str, str], float] = {}
        source_lookup: dict[tuple[str, str, str], str] = {}
        for _, row in tcg_df.iterrows():
            product_name = safe_text(row.get(product_name_column, ""))
            set_name = safe_text(row.get(set_name_column, ""))
            card_number = safe_text(row.get(number_column, "")) if number_column else ""
            row_key = (
                normalize_header(product_name),
                normalize_header(set_name),
                normalize_identifier(card_number),
            )
            candidate = choose_manapool_candidate(cards_by_name.get(normalize_header(product_name), []), set_name, card_number)
            if not candidate:
                continue
            price_lookup[row_key] = round(int(candidate.get("from_price_cents", 0)) / 100, 2)
            set_match = normalize_header(candidate.get("set_name", "")) == normalize_header(set_name)
            number_match = normalize_identifier(candidate.get("card_number", "")) == normalize_identifier(card_number)
            if set_match and number_match:
                source_lookup[row_key] = "Mana Pool API floor (exact set/number match)"
            elif set_match:
                source_lookup[row_key] = "Mana Pool API floor (set match)"
            else:
                source_lookup[row_key] = "Mana Pool API floor (best available name match)"

        warning = None
        if successful_auth_label:
            warning = f"Mana Pool API connected using auth mode: {successful_auth_label}."
        return price_lookup, source_lookup, warning
    except Exception as exc:
        return {}, {}, f"Mana Pool API lookup unavailable, so TCG fallback pricing was used instead. Details: {exc}"


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
            if any("Missing both TCG" in error for error in row_errors):
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
            error_rows.append(build_error_row(row, "Missing both Mana Pool lookup price and TCG fallback price", source_columns))
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

    manapool_full_df = pd.DataFrame(
        manapool_rows,
        columns=DISPLAY_COLUMNS_MANAPOOL + ["_forced_min", "_bump_exceeded"],
    )
    direct_full_df = pd.DataFrame(
        direct_rows,
        columns=DISPLAY_COLUMNS_DIRECT + ["_bump_exceeded"],
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
