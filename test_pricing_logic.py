from io import BytesIO

import pandas as pd

from pricing_logic import (
    OptimizerSettings,
    calculate_direct_bump_pct,
    calculate_manapool_net,
    find_required_direct_price,
    load_direct_fee_table,
    lookup_direct_net,
    process_files,
)


def build_fee_csv() -> bytes:
    rows = [
        ["Price", "", "", "", "", "", "", "", "", "Net"],
        [0.25, "", "", "", "", "", "", "", "", 0.05],
        [0.50, "", "", "", "", "", "", "", "", 0.22],
        [1.00, "", "", "", "", "", "", "", "", 0.62],
        [2.50, "", "", "", "", "", "", "", "", 1.75],
        [2.99, "", "", "", "", "", "", "", "", 2.35],
        [3.50, "", "", "", "", "", "", "", "", 2.65],
        [4.00, "", "", "", "", "", "", "", "", 3.05],
        [4.50, "", "", "", "", "", "", "", "", 3.45],
        [5.00, "", "", "", "", "", "", "", "", 3.90],
    ]
    csv_lines = []
    for row in rows:
        csv_lines.append(",".join("" if value == "" else str(value) for value in row))
    return "\n".join(csv_lines).encode("utf-8")


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
                "TCG Low Price": "2.50",
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


def test_direct_fee_lookup_uses_floor_price():
    fee_table = load_direct_fee_table(build_fee_csv(), "fees.csv")
    assert lookup_direct_net(3.20, fee_table) == 2.35


def test_required_direct_price_search_finds_first_qualifying_price():
    fee_table = load_direct_fee_table(build_fee_csv(), "fees.csv")
    assert find_required_direct_price(2.50, fee_table) == 3.50


def test_direct_bump_percent_calculation():
    assert round(calculate_direct_bump_pct(2.50, 2.99), 4) == 0.196


def test_process_files_assigns_rows_and_records_errors():
    result = process_files(
        tcgplayer_bytes=build_tcg_csv(),
        direct_fee_bytes=build_fee_csv(),
        direct_fee_filename="fees.csv",
        settings=OptimizerSettings(),
    )

    assert len(result.manapool_preview_df) == 1
    assert len(result.direct_preview_df) == 1
    assert len(result.errors_df) == 1
    assert result.manapool_preview_df.iloc[0]["Manapool Price"] == 0.25
    assert "Forced to Manapool minimum" in result.manapool_preview_df.iloc[0]["Reason"]
    assert result.direct_preview_df.iloc[0]["Direct Listing Price"] == 2.50


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
                "TCG Low Price": "3.20",
                "Total Quantity": "1",
                "Add to Quantity": "",
            }
        ]
    )
    buffer = BytesIO()
    tcg_dataframe.to_csv(buffer, index=False)
    result = process_files(
        tcgplayer_bytes=buffer.getvalue(),
        direct_fee_bytes=build_fee_csv(),
        direct_fee_filename="fees.csv",
        settings=OptimizerSettings(),
    )

    assert result.direct_preview_df.iloc[0]["Direct Listing Price"] == 3.50
    assert "cliff" in result.direct_preview_df.iloc[0]["Reason"].lower()
