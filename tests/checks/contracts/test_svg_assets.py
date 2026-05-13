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
ALLOWED_FONT_WEIGHTS = {"normal", "bold", "400", "500", "600", "700"}
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
