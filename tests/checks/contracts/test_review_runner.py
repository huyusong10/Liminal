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


def test_default_path_language_case_keeps_hint_scope_on_default_surfaces() -> None:
    case = review_runner._parse_case(ROOT / "tests" / "reviews" / "cases" / "default-path-language.md")
    targets = {target["id"]: target for target in case.targets}

    text_globs = set(targets["default-path-text"]["globs"])
    hint_globs = set(targets["expert-language-hints"]["globs"])

    assert "src/loopora/assets/alignment/product-primer.md" in text_globs
    assert "src/loopora/assets/alignment/system-prompt.md" in text_globs
    assert all(not glob.startswith("src/loopora/assets/alignment/") for glob in hint_globs)
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
    drift_terms = set(targets["concept-drift-hints"]["terms"])
    drift_globs = set(targets["concept-drift-hints"]["globs"])
    source_globs = set(targets["concept-source-text"]["globs"])

    assert {"prompt pack", "role zoo", "generic chat", "script runner", "loop script", "chat wrapper"}.issubset(
        drift_terms
    )
    assert "human-in-the-loop" not in drift_terms
    assert "evidence" not in drift_terms
    assert "judgment" not in drift_terms
    assert "GateKeeper" not in drift_terms
    assert "design/core-ideas/*.md" in source_globs
    assert "src/loopora/assets/alignment/system-prompt.md" in source_globs
    assert "design/core-ideas/*.md" not in drift_globs
    assert "src/loopora/assets/alignment/*.md" not in drift_globs
    assert "README.md" in drift_globs
    assert "src/loopora/templates/tutorial.html" in drift_globs


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
    assert "design/detailed-design/10-agent-adapters.md" not in risk_globs
    assert "tests/probes/real_environment/README.md" not in risk_globs
    assert "tests/probes/real_environment/*.py" not in risk_globs


def test_review_case_files_have_valid_front_matter() -> None:
    for path in sorted((ROOT / "tests" / "reviews" / "cases").glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        assert raw.startswith("---\n"), path
        _prefix, front_matter, _body = raw.split("---", 2)
        metadata = yaml.safe_load(front_matter)
        assert metadata["id"]
        assert metadata["targets"]
