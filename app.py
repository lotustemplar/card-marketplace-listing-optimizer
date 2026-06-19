from __future__ import annotations

import os
import pickle
from datetime import datetime

import pandas as pd
import streamlit as st

from pricing_logic import OptimizerSettings, process_files
from workbook_writer import build_workbook


APP_VERSION = "4.0"

st.set_page_config(
    page_title="Card Marketplace Listing Optimizer",
    layout="wide",
)


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
        st.error("Incorrect password.")
    st.stop()


def build_settings() -> OptimizerSettings:
    st.sidebar.header("Settings")
    st.sidebar.caption(f"App version {APP_VERSION}")
    return OptimizerSettings(
        manapool_min_price=st.sidebar.number_input("Manapool minimum price ($)", min_value=0.01, value=0.25, step=0.01, format="%.2f"),
        manapool_platform_fee=st.sidebar.number_input("Manapool platform fee (%)", min_value=0.0, value=5.0, step=0.1, format="%.1f") / 100,
        credit_card_fee=st.sidebar.number_input("Credit card fee (%)", min_value=0.0, value=2.9, step=0.1, format="%.1f") / 100,
        processing_fee=st.sidebar.number_input("Processing fee ($)", min_value=0.0, value=0.30, step=0.01, format="%.2f"),
        buyer_shipping_charged=st.sidebar.number_input("Buyer shipping charged ($)", min_value=0.0, value=1.31, step=0.01, format="%.2f"),
        stamp_cost=st.sidebar.number_input("Stamp cost ($)", min_value=0.0, value=0.75, step=0.01, format="%.2f"),
        toploader_cost=st.sidebar.number_input("Toploader cost ($)", min_value=0.0, value=0.10, step=0.01, format="%.2f"),
        envelope_cost=st.sidebar.number_input("Envelope cost ($)", min_value=0.0, value=0.03, step=0.01, format="%.2f"),
        team_bag_cost=st.sidebar.number_input("Team bag cost ($)", min_value=0.0, value=0.03, step=0.01, format="%.2f"),
        max_direct_bump_pct=st.sidebar.number_input("Maximum Direct bump percentage (%)", min_value=0.0, value=20.0, step=1.0, format="%.1f") / 100,
        tracked_shipping_threshold=st.sidebar.number_input("Manapool free tracked shipping threshold ($)", min_value=0.0, value=50.00, step=0.50, format="%.2f"),
        tracked_shipping_cost=st.sidebar.number_input("Tracked shipping cost ($)", min_value=0.0, value=6.00, step=0.25, format="%.2f"),
        direct_min_listing_price=st.sidebar.number_input("Direct minimum listing price ($)", min_value=0.01, value=0.40, step=0.01, format="%.2f"),
    )


def dataframe_to_csv_bytes(dataframe: pd.DataFrame, encoding: str = "cp1252") -> bytes:
    csv_text = dataframe.to_csv(index=False, lineterminator="\r\n")
    return csv_text.encode(encoding, errors="replace")


def render_summary(result) -> None:
    summary = result.summary
    row_one = st.columns(4)
    row_one[0].metric("Rows Imported", summary["total_rows_imported"])
    row_one[1].metric("Quantity Imported", summary["total_quantity_imported"])
    row_one[2].metric("Assigned to Manapool", summary["total_cards_assigned_manapool"])
    row_one[3].metric("Assigned to Direct", summary["total_cards_assigned_direct"])

    row_two = st.columns(4)
    row_two[0].metric("Estimated Manapool Net", f"${summary['total_estimated_manapool_net']:.2f}")
    row_two[1].metric("Estimated Direct Net", f"${summary['total_estimated_direct_net']:.2f}")
    row_two[2].metric("Combined Estimated Net", f"${summary['combined_estimated_net']:.2f}")
    row_two[3].metric("Skipped/Error Rows", summary["skipped_error_rows"])

    row_three = st.columns(2)
    row_three[0].metric("If Everything Went to Mana Pool", f"${summary['all_manapool_estimated_net']:.2f}")
    row_three[1].metric("If Everything Went to Direct", f"${summary['all_direct_estimated_net']:.2f}")

    st.dataframe(result.analysis_df, width="stretch", hide_index=True)


def render_result(result, workbook_bytes: bytes, timestamp: str) -> None:
    if result.missing_columns:
        st.error(f"Required columns are missing: {', '.join(result.missing_columns)}")
    else:
        st.success("Workbook generated successfully.")

    if result.warning_message:
        st.warning(result.warning_message)

    render_summary(result)

    downloads = st.columns(3)
    with downloads[0]:
        st.download_button(
            "Download Optimized Listing Workbook",
            data=workbook_bytes,
            file_name=f"card_listing_output_{timestamp}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
        )
    with downloads[1]:
        st.download_button(
            "Download Manapool CSV",
            data=dataframe_to_csv_bytes(result.manapool_csv_df),
            file_name=f"manapool_upload_{timestamp}.csv",
            mime="text/csv",
            width="stretch",
            disabled=result.manapool_csv_df.empty,
        )
    with downloads[2]:
        st.download_button(
            "Download TCGPlayer Direct CSV",
            data=dataframe_to_csv_bytes(result.direct_csv_df),
            file_name=f"tcgplayer_direct_upload_{timestamp}.csv",
            mime="text/csv",
            width="stretch",
            disabled=result.direct_csv_df.empty,
        )

    st.subheader("Manapool Sheet Preview")
    st.dataframe(result.manapool_preview_df, width="stretch", hide_index=True)

    st.subheader("TCGPlayer Direct Sheet Preview")
    st.dataframe(result.direct_preview_df, width="stretch", hide_index=True)

    if not result.errors_df.empty:
        st.subheader("Errors Sheet Preview")
        st.dataframe(result.errors_df, width="stretch", hide_index=True)


def run_optimizer(mode: str, settings: OptimizerSettings, tcgplayer_file=None, manabox_tcg_file=None, manabox_manapool_file=None) -> None:
    if mode == "TCGPlayer CSV":
        result = process_files(settings=settings, tcgplayer_bytes=tcgplayer_file.getvalue())
    else:
        result = process_files(
            settings=settings,
            manabox_tcg_bytes=manabox_tcg_file.getvalue(),
            manabox_manapool_bytes=manabox_manapool_file.getvalue(),
        )
    workbook_bytes = build_workbook(result)
    st.session_state["optimizer_result"] = pickle.dumps(result)
    st.session_state["optimizer_workbook_bytes"] = workbook_bytes
    st.session_state["optimizer_timestamp"] = datetime.now().strftime("%Y-%m-%d_%H%M")
    st.session_state["optimizer_mode"] = mode


def main() -> None:
    require_password_if_needed()

    st.markdown(
        """
        <style>
        .block-container {padding-top: 2rem; padding-bottom: 2rem;}
        div[data-testid="stMetric"] {
            background: #ffffff;
            border: 1px solid #d9e2ec;
            border-radius: 14px;
            padding: 0.85rem 1rem;
            box-shadow: 0 8px 24px rgba(15, 76, 92, 0.06);
        }
        .upload-panel {
            border: 1px solid #d9e2ec;
            border-radius: 16px;
            padding: 1rem 1.25rem;
            background: linear-gradient(180deg, #ffffff 0%, #f8fbfc 100%);
            margin-bottom: 1rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    settings = build_settings()

    st.title("Card Marketplace Listing Optimizer")
    st.caption(f"Compare TCGPlayer Direct vs Manapool and generate optimized listing sheets. App version {APP_VERSION}.")
    st.markdown(f"**App version:** `{APP_VERSION}`")
    st.info("Use either a native TCGPlayer export or two ManaBox pricing exports with the same inventory slice: one priced to TCGPlayer market and one priced to Manapool market. Dual ManaBox mode now fills TCGplayer Id from each row's Scryfall ID when available.")

    mode = st.radio("Input mode", ["TCGPlayer CSV", "Dual ManaBox Pricing CSVs"], horizontal=True)

    st.markdown('<div class="upload-panel">', unsafe_allow_html=True)
    generate_clicked = False
    tcgplayer_file = None
    manabox_tcg_file = None
    manabox_manapool_file = None

    if mode == "TCGPlayer CSV":
        tcgplayer_file = st.file_uploader("Upload TCGPlayer CSV export", type=["csv"], key="tcgplayer_csv")
        generate_clicked = st.button("Generate Listing Sheets", type="primary", width="stretch", key="generate_tcg")
    else:
        upload_cols = st.columns(2)
        with upload_cols[0]:
            manabox_tcg_file = st.file_uploader(
                "Upload ManaBox CSV with TCGPlayer market pricing",
                type=["csv"],
                key="manabox_tcg_csv",
            )
        with upload_cols[1]:
            manabox_manapool_file = st.file_uploader(
                "Upload ManaBox CSV with Manapool market pricing",
                type=["csv"],
                key="manabox_manapool_csv",
            )
        generate_clicked = st.button("Generate Listing Sheets", type="primary", width="stretch", key="generate_manabox")
    st.markdown("</div>", unsafe_allow_html=True)

    if generate_clicked:
        try:
            if mode == "TCGPlayer CSV":
                if tcgplayer_file is None:
                    st.error("Please upload the TCGPlayer CSV export.")
                    return
                run_optimizer(mode, settings, tcgplayer_file=tcgplayer_file)
            else:
                if manabox_tcg_file is None or manabox_manapool_file is None:
                    st.error("Please upload both ManaBox pricing exports.")
                    return
                run_optimizer(
                    mode,
                    settings,
                    manabox_tcg_file=manabox_tcg_file,
                    manabox_manapool_file=manabox_manapool_file,
                )
        except Exception as exc:
            st.error(f"Processing failed: {exc}")
            return

    stored_result = st.session_state.get("optimizer_result")
    stored_workbook_bytes = st.session_state.get("optimizer_workbook_bytes")
    stored_timestamp = st.session_state.get("optimizer_timestamp")
    if not stored_result or not stored_workbook_bytes or not stored_timestamp:
        if mode == "TCGPlayer CSV":
            st.info("Upload your TCGPlayer CSV, adjust the settings in the sidebar, and generate the workbook.")
        else:
            st.info("Upload both ManaBox pricing CSVs for the same inventory slice, then generate the workbook.")
        return

    result = pickle.loads(stored_result)
    render_result(result, stored_workbook_bytes, stored_timestamp)


if __name__ == "__main__":
    main()
