"""
dashboard.py — Optional Streamlit dashboard for the Finance Email Agent.

Run with:
    streamlit run dashboard.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from datetime import datetime

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Finance Email Agent",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
        padding: 2rem;
        border-radius: 12px;
        margin-bottom: 2rem;
        color: white;
    }
    .metric-card {
        background: #f8f9fa;
        border-left: 4px solid #0f3460;
        padding: 1rem;
        border-radius: 8px;
    }
    .stage-1 { color: #28a745; font-weight: bold; }
    .stage-2 { color: #ffc107; font-weight: bold; }
    .stage-3 { color: #fd7e14; font-weight: bold; }
    .stage-4 { color: #dc3545; font-weight: bold; }
    .escalated { color: #6f42c1; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="main-header">
    <h1>💼 Finance Credit Follow-Up Email Agent</h1>
    <p style="opacity:0.8;margin:0;">AI-powered accounts receivable automation | Claude Sonnet 4 + LangGraph</p>
</div>
""", unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Configuration")

    csv_path = st.text_input("Invoice CSV Path", value="data/invoices.csv")
    dry_run = st.toggle("Dry Run Mode (no real emails)", value=True)

    if dry_run:
        st.success("🔒 Dry run — no real emails will be sent")
    else:
        st.warning("🚀 Live mode — emails WILL be sent!")

    st.divider()
    st.markdown("**Quick Actions**")
    run_all = st.button("▶ Run Agent on All Invoices", type="primary", use_container_width=True)
    show_audit = st.button("📋 Refresh Audit Log", use_container_width=True)

    st.divider()
    st.markdown("**API Status**")
    if os.getenv("ANTHROPIC_API_KEY"):
        st.success("✓ Anthropic API key loaded")
    else:
        st.error("✗ ANTHROPIC_API_KEY missing")

# ── Load invoices ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=30)
def get_invoices(path: str):
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from agent.data_loader import load_invoices
        return load_invoices(path)
    except Exception as e:
        return None, str(e)


# ── Main content ──────────────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["📋 Invoice Queue", "📊 Audit Log", "📧 Email Preview"])

with tab1:
    st.subheader("Overdue Invoice Queue")

    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from agent.data_loader import load_invoices
        from agent.models import FollowUpStage

        invoices = load_invoices(csv_path)

        # Summary metrics
        col1, col2, col3, col4, col5 = st.columns(5)
        stage_counts = {}
        for inv in invoices:
            s = inv.get_stage().value
            stage_counts[s] = stage_counts.get(s, 0) + 1

        with col1:
            st.metric("Total Overdue", len(invoices))
        with col2:
            st.metric("🟢 Stage 1 (Warm)", stage_counts.get("stage_1", 0))
        with col3:
            st.metric("🟡 Stage 2 (Firm)", stage_counts.get("stage_2", 0))
        with col4:
            st.metric("🟠 Stage 3 (Formal)", stage_counts.get("stage_3", 0))
        with col5:
            st.metric("🔴 Stage 4 + Escalated",
                      stage_counts.get("stage_4", 0) + stage_counts.get("escalated", 0))

        # Invoice table
        df_data = []
        for inv in invoices:
            stage = inv.get_stage()
            stage_labels = {
                "stage_1": "🟢 Stage 1 — Warm",
                "stage_2": "🟡 Stage 2 — Firm",
                "stage_3": "🟠 Stage 3 — Formal",
                "stage_4": "🔴 Stage 4 — Urgent",
                "escalated": "🚨 ESCALATED",
            }
            df_data.append({
                "Invoice #": inv.invoice_no,
                "Client": inv.client_name,
                "Email": inv.client_email,
                "Amount": inv.formatted_amount(),
                "Due Date": str(inv.due_date),
                "Days Overdue": inv.days_overdue,
                "Stage": stage_labels.get(stage.value, stage.value),
                "Follow-ups Sent": inv.follow_up_count,
            })

        df = pd.DataFrame(df_data)
        st.dataframe(df, use_container_width=True, hide_index=True)

        # Single invoice run
        st.divider()
        st.subheader("Run Single Invoice")
        invoice_options = [inv.invoice_no for inv in invoices]
        selected = st.selectbox("Select Invoice", invoice_options)
        if st.button("Generate & Send Selected Invoice"):
            os.environ["DRY_RUN"] = "true" if dry_run else "false"
            from agent.email_generator import generate_email
            from agent.email_sender import send_email
            from agent.audit_logger import log_action
            record = next(i for i in invoices if i.invoice_no == selected)
            with st.spinner("Generating email with Claude..."):
                generated, is_escalated = generate_email(record)
            if is_escalated:
                st.error(f"⚠️ {selected} is escalated — flagged for legal review.")
            elif generated:
                st.success(f"✓ Email generated!")
                st.markdown(f"**Subject:** {generated.subject}")
                st.text_area("Body", generated.body, height=250)
                success, status = send_email(record, generated)
                log_action(record, generated, status)
                st.info(f"Status: {status}")

    except Exception as e:
        st.error(f"Error loading invoices: {e}")

with tab2:
    st.subheader("📊 Audit Trail")
    audit_path = Path(os.getenv("AUDIT_LOG_PATH", "logs/audit_log.jsonl"))

    if audit_path.exists():
        entries = []
        with open(audit_path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        pass

        if entries:
            df_audit = pd.DataFrame(entries)
            df_audit["timestamp"] = pd.to_datetime(df_audit["timestamp"]).dt.strftime("%Y-%m-%d %H:%M")

            # Summary
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Actions", len(entries))
            with col2:
                sent = sum(1 for e in entries if e.get("send_status") in ("sent", "dry_run"))
                st.metric("Sent / Simulated", sent)
            with col3:
                esc = sum(1 for e in entries if e.get("send_status") == "escalated")
                st.metric("Escalated", esc)

            display_cols = ["timestamp", "invoice_no", "client_name", "stage", "send_status", "subject"]
            available = [c for c in display_cols if c in df_audit.columns]
            st.dataframe(df_audit[available], use_container_width=True, hide_index=True)
        else:
            st.info("No audit entries yet. Run the agent to generate entries.")
    else:
        st.info("No audit log file found. Run the agent first.")

    if run_all:
        with st.spinner("Running agent on all invoices..."):
            os.environ["DRY_RUN"] = "true" if dry_run else "false"
            from agent.orchestrator import run_agent
            results = run_agent()
        st.success(f"✓ Processed {len(results)} invoice(s).")
        st.rerun()

with tab3:
    st.subheader("📧 Email Stage Preview")
    st.markdown("""
    Below are example emails for each escalation stage, generated by the agent.
    """)

    stages = {
        "Stage 1 — Warm & Friendly (1–7 days)": {
            "subject": "Quick Reminder – Invoice #INV-2024-001 | ₹45,000 Due",
            "body": """Hi Rajesh,

I hope you're doing well! This is a friendly reminder that Invoice #INV-2024-001 for ₹45,000 was due on 20 Apr 2025.

If you have already processed this payment, please disregard this message — and thank you!

If not, you can complete the payment using the secure link below:
👉 https://pay.example.com/inv-2024-001

Please feel free to reach out if you have any questions.

Warm regards,
Finance Team | Your Company Pvt Ltd""",
            "color": "#d4edda",
        },
        "Stage 2 — Polite but Firm (8–14 days)": {
            "subject": "Payment Follow-Up – Invoice #INV-2024-001 | ₹45,000 Still Pending",
            "body": """Dear Rajesh,

We hope this message finds you well. We wanted to follow up on Invoice #INV-2024-001 for ₹45,000, which was due on 20 Apr 2025 and remains unpaid — now 12 days overdue.

We would appreciate it if you could confirm the payment status or let us know if there are any issues we can help resolve.

Payment can be made here: https://pay.example.com/inv-2024-001

Thank you for your prompt attention.

Best regards,
Finance Team | Your Company Pvt Ltd""",
            "color": "#fff3cd",
        },
        "Stage 3 — Formal & Serious (15–21 days)": {
            "subject": "IMPORTANT: Outstanding Payment – Invoice #INV-2024-001 (18 Days Overdue)",
            "body": """Dear Mr. Kapoor,

Despite our previous reminders, Invoice #INV-2024-001 for ₹45,000 remains unpaid as of today — now 18 days overdue.

We request your immediate attention to this matter. Continued non-payment may impact your credit terms with us and could necessitate further action.

Please respond within 48 hours confirming your payment or providing an expected payment date.

Payment Link: https://pay.example.com/inv-2024-001
Contact: finance@company.com | +91-XXXXX-XXXXX

Regards,
Finance Department | Your Company Pvt Ltd""",
            "color": "#fde8d8",
        },
        "Stage 4 — Stern & Urgent (22–30 days)": {
            "subject": "FINAL NOTICE – Invoice #INV-2024-001 – Immediate Action Required",
            "body": """Dear Mr. Kapoor,

This is our final reminder. Invoice #INV-2024-001 for ₹45,000 is now 26 days overdue, despite multiple attempts to resolve this matter.

Failure to remit full payment within 24 hours of this notice will result in escalation to our legal and recovery team, which may affect your credit standing and result in additional costs.

Please act immediately:
Payment Link: https://pay.example.com/inv-2024-001
Emergency Contact: +91-XXXXX-XXXXX

Your Company Pvt Ltd Finance Department""",
            "color": "#f8d7da",
        },
    }

    for stage_name, content in stages.items():
        with st.expander(stage_name):
            st.markdown(
                f"""<div style="background:{content['color']};padding:1rem;border-radius:8px;">
                <strong>Subject:</strong> {content['subject']}<br><br>
                <pre style="white-space:pre-wrap;font-family:inherit;">{content['body']}</pre>
                </div>""",
                unsafe_allow_html=True,
            )
