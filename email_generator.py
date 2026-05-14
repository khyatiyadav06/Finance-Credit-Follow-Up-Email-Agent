"""
agent/email_generator.py — LLM-powered email generation using Claude via Anthropic API.

Design decisions:
- Uses claude-sonnet-4-20250514 for high-quality, nuanced tone variation.
- Structured JSON output mode prevents hallucination of invoice fields.
- System prompt uses strict guardrails and format constraints.
- All dynamic fields are injected from validated InvoiceRecord objects,
  never from raw user input — mitigating prompt injection.
- LLM is explicitly forbidden from inventing data not in the context.
"""
from __future__ import annotations

import json
import os
import re
from typing import Tuple

import anthropic
from rich.console import Console

from agent.models import (
    FollowUpStage,
    GeneratedEmail,
    InvoiceRecord,
    STAGE_META,
)

console = Console()

# ---------------------------------------------------------------------------
# System prompt — the core guardrail layer
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are a professional finance communications assistant for a company's accounts receivable team.

Your ONLY task is to generate follow-up emails for overdue invoices.

STRICT RULES:
1. Use ONLY the invoice data provided. NEVER invent or modify any field (amount, invoice number, dates, names).
2. Do NOT add any payment amounts, dates, or contact details that are not in the provided data.
3. Match the tone EXACTLY as instructed. Do not soften stage 4 or make stage 1 stern.
4. Output ONLY valid JSON — no markdown, no preamble, no explanation.
5. The body must be professional, concise (150–250 words max), and free of spelling errors.
6. Address the client by first name in stages 1–2, by "Mr./Ms. [Last Name]" in stages 3–4.
7. Always include the payment link if provided.
8. Never threaten legal action unless explicitly instructed (stage 4 only may mention escalation).

OUTPUT FORMAT (strict JSON, no code fences):
{
  "subject": "...",
  "body": "..."
}"""


def _build_user_prompt(record: InvoiceRecord, stage: FollowUpStage) -> str:
    """Build the user turn for the LLM — all fields come from validated model."""
    meta = STAGE_META[stage]
    name_parts = record.client_name.strip().split()
    first_name = name_parts[0] if name_parts else record.client_name
    last_name = name_parts[-1] if len(name_parts) > 1 else name_parts[0]

    payment_section = (
        f"Payment Link: {record.payment_link}" if record.payment_link
        else f"Contact: {record.contact_phone or 'our finance team'}"
    )

    return f"""Generate a follow-up email with the following parameters:

TONE: {meta['tone']}
STAGE: {stage.value} ({meta['label']})

INVOICE DATA (use these exact values — do not modify):
- Invoice Number: {record.invoice_no}
- Client Full Name: {record.client_name}
- Client First Name: {first_name}
- Client Last Name: {last_name}
- Amount Due: {record.formatted_amount()}
- Due Date: {record.due_date.strftime('%d %b %Y')}
- Days Overdue: {record.days_overdue}
- Follow-ups Already Sent: {record.follow_up_count}
- {payment_section}

COMPANY CONTACT:
- Company Name: {os.getenv('COMPANY_NAME', 'Finance Dept')}
- Company Email: {os.getenv('COMPANY_EMAIL', 'finance@company.com')}
- Company Phone: {os.getenv('COMPANY_PHONE', '')}

Generate the email now. Return ONLY the JSON object."""


def generate_email(record: InvoiceRecord) -> Tuple[GeneratedEmail | None, bool]:
    """
    Generate a follow-up email for a single invoice.
    Returns (GeneratedEmail, is_escalated).
    Returns (None, True) for records flagged for legal escalation.
    """
    stage = record.get_stage()

    # Escalated records — no email generated
    if stage == FollowUpStage.ESCALATED:
        console.print(
            f"[bold red]🚨 {record.invoice_no} — ESCALATED ({record.days_overdue} days overdue). "
            f"Flagged for legal/finance review. No email sent.[/bold red]"
        )
        return None, True

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": _build_user_prompt(record, stage)}
            ],
        )

        raw = response.content[0].text.strip()

        # Strip any accidental markdown code fences
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        parsed = json.loads(raw)

        # Validate required keys exist
        if "subject" not in parsed or "body" not in parsed:
            raise ValueError(f"LLM response missing subject/body keys: {parsed}")

        # Validate that the invoice number appears in the email (hallucination check)
        if record.invoice_no not in parsed["body"] and record.invoice_no not in parsed["subject"]:
            console.print(
                f"[yellow]⚠  Hallucination warning: invoice_no {record.invoice_no} "
                f"not found in generated email. Review manually.[/yellow]"
            )

        meta = STAGE_META[stage]
        email = GeneratedEmail(
            invoice_no=record.invoice_no,
            subject=parsed["subject"],
            body=parsed["body"],
            stage=stage,
            tone_label=meta["label"],
        )
        return email, False

    except json.JSONDecodeError as e:
        console.print(f"[red]✗ JSON parse error for {record.invoice_no}: {e}[/red]")
        console.print(f"[dim]Raw LLM output: {raw[:300]}[/dim]")
        return None, False
    except Exception as e:
        console.print(f"[red]✗ Generation error for {record.invoice_no}: {e}[/red]")
        return None, False
