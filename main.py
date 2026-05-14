"""
main.py — CLI entrypoint for the Finance Credit Follow-Up Email Agent.

Usage:
    python main.py                    # Run agent (DRY_RUN=true by default)
    python main.py --live             # Run with real email sending
    python main.py --audit            # Show audit log only
    python main.py --invoice INV-001  # Process single invoice only
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console

console = Console()


def main() -> None:
    # Load environment variables from .env file
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Finance Credit Follow-Up Email Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                    Run agent in dry-run mode (safe, no emails sent)
  python main.py --live             Run with real email sending
  python main.py --audit            Display the audit log
  python main.py --invoice INV-001  Process a single invoice
        """
    )
    parser.add_argument("--live", action="store_true", help="Enable real email sending (overrides DRY_RUN=true)")
    parser.add_argument("--audit", action="store_true", help="Show audit log and exit")
    parser.add_argument("--invoice", type=str, help="Process a single invoice by number")
    parser.add_argument("--csv", type=str, help="Path to invoice CSV (overrides INVOICE_CSV_PATH env var)")
    args = parser.parse_args()

    # Validate API key
    if not os.getenv("ANTHROPIC_API_KEY"):
        console.print(
            "[bold red]✗ ANTHROPIC_API_KEY not set.[/bold red]\n"
            "  Copy .env.example → .env and fill in your API key."
        )
        sys.exit(1)

    if args.csv:
        os.environ["INVOICE_CSV_PATH"] = args.csv

    if args.live:
        os.environ["DRY_RUN"] = "false"
        console.print("[bold yellow]⚠  LIVE MODE — real emails will be sent![/bold yellow]")
    else:
        os.environ.setdefault("DRY_RUN", "true")

    if args.audit:
        from agent.audit_logger import load_audit_log, print_audit_summary
        entries = load_audit_log()
        if not entries:
            console.print("[yellow]No audit entries found.[/yellow]")
        else:
            print_audit_summary(entries)
        return

    if args.invoice:
        # Single invoice mode
        _run_single_invoice(args.invoice)
    else:
        # Full batch run
        from agent.orchestrator import run_agent
        results = run_agent()
        console.print(f"\n[bold green]✓ Processed {len(results)} invoice(s).[/bold green]")


def _run_single_invoice(invoice_no: str) -> None:
    """Run the agent for a single invoice number."""
    from agent.data_loader import load_invoices
    from agent.email_generator import generate_email
    from agent.email_sender import send_email
    from agent.audit_logger import log_action

    path = os.getenv("INVOICE_CSV_PATH", "data/invoices.csv")
    invoices = load_invoices(path)

    matches = [r for r in invoices if r.invoice_no == invoice_no]
    if not matches:
        console.print(f"[red]✗ Invoice {invoice_no} not found in {path}[/red]")
        sys.exit(1)

    record = matches[0]
    generated, is_escalated = generate_email(record)

    if is_escalated:
        log_action(record, None, "escalated", is_escalated=True)
        return

    if generated:
        success, status = send_email(record, generated)
        log_action(record, generated, status)
        console.print(f"\n[green]✓ Done: {invoice_no} — {status}[/green]")


if __name__ == "__main__":
    main()
