from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopora.executor import (
    RealCodexExecutor,
    RoleRequest,
    build_custom_exec_args,
    build_claude_exec_args,
    build_codex_exec_args,
    build_opencode_exec_args,
    validate_command_args_text,
    validate_extra_cli_args_text,
)
from loopora.providers import normalize_executor_kind, normalize_executor_mode, normalize_reasoning_setting
from loopora.providers import executor_profile


def _request(tmp_path: Path, *, executor_kind: str, model: str, reasoning_effort: str) -> RoleRequest:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    return RoleRequest(
        run_id="run_test",
        role="tester",
        prompt="Return JSON only.",
        workdir=tmp_path,
        model=model,
        reasoning_effort=reasoning_effort,
        output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
        output_path=run_dir / "output.json",
        run_dir=run_dir,
        executor_kind=executor_kind,
    )


def test_executor_kind_aliases_normalize() -> None:
    assert normalize_executor_kind("codex") == "codex"
    assert normalize_executor_kind("claudecode") == "claude"
    assert normalize_executor_kind("open-code") == "opencode"
    assert normalize_executor_kind("custom") == "custom"


def test_executor_mode_normalizes() -> None:
    assert normalize_executor_mode("preset") == "preset"
    assert normalize_executor_mode("command") == "command"


def test_reasoning_setting_is_provider_specific() -> None:
    assert normalize_reasoning_setting("minimal", executor_kind="codex") == "low"
    assert normalize_reasoning_setting("xhigh", executor_kind="claude") == "max"
    assert normalize_reasoning_setting("", executor_kind="opencode") == ""
    assert normalize_reasoning_setting("default", executor_kind="opencode") == ""
    assert normalize_reasoning_setting("default", executor_kind="custom") == ""
    assert executor_profile("opencode").preset_effort_visible is True
    assert executor_profile("custom").command_only is True


def test_codex_exec_args_include_output_schema_and_reasoning(tmp_path: Path) -> None:
    request = _request(tmp_path, executor_kind="codex", model="gpt-5.4", reasoning_effort="high")
    args = build_codex_exec_args(request, request.run_dir / "schema.json")

    assert args[:3] == ["codex", "exec", "--json"]
    assert "--output-schema" in args
    assert "--output-last-message" in args
    assert "--model" in args
    assert 'model_reasoning_effort="high"' in args


def test_codex_exec_args_start_fresh_session_when_resume_id_is_missing(tmp_path: Path) -> None:
    request = _request(tmp_path, executor_kind="codex", model="gpt-5.4", reasoning_effort="medium")
    request.inherit_session = True
    request.resume_session_id = ""

    args = build_codex_exec_args(request, request.run_dir / "schema.json")

    assert args[:3] == ["codex", "exec", "--json"]
    assert "resume" not in args
    assert "--last" not in args
    assert "--cd" in args


def test_codex_exec_args_can_resume_previous_session_and_append_extra_args(tmp_path: Path) -> None:
    request = _request(tmp_path, executor_kind="codex", model="gpt-5.4", reasoning_effort="medium")
    request.inherit_session = True
    request.resume_session_id = "codex-session-123"
    request.extra_cli_args_text = "--search --verbose"

    args = build_codex_exec_args(request, request.run_dir / "schema.json")

    assert args[:3] == ["codex", "exec", "resume"]
    assert "codex-session-123" in args
    assert "--cd" not in args
    assert "--sandbox" not in args
    assert "--output-schema" not in args
    assert "--output-last-message" in args
    assert "--search" in args
    assert "--verbose" in args
    assert args[-1] == "Return JSON only."


def test_claude_exec_args_map_xhigh_to_max(tmp_path: Path) -> None:
    request = _request(tmp_path, executor_kind="claude", model="sonnet", reasoning_effort="xhigh")
    args = build_claude_exec_args(request)

    assert args[:6] == ["claude", "--setting-sources", "local,project", "-p", "--output-format", "stream-json"]
    assert "--json-schema" in args
    assert "--model" in args
    assert "--effort" in args
    assert "max" in args
    assert "xhigh" not in args


def test_claude_exec_args_resume_session_and_drop_no_persistence(tmp_path: Path) -> None:
    request = _request(tmp_path, executor_kind="claude", model="sonnet", reasoning_effort="high")
    request.inherit_session = True
    request.resume_session_id = "claude-session-abc"
    request.extra_cli_args_text = "--verbose"

    args = build_claude_exec_args(request)

    assert "--resume" in args
    assert "claude-session-abc" in args
    assert "--no-session-persistence" not in args
    assert "--verbose" in args


def test_claude_preset_defaults_to_blank_model() -> None:
    profile = executor_profile("claude")

    assert profile.default_model == ""
    assert "--model" in profile.command_args_template
    assert "{model}" in profile.command_args_template


def test_claude_exec_args_omit_model_when_blank(tmp_path: Path) -> None:
    request = _request(tmp_path, executor_kind="claude", model="", reasoning_effort="medium")
    args = build_claude_exec_args(request)

    assert args[:6] == ["claude", "--setting-sources", "local,project", "-p", "--output-format", "stream-json"]
    assert "--json-schema" in args
    assert "--model" not in args
    assert "--effort" in args


def test_opencode_exec_args_use_variant_only_when_present(tmp_path: Path) -> None:
    request = _request(tmp_path, executor_kind="opencode", model="", reasoning_effort="")
    args = build_opencode_exec_args(request)

    assert args[:4] == ["opencode", "run", "--format", "json"]
    assert "--dangerously-skip-permissions" in args
    assert "--model" not in args
    assert "--variant" not in args


def test_opencode_exec_args_can_resume_session_and_append_extra_args(tmp_path: Path) -> None:
    request = _request(tmp_path, executor_kind="opencode", model="", reasoning_effort="")
    request.inherit_session = True
    request.resume_session_id = "open-session-42"
    request.extra_cli_args_text = "--share"

    args = build_opencode_exec_args(request)

    assert "--session" in args
    assert "open-session-42" in args
    assert "--share" in args


def test_custom_exec_args_require_runtime_placeholders() -> None:
    with pytest.raises(ValueError, match="missing required placeholders"):
        validate_command_args_text("--model\ngpt-5.4\n{prompt}\n", executor_kind="codex")


def test_claude_command_args_require_json_schema_placeholder() -> None:
    with pytest.raises(ValueError, match="\\{json_schema\\}"):
        validate_command_args_text("-p\n--output-format\nstream-json\n{prompt}\n", executor_kind="claude")


def test_custom_command_args_require_output_path_placeholder() -> None:
    with pytest.raises(ValueError, match="\\{output_path\\}"):
        validate_command_args_text("--prompt\n{prompt}\n", executor_kind="custom")


def test_custom_exec_args_resolve_runtime_values(tmp_path: Path) -> None:
    request = _request(tmp_path, executor_kind="claude", model="sonnet", reasoning_effort="medium")
    request.executor_mode = "command"
    request.command_cli = "claude"
    request.command_args_text = "\n".join(
        [
            "-p",
            "--output-format",
            "stream-json",
            "--json-schema",
            "{json_schema}",
            "{prompt}",
        ]
    )

    args = build_custom_exec_args(request, request.run_dir / "schema.json")

    assert args[0] == "claude"
    assert "--json-schema" in args
    assert "Return JSON only." in args
    schema_arg = args[args.index("--json-schema") + 1]
    assert schema_arg.startswith("{")


def test_custom_exec_args_insert_extra_cli_args_before_prompt_when_possible(tmp_path: Path) -> None:
    request = _request(tmp_path, executor_kind="codex", model="gpt-5.4", reasoning_effort="medium")
    request.executor_mode = "command"
    request.command_cli = "codex"
    request.command_args_text = "\n".join(
        [
            "exec",
            "--json",
            "--output-schema",
            "{schema_path}",
            "--output-last-message",
            "{output_path}",
            "{prompt}",
        ]
    )
    request.extra_cli_args_text = "--verbose --search"

    args = build_custom_exec_args(request, request.run_dir / "schema.json")

    prompt_index = args.index("Return JSON only.")
    assert args[prompt_index - 2 : prompt_index] == ["--verbose", "--search"]


def test_custom_exec_args_drop_empty_placeholder_lines(tmp_path: Path) -> None:
    request = _request(tmp_path, executor_kind="opencode", model="", reasoning_effort="")
    request.executor_mode = "command"
    request.command_cli = "opencode"
    request.command_args_text = "\n".join(
        [
            "run",
            "--model",
            "{model}",
            "{prompt}",
        ]
    )

    args = build_custom_exec_args(request, request.run_dir / "schema.json")

    assert args == ["opencode", "run", "Return JSON only."]


def test_custom_exec_args_do_not_expand_placeholders_inside_prompt_value(tmp_path: Path) -> None:
    request = _request(tmp_path, executor_kind="codex", model="gpt-5.4", reasoning_effort="medium")
    request.prompt = "Keep the literal token {workdir} in the final prompt."
    request.executor_mode = "command"
    request.command_cli = "codex"
    request.command_args_text = "\n".join(
        [
            "exec",
            "--json",
            "--output-schema",
            "{schema_path}",
            "--output-last-message",
            "{output_path}",
            "{prompt}",
        ]
    )

    args = build_custom_exec_args(request, request.run_dir / "schema.json")

    assert args[-1] == "Keep the literal token {workdir} in the final prompt."


def test_extra_cli_args_validation_rejects_unbalanced_quotes() -> None:
    with pytest.raises(ValueError, match="invalid extra CLI args"):
        validate_extra_cli_args_text('--verbose "unterminated')


def test_claude_stream_parser_extracts_structured_output(tmp_path: Path) -> None:
    executor = RealCodexExecutor()
    state = {"blocks": {}, "structured_output": None}
    emitted: list[tuple[str, dict]] = []

    lines = [
        json.dumps(
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_start",
                    "content_block": {"name": "StructuredOutput", "input": {}, "id": "tool_1", "type": "tool_use"},
                    "index": 1,
                },
            }
        ),
        json.dumps(
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "input_json_delta", "partial_json": '{"ok": true'},
                    "index": 1,
                },
            }
        ),
        json.dumps(
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "input_json_delta", "partial_json": "}"},
                    "index": 1,
                },
            }
        ),
        json.dumps({"type": "result", "result": "done", "structured_output": {"ok": True}}),
    ]

    for line in lines:
        executor._handle_claude_line(line, state, lambda event_type, payload: emitted.append((event_type, payload)))

    assert state["structured_output"] == {"ok": True}
    assert ("codex_event", {"type": "stdout", "message": "done"}) in emitted


def test_claude_stream_parser_logs_tool_use_and_tool_result(tmp_path: Path) -> None:
    executor = RealCodexExecutor()
    state = {"blocks": {}, "structured_output": None}
    emitted: list[tuple[str, dict]] = []

    lines = [
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Bash",
                            "input": {"command": "pwd", "description": "Get current working directory"},
                        }
                    ]
                },
            }
        ),
        json.dumps(
            {
                "type": "user",
                "message": {"content": [{"type": "tool_result", "content": "/tmp/workdir"}]},
                "tool_use_result": {"stdout": "/tmp/workdir", "stderr": "", "interrupted": False},
            }
        ),
    ]

    for line in lines:
        executor._handle_claude_line(line, state, lambda event_type, payload: emitted.append((event_type, payload)))

    assert ("codex_event", {"type": "stdout", "message": "Tool use · Bash · pwd · Get current working directory"}) in emitted
    assert ("codex_event", {"type": "stdout", "message": "Tool result · /tmp/workdir"}) in emitted


def test_claude_stream_parser_truncates_large_tool_results(tmp_path: Path) -> None:
    executor = RealCodexExecutor()
    state = {"blocks": {}, "structured_output": None}
    emitted: list[tuple[str, dict]] = []
    long_stdout = "\n".join(f"line {index}" for index in range(40))

    executor._handle_claude_line(
        json.dumps(
            {
                "type": "user",
                "message": {"content": [{"type": "tool_result", "content": long_stdout}]},
                "tool_use_result": {"stdout": long_stdout, "stderr": "", "interrupted": False},
            }
        ),
        state,
        lambda event_type, payload: emitted.append((event_type, payload)),
    )

    assert emitted
    message = emitted[0][1]["message"]
    assert message.startswith("Tool result · line 0")
    assert "... (truncated)" in message
    assert "line 39" not in message


def test_opencode_text_parser_extracts_json_object(tmp_path: Path) -> None:
    executor = RealCodexExecutor()
    state = {"latest_text": "", "text_parts": []}
    emitted: list[tuple[str, dict]] = []

    executor._handle_opencode_line(
        json.dumps(
            {
                "type": "text",
                "part": {"text": '{"ok": true}'},
            }
        ),
        state,
        lambda event_type, payload: emitted.append((event_type, payload)),
    )

    assert state["latest_text"] == '{"ok": true}'
    assert executor._parse_structured_output_from_text(state["latest_text"]) == {"ok": True}
    assert ("codex_event", {"type": "stdout", "message": '{"ok": true}'}) in emitted
