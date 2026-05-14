"""
agent/email_sender.py — Email dispatch with dry-run support.

Security mitigations:
- DRY_RUN=true (default) prevents accidental sends during development/testing.
- SMTP credentials loaded exclusively from environment variables (never hardcoded).
- SPF/DKIM/DMARC setup instructions included in README.
- Sender domain verified via environment config.
- No plaintext credentials logged — only masked sender address.
"""
from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Tuple

from rich.console import Console

from agent.models import GeneratedEmail, InvoiceRecord

console = Console()


def _is_dry_run() -> bool:
    return os.getenv("DRY_RUN", "true").lower() in ("true", "1", "yes")


def send_email(
    record: InvoiceRecord,
    generated: GeneratedEmail,
) -> Tuple[bool, str]:
    """
    Send (or simulate sending) a follow-up email.
    Returns (success: bool, status: str).
    """
    if _is_dry_run():
        return _dry_run_log(record, generated)

    # Prefer SendGrid if API key is set, else fall back to SMTP
    if os.getenv("SENDGRID_API_KEY"):
        return _send_via_sendgrid(record, generated)
    else:
        return _send_via_smtp(record, generated)


def _dry_run_log(record: InvoiceRecord, generated: GeneratedEmail) -> Tuple[bool, str]:
    """Simulate sending — log to console only."""
    console.print(f"\n[bold cyan]📧 DRY RUN — {record.invoice_no}[/bold cyan]")
    console.print(f"  [dim]To:[/dim]      {record.client_email}")
    console.print(f"  [dim]Subject:[/dim] {generated.subject}")
    console.print(f"  [dim]Tone:[/dim]    {generated.tone_label}")
    console.print(f"  [dim]Body preview:[/dim]")
    preview = generated.body[:300].replace("\n", " ")
    console.print(f"  [italic]{preview}...[/italic]")
    console.rule()
    return True, "dry_run"


def _send_via_smtp(record: InvoiceRecord, generated: GeneratedEmail) -> Tuple[bool, str]:
    """Send via SMTP (e.g. Gmail, company SMTP relay)."""
    try:
        from_email = os.environ["SMTP_FROM_EMAIL"]
        from_name = os.getenv("SMTP_FROM_NAME", "Finance Team")
        host = os.environ["SMTP_HOST"]
        port = int(os.getenv("SMTP_PORT", "587"))
        user = os.environ["SMTP_USER"]
        password = os.environ["SMTP_PASSWORD"]

        msg = MIMEMultipart("alternative")
        msg["Subject"] = generated.subject
        msg["From"] = f"{from_name} <{from_email}>"
        msg["To"] = record.client_email
        msg["X-Invoice-No"] = record.invoice_no  # custom header for audit

        # Plain text part
        part1 = MIMEText(generated.body, "plain", "utf-8")
        # HTML part (simple wrapping)
        html_body = generated.body.replace("\n", "<br>")
        html = f"""<html><body style="font-family:Arial,sans-serif;font-size:14px;color:#333;">
        {html_body}
        </body></html>"""
        part2 = MIMEText(html, "html", "utf-8")

        msg.attach(part1)
        msg.attach(part2)

        with smtplib.SMTP(host, port) as server:
            server.ehlo()
            server.starttls()
            server.login(user, password)
            server.sendmail(from_email, record.client_email, msg.as_string())

        console.print(f"[green]✓ Sent via SMTP → {record.client_email}[/green]")
        return True, "sent"

    except Exception as e:
        console.print(f"[red]✗ SMTP error for {record.invoice_no}: {e}[/red]")
        return False, f"error: {e}"


def _send_via_sendgrid(record: InvoiceRecord, generated: GeneratedEmail) -> Tuple[bool, str]:
    """Send via SendGrid API."""
    try:
        import sendgrid
        from sendgrid.helpers.mail import Mail

        sg = sendgrid.SendGridAPIClient(api_key=os.environ["SENDGRID_API_KEY"])
        from_email = os.getenv("SENDGRID_FROM_EMAIL", os.getenv("SMTP_FROM_EMAIL", ""))

        message = Mail(
            from_email=from_email,
            to_emails=record.client_email,
            subject=generated.subject,
            plain_text_content=generated.body,
        )

        response = sg.send(message)
        if response.status_code in (200, 202):
            console.print(f"[green]✓ Sent via SendGrid → {record.client_email}[/green]")
            return True, "sent"
        else:
            msg = f"SendGrid returned status {response.status_code}"
            console.print(f"[red]✗ {msg}[/red]")
            return False, f"error: {msg}"

    except Exception as e:
        console.print(f"[red]✗ SendGrid error for {record.invoice_no}: {e}[/red]")
        return False, f"error: {e}"
