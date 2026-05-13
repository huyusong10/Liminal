from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys
from base64 import b64encode
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
CASE_DIR = Path(__file__).resolve().parent / "cases"
DEFAULT_OUTPUT_ROOT = ROOT / ".loopora" / "reviews"
SVG_TEXT_HINT_SCRIPT = """() => {
  const hints = [];
  const svg = document.querySelector("svg");
  if (!svg) {
    return hints;
  }
  const rects = [...svg.querySelectorAll("rect")]
    .map((rect) => {
      const box = rect.getBBox();
      return {x: box.x, y: box.y, width: box.width, height: box.height};
    })
    .filter((rect) => rect.width < 1150 && rect.height < 520 && rect.width > 20 && rect.height > 20);
  for (const text of svg.querySelectorAll("text")) {
    const box = text.getBBox();
    const centerX = box.x + box.width / 2;
    const centerY = box.y + box.height / 2;
    const candidates = rects
      .filter((rect) => centerX >= rect.x && centerX <= rect.x + rect.width && centerY >= rect.y && centerY <= rect.y + rect.height)
      .sort((left, right) => left.width * left.height - right.width * right.height);
    if (!candidates.length) {
      continue;
    }
    const rect = candidates[0];
    if (box.x < rect.x + 6 || box.x + box.width > rect.x + rect.width - 6 || box.y < rect.y + 2 || box.y + box.height > rect.y + rect.height - 2) {
      hints.push(`"${text.textContent}" is close to or outside its local shape`);
    }
  }
  return hints;
}"""
WEB_LAYOUT_HINT_SCRIPT = """() => {
  const hints = [];
  const viewportWidth = window.innerWidth;
  for (const element of document.body.querySelectorAll("*")) {
    const style = window.getComputedStyle(element);
    if (style.visibility === "hidden" || style.display === "none") {
      continue;
    }
    const box = element.getBoundingClientRect();
    if (box.width < 2 || box.height < 2) {
      continue;
    }
    const directText = [...element.childNodes]
      .filter((node) => node.nodeType === Node.TEXT_NODE)
      .map((node) => node.textContent || "")
      .join(" ")
      .trim();
    const label = (element.getAttribute("data-testid") || element.getAttribute("aria-label") || directText || element.textContent || element.tagName).trim().replace(/\\s+/g, " ").slice(0, 80);
    const hasReviewableInlineContent = Boolean(directText) || element.matches("a,button,input,label,select,textarea,[role='button'],[role='link'],[role='menuitem'],[role='tab']");
    const intentionalEllipsis = style.textOverflow === "ellipsis" && ["hidden", "clip"].includes(style.overflowX);
    if (hasReviewableInlineContent && !intentionalEllipsis && (element.scrollWidth > element.clientWidth + 2 || element.scrollHeight > element.clientHeight + 2)) {
      hints.push(`${label}: content overflows its element`);
    }
    if (box.left < -2 || box.top < -2 || box.right > viewportWidth + 2) {
      hints.push(`${label}: visible box extends outside the viewport`);
    }
  }
  return [...new Set(hints)].slice(0, 80);
}"""


@dataclass
class Case:
    case_id: str
    title: str
    targets: list[dict[str, Any]]
    brief: str
    path: Path


@dataclass
class Artifact:
    target_id: str
    title: str
    kind: str
    path: Path
    hints: list[str]


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-").lower()
    return slug or "target"


def _parse_case(path: Path) -> Case:
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---\n"):
        raise ValueError(f"review case is missing front matter: {path}")
    _, front_matter, brief = raw.split("---", 2)
    metadata = yaml.safe_load(front_matter) or {}
    case_id = str(metadata.get("id") or path.stem)
    return Case(
        case_id=case_id,
        title=str(metadata.get("title") or case_id),
        targets=list(metadata.get("targets") or []),
        brief=brief.strip(),
        path=path,
    )


def _load_cases() -> dict[str, Case]:
    return {case.case_id: case for case in (_parse_case(path) for path in sorted(CASE_DIR.glob("*.md")))}


def _parse_named_urls(raw_urls: list[str], env_value: str | None) -> list[tuple[str, str]]:
    values = [*raw_urls]
    if env_value:
        values.extend(item.strip() for item in env_value.split(",") if item.strip())
    urls: list[tuple[str, str]] = []
    for index, raw in enumerate(values, start=1):
        if "=" in raw:
            name, url = raw.split("=", 1)
        else:
            name, url = f"page-{index}", raw
        urls.append((_slugify(name), url))
    return urls


def _target_file_globs(target: dict[str, Any]) -> list[str]:
    globs = target.get("exclude") or []
    return [str(item) for item in globs]


def _is_excluded(path: Path, globs: list[str]) -> bool:
    return any(fnmatch.fnmatch(path.name, pattern) or fnmatch.fnmatch(str(path), pattern) for pattern in globs)


def _svg_contact_sheet_html(root: Path, files: list[Path]) -> str:
    cards = []
    for path in files:
        rel = path.relative_to(root)
        data = b64encode(path.read_bytes()).decode("ascii")
        cards.append(f'<section class="card"><div class="name">{escape(str(rel))}</div><div class="frame"><img src="data:image/svg+xml;base64,{data}" /></div></section>')
    return f"""<!doctype html><meta charset="utf-8"><style>
body{{margin:0;background:#f4f1ed;color:#24201c;font:13px/1.35 -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;padding:24px;}}
h1{{font-size:22px;margin:0 0 18px;}}
.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px;}}
.card{{background:white;border:1px solid #d8d0c8;border-radius:10px;padding:12px;box-shadow:0 1px 2px rgba(0,0,0,.04);}}
.name{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;color:#5f554b;margin-bottom:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}}
.frame{{height:260px;display:flex;align-items:center;justify-content:center;background:linear-gradient(45deg,#fff 25%,#f7f7f7 25%,#f7f7f7 50%,#fff 50%,#fff 75%,#f7f7f7 75%);background-size:24px 24px;border:1px solid #eee7df;border-radius:8px;overflow:hidden;}}
img{{max-width:100%;max-height:100%;display:block;}}
</style><h1>Loopora review contact sheet</h1><div class="grid">{''.join(cards)}</div>"""


def _render_svg_directory(playwright_driver: Any, target: dict[str, Any], output_dir: Path) -> Artifact:
    target_id = _slugify(str(target["id"]))
    source_dir = ROOT / str(target["path"])
    globs = _target_file_globs(target)
    files = [path for path in sorted(source_dir.glob("*.svg")) if not _is_excluded(path, globs)]
    if not files:
        raise ValueError(f"no SVG files matched target {target_id}: {source_dir}")

    browser = playwright_driver.chromium.launch(headless=True)
    try:
        page = browser.new_page(viewport={"width": 1500, "height": 4200}, device_scale_factor=1)
        html = _svg_contact_sheet_html(ROOT, files)
        html_path = output_dir / f"{target_id}.html"
        screenshot_path = output_dir / f"{target_id}.png"
        html_path.write_text(html, encoding="utf-8")
        page.set_content(html, wait_until="load")
        page.screenshot(path=str(screenshot_path), full_page=True)

        hints: list[str] = []
        probe = browser.new_page(viewport={"width": 1400, "height": 1000})
        for path in files:
            probe.set_content(path.read_text(encoding="utf-8"), wait_until="load")
            hints.extend(f"{path.relative_to(ROOT)}: {hint}" for hint in probe.evaluate(SVG_TEXT_HINT_SCRIPT))
        return Artifact(target_id=target_id, title=str(target.get("title") or target_id), kind="svg_directory", path=screenshot_path, hints=hints)
    finally:
        browser.close()


def _render_web_urls(playwright_driver: Any, target: dict[str, Any], output_dir: Path, cli_urls: list[str]) -> list[Artifact]:
    target_id = _slugify(str(target["id"]))
    urls = _parse_named_urls(cli_urls, os.environ.get(str(target.get("urls_env") or "")))
    if not urls and target.get("optional", False):
        return []
    if not urls:
        raise ValueError(f"web target {target_id} needs --url or {target.get('urls_env')}")

    viewports = list(target.get("viewports") or [{"name": "desktop", "width": 1440, "height": 1000}])
    browser = playwright_driver.chromium.launch(headless=True)
    artifacts: list[Artifact] = []
    try:
        for name, url in urls:
            for viewport in viewports:
                viewport_name = _slugify(str(viewport.get("name") or "viewport"))
                width = int(viewport.get("width") or 1440)
                height = int(viewport.get("height") or 1000)
                page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
                page.goto(url, wait_until="networkidle")
                screenshot_path = output_dir / f"{target_id}-{name}-{viewport_name}.png"
                page.screenshot(path=str(screenshot_path), full_page=True)
                hints = [f"{name} {viewport_name}: {hint}" for hint in page.evaluate(WEB_LAYOUT_HINT_SCRIPT)]
                page.close()
                artifacts.append(Artifact(target_id=target_id, title=f"{name} ({viewport_name})", kind="web_url", path=screenshot_path, hints=hints))
    finally:
        browser.close()
    return artifacts


def _write_report(case: Case, artifacts: list[Artifact], output_dir: Path) -> Path:
    lines = [
        f"# {case.title}",
        "",
        f"- Case: `{case.case_id}`",
        f"- Source: `{case.path.relative_to(ROOT)}`",
        f"- Generated: `{datetime.now(UTC).isoformat(timespec='seconds')}`",
        "",
        "## Review Brief",
        "",
        case.brief,
        "",
        "## Artifacts",
        "",
    ]
    for artifact in artifacts:
        rel_path = artifact.path.relative_to(output_dir)
        lines.extend([f"- `{artifact.title}` (`{artifact.kind}`): `{rel_path}`"])
    if not artifacts:
        lines.append("- No artifacts captured. Use the brief as an operator review checklist.")
    lines.extend(["", "## Machine Hints", ""])
    hints = [hint for artifact in artifacts for hint in artifact.hints]
    if hints:
        lines.extend(f"- {hint}" for hint in hints)
    elif artifacts:
        lines.append("- No machine hints. Still inspect the artifacts against the brief.")
    else:
        lines.append("- No machine hints because this case has no captured targets.")
    lines.extend(["", "Machine hints are triage aids, not final pass/fail assertions."])
    report_path = output_dir / "report.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    machine_report = [
        {"target_id": artifact.target_id, "title": artifact.title, "kind": artifact.kind, "path": str(artifact.path), "hints": artifact.hints}
        for artifact in artifacts
    ]
    (output_dir / "machine-hints.json").write_text(json.dumps(machine_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report_path


def _run_case(case: Case, output_root: Path, cli_urls: list[str]) -> Path:
    sync_api = __import__("playwright.sync_api", fromlist=["sync_playwright"])
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    output_dir = output_root / run_id / _slugify(case.case_id)
    output_dir.mkdir(parents=True, exist_ok=True)

    artifacts: list[Artifact] = []
    with sync_api.sync_playwright() as playwright_driver:
        for target in case.targets:
            target_type = target.get("type")
            if target_type == "svg_directory":
                artifacts.append(_render_svg_directory(playwright_driver, target, output_dir))
            elif target_type == "web_urls":
                artifacts.extend(_render_web_urls(playwright_driver, target, output_dir, cli_urls))
            else:
                raise ValueError(f"unknown review target type: {target_type}")
    return _write_report(case, artifacts, output_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run opt-in review cases for rendered surfaces and fuzzy semantic checks.")
    parser.add_argument("--list", action="store_true", help="List available review cases.")
    parser.add_argument("--case", action="append", dest="case_ids", help="Case id to run. Defaults to rendered-surfaces.")
    parser.add_argument("--url", action="append", default=[], help="Web URL to include, optionally as name=url.")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT, help="Directory where review artifacts are written.")
    args = parser.parse_args(argv)

    cases = _load_cases()
    if args.list:
        for case in cases.values():
            print(f"{case.case_id}\t{case.title}")
        return 0

    selected_ids = args.case_ids or ["rendered-surfaces"]
    missing = [case_id for case_id in selected_ids if case_id not in cases]
    if missing:
        print(f"Unknown review case(s): {', '.join(missing)}", file=sys.stderr)
        return 2

    for case_id in selected_ids:
        report_path = _run_case(cases[case_id], args.output_root, args.url)
        print(f"Review report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
