"""
agent/audit_logger.py — Immutable audit trail for all email actions.

Privacy notes:
- Full email body is NOT stored — only a 200-char preview.
- Client email stored for traceability but can be masked in prod.
- Log file is append-only JSON Lines format for easy querying.
- In production, consider encrypting the log file at rest.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from rich.console import Console
from rich.table import Table

from agent.models import AuditEntry, FollowUpStage, GeneratedEmail, InvoiceRecord

console = Console()


def _get_log_path() -> Path:
    path = Path(os.getenv("AUDIT_LOG_PATH", "logs/audit_log.jsonl"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def log_action(
    record: InvoiceRecord,
    generated: Optional[GeneratedEmail],
    send_status: str,
    error_message: Optional[str] = None,
    is_escalated: bool = False,
) -> AuditEntry:
    """Write an audit entry and return it."""
    stage = record.get_stage()

    if is_escalated:
        subject = "ESCALATED — flagged for legal review"
        body_preview = f"Invoice {record.invoice_no} escalated after {record.days_overdue} days overdue."
    else:
        subject = generated.subject if generated else "GENERATION_FAILED"
        body_preview = (generated.body[:200] if generated else "")

    entry = AuditEntry(
        timestamp=datetime.utcnow(),
        invoice_no=record.invoice_no,
        client_name=record.client_name,
        client_email=record.client_email,
        stage=stage,
        subject=subject,
        body_preview=body_preview,
        send_status=send_status,
        error_message=error_message,
        dry_run=os.getenv("DRY_RUN", "true").lower() in ("true", "1", "yes"),
    )

    log_path = _get_log_path()
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(entry.model_dump_json() + "\n")

    return entry


def load_audit_log() -> List[AuditEntry]:
    """Load all audit entries from the log file."""
    log_path = _get_log_path()
    if not log_path.exists():
        return []
    entries = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(AuditEntry.model_validate_json(line))
                except Exception:
                    pass
    return entries


def print_audit_summary(entries: List[AuditEntry]) -> None:
    """Print a Rich summary table of the audit log."""
    table = Table(title="📊 Audit Log Summary", show_lines=True)
    table.add_column("Timestamp (UTC)", style="dim")
    table.add_column("Invoice #", style="cyan")
    table.add_column("Client")
    table.add_column("Stage", style="magenta")
    table.add_column("Status", style="green")
    table.add_column("Dry Run", justify="center")

    status_styles = {
        "sent": "green",
        "dry_run": "yellow",
        "escalated": "red",
        "error": "bold red",
    }

    for e in entries[-20:]:  # show last 20
        status_style = status_styles.get(e.send_status.split(":")[0], "white")
        table.add_row(
            e.timestamp.strftime("%Y-%m-%d %H:%M"),
            e.invoice_no,
            e.client_name,
            e.stage.value.replace("_", " ").title(),
            f"[{status_style}]{e.send_status}[/{status_style}]",
            "✓" if e.dry_run else "✗",
        )

    console.print(table)

    # Summary stats
    total = len(entries)
    sent = sum(1 for e in entries if e.send_status in ("sent", "dry_run"))
    escalated = sum(1 for e in entries if e.send_status == "escalated")
    errors = sum(1 for e in entries if e.send_status.startswith("error"))

    console.print(
        f"\n[bold]Total actions:[/bold] {total} | "
        f"[green]Sent/Simulated:[/green] {sent} | "
        f"[red]Escalated:[/red] {escalated} | "
        f"[yellow]Errors:[/yellow] {errors}"
    )
