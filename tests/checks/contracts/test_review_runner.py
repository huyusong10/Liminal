from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
REVIEW_RUNNER_PATH = ROOT / "tests" / "reviews" / "run.py"
spec = importlib.util.spec_from_file_location("loopora_review_runner", REVIEW_RUNNER_PATH)
assert spec is not None and spec.loader is not None
review_runner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = review_runner
spec.loader.exec_module(review_runner)


def _target_terms(target: dict) -> set[str]:
    terms: set[str] = set()
    for item in target["terms"]:
        terms.add(item["term"] if isinstance(item, dict) else item)
    return terms


def test_review_term_hints_scan_visible_text_not_template_identifiers(monkeypatch, tmp_path: Path) -> None:
    templates = tmp_path / "src" / "loopora" / "templates"
    templates.mkdir(parents=True)
    page = templates / "page.html"
    page.write_text(
        "\n".join(
            [
                '<a href="/loops/new/bundle" data-testid="bundle-import-link">Import plan</a>',
                '<h2><span data-lang="en">Import Existing Bundle / YAML</span></h2>',
                '<button aria-label="{{ \'Open bundle chooser\' if page_locale == \'en\' else \'打开方案选择器\' }}"></button>',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(review_runner, "ROOT", tmp_path)
    artifact = review_runner._write_term_hints(
        {
            "id": "expert-language-hints",
            "type": "term_hints",
            "globs": ["src/loopora/templates/*.html"],
            "terms": ["bundle", "YAML"],
        },
        tmp_path,
    )

    report = artifact.path.read_text(encoding="utf-8")

    assert "page.html:1" not in report
    assert "`src/loopora/templates/page.html:2` `bundle`" in report
    assert "`src/loopora/templates/page.html:2` `YAML`" in report
    assert "`src/loopora/templates/page.html:3` `bundle`" in report
    assert "data-testid" not in report
    assert "href=" not in report


def test_review_term_hints_scan_locale_text_but_not_js_selectors(monkeypatch, tmp_path: Path) -> None:
    scripts = tmp_path / "src" / "loopora" / "static" / "pages"
    scripts.mkdir(parents=True)
    script = scripts / "alignment.js"
    script.write_text(
        "\n".join(
            [
                'const preview = document.getElementById("bundle-preview-title");',
                'showStatus(target, localeText("方案文件预览失败。", "Bundle preview failed."));',
                "window.alert(pickText({",
                '  zh: "无法删除这个方案包。",',
                '  en: "Unable to delete this bundle.",',
                "}));",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(review_runner, "ROOT", tmp_path)
    artifact = review_runner._write_term_hints(
        {
            "id": "expert-language-hints",
            "type": "term_hints",
            "globs": ["src/loopora/static/pages/*.js"],
            "terms": ["bundle"],
        },
        tmp_path,
    )

    report = artifact.path.read_text(encoding="utf-8")

    assert "alignment.js:1" not in report
    assert "`src/loopora/static/pages/alignment.js:2` `bundle`" in report
    assert "`src/loopora/static/pages/alignment.js:5` `bundle`" in report
    assert "document.getElementById" not in report


def test_review_term_hints_ignore_javascript_template_interpolation_identifiers(
    monkeypatch, tmp_path: Path
) -> None:
    scripts = tmp_path / "src" / "loopora" / "static" / "pages"
    scripts.mkdir(parents=True)
    script = scripts / "alignment.js"
    script.write_text(
        "\n".join(
            [
                'showStatus(target, localeText(`${workflow.step_count || 0} steps`, "Run flow"));',
                'showStatus(target, localeText(`Visible workflow ${count}`, "Run flow"));',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(review_runner, "ROOT", tmp_path)
    artifact = review_runner._write_term_hints(
        {
            "id": "expert-language-hints",
            "type": "term_hints",
            "globs": ["src/loopora/static/pages/*.js"],
            "terms": ["workflow"],
        },
        tmp_path,
    )

    report = artifact.path.read_text(encoding="utf-8")

    assert "alignment.js:1" not in report
    assert "`src/loopora/static/pages/alignment.js:2` `workflow`" in report
    assert "workflow.step_count" not in report


def test_review_term_hints_ignore_explicit_negative_positioning(monkeypatch, tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(
        "\n".join(
            [
                "Loopora is not a prompt pack.",
                "Loopora is not generic chat.",
                "Default users should not see raw YAML.",
                "This page exposes workflow controls.",
                "它不是 prompt 模板库。",
                "默认用户不应看到 YAML。",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(review_runner, "ROOT", tmp_path)
    artifact = review_runner._write_term_hints(
        {
            "id": "expert-language-hints",
            "type": "term_hints",
            "globs": ["README.md"],
            "terms": ["prompt pack", "generic chat", "YAML", "workflow controls", "prompt 模板库"],
        },
        tmp_path,
    )

    report = artifact.path.read_text(encoding="utf-8")

    assert "README.md:1" not in report
    assert "README.md:2" not in report
    assert "README.md:3" in report
    assert "README.md:4" in report
    assert "README.md:5" not in report
    assert "README.md:6" in report


def test_default_path_language_case_keeps_hint_scope_on_default_surfaces() -> None:
    case = review_runner._parse_case(ROOT / "tests" / "reviews" / "cases" / "default-path-language.md")
    targets = {target["id"]: target for target in case.targets}

    text_globs = set(targets["default-path-text"]["globs"])
    hint_globs = set(targets["expert-language-hints"]["globs"])
    hint_terms = _target_terms(targets["expert-language-hints"])

    assert "src/loopora/assets/alignment/product-primer.md" in text_globs
    assert "src/loopora/assets/alignment/system-prompt.md" in text_globs
    assert "README.md" in text_globs
    assert "README.zh-CN.md" in text_globs
    assert {"workflow", "workflow controls", "orchestration"}.issubset(hint_terms)
    assert all(not glob.startswith("src/loopora/assets/alignment/") for glob in hint_globs)
    assert "README.md" in hint_globs
    assert "README.zh-CN.md" in hint_globs
    assert "src/loopora/templates/bundle_detail.html" not in hint_globs
    assert "src/loopora/templates/bundles.html" not in hint_globs
    assert "src/loopora/templates/new_orchestration.html" not in hint_globs
    assert "src/loopora/templates/new_role_definition.html" not in hint_globs
    assert "src/loopora/templates/orchestrations.html" not in hint_globs
    assert "src/loopora/templates/role_definitions.html" not in hint_globs
    assert "src/loopora/templates/index.html" in hint_globs
    assert "src/loopora/templates/new_loop.html" in hint_globs
    assert "src/loopora/templates/run_detail.html" in hint_globs


def test_concept_coherence_case_keeps_core_concepts_out_of_drift_hints() -> None:
    case = review_runner._parse_case(ROOT / "tests" / "reviews" / "cases" / "concept-coherence.md")
    targets = {target["id"]: target for target in case.targets}
    anchor_globs = set(targets["top-level-anchor-text"]["globs"])
    drift_terms = _target_terms(targets["concept-drift-hints"])
    drift_globs = set(targets["concept-drift-hints"]["globs"])
    source_globs = set(targets["concept-source-text"]["globs"])
    gen_loop_globs = set(targets["gen-loop-contract-text"]["globs"])

    assert anchor_globs == {
        "README.md",
        "README.zh-CN.md",
        "HUMAN-SHAPED-LOOP.md",
        "HUMAN-SHAPED-LOOP.zh-CN.md",
    }
    assert targets["top-level-anchor-text"]["max_bytes_per_file"] >= 30000
    assert {"prompt pack", "role zoo", "generic chat", "script runner", "loop script", "chat wrapper"}.issubset(
        drift_terms
    )
    assert {"一点也", "这个图", "这里可能", "看看怎么", "有点突兀", "受到质疑", "吸引力"}.issubset(
        drift_terms
    )
    assert "human-in-the-loop" not in drift_terms
    assert "evidence" not in drift_terms
    assert "judgment" not in drift_terms
    assert "GateKeeper" not in drift_terms
    assert "design/core-ideas/*.md" in source_globs
    assert "src/loopora/assets/alignment/system-prompt.md" in source_globs
    assert "design/detailed-design/08-bundles-and-alignment.md" not in source_globs
    assert "design/detailed-design/10-agent-adapters.md" not in source_globs
    assert gen_loop_globs == {
        "design/detailed-design/08-bundles-and-alignment.md",
        "design/detailed-design/10-agent-adapters.md",
    }
    assert targets["gen-loop-contract-text"]["max_bytes_per_file"] >= 40000
    assert "design/core-ideas/*.md" not in drift_globs
    assert "src/loopora/assets/alignment/*.md" not in drift_globs
    assert "README.md" in drift_globs
    assert "src/loopora/templates/tutorial.html" in drift_globs
    assert "Whether bundle design still externalizes task-scoped human judgment" in case.brief
    assert "Whether `/loopora-gen` still helps the human externalize judgment" in case.brief
    assert "Whether `/loopora-loop` still executes the reviewed Loop" in case.brief


def test_concept_coherence_anchor_text_reaches_agent_first_execution_contract(tmp_path: Path) -> None:
    case = review_runner._parse_case(ROOT / "tests" / "reviews" / "cases" / "concept-coherence.md")
    targets = {target["id"]: target for target in case.targets}
    artifact = review_runner._write_text_index(targets["top-level-anchor-text"], tmp_path)

    report = artifact.path.read_text(encoding="utf-8")

    assert "Human-shaped Loop is not just the name of an essay." in report
    assert "Human-shaped Loop 不只是这篇文档的名字" in report
    assert "A candidate Loop cannot be only a task summary" in report
    assert "候选 Loop 不能只是任务摘要" in report
    assert "each step should inherit these judgments, action boundaries, and evidence gaps" in report
    assert "每一步都应继承这些判断、行动边界和证据缺口" in report
    assert "_Truncated after" not in report


def test_concept_coherence_design_text_reaches_gen_and_loop_contracts(tmp_path: Path) -> None:
    case = review_runner._parse_case(ROOT / "tests" / "reviews" / "cases" / "concept-coherence.md")
    targets = {target["id"]: target for target in case.targets}
    artifact = review_runner._write_text_index(targets["gen-loop-contract-text"], tmp_path)

    report = artifact.path.read_text(encoding="utf-8")

    assert "Agent-first `/loopora-gen` 生成或发现候选后必须回到同一 READY 预览" in report
    assert "`/loopora-loop` 不从一句话任务直接生成 bundle。" in report
    assert "execution capsule 至少包含 step identity" in report
    assert (
        "Agent-native submit 必须把 `next_step.output_schema`、`action_policy`、`judgment_contract`、`required_coverage` 与 `known_evidence_ids` 当成 Core 边界"
        in report
    )
    assert "_Truncated after" not in report


def test_agent_native_case_keeps_core_concepts_out_of_shortcut_hints() -> None:
    case = review_runner._parse_case(ROOT / "tests" / "reviews" / "cases" / "agent-native-behavior.md")
    targets = {target["id"]: target for target in case.targets}
    risk_terms = set(targets["agent-native-risk-hints"]["terms"])
    risk_globs = set(targets["agent-native-risk-hints"]["globs"])
    handbook_globs = set(targets["agent-native-handbook"]["globs"])

    assert {"inline", "nested", "prewritten", "host dispatch"}.issubset(risk_terms)
    assert "READY" not in risk_terms
    assert "evidence" not in risk_terms
    assert targets["agent-native-risk-hints"]["optional"] is True
    assert ".loopora/real-probes/*phase-report.json" in risk_globs
    assert ".loopora/real-probes/**/*phase-report.json" in risk_globs
    assert "design/detailed-design/10-agent-adapters.md" in handbook_globs
    assert "tests/probes/real_environment/README.md" in handbook_globs
    assert "tests/probes/real_environment/test_real_agent_adapter_probe.py" in handbook_globs
    assert targets["agent-native-handbook"]["max_bytes_per_file"] >= 48000
    assert "design/detailed-design/10-agent-adapters.md" not in risk_globs
    assert "tests/probes/real_environment/README.md" not in risk_globs
    assert "tests/probes/real_environment/*.py" not in risk_globs


def test_agent_native_handbook_reaches_real_probe_boundaries(tmp_path: Path) -> None:
    case = review_runner._parse_case(ROOT / "tests" / "reviews" / "cases" / "agent-native-behavior.md")
    targets = {target["id"]: target for target in case.targets}
    artifact = review_runner._write_text_index(targets["agent-native-handbook"], tmp_path)

    report = artifact.path.read_text(encoding="utf-8")

    assert "Real probe 应证明至少一个 role step 通过 `role_dispatch.target_agent` 路径提交" in report
    assert "不得预先写好 candidate plan file" in report
    assert "不得在 prompt 中嵌入完整候选文件再让宿主照抄导入" in report
    assert "Codex real probe 通过原生 `spawn_agent` 验证 `role_dispatch.target_agent`" in report
    assert "`next_step.output_schema`、`next_step.action_policy`、`next_step.known_evidence_ids`" in report
    assert "output schema、action policy 与 evidence ids" in report
    assert "Nested host CLI sentinels must remain silent." in report
    assert "Use these requirements to author, not copy, the candidate" in report
    assert "canonical candidate bundle draft" not in report
    assert '--show-playbook", action="store_true"' in report
    assert "_Truncated after" not in report


def test_review_case_files_have_valid_front_matter() -> None:
    for path in sorted((ROOT / "tests" / "reviews" / "cases").glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        assert raw.startswith("---\n"), path
        _prefix, front_matter, _body = raw.split("---", 2)
        metadata = yaml.safe_load(front_matter)
        assert metadata["id"]
        assert metadata["targets"]
