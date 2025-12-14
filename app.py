import streamlit as st
import pdfplumber
import json
import pandas as pd
import re
from datetime import datetime
from io import BytesIO

# ---------------------------------------------------
# Import standalone parsers
# ---------------------------------------------------
from maybank import parse_transactions_maybank
from public_bank import parse_transactions_pbb
from rhb import parse_transactions_rhb
from cimb import parse_transactions_cimb
from bank_islam import parse_bank_islam


# ---------------------------------------------------
# Streamlit Setup
# ---------------------------------------------------
st.set_page_config(page_title="Bank Statement Parser", layout="wide")
st.title("📄 Bank Statement Parser (Multi-File Support)")
st.write("Upload one or more bank statement PDFs to extract transactions.")


# ---------------------------------------------------
# Session State
# ---------------------------------------------------
if "status" not in st.session_state:
    st.session_state.status = "idle"

if "results" not in st.session_state:
    st.session_state.results = []


# ---------------------------------------------------
# Bank Selection
# ---------------------------------------------------
bank_choice = st.selectbox(
    "Select Bank Format",
    ["Maybank", "Public Bank (PBB)", "RHB Bank", "CIMB Bank", "Bank Islam"]
)


# ---------------------------------------------------
# File Upload
# ---------------------------------------------------
uploaded_files = st.file_uploader(
    "Upload PDF files", type=["pdf"], accept_multiple_files=True
)

if uploaded_files:
    uploaded_files = sorted(uploaded_files, key=lambda x: x.name)


# ---------------------------------------------------
# Controls
# ---------------------------------------------------
col1, col2, col3 = st.columns(3)

with col1:
    if st.button("▶️ Start Processing"):
        st.session_state.status = "running"

with col2:
    if st.button("⏹️ Stop"):
        st.session_state.status = "stopped"

with col3:
    if st.button("🔄 Reset"):
        st.session_state.status = "idle"
        st.session_state.results = []
        st.rerun()

st.write(f"### ⚙️ Status: **{st.session_state.status.upper()}**")


# ---------------------------------------------------
# MAIN PROCESSING
# ---------------------------------------------------
all_tx = []

if uploaded_files and st.session_state.status == "running":

    progress_bar = st.progress(0)
    total_files = len(uploaded_files)

    for idx, uploaded_file in enumerate(uploaded_files):

        if st.session_state.status == "stopped":
            st.warning("⏹️ Processing stopped.")
            break

        st.write(f"### 🗂️ Processing **{uploaded_file.name}**")

        try:
            with pdfplumber.open(uploaded_file) as pdf:

                tx = []

                if bank_choice == "Maybank":
                    tx = parse_transactions_maybank(pdf, uploaded_file.name)

                elif bank_choice == "Public Bank (PBB)":
                    tx = parse_transactions_pbb(pdf, uploaded_file.name)

                elif bank_choice == "RHB Bank":
                    tx = parse_transactions_rhb(pdf, uploaded_file.name)

                elif bank_choice == "CIMB Bank":
                    tx = parse_transactions_cimb(pdf, uploaded_file.name)

                elif bank_choice == "Bank Islam":
                    tx = parse_bank_islam(pdf, uploaded_file.name)

                if tx:
                    st.success(f"✅ {len(tx)} transactions extracted")
                    all_tx.extend(tx)
                else:
                    st.warning("⚠️ No transactions found")

        except Exception as e:
            st.error(f"❌ Error: {e}")

        progress_bar.progress((idx + 1) / total_files)

    st.session_state.results = all_tx


# ---------------------------------------------------
# MONTHLY SUMMARY (BANK ISLAM SAFE)
# ---------------------------------------------------
def calculate_monthly_summary(transactions):

    if not transactions:
        return []

    df = pd.DataFrame(transactions)

    df['date'] = df['date'].astype(str).str.strip()

    # -------------------------------
    # 🔒 FIX BANK ISLAM BROKEN DATES
    # -------------------------------
    if 'bank' in df.columns:
        mask = df['bank'] == 'Bank Islam'

        def fix_bank_islam_date(val):
            """
            Fix:
            2025 16:00:26-03-13
            → 2025-03-13 16:00:26
            """
            m = re.match(
                r'(\d{4})\s+(\d{2}:\d{2}:\d{2})-(\d{2})-(\d{2})',
                val
            )
            if m:
                y, t, mth, d = m.groups()
                return f"{y}-{mth}-{d} {t}"
            return val

        df.loc[mask, 'date'] = df.loc[mask, 'date'].apply(fix_bank_islam_date)

    # -------------------------------
    # Parse datetime
    # -------------------------------
    df['date_parsed'] = pd.to_datetime(df['date'], errors='coerce')
    df = df[df['date_parsed'].notna()]

    if df.empty:
        st.warning("⚠️ No valid dates.")
        return []

    # -------------------------------
    # Month grouping (NO .dt)
    # -------------------------------
    df['month_period'] = df['date_parsed'].apply(
        lambda d: f"{d.year:04d}-{d.month:02d}"
    )

    # -------------------------------
    # Amount cleanup
    # -------------------------------
    df['debit'] = pd.to_numeric(df['debit'], errors='coerce').fillna(0)
    df['credit'] = pd.to_numeric(df['credit'], errors='coerce').fillna(0)
    df['balance'] = pd.to_numeric(df['balance'], errors='coerce')

    summary = []

    for period, g in df.groupby('month_period', sort=True):
        g = g.sort_values('date_parsed')

        bal = g['balance'].dropna()
        ending_balance = round(bal.iloc[-1], 2) if not bal.empty else None

        summary.append({
            "month": period,
            "transaction_count": len(g),
            "total_debit": round(g['debit'].sum(), 2),
            "total_credit": round(g['credit'].sum(), 2),
            "net_change": round(g['credit'].sum() - g['debit'].sum(), 2),
            "ending_balance": ending_balance,
            "lowest_balance": round(g['balance'].min(), 2) if not g['balance'].isna().all() else None,
            "highest_balance": round(g['balance'].max(), 2) if not g['balance'].isna().all() else None,
            "source_files": ', '.join(sorted(g['source_file'].unique()))
        })

    return sorted(summary, key=lambda x: x['month'])


# ---------------------------------------------------
# DISPLAY RESULTS
# ---------------------------------------------------
if st.session_state.results:

    st.subheader("📊 Transactions")
    df = pd.DataFrame(st.session_state.results)

    cols = ["date", "description", "debit", "credit", "balance", "bank", "source_file"]
    st.dataframe(df[cols], use_container_width=True)

    monthly = calculate_monthly_summary(st.session_state.results)

    if monthly:
        st.subheader("📅 Monthly Summary")
        st.dataframe(pd.DataFrame(monthly), use_container_width=True)

else:
    if uploaded_files:
        st.warning("⚠️ Click **Start Processing**.")
