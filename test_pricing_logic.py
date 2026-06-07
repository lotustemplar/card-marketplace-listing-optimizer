from io import BytesIO

import pandas as pd

from pricing_logic import (
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
                "Number": "001",
                "Rarity": "Rare",
                "Condition": "Near Mint",
                "TCG Market Price": "2.50",
                "TCG Direct Low": "2.50",
                "TCG Low Price": "1.00",
                "Total Quantity": "2",
                "Add to Quantity": "",
                "TCG Marketplace Price": "",
            },
            {
                "TCGplayer Id": "2",
                "Product Line": "Magic",
                "Set Name": "Set B",
                "Product Name": "Budget Card",
                "Number": "002",
                "Rarity": "Common",
                "Condition": "Near Mint",
                "TCG Market Price": "0.10",
                "TCG Direct Low": "0.10",
                "TCG Low Price": "0.10",
                "Total Quantity": "1",
                "Add to Quantity": "",
                "TCG Marketplace Price": "",
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


def test_process_files_dual_manabox_mode_compares_purchase_prices():
    result = process_files(
        settings=OptimizerSettings(max_direct_bump_pct=0.20, direct_min_listing_price=0.40),
        manabox_tcg_bytes=build_manabox_tcg_csv(),
        manabox_manapool_bytes=build_manabox_manapool_csv(),
    )

    assert result.source_mode == "dual_manabox"
    assert len(result.direct_preview_df) == 2
    assert result.direct_preview_df.iloc[0]["Condition"] == "Near Mint Foil"
    assert "Dual ManaBox pricing comparison" in result.direct_preview_df.iloc[0]["Reason"]
    assert "Set Code" in result.direct_csv_df.columns
