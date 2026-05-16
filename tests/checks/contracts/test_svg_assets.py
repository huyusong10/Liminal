from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SVG_NAMESPACE = {"svg": "http://www.w3.org/2000/svg"}
PUBLIC_SVG_DIRS = (
    ROOT / "src/loopora/assets/logo",
    ROOT / "assets/diagrams",
)
PUBLIC_MARKDOWN_DOCS = (
    ROOT / "README.md",
    ROOT / "README.zh-CN.md",
    ROOT / "HUMAN-SHAPED-LOOP.md",
    ROOT / "HUMAN-SHAPED-LOOP.zh-CN.md",
)
ALLOWED_FONT_WEIGHTS = {"normal", "bold", "400", "500", "600", "700"}
PUBLIC_MARKDOWN_SVG_REF_PATTERN = re.compile(
    r'<img\s+[^>]*src="(\./(?:assets/diagrams|src/loopora/assets/logo)/[^"]+\.svg)"'
)
LEGACY_WARM_NEUTRALS = {
    "#faf9f6",
    "#f8f5ef",
    "#e8dfd3",
    "#d9d0c5",
    "#8d8378",
    "#6d665d",
    "#211b15",
    "#2c2118",
}


def _public_svg_files() -> list[Path]:
    return [path for directory in PUBLIC_SVG_DIRS for path in sorted(directory.glob("*.svg"))]


def _read_svg(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _public_markdown_svg_refs(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8")
    return PUBLIC_MARKDOWN_SVG_REF_PATTERN.findall(raw)


def test_public_svg_assets_are_parseable_and_avoid_fragile_typography() -> None:
    for path in _public_svg_files():
        raw = _read_svg(path)

        ET.fromstring(raw)
        assert not re.search(r'letter-spacing="-\d', raw), f"{path.relative_to(ROOT)} uses negative tracking"

        font_weights = re.findall(r'font-weight="([^"]+)"', raw)
        unsupported = sorted({weight for weight in font_weights if weight not in ALLOWED_FONT_WEIGHTS})
        assert not unsupported, f"{path.relative_to(ROOT)} uses fragile font weights: {unsupported}"


def test_logo_assets_do_not_depend_on_fixed_white_tiles() -> None:
    for path in sorted((ROOT / "src/loopora/assets/logo").glob("*.svg")):
        root = ET.fromstring(_read_svg(path))
        white_rects = [
            rect
            for rect in root.findall(".//svg:rect", SVG_NAMESPACE)
            if rect.attrib.get("fill", "").lower() in {"white", "#fff", "#ffffff"}
        ]
        assert not white_rects, f"{path.relative_to(ROOT)} should render as a transparent logo asset"


def test_document_diagrams_keep_accessible_metadata_and_current_palette() -> None:
    for path in sorted((ROOT / "assets/diagrams").glob("*.svg")):
        raw = _read_svg(path)
        root = ET.fromstring(raw)

        assert root.attrib.get("role") == "img"
        assert root.attrib.get("aria-labelledby") == "title desc"
        assert root.find("svg:title", SVG_NAMESPACE) is not None
        assert root.find("svg:desc", SVG_NAMESPACE) is not None

        lower_raw = raw.lower()
        leaked_legacy_colors = sorted(color for color in LEGACY_WARM_NEUTRALS if color in lower_raw)
        assert not leaked_legacy_colors, f"{path.relative_to(ROOT)} uses legacy warm-neutral palette: {leaked_legacy_colors}"


def test_judgment_surfaces_diagrams_use_execution_strategy_language() -> None:
    diagram_en = _read_svg(ROOT / "assets" / "diagrams" / "judgment-surfaces.en.svg")
    diagram_zh = _read_svg(ROOT / "assets" / "diagrams" / "judgment-surfaces.zh.svg")

    assert "Execution strategy" in diagram_en
    assert "execution posture" not in diagram_en.lower()
    assert "执行策略" in diagram_zh
    assert "执行姿态" not in diagram_zh


def test_public_markdown_svg_refs_are_manifested_distribution_assets() -> None:
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")

    assert "include README.md README.zh-CN.md" in manifest
    assert "include HUMAN-SHAPED-LOOP.md HUMAN-SHAPED-LOOP.zh-CN.md" in manifest
    assert "recursive-include assets/diagrams *.svg *.md" in manifest
    assert "recursive-include src/loopora/assets/logo *.svg" in manifest

    for doc in PUBLIC_MARKDOWN_DOCS:
        refs = _public_markdown_svg_refs(doc)
        assert refs, f"{doc.relative_to(ROOT)} should keep its public SVG references explicit"
        for ref in refs:
            asset = ROOT / ref.removeprefix("./")
            assert asset.is_file(), f"{doc.relative_to(ROOT)} references missing public SVG {ref}"

    logo_ref = "./src/loopora/assets/logo/logo-with-text-horizontal.svg"
    assert logo_ref in _public_markdown_svg_refs(ROOT / "README.md")
    assert logo_ref in _public_markdown_svg_refs(ROOT / "README.zh-CN.md")


def test_plan_judgment_diagrams_keep_table_rows_inside_panel() -> None:
    for locale in ("en", "zh"):
        root = ET.fromstring((ROOT / "assets" / "diagrams" / f"plan-judgment-structure.{locale}.svg").read_text(encoding="utf-8"))
        panel = next(
            rect
            for rect in root.findall("svg:rect", SVG_NAMESPACE)
            if rect.attrib.get("x") == "58" and rect.attrib.get("y") == "126"
        )
        panel_bottom = float(panel.attrib["y"]) + float(panel.attrib["height"])
        row_rects = [
            rect
            for rect in root.findall("svg:rect", SVG_NAMESPACE)
            if rect.attrib.get("x") == "98" and rect.attrib.get("width") == "804"
        ]

        assert len(row_rects) == 6
        assert max(float(rect.attrib["y"]) + float(rect.attrib["height"]) for rect in row_rects) < panel_bottom

        diagram_text = " ".join(node.text or "" for node in root.iter())
        if locale == "en":
            assert "Execution strategy" in diagram_text
        else:
            assert "执行策略" in diagram_text


def test_readme_first_use_docs_describe_plan_files_without_bundle_internals() -> None:
    readme_en = (ROOT / "README.md").read_text(encoding="utf-8")
    readme_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    diagram_en = ET.fromstring((ROOT / "assets" / "diagrams" / "plan-judgment-structure.en.svg").read_text(encoding="utf-8"))
    diagram_zh = ET.fromstring((ROOT / "assets" / "diagrams" / "plan-judgment-structure.zh.svg").read_text(encoding="utf-8"))

    assert "plan file" in readme_en.lower()
    assert "Bundle" not in readme_en
    assert "方案文件" in readme_zh
    assert "Bundle" not in readme_zh

    diagram_en_text = " ".join(node.text or "" for node in diagram_en.iter())
    diagram_zh_text = " ".join(node.text or "" for node in diagram_zh.iter())
    assert "plan file" in diagram_en_text.lower()
    assert "bundle" not in diagram_en_text.lower()
    assert "方案文件" in diagram_zh_text
    assert "Bundle" not in diagram_zh_text


def test_public_plan_file_judgment_faces_map_to_runtime_contract() -> None:
    readme_en = (ROOT / "README.md").read_text(encoding="utf-8")
    readme_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    core_contract = (ROOT / "design" / "core-ideas" / "core-contract.md").read_text(encoding="utf-8")
    concept_map = (ROOT / "design" / "core-ideas" / "concept-map.md").read_text(encoding="utf-8")
    bundle_design = (ROOT / "design" / "detailed-design" / "08-bundles-and-alignment.md").read_text(
        encoding="utf-8"
    )

    for term in (
        "Task contract",
        "Agent responsibilities",
        "Execution strategy",
        "Run flow",
        "Evidence rules",
        "Verdict rules",
    ):
        assert term in readme_en

    for term in ("任务契约", "Agent 职责", "执行策略", "运行流程", "证据规则", "裁决规则"):
        assert term in readme_zh

    for term in (
        "Task contract",
        "Agent responsibilities",
        "Execution strategy",
        "Run flow",
        "Evidence rules",
        "Verdict rules",
    ):
        assert term in core_contract
    for anchor in ("`spec`", "`roles`", "`workflow`", "`evidence`", "task verdict projection"):
        assert anchor in core_contract
    assert "not another fact source" in core_contract
    assert "不是新的运行期治理 surface" in concept_map
    assert "这是概念压缩，不是另一套 runtime surface" in concept_map
    assert "不能因此新增新的运行期事实源" in bundle_design
