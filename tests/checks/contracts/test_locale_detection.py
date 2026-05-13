from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest


NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is required for locale detection tests")
APP_JS = Path(__file__).resolve().parents[3] / "src" / "loopora" / "static" / "app.js"


@dataclass(frozen=True)
class LocaleCase:
    saved: str | None = None
    languages: list[str] | None = None
    language: str | None = None
    user_language: str | None = None
    browser_language: str | None = None
    system_language: str | None = None
    intl_locale: str | None = None


def _run_locale_case(case: LocaleCase) -> dict:
    script = f"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync({json.dumps(str(APP_JS))}, "utf8");
const storage = {{
  value: {json.dumps(case.saved)},
  getItem(key) {{
    return key === "loopora:locale" ? this.value : null;
  }},
  setItem(key, value) {{
    if (key === "loopora:locale") this.value = value;
  }},
}};
const document = {{
  documentElement: {{ dataset: {{}}, lang: "zh-CN" }},
  addEventListener() {{}},
  querySelectorAll() {{ return []; }},
  dispatchEvent() {{}},
}};
const window = {{ localStorage: storage, LooporaUI: null }};
const navigator = {{
  languages: {json.dumps(case.languages)},
  language: {json.dumps(case.language)},
  userLanguage: {json.dumps(case.user_language)},
  browserLanguage: {json.dumps(case.browser_language)},
  systemLanguage: {json.dumps(case.system_language)},
}};
const Intl = {{
  DateTimeFormat() {{
    return {{
      resolvedOptions() {{
        return {{ locale: {json.dumps(case.intl_locale)} }};
      }},
    }};
  }},
}};
const context = {{ window, document, navigator, Intl, CustomEvent: function () {{}}, console }};
vm.createContext(context);
vm.runInContext(code, context);
const preferred = context.window.LooporaUI.detectPreferredLocale();
context.window.LooporaUI.setLocale(preferred, {{ persist: false }});
console.log(JSON.stringify({{
  preferred,
  stored: storage.value,
  htmlLang: document.documentElement.lang,
}}));
"""
    completed = subprocess.run(
        [NODE, "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_saved_locale_overrides_environment_detection() -> None:
    result = _run_locale_case(
        LocaleCase(
            saved="en",
            languages=["zh-CN"],
            language="zh-CN",
            system_language="zh-CN",
            intl_locale="zh-CN",
        )
    )

    assert result["preferred"] == "en"
    assert result["stored"] == "en"
    assert result["htmlLang"] == "en"


def test_system_chinese_defaults_to_chinese_even_if_browser_language_is_english() -> None:
    result = _run_locale_case(
        LocaleCase(
            languages=["en-US"],
            language="en-US",
            system_language="zh-CN",
            intl_locale="zh-CN",
        )
    )

    assert result["preferred"] == "zh"
    assert result["stored"] is None
    assert result["htmlLang"] == "zh-CN"


def test_primary_browser_chinese_defaults_to_chinese() -> None:
    result = _run_locale_case(
        LocaleCase(
            languages=["zh-CN", "en-US"],
            language="zh-CN",
            intl_locale="en-US",
        )
    )

    assert result["preferred"] == "zh"
    assert result["stored"] is None


def test_role_translation_accepts_current_chinese_archetype_labels() -> None:
    script = f"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync({json.dumps(str(APP_JS))}, "utf8");
const document = {{
  documentElement: {{ dataset: {{}}, lang: "zh-CN" }},
  addEventListener() {{}},
  querySelectorAll() {{ return []; }},
  dispatchEvent() {{}},
}};
const window = {{ localStorage: {{ getItem() {{ return "zh"; }}, setItem() {{}} }}, LooporaUI: null }};
const navigator = {{ languages: ["zh-CN"], language: "zh-CN" }};
const context = {{ window, document, navigator, Intl, CustomEvent: function () {{}}, console }};
vm.createContext(context);
vm.runInContext(code, context);
console.log(JSON.stringify({{
  builder: context.window.LooporaUI.translateRole("构建者"),
  gatekeeper: context.window.LooporaUI.translateRole("守门者"),
  guide: context.window.LooporaUI.translateRole("引导者"),
  custom: context.window.LooporaUI.translateRole("Custom Role"),
}}));
"""
    completed = subprocess.run(
        [NODE, "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == {
        "builder": "构建者",
        "gatekeeper": "守门者",
        "guide": "引导者",
        "custom": "自定义角色",
    }


def test_secondary_browser_chinese_does_not_override_english_default() -> None:
    result = _run_locale_case(
        LocaleCase(
            languages=["en-US", "zh-CN"],
            language="en-US",
            browser_language="en-US",
            intl_locale="en-US",
        )
    )

    assert result["preferred"] == "en"
    assert result["stored"] is None
