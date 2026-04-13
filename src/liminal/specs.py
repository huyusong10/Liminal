from __future__ import annotations

import re
from pathlib import Path

REQUIRED_SECTIONS = ["Goal"]


class SpecError(ValueError):
    """Raised when a Markdown spec cannot be compiled."""


def spec_template(locale: str = "zh") -> str:
    if locale.lower().startswith("en"):
        return """# Goal

Describe, in natural language, the outcome this loop should achieve.

# Checks

### Successful primary flow

- When: Which user or system situation should be checked
- Expect: What good behavior looks like
- Fail if: What would count as a miss or regression

### Safe fallback

- When: An edge case, bad input, or incomplete prototype path appears
- Expect: The experience still stays understandable and controllable
- Fail if: The page breaks, becomes misleading, or leaves the user stuck

# Constraints

- What must not be changed
- Which directories may be edited, and which are off-limits
- Tool, resource, or compatibility limits

<!-- Optional: omit # Checks when you want Liminal to auto-generate a frozen set of exploratory checks for each run. -->
"""

    return """# Goal

用自然语言描述这个循环最终要达成的目标。

# Checks

### 主路径可用

- When: 需要检查的用户场景或系统状态
- Expect: 希望看到的正确行为
- Fail if: 哪些现象算失败或退化

### 边界情况可控

- When: 触发失败路径、异常输入或尚未完善的原型分支
- Expect: 页面或流程依然可理解、可恢复
- Fail if: 页面报错、状态混乱，或让用户卡住

# Constraints

- 不允许做什么
- 允许改哪些目录，禁止改哪些目录
- 资源限制、工具限制、兼容性限制

<!-- 可选：如果不写 # Checks，Liminal 会在每次 run 开始时自动生成一组只在本次运行内冻结的 exploratory checks。 -->
"""


def init_spec_file(path: Path, *, locale: str = "zh") -> Path:
    if path.exists():
        raise FileExistsError(f"spec already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(spec_template(locale=locale), encoding="utf-8")
    return path


def compile_markdown_spec(markdown_text: str) -> dict:
    sections = _split_sections(markdown_text)
    missing = [section for section in REQUIRED_SECTIONS if not sections.get(section)]
    if missing:
        raise SpecError(f"missing top-level sections: {', '.join(missing)}")

    checks_section = sections.get("Checks", "")
    checks = _extract_checks(checks_section)
    if checks_section.strip() and not checks:
        raise SpecError("`# Checks` must include at least one `###` check heading")
    compiled_checks = []
    for index, check in enumerate(checks, start=1):
        compiled_checks.append(
            {
                "id": f"check_{index:03d}",
                "title": check["title"],
                "details": check["body"],
                "when": check["fields"].get("when", ""),
                "expect": check["fields"].get("expect", ""),
                "fail_if": check["fields"].get("fail_if", ""),
                "source": "specified",
            }
        )

    return {
        "goal": sections["Goal"].strip(),
        "constraints": sections.get("Constraints", "").strip(),
        "checks": compiled_checks,
        "check_mode": "specified" if compiled_checks else "auto_generate",
        "raw_sections": {key: value.strip() for key, value in sections.items()},
    }


def read_and_compile(path: Path) -> tuple[str, dict]:
    markdown_text = path.read_text(encoding="utf-8")
    return markdown_text, compile_markdown_spec(markdown_text)


def _split_sections(markdown_text: str) -> dict[str, str]:
    pattern = re.compile(r"^# (.+?)\s*$", re.MULTILINE)
    matches = list(pattern.finditer(markdown_text))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        name = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown_text)
        sections[name] = markdown_text[start:end].strip()
    return sections


def _extract_checks(section_text: str) -> list[dict[str, object]]:
    pattern = re.compile(r"^### (.+?)\s*$", re.MULTILINE)
    matches = list(pattern.finditer(section_text))
    results: list[dict[str, object]] = []
    for index, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(section_text)
        body = section_text[start:end].strip()
        results.append({"title": title, "body": body, "fields": _extract_check_fields(body)})
    return results


def _extract_check_fields(body: str) -> dict[str, str]:
    field_map = {
        "when": "when",
        "expect": "expect",
        "fail if": "fail_if",
        "fail-if": "fail_if",
    }
    pattern = re.compile(r"^\s*[-*]?\s*([A-Za-z][A-Za-z \-]+):\s*(.+?)\s*$", re.MULTILINE)
    fields: dict[str, str] = {}
    for match in pattern.finditer(body):
        label = match.group(1).strip().lower()
        key = field_map.get(label)
        if key and key not in fields:
            fields[key] = match.group(2).strip()
    return fields
