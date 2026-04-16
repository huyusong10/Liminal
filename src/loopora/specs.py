from __future__ import annotations

import re
from pathlib import Path

REQUIRED_SECTIONS = ["Goal"]
HTML_COMMENT_PATTERN = re.compile(r"<!--.*?-->", re.DOTALL)


class SpecError(ValueError):
    """Raised when a Markdown spec cannot be compiled."""


def spec_template(locale: str = "zh") -> str:
    if locale.lower().startswith("en"):
        return """<!--
Delete this note whenever you want.

Required:
- Keep `# Goal`. If you delete it, spec validation fails.

Optional:
- Delete the whole `# Checks` section if you want Loopora to auto-generate and freeze exploratory checks for each run.
- Delete the whole `# Constraints` section if you have no extra constraints.

One gotcha:
- If you keep `# Checks`, it must contain at least one `###` check heading.

Good default safety rule:
- If this loop points at an existing project, say so in `# Constraints`: preserve existing user files and prefer focused in-place edits over rewrites.

Helpful benchmark-loop rule:
- If the goal depends on a long-running project-owned benchmark, say which harness and report/status artifacts count as the trusted evidence path.
-->

# Goal

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
- Preserve existing user-owned files; prefer in-place edits over large rewrites
- Tool, resource, or compatibility limits
"""

    return """<!--
这段提示看完就可以删。

必填：
- 保留 `# Goal`。如果删掉，spec 校验会直接失败。

可选：
- 如果想让 Loopora 在每次 run 开始时自动生成并冻结 exploratory checks，就把整个 `# Checks` 章节删掉。
- 如果没有额外约束，就把整个 `# Constraints` 章节删掉。

一个小坑：
- 如果保留 `# Checks`，里面至少要有一个 `###` check 标题。

一个默认安全建议：
- 如果这个 loop 指向的是现有项目，最好在 `# Constraints` 里写明：保留现有用户文件，优先原地小改，不要大改大删。

一个适合 benchmark loop 的建议：
- 如果目标依赖项目自带的长流程评估，最好写明哪个 harness 是可信入口，以及等待期间应该观察哪些状态文件或报告产物。
-->

# Goal

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
- 保留现有用户文件，优先原地修改，不要大范围重写
- 资源限制、工具限制、兼容性限制
"""


def init_spec_file(path: Path, *, locale: str = "zh") -> Path:
    if path.exists():
        raise FileExistsError(f"spec already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(spec_template(locale=locale), encoding="utf-8")
    return path


def compile_markdown_spec(markdown_text: str) -> dict:
    cleaned_markdown = _strip_html_comments(markdown_text)
    sections = _split_sections(cleaned_markdown)
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
        "check_mode": "specified" if compiled_checks else "auto_generated",
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


def _strip_html_comments(markdown_text: str) -> str:
    return HTML_COMMENT_PATTERN.sub("", markdown_text)


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
