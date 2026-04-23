from __future__ import annotations

from pathlib import Path

import typer

from loopora.cli_shared import BundleFileOption, BundleOutputOption, echo_json, get_service, handle_error
from loopora.service import LooporaError


def register_bundle_commands(bundles_app: typer.Typer) -> None:
    @bundles_app.command("list")
    def list_bundles() -> None:
        """List imported YAML bundles."""
        try:
            bundles = get_service().list_bundles()
            for item in bundles:
                typer.echo(
                    f"{item['id']}  {item['name']}  revision={item.get('revision', 1)}  "
                    f"loop={item.get('loop_id', '-') or '-'}  workdir={item.get('workdir', '-') or '-'}"
                )
        except LooporaError as exc:
            handle_error(exc)

    @bundles_app.command("get")
    def get_bundle(bundle_id: str = typer.Argument(..., help="Imported bundle id.")) -> None:
        """Show one imported bundle as JSON."""
        try:
            echo_json(get_service().get_bundle(bundle_id))
        except LooporaError as exc:
            handle_error(exc)

    @bundles_app.command("import")
    def import_bundle(
        bundle_file: BundleFileOption,
        replace_bundle_id: str = typer.Option("", help="Replace an existing imported bundle id in place."),
    ) -> None:
        """Import one YAML bundle and materialize its loop-ready assets."""
        try:
            echo_json(
                get_service().import_bundle_file(
                    bundle_file,
                    replace_bundle_id=replace_bundle_id.strip() or None,
                )
            )
        except LooporaError as exc:
            handle_error(exc)

    @bundles_app.command("export")
    def export_bundle(
        bundle_id: str = typer.Argument(..., help="Imported bundle id."),
        output: BundleOutputOption = None,
    ) -> None:
        """Export one imported bundle as YAML."""
        try:
            service = get_service()
            if output is None:
                typer.echo(service.export_bundle_yaml(bundle_id))
                return
            written = service.write_bundle_file(bundle_id, output)
            typer.echo(str(written.resolve()))
        except LooporaError as exc:
            handle_error(exc)

    @bundles_app.command("derive")
    def derive_bundle(
        loop_id: str = typer.Argument(..., help="Loop definition id to export as a YAML bundle."),
        output: BundleOutputOption = None,
        name: str | None = typer.Option(None, help="Override the exported bundle name."),
        description: str = typer.Option("", help="Optional bundle description."),
        collaboration_summary: str = typer.Option("", help="Optional readable collaboration summary."),
    ) -> None:
        """Derive a YAML bundle from an existing loop definition."""
        try:
            service = get_service()
            bundle = service.derive_bundle_from_loop(
                loop_id,
                name=name,
                description=description,
                collaboration_summary=collaboration_summary,
            )
            if output is None:
                from loopora.bundles import bundle_to_yaml

                typer.echo(bundle_to_yaml(bundle))
                return
            target = Path(output).expanduser()
            target.parent.mkdir(parents=True, exist_ok=True)
            from loopora.bundles import bundle_to_yaml

            target.write_text(bundle_to_yaml(bundle), encoding="utf-8")
            typer.echo(str(target.resolve()))
        except LooporaError as exc:
            handle_error(exc)

    @bundles_app.command("delete")
    def delete_bundle(bundle_id: str = typer.Argument(..., help="Imported bundle id.")) -> None:
        """Delete one imported bundle and its imported asset group."""
        try:
            echo_json(get_service().delete_bundle(bundle_id))
        except LooporaError as exc:
            handle_error(exc)
