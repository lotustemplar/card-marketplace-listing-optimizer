from io import BytesIO

import pandas as pd

from pricing_logic import (
    OptimizerSettings,
    calculate_direct_bump_pct,
    calculate_direct_net,
    calculate_manapool_net,
    find_required_direct_price,
    lookup_direct_net,
    process_files,
)


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
                "TCG Market Price": "5.00",
                "TCG Direct Low": "5.00",
                "TCG Low Price": "2.50",
                "TCG Marketplace Price": "",
                "Total Quantity": "2",
                "Add to Quantity": "",
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
                "TCG Marketplace Price": "",
                "Total Quantity": "1",
                "Add to Quantity": "",
            },
            {
                "TCGplayer Id": "3",
                "Product Line": "Magic",
                "Set Name": "Set C",
                "Product Name": "Error Card",
                "Number": "003",
                "Rarity": "Uncommon",
                "Condition": "Near Mint",
                "TCG Market Price": "",
                "TCG Direct Low": "",
                "TCG Low Price": "",
                "TCG Marketplace Price": "",
                "Total Quantity": "0",
                "Add to Quantity": "",
            },
        ]
    )
    buffer = BytesIO()
    dataframe.to_csv(buffer, index=False)
    return buffer.getvalue()


def test_manapool_net_calculation():
    settings = OptimizerSettings()
    assert calculate_manapool_net(1.00, settings) == 0.91


def test_direct_net_calculation_below_250():
    assert calculate_direct_net(2.00) == 1.00


def test_direct_net_calculation_at_or_above_250():
    assert calculate_direct_net(3.00) == 1.54


def test_required_direct_price_search_finds_first_qualifying_price():
    assert find_required_direct_price(1.41) == 2.86


def test_direct_bump_percent_calculation():
    assert round(calculate_direct_bump_pct(2.50, 2.89), 4) == 0.156


def test_lookup_direct_net_uses_new_formula():
    assert lookup_direct_net(4.00) == 2.42


def test_process_files_assigns_rows_and_records_errors():
    result = process_files(
        tcgplayer_bytes=build_tcg_csv(),
        direct_fee_bytes=None,
        direct_fee_filename=None,
        settings=OptimizerSettings(),
    )

    assert len(result.manapool_preview_df) == 1
    assert len(result.direct_preview_df) == 1
    assert len(result.errors_df) == 1
    assert result.manapool_preview_df.iloc[0]["Manapool Price"] == 0.25
    assert "Forced to Manapool minimum" in result.manapool_preview_df.iloc[0]["Reason"]
    assert result.direct_preview_df.iloc[0]["Direct Listing Price"] == 5.00


def test_cliff_rule_bumps_above_direct_cliff():
    tcg_dataframe = pd.DataFrame(
        [
            {
                "TCGplayer Id": "9",
                "Product Line": "Magic",
                "Set Name": "Set Z",
                "Product Name": "Cliff Card",
                "Number": "009",
                "Rarity": "Rare",
                "Condition": "Near Mint",
                "TCG Market Price": "2.60",
                "TCG Direct Low": "2.60",
                "TCG Low Price": "1.85",
                "TCG Marketplace Price": "",
                "Total Quantity": "1",
                "Add to Quantity": "",
            }
        ]
    )
    buffer = BytesIO()
    tcg_dataframe.to_csv(buffer, index=False)
    result = process_files(
        tcgplayer_bytes=buffer.getvalue(),
        direct_fee_bytes=None,
        direct_fee_filename=None,
        settings=OptimizerSettings(),
    )

    assert result.manapool_preview_df.iloc[0]["Required Direct Price"] == 3.41
    assert "cliff" in result.manapool_preview_df.iloc[0]["Reason"].lower()
