"""
Streamlit Invoice Processing App
Hosted on: AWS App Runner
Tabs:
  1. Upload invoices → S3
  2. Dashboard → read from DynamoDB
"""

import io
import os
from datetime import datetime
from decimal import Decimal

import boto3
import pandas as pd
import streamlit as st
from boto3.dynamodb.conditions import Attr

# ── Config ────────────────────────────────────────────────────────────────────
S3_BUCKET      = "invoice-uploads"
S3_PREFIX      = "raw/"
DYNAMODB_TABLE = "invoices"
AWS_REGION     = os.environ.get("AWS_REGION", "us-east-1")

# ── AWS Clients ───────────────────────────────────────────────────────────────
s3_client = boto3.client("s3", region_name=AWS_REGION)
dynamodb  = boto3.resource("dynamodb", region_name=AWS_REGION)
table     = dynamodb.Table(DYNAMODB_TABLE)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Invoice Processing System",
    page_icon="🧾",
    layout="wide",
)

st.title("🧾 Invoice Processing System")
st.markdown("Powered by **Amazon Textract + Bedrock (Llama 3.1) + DynamoDB**")
st.divider()

tab1, tab2 = st.tabs(["📤 Upload Invoices", "📊 Dashboard"])


# ═════════════════════════════════════════════════════════════════════════════
# TAB 1 — UPLOAD
# ═════════════════════════════════════════════════════════════════════════════
with tab1:
    st.header("Upload Invoices")
    st.info(
        "Upload PDF or image invoices. They will be stored in S3 and automatically "
        "processed by the AI pipeline (Textract → Bedrock → DynamoDB)."
    )

    uploaded_files = st.file_uploader(
        "Choose invoice files",
        type=["pdf", "png", "jpg", "jpeg", "tiff"],
        accept_multiple_files=True,
    )

    if uploaded_files:
        st.write(f"**{len(uploaded_files)} file(s) selected:**")
        for f in uploaded_files:
            st.write(f"- {f.name} ({round(f.size / 1024, 1)} KB)")

    if st.button("🚀 Upload to S3", disabled=not uploaded_files):
        results = []
        progress = st.progress(0)

        for idx, uploaded_file in enumerate(uploaded_files):
            s3_key = f"{S3_PREFIX}{uploaded_file.name}"
            try:
                s3_client.upload_fileobj(
                    io.BytesIO(uploaded_file.read()),
                    S3_BUCKET,
                    s3_key,
                    ExtraArgs={"ContentType": uploaded_file.type},
                )
                results.append({"file": uploaded_file.name, "status": "✅ Uploaded", "s3_key": s3_key})
            except Exception as e:
                results.append({"file": uploaded_file.name, "status": f"❌ Failed: {e}", "s3_key": "-"})

            progress.progress((idx + 1) / len(uploaded_files))

        st.success("Upload complete!")
        st.dataframe(pd.DataFrame(results), use_container_width=True)
        st.info("🔄 The AI pipeline will process your invoices in the background. Check the Dashboard tab in ~30 seconds.")


# ═════════════════════════════════════════════════════════════════════════════
# TAB 2 — DASHBOARD
# ═════════════════════════════════════════════════════════════════════════════
with tab2:
    st.header("Invoice Dashboard")

    # ── Refresh button ────────────────────────────────────────────────────────
    col_refresh, col_spacer = st.columns([1, 5])
    with col_refresh:
        refresh = st.button("🔄 Refresh")

    # ── Fetch all invoices from DynamoDB ──────────────────────────────────────
    @st.cache_data(ttl=30, show_spinner="Loading invoices...")
    def fetch_invoices():
        items = []
        response = table.scan()
        items.extend(response.get("Items", []))
        # Handle pagination
        while "LastEvaluatedKey" in response:
            response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
            items.extend(response.get("Items", []))
        return items

    if refresh:
        st.cache_data.clear()

    try:
        invoices = fetch_invoices()
    except Exception as e:
        st.error(f"Could not load invoices from DynamoDB: {e}")
        invoices = []

    if not invoices:
        st.warning("No invoices found yet. Upload some invoices first!")
        st.stop()

    # ── Convert Decimal → float for display ───────────────────────────────────
    def clean(val):
        if isinstance(val, Decimal):
            return float(val)
        return val

    def clean_item(item: dict) -> dict:
        return {k: clean(v) for k, v in item.items() if k != "line_items"}

    df = pd.DataFrame([clean_item(i) for i in invoices])

    # ── KPI Cards ─────────────────────────────────────────────────────────────
    st.subheader("📈 Summary")
    k1, k2, k3, k4 = st.columns(4)

    total_invoices = len(df)
    total_amount   = df["total_amount"].sum() if "total_amount" in df.columns else 0
    avg_amount     = df["total_amount"].mean() if "total_amount" in df.columns else 0
    unique_vendors = df["vendor"].nunique() if "vendor" in df.columns else 0

    k1.metric("Total Invoices",   total_invoices)
    k2.metric("Total Amount",     f"${total_amount:,.2f}")
    k3.metric("Average Invoice",  f"${avg_amount:,.2f}")
    k4.metric("Unique Vendors",   unique_vendors)

    st.divider()

    # ── Filters ───────────────────────────────────────────────────────────────
    st.subheader("🔍 Filter & Search")
    f1, f2, f3 = st.columns(3)

    with f1:
        search_vendor = st.text_input("Search by vendor", "")
    with f2:
        status_filter = st.selectbox("Status", ["All", "processed", "failed"])
    with f3:
        sort_col = st.selectbox("Sort by", ["processed_at", "total_amount", "date", "vendor"])

    filtered = df.copy()
    if search_vendor:
        filtered = filtered[filtered["vendor"].str.contains(search_vendor, case=False, na=False)]
    if status_filter != "All" and "status" in filtered.columns:
        filtered = filtered[filtered["status"] == status_filter]
    if sort_col in filtered.columns:
        filtered = filtered.sort_values(sort_col, ascending=False)

    st.divider()

    # ── Invoice Table ─────────────────────────────────────────────────────────
    st.subheader(f"📋 Invoices ({len(filtered)} records)")

    display_cols = [c for c in ["invoice_id", "vendor", "date", "due_date", "total_amount", "currency", "status", "processed_at"] if c in filtered.columns]
    st.dataframe(
        filtered[display_cols].reset_index(drop=True),
        use_container_width=True,
        column_config={
            "total_amount": st.column_config.NumberColumn("Total Amount", format="$%.2f"),
            "processed_at": st.column_config.TextColumn("Processed At"),
        },
    )

    # ── Charts ────────────────────────────────────────────────────────────────
    st.divider()
    st.subheader("📊 Analytics")

    c1, c2 = st.columns(2)

    with c1:
        st.markdown("**Spend by Vendor**")
        if "vendor" in df.columns and "total_amount" in df.columns:
            vendor_spend = (
                df.groupby("vendor")["total_amount"]
                .sum()
                .sort_values(ascending=False)
                .head(10)
                .reset_index()
            )
            st.bar_chart(vendor_spend.set_index("vendor"))

    with c2:
        st.markdown("**Invoice Status Distribution**")
        if "status" in df.columns:
            status_counts = df["status"].value_counts().reset_index()
            status_counts.columns = ["status", "count"]
            st.bar_chart(status_counts.set_index("status"))

    # ── Line Items Detail ─────────────────────────────────────────────────────
    st.divider()
    st.subheader("🔎 Invoice Detail")
    invoice_ids = df["invoice_id"].tolist() if "invoice_id" in df.columns else []
    selected_id = st.selectbox("Select an invoice to view line items", options=["—"] + invoice_ids)

    if selected_id and selected_id != "—":
        match = [i for i in invoices if str(i.get("invoice_id")) == str(selected_id)]
        if match:
            inv = match[0]
            c_left, c_right = st.columns(2)
            with c_left:
                st.json({k: str(v) for k, v in inv.items() if k != "line_items"})
            with c_right:
                line_items = inv.get("line_items", [])
                if line_items:
                    st.markdown("**Line Items**")
                    li_df = pd.DataFrame([{k: float(v) if isinstance(v, Decimal) else v for k, v in li.items()} for li in line_items])
                    st.dataframe(li_df, use_container_width=True)
                else:
                    st.info("No line items recorded.")
