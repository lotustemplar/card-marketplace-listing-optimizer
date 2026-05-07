from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import streamlit as st

from pricing_logic import OptimizerSettings, process_files
from workbook_writer import build_workbook


st.set_page_config(
    page_title="Card Marketplace Listing Optimizer",
    layout="wide",
)


DIRECT_FEE_CANDIDATE_PATHS = [
    Path(__file__).parent / "DIRECT vs PWE CALC.xlsx",
    Path(__file__).parent / "assets" / "DIRECT vs PWE CALC.xlsx",
]


def get_configured_password() -> str | None:
    secret_password = None
    if hasattr(st, "secrets"):
        secret_password = st.secrets.get("APP_PASSWORD")
    return secret_password or os.getenv("APP_PASSWORD")


def require_password_if_needed() -> None:
    configured_password = get_configured_password()
    if not configured_password:
        return

    if st.session_state.get("authenticated"):
        return

    st.title("Card Marketplace Listing Optimizer")
    st.caption("Password protected access is enabled for this deployment.")
    entered_password = st.text_input("Enter password", type="password")
    if st.button("Unlock"):
        if entered_password == configured_password:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    st.stop()


def build_settings() -> OptimizerSettings:
    st.sidebar.header("Settings")
    manapool_min_price = st.sidebar.number_input("Manapool minimum price ($)", min_value=0.01, value=0.25, step=0.01, format="%.2f")
    manapool_platform_fee_pct = st.sidebar.number_input("Manapool platform fee (%)", min_value=0.0, value=5.0, step=0.1, format="%.1f")
    credit_card_fee_pct = st.sidebar.number_input("Credit card fee (%)", min_value=0.0, value=2.9, step=0.1, format="%.1f")
    processing_fee = st.sidebar.number_input("Processing fee ($)", min_value=0.0, value=0.30, step=0.01, format="%.2f")
    buyer_shipping_charged = st.sidebar.number_input("Buyer shipping charged ($)", min_value=0.0, value=1.31, step=0.01, format="%.2f")
    stamp_cost = st.sidebar.number_input("Stamp cost ($)", min_value=0.0, value=0.75, step=0.01, format="%.2f")
    toploader_cost = st.sidebar.number_input("Toploader cost ($)", min_value=0.0, value=0.10, step=0.01, format="%.2f")
    envelope_cost = st.sidebar.number_input("Envelope cost ($)", min_value=0.0, value=0.03, step=0.01, format="%.2f")
    team_bag_cost = st.sidebar.number_input("Team bag cost ($)", min_value=0.0, value=0.03, step=0.01, format="%.2f")
    max_direct_bump_percent = st.sidebar.number_input("Maximum Direct bump percentage (%)", min_value=0.0, value=20.0, step=1.0, format="%.1f")
    direct_cliff_start = st.sidebar.number_input("Direct low-price cliff start ($)", min_value=0.01, value=3.00, step=0.01, format="%.2f")
    direct_cliff_end = st.sidebar.number_input("Direct low-price cliff end ($)", min_value=0.01, value=3.40, step=0.01, format="%.2f")
    tracked_shipping_threshold = st.sidebar.number_input(
        "Manapool free tracked shipping threshold ($)",
        min_value=0.0,
        value=50.00,
        step=0.50,
        format="%.2f",
    )
    tracked_shipping_cost = st.sidebar.number_input("Tracked shipping cost ($)", min_value=0.0, value=6.00, step=0.25, format="%.2f")

    return OptimizerSettings(
        manapool_min_price=manapool_min_price,
        manapool_platform_fee=manapool_platform_fee_pct / 100,
        credit_card_fee=credit_card_fee_pct / 100,
        processing_fee=processing_fee,
        buyer_shipping_charged=buyer_shipping_charged,
        stamp_cost=stamp_cost,
        toploader_cost=toploader_cost,
        envelope_cost=envelope_cost,
        team_bag_cost=team_bag_cost,
        max_direct_bump_pct=max_direct_bump_percent / 100,
        direct_cliff_start=direct_cliff_start,
        direct_cliff_end=direct_cliff_end,
        tracked_shipping_threshold=tracked_shipping_threshold,
        tracked_shipping_cost=tracked_shipping_cost,
    )


def render_summary(result) -> None:
    summary = result.summary
    metric_one, metric_two, metric_three, metric_four = st.columns(4)
    metric_one.metric("Rows Imported", summary["total_rows_imported"])
    metric_two.metric("Quantity Imported", summary["total_quantity_imported"])
    metric_three.metric("Assigned to Manapool", summary["total_cards_assigned_manapool"])
    metric_four.metric("Assigned to Direct", summary["total_cards_assigned_direct"])

    metric_five, metric_six, metric_seven, metric_eight = st.columns(4)
    metric_five.metric("Estimated Manapool Net", f"${summary['total_estimated_manapool_net']:.2f}")
    metric_six.metric("Estimated Direct Net", f"${summary['total_estimated_direct_net']:.2f}")
    metric_seven.metric("Combined Estimated Net", f"${summary['combined_estimated_net']:.2f}")
    metric_eight.metric("Skipped/Error Rows", summary["skipped_error_rows"])

    st.dataframe(result.analysis_df, use_container_width=True, hide_index=True)


def load_builtin_direct_fee_file() -> tuple[bytes | None, str | None]:
    for candidate_path in DIRECT_FEE_CANDIDATE_PATHS:
        if candidate_path.exists():
            return candidate_path.read_bytes(), candidate_path.name
    return None, None


def main() -> None:
    require_password_if_needed()

    st.markdown(
        """
        <style>
        .stApp {
            background:
                radial-gradient(circle at top left, rgba(15, 118, 110, 0.22), transparent 28%),
                radial-gradient(circle at top right, rgba(59, 130, 246, 0.18), transparent 24%),
                linear-gradient(180deg, #071018 0%, #0b1520 100%);
            color: #e6edf3;
        }
        .block-container {padding-top: 2rem; padding-bottom: 2rem;}
        h1, h2, h3, p, label, .stCaption {
            color: #e6edf3 !important;
        }
        div[data-testid="stMetric"] {
            background: rgba(9, 18, 28, 0.88);
            border: 1px solid rgba(148, 163, 184, 0.22);
            border-radius: 14px;
            padding: 0.85rem 1rem;
            box-shadow: 0 16px 36px rgba(2, 6, 23, 0.34);
        }
        .upload-panel {
            border: 1px solid rgba(148, 163, 184, 0.18);
            border-radius: 16px;
            padding: 1rem 1.25rem;
            background: linear-gradient(180deg, rgba(7, 16, 24, 0.9) 0%, rgba(13, 23, 34, 0.94) 100%);
            margin-bottom: 1rem;
        }
        div[data-baseweb="input"] > div,
        div[data-testid="stFileUploader"] section,
        div[data-testid="stDataFrame"] {
            background: rgba(9, 18, 28, 0.88) !important;
            color: #e6edf3 !important;
            border-color: rgba(148, 163, 184, 0.2) !important;
        }
        div[data-testid="stSidebar"] {
            background: #08131c;
        }
        div[data-testid="stSidebar"] * {
            color: #e6edf3 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    settings = build_settings()

    st.title("Card Marketplace Listing Optimizer")
    st.caption("Compare TCGPlayer Direct vs Manapool and generate optimized listing sheets.")

    st.markdown('<div class="upload-panel">', unsafe_allow_html=True)
    tcgplayer_file = st.file_uploader("Upload TCGPlayer CSV export", type=["csv"])
    built_in_fee_bytes, built_in_fee_name = load_builtin_direct_fee_file()
    if built_in_fee_bytes:
        st.success(f"Built-in Direct fee table loaded: `{built_in_fee_name}`")
    else:
        st.info("Built-in Direct fee table not added yet. Add `DIRECT vs PWE CALC.xlsx` to the repo root or `assets/` and the app will use it automatically.")
    generate_clicked = st.button("Generate Listing Sheets", type="primary", use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

    if not generate_clicked:
        st.info("Upload your TCGPlayer CSV, adjust any settings you want in the sidebar, and generate the workbook.")
        return

    if tcgplayer_file is None:
        st.error("Please upload the TCGPlayer CSV export.")
        return

    if not built_in_fee_bytes or not built_in_fee_name:
        st.error("The built-in Direct fee table has not been added yet. Add `DIRECT vs PWE CALC.xlsx` to the repo root or `assets/` and the app will use it automatically.")
        return

    try:
        tcgplayer_bytes = tcgplayer_file.getvalue()
        result = process_files(
            tcgplayer_bytes=tcgplayer_bytes,
            direct_fee_bytes=built_in_fee_bytes,
            direct_fee_filename=built_in_fee_name,
            settings=settings,
        )
        workbook_bytes = build_workbook(result)
    except Exception as exc:
        st.error(f"Processing failed: {exc}")
        return

    if result.missing_columns:
        st.error(f"Required columns are missing from the TCGPlayer CSV: {', '.join(result.missing_columns)}")
    else:
        st.success("Workbook generated successfully.")

    if result.warning_message:
        st.warning(result.warning_message)

    render_summary(result)

    filename = f"card_listing_output_{datetime.now().strftime('%Y-%m-%d_%H%M')}.xlsx"
    st.download_button(
        "Download Optimized Listing Workbook",
        data=workbook_bytes,
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    st.subheader("Manapool Sheet Preview")
    st.dataframe(result.manapool_preview_df, use_container_width=True, hide_index=True)

    st.subheader("TCGPlayer Direct Sheet Preview")
    st.dataframe(result.direct_preview_df, use_container_width=True, hide_index=True)

    if not result.errors_df.empty:
        st.subheader("Errors Sheet Preview")
        st.dataframe(result.errors_df, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
