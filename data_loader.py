"""
agent/data_loader.py — Load and validate invoice records from CSV / Excel.

Security notes:
- All fields are validated through Pydantic models before use.
- client_name is sanitized to strip prompt-injection characters.
- client_email is lowercased and stripped.
- No raw user data is ever interpolated directly into LLM prompts
  without going through the validated InvoiceRecord model first.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import List

import pandas as pd
from rich.console import Console
from rich.table import Table

from agent.models import InvoiceRecord

console = Console()


def load_invoices(path: str | Path) -> List[InvoiceRecord]:
    """
    Load invoice records from a CSV or Excel file.
    Returns only overdue records (days_overdue > 0).
    Raises on missing required columns.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Invoice file not found: {path}")

    if path.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(path, dtype=str)
    else:
        df = pd.read_csv(path, dtype=str)

    required = {
        "invoice_no", "client_name", "client_email",
        "amount", "due_date", "days_overdue",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Invoice file missing required columns: {missing}")

    records: List[InvoiceRecord] = []
    skipped = 0

    for _, row in df.iterrows():
        try:
            record = InvoiceRecord(
                invoice_no=str(row["invoice_no"]).strip(),
                client_name=str(row["client_name"]).strip(),
                client_email=str(row["client_email"]).strip(),
                amount=float(str(row["amount"]).replace(",", "")),
                currency=str(row.get("currency", "INR")).strip(),
                due_date=date.fromisoformat(str(row["due_date"]).strip()),
                follow_up_count=int(row.get("follow_up_count", 0)),
                days_overdue=int(row["days_overdue"]),
                payment_link=str(row.get("payment_link", "")).strip() or None,
                contact_phone=str(row.get("contact_phone", "")).strip() or None,
            )
            if record.days_overdue > 0:
                records.append(record)
        except Exception as e:
            console.print(f"[yellow]⚠  Skipping row {row.get('invoice_no', '?')}: {e}[/yellow]")
            skipped += 1

    console.print(
        f"[green]✓ Loaded {len(records)} overdue invoice(s)[/green]"
        + (f" | [yellow]{skipped} skipped[/yellow]" if skipped else "")
    )
    return records


def print_invoice_summary(records: List[InvoiceRecord]) -> None:
    """Render a Rich table of loaded invoices for CLI visibility."""
    table = Table(title="📋 Overdue Invoice Queue", show_lines=True)
    table.add_column("Invoice #", style="cyan")
    table.add_column("Client", style="white")
    table.add_column("Amount", style="green", justify="right")
    table.add_column("Days Overdue", style="red", justify="center")
    table.add_column("Stage", style="magenta")
    table.add_column("Follow-ups Sent", justify="center")

    for r in records:
        stage = r.get_stage()
        table.add_row(
            r.invoice_no,
            r.client_name,
            r.formatted_amount(),
            str(r.days_overdue),
            stage.value.replace("_", " ").title(),
            str(r.follow_up_count),
        )

    console.print(table)
