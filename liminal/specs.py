from __future__ import annotations

import re
from pathlib import Path

REQUIRED_SECTIONS = ["Goal", "Cases", "Expected Results", "Acceptance", "Constraints"]


class SpecError(ValueError):
    """Raised when a Markdown spec cannot be compiled."""


def spec_template() -> str:
    return """# Goal

用自然语言描述这个循环最终要达成的目标。

# Cases

### Case 1: Primary flow

- Scenario: 用户或系统处于什么场景
- Steps: 希望执行什么动作
- Notes: 边界、前置条件、补充说明

### Case 2: Edge case

- Scenario: 边界或失败路径
- Steps: 触发方式
- Notes: 为什么这个 case 很重要

# Expected Results

### Case 1: Primary flow

- 输出应该是什么
- 如何判断这次执行是正确的

### Case 2: Edge case

- 错误处理或降级行为应该是什么
- 允许什么，不允许什么

# Acceptance

- 通过阈值、质量标准、必须满足的验收条件
- 可以包含延迟、正确率、结构化输出要求等

# Constraints

- 不允许做什么
- 允许改哪些目录，禁止改哪些目录
- 资源限制、工具限制、兼容性限制
"""


def init_spec_file(path: Path) -> Path:
    if path.exists():
        raise FileExistsError(f"spec already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(spec_template(), encoding="utf-8")
    return path


def compile_markdown_spec(markdown_text: str) -> dict:
    sections = _split_sections(markdown_text)
    missing = [section for section in REQUIRED_SECTIONS if not sections.get(section)]
    if missing:
        raise SpecError(f"missing top-level sections: {', '.join(missing)}")

    cases = _extract_cases(sections["Cases"])
    expected_results = _extract_cases(sections["Expected Results"])
    if not cases:
        raise SpecError("`# Cases` must include at least one `###` case heading")

    expected_map = {item["title"]: item["body"] for item in expected_results}
    compiled_cases = []
    for index, case in enumerate(cases, start=1):
        compiled_cases.append(
            {
                "id": f"case_{index:03d}",
                "title": case["title"],
                "description": case["body"],
                "expected_result": expected_map.get(case["title"], ""),
            }
        )

    return {
        "goal": sections["Goal"].strip(),
        "acceptance": sections["Acceptance"].strip(),
        "constraints": sections["Constraints"].strip(),
        "cases": compiled_cases,
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


def _extract_cases(section_text: str) -> list[dict[str, str]]:
    pattern = re.compile(r"^### (.+?)\s*$", re.MULTILINE)
    matches = list(pattern.finditer(section_text))
    results: list[dict[str, str]] = []
    for index, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(section_text)
        results.append({"title": title, "body": section_text[start:end].strip()})
    return results
