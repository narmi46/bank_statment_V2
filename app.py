import streamlit as st
import pdfplumber
import json
import pandas as pd
from datetime import datetime
from io import BytesIO

# Import standalone parsers
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
    st.session_state.status = "idle"    # idle, running, stopped

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
uploaded_files = st.file_uploader("Upload PDF files", type=["pdf"], accept_multiple_files=True)

# Sort uploaded files by name
if uploaded_files:
    uploaded_files = sorted(uploaded_files, key=lambda x: x.name)


# ---------------------------------------------------
# Start / Stop / Reset Controls
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
    
    bank_display_box = st.empty()
    progress_bar = st.progress(0)
    
    total_files = len(uploaded_files)
    
    for file_idx, uploaded_file in enumerate(uploaded_files):
        
        if st.session_state.status == "stopped":
            st.warning("⏹️ Processing stopped by user.")
            break
        
        st.write(f"### 🗂️ Processing File: **{uploaded_file.name}**")
        bank_display_box.info(f"📄 Processing {bank_choice}: {uploaded_file.name}...")
        
        try:
            with pdfplumber.open(uploaded_file) as pdf:
                
                # Call the appropriate standalone parser
                # Each parser now handles its own year extraction
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
                    st.success(f"✅ Extracted {len(tx)} transactions from {uploaded_file.name}")
                    all_tx.extend(tx)
                else:
                    st.warning(f"⚠️ No transactions found in {uploaded_file.name}")
        
        except Exception as e:
            st.error(f"❌ Error processing {uploaded_file.name}: {e}")
        
        # Update progress
        progress = (file_idx + 1) / total_files
        progress_bar.progress(progress)
    
    bank_display_box.success(f"🏦 Completed processing: **{bank_choice}**")
    st.session_state.results = all_tx


# ---------------------------------------------------
# CALCULATE MONTHLY SUMMARY
# ---------------------------------------------------
def calculate_monthly_summary(transactions):
    """
    Calculate monthly summary from transactions.
    Groups by year-month extracted from transaction dates.
    """
    if not transactions:
        return []
    
    df = pd.DataFrame(transactions)
    
    # Parse dates
    df['date_parsed'] = pd.to_datetime(df['date'], errors='coerce')
    df = df.dropna(subset=['date_parsed'])
    
    if df.empty:
        st.warning("⚠️ No valid transaction dates found.")
        return []
    
    # Create month grouping
    df['month_period'] = df['date_parsed'].dt.strftime('%Y-%m')
    
    # Convert amounts to numeric
    df['debit'] = pd.to_numeric(df['debit'], errors='coerce').fillna(0)
    df['credit'] = pd.to_numeric(df['credit'], errors='coerce').fillna(0)
    df['balance'] = pd.to_numeric(df['balance'], errors='coerce')
    
    monthly_summary = []
    
    for period, group in df.groupby('month_period', sort=True):
        # Get ending balance (last transaction's balance in the month)
        ending_balance = None
        if not group['balance'].isna().all():
            group_sorted = group.sort_values('date_parsed')
            last_balance = group_sorted['balance'].dropna().iloc[-1] if len(group_sorted['balance'].dropna()) > 0 else None
            ending_balance = round(last_balance, 2) if last_balance is not None else None
        
        summary = {
            'month': period,
            'total_debit': round(group['debit'].sum(), 2),
            'total_credit': round(group['credit'].sum(), 2),
            'net_change': round(group['credit'].sum() - group['debit'].sum(), 2),
            'ending_balance': ending_balance,
            'lowest_balance': round(group['balance'].min(), 2) if not group['balance'].isna().all() else None,
            'highest_balance': round(group['balance'].max(), 2) if not group['balance'].isna().all() else None,
            'transaction_count': len(group),
            'source_files': ', '.join(sorted(group['source_file'].unique())) if 'source_file' in group.columns else ''
        }
        monthly_summary.append(summary)
    
    return sorted(monthly_summary, key=lambda x: x['month'])


# ---------------------------------------------------
# DISPLAY RESULTS
# ---------------------------------------------------
if st.session_state.results:
    st.subheader("📊 Extracted Transactions")
    
    df = pd.DataFrame(st.session_state.results)
    
    # Display columns
    display_cols = ["date", "description", "debit", "credit", "balance", "page", "bank", "source_file"]
    display_cols = [c for c in display_cols if c in df.columns]
    
    df_display = df[display_cols]
    
    st.dataframe(df_display, use_container_width=True)
    
    # Monthly Summary
    monthly_summary = calculate_monthly_summary(st.session_state.results)
    
    if monthly_summary:
        st.subheader("📅 Monthly Summary")
        
        summary_df = pd.DataFrame(monthly_summary)
        
        summary_df = summary_df[[
            'month', 'transaction_count', 'total_debit', 'total_credit',
            'net_change', 'ending_balance', 'lowest_balance', 'highest_balance',
            'source_files'
        ]]
        
        st.dataframe(summary_df, use_container_width=True)
        
        # Metrics
        st.markdown("---")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Transactions", summary_df['transaction_count'].sum())
        with col2:
            st.metric("Total Debits", f"RM {summary_df['total_debit'].sum():,.2f}")
        with col3:
            st.metric("Total Credits", f"RM {summary_df['total_credit'].sum():,.2f}")
        with col4:
            net_total = summary_df['net_change'].sum()
            st.metric("Net Change", f"RM {net_total:,.2f}",
                     delta=f"{'Positive' if net_total > 0 else 'Negative'}")
    
    # Download Options
    st.subheader("⬇️ Download Options")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        json_transactions = json.dumps(df_display.to_dict(orient="records"), indent=4)
        st.download_button(
            "📄 Download Transactions (JSON)",
            json_transactions,
            file_name="transactions.json",
            mime="application/json"
        )
    
    with col2:
        full_report = {
            "summary": {
                "total_transactions": len(df),
                "date_range": f"{df['date'].min()} to {df['date'].max()}" if 'date' in df.columns else "N/A",
                "total_files_processed": df['source_file'].nunique() if 'source_file' in df.columns else 0
            },
            "monthly_summary": monthly_summary,
            "transactions": df_display.to_dict(orient="records")
        }
        json_full_report = json.dumps(full_report, indent=4)
        st.download_button(
            "📊 Download Full Report (JSON)",
            json_full_report,
            file_name="full_report.json",
            mime="application/json"
        )
    
    with col3:
        try:
            output = BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_display.to_excel(writer, sheet_name='Transactions', index=False)
                if monthly_summary:
                    pd.DataFrame(monthly_summary).to_excel(writer, sheet_name='Monthly Summary', index=False)
            
            excel_data = output.getvalue()
            st.download_button(
                "📊 Download Full Report (XLSX)",
                excel_data,
                file_name="full_report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        except ImportError:
            st.error("⚠️ xlsxwriter package not installed. Install with: pip install xlsxwriter")

else:
    if uploaded_files:
        st.warning("⚠️ No transactions found — click **Start Processing**.")
