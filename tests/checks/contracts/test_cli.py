from __future__ import annotations

import json
import re
from importlib.metadata import distribution
from pathlib import Path

from typer.testing import CliRunner

from loopora import cli
from loopora.bundles import bundle_to_yaml
from loopora.cli_run_support import print_run_result
from loopora.db import LooporaRepository
from loopora.executor import FakeCodexExecutor
from loopora.run_artifacts import RunArtifactLayout
from loopora.service import LooporaService
from loopora.settings import AppSettings
from loopora.settings import app_home
from loopora.utils import utc_now


def _result_error_text(result) -> str:
    try:
        return result.stderr
    except ValueError:
        return result.output


def _assert_cli_list(output: str, key: str, *items: str) -> None:
    assert f"{key}:\n" in output
    assert f"{key}: [" not in output
    for item in items:
        assert f"- {item}" in output


def _assert_readme_entry_points(readmes: list[str], documented_adapters: list[set[str]]) -> None:
    assert documented_adapters == [{"codex", "claude", "opencode"}, {"codex", "claude", "opencode"}]
    assert all("loopora serve " in readme for readme in readmes)
    assert "After the preview looks right, run `/loopora-loop`" in readmes[0]
    assert "预览看起来正确后，运行 `/loopora-loop`" in readmes[1]
    assert all("confirmed Loop" not in readme for readme in readmes)


def _assert_public_anchor_default_language(
    english_readme: str,
    chinese_readme: str,
    human_shaped_loop_docs: list[str],
) -> None:
    readmes = [english_readme, chinese_readme]
    assert all("judgment_contract" not in readme for readme in readmes)
    assert all("GateKeeper" not in readme for readme in readmes)
    assert "automated proof" in english_readme
    for forbidden in ("benchmark or proof harness", "benchmarks", "proof harness"):
        assert forbidden not in english_readme
    assert "基准评测" in chinese_readme
    assert "证明脚本" in chinese_readme
    for forbidden in ("benchmark", "proof harness", "required coverage", "run contract"):
        assert forbidden not in chinese_readme
    assert "Readers do not need to understand Loopora's internal terms first" in human_shaped_loop_docs[0]
    assert "读者不需要先理解 Loopora 的内部名词" in human_shaped_loop_docs[1]
    for doc in human_shaped_loop_docs:
        for forbidden in ("judgment_contract", "run contract", "step capsule", "GateKeeper", "Builder", "Inspector"):
            assert forbidden not in doc
    hsl_intro = human_shaped_loop_docs[1].split("## 2.", 1)[0]
    for forbidden in ("happy path", "coverage", "artifact 引用", "workflow handoff", "GateKeeper", "blocking issue"):
        assert forbidden not in hsl_intro


def _assert_alignment_language_assets(
    agent_first_design: str,
    product_principle: str,
    core_contract: str,
    web_alignment_design: str,
    governance_scenario: str,
) -> None:
    assert "查看、审查或修改候选 Loop" in agent_first_design
    assert "确认候选 Loop" not in agent_first_design
    assert "我审查并认可 Loop 的任务目标" in product_principle
    assert "我确认 Loop" not in product_principle
    assert "Loop composition -> Loop review -> run" in core_contract
    assert "Loop confirmation" not in core_contract
    assert "最近对话、三种编排模式入口" in web_alignment_design
    assert "继续已有对话，基于已有 Loop、方案文件、运行证据或任务契约改进" in web_alignment_design
    assert "最近 alignment sessions" not in web_alignment_design
    assert "继续已有 alignment session" not in web_alignment_design
    assert "已有 Loop / bundle / run / spec" not in web_alignment_design
    assert "明确确认工作约定后进入 READY" in governance_scenario
    assert "确认方案后进入 READY" not in governance_scenario


def _assert_documented_cli_entries_available(documented_adapters: list[set[str]]) -> None:
    runner = CliRunner()
    for adapter in sorted(documented_adapters[0]):
        result = runner.invoke(cli.app, ["init", adapter, "--help"])
        assert result.exit_code == 0, _result_error_text(result)
        assert "task goal" in result.stdout
        assert "fake-done risk" in result.stdout
        assert "required" in result.stdout
        assert "evidence" in result.stdout
        assert "/loopora-gen" in result.stdout
        assert "READY Loop preview" in result.stdout
        assert "/loopora-loop" in result.stdout
        assert "same Agent session" in result.stdout

    serve_result = runner.invoke(cli.app, ["serve", "--help"])
    assert serve_result.exit_code == 0, _result_error_text(serve_result)

    help_result = runner.invoke(cli.app, ["--help"])
    assert help_result.exit_code == 0, _result_error_text(help_result)
    assert "Start here:" in help_result.stdout
    assert re.search(r"loopora\s+init\s+codex", help_result.stdout)
    assert "task goal" in help_result.stdout
    assert "fake-done risk" in help_result.stdout
    assert "required evidence" in help_result.stdout
    assert "/loopora-gen" in help_result.stdout
    assert "/loopora-loop" in help_result.stdout
    assert "same" in help_result.stdout
    assert "Agent session" in help_result.stdout
    assert help_result.stdout.index("Start here:") < help_result.stdout.index("Expert: create and run")
    assert help_result.stdout.index("│ init") < help_result.stdout.index("│ run")
    assert help_result.stdout.index("│ serve") < help_result.stdout.index("│ run")
    assert help_result.stdout.index("Install /loopora-gen") < help_result.stdout.index(
        "Expert: create and inspect reusable run flows"
    )


def test_cli_package_exposes_loopora_console_script() -> None:
    console_scripts = {
        entry_point.name: entry_point.value
        for entry_point in distribution("loopora").entry_points
        if entry_point.group == "console_scripts"
    }

    assert console_scripts["loopora"] == "loopora.cli:app"


def test_readme_first_use_commands_match_cli_entries() -> None:
    root = Path(__file__).resolve().parents[3]
    english_readme = (root / "README.md").read_text(encoding="utf-8")
    chinese_readme = (root / "README.zh-CN.md").read_text(encoding="utf-8")
    readmes = [english_readme, chinese_readme]
    human_shaped_loop_docs = [
        (root / "HUMAN-SHAPED-LOOP.md").read_text(encoding="utf-8"),
        (root / "HUMAN-SHAPED-LOOP.zh-CN.md").read_text(encoding="utf-8"),
    ]
    agent_first_design = (root / "design" / "core-ideas" / "agent-first-loopora.md").read_text(encoding="utf-8")
    product_principle = (root / "design" / "core-ideas" / "product-principle.md").read_text(encoding="utf-8")
    core_contract = (root / "design" / "core-ideas" / "core-contract.md").read_text(encoding="utf-8")
    web_alignment_design = (root / "design" / "detailed-design" / "09-web-bundle-alignment.md").read_text(
        encoding="utf-8"
    )
    governance_scenario = (root / "tests" / "scenarios" / "long_running_governance_loop.md").read_text(
        encoding="utf-8"
    )
    documented_adapters = [set(re.findall(r"\bloopora init ([a-z]+)\b", readme)) for readme in readmes]

    _assert_readme_entry_points(readmes, documented_adapters)
    _assert_public_anchor_default_language(english_readme, chinese_readme, human_shaped_loop_docs)
    _assert_alignment_language_assets(
        agent_first_design,
        product_principle,
        core_contract,
        web_alignment_design,
        governance_scenario,
    )
    _assert_documented_cli_entries_available(documented_adapters)


def test_cli_help_keeps_first_use_language_on_plan_files() -> None:
    runner = CliRunner()

    root_help = runner.invoke(cli.app, ["--help"])
    assert root_help.exit_code == 0, _result_error_text(root_help)
    assert "Import, export, and manage Loop plan files" in root_help.stdout
    assert "Install /loopora-gen and /loopora-loop project entries" in root_help.stdout
    assert "task goal, fake-done risk, and required evidence" in root_help.stdout
    assert "Remove Loopora-managed Coding Agent project entries" in root_help.stdout
    assert "Internal runtime used by /loopora-gen and /loopora-loop" in root_help.stdout
    assert "project entries" in root_help.stdout
    assert "Import and manage YAML bundles" not in root_help.stdout
    assert "Coding Agent adapters" not in root_help.stdout

    init_group_help = runner.invoke(cli.app, ["init", "--help"])
    assert init_group_help.exit_code == 0, _result_error_text(init_group_help)
    assert "task goal, fake-done risk, and required evidence" in init_group_help.stdout

    init_help = runner.invoke(cli.app, ["init", "codex", "--help"])
    assert init_help.exit_code == 0, _result_error_text(init_help)
    assert "Install or update the Codex project entry for task-judgment first" in init_help.stdout
    assert "task goal" in init_help.stdout
    assert "fake-done risk" in init_help.stdout
    assert "required" in init_help.stdout
    assert "evidence" in init_help.stdout
    assert "/loopora-gen" in init_help.stdout
    assert "READY Loop preview" in init_help.stdout
    assert "/loopora-loop" in init_help.stdout
    assert "same Agent session" in init_help.stdout
    assert "Project directory where the Coding Agent will" in init_help.stdout
    assert "work." in init_help.stdout
    assert "adapter" not in init_help.stdout.lower()

    uninstall_help = runner.invoke(cli.app, ["uninstall", "codex", "--help"])
    assert uninstall_help.exit_code == 0, _result_error_text(uninstall_help)
    assert "Remove the Loopora-managed Codex project entry." in uninstall_help.stdout
    assert "Project directory where the Coding Agent will" in uninstall_help.stdout
    assert "work." in uninstall_help.stdout
    assert "adapter" not in uninstall_help.stdout.lower()

    agent_help = runner.invoke(cli.app, ["agent", "codex", "gen", "--help"])
    assert agent_help.exit_code == 0, _result_error_text(agent_help)
    assert "Validate a generated Loop plan and return the Loop preview URL." in agent_help.stdout
    assert "Candidate Loop plan file" in agent_help.stdout
    assert "produced by the Coding Agent." in agent_help.stdout
    assert "--plan-file" in agent_help.stdout
    assert "Candidate Loopora bundle YAML" not in agent_help.stdout

    agent_group_help = runner.invoke(cli.app, ["agent", "codex", "--help"])
    assert agent_group_help.exit_code == 0, _result_error_text(agent_group_help)
    assert "Internal Codex runtime used by Loopora project entries" in agent_group_help.stdout
    assert "adapter runtime" not in agent_group_help.stdout.lower()

    import_help = runner.invoke(cli.app, ["bundles", "import", "--help"])
    assert import_help.exit_code == 0, _result_error_text(import_help)
    assert "Import one Loop plan file and materialize its run-ready assets." in import_help.stdout
    assert "Path to a Loop plan file" in import_help.stdout
    assert "YAML bundle" not in import_help.stdout


def test_design_main_workflow_anchors_separate_run_status_and_loop_verdict() -> None:
    root = Path(__file__).resolve().parents[3]
    design_sources = {
        "design/README.md": (root / "design" / "README.md").read_text(encoding="utf-8"),
        "design/core-ideas/README.md": (root / "design" / "core-ideas" / "README.md").read_text(encoding="utf-8"),
        "design/core-ideas/product-principle.md": (
            root / "design" / "core-ideas" / "product-principle.md"
        ).read_text(encoding="utf-8"),
        "design/core-ideas/concept-map.md": (root / "design" / "core-ideas" / "concept-map.md").read_text(
            encoding="utf-8"
        ),
        "design/core-ideas/task-scoped-alignment.md": (
            root / "design" / "core-ideas" / "task-scoped-alignment.md"
        ).read_text(encoding="utf-8"),
    }

    full_workflow = "`编排 Loop -> 运行 Loop -> 自动迭代并收集证据 -> 输出运行状态、Loop 裁决与结果`"
    runtime_tail = "`运行 Loop -> 自动迭代并收集证据 -> 输出运行状态、Loop 裁决与结果`"
    assert full_workflow in design_sources["design/README.md"]
    assert full_workflow in design_sources["design/core-ideas/README.md"]
    assert full_workflow in design_sources["design/core-ideas/product-principle.md"]
    assert full_workflow in design_sources["design/core-ideas/concept-map.md"]
    assert runtime_tail in design_sources["design/core-ideas/task-scoped-alignment.md"]
    assert "运行状态与 Loop 裁决必须分开表达" in design_sources["design/core-ideas/concept-map.md"]
    assert "Web 内置对话编排入口" in design_sources["design/README.md"]
    assert "Web 内置任务对齐入口" not in design_sources["design/README.md"]

    for name, source in design_sources.items():
        assert "输出证据裁决与结果" not in source, name


def test_interface_design_uses_loop_verdict_for_user_result_surface() -> None:
    root = Path(__file__).resolve().parents[3]
    interface_design = (root / "design" / "detailed-design" / "05-interfaces.md").read_text(encoding="utf-8")

    assert "查看 Loop 裁决后" in interface_design
    assert "Loopora fit、执行策略、判断取舍、本地治理责任与角色姿态" in interface_design
    assert "evidence verdict" not in interface_design


def test_runtime_design_uses_loop_verdict_for_chinese_result_surface() -> None:
    root = Path(__file__).resolve().parents[3]
    design_paths = [
        root / "design" / "detailed-design" / "02-orchestration-service.md",
        root / "design" / "detailed-design" / "07-observability-and-diagnostics.md",
        root / "design" / "detailed-design" / "08-bundles-and-alignment.md",
        root / "design" / "detailed-design" / "09-web-bundle-alignment.md",
    ]

    for path in design_paths:
        source = path.read_text(encoding="utf-8")
        assert "Loop 裁决" in source, path.name
        assert "任务裁决" not in source, path.name


def test_workflow_design_freezes_execution_strategy_in_runtime_contract() -> None:
    root = Path(__file__).resolve().parents[3]
    workflow_design = (root / "design" / "detailed-design" / "06-workflow-and-prompts.md").read_text(
        encoding="utf-8"
    )

    frozen_fields = (
        "Task / Done When / Guardrails / Success Surface / Fake Done / Evidence Preferences / "
        "Execution Strategy / Judgment Tradeoffs / Local Governance / Residual Risk"
    )
    assert frozen_fields in workflow_design
    assert "Evidence Preferences / Judgment Tradeoffs / Local Governance / Residual Risk" not in workflow_design
    assert "已进入运行责任链的本地治理" in workflow_design
    assert "形成 Builder 读取、Inspector / Custom 验证、GateKeeper 阻断 / 弱证据处理链路" in workflow_design


def test_bundle_alignment_design_traceability_includes_local_governance() -> None:
    root = Path(__file__).resolve().parents[3]
    bundle_design = (root / "design" / "detailed-design" / "08-bundles-and-alignment.md").read_text(
        encoding="utf-8"
    )
    web_alignment_design = (root / "design" / "detailed-design" / "09-web-bundle-alignment.md").read_text(
        encoding="utf-8"
    )
    agent_adapter_design = (root / "design" / "detailed-design" / "10-agent-adapters.md").read_text(
        encoding="utf-8"
    )

    assert "执行策略、残余风险、本地治理责任、判断取舍" in bundle_design
    assert "本地治理责任不能只停留在 `collaboration_summary`" in bundle_design
    assert "`spec.markdown` 的 `Role Notes`" in bundle_design
    assert "本地治理责任没有进入 `Role Notes` / 角色 prompt / posture / `workflow`" in bundle_design
    assert "残余风险策略只有命名可接受风险及其负责人" in bundle_design
    assert "本地治理责任的预览卡片只展示已形成 Builder 读取" in bundle_design
    assert "READY 预览、导入或 Agent-first `/loopora-loop` 启动前必须重新读取当前 canonical `bundle.yml`" in bundle_design
    assert "旧 `validation.json` 或 DB validation 不能让已被改坏或指向其他目录的文件继续成为候选来源" in bundle_design
    assert "`spec.markdown` / `Role Notes`" in web_alignment_design
    assert "空泛风险话术只能暴露为 warning 和 traceability 缺口" in web_alignment_design
    assert "本地治理责任卡片只展示已形成 Builder 读取" in web_alignment_design
    assert "READY 预览必须读取当前 canonical `artifacts/bundle.yml`" in web_alignment_design
    assert "旧 validation 不能让已被改坏或指向其他目录的文件继续成为可改进来源" in web_alignment_design
    assert "重新读取当前 bundle 文件并执行同一套结构、语义与 traceability 校验" in agent_adapter_design
    assert "binding 与 alignment session 的 workdir 都等于当前 adapter root" in agent_adapter_design
    assert "冻结 `judgment_contract` 投影" in agent_adapter_design


def test_cli_run_result_separates_run_status_and_task_verdict(capsys, tmp_path: Path) -> None:
    print_run_result(
        {
            "id": "run_contract",
            "status": "succeeded",
            "run_status": "succeeded",
            "runs_dir": str(tmp_path / "runs" / "run_contract"),
            "task_verdict": {
                "status": "insufficient_evidence",
                "source": "rounds_completion",
                "summary": "The run ended, but evidence is still too thin.",
            },
        }
    )

    output = capsys.readouterr().out
    assert "run_status: succeeded" in output
    assert "task_verdict: insufficient_evidence" in output
    assert "task_verdict_source: rounds_completion" in output
    assert "task_verdict_summary: The run ended, but evidence is still too thin." in output


def test_cli_run_result_prints_not_evaluated_when_task_verdict_is_missing(capsys, tmp_path: Path) -> None:
    print_run_result(
        {
            "id": "run_legacy",
            "status": "succeeded",
            "run_status": "succeeded",
            "runs_dir": str(tmp_path / "runs" / "run_legacy"),
        }
    )

    output = capsys.readouterr().out
    assert "run_status: succeeded" in output
    assert "task_verdict: not_evaluated" in output


def test_cli_run_result_prints_frozen_judgment_contract_summary(capsys, tmp_path: Path) -> None:
    layout = RunArtifactLayout(tmp_path / "runs" / "run_bundle")
    layout.initialize()
    layout.run_contract_path.write_text(
        json.dumps(
            {
                "collaboration_summary": "Prefer proof before speed.",
                "loop_fit_reasons": ["Future rounds keep proof alive."],
                "judgment_tradeoffs": ["Proof beats speed when closure is uncertain."],
                "execution_strategy": ["Prove the focused path first, then expand after evidence is strong."],
                "local_governance": ["GateKeeper treats skipped tests/ evidence as Blocking."],
                "role_postures": [
                    {
                        "role_name": "GateKeeper",
                        "archetype": "gatekeeper",
                        "posture_notes": "Fail closed when evidence is weak.",
                    }
                ],
                "source_bundle": {
                    "id": "bundle_cli",
                    "name": "CLI Frozen Contract Bundle",
                    "revision": 3,
                    "imported_from_path": "/tmp/loopora/cli-bundle.yml",
                    "bundle_sha256": "abcdef1234567890",
                    "bundle_bytes": 2048,
                },
                "completion_mode": "gatekeeper",
                "workflow": {
                    "preset": "build_then_parallel_review",
                    "collaboration_intent": "Builder evidence feeds Inspector review before GateKeeper closure.",
                },
                "compiled_spec": {
                    "goal": "Ship the requested behavior.",
                    "check_mode": "specified",
                    "checks": [{"id": "check_001"}, {"id": "check_002"}],
                    "coverage_targets": [
                        {"id": "done_when.check_001", "required": True},
                        {"id": "gatekeeper.finish", "required": True},
                    ],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print_run_result(
        {
            "id": "run_bundle",
            "status": "succeeded",
            "run_status": "succeeded",
            "runs_dir": str(layout.run_dir),
            "task_verdict": {"status": "passed"},
        }
    )

    output = capsys.readouterr().out
    assert f"run_contract_path: {layout.run_contract_path}" in output
    assert "source_plan: CLI Frozen Contract Bundle (bundle_cli, rev 3)" in output
    assert "source_plan_path: /tmp/loopora/cli-bundle.yml" in output
    assert "source_plan_digest: sha256:abcdef123456, 2048 bytes" in output
    assert 'source_plan: {"id":' not in output
    assert "judgment_contract_summary: Prefer proof before speed." in output
    assert "check_mode: specified" in output
    assert "completion_mode: gatekeeper" in output
    assert "workflow_preset: build_then_parallel_review" in output
    assert "workflow_collaboration_intent: Builder evidence feeds Inspector review before GateKeeper closure." in output
    assert "check_count: 2" in output
    _assert_cli_list(output, "coverage_targets", "done_when.check_001 (required)", "gatekeeper.finish (required)")
    _assert_cli_list(output, "loop_fit_reasons", "Future rounds keep proof alive.")
    _assert_cli_list(output, "judgment_tradeoffs", "Proof beats speed when closure is uncertain.")
    _assert_cli_list(
        output,
        "execution_strategy",
        "Prove the focused path first, then expand after evidence is strong.",
    )
    _assert_cli_list(output, "local_governance", "GateKeeper treats skipped tests/ evidence as Blocking.")
    _assert_cli_list(output, "role_postures", "GateKeeper: Fail closed when evidence is weak.")


def test_cli_run_result_marks_truncated_judgment_summary(capsys, tmp_path: Path) -> None:
    layout = RunArtifactLayout(tmp_path / "runs" / "run_long_contract")
    layout.initialize()
    layout.run_contract_path.write_text(
        json.dumps(
            {
                "collaboration_summary": " ".join(["Evidence must stay visible before closure"] * 20),
                "completion_mode": "gatekeeper",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print_run_result(
        {
            "id": "run_long_contract",
            "status": "awaiting_agent",
            "run_status": "awaiting_agent",
            "runs_dir": str(layout.run_dir),
        }
    )

    output = capsys.readouterr().out
    summary_line = next(line for line in output.splitlines() if line.startswith("judgment_contract_summary: "))
    assert summary_line.endswith("...")
    assert len(summary_line) < 280


def test_cli_run_allows_zero_max_iters(monkeypatch, tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("# Task\n\nKeep going.\n", encoding="utf-8")
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    calls: dict[str, object] = {}

    class FakeService:
        def create_loop(self, **kwargs):
            calls["create_loop"] = kwargs
            return {"id": "loop_test"}

        def rerun(self, loop_id: str, *, background: bool = False):
            calls["rerun"] = loop_id
            calls["background"] = background
            return {"id": "run_test", "status": "running", "runs_dir": str(tmp_path / "runs" / "run_test")}

    monkeypatch.setattr(cli, "create_service", FakeService)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "run",
            "--spec",
            str(spec_path),
            "--workdir",
            str(workdir),
            "--max-iters",
            "0",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert calls["create_loop"]["max_iters"] == 0
    assert calls["rerun"] == "loop_test"
    assert calls["background"] is False


def test_cli_loop_creation_emits_structured_logs(monkeypatch, tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("# Task\n\nKeep going.\n", encoding="utf-8")
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    class FakeService:
        def create_loop(self, **kwargs):
            return {"id": "loop_logged", "name": kwargs["name"], "workdir": str(kwargs["workdir"])}

        def rerun(self, loop_id: str, *, background: bool = False):
            raise AssertionError(f"loop creation without --start should not rerun: {loop_id=} {background=}")

    monkeypatch.setattr(cli, "create_service", FakeService)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "loops",
            "create",
            "--spec",
            str(spec_path),
            "--workdir",
            str(workdir),
            "--name",
            "Logged Loop",
        ],
    )

    assert result.exit_code == 0, result.stdout
    records = [
        json.loads(line)
        for line in (app_home() / "logs" / "service.log").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    created_record = next(item for item in records if item["event"] == "cli.loop.create.completed")
    assert created_record["loop_id"] == "loop_logged"
    assert created_record["context"]["start"] is False


def test_cli_loop_create_accepts_parallel_workflow_file(monkeypatch, tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("# Task\n\nKeep going.\n", encoding="utf-8")
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    workflow_path = tmp_path / "workflow.yml"
    workflow_path.write_text(
        """
version: 1
collaboration_intent: "Build first, then inspect contract and evidence in parallel before GateKeeper closes."
roles:
  - id: builder
    archetype: builder
    prompt_ref: builder.md
  - id: contract_inspector
    name: Contract Inspector
    archetype: inspector
    prompt_ref: inspector.md
  - id: evidence_inspector
    name: Evidence Inspector
    archetype: inspector
    prompt_ref: inspector.md
  - id: gatekeeper
    archetype: gatekeeper
    prompt_ref: gatekeeper.md
steps:
  - id: builder_step
    role_id: builder
  - id: contract_inspection_step
    role_id: contract_inspector
    parallel_group: inspection_pack
    inputs:
      handoffs_from: ["builder_step"]
      evidence_query:
        archetypes: ["builder"]
        limit: 8
      iteration_memory: summary_only
  - id: evidence_inspection_step
    role_id: evidence_inspector
    parallel_group: inspection_pack
    inputs:
      handoffs_from: ["builder_step"]
  - id: gatekeeper_step
    role_id: gatekeeper
    on_pass: finish_run
    inputs:
      handoffs_from: ["contract_inspection_step", "evidence_inspection_step"]
controls:
  - id: stale_evidence_check
    when:
      signal: no_evidence_progress
      after: 20m
    call:
      role_id: evidence_inspector
    mode: repair_guidance
    max_fires_per_run: 1
""",
        encoding="utf-8",
    )
    calls: dict[str, object] = {}

    class FakeService:
        def create_loop(self, **kwargs):
            calls["create_loop"] = kwargs
            return {"id": "loop_parallel", "name": kwargs["name"], "workdir": str(kwargs["workdir"])}

        def rerun(self, loop_id: str, *, background: bool = False):
            raise AssertionError(f"loop creation without --start should not rerun: {loop_id=} {background=}")

    monkeypatch.setattr(cli, "create_service", FakeService)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "loops",
            "create",
            "--spec",
            str(spec_path),
            "--workdir",
            str(workdir),
            "--workflow-file",
            str(workflow_path),
        ],
    )

    assert result.exit_code == 0, result.stdout
    workflow = calls["create_loop"]["workflow"]
    assert workflow["steps"][1]["parallel_group"] == "inspection_pack"
    assert workflow["steps"][1]["inputs"]["evidence_query"]["archetypes"] == ["builder"]
    assert workflow["steps"][3]["inputs"]["handoffs_from"] == [
        "contract_inspection_step",
        "evidence_inspection_step",
    ]
    assert workflow["controls"][0]["when"]["signal"] == "no_evidence_progress"
    assert workflow["controls"][0]["call"]["role_id"] == "evidence_inspector"


def test_cli_run_supports_command_mode_background_and_role_models(monkeypatch, tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("# Task\n\nKeep going.\n", encoding="utf-8")
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    calls: dict[str, object] = {}

    class FakeService:
        def create_loop(self, **kwargs):
            calls["create_loop"] = kwargs
            return {"id": "loop_cmd", "name": kwargs["name"], "workdir": str(kwargs["workdir"])}

        def start_run(self, loop_id: str):
            calls["start_run"] = loop_id
            return {
                "id": "run_cmd",
                "status": "queued",
                "runs_dir": str(tmp_path / "runs" / "run_cmd"),
                "workdir": str(workdir),
            }

        def rerun(self, loop_id: str, *, background: bool = False):
            raise AssertionError(f"background CLI path should not call service.rerun(): {loop_id=} {background=}")

    monkeypatch.setattr(cli, "create_service", FakeService)

    def fake_spawn_background_worker(_service, run: dict):
        calls["spawned_run_id"] = run["id"]
        return run

    monkeypatch.setattr(cli, "_spawn_background_worker", fake_spawn_background_worker)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "run",
            "--spec",
            str(spec_path),
            "--workdir",
            str(workdir),
            "--executor",
            "codex",
            "--executor-mode",
            "command",
            "--command-cli",
            "codex",
            "--command-arg",
            "exec",
            "--command-arg",
            "--json",
            "--command-arg",
            "--output-schema",
            "--command-arg",
            "{schema_path}",
            "--command-arg",
            "--output-last-message",
            "--command-arg",
            "{output_path}",
            "--command-arg",
            "--model",
            "--command-arg",
            "{model}",
            "--command-arg",
            "{prompt}",
            "--model",
            "gpt-5.4-mini",
            "--role-model",
            "generator=gpt-5.4",
            "--role-model",
            "verifier=gpt-5.4-mini",
            "--background",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert calls["start_run"] == "loop_cmd"
    assert calls["spawned_run_id"] == "run_cmd"
    assert calls["create_loop"]["executor_mode"] == "command"
    assert calls["create_loop"]["command_cli"] == "codex"
    assert "{schema_path}" in calls["create_loop"]["command_args_text"]
    assert "{model}" in calls["create_loop"]["command_args_text"]
    assert calls["create_loop"]["role_models"] == {
        "builder": "gpt-5.4",
        "gatekeeper": "gpt-5.4-mini",
    }


def test_cli_run_supports_round_completion_and_iteration_interval(monkeypatch, tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("# Task\n\nKeep going.\n", encoding="utf-8")
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    calls: dict[str, object] = {}

    class FakeService:
        def create_loop(self, **kwargs):
            calls["create_loop"] = kwargs
            return {"id": "loop_rounds"}

        def rerun(self, loop_id: str, *, background: bool = False):
            assert background is False
            calls["rerun"] = loop_id
            return {"id": "run_rounds", "status": "succeeded", "runs_dir": str(tmp_path / "runs" / "run_rounds")}

    monkeypatch.setattr(cli, "create_service", FakeService)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "run",
            "--spec",
            str(spec_path),
            "--workdir",
            str(workdir),
            "--completion-mode",
            "rounds",
            "--iteration-interval-seconds",
            "60",
            "--max-iters",
            "2",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert calls["create_loop"]["completion_mode"] == "rounds"
    assert calls["create_loop"]["iteration_interval_seconds"] == 60.0
    assert calls["rerun"] == "loop_rounds"


def test_cli_loops_rerun_background_spawns_worker(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {}

    class FakeService:
        def start_run(self, loop_id: str):
            calls["start_run"] = loop_id
            return {
                "id": "run_background",
                "status": "queued",
                "runs_dir": str(tmp_path / "runs" / "run_background"),
                "workdir": str(tmp_path / "workdir"),
            }

        def rerun(self, loop_id: str, *, background: bool = False):
            raise AssertionError(f"background CLI path should not call service.rerun(): {loop_id=} {background=}")

    monkeypatch.setattr(cli, "create_service", FakeService)

    def fake_spawn_background_worker(_service, run: dict):
        calls["spawned"] = run["id"]
        return run

    monkeypatch.setattr(cli, "_spawn_background_worker", fake_spawn_background_worker)
    runner = CliRunner()

    result = runner.invoke(cli.app, ["loops", "rerun", "loop_saved", "--background"])

    assert result.exit_code == 0, result.stdout
    assert calls["start_run"] == "loop_saved"
    assert calls["spawned"] == "run_background"


def test_cli_loops_create_can_save_without_starting(monkeypatch, tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("# Task\n\nKeep going.\n", encoding="utf-8")
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    calls: dict[str, object] = {}

    class FakeService:
        def create_loop(self, **kwargs):
            calls["create_loop"] = kwargs
            return {"id": "loop_saved", "name": kwargs["name"], "workdir": str(kwargs["workdir"])}

        def rerun(self, loop_id: str, *, background: bool = False):
            calls["rerun"] = (loop_id, background)
            return {"id": "run_saved", "status": "queued", "runs_dir": str(tmp_path / "runs" / "run_saved")}

    monkeypatch.setattr(cli, "create_service", FakeService)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "loops",
            "create",
            "--spec",
            str(spec_path),
            "--workdir",
            str(workdir),
            "--name",
            "Saved Loop",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert calls["create_loop"]["name"] == "Saved Loop"
    assert "rerun" not in calls


def test_cli_loops_create_accepts_orchestration_id(monkeypatch, tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("# Task\n\nKeep going.\n", encoding="utf-8")
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    calls: dict[str, object] = {}

    class FakeService:
        def create_loop(self, **kwargs):
            calls["create_loop"] = kwargs
            return {"id": "loop_saved", "name": kwargs["name"], "workdir": str(kwargs["workdir"])}

    monkeypatch.setattr(cli, "create_service", FakeService)
    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "loops",
            "create",
            "--spec",
            str(spec_path),
            "--workdir",
            str(workdir),
            "--orchestration-id",
            "builtin:inspect_first",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert calls["create_loop"]["orchestration_id"] == "builtin:inspect_first"
    assert calls["create_loop"]["workflow"] is None


def test_cli_orchestrations_create_and_list(monkeypatch) -> None:
    calls: dict[str, object] = {}

    class FakeService:
        def create_orchestration(self, **kwargs):
            calls["create_orchestration"] = kwargs
            return {"id": "orch_1", "name": kwargs["name"], "workflow_json": {"roles": [], "steps": []}}

        def list_orchestrations(self):
            return [
                {"id": "builtin:build_first", "name": "Build First", "source": "builtin", "workflow_json": {"roles": [1], "steps": [1]}},
                {"id": "orch_1", "name": "Custom", "source": "custom", "workflow_json": {"roles": [1, 2], "steps": [1, 2]}},
            ]

    monkeypatch.setattr(cli, "create_service", FakeService)
    runner = CliRunner()

    create_result = runner.invoke(cli.app, ["orchestrations", "create", "--name", "Custom", "--workflow-preset", "inspect_first"])
    assert create_result.exit_code == 0, create_result.stdout
    assert calls["create_orchestration"]["name"] == "Custom"
    assert calls["create_orchestration"]["workflow"] == {"preset": "inspect_first"}

    list_result = runner.invoke(cli.app, ["orchestrations", "list"])
    assert list_result.exit_code == 0, list_result.stdout
    assert "builtin:build_first" in list_result.stdout
    assert "orch_1" in list_result.stdout


def test_cli_orchestrations_get_update_derive_and_delete(monkeypatch) -> None:
    calls: dict[str, object] = {}

    current = {
        "id": "orch_1",
        "name": "Current",
        "description": "Saved orchestration",
        "workflow_json": {"preset": "inspect_first"},
        "prompt_files_json": {"builder.md": "---\nversion: 1\narchetype: builder\n---\nBuilder body\n"},
        "role_models_json": {"builder": "gpt-5.4-mini"},
    }

    class FakeService:
        def get_orchestration(self, orchestration_id: str):
            calls.setdefault("get_ids", []).append(orchestration_id)
            if orchestration_id == "builtin:build_first":
                return {
                    "id": "builtin:build_first",
                    "name": "Build First",
                    "description": "Built-in",
                    "workflow_json": {"preset": "build_first"},
                    "prompt_files_json": {},
                    "role_models_json": {},
                }
            return current

        def update_orchestration(self, orchestration_id: str, **kwargs):
            calls["update"] = (orchestration_id, kwargs)
            return {"id": orchestration_id, **kwargs, "workflow_json": kwargs["workflow"]}

        def create_orchestration(self, **kwargs):
            calls.setdefault("create", []).append(kwargs)
            return {"id": "orch_new", **kwargs, "workflow_json": kwargs["workflow"]}

        def delete_orchestration(self, orchestration_id: str):
            calls["delete"] = orchestration_id
            return {"id": orchestration_id, "deleted": True}

    monkeypatch.setattr(cli, "create_service", FakeService)
    runner = CliRunner()

    get_result = runner.invoke(cli.app, ["orchestrations", "get", "orch_1"])
    assert get_result.exit_code == 0, get_result.stdout
    assert json.loads(get_result.stdout)["id"] == "orch_1"

    update_result = runner.invoke(cli.app, ["orchestrations", "update", "orch_1", "--name", "Updated", "--workflow-preset", "repair_loop"])
    assert update_result.exit_code == 0, update_result.stdout
    update_id, update_kwargs = calls["update"]
    assert update_id == "orch_1"
    assert update_kwargs["name"] == "Updated"
    assert update_kwargs["workflow"] == {"preset": "repair_loop"}

    derive_result = runner.invoke(cli.app, ["orchestrations", "derive", "builtin:build_first", "--name", "Derived"])
    assert derive_result.exit_code == 0, derive_result.stdout
    assert calls["create"][-1]["name"] == "Derived"
    assert calls["create"][-1]["workflow"] == {"preset": "build_first"}

    delete_result = runner.invoke(cli.app, ["orchestrations", "delete", "orch_1"])
    assert delete_result.exit_code == 0, delete_result.stdout
    assert calls["delete"] == "orch_1"


def test_cli_loops_delete_prints_json(monkeypatch) -> None:
    class FakeService:
        def delete_loop(self, loop_id: str):
            return {"id": loop_id, "deleted_runs": 2, "workdir": "/tmp/project"}

    monkeypatch.setattr(cli, "create_service", FakeService)
    runner = CliRunner()

    result = runner.invoke(cli.app, ["loops", "delete", "loop_test"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["id"] == "loop_test"
    assert payload["deleted_runs"] == 2


def test_cli_roles_list_get_create_update_derive_and_delete(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {}
    prompt_path = tmp_path / "builder.md"
    prompt_path.write_text("---\nversion: 1\narchetype: builder\n---\nBuilder body\n", encoding="utf-8")

    current = {
        "id": "role_custom",
        "name": "Custom Builder",
        "description": "Saved builder",
        "archetype": "builder",
        "prompt_ref": "custom-builder.md",
        "prompt_markdown": "---\nversion: 1\narchetype: builder\n---\nCurrent builder body\n",
        "executor_kind": "codex",
        "executor_mode": "preset",
        "command_cli": "codex",
        "command_args_text": "",
        "model": "gpt-5.4-mini",
        "reasoning_effort": "medium",
    }

    class FakeService:
        def list_role_definitions(self):
            return [
                {"id": "builtin:builder", "name": "Builder", "source": "builtin", "archetype": "builder", "executor_kind": "codex"},
                {"id": "role_custom", "name": "Custom Builder", "source": "custom", "archetype": "builder", "executor_kind": "codex"},
            ]

        def get_role_definition(self, role_definition_id: str):
            calls.setdefault("get_ids", []).append(role_definition_id)
            if role_definition_id == "builtin:builder":
                return {
                    "id": "builtin:builder",
                    "name": "Builder",
                    "description": "Built-in",
                    "archetype": "builder",
                    "prompt_ref": "builder.md",
                    "prompt_markdown": "---\nversion: 1\narchetype: builder\n---\nBuiltin builder body\n",
                    "executor_kind": "codex",
                    "executor_mode": "preset",
                    "command_cli": "codex",
                    "command_args_text": "",
                    "model": "gpt-5.4",
                    "reasoning_effort": "medium",
                }
            return current

        def create_role_definition(self, **kwargs):
            calls.setdefault("create", []).append(kwargs)
            return {"id": "role_new", **kwargs}

        def update_role_definition(self, role_definition_id: str, **kwargs):
            calls["update"] = (role_definition_id, kwargs)
            return {"id": role_definition_id, **kwargs}

        def delete_role_definition(self, role_definition_id: str):
            calls["delete"] = role_definition_id
            return {"id": role_definition_id, "deleted": True}

    monkeypatch.setattr(cli, "create_service", FakeService)
    runner = CliRunner()

    list_result = runner.invoke(cli.app, ["roles", "list"])
    assert list_result.exit_code == 0, list_result.stdout
    assert "builtin:builder" in list_result.stdout

    get_result = runner.invoke(cli.app, ["roles", "get", "role_custom"])
    assert get_result.exit_code == 0, get_result.stdout
    assert json.loads(get_result.stdout)["id"] == "role_custom"

    create_result = runner.invoke(cli.app, ["roles", "create", "--name", "New Builder", "--archetype", "builder", "--prompt-file", str(prompt_path)])
    assert create_result.exit_code == 0, create_result.stdout
    assert calls["create"][0]["name"] == "New Builder"
    assert "Builder body" in calls["create"][0]["prompt_markdown"]

    update_result = runner.invoke(cli.app, ["roles", "update", "role_custom", "--name", "Updated Builder", "--prompt-file", str(prompt_path)])
    assert update_result.exit_code == 0, update_result.stdout
    update_id, update_kwargs = calls["update"]
    assert update_id == "role_custom"
    assert update_kwargs["name"] == "Updated Builder"
    assert update_kwargs["prompt_ref"] == "custom-builder.md"

    derive_result = runner.invoke(cli.app, ["roles", "derive", "builtin:builder", "--name", "Derived Builder"])
    assert derive_result.exit_code == 0, derive_result.stdout
    assert calls["create"][-1]["name"] == "Derived Builder"
    assert calls["create"][-1]["archetype"] == "builder"

    delete_result = runner.invoke(cli.app, ["roles", "delete", "role_custom"])
    assert delete_result.exit_code == 0, delete_result.stdout
    assert calls["delete"] == "role_custom"


def test_cli_spec_init_accepts_locale_and_validate_reports_check_mode(tmp_path: Path) -> None:
    spec_path = tmp_path / "created-spec.md"
    runner = CliRunner()

    init_result = runner.invoke(cli.app, ["spec", "init", "--locale", "en", str(spec_path)])

    assert init_result.exit_code == 0, init_result.stdout
    created_text = spec_path.read_text(encoding="utf-8")
    assert "# Task" in created_text
    assert "# Done When" in created_text
    assert "# Guardrails" in created_text
    assert "# Role Notes" in created_text
    assert "delete `# Done When`" in created_text

    validate_result = runner.invoke(cli.app, ["spec", "validate", str(spec_path)])

    assert validate_result.exit_code == 0, validate_result.stdout
    payload = json.loads(validate_result.stdout)
    assert payload["ok"] is True
    assert payload["check_mode"] == "specified"

    invalid_spec_path = tmp_path / "invalid-spec.md"
    invalid_spec_path.write_bytes(b"\xff")
    invalid_result = runner.invoke(cli.app, ["spec", "validate", str(invalid_spec_path)])
    assert invalid_result.exit_code == 1
    assert "UTF-8 encoded Markdown" in _result_error_text(invalid_result)


def test_cli_spec_init_accepts_workflow_preset(tmp_path: Path) -> None:
    spec_path = tmp_path / "repair-loop-spec.md"
    runner = CliRunner()

    result = runner.invoke(cli.app, ["spec", "init", "--locale", "en", "--workflow-preset", "repair_loop", str(spec_path)])

    assert result.exit_code == 0, result.stdout
    created_text = spec_path.read_text(encoding="utf-8")
    assert "## Builder Notes" in created_text
    assert "## Regression Inspector Notes" in created_text
    assert "## Contract Inspector Notes" in created_text
    assert "## Guide Notes" in created_text
    assert "## GateKeeper Notes" in created_text
    assert created_text.count("## Builder Notes") == 1


def test_cli_spec_template_read_and_write(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    spec_path = tmp_path / "spec.md"
    source_path = tmp_path / "source.md"
    source_path.write_text("# Task\n\nUpdated task.\n", encoding="utf-8")

    class FakeService:
        def get_orchestration(self, orchestration_id: str):
            assert orchestration_id == "builtin:repair_loop"
            return {"workflow_json": {"preset": "repair_loop"}}

    monkeypatch.setattr(cli, "create_service", FakeService)

    template_result = runner.invoke(
        cli.app,
        ["spec", "template", "--locale", "en", "--orchestration-id", "builtin:repair_loop", "--json"],
    )
    assert template_result.exit_code == 0, template_result.stdout
    template_payload = json.loads(template_result.stdout)
    assert "# Task" in template_payload["markdown"]
    assert any(item["heading"] == "Builder Notes" for item in template_payload["role_note_sections"])

    write_result = runner.invoke(cli.app, ["spec", "write", str(spec_path), "--from-file", str(source_path)])
    assert write_result.exit_code == 0, write_result.stdout
    write_payload = json.loads(write_result.stdout)
    assert write_payload["validation"]["ok"] is True

    read_result = runner.invoke(cli.app, ["spec", "read", str(spec_path)])
    assert read_result.exit_code == 0, read_result.stdout
    read_payload = json.loads(read_result.stdout)
    assert read_payload["content"] == "# Task\n\nUpdated task.\n"
    assert read_payload["validation"]["ok"] is True

    invalid_source_path = tmp_path / "invalid-source.md"
    invalid_source_path.write_bytes(b"\xff")
    invalid_read = runner.invoke(cli.app, ["spec", "read", str(invalid_source_path)])
    assert invalid_read.exit_code == 1
    assert "UTF-8 encoded Markdown" in _result_error_text(invalid_read)
    invalid_write = runner.invoke(cli.app, ["spec", "write", str(spec_path), "--from-file", str(invalid_source_path)])
    assert invalid_write.exit_code == 1
    assert "UTF-8 encoded Markdown" in _result_error_text(invalid_write)


def test_cli_prompts_list_template_and_validate(tmp_path: Path) -> None:
    runner = CliRunner()
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("---\nversion: 1\narchetype: builder\n---\nPrompt body.\n", encoding="utf-8")

    list_result = runner.invoke(cli.app, ["prompts", "list"])
    assert list_result.exit_code == 0, list_result.stdout
    assert any(item["prompt_ref"] == "builder.md" for item in json.loads(list_result.stdout))

    template_result = runner.invoke(cli.app, ["prompts", "template", "builder.md", "--locale", "en"])
    assert template_result.exit_code == 0, template_result.stdout
    assert "version: 1" in template_result.stdout

    validate_result = runner.invoke(cli.app, ["prompts", "validate", str(prompt_path), "--archetype", "builder"])
    assert validate_result.exit_code == 0, validate_result.stdout
    payload = json.loads(validate_result.stdout)
    assert payload["ok"] is True
    assert payload["metadata"]["archetype"] == "builder"

    invalid_prompt_path = tmp_path / "invalid-prompt.md"
    invalid_prompt_path.write_bytes(b"\xff")
    invalid_result = runner.invoke(cli.app, ["prompts", "validate", str(invalid_prompt_path)])
    assert invalid_result.exit_code == 1
    assert "UTF-8 encoded Markdown" in _result_error_text(invalid_result)


def test_cli_bundles_import_export_derive_and_delete(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {}
    runner = CliRunner()
    bundle_path = tmp_path / "task-bundle.yml"
    bundle_path.write_text(
        bundle_to_yaml(
            {
                "version": 1,
                "metadata": {"name": "CLI Bundle", "description": "", "revision": 1},
                "collaboration_summary": "Prefer evidence over rush.",
                "loop": {
                    "name": "CLI Bundle Loop",
                    "workdir": str(tmp_path / "workdir"),
                    "completion_mode": "gatekeeper",
                    "executor_kind": "codex",
                    "executor_mode": "preset",
                    "command_cli": "codex",
                    "command_args_text": "",
                    "model": "",
                    "reasoning_effort": "",
                    "iteration_interval_seconds": 0,
                    "max_iters": 2,
                    "max_role_retries": 1,
                    "delta_threshold": 0.005,
                    "trigger_window": 2,
                    "regression_window": 2,
                },
                "spec": {"markdown": "# Task\n\nShip the change.\n\n# Done When\n- It works.\n"},
                "role_definitions": [
                    {
                        "key": "builder",
                        "name": "Builder",
                        "description": "",
                        "archetype": "builder",
                        "prompt_ref": "builder.md",
                        "prompt_markdown": "---\nversion: 1\narchetype: builder\n---\nBuild it.\n",
                        "posture_notes": "Favor maintainability when possible.",
                        "executor_kind": "codex",
                        "executor_mode": "preset",
                        "command_cli": "codex",
                        "command_args_text": "",
                        "model": "",
                        "reasoning_effort": "",
                    },
                    {
                        "key": "gatekeeper",
                        "name": "GateKeeper",
                        "description": "",
                        "archetype": "gatekeeper",
                        "prompt_ref": "gatekeeper.md",
                        "prompt_markdown": "---\nversion: 1\narchetype: gatekeeper\n---\nJudge it.\n",
                        "posture_notes": "Close only on real evidence.",
                        "executor_kind": "codex",
                        "executor_mode": "preset",
                        "command_cli": "codex",
                        "command_args_text": "",
                        "model": "",
                        "reasoning_effort": "",
                    },
                ],
                "workflow": {
                    "version": 1,
                    "preset": "",
                    "collaboration_intent": "Verify before sign-off.",
                    "roles": [
                        {"id": "builder", "role_definition_key": "builder"},
                        {"id": "gatekeeper", "role_definition_key": "gatekeeper"},
                    ],
                    "steps": [
                        {"id": "builder_step", "role_id": "builder", "on_pass": "continue"},
                        {"id": "gatekeeper_step", "role_id": "gatekeeper", "on_pass": "finish_run"},
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    class FakeService:
        def import_bundle_file(self, path: Path, *, replace_bundle_id=None):
            calls["import"] = {"path": str(path), "replace_bundle_id": replace_bundle_id}
            return {"id": "bundle_cli", "name": "CLI Bundle"}

        def export_bundle_yaml(self, bundle_id: str):
            calls["export"] = bundle_id
            return "version: 1\nmetadata:\n  name: CLI Bundle\n"

        def write_bundle_file(self, bundle_id: str, path: Path):
            calls["write"] = {"bundle_id": bundle_id, "path": str(path)}
            path.write_text("version: 1\nmetadata:\n  name: CLI Bundle\n", encoding="utf-8")
            return path

        def derive_bundle_from_loop(self, loop_id: str, **kwargs):
            calls["derive"] = {"loop_id": loop_id, **kwargs}
            return {
                "version": 1,
                "metadata": {"name": kwargs.get("name") or "Derived CLI Bundle", "description": "", "revision": 1},
                "collaboration_summary": kwargs.get("collaboration_summary") or "Derived from an existing loop.",
                "loop": {
                    "name": "Derived CLI Bundle",
                    "workdir": str(tmp_path / "workdir"),
                    "completion_mode": "gatekeeper",
                    "executor_kind": "codex",
                    "executor_mode": "preset",
                    "command_cli": "codex",
                    "command_args_text": "",
                    "model": "",
                    "reasoning_effort": "",
                    "iteration_interval_seconds": 0,
                    "max_iters": 2,
                    "max_role_retries": 1,
                    "delta_threshold": 0.005,
                    "trigger_window": 2,
                    "regression_window": 2,
                },
                "spec": {"markdown": "# Task\n\nDerived.\n\n# Done When\n- Ready.\n"},
                "role_definitions": [
                    {
                        "key": "builder",
                        "name": "Builder",
                        "description": "",
                        "archetype": "builder",
                        "prompt_ref": "builder.md",
                        "prompt_markdown": "---\nversion: 1\narchetype: builder\n---\nBuild it.\n",
                        "posture_notes": "",
                        "executor_kind": "codex",
                        "executor_mode": "preset",
                        "command_cli": "codex",
                        "command_args_text": "",
                        "model": "",
                        "reasoning_effort": "",
                    },
                    {
                        "key": "gatekeeper",
                        "name": "GateKeeper",
                        "description": "",
                        "archetype": "gatekeeper",
                        "prompt_ref": "gatekeeper.md",
                        "prompt_markdown": "---\nversion: 1\narchetype: gatekeeper\n---\nJudge it.\n",
                        "posture_notes": "",
                        "executor_kind": "codex",
                        "executor_mode": "preset",
                        "command_cli": "codex",
                        "command_args_text": "",
                        "model": "",
                        "reasoning_effort": "",
                    },
                ],
                "workflow": {
                    "version": 1,
                    "preset": "",
                    "collaboration_intent": "",
                    "roles": [
                        {"id": "builder", "role_definition_key": "builder"},
                        {"id": "gatekeeper", "role_definition_key": "gatekeeper"},
                    ],
                    "steps": [
                        {"id": "builder_step", "role_id": "builder", "on_pass": "continue"},
                        {"id": "gatekeeper_step", "role_id": "gatekeeper", "on_pass": "finish_run"},
                    ],
                },
            }

        def delete_bundle(self, bundle_id: str):
            calls["delete"] = bundle_id
            return {"id": bundle_id, "deleted": True}

    monkeypatch.setattr(cli, "create_service", FakeService)

    import_result = runner.invoke(
        cli.app,
        ["bundles", "import", str(bundle_path), "--replace-bundle-id", "bundle_old"],
    )
    assert import_result.exit_code == 0, import_result.stdout
    assert calls["import"] == {"path": str(bundle_path), "replace_bundle_id": "bundle_old"}

    export_path = tmp_path / "exported.yml"
    export_result = runner.invoke(cli.app, ["bundles", "export", "bundle_cli", "--output", str(export_path)])
    assert export_result.exit_code == 0, export_result.stdout
    assert calls["write"] == {"bundle_id": "bundle_cli", "path": str(export_path)}
    assert export_path.read_text(encoding="utf-8").startswith("version: 1")

    derive_result = runner.invoke(
        cli.app,
        ["bundles", "derive", "loop_saved", "--name", "Derived CLI Bundle"],
    )
    assert derive_result.exit_code == 0, derive_result.stdout
    assert calls["derive"]["loop_id"] == "loop_saved"
    assert calls["derive"]["name"] == "Derived CLI Bundle"
    assert "Derived CLI Bundle" in derive_result.stdout

    delete_result = runner.invoke(cli.app, ["bundles", "delete", "bundle_cli"])
    assert delete_result.exit_code == 0, delete_result.stdout
    assert calls["delete"] == "bundle_cli"


def test_cli_diagnose_event_redaction_dry_run_and_fix(monkeypatch, tmp_path: Path) -> None:
    marker = "UNIQUE-CLI-REDACTION-MARKER"
    alignment_marker = "UNIQUE-ALIGNMENT-REDACTION-MARKER"
    repository = LooporaRepository(tmp_path / "app.db")
    service = LooporaService(
        repository=repository,
        settings=AppSettings(max_concurrent_runs=1, polling_interval_seconds=0.05, stop_grace_period_seconds=0.2),
        executor_factory=lambda: FakeCodexExecutor(scenario="success"),
    )
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("# Task\n\nKeep sensitive data out of historical events.\n", encoding="utf-8")
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    loop = service.create_loop(
        name="Redaction Audit Loop",
        spec_path=spec_path,
        workdir=workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=1,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    run = service.start_run(loop["id"])
    unsafe_event = {
        "id": 999,
        "run_id": run["id"],
        "created_at": utc_now(),
        "event_type": "codex_event",
        "role": "generator",
        "payload": {
            "type": "command",
            "message": "uv run pytest -q",
            "prompt": marker,
            "json_schema": {"marker": marker},
        },
    }
    with repository.transaction() as connection:
        connection.execute(
            """
            INSERT INTO run_events (run_id, created_at, event_type, role, payload_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                run["id"],
                unsafe_event["created_at"],
                unsafe_event["event_type"],
                unsafe_event["role"],
                json.dumps(unsafe_event["payload"], ensure_ascii=False),
            ),
        )
    layout = RunArtifactLayout(Path(run["runs_dir"]))
    layout.timeline_events_path.write_text(json.dumps(unsafe_event, ensure_ascii=False) + "\n", encoding="utf-8")
    alignment = service.create_alignment_session(
        workdir=workdir,
        message="Create an alignment event redaction audit fixture.",
        start_immediately=False,
    )
    unsafe_alignment_event = {
        "id": 1000,
        "session_id": alignment["id"],
        "created_at": utc_now(),
        "event_type": "codex_event",
        "payload": {
            "type": "command",
            "message": f"codex exec --token {alignment_marker}",
            "prompt": alignment_marker,
            "json_schema": {"marker": alignment_marker},
        },
    }
    with repository.transaction() as connection:
        connection.execute(
            """
            INSERT INTO alignment_events (session_id, created_at, event_type, payload_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                alignment["id"],
                unsafe_alignment_event["created_at"],
                unsafe_alignment_event["event_type"],
                json.dumps(unsafe_alignment_event["payload"], ensure_ascii=False),
            ),
        )
    alignment_events_path = Path(alignment["artifact_dir"]) / "events" / "events.jsonl"
    with alignment_events_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(unsafe_alignment_event, ensure_ascii=False) + "\n")

    class FakeService:
        def __init__(self, repository):
            self.repository = repository

    monkeypatch.setattr(cli, "create_service", lambda: FakeService(repository))
    runner = CliRunner()

    dry_run = runner.invoke(cli.app, ["diagnose", "event-redaction"])
    assert dry_run.exit_code == 0, dry_run.stdout
    dry_report = json.loads(dry_run.stdout)
    assert dry_report["mode"] == "dry-run"
    assert dry_report["suspect"] >= 2
    assert dry_report["alignment_db_events"]["suspect"] >= 1
    assert dry_report["alignment_event_files"]["suspect"] >= 1
    assert marker in layout.timeline_events_path.read_text(encoding="utf-8")
    assert alignment_marker in alignment_events_path.read_text(encoding="utf-8")

    fix_run = runner.invoke(cli.app, ["diagnose", "event-redaction", "--fix"])
    assert fix_run.exit_code == 0, fix_run.stdout
    fix_report = json.loads(fix_run.stdout)
    assert fix_report["mode"] == "fix"
    assert fix_report["fixed"] >= 4
    assert marker not in layout.timeline_events_path.read_text(encoding="utf-8")
    assert "uv run pytest -q" in layout.timeline_events_path.read_text(encoding="utf-8")
    fixed_payload = repository.list_events(run["id"], after_id=0, limit=20)[-1]["payload"]
    assert marker not in json.dumps(fixed_payload, ensure_ascii=False)
    assert fixed_payload["message"] == "uv run pytest -q"
    assert alignment_marker not in alignment_events_path.read_text(encoding="utf-8")
    fixed_alignment_payload = service.list_alignment_events(alignment["id"])[-1]["payload"]
    assert alignment_marker not in json.dumps(fixed_alignment_payload, ensure_ascii=False)
    assert fixed_alignment_payload["message"] == "codex exec --token <secret omitted>"


def test_cli_diagnose_event_redaction_scans_registered_orphan_run_dirs(monkeypatch, tmp_path: Path) -> None:
    marker = "UNSAFE-ORPHAN-TIMELINE-MARKER"
    repository = LooporaRepository(tmp_path / "app.db")
    run_dir = tmp_path / ".loopora" / "runs" / "run_orphan"
    layout = RunArtifactLayout(run_dir)
    layout.timeline_dir.mkdir(parents=True)
    unsafe_event = {
        "id": 1,
        "run_id": "run_orphan",
        "created_at": utc_now(),
        "event_type": "codex_event",
        "role": "generator",
        "payload": {
            "type": "command",
            "message": "uv run pytest -q",
            "prompt": marker,
            "json_schema": {"marker": marker},
        },
    }
    layout.timeline_events_path.write_text(json.dumps(unsafe_event, ensure_ascii=False) + "\n", encoding="utf-8")
    repository.upsert_local_asset_root(
        resource_type="run",
        resource_id="run_orphan",
        path=run_dir,
        workdir=str(tmp_path),
        owner_id="loop_missing",
        state="orphaned",
    )

    class FakeService:
        def __init__(self, repository):
            self.repository = repository

    monkeypatch.setattr(cli, "create_service", lambda: FakeService(repository))
    runner = CliRunner()

    dry_run = runner.invoke(cli.app, ["diagnose", "event-redaction"])
    assert dry_run.exit_code == 0, dry_run.stdout
    assert json.loads(dry_run.stdout)["suspect"] == 1
    assert marker in layout.timeline_events_path.read_text(encoding="utf-8")

    fix_run = runner.invoke(cli.app, ["diagnose", "event-redaction", "--fix"])
    assert fix_run.exit_code == 0, fix_run.stdout
    assert json.loads(fix_run.stdout)["fixed"] == 1
    timeline_text = layout.timeline_events_path.read_text(encoding="utf-8")
    assert marker not in timeline_text
    assert "uv run pytest -q" in timeline_text


def test_cli_diagnose_event_redaction_reports_unreadable_timeline_files(monkeypatch, tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    run_dir = tmp_path / ".loopora" / "runs" / "run_unreadable"
    layout = RunArtifactLayout(run_dir)
    layout.timeline_dir.mkdir(parents=True)
    layout.timeline_events_path.write_bytes(b"\xff")
    repository.upsert_local_asset_root(
        resource_type="run",
        resource_id="run_unreadable",
        path=run_dir,
        workdir=str(tmp_path),
        owner_id="loop_missing",
        state="orphaned",
    )

    class FakeService:
        def __init__(self, repository):
            self.repository = repository

    monkeypatch.setattr(cli, "create_service", lambda: FakeService(repository))
    runner = CliRunner()

    dry_run = runner.invoke(cli.app, ["diagnose", "event-redaction"])
    assert dry_run.exit_code == 0, dry_run.stdout
    dry_report = json.loads(dry_run.stdout)
    assert dry_report["suspect"] == 0
    assert dry_report["fixed"] == 0
    assert dry_report["timeline_files"]["scanned_files"] == 1
    assert dry_report["timeline_files"]["scanned_events"] == 0
    assert any(
        item["source"] == "timeline"
        and item["reason"] == "read_failed"
        and item["error_type"] == "UnicodeDecodeError"
        for item in dry_report["unfixable"]
    )

    fix_run = runner.invoke(cli.app, ["diagnose", "event-redaction", "--fix"])
    assert fix_run.exit_code == 0, fix_run.stdout
    fix_report = json.loads(fix_run.stdout)
    assert fix_report["fixed"] == 0
    assert any(item["reason"] == "read_failed" for item in fix_report["unfixable"])
    assert layout.timeline_events_path.read_bytes() == b"\xff"
