from __future__ import annotations

import json

import typer

from loopora.event_redaction_audit import audit_run_event_redaction


def register_diagnose_commands(app: typer.Typer) -> None:
    @app.command("event-redaction")
    def diagnose_event_redaction(
        fix: bool = typer.Option(False, "--fix", help="Rewrite DB and timeline events that current redaction rules can safely repair."),
    ) -> None:
        from loopora.cli import create_service

        service = create_service()
        report = audit_run_event_redaction(service.repository, fix=fix)
        typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
