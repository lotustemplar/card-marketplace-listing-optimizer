from io import BytesIO
from unittest.mock import patch

import pandas as pd

from pricing_logic import (
    EXPORT_COLUMNS,
    OptimizerSettings,
    calculate_direct_bump_pct,
    calculate_manapool_net,
    find_required_direct_price,
    lookup_direct_net,
    process_files,
)


def _csv_bytes(dataframe: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    dataframe.to_csv(buffer, index=False)
    return buffer.getvalue()


def build_tcg_csv() -> bytes:
    dataframe = pd.DataFrame(
        [
            {
                "TCGplayer Id": "1",
                "Product Line": "Magic",
                "Set Name": "Set A",
                "Product Name": "Alpha Card",
                "Title": "",
                "Number": "001",
                "Rarity": "Rare",
                "Condition": "Near Mint",
                "TCG Market Price": "2.50",
                "TCG Direct Low": "2.50",
                "TCG Low Price With Shipping": "3.49",
                "TCG Low Price": "1.00",
                "Total Quantity": "2",
                "Add to Quantity": "",
                "TCG Marketplace Price": "",
                "Photo URL": "",
            },
            {
                "TCGplayer Id": "2",
                "Product Line": "Magic",
                "Set Name": "Set B",
                "Product Name": "Budget Card",
                "Title": "",
                "Number": "002",
                "Rarity": "Common",
                "Condition": "Near Mint",
                "TCG Market Price": "0.10",
                "TCG Direct Low": "0.10",
                "TCG Low Price With Shipping": "1.50",
                "TCG Low Price": "0.10",
                "Total Quantity": "1",
                "Add to Quantity": "",
                "TCG Marketplace Price": "",
                "Photo URL": "",
            },
        ]
    )
    return _csv_bytes(dataframe)


def build_tcg_csv_with_market_fallbacks() -> bytes:
    dataframe = pd.DataFrame(
        [
            {
                "TCGplayer Id": "3",
                "Product Line": "Magic",
                "Set Name": "Set C",
                "Product Name": "Low Price Fallback Card",
                "Title": "",
                "Number": "003",
                "Rarity": "Common",
                "Condition": "Near Mint",
                "TCG Market Price": "",
                "TCG Direct Low": "",
                "TCG Low Price With Shipping": "1.75",
                "TCG Low Price": "0.32",
                "Total Quantity": "2",
                "Add to Quantity": "",
                "TCG Marketplace Price": "",
                "Photo URL": "",
            },
            {
                "TCGplayer Id": "4",
                "Product Line": "Magic",
                "Set Name": "Set D",
                "Product Name": "Direct Low Fallback Card",
                "Title": "",
                "Number": "004",
                "Rarity": "Uncommon",
                "Condition": "Near Mint",
                "TCG Market Price": "",
                "TCG Direct Low": "0.55",
                "TCG Low Price With Shipping": "1.90",
                "TCG Low Price": "",
                "Total Quantity": "1",
                "Add to Quantity": "",
                "TCG Marketplace Price": "",
                "Photo URL": "",
            },
        ]
    )
    return _csv_bytes(dataframe)


def build_non_mtg_tcg_csv() -> bytes:
    dataframe = pd.DataFrame(
        [
            {
                "TCGplayer Id": "5",
                "Product Line": "Weiss Schwarz",
                "Set Name": "Set E",
                "Product Name": "Non MTG Card",
                "Title": "",
                "Number": "005",
                "Rarity": "Rare",
                "Condition": "Near Mint",
                "TCG Market Price": "0.22",
                "TCG Direct Low": "",
                "TCG Low Price With Shipping": "1.60",
                "TCG Low Price": "0.12",
                "Total Quantity": "1",
                "Add to Quantity": "",
                "TCG Marketplace Price": "",
                "Photo URL": "",
            },
        ]
    )
    return _csv_bytes(dataframe)


def build_scan_export_csv() -> bytes:
    dataframe = pd.DataFrame(
        [
            {
                "game": "Magic: The Gathering",
                "set": "Commander: Marvel Super Heroes",
                "card_name": "Fantastic Elasticity",
                "card_number": "30",
                "variant": "Normal",
                "condition": "NM",
                "language": "English",
                "tcgplayer_id": "697542",
                "manapool_id": "mana-1",
                "market_price": "1.24",
                "manapool_price": "0.79",
                "device_id": "FILE",
                "timestamp": "2026-06-29T03:13:41.000Z",
            },
            {
                "game": "Magic: The Gathering",
                "set": "Commander: Marvel Super Heroes",
                "card_name": "Council of Reeds (Surge Foil)",
                "card_number": "28",
                "variant": "Normal",
                "condition": "NM",
                "language": "English",
                "tcgplayer_id": "697538",
                "manapool_id": "mana-2",
                "market_price": "",
                "manapool_price": "2.80",
                "device_id": "FILE",
                "timestamp": "2026-06-29T03:13:41.000Z",
            },
            {
                "game": "Magic: The Gathering",
                "set": "Commander: Marvel Super Heroes",
                "card_name": "Fantastic Elasticity",
                "card_number": "30",
                "variant": "Normal",
                "condition": "NM",
                "language": "English",
                "tcgplayer_id": "697542",
                "manapool_id": "mana-1",
                "market_price": "1.24",
                "manapool_price": "0.79",
                "device_id": "FILE",
                "timestamp": "2026-06-29T03:13:50.000Z",
            },
        ]
    )
    return _csv_bytes(dataframe)


def build_manabox_tcg_csv() -> bytes:
    dataframe = pd.DataFrame(
        [
            {
                "Name": "Goblin",
                "Set code": "SLD",
                "Set name": "Secret Lair Drop",
                "Collector number": "2421",
                "Foil": "foil",
                "Rarity": "common",
                "Quantity": "2",
                "Scryfall ID": "abc-1",
                "Purchase price": "6.00",
                "Condition": "near_mint",
                "Language": "en",
            },
            {
                "Name": "Storm Counter",
                "Set code": "SLD",
                "Set name": "Secret Lair Drop",
                "Collector number": "2422",
                "Foil": "foil",
                "Rarity": "common",
                "Quantity": "1",
                "Scryfall ID": "abc-2",
                "Purchase price": "14.20",
                "Condition": "near_mint",
                "Language": "en",
            },
        ]
    )
    return _csv_bytes(dataframe)


def build_manabox_manapool_csv() -> bytes:
    dataframe = pd.DataFrame(
        [
            {
                "Name": "Goblin",
                "Set code": "SLD",
                "Set name": "Secret Lair Drop",
                "Collector number": "2421",
                "Foil": "foil",
                "Rarity": "common",
                "Quantity": "2",
                "Scryfall ID": "abc-1",
                "Purchase price": "5.00",
                "Condition": "near_mint",
                "Language": "en",
            },
            {
                "Name": "Storm Counter",
                "Set code": "SLD",
                "Set name": "Secret Lair Drop",
                "Collector number": "2422",
                "Foil": "foil",
                "Rarity": "common",
                "Quantity": "1",
                "Scryfall ID": "abc-2",
                "Purchase price": "10.00",
                "Condition": "near_mint",
                "Language": "en",
            },
        ]
    )
    return _csv_bytes(dataframe)


def test_manapool_net_calculation():
    settings = OptimizerSettings()
    assert calculate_manapool_net(1.00, settings) == 0.92


def test_direct_net_uses_builtin_floor():
    settings = OptimizerSettings(direct_min_listing_price=0.40)
    assert lookup_direct_net(0.10, settings) == 0.20


def test_required_direct_price_search_finds_first_qualifying_price():
    settings = OptimizerSettings(direct_min_listing_price=0.40)
    assert find_required_direct_price(0.23, settings) == 0.45


def test_direct_bump_percent_calculation():
    assert round(calculate_direct_bump_pct(2.50, 2.99), 4) == 0.196


def test_process_files_tcgplayer_mode_routes_low_card_to_manapool():
    result = process_files(
        settings=OptimizerSettings(max_direct_bump_pct=0.20, direct_min_listing_price=0.40),
        tcgplayer_bytes=build_tcg_csv(),
    )

    assert len(result.manapool_preview_df) == 1
    assert len(result.direct_preview_df) == 1
    assert result.manapool_preview_df.iloc[0]["Product Name"] == "Budget Card"
    assert "Required Direct bump exceeded max allowed %" in result.manapool_preview_df.iloc[0]["Reason"]


def test_process_files_tcgplayer_mode_uses_low_or_direct_when_market_missing():
    result = process_files(
        settings=OptimizerSettings(max_direct_bump_pct=0.20, direct_min_listing_price=0.40),
        tcgplayer_bytes=build_tcg_csv_with_market_fallbacks(),
    )

    assert result.summary["skipped_error_rows"] == 0
    assert len(result.direct_preview_df) + len(result.manapool_preview_df) == 2
    combined_csv_df = pd.concat([result.direct_csv_df, result.manapool_csv_df], ignore_index=True)
    low_fallback_row = combined_csv_df[combined_csv_df["Product Name"] == "Low Price Fallback Card"]
    direct_fallback_row = combined_csv_df[combined_csv_df["Product Name"] == "Direct Low Fallback Card"]
    assert not low_fallback_row.empty
    assert not direct_fallback_row.empty
    assert low_fallback_row.iloc[0]["TCG Market Price"] == "0.32"
    assert direct_fallback_row.iloc[0]["TCG Market Price"] == "0.55"


def test_process_files_non_mtg_routes_to_direct():
    result = process_files(
        settings=OptimizerSettings(max_direct_bump_pct=0.20, direct_min_listing_price=0.40),
        tcgplayer_bytes=build_non_mtg_tcg_csv(),
    )

    assert len(result.direct_preview_df) == 1
    assert len(result.manapool_preview_df) == 0
    assert result.direct_preview_df.iloc[0]["Product Line"] == "Weiss Schwarz"
    assert "Non-MTG product line routed to TCGPlayer because Manapool only supports Magic" in result.direct_preview_df.iloc[0]["Reason"]


def test_process_files_accepts_scan_export_format():
    result = process_files(
        settings=OptimizerSettings(max_direct_bump_pct=0.20, direct_min_listing_price=0.40),
        tcgplayer_bytes=build_scan_export_csv(),
    )

    assert result.source_mode == "scan_export"
    assert result.summary["skipped_error_rows"] == 0
    assert result.summary["total_rows_imported"] == 2
    combined_csv_df = pd.concat([result.direct_csv_df, result.manapool_csv_df], ignore_index=True)
    fantastic = combined_csv_df[combined_csv_df["Product Name"] == "Fantastic Elasticity"]
    reeds = combined_csv_df[combined_csv_df["Product Name"] == "Council of Reeds (Surge Foil)"]
    assert not fantastic.empty
    assert not reeds.empty
    assert fantastic.iloc[0]["Total Quantity"] == "2"
    assert fantastic.iloc[0]["TCGplayer Id"] == "697542"
    assert fantastic.iloc[0]["Condition"] == "Near Mint"
    assert reeds.iloc[0]["TCG Market Price"] == ""
    reason_text = " ".join(result.direct_preview_df["Reason"].astype(str).tolist() + result.manapool_preview_df["Reason"].astype(str).tolist())
    assert "Scan export pricing comparison" in reason_text


@patch(
    "pricing_logic.fetch_tcgplayer_metadata_from_scryfall",
    return_value=(
        {
            "abc-1": {
                "TCGplayer Id": "111",
                "Set Name": "Secret Lair Drop Series",
                "Product Name": "Goblin Token",
                "Number": "2421",
                "Rarity": "T",
            },
            "abc-2": {
                "TCGplayer Id": "222",
                "Set Name": "Secret Lair Drop Series",
                "Product Name": "Storm Counter",
                "Number": "2422",
                "Rarity": "T",
            },
        },
        [],
    ),
)
def test_process_files_dual_manabox_mode_compares_purchase_prices(mock_scryfall_lookup):
    result = process_files(
        settings=OptimizerSettings(max_direct_bump_pct=0.20, direct_min_listing_price=0.40),
        manabox_tcg_bytes=build_manabox_tcg_csv(),
        manabox_manapool_bytes=build_manabox_manapool_csv(),
    )

    assert result.source_mode == "dual_manabox"
    assert len(result.direct_preview_df) == 2
    assert result.direct_preview_df.iloc[0]["Condition"] == "Near Mint Foil"
    assert "Dual ManaBox pricing comparison" in result.direct_preview_df.iloc[0]["Reason"]
    assert list(result.direct_csv_df.columns) == EXPORT_COLUMNS
    assert list(result.manapool_csv_df.columns) == EXPORT_COLUMNS
    assert set(result.direct_csv_df["TCGplayer Id"]) == {"111", "222"}
    assert set(result.direct_csv_df["Rarity"]) == {"T"}
    assert set(result.direct_csv_df["Set Name"]) == {"Secret Lair Drop Series"}
    assert set(result.direct_csv_df["Product Name"]) == {"Goblin Token", "Storm Counter"}
    assert set(result.direct_csv_df["Title"]) == {""}
    assert set(result.direct_csv_df["Photo URL"]) == {""}
    mock_scryfall_lookup.assert_called_once()
