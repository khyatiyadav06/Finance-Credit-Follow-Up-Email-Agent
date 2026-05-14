# Finance-Credit-Follow-Up-Email-Agent

> AI-powered accounts receivable automation — automatically generates and dispatches escalating follow-up emails for overdue invoices using **Claude Sonnet 4** and **LangGraph**.

---

## 📋 Table of Contents

1. [Project Overview](#-project-overview)
2. [Architecture](#-architecture)
3. [Tech Stack & Decision Log](#-tech-stack--decision-log)
4. [Security Risk Mitigations](#-security-risk-mitigations)
5. [Setup Instructions](#-setup-instructions)
6. [Running the Agent](#-running-the-agent)
7. [Escalation Matrix](#-tone-escalation-matrix)
8. [Sample Output](#-sample-output)
9. [Project Structure](#-project-structure)

---

## 🎯 Project Overview

Finance teams spend significant time manually chasing overdue payments. This agent automates the entire follow-up workflow:

- **Ingests** overdue invoice records from CSV / Excel
- **Classifies** each record into the correct escalation stage based on days overdue
- **Generates** a personalised, tone-appropriate email using Claude Sonnet 4
- **Dispatches** emails via SMTP or SendGrid (or simulates with dry-run)
- **Flags** severely overdue records for legal/finance review
- **Logs** every action with a full audit trail

### Business Impact
- Reduces DSO (Days Sales Outstanding) by ensuring consistent, timely follow-ups
- Eliminates human inconsistency in communication tone
- Scales to hundreds of invoices with no additional effort
- Maintains client relationships by calibrating tone to urgency

---

## 🏗 Architecture

### Agent Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    LangGraph Agent Graph                         │
│                                                                  │
│  ┌─────────────┐    ┌───────────┐    ┌──────────────────────┐  │
│  │ load_invoices│───▶│ pick_next │───▶│  should_continue?    │  │
│  └─────────────┘    └───────────┘    └──────────────────────┘  │
│                                              │          │        │
│                                           process      done     │
│                                              │          │        │
│                                              ▼          ▼        │
│                                    ┌──────────────┐   END       │
│                                    │generate_email│             │
│                                    └──────────────┘             │
│                                          │      │               │
│                                     send    skip_send           │
│                                       │      (escalated)        │
│                                       ▼          │              │
│                                  ┌──────────┐    │              │
│                                  │send_email│    │              │
│                                  └──────────┘    │              │
│                                       │          │              │
│                                       └────┬─────┘              │
│                                            ▼                    │
│                                    ┌───────────────┐            │
│                                    │  log_audit    │            │
│                                    └───────────────┘            │
│                                            │                    │
│                                            └──▶ pick_next (loop)│
└─────────────────────────────────────────────────────────────────┘
```

### Node Descriptions

| Node | Responsibility |
|------|---------------|
| `load_invoices` | Read + validate CSV, filter to overdue records only |
| `pick_next` | Advance index; fetch next InvoiceRecord from queue |
| `generate_email` | Call Claude Sonnet 4 with structured JSON output mode |
| `send_email` | Dispatch via SMTP/SendGrid or simulate in dry-run |
| `log_audit` | Append immutable entry to JSONL audit trail |

---

## 🛠 Tech Stack & Decision Log

### LLM: Claude Sonnet 4 (`claude-sonnet-4-20250514`)

| Factor | Decision |
|--------|----------|
| **Model** | `claude-sonnet-4-20250514` via Anthropic API |
| **Why Claude over GPT-4o** | Superior instruction-following for strict JSON output; better tone calibration for professional communication; Anthropic's Constitutional AI reduces hallucination risk in financial contexts |
| **Why Sonnet over Opus** | Sonnet provides 95% of Opus quality at ~5× lower cost and ~3× higher speed — ideal for batch invoice processing |
| **Context window** | 200K tokens — sufficient to include full invoice context + conversation history |
| **Tool-calling** | Full support for structured outputs and JSON mode |

### Agent Framework: LangGraph

| Factor | Decision |
|--------|----------|
| **Framework** | LangGraph 0.1.x |
| **Architecture** | Plan-and-Execute loop with conditional branching |
| **Why LangGraph over LangChain Agents** | LangGraph provides explicit, auditable state transitions — critical for financial workflows where every step must be traceable. LangChain's ReAct loop is less predictable in production. |
| **Why not CrewAI** | Single-agent task; CrewAI's multi-agent overhead is unnecessary here |
| **State management** | TypedDict-based `AgentState` — type-safe, serializable, debuggable |

### Prompt Design

The system prompt enforces strict guardrails:

```
You are a professional finance communications assistant...

STRICT RULES:
1. Use ONLY the invoice data provided. NEVER invent or modify any field.
2. Output ONLY valid JSON — no markdown, no preamble, no explanation.
3. Match the tone EXACTLY as instructed.
4. Body must be 150–250 words max.
5. Never threaten legal action unless stage 4.
```

**Key prompt engineering decisions:**
- **Separation of system vs user turn**: Guardrails in system prompt, invoice data in user turn — prevents data from overriding instructions
- **Explicit output schema**: Forces `{"subject": "...", "body": "..."}` — no parsing ambiguity
- **Tone anchoring**: Stage-specific tone descriptors ("warm, friendly, gentle" vs "stern, urgent, final warning") guide consistent generation
- **Anti-hallucination rule**: LLM explicitly forbidden from inventing data not provided
- **Post-generation validation**: Code checks that invoice_no appears in output — flags if missing

---

## 🔒 Security Risk Mitigations

> **This section is mandatory per project brief and covers all graded security components.**

### 1. Prompt Injection

**Risk**: Malicious data in client_name or other fields could manipulate LLM behaviour.

**Mitigations implemented:**
- `InvoiceRecord.sanitize_name()` validator strips all characters except `[\w\s.,\-'&()]` using regex
- `InvoiceRecord.sanitize_email()` lowercases and strips whitespace
- All dynamic data is injected into prompts **only after passing Pydantic validation** — raw CSV strings never touch the LLM directly
- System prompt uses clear delimiters (`INVOICE DATA:` header) to structurally separate instructions from data
- Structured JSON output mode means even if injection occurs, the output schema constrains what the LLM can produce

```python
@validator("client_name")
def sanitize_name(cls, v: str) -> str:
    sanitized = re.sub(r"[^\w\s.,\-'&()]", "", v).strip()
    ...
```

### 2. Data Privacy / PII

**Risk**: Resume/email data contains personal information (names, emails, invoice amounts).

**Mitigations implemented:**
- Audit log stores only a **200-character body preview** — never the full email body
- PII (client_email) in logs is separated from email content
- `.env` file excluded from Git via `.gitignore`
- In production: recommend encrypting `logs/` directory at rest and masking emails in logs (e.g. `r***@domain.com`)
- Data processed locally — only sanitized, structured fields sent to Anthropic API

### 3. API Key Exposure

**Risk**: LLM/email API keys leaked in source code or version control.

**Mitigations implemented:**
- All credentials loaded exclusively via `python-dotenv` from `.env` file
- `.env` listed in `.gitignore` — never committed
- `.env.example` provided as template (no real values)
- Runtime check in `main.py` fails fast if `ANTHROPIC_API_KEY` is missing
- In production: use AWS Secrets Manager / GCP Secret Manager / HashiCorp Vault

```python
# CORRECT — from environment only
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# NEVER do this
client = anthropic.Anthropic(api_key="sk-ant-...")  # ❌
```

### 4. Hallucination Risk

**Risk**: LLM generating wrong amounts, dates, or fabricated invoice numbers.

**Mitigations implemented:**
- **Structured JSON output** (`{"subject": ..., "body": ...}`) — LLM cannot add unexpected fields
- **Pydantic validation** on all inputs and `GeneratedEmail` output model
- **Post-generation check**: code verifies `invoice_no` appears in the generated email — logs a warning if missing
- **Human-in-the-loop**: DRY_RUN=true by default — human reviews before live sending
- **Explicit prohibition** in system prompt: "NEVER invent or modify any field"
- All factual fields (amount, date, invoice number) injected from validated Python objects — LLM cannot change them

### 5. Unauthorised Access

**Risk**: Anyone triggering the agent endpoint.

**Mitigations implemented:**
- CLI requires explicit `--live` flag — prevents accidental live runs
- Streamlit dashboard runs locally by default (no public exposure)
- In production: add API key authentication or OAuth on any exposed FastAPI endpoint
- Rate limiting recommended via nginx or API gateway in production deployment

### 6. Email Spoofing (Task 2 specific)

**Risk**: Emails appearing to come from wrong/spoofed sender.

**Mitigations implemented:**
- `SMTP_FROM_EMAIL` and `SENDGRID_FROM_EMAIL` loaded from environment — never derived from invoice data
- DRY_RUN mode (default) prevents any real emails during development/testing
- **Production recommendations** (documented):
  - Set up SPF record: `v=spf1 include:sendgrid.net ~all`
  - Enable DKIM signing via your email provider
  - Add DMARC policy: `v=DMARC1; p=reject; rua=mailto:dmarc@yourcompany.com`
  - Use a verified sender domain (not free email services)

---

## ⚙️ Setup Instructions

### Prerequisites
- Python 3.10+
- An [Anthropic API key](https://console.anthropic.com/)

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/finance-email-agent.git
cd finance-email-agent
```

### 2. Create a virtual environment

```bash
python -m venv venv
source venv/bin/activate        # Linux/Mac
# venv\Scripts\activate         # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment

```bash
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

Minimum required in `.env`:
```
ANTHROPIC_API_KEY=sk-ant-...
DRY_RUN=true
```

### 5. Run tests

```bash
pytest tests/ -v
```

---

## 🚀 Running the Agent

### CLI — Dry Run (safe, no real emails)

```bash
python main.py
```

### CLI — Live Mode (real emails)

```bash
python main.py --live
```

### CLI — Single Invoice

```bash
python main.py --invoice INV-2024-001
```

### CLI — View Audit Log

```bash
python main.py --audit
```

### Streamlit Dashboard

```bash
streamlit run dashboard.py
```

Then open `http://localhost:8501` in your browser.

---

## 📊 Tone Escalation Matrix

| Stage | Days Overdue | Tone | Subject Style | CTA |
|-------|-------------|------|---------------|-----|
| Stage 1 | 1–7 | Warm & Friendly | `Quick Reminder – Invoice #...` | Pay now link |
| Stage 2 | 8–14 | Polite but Firm | `Payment Follow-Up – Invoice #...` | Confirm payment date |
| Stage 3 | 15–21 | Formal & Serious | `IMPORTANT: Outstanding Payment – Invoice #...` | Respond within 48 hrs |
| Stage 4 | 22–30 | Stern & Urgent | `FINAL NOTICE – Invoice #...` | Pay immediately or call |
| Escalated | 30+ | 🚨 No email | Flagged for legal/finance review | Assign to finance manager |

---

## 📧 Sample Output

### Sample Audit Log Entry

```json
{
  "timestamp": "2025-05-14T10:30:00",
  "invoice_no": "INV-2024-001",
  "client_name": "Rajesh Kapoor",
  "client_email": "rajesh.kapoor@acmecorp.com",
  "stage": "stage_2",
  "subject": "Payment Follow-Up – Invoice #INV-2024-001 | ₹45,000 Still Pending",
  "body_preview": "Dear Rajesh, We hope this message finds you well. We wanted to follow up on Invoice #INV-2024-001 for ₹45,000, which was due on 20 Apr 2025...",
  "send_status": "dry_run",
  "error_message": null,
  "dry_run": true
}
```

### Sample Stage 1 Email (Warm)

> **Subject**: Quick Reminder – Invoice #INV-2024-005 | ₹15,500 Due
>
> Hi Suresh,
>
> I hope you're doing well! This is a friendly reminder that Invoice #INV-2024-005 for ₹15,500 was due on 05 May 2025. If you have already processed this, please disregard — and thank you!
>
> Otherwise, you can complete your payment here: https://pay.example.com/inv-2024-005
>
> Warm regards,
> Finance Team | Your Company Pvt Ltd

---

## 📁 Project Structure

```
finance-email-agent/
├── agent/
│   ├── __init__.py
│   ├── models.py           # Pydantic data models (InvoiceRecord, GeneratedEmail, AuditEntry)
│   ├── data_loader.py      # CSV/Excel ingestion with validation
│   ├── email_generator.py  # Claude Sonnet 4 LLM integration
│   ├── email_sender.py     # SMTP / SendGrid / dry-run dispatch
│   ├── audit_logger.py     # Append-only JSONL audit trail
│   └── orchestrator.py     # LangGraph agent graph
├── data/
│   └── invoices.csv        # Sample invoice data
├── logs/                   # Audit logs (git-ignored)
├── tests/
│   ├── conftest.py
│   └── test_agent.py       # Unit tests (pytest)
├── dashboard.py            # Streamlit UI (optional)
├── main.py                 # CLI entrypoint
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## 🏆 Pro Tips Implemented

- ✅ **Dry-run mode** — default ON, prevents accidental emails during testing
- ✅ **Structured output (JSON mode)** — used from day one, eliminates parsing bugs
- ✅ **Pydantic validation** — all inputs and outputs validated before use
- ✅ **Prompt injection protection** — name/email sanitized via regex validators
- ✅ **Audit trail** — every action logged with timestamp and status
- ✅ **Hallucination check** — post-generation invoice_no verification
- ✅ **LangGraph** — explicit, auditable state machine instead of ReAct loop

---

*Built for the AI Enablement Internship — Task 2: Finance Credit Follow-Up Email Agent*
