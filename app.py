from __future__ import annotations

import os
import pickle
from datetime import datetime

import pandas as pd
import streamlit as st

from pricing_logic import OptimizerSettings, process_files
from workbook_writer import build_workbook


APP_VERSION = "1.4"

st.set_page_config(
    page_title="Card Marketplace Listing Optimizer",
    layout="wide",
)


def get_configured_password() -> str | None:
    secret_password = None
    if hasattr(st, "secrets"):
        secret_password = st.secrets.get("APP_PASSWORD")
    return secret_password or os.getenv("APP_PASSWORD")


def get_manapool_api_key() -> str | None:
    secret_key = None
    if hasattr(st, "secrets"):
        secret_key = st.secrets.get("MANAPOOL_API_KEY")
    return secret_key or os.getenv("MANAPOOL_API_KEY")


def get_manapool_email() -> str | None:
    secret_email = None
    if hasattr(st, "secrets"):
        secret_email = st.secrets.get("MANAPOOL_EMAIL")
    return secret_email or os.getenv("MANAPOOL_EMAIL")


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
        tracked_shipping_threshold=tracked_shipping_threshold,
        tracked_shipping_cost=tracked_shipping_cost,
    )


def dataframe_to_plain_csv_bytes(dataframe: pd.DataFrame) -> bytes:
    csv_text = dataframe.to_csv(index=False, lineterminator="\r\n")
    return csv_text.encode("cp1252", errors="replace")


def run_optimizer(
    tcgplayer_bytes: bytes,
    settings: OptimizerSettings,
    manapool_api_key: str | None,
    manapool_email: str | None,
    match_overrides: dict[str, dict[str, object]] | None = None,
) -> None:
    result = process_files(
        tcgplayer_bytes=tcgplayer_bytes,
        settings=settings,
        manapool_api_key=manapool_api_key,
        manapool_email=manapool_email,
        manapool_match_overrides=match_overrides,
    )
    workbook_bytes = build_workbook(result)
    st.session_state["optimizer_result"] = pickle.dumps(result)
    st.session_state["optimizer_workbook_bytes"] = workbook_bytes
    st.session_state["optimizer_timestamp"] = datetime.now().strftime("%Y-%m-%d_%H%M")
    st.session_state["optimizer_source_bytes"] = tcgplayer_bytes
    st.session_state["optimizer_match_overrides"] = match_overrides or {}


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

    metric_nine, metric_ten = st.columns(2)
    metric_nine.metric("If Everything Went to Mana Pool", f"${summary['all_manapool_estimated_net']:.2f}")
    metric_ten.metric("If Everything Went to Direct", f"${summary['all_direct_estimated_net']:.2f}")

    st.dataframe(result.analysis_df, width="stretch", hide_index=True)


def render_result(result, workbook_bytes: bytes, timestamp: str) -> None:
    if result.missing_columns:
        st.error(f"Required columns are missing from the TCGPlayer CSV: {', '.join(result.missing_columns)}")
    else:
        st.success("Workbook generated successfully.")

    if result.warning_message:
        st.warning(result.warning_message)

    render_summary(result)

    filename = f"card_listing_output_{timestamp}.xlsx"
    download_one, download_two, download_three = st.columns(3)
    with download_one:
        st.download_button(
            "Download Optimized Listing Workbook",
            data=workbook_bytes,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
        )
    with download_two:
        st.download_button(
            "Download Manapool CSV",
            data=dataframe_to_plain_csv_bytes(result.manapool_csv_df),
            file_name=f"manapool_upload_{timestamp}.csv",
            mime="text/csv",
            width="stretch",
            disabled=result.manapool_csv_df.empty,
        )
    with download_three:
        st.download_button(
            "Download TCGPlayer Direct CSV",
            data=dataframe_to_plain_csv_bytes(result.direct_csv_df),
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


def render_manual_resolution_panel(
    result,
    settings: OptimizerSettings,
    manapool_api_key: str | None,
    manapool_email: str | None,
) -> None:
    unresolved_options = result.unresolved_options
    if not unresolved_options:
        return

    current_overrides = dict(st.session_state.get("optimizer_match_overrides", {}))
    auto_overrides_added = False

    for item in unresolved_options:
        if len(item["options"]) != 1:
            continue
        selected_option = item["options"][0]
        existing_override = current_overrides.get(item["row_key"])
        if existing_override and existing_override.get("label") == selected_option["label"]:
            continue
        current_overrides[item["row_key"]] = {
            "price": selected_option["price"],
            "label": selected_option["label"],
            "reason": selected_option.get("reason", f"Mana Pool single-option auto override: {selected_option['label']}"),
        }
        auto_overrides_added = True

    if auto_overrides_added:
        source_bytes = st.session_state.get("optimizer_source_bytes")
        if not source_bytes:
            st.error("The original TCGPlayer CSV is no longer in session. Please upload it again and regenerate.")
            return
        run_optimizer(
            tcgplayer_bytes=source_bytes,
            settings=settings,
            manapool_api_key=manapool_api_key,
            manapool_email=manapool_email,
            match_overrides=current_overrides,
        )
        st.rerun()

    remaining_unresolved = [item for item in unresolved_options if len(item["options"]) > 1]
    if not remaining_unresolved:
        return

    st.subheader("Resolve Mana Pool Matches")
    st.caption("These rows only appear here when more than one real Mana Pool option still remains after filtering. If the app narrows a row down to one valid option, it auto-applies it before showing manual review.")

    with st.form("manapool_match_override_form"):
        for item in remaining_unresolved:
            st.markdown(f"**{item['product_name']}** | {item['set_name']} | #{item['number'] or '?'}")
            labels = ["Use TCG fallback"] + [option["label"] for option in item["options"]]
            default_label = "Use TCG fallback"
            existing_override = current_overrides.get(item["row_key"])
            if existing_override and existing_override.get("label") in labels:
                default_label = existing_override["label"]
            st.selectbox(
                "Choose Mana Pool match",
                labels,
                index=labels.index(default_label),
                key=f"override_select_{item['row_key']}",
                label_visibility="collapsed",
            )

        submitted = st.form_submit_button("Apply Mana Pool Match Overrides")

    if submitted:
        match_overrides: dict[str, dict[str, object]] = dict(current_overrides)
        for item in remaining_unresolved:
            selected_label = st.session_state.get(f"override_select_{item['row_key']}", "Use TCG fallback")
            if selected_label == "Use TCG fallback":
                match_overrides.pop(item["row_key"], None)
                continue
            selected_option = next((option for option in item["options"] if option["label"] == selected_label), None)
            if not selected_option:
                continue
            match_overrides[item["row_key"]] = {
                "price": selected_option["price"],
                "label": selected_option["label"],
                "reason": selected_option.get("reason", f"Mana Pool manual override: {selected_option['label']}"),
            }

        source_bytes = st.session_state.get("optimizer_source_bytes")
        if not source_bytes:
            st.error("The original TCGPlayer CSV is no longer in session. Please upload it again and regenerate.")
            return

        run_optimizer(
            tcgplayer_bytes=source_bytes,
            settings=settings,
            manapool_api_key=manapool_api_key,
            manapool_email=manapool_email,
            match_overrides=match_overrides,
        )
        st.rerun()


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
    manapool_api_key = get_manapool_api_key()
    manapool_email = get_manapool_email()

    st.title("Card Marketplace Listing Optimizer")
    st.caption(f"Compare TCGPlayer Direct vs Manapool and generate optimized listing sheets. App version {APP_VERSION}.")
    st.info("TCGPlayer Direct fees are built into the app: under $2.50 the net is 50% of item value, and at $2.50 or higher the fee model is $1.12 + 8.95% + 2.5%.")
    st.success("Mana Pool pricing now assumes Near Mint nonfoil by default, uses Near Mint Foil pricing only when the TCGPlayer condition says foil, and treats The List Reprints as PLST during set matching.")

    with st.expander("Mana Pool Credential Diagnostics"):
        diagnostics_df = pd.DataFrame(
            [
                {"Check": "App version", "Status": APP_VERSION},
                {"Check": "Mana Pool lookup mode", "Status": "Official API /card_info + NM singles pricing"},
                {"Check": "Mana Pool email loaded", "Status": "Yes" if bool(manapool_email) else "No"},
                {"Check": "Mana Pool email looks like an email", "Status": "Yes" if bool(manapool_email and "@" in manapool_email) else "No"},
                {"Check": "Mana Pool API token loaded", "Status": "Yes" if bool(manapool_api_key) else "No"},
                {"Check": "Mana Pool API token has visible length", "Status": "Yes" if bool(manapool_api_key and len(manapool_api_key.strip()) >= 8) else "No"},
            ]
        )
        st.dataframe(diagnostics_df, width="stretch", hide_index=True)
        st.caption("This panel only shows safe yes/no checks and the current app version. It does not reveal your email or API token.")

    st.markdown('<div class="upload-panel">', unsafe_allow_html=True)
    tcgplayer_file = st.file_uploader("Upload TCGPlayer CSV export", type=["csv"])
    generate_clicked = st.button("Generate Listing Sheets", type="primary", width="stretch")
    st.markdown("</div>", unsafe_allow_html=True)

    if generate_clicked:
        if tcgplayer_file is None:
            st.error("Please upload the TCGPlayer CSV export.")
            return

        try:
            run_optimizer(
                tcgplayer_bytes=tcgplayer_file.getvalue(),
                settings=settings,
                manapool_api_key=manapool_api_key,
                manapool_email=manapool_email,
                match_overrides={},
            )
        except Exception as exc:
            st.error(f"Processing failed: {exc}")
            return

    stored_result = st.session_state.get("optimizer_result")
    stored_workbook_bytes = st.session_state.get("optimizer_workbook_bytes")
    stored_timestamp = st.session_state.get("optimizer_timestamp")

    if not stored_result or not stored_workbook_bytes or not stored_timestamp:
        st.info("Upload your TCGPlayer CSV, adjust any settings you want in the sidebar, and generate the workbook.")
        return

    result = pickle.loads(stored_result)
    render_result(
        result=result,
        workbook_bytes=stored_workbook_bytes,
        timestamp=stored_timestamp,
    )
    render_manual_resolution_panel(
        result=result,
        settings=settings,
        manapool_api_key=manapool_api_key,
        manapool_email=manapool_email,
    )


if __name__ == "__main__":
    main()
