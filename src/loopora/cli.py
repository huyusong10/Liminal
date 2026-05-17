from __future__ import annotations

import typer
from typer.core import TyperGroup

from loopora.branding import APP_NAME
from loopora.cli_agent_adapter_commands import register_agent_adapter_commands
from loopora.cli_bundle_commands import register_bundle_commands
from loopora.cli_diagnose_commands import register_diagnose_commands
from loopora.cli_shared import spawn_background_worker as _spawn_background_worker
from loopora.cli_loop_commands import register_loop_commands
from loopora.cli_orchestration_commands import register_orchestration_commands
from loopora.cli_prompt_commands import register_prompt_commands
from loopora.cli_role_commands import register_role_commands
from loopora.cli_root_commands import register_root_commands
from loopora.cli_spec_commands import register_spec_commands
from loopora.service import create_service


class LooporaRootHelpGroup(TyperGroup):
    def list_commands(self, ctx):
        names = super().list_commands(ctx)
        first_use_order = {
            "init": 0,
            "serve": 1,
            "uninstall": 2,
            "loops": 3,
            "bundles": 4,
            "diagnose": 5,
            "run": 6,
            "orchestrations": 7,
            "roles": 8,
            "spec": 9,
            "prompts": 10,
            "agent": 11,
        }
        original_order = {name: index for index, name in enumerate(names)}
        return sorted(names, key=lambda name: (first_use_order.get(name, 100), original_order[name]))


app = typer.Typer(
    cls=LooporaRootHelpGroup,
    help=(
        f"{APP_NAME} CLI\n\n"
        "Start here: in the project where your Coding Agent will work, run "
        "`loopora init codex`, `loopora init claude`, or `loopora init opencode`, "
        "then return to that Agent with the task goal, fake-done risk, and required evidence. "
        "Run `/loopora-gen`, review the Loop preview, then run `/loopora-loop` in the same Agent session."
    )
)
loops_app = typer.Typer(help="Inspect and run saved Loops")
orchestrations_app = typer.Typer(help="Expert: create and inspect reusable run flows")
roles_app = typer.Typer(help="Expert: create and inspect reusable role definitions")
bundles_app = typer.Typer(help="Import, export, and manage Loop plan files")
spec_app = typer.Typer(help="Expert: work with Markdown Loop contracts")
prompts_app = typer.Typer(help="Developer: validate and inspect prompt templates")
diagnose_app = typer.Typer(help="Inspect local diagnostics and repair safe historical issues")
init_app = typer.Typer(
    help=(
        "Install /loopora-gen and /loopora-loop project entries, then return to the Agent "
        "with the task goal, fake-done risk, and required evidence."
    )
)
uninstall_app = typer.Typer(help="Remove Loopora-managed Coding Agent project entries")
agent_app = typer.Typer(help="Internal runtime used by /loopora-gen and /loopora-loop project entries")

app.add_typer(init_app, name="init")
app.add_typer(uninstall_app, name="uninstall")
app.add_typer(loops_app, name="loops")
app.add_typer(orchestrations_app, name="orchestrations")
app.add_typer(roles_app, name="roles")
app.add_typer(bundles_app, name="bundles")
app.add_typer(spec_app, name="spec")
app.add_typer(prompts_app, name="prompts")
app.add_typer(diagnose_app, name="diagnose")
app.add_typer(agent_app, name="agent")

register_root_commands(app)
register_loop_commands(loops_app)
register_orchestration_commands(orchestrations_app)
register_role_commands(roles_app)
register_bundle_commands(bundles_app)
register_spec_commands(spec_app)
register_prompt_commands(prompts_app)
register_diagnose_commands(diagnose_app)
register_agent_adapter_commands(init_app, uninstall_app, agent_app)

__all__ = ["_spawn_background_worker", "app", "create_service"]
