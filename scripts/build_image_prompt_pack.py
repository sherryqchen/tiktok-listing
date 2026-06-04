#!/usr/bin/env python3
"""Build image-generation prompt packs for INKERASTORY listing assets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_CONFIG = Path("data/image_workflows.json")
DEFAULT_MARKDOWN = Path("outputs/image_prompt_pack.md")
DEFAULT_MANIFEST = Path("outputs/image_prompt_manifest.json")


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def selected_themes(config: dict, theme_id: str | None) -> list[dict]:
    themes = config["themes"]
    if not theme_id:
        return themes
    selected = [theme for theme in themes if theme["id"] == theme_id]
    if not selected:
        known = ", ".join(theme["id"] for theme in themes)
        raise SystemExit(f"Unknown theme {theme_id!r}. Known themes: {known}")
    return selected


def build_manifest(config: dict, themes: list[dict]) -> dict:
    brand = config["brand"]
    global_specs = config["global_specs"]
    items = []
    for theme in themes:
        for asset in theme["assets"]:
            prompt = asset["prompt"].strip()
            avoid_line = "Avoid: " + ", ".join(global_specs["avoid"])
            if avoid_line not in prompt:
                prompt = f"{prompt}\n{avoid_line}"
            items.append(
                {
                    "theme_id": theme["id"],
                    "theme_name": theme["display_name"],
                    "slot": asset["slot"],
                    "kind": asset["kind"],
                    "filename": asset["filename"],
                    "hook": asset["hook"],
                    "brand": brand["name"],
                    "target_size": global_specs["listing_image_size"],
                    "prompt": prompt,
                }
            )
    return {"brand": brand, "assets": items}


def build_markdown(config: dict, themes: list[dict], manifest: dict) -> str:
    lines = [
        "# INKERASTORY Image Prompt Pack",
        "",
        f"Brand: {config['brand']['name']}",
        f"Product: {config['brand']['product']}",
        f"Target: {config['brand']['audience']}",
        "",
        "## Workflow",
        "",
        "1. Generate images from the prompts below.",
        "2. Review for product clarity, no official logos, no watermarks, and no misleading scale.",
        "3. Upload approved images to TikTok Shop Media Center or another public image host.",
        "4. Paste the final image URLs into `data/inkerastory_listing.json`.",
        "5. Run `python3 scripts/build_tiktok_bulk_upload.py` to regenerate the upload workbook.",
        "",
        "## Global Avoid List",
        "",
    ]
    for item in config["global_specs"]["avoid"]:
        lines.append(f"- {item}")

    for theme in themes:
        lines.extend(
            [
                "",
                f"## {theme['display_name']}",
                "",
                theme["positioning"],
                "",
                "Compliance notes:",
            ]
        )
        for note in theme["compliance_notes"]:
            lines.append(f"- {note}")
        for asset in [a for a in manifest["assets"] if a["theme_id"] == theme["id"]]:
            lines.extend(
                [
                    "",
                    f"### {asset['slot']} - {asset['filename']}",
                    "",
                    f"Kind: `{asset['kind']}`",
                    f"Hook: {asset['hook']}",
                    "",
                    "```text",
                    asset["prompt"],
                    "```",
                ]
            )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build image prompt packs.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--theme", help="Only output one theme, e.g. world_cup or pets.")
    parser.add_argument("--markdown", default=str(DEFAULT_MARKDOWN))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    args = parser.parse_args()

    config = load_config(Path(args.config))
    themes = selected_themes(config, args.theme)
    manifest = build_manifest(config, themes)
    markdown = build_markdown(config, themes, manifest)

    markdown_path = Path(args.markdown)
    manifest_path = Path(args.manifest)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(markdown, encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote {len(manifest['assets'])} image prompts to {markdown_path}")
    print(f"Wrote machine-readable manifest to {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
