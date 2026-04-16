from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is required for locale detection tests")
APP_JS = Path(__file__).resolve().parents[1] / "src" / "loopora" / "static" / "app.js"


def _run_locale_case(
    *,
    saved: str | None = None,
    languages: list[str] | None = None,
    language: str | None = None,
    user_language: str | None = None,
    browser_language: str | None = None,
    system_language: str | None = None,
    intl_locale: str | None = None,
) -> dict:
    script = f"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync({json.dumps(str(APP_JS))}, "utf8");
const storage = {{
  value: {json.dumps(saved)},
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
  languages: {json.dumps(languages)},
  language: {json.dumps(language)},
  userLanguage: {json.dumps(user_language)},
  browserLanguage: {json.dumps(browser_language)},
  systemLanguage: {json.dumps(system_language)},
}};
const Intl = {{
  DateTimeFormat() {{
    return {{
      resolvedOptions() {{
        return {{ locale: {json.dumps(intl_locale)} }};
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
        saved="en",
        languages=["zh-CN"],
        language="zh-CN",
        system_language="zh-CN",
        intl_locale="zh-CN",
    )

    assert result["preferred"] == "en"
    assert result["stored"] == "en"
    assert result["htmlLang"] == "en"


def test_system_chinese_defaults_to_chinese_even_if_browser_language_is_english() -> None:
    result = _run_locale_case(
        languages=["en-US"],
        language="en-US",
        system_language="zh-CN",
        intl_locale="zh-CN",
    )

    assert result["preferred"] == "zh"
    assert result["stored"] is None
    assert result["htmlLang"] == "zh-CN"


def test_primary_browser_chinese_defaults_to_chinese() -> None:
    result = _run_locale_case(
        languages=["zh-CN", "en-US"],
        language="zh-CN",
        intl_locale="en-US",
    )

    assert result["preferred"] == "zh"
    assert result["stored"] is None


def test_secondary_browser_chinese_does_not_override_english_default() -> None:
    result = _run_locale_case(
        languages=["en-US", "zh-CN"],
        language="en-US",
        browser_language="en-US",
        intl_locale="en-US",
    )

    assert result["preferred"] == "en"
    assert result["stored"] is None
