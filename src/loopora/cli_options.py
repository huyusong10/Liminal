from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from loopora.workflows import preset_names

SpecOption = Annotated[Path, typer.Option(..., exists=True, help="Path to the Markdown spec.")]
WorkdirOption = Annotated[Path, typer.Option(..., exists=True, file_okay=False, dir_okay=True, help="Target workdir.")]
ExecutorOption = Annotated[str, typer.Option("--executor", help="Execution tool: codex, claude, opencode, or custom.")]
ExecutorModeOption = Annotated[str, typer.Option("--executor-mode", help="Execution mode: preset or command.")]
ModelOption = Annotated[str, typer.Option(help="Default model or alias for the selected execution tool.")]
ReasoningOption = Annotated[str, typer.Option(help="Reasoning effort or variant for the selected execution tool.")]
CommandCliOption = Annotated[str, typer.Option("--command-cli", help="Executable to invoke in command mode. Defaults to the selected tool CLI.")]
CommandArgOption = Annotated[
    list[str] | None,
    typer.Option(
        "--command-arg",
        help="One command-mode argv template entry. Repeat once per argument. Supports placeholders like {workdir}, {schema_path}, {output_path}, {json_schema}, {sandbox}, {prompt}, {model}, and {reasoning_effort}.",
    ),
]
CompletionModeOption = Annotated[
    str,
    typer.Option("--completion-mode", help="Completion mode: gatekeeper or rounds."),
]
IterationIntervalOption = Annotated[
    float,
    typer.Option("--iteration-interval-seconds", min=0.0, help="Wait this many seconds between iterations."),
]
MaxItersOption = Annotated[int, typer.Option(min=0, help="Maximum orchestration iterations. Use 0 to keep iterating until you stop it.")]
MaxRoleRetriesOption = Annotated[int, typer.Option(min=0, help="Retries per role before aborting.")]
DeltaThresholdOption = Annotated[float, typer.Option(min=0.0, help="Plateau threshold.")]
TriggerWindowOption = Annotated[int, typer.Option(min=1, help="Plateau trigger window.")]
RegressionWindowOption = Annotated[int, typer.Option(min=1, help="Regression trigger window.")]
NameOption = Annotated[str | None, typer.Option(help="Optional loop name.")]
RoleModelOption = Annotated[
    list[str] | None,
    typer.Option(
        "--role-model",
        help="Per-role model override like builder=gpt-5.4-mini. Legacy names like generator/verifier still work.",
    ),
]
WorkflowPresetOption = Annotated[
    str,
    typer.Option(
        "--workflow-preset",
        help=f"Workflow preset: {', '.join(preset_names())}.",
    ),
]
OrchestrationIdOption = Annotated[
    str,
    typer.Option(
        "--orchestration-id",
        help="Use a saved orchestration id, such as builtin:build_first or a custom orchestration id.",
    ),
]
WorkflowFileOption = Annotated[
    Path | None,
    typer.Option(
        "--workflow-file",
        exists=True,
        file_okay=True,
        dir_okay=False,
        help="Path to a JSON or YAML workflow bundle. Supports {workflow, prompt_files} or a raw workflow object.",
    ),
]
BundleFileOption = Annotated[
    Path,
    typer.Argument(
        ...,
        exists=True,
        file_okay=True,
        dir_okay=False,
        help="Path to a single YAML bundle file.",
    ),
]
BundleOutputOption = Annotated[
    Path | None,
    typer.Option(
        "--output",
        file_okay=True,
        dir_okay=False,
        help="Write the YAML bundle to this path instead of printing it.",
    ),
]
StartOption = Annotated[bool, typer.Option("--start", help="Start a run immediately after creating the loop definition.")]
BackgroundOption = Annotated[bool, typer.Option("--background", help="Queue the run and return immediately instead of waiting for it to finish.")]
LocaleOption = Annotated[str, typer.Option("--locale", help="Template locale: zh or en.")]
PromptFileOption = Annotated[
    Path | None,
    typer.Option(
        "--prompt-file",
        exists=True,
        file_okay=True,
        dir_okay=False,
        help="Path to a Markdown prompt file.",
    ),
]
PromptTemplateOption = Annotated[
    str,
    typer.Option("--prompt-template", help="Built-in prompt template ref such as builder.md."),
]
ArchetypeOption = Annotated[
    str,
    typer.Option("--archetype", help="Role archetype: builder, inspector, gatekeeper, guide, or custom."),
]
JsonOutputOption = Annotated[bool, typer.Option("--json", help="Print structured JSON instead of plain text.")]
FromFileOption = Annotated[
    Path | None,
    typer.Option(
        "--from-file",
        exists=True,
        file_okay=True,
        dir_okay=False,
        help="Read Markdown content from this file.",
    ),
]
