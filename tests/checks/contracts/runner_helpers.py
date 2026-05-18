from __future__ import annotations

import json
import time
from pathlib import Path


from loopora.branding import state_dir_for_workdir
from loopora.context_flow import (
    system_prompt_prefix,
)
from loopora.run_artifacts import RunArtifactLayout
from loopora.service import LooporaService
from loopora.workflows import prompt_asset_path


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _step_outputs_by_archetype(run_dir: Path) -> dict[str, list[dict]]:
    outputs: dict[str, list[dict]] = {}
    for metadata_path in sorted(run_dir.glob("iterations/iter_*/steps/*/metadata.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        output_path = metadata_path.parent / "output.normalized.json"
        outputs.setdefault(metadata["archetype"], []).append(
            {
                "metadata": metadata,
                "output": json.loads(output_path.read_text(encoding="utf-8")),
                "step_dir": metadata_path.parent,
            }
        )
    return outputs


def _wait_for_terminal_run(service: LooporaService, run_id: str, *, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    current = service.get_run(run_id)
    while time.time() < deadline:
        current = service.get_run(run_id)
        if current["status"] in {"succeeded", "failed", "stopped"}:
            return current
        time.sleep(0.05)
    return current


def _join_async_run(service: LooporaService, run_id: str, *, timeout: float = 5.0) -> None:
    thread = service._threads.get(run_id)
    if thread is not None:
        thread.join(timeout=timeout)
    service.get_run(run_id)


def _create_loop(
    service,
    sample_spec_file: Path,
    sample_workdir: Path,
    name: str = "Demo Loop",
    *,
    workflow: dict | None = None,
    **overrides,
) -> dict:
    payload = {
        "name": name,
        "spec_path": sample_spec_file,
        "workdir": sample_workdir,
        "model": "",
        "reasoning_effort": "",
        "max_iters": 3,
        "max_role_retries": 1,
        "delta_threshold": 0.005,
        "trigger_window": 2,
        "regression_window": 2,
        "role_models": {},
        "workflow": workflow,
    }
    payload.update(overrides)
    return service.create_loop(**payload)


def _force_run_into_legacy_mode(service: LooporaService, run_id: str) -> dict:
    with service.repository.transaction() as connection:
        connection.execute(
            "UPDATE loop_runs SET workflow_json = ? WHERE id = ?",
            (json.dumps({}, ensure_ascii=False), run_id),
        )
    return service.get_run(run_id)


def _corrupt_loop_prompt_artifact(loop: dict, prompt_ref: str) -> None:
    prompt_dir = state_dir_for_workdir(Path(loop["workdir"])) / "loops" / loop["id"] / "prompts"
    prompt_asset_path(prompt_dir, prompt_ref).write_bytes(b"\xff")


def _corrupt_run_prompt_artifact(run: dict, prompt_ref: str) -> None:
    layout = RunArtifactLayout(Path(run["runs_dir"]))
    prompt_asset_path(layout.contract_prompts_dir, prompt_ref).write_bytes(b"\xff")


def _assert_evidence_manifest(run_dir: Path) -> None:
    manifest = json.loads((run_dir / "evidence" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_path"] == "evidence/manifest.json"
    assert manifest["ledger_path"] == "evidence/ledger.jsonl"
    assert manifest["coverage_path"] == "evidence/coverage.json"
    assert manifest["claim_count"] >= 3
    assert manifest["artifact_backed_claim_count"] == manifest["claim_count"]
    assert manifest["run_artifact_claim_count"] >= 1
    assert all(claim["producer"]["step_id"] for claim in manifest["claims"])


def _assert_runtime_contract_frozen_prefixes() -> None:
    for archetype in ["builder", "inspector", "gatekeeper", "custom", "guide"]:
        prefix = system_prompt_prefix(archetype)
        assert "Treat the run contract as frozen" in prefix
        assert (
            "do not reinterpret or lower Task, Done When, Guardrails, bundle collaboration summary, Loopora fit, workflow collaboration intent, role posture, "
            "Success Surface, Fake Done, Evidence Preferences, Execution Strategy, Judgment Tradeoffs, Local Governance, or Residual Risk"
        ) in prefix
        assert "evidence gaps or blockers" in prefix
        assert "project-local instructions, design docs, and tests" in prefix


def _assert_prompt_assets_contract_frozen(prompts: list[str], zh_prompts: list[str]) -> None:
    for prompt in prompts:
        assert "Treat the run contract as frozen" in prompt
        assert (
            "do not reinterpret or lower Task, Done When, checks, guardrails, bundle collaboration summary, Loopora fit, workflow intent, role posture, "
            "Success Surface, Fake Done, Evidence Preferences, Execution Strategy, Judgment Tradeoffs, Local Governance, or Residual Risk"
        ) in prompt
        assert "evidence gaps or blockers" in prompt
        assert "project-local instructions, design docs" in prompt
    for prompt in zh_prompts:
        assert "把 run contract 当作已冻结" in prompt
        assert "不要重新解释或降低 Task、Done When、checks、guardrails、bundle 协作摘要、Loopora fit、流程意图、角色姿态、Success Surface、Fake Done、Evidence Preferences、Execution Strategy / 执行策略、Judgment Tradeoffs / 判断取舍、Local Governance / 本地治理 或 Residual Risk" in prompt
        assert "证据缺口或 blocker" in prompt
        assert "项目本地指令、design 文档或 tests" in prompt


def _runtime_prompt_assets() -> tuple[dict[str, str], dict[str, str]]:
    prompts_dir = Path(__file__).resolve().parents[3] / "src" / "loopora" / "assets" / "prompts"
    names = ["builder", "inspector", "custom", "guide", "gatekeeper", "gatekeeper-benchmark"]
    prompts = {name: (prompts_dir / f"{name}.md").read_text(encoding="utf-8") for name in names}
    zh_prompts = {name: (prompts_dir / f"{name}.zh.md").read_text(encoding="utf-8") for name in names}
    return prompts, zh_prompts


def _assert_prompt_evidence_fallback_rules(prompts: dict[str, str], zh_prompts: dict[str, str]) -> None:
    assert "smallest repeatable verification artifact" in prompts["builder"]
    assert "strongest no-install executable proof" in prompts["builder"]
    assert "最小可重复验证产物" in zh_prompts["builder"]
    assert "最强免安装可执行证明" in zh_prompts["builder"]
    assert "strongest repeatable fallback evidence" in prompts["gatekeeper"]
    assert "deterministic local proof" in prompts["gatekeeper"]
    assert "最强可重复 fallback 证据" in zh_prompts["gatekeeper"]
    assert "确定性本地证明" in zh_prompts["gatekeeper"]


def _assert_prompt_parallel_review_rules(prompts: dict[str, str], zh_prompts: dict[str, str]) -> None:
    assert "Inspector or Custom review steps will run in parallel" in prompts["builder"]
    assert "Inspector 或 Custom review step 并行检视" in zh_prompts["builder"]
    assert "parallel review group" in prompts["inspector"]
    assert "peer reviewers" in prompts["inspector"]
    assert "Custom reviewer" in prompts["inspector"]
    assert "并行 review 组" in zh_prompts["inspector"]
    assert "其他 reviewer" in zh_prompts["inspector"]
    assert "Custom reviewer" in zh_prompts["inspector"]
    assert "places you in a parallel review group" in prompts["custom"]
    assert "downstream GateKeeper can fan in" in prompts["custom"]
    assert "把你放进并行 review 组" in zh_prompts["custom"]
    assert "GateKeeper 可以和其他 review 分支一起汇总" in zh_prompts["custom"]
    assert "parallel Inspector or Custom review steps" in prompts["gatekeeper"]
    assert "all relevant review handoffs" in prompts["gatekeeper"]
    assert "并行 Inspector 或 Custom review step" in zh_prompts["gatekeeper"]
    assert "相关 review handoff" in zh_prompts["gatekeeper"]


def _assert_prompt_bucket_rules(prompts: dict[str, str], zh_prompts: dict[str, str]) -> None:
    evidence_bucket_phrase = "Proven / Weak / Unproven / Blocking / Residual risk"
    evidence_bucket_zh_phrase = "已证明 / 弱证据 / 未证明 / 阻断 / 残余风险"
    for prompt in prompts.values():
        assert evidence_bucket_phrase in prompt
    for prompt in zh_prompts.values():
        assert evidence_bucket_zh_phrase in prompt
