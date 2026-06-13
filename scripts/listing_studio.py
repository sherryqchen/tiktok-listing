#!/usr/bin/env python3
"""Listing production workbench — Category × Art Style selectors, editable prompts,
live preview, and TikTok XLSX export."""

from __future__ import annotations

import json
import io
import mimetypes
import os
import subprocess
import sys
import urllib.parse
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT       = Path(__file__).resolve().parents[1]
DATA_PATH  = ROOT / "data" / "image_workflows.json"
LISTING_PATH = ROOT / "data" / "inkerastory_listing.json"
OUTPUT_DIR = ROOT / "outputs" / "generated_images"
MODES      = {"dry-run", "mock", "live"}


# ── helpers ──────────────────────────────────────────────────────────────────

def load_env_file(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip(); value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def file_url(path: Path) -> str:
    return "/files/" + urllib.parse.quote(path.relative_to(ROOT).as_posix())


def asset_path(theme_id: str, filename: str) -> Path:
    return OUTPUT_DIR / theme_id / Path(filename).name


# ── data access ──────────────────────────────────────────────────────────────

def load_workflow_config() -> dict[str, Any]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def save_workflow_config(config: dict[str, Any]) -> None:
    DATA_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_listing_config() -> dict[str, Any]:
    return normalize_listing_config(json.loads(LISTING_PATH.read_text(encoding="utf-8")))


def save_listing_config(config: dict[str, Any]) -> None:
    LISTING_PATH.write_text(json.dumps(normalize_listing_config(config), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_listing_config(config: dict[str, Any]) -> dict[str, Any]:
    if "listings" not in config:
        config = {
            "template_path": config.get("template_path", "input_template.xlsx"),
            "output_path": config.get("output_path", "outputs/inkerastory_tiktok_bulk_upload.xlsx"),
            "active_listing_id": config.get("active_listing_id", "item_1"),
            "listings": [
                {
                    "id": config.get("active_listing_id", "item_1"),
                    "theme_id": config.get("theme_id", "pets"),
                    "listing": config.get("listing", {}),
                    "skus": config.get("skus", []),
                }
            ],
        }

    listings = config.setdefault("listings", [])
    used_prefixes: set[str] = set()
    for index, item in enumerate(listings, start=1):
        item.setdefault("id", f"item_{index}")
        item.setdefault("theme_id", "pets")
        item["sku_prefix"] = _unique_sku_prefix(item.get("sku_prefix") or _infer_sku_prefix(item) or _base_sku_prefix(item["theme_id"]), used_prefixes)
        used_prefixes.add(item["sku_prefix"])
        item.setdefault("listing", {})
        item.setdefault("skus", [])
        item["listing"].setdefault("images", {})
        item["listing"].setdefault("attributes", {})
    if not listings:
        listings.append({"id": "item_1", "theme_id": "pets", "listing": {"images": {}, "attributes": {}}, "skus": []})
    active_id = config.get("active_listing_id")
    if not active_id or not any(item["id"] == active_id for item in listings):
        config["active_listing_id"] = listings[0]["id"]
    config.setdefault("template_path", "input_template.xlsx")
    config.setdefault("output_path", "outputs/inkerastory_tiktok_bulk_upload.xlsx")
    return config


def _base_sku_prefix(theme_id: str) -> str:
    return {
        "pets": "PET",
        "pets_original": "ORG",
        "pets_royal": "ROY",
        "pets_anime": "ANI",
        "people": "PPL",
        "world_cup": "WC",
    }.get(theme_id, "X")


def _infer_sku_prefix(item: dict[str, Any]) -> str:
    for sku in item.get("skus", []):
        parts = str(sku.get("seller_sku", "")).split("-")
        if len(parts) >= 3 and parts[1]:
            return parts[1]
    return ""


def _unique_sku_prefix(prefix: str, used: set[str]) -> str:
    if prefix not in used:
        return prefix
    base = prefix.rstrip("0123456789") or prefix
    counter = 2
    while f"{base}{counter}" in used:
        counter += 1
    return f"{base}{counter}"


def read_generation_manifest() -> dict[str, Any] | None:
    path = OUTPUT_DIR / "generation_manifest.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def update_prompt(theme_id: str, slot: str, new_prompt: str) -> None:
    """Persist a prompt edit back to image_workflows.json."""
    config = load_workflow_config()
    found = False
    for theme in config["themes"]:
        if theme["id"] == theme_id:
            for asset in theme["assets"]:
                if asset["slot"] == slot:
                    asset["prompt"] = new_prompt
                    found = True
                    break
    if not found:
        raise ValueError(f"theme '{theme_id}' slot '{slot}' not found")
    save_workflow_config(config)


# ── build state ───────────────────────────────────────────────────────────────

def build_state() -> dict[str, Any]:
    load_env_file()
    config = load_workflow_config()
    manifest = read_generation_manifest()

    themes = []
    total = present = 0
    for theme in config["themes"]:
        assets = []
        for asset in theme["assets"]:
            total += 1
            p = asset_path(theme["id"], asset["filename"])
            exists = p.exists()
            present += int(exists)
            assets.append({
                "slot":      asset["slot"],
                "kind":      asset["kind"],
                "filename":  Path(asset["filename"]).name,
                "hook":      asset["hook"],
                "prompt":    asset["prompt"],
                "exists":    exists,
                "image_url": file_url(p) if exists else None,
                "path":      str(p.relative_to(ROOT)),
            })
        themes.append({
            "id":          theme["id"],
            "name":        theme["display_name"],
            "positioning": theme["positioning"],
            "assets":      assets,
        })

    openai_key = os.environ.get("OPENAI_API_KEY", "")
    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    api_key    = openai_key or gemini_key
    provider   = ("openai " if openai_key else "gemini ") if api_key else ""
    return {
        "api_key_loaded":  bool(api_key),
        "api_key_hint":    f"{provider}...{api_key[-4:]}" if api_key else "",
        "generated_count": present,
        "asset_count":     total,
        "themes":          themes,
        "generation_manifest": manifest,
        "template_exists": (ROOT / "input_template.xlsx").exists(),
    }


# ── generation ────────────────────────────────────────────────────────────────

def run_generation(
    theme: str,
    mode: str,
    slot: str | None,
    limit: int | None,
    overwrite: bool,
    provider: str = "openai",
    prompt_override: str | None = None,
) -> dict[str, Any]:
    if mode not in MODES:
        raise ValueError(f"Unsupported mode: {mode}")

    cmd = [sys.executable, "scripts/image_generation_agent.py", "generate",
           "--theme", theme, "--provider", provider]
    if mode == "dry-run":
        cmd.append("--dry-run")
    elif mode == "mock":
        cmd.append("--mock")
    if slot:
        cmd.extend(["--slot", slot])
    if limit:
        cmd.extend(["--limit", str(limit)])
    if overwrite:
        cmd.append("--overwrite")
    if prompt_override and slot:
        cmd.extend(["--prompt", prompt_override])

    result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=600, check=False)
    return {
        "command":    cmd,
        "returncode": result.returncode,
        "stdout":     result.stdout,
        "stderr":     result.stderr,
        "ok":         result.returncode == 0,
    }


def run_export(listing_ids: list[str] | None = None) -> dict[str, Any]:
    import tempfile

    if not (ROOT / "input_template.xlsx").exists():
        return {"ok": False, "error": "input_template.xlsx missing from project root."}

    # If a selection is provided, write a temporary filtered config
    tmp_path: str | None = None
    if listing_ids is not None:
        try:
            config = load_listing_config()
            filtered = [
                item for item in config.get("listings", [])
                if item.get("id") in listing_ids
            ]
            if not filtered:
                return {"ok": False, "error": "No listings selected for export."}
            config["listings"] = filtered
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, encoding="utf-8"
            ) as f:
                json.dump(config, f, ensure_ascii=False)
                tmp_path = f.name
        except Exception as e:
            return {"ok": False, "error": f"Failed to prepare config: {e}"}

    cmd = [sys.executable, "scripts/build_tiktok_bulk_upload.py"]
    if tmp_path:
        cmd.extend(["--config", tmp_path])

    try:
        result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=120, check=False)
    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink()
            except OSError:
                pass

    if result.returncode != 0:
        return {"ok": False, "error": result.stderr or result.stdout}
    out = ROOT / "outputs" / "inkerastory_tiktok_bulk_upload.xlsx"
    if not out.exists():
        return {"ok": False, "error": "Build succeeded but output file not found."}
    import re as _re
    m = _re.search(r"Wrote (\d+) SKU rows", result.stdout)
    rows = int(m.group(1)) if m else 0
    return {"ok": True, "path": str(out.relative_to(ROOT)), "rows": rows, "stdout": result.stdout}


def build_images_zip(theme_id: str) -> tuple[str, bytes, int]:
    config = load_workflow_config()
    theme = next((item for item in config["themes"] if item["id"] == theme_id), None)
    if not theme:
        raise ValueError(f"Theme not found: {theme_id}")

    files: list[tuple[str, Path]] = []
    for asset in theme.get("assets", []):
        path = asset_path(theme_id, asset.get("filename", ""))
        if path.is_file():
            files.append((asset.get("slot", path.stem), path))
    if not files:
        raise FileNotFoundError(f"No generated images found for {theme_id}.")

    safe_theme = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in theme_id)
    buffer = io.BytesIO()
    order_lines = []
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for slot, path in files:
            archive.write(path, arcname=f"{safe_theme}/{path.name}")
            order_lines.append(f"{slot}: {path.name}")
        archive.writestr(f"{safe_theme}/image_order.txt", "\n".join(order_lines) + "\n")
    return f"inkerastory_{safe_theme}_images.zip", buffer.getvalue(), len(files)


# ─────────────────────────────────────────────────────────────────────────────
# HTML
# ─────────────────────────────────────────────────────────────────────────────

INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Listing Studio</title>
<style>
:root{
  --bg:#f0f2f5;--panel:#fff;--ink:#1a1d23;--muted:#6b7280;
  --line:#e5e7eb;--accent:#2563eb;--ok:#059669;--warn:#d97706;--danger:#dc2626;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:Inter,ui-sans-serif,system-ui,sans-serif;background:var(--bg);color:var(--ink);
     height:100vh;display:flex;flex-direction:column;overflow:hidden}

/* header */
header{background:#fff;border-bottom:1px solid var(--line);padding:10px 18px;
       display:flex;align-items:center;justify-content:space-between;flex-shrink:0;gap:12px}
header h1{font-size:16px;font-weight:700;white-space:nowrap}
header .sub{font-size:11px;color:var(--muted)}
.pills{display:flex;gap:7px;flex-wrap:wrap;justify-content:flex-end}
.pill{font-size:11px;padding:3px 9px;border-radius:999px;border:1px solid var(--line);
      color:var(--muted);background:var(--bg);white-space:nowrap}
.pill.ok  {color:var(--ok);   border-color:#a7f3d0;background:#ecfdf5}
.pill.warn{color:var(--warn); border-color:#fde68a;background:#fffbeb}
.pill.err {color:var(--danger);border-color:#fecaca;background:#fef2f2}

/* workspace */
.workspace{display:grid;grid-template-columns:300px 1fr 320px;flex:1;overflow:hidden}
.panel{overflow-y:auto;padding:14px 15px 28px;border-right:1px solid var(--line)}
.panel:last-child{border-right:none}
.ptitle{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;
        color:var(--muted);margin-bottom:12px}

/* form */
.field{margin-bottom:11px}
label{font-size:12px;font-weight:600;color:var(--ink);display:block;margin-bottom:4px}
input[type=text],input[type=number],input[type=url],select,textarea{
  width:100%;padding:6px 9px;border:1px solid var(--line);border-radius:6px;
  font:inherit;font-size:12px;color:var(--ink);background:#fff;outline:none}
input:focus,select:focus,textarea:focus{border-color:var(--accent)}
textarea{resize:vertical}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:8px}

/* section label */
.slabel{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;
        color:var(--muted);margin:13px 0 7px;padding-bottom:5px;border-bottom:1px solid var(--line)}

/* checkboxes */
.ckrow{display:flex;align-items:center;gap:7px;font-size:12px;margin-bottom:5px;
       cursor:pointer;user-select:none}
.ckrow input{width:auto;cursor:pointer}

/* buttons */
button{cursor:pointer;border-radius:6px;font:inherit;font-size:12px;font-weight:600;
       padding:6px 11px;border:1px solid var(--line);background:#fff;color:var(--ink)}
button:hover{background:#f9fafb}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
button.primary:hover{background:#1d4ed8}
button.success{background:var(--ok);border-color:var(--ok);color:#fff}
button.success:hover{background:#047857}
button.sm{font-size:11px;padding:4px 8px}
button:disabled{opacity:.4;cursor:not-allowed!important}

/* sku table */
.sku-wrap{overflow-x:auto}
.sku-table{width:100%;border-collapse:collapse;font-size:11px}
.sku-table th{text-align:left;color:var(--muted);font-weight:600;padding:4px 5px;
              border-bottom:1px solid var(--line);white-space:nowrap}
.sku-table td{padding:4px 5px;vertical-align:middle}
.sku-table tr:nth-child(even) td{background:#fafafa}
.sku-table input[type=number]{width:60px;padding:3px 5px}
.sku-code{font-size:10px;color:var(--muted);font-family:ui-monospace,monospace}

/* asset cards */
.ac{background:#fff;border:1px solid var(--line);border-radius:8px;margin-bottom:10px;overflow:hidden}
.ac.req{border-left:3px solid var(--accent)}
.ac-head{display:flex;align-items:center;justify-content:space-between;
         padding:8px 11px;background:#fafafa;border-bottom:1px solid var(--line);gap:8px}
.ac-slot{font-size:12px;font-weight:700}
.ac-sub{font-size:10px;color:var(--muted);margin-top:1px}
.ac-body{padding:10px 11px;display:flex;gap:10px}
.ac-thumb{width:72px;height:72px;border-radius:6px;border:1px solid var(--line);
          background:#f3f4f6;flex-shrink:0;overflow:hidden;
          display:flex;align-items:center;justify-content:center}
.ac-thumb img{width:100%;height:100%;object-fit:cover;display:block}
.ac-thumb .ni{font-size:9px;color:var(--muted);text-align:center;padding:6px;line-height:1.3}
.ac-ctrl{flex:1;min-width:0}
.prompt-label{display:flex;justify-content:space-between;align-items:center;
              margin-bottom:4px}
.prompt-label span{font-size:10px;font-weight:700;text-transform:uppercase;
                   letter-spacing:.04em;color:var(--muted)}
.ac-prompt{width:100%;font-size:10px;font-family:ui-monospace,Menlo,monospace;
           border:1px solid var(--line);border-radius:5px;padding:5px 7px;
           resize:vertical;line-height:1.5;color:#374151;background:#fafafa}
.ac-prompt:focus{border-color:var(--accent);background:#fff;outline:none}
.url-row{display:flex;gap:5px;margin-top:6px}
.url-row input{flex:1;font-size:11px}
.gen-row{display:flex;gap:5px;margin-top:6px;flex-wrap:wrap}
.gen-row button{font-size:11px;padding:4px 8px}

/* badges */
.badge{font-size:9px;font-weight:700;padding:2px 6px;border-radius:4px;
       text-transform:uppercase;white-space:nowrap}
.badge.req  {background:#dbeafe;color:#1d4ed8}
.badge.opt  {background:#f3f4f6;color:var(--muted)}
.badge.ok   {background:#d1fae5;color:var(--ok)}
.badge.miss {background:#fee2e2;color:var(--danger)}

/* preview */
.tt-card{background:#fff;border:1px solid var(--line);border-radius:10px;
         overflow:hidden;margin-bottom:14px}
.carousel{position:relative;aspect-ratio:1;background:#f3f4f6;overflow:hidden}
.carousel img{width:100%;height:100%;object-fit:cover;display:block}
.no-img-ph{width:100%;height:100%;display:flex;flex-direction:column;
            align-items:center;justify-content:center;color:var(--muted);
            font-size:12px;gap:8px}
.cdots{position:absolute;bottom:7px;left:0;right:0;display:flex;
       justify-content:center;gap:4px;pointer-events:none}
.cdot{width:5px;height:5px;border-radius:3px;background:rgba(255,255,255,.5);
      transition:all .2s;pointer-events:all;cursor:pointer}
.cdot.active{background:#fff;width:14px}
.cnav{position:absolute;top:50%;transform:translateY(-50%);
      width:26px;height:26px;background:rgba(0,0,0,.3);border:none;
      border-radius:50%;color:#fff;font-size:16px;display:flex;
      align-items:center;justify-content:center;cursor:pointer;padding:0}
.cnav.prev{left:7px}.cnav.next{right:7px}
.tt-body{padding:11px 13px}
.tt-name{font-size:13px;font-weight:600;line-height:1.35;margin-bottom:5px}
.tt-price{font-size:20px;font-weight:700;color:#e02020;margin-bottom:3px}
.tt-rating{font-size:11px;color:var(--muted);margin-bottom:9px}
.tt-desc{font-size:11px;color:var(--muted);line-height:1.5;
         max-height:72px;overflow:hidden;position:relative}
.tt-desc::after{content:'';position:absolute;bottom:0;left:0;right:0;
                height:24px;background:linear-gradient(transparent,#fff)}

/* export */
.exp-box{background:#fff;border:1px solid var(--line);border-radius:8px;padding:13px;margin-bottom:12px}
.exp-box-title{font-size:12px;font-weight:700;margin-bottom:10px}
.exp-box button{width:100%;margin-bottom:6px}
.exp-status{font-size:11px;color:var(--muted);min-height:16px}

/* console */
.console{background:#111827;color:#a7f3d0;border-radius:6px;
         padding:9px 11px;font:11px/1.5 ui-monospace,Menlo,monospace;
         white-space:pre-wrap;overflow-wrap:anywhere;max-height:120px;
         overflow-y:auto;margin-top:10px}

/* image gallery row */
.gallery{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}
.gallery-item{position:relative;width:64px;height:64px;border-radius:6px;
              border:1px solid var(--line);overflow:hidden;cursor:pointer}
.gallery-item img{width:100%;height:100%;object-fit:cover}
.gallery-label{position:absolute;bottom:0;left:0;right:0;
               font-size:8px;background:rgba(0,0,0,.5);color:#fff;
               padding:2px 3px;text-align:center;white-space:nowrap;overflow:hidden}
.gallery-download{position:absolute;top:3px;right:3px;width:22px;height:22px;
                  padding:0;border:0;border-radius:4px;background:rgba(255,255,255,.92);
                  color:var(--ink);font-size:12px;line-height:1;display:flex;
                  align-items:center;justify-content:center}
.gallery-download:hover{background:#fff}

@media(max-width:960px){
  body{overflow:auto}
  .workspace{grid-template-columns:1fr;overflow:visible}
  .panel{overflow:visible;border-right:none;border-bottom:1px solid var(--line)}
}

/* listing tabs */
.ltab-bar{background:#fff;border-bottom:1px solid var(--line);display:flex;align-items:stretch;
          overflow-x:auto;flex-shrink:0;scrollbar-width:none}
.ltab-bar::-webkit-scrollbar{display:none}
.ltab{display:flex;align-items:center;gap:6px;padding:9px 14px;border:none;border-bottom:3px solid transparent;
      background:none;cursor:pointer;white-space:nowrap;font:inherit;font-size:12px;font-weight:600;
      color:var(--muted);border-radius:0;flex-shrink:0}
.ltab:hover:not(.active){background:#f8fafc;color:var(--ink)}
.ltab.active{color:var(--accent);border-bottom-color:var(--accent)}
.ltab-emoji{font-size:13px}
.ltab-name{max-width:120px;overflow:hidden;text-overflow:ellipsis}
.ltab-close{font-size:14px;line-height:1;color:var(--muted);opacity:.5;margin-left:2px}
.ltab-close:hover{opacity:1;color:var(--danger)}
.ltab-add{padding:9px 14px;border:none;background:none;cursor:pointer;font-size:18px;
          color:var(--muted);font-weight:300;line-height:1;border-radius:0;flex-shrink:0}
.ltab-add:hover{color:var(--accent);background:#f8fafc}
.ltab-sep{width:1px;background:var(--line);margin:6px 0;flex-shrink:0}

/* export listing summary */
.exp-list{margin:8px 0 0}
.exp-row{display:flex;align-items:center;gap:7px;padding:6px 8px;border-radius:6px;
         font-size:11px;border:1px solid var(--line);margin-bottom:5px;background:#fafafa}
.exp-row.active-row{border-color:var(--accent);background:#eff6ff}
.exp-row-icon{font-size:14px;flex-shrink:0}
.exp-row-info{flex:1;min-width:0}
.exp-row-name{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.exp-row-meta{color:var(--muted);font-size:10px;margin-top:1px}
.exp-row-status{font-size:10px;font-weight:700;padding:2px 6px;border-radius:4px}
.exp-row-status.ok{background:#d1fae5;color:var(--ok)}
.exp-row-status.warn{background:#fef3c7;color:var(--warn)}
</style>
</head>
<body>
<header>
  <div><h1>INKERASTORY Listing Studio</h1><div class="sub">TikTok Shop listing workbench</div></div>
  <div class="pills" id="pills"></div>
</header>

<!-- listing tabs bar -->
<div class="ltab-bar" id="listingTabs"></div>

<div class="workspace">

<!-- ══════════ Panel 1 — Listing Builder ══════════ -->
<div class="panel">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
    <div class="ptitle" style="margin:0">Listing Detail</div>
    <button class="sm" id="dupeListingBtn" title="Duplicate active listing">Duplicate</button>
  </div>

  <div class="row2">
    <div class="field">
      <label>Content Category</label>
      <select id="fCategory">
        <option value="pets">🐾 Pets</option>
        <option value="people">👨‍👩‍👧 People</option>
        <option value="world_cup">⚽ World Cup</option>
      </select>
    </div>
    <div class="field">
      <label>Art Style</label>
      <select id="fArtStyle"></select>
    </div>
  </div>

  <div class="row2">
    <div class="field">
      <label>Purpose</label>
      <select id="fPurpose">
        <option>Gift</option><option>Home Decor</option><option>Memorial</option>
        <option>Wedding</option><option>Anniversary</option><option>Seasonal</option>
      </select>
    </div>
    <div class="field">
      <label>Aesthetic</label>
      <select id="fAesthetic">
        <option>Minimalist</option><option>Rustic</option><option>Modern</option>
        <option>Warm</option><option>Elegant</option>
      </select>
    </div>
  </div>

  <div class="field">
    <label>Product Name
      <button class="sm" id="fillNameBtn" style="float:right;font-weight:400">Auto-fill</button>
    </label>
    <input type="text" id="fName" placeholder="e.g. Personalized Pet Portrait Canvas…"/>
  </div>

  <div class="field">
    <label>Description
      <button class="sm" id="fillDescBtn" style="float:right;font-weight:400">Use Template</button>
    </label>
    <textarea id="fDesc" rows="8"></textarea>
  </div>

  <div class="slabel">Product Types</div>
  <label class="ckrow"><input type="checkbox" id="typePrint"  checked> Print Only</label>
  <label class="ckrow"><input type="checkbox" id="typeCanvas" checked> Stretched Canvas</label>

  <div class="slabel">Sizes</div>
  <div id="sizeChecks"></div>

  <div class="slabel">SKU Pricing</div>
  <div class="sku-wrap">
    <table class="sku-table">
      <thead><tr><th>SKU</th><th>Type</th><th>Size</th><th>Price ($)</th></tr></thead>
      <tbody id="skuBody"></tbody>
    </table>
  </div>

  <div style="display:flex;gap:7px;margin-top:13px">
    <button class="primary" id="saveBtn" style="flex:1">Save Config</button>
    <button id="reloadBtn">Reload</button>
  </div>
  <div id="saveStatus" style="font-size:11px;min-height:15px;margin-top:5px"></div>
</div>

<!-- ══════════ Panel 2 — Image Assets ══════════ -->
<div class="panel">
  <div class="ptitle">Image Assets</div>

  <div style="display:flex;justify-content:space-between;align-items:center;
              margin-bottom:10px;gap:8px;flex-wrap:wrap">
    <div style="font-size:11px;color:var(--muted)">
      <strong style="color:var(--ink)">Closeup + Scene required</strong> · Mood + Room optional
    </div>
    <div style="display:flex;gap:6px;align-items:center">
      <select id="providerSel" style="font-size:11px;padding:4px 7px;height:auto;width:auto">
        <option value="openai">OpenAI</option>
        <option value="gemini">Gemini</option>
      </select>
      <button id="genMockBtn" class="sm">Mock All</button>
      <button id="genLiveBtn" class="primary sm">Generate All</button>
    </div>
  </div>

  <div id="assetCards"></div>

  <!-- All Generated Images Gallery -->
  <div class="slabel" style="margin-top:14px">All Generated Images</div>
  <div id="gallery" class="gallery"></div>

  <div class="console" id="console">Ready.</div>
</div>

<!-- ══════════ Panel 3 — Preview + Export ══════════ -->
<div class="panel">
  <div class="ptitle">Listing Preview</div>

  <div class="tt-card">
    <div class="carousel" id="carousel">
      <div class="no-img-ph" id="noImgPh">
        <svg width="36" height="36" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" stroke-width="1.3" opacity=".3">
          <rect x="3" y="3" width="18" height="18" rx="2"/>
          <circle cx="8.5" cy="8.5" r="1.5"/>
          <path d="m21 15-5-5L5 21"/>
        </svg>
        No images yet
      </div>
      <img id="cImg" alt="" style="display:none"/>
      <button class="cnav prev" id="cPrev" onclick="shiftC(-1)" style="display:none">&#8249;</button>
      <button class="cnav next" id="cNext" onclick="shiftC(1)"  style="display:none">&#8250;</button>
      <div class="cdots" id="cDots"></div>
    </div>
    <div class="tt-body">
      <div class="tt-name"   id="pvName">Product Name</div>
      <div class="tt-price"  id="pvPrice">—</div>
      <div class="tt-rating">★★★★★ 4.8 · 200+ sold</div>
      <div class="tt-desc"   id="pvDesc">Description will appear here.</div>
    </div>
  </div>

  <div class="exp-box">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
      <div class="exp-box-title" style="margin:0">Export &amp; Upload</div>
      <div style="display:flex;gap:8px">
        <span style="font-size:11px;color:var(--accent);cursor:pointer" onclick="toggleAllExport(true)">Select all</span>
        <span style="font-size:11px;color:var(--muted)">·</span>
        <span style="font-size:11px;color:var(--muted);cursor:pointer" onclick="toggleAllExport(false)">None</span>
      </div>
    </div>
    <div id="exportListingSummary" class="exp-list"></div>
    <div style="display:flex;gap:6px;margin-top:9px">
      <button class="success" id="exportBtn" style="flex:1">Build XLSX</button>
      <button id="xlsxDownloadBtn" title="Download the last built XLSX file" disabled>⬇ Download</button>
    </div>
    <button id="downloadImagesBtn" style="width:100%;margin-top:5px">Download Current Images</button>
    <div class="exp-status" id="expStatus" style="margin-top:6px"></div>
    <div id="xlsxInfo" style="font-size:10px;color:var(--muted);margin-top:4px;min-height:14px"></div>
  </div>

  <div class="slabel">Image URLs (for production export)</div>
  <div id="urlInputs"></div>
</div>

</div><!-- .workspace -->

<script>
// ─── constants ───────────────────────────────────────────────────────────────
const SIZES = ['8 x 12 in','12 x 18 in','16 x 24 in','24 x 36 in'];

// Category → available art styles (id maps to theme_id as `{cat}_{styleId}`)
const CAT_STYLES = {
  pets: [
    { id:'classic',  label:'🎨 Classic Portrait',       theme:'pets' },
    { id:'original', label:'📷 Original Photo Print',   theme:'pets_original' },
    { id:'royal',    label:'👑 Royal Portrait (AI)',     theme:'pets_royal' },
    { id:'anime',    label:'🌸 Anime / Kawaii (AI)',     theme:'pets_anime' },
  ],
  people: [
    { id:'classic',  label:'🎨 Classic Portrait',       theme:'people' },
  ],
  world_cup: [
    { id:'classic',  label:'⚽ Soccer Fan',              theme:'world_cup' },
  ],
};

const SLOT_META = {
  main_image: { label:'Closeup / Product Detail', required:true,
                hint:'Clean studio shot — white bg, shows product quality & texture' },
  image_2:    { label:'Scene / Lifestyle',         required:true,
                hint:'Context shot — Before/After, lifestyle, or emotional hook' },
  image_3:    { label:'Mood / Story',              required:false,
                hint:'Owner reaction, gift moment, or atmospheric scene' },
  image_4:    { label:'Room Mockup',               required:false,
                hint:'Shows scale in a real room — helps buyers visualise' },
  image_5:    { label:'Size Chart',                required:false,
                hint:'4 canvases side-by-side (8×12 → 24×36) with size labels — helps buyers choose' },
  image_6:    { label:'Print Only Mockup',         required:false,
                hint:'Flat unframed print flat-lay — shows buyers what the poster/print version looks like' },
};

// Description templates keyed by theme_id
const DESC = {
  pets: `INKERASTORY - Ink Your Pet Story on Canvas

Turn your favorite dog, cat, or pet photo into warm personalized wall art — perfect for home decor, gifting, and keepsakes.

Each piece is made to order. Add your pet's name, a short quote, or keep it portrait-focused.

Perfect for:
- Dog & cat portraits  ·  Pet memorial keepsakes
- New pet parent gifts  ·  Birthday & holiday gifts
- Multi-pet family photos

Product Features:
- Personalized from your photo  ·  Premium HD printing
- Fade-resistant inks  ·  Print Only or Stretched Canvas
- Multiple sizes

INKERASTORY - Because every pet story deserves a place on your wall.`,

  pets_original: `INKERASTORY - Your Pet Photo, Printed Perfectly on Canvas

Upload your favorite pet photo and we print it exactly as you captured it — every whisker, every color, every memory preserved in HD quality on premium canvas.

✅ How it works:
1. Order & choose your size
2. Upload your pet photo in the order notes
3. We print, quality-check & ship

Perfect for:
- Dog & cat photos  ·  Preserving a beloved pet's memory
- Gift for pet owners  ·  Living room & bedroom wall art

Quality:
- True-to-life color accuracy  ·  Fade-resistant inks
- Print Only or Stretched Canvas

Photo tip: bright, clear, front-facing photos work best.

INKERASTORY - Your pet, your photo, your canvas.`,

  pets_royal: `INKERASTORY - AI Royal Portrait | Upload Your Pet Photo

Upload your pet photo and we transform it into a stunning royal oil-painting portrait — then print it on premium canvas.

👑 Your pet reimagined as nobility: velvet cloak, gold crown, classical oil-painting style.

✅ How it works:
1. Order & choose your size
2. Upload your pet photo in the order notes
3. We apply AI royal transformation + print
4. Shipped to you

Perfect for:
- Unique pet lover gifts  ·  Conversation-starter wall art
- Birthday & holiday gifts  ·  Dog & cat owners who love art

Print Quality:
- Premium HD canvas  ·  Fade-resistant inks
- Print Only or Stretched Canvas

INKERASTORY - Your pet, royally transformed.`,

  pets_anime: `INKERASTORY - AI Anime Pet Portrait | Upload Your Pet Photo

Upload your pet photo and we transform it into an adorable kawaii anime illustration — then print it on premium canvas.

🌸 Cute anime art style: big expressive eyes, soft pastel colors, original kawaii character.

✅ How it works:
1. Order & choose your size
2. Upload your pet photo in the order notes
3. We apply AI anime transformation + print
4. Shipped to you

Perfect for:
- Anime lovers with pets  ·  Fun & unique pet gifts
- Bedroom, gaming room & aesthetic decor  ·  Kids & young adults

Print Quality:
- Premium HD canvas  ·  Fade-resistant inks
- Print Only or Stretched Canvas

INKERASTORY - Your pet, animated with love.`,

  people: `INKERASTORY - Ink Your Story on Canvas

Transform your cherished photos of family, couples, or friends into stunning personalized wall art for life's most meaningful moments.

Perfect for:
- Wedding & anniversary gifts  ·  Family portrait wall art
- Couples gifts  ·  Graduation & milestone gifts
- Baby & newborn keepsakes  ·  Mother's & Father's Day

Product Features:
- Personalized from your photo  ·  Premium HD printing
- Print Only or Stretched Canvas  ·  Multiple sizes

INKERASTORY - Because every story deserves a place on your wall.`,

  world_cup: `INKERASTORY - Ink Your Soccer Story on Canvas

Celebrate the beautiful game with personalized soccer memory wall art. Turn your favorite match-day or family fan photo into a premium canvas.

Perfect for:
- Soccer fan gifts  ·  Match-day memory keepsakes
- Watch-party celebration prints  ·  Sports home decor
- Father's Day & holiday gifts

Product Features:
- Personalized from your photo  ·  Premium HD printing
- Print Only or Stretched Canvas  ·  Multiple sizes

INKERASTORY - Because every soccer story deserves a place on your wall.`,
};

const NAME_TPL = {
  pets:          'Personalized Pet Portrait Canvas Print | Custom Dog Cat Photo Wall Art | Pet Gift | INKERASTORY',
  pets_original: 'Custom Pet Photo Canvas | Upload Your Dog Cat Photo | Premium HD Print | INKERASTORY',
  pets_royal:    'AI Royal Pet Portrait Canvas | Upload Photo → Royal Oil Painting Style | Dog Cat Gift | INKERASTORY',
  pets_anime:    'AI Anime Pet Portrait Canvas | Upload Photo → Kawaii Style | Custom Dog Cat Art | INKERASTORY',
  people:        'Personalized Portrait Canvas Print | Custom Family Photo Wall Art | Meaningful Gift | INKERASTORY',
  world_cup:     'Custom Soccer Fan Canvas | Personalized Match Day Memory Wall Art | Soccer Gift | INKERASTORY',
};

const DEFAULT_PRICES = {
  'Print Only':      {'8 x 12 in':14.98,'12 x 18 in':17.99,'16 x 24 in':26.99,'24 x 36 in':39.99},
  'Stretched Canvas':{'8 x 12 in':19.99,'12 x 18 in':29.99,'16 x 24 in':39.99,'24 x 36 in':50.99},
};
const DEFAULT_DIMS = {
  'Print Only':      {weight_lb:.21,length_in:9.84, width_in:5.91, height_in:.79},
  'Stretched Canvas':{weight_lb:.63,length_in:12.60,width_in:8.27, height_in:.79},
};
const THEME_SKU_PREFIX = {
  pets:'PET',pets_original:'ORG',pets_royal:'ROY',pets_anime:'ANI',
  people:'PPL',world_cup:'WC'
};

// ─── state ───────────────────────────────────────────────────────────────────
let listing  = {};
let imgState = {};
let cImages  = [];
let cIdx     = 0;

function normalizeListingConfig(data) {
  const cfg = data || {};
  if (!Array.isArray(cfg.listings)) {
    cfg.listings = [{
      id: cfg.active_listing_id || 'item_1',
      theme_id: cfg.theme_id || 'pets',
      listing: cfg.listing || {},
      skus: cfg.skus || [],
    }];
  }
  if (!cfg.listings.length) {
    cfg.listings.push({id:'item_1', theme_id:'pets', listing:{images:{}, attributes:{}}, skus:[]});
  }
  const usedPrefixes = new Set();
  cfg.listings.forEach((item, idx)=>{
    item.id = item.id || `item_${idx+1}`;
    item.theme_id = item.theme_id || 'pets';
    let prefix = item.sku_prefix || inferSkuPrefix(item) || baseSkuPrefix(item.theme_id);
    if (usedPrefixes.has(prefix)) {
      const base = baseSkuPrefix(item.theme_id);
      let suffix = 2;
      while (usedPrefixes.has(`${base}${suffix}`)) suffix += 1;
      prefix = `${base}${suffix}`;
    }
    item.sku_prefix = prefix;
    usedPrefixes.add(prefix);
    item.listing = item.listing || {};
    item.listing.images = item.listing.images || {};
    item.listing.attributes = item.listing.attributes || {};
    item.skus = item.skus || [];
  });
  if (!cfg.active_listing_id || !cfg.listings.some(item=>item.id===cfg.active_listing_id)) {
    cfg.active_listing_id = cfg.listings[0].id;
  }
  cfg.template_path = cfg.template_path || 'input_template.xlsx';
  cfg.output_path = cfg.output_path || 'outputs/inkerastory_tiktok_bulk_upload.xlsx';
  return cfg;
}

function activeItem() {
  listing = normalizeListingConfig(listing);
  return listing.listings.find(item=>item.id===listing.active_listing_id) || listing.listings[0];
}

function activeListingData() {
  return activeItem().listing || {};
}

function listingLabel(item, idx) {
  const name = item.listing?.product_name?.trim();
  return name ? name.slice(0, 64) : `Item ${idx+1}`;
}

function uniqueItemId() {
  return `item_${Date.now().toString(36)}_${Math.random().toString(36).slice(2,6)}`;
}

function baseSkuPrefix(themeId) {
  return THEME_SKU_PREFIX[themeId] || 'X';
}

function inferSkuPrefix(item) {
  const sku = item.skus?.find(row=>row.seller_sku)?.seller_sku || '';
  const parts = sku.split('-');
  return parts.length >= 3 ? parts[1] : '';
}

function uniqueSkuPrefix(themeId, excludeId=null) {
  const base = baseSkuPrefix(themeId);
  const used = new Set((listing.listings||[])
    .filter(item=>item.id!==excludeId)
    .map(item=>item.sku_prefix || inferSkuPrefix(item))
    .filter(Boolean));
  if (!used.has(base)) return base;
  for (let i=2; i<100; i++) {
    const candidate = `${base}${i}`;
    if (!used.has(candidate)) return candidate;
  }
  return `${base}${Date.now().toString(36).slice(-3).toUpperCase()}`;
}

function skuSizeToken(size) {
  return size.replace(/\s*x\s*/i,'').replace(/ in$/,'').replace(/\s/g,'');
}

function buildSkus(themeId, skuPrefix, types=['Print Only','Stretched Canvas'], sizes=SIZES, existing=[]) {
  const ex = {};
  (existing||[]).forEach(s=>{ex[`${s.type}|${s.size}`]=s;});
  const skus = [];
  types.forEach(type => {
    sizes.forEach(size => {
      const old = ex[`${type}|${size}`] || {};
      const d = DEFAULT_DIMS[type] || DEFAULT_DIMS['Print Only'];
      const T = type==='Print Only'?'P':'C';
      skus.push({
        seller_sku:`IS-${skuPrefix}-${T}-${skuSizeToken(size)}`,
        type,
        size,
        price: old.price ?? DEFAULT_PRICES[type]?.[size] ?? 19.99,
        weight_lb: old.weight_lb??d.weight_lb,
        length_in: old.length_in??d.length_in,
        width_in:  old.width_in ??d.width_in,
        height_in: old.height_in??d.height_in,
      });
    });
  });
  return skus;
}

// ─── init ────────────────────────────────────────────────────────────────────
async function init() {
  buildSizeChecks();
  updateStyleOptions();
  await loadAll();
  setupListeners();
}

async function loadAll() {
  const [s, l] = await Promise.all([
    fetch('/api/state').then(r=>r.json()).catch(()=>({})),
    fetch('/api/listing').then(r=>r.json()).catch(()=>({})),
  ]);
  imgState = s; listing = normalizeListingConfig(l);
  renderPills();
  renderListingTabs();
  populateForm();
  renderAssets();
  renderGallery();
  renderPreview();
  renderUrlInputs();
}

const THEME_EMOJI = {
  pets:'🐾', pets_original:'📷', pets_royal:'👑', pets_anime:'🌸',
  people:'👨‍👩‍👧', world_cup:'⚽',
};

function tabLabel(item) {
  const name = item.listing?.product_name?.trim();
  if (name) {
    const short = name.split('|')[0].trim();
    return short.length > 24 ? short.slice(0,22)+'…' : short;
  }
  const emoji = THEME_EMOJI[item.theme_id] || '📋';
  return emoji + ' New Listing';
}

function renderListingTabs() {
  const bar = document.getElementById('listingTabs');
  if (!bar) return;
  bar.innerHTML = '';
  listing.listings.forEach((item, idx) => {
    const tab = document.createElement('button');
    tab.className = 'ltab' + (item.id===listing.active_listing_id?' active':'');
    const emoji = THEME_EMOJI[item.theme_id] || '📋';
    const label = tabLabel(item);
    const canDel = listing.listings.length > 1;
    tab.innerHTML = `<span class="ltab-emoji">${emoji}</span>
      <span class="ltab-name">${label}</span>
      ${canDel?`<span class="ltab-close" data-id="${item.id}" title="Delete">×</span>`:''}`;
    tab.addEventListener('click', e => {
      if (e.target.classList.contains('ltab-close')) return;
      switchListing(item.id);
    });
    if (canDel) {
      tab.querySelector('.ltab-close').addEventListener('click', e => {
        e.stopPropagation();
        if (!confirm(`Delete listing "${label}"?`)) return;
        deleteListingById(item.id);
      });
    }
    bar.appendChild(tab);
  });
  const sep = document.createElement('div');
  sep.className = 'ltab-sep';
  bar.appendChild(sep);
  const addBtn = document.createElement('button');
  addBtn.className = 'ltab-add';
  addBtn.title = 'Add new listing';
  addBtn.textContent = '+';
  addBtn.addEventListener('click', addListing);
  bar.appendChild(addBtn);
  renderExportSummary();
}

function renderExportSummary() {
  const el = document.getElementById('exportListingSummary');
  if (!el) return;
  el.innerHTML = '';
  listing.listings.forEach(item => {
    const isActive = item.id === listing.active_listing_id;
    const emoji = THEME_EMOJI[item.theme_id] || '📋';
    const name = item.listing?.product_name?.trim() || 'Untitled Listing';
    const skuCount = item.skus?.length || 0;
    const imgCount = Object.values(item.listing?.images||{}).filter(Boolean).length;
    const themeAssets = imgState.themes?.find(t=>t.id===item.theme_id)?.assets||[];
    const genCount = themeAssets.filter(a=>a.image_url).length;
    const imgTotal = Math.max(imgCount + genCount, 0);
    const ready = skuCount > 0 && (imgCount > 0 || genCount > 0);

    const row = document.createElement('div');
    row.className = 'exp-row' + (isActive?' active-row':'');

    const ckId = `expck_${item.id}`;
    row.innerHTML = `
      <input type="checkbox" id="${ckId}" class="exp-check" data-id="${item.id}"
             style="flex-shrink:0;cursor:pointer" checked>
      <label for="${ckId}" class="exp-row-icon" style="cursor:pointer">${emoji}</label>
      <div class="exp-row-info" style="cursor:pointer">
        <div class="exp-row-name" title="${name}">${name.slice(0,36)+(name.length>36?'…':'')}</div>
        <div class="exp-row-meta">${skuCount} SKUs · ${imgTotal > 0 ? imgTotal+' images' : 'No images yet'}</div>
      </div>
      <span class="exp-row-status ${ready?'ok':'warn'}">${ready?'Ready':'Incomplete'}</span>`;

    // clicking row body (not checkbox) = switch to that listing
    row.querySelector('.exp-row-info').addEventListener('click', () => switchListing(item.id));
    row.querySelector('.exp-row-icon').addEventListener('click', () => switchListing(item.id));
    row.querySelector('.exp-check').addEventListener('change', updateExportBtn);

    el.appendChild(row);
  });
  updateExportBtn();
}

function getSelectedListingIds() {
  return [...document.querySelectorAll('.exp-check:checked')].map(el => el.dataset.id);
}

function updateExportBtn() {
  const sel = document.querySelectorAll('.exp-check:checked').length;
  const total = listing.listings?.length || 0;
  const btn = document.getElementById('exportBtn');
  if (!btn) return;
  btn.textContent = total <= 1
    ? '⬇ Export Listing → XLSX'
    : `⬇ Export ${sel} of ${total} Listings → XLSX`;
  btn.disabled = sel === 0;
}

function toggleAllExport(checked) {
  document.querySelectorAll('.exp-check').forEach(el => { el.checked = checked; });
  updateExportBtn();
}

// ─── pills ───────────────────────────────────────────────────────────────────
function renderPills() {
  const el = document.getElementById('pills');
  el.innerHTML = '';
  const ok = imgState.api_key_loaded;
  mkPill(el, ok?'ok':'warn', ok?`API ${imgState.api_key_hint}`:'No API key');
  mkPill(el, '', `${imgState.generated_count||0}/${imgState.asset_count||0} images`);
  const n = listing.listings?.length || 1;
  mkPill(el, n > 1 ? 'ok' : '', `${n} listing${n===1?'':'s'}`);
  if (imgState.template_exists===false) mkPill(el,'err','template.xlsx missing');
}
function mkPill(p,cls,txt){
  const s=document.createElement('span');s.className='pill '+cls;s.textContent=txt;p.appendChild(s);
}

// ─── style options ────────────────────────────────────────────────────────────
function updateStyleOptions() {
  const cat = document.getElementById('fCategory').value;
  const sel = document.getElementById('fArtStyle');
  const prev = sel.value;
  sel.innerHTML = '';
  (CAT_STYLES[cat]||[]).forEach(s => {
    const o = document.createElement('option');
    o.value = s.id; o.textContent = s.label;
    sel.appendChild(o);
  });
  // restore previous selection if valid
  if ([...sel.options].some(o=>o.value===prev)) sel.value = prev;
}

function getThemeId() {
  const cat   = document.getElementById('fCategory').value;
  const style = document.getElementById('fArtStyle').value;
  const entry = (CAT_STYLES[cat]||[]).find(s=>s.id===style);
  return entry ? entry.theme : cat;
}

function syncActiveTheme() {
  const item = activeItem();
  const themeId = getThemeId();
  if (item.theme_id !== themeId) {
    item.theme_id = themeId;
    item.sku_prefix = uniqueSkuPrefix(themeId, item.id);
  }
}

function setThemeControls(themeId) {
  const match = Object.entries(CAT_STYLES).flatMap(([cat, styles]) =>
    styles.map(style => ({cat, styleId:style.id, theme:style.theme}))
  ).find(item => item.theme === themeId);
  if (!match) return;
  document.getElementById('fCategory').value = match.cat;
  updateStyleOptions();
  document.getElementById('fArtStyle').value = match.styleId;
}

// ─── form populate ────────────────────────────────────────────────────────────
function buildSizeChecks() {
  const el = document.getElementById('sizeChecks');
  SIZES.forEach(s => {
    const lbl = document.createElement('label');
    lbl.className = 'ckrow';
    lbl.innerHTML = `<input type="checkbox" class="szck" value="${s}" checked> ${s}`;
    el.appendChild(lbl);
  });
}

function populateForm() {
  const item = activeItem();
  const l = item.listing || {};
  setThemeControls(item.theme_id || 'pets');
  document.getElementById('fName').value     = l.product_name       || '';
  document.getElementById('fDesc').value     = l.product_description || '';
  document.getElementById('fAesthetic').value= l.attributes?.style  || 'Minimalist';
  document.getElementById('fPurpose').value  = l.attributes?.occasion|| 'Gift';

  const types = new Set((item.skus||[]).map(s=>s.type));
  document.getElementById('typePrint').checked  = types.size===0||types.has('Print Only');
  document.getElementById('typeCanvas').checked = types.size===0||types.has('Stretched Canvas');

  const sizes = new Set((item.skus||[]).map(s=>s.size));
  document.querySelectorAll('.szck').forEach(cb=>{
    cb.checked = sizes.size===0 || sizes.has(cb.value);
  });
  renderSkuTable();
}

// ─── sku table ────────────────────────────────────────────────────────────────
function getSizes() { return [...document.querySelectorAll('.szck:checked')].map(c=>c.value); }
function getTypes() {
  const t=[];
  if(document.getElementById('typePrint').checked)  t.push('Print Only');
  if(document.getElementById('typeCanvas').checked) t.push('Stretched Canvas');
  return t;
}

function renderSkuTable() {
  const sizes = getSizes(), types = getTypes();
  const themeId = getThemeId();
  const body = document.getElementById('skuBody');
  body.innerHTML = '';

  const ex = {};
  (activeItem().skus||[]).forEach(s=>{ex[`${s.type}|${s.size}`]=s;});

  const skuPrefix = activeItem().sku_prefix || baseSkuPrefix(themeId);

  types.forEach(type => {
    sizes.forEach(size => {
      const key   = `${type}|${size}`;
      const price = ex[key]?.price ?? DEFAULT_PRICES[type]?.[size] ?? 19.99;
      const T = type==='Print Only'?'P':'C';
      const S = skuSizeToken(size);
      const sku = `IS-${skuPrefix}-${T}-${S}`;
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td class="sku-code">${sku}</td>
        <td>${type==='Print Only'?'Print':'Canvas'}</td>
        <td>${size}</td>
        <td><input type="number" min="0.01" step="0.01" value="${price}"
             class="priceinput" data-type="${type}" data-size="${size}"
             oninput="renderPreview()"/></td>`;
      body.appendChild(tr);
    });
  });
  renderPreview();
}

// ─── listeners ───────────────────────────────────────────────────────────────
function setupListeners() {
  document.getElementById('dupeListingBtn').addEventListener('click', duplicateListing);

  document.getElementById('typePrint').addEventListener('change',  renderSkuTable);
  document.getElementById('typeCanvas').addEventListener('change', renderSkuTable);
  document.querySelectorAll('.szck').forEach(cb=>cb.addEventListener('change',()=>{
    renderSkuTable(); renderAssets(); renderPreview();
  }));

  document.getElementById('fCategory').addEventListener('change',()=>{
    updateStyleOptions(); syncActiveTheme(); renderSkuTable(); renderAssets(); renderPreview();
  });
  document.getElementById('fArtStyle').addEventListener('change',()=>{
    syncActiveTheme(); renderSkuTable(); renderAssets(); renderPreview();
  });

  document.getElementById('fName').addEventListener('input', renderPreview);
  document.getElementById('fDesc').addEventListener('input', renderPreview);

  document.getElementById('fillNameBtn').addEventListener('click',()=>{
    document.getElementById('fName').value = NAME_TPL[getThemeId()]||'';
    renderPreview();
  });
  document.getElementById('fillDescBtn').addEventListener('click',()=>{
    document.getElementById('fDesc').value = DESC[getThemeId()]||'';
    renderPreview();
  });

  document.getElementById('saveBtn').addEventListener('click',  ()=>saveListing(false));
  document.getElementById('reloadBtn').addEventListener('click', loadAll);
  document.getElementById('genMockBtn').addEventListener('click', ()=>generateAll('mock'));
  document.getElementById('genLiveBtn').addEventListener('click', ()=>generateAll('live'));
  document.getElementById('exportBtn').addEventListener('click',  exportXLSX);
  document.getElementById('xlsxDownloadBtn').addEventListener('click', downloadXLSX);
  document.getElementById('downloadImagesBtn').addEventListener('click', downloadImagesZip);
  checkExistingXLSX();
}

async function switchListing(id) {
  commitActiveItemFromForm();
  listing.active_listing_id = id;
  await saveFullConfig(true);
  renderListingTabs();
  populateForm();
  renderAssets();
  renderPreview();
  renderUrlInputs();
}

async function addListing() {
  commitActiveItemFromForm();
  const themeId = getThemeId();
  const id = uniqueItemId();
  const skuPrefix = uniqueSkuPrefix(themeId);
  listing.listings.push({
    id,
    theme_id: themeId,
    sku_prefix: skuPrefix,
    listing: {
      category:'Home Decor/Posters & Prints/Prints',
      brand:'No brand',
      product_name: NAME_TPL[themeId] || '',
      product_description: DESC[themeId] || '',
      images:{},
      variation_1_name:'Type', variation_2_name:'Size',
      delivery:'Default', warehouse_quantity_1:100, warehouse_quantity_2:0, status:'Draft(2)',
      attributes:{...(activeListingData().attributes||{}), style:'Minimalist', occasion:'Gift'},
    },
    skus: buildSkus(themeId, skuPrefix),
  });
  listing.active_listing_id = id;
  await saveFullConfig(true);
  renderListingTabs();
  populateForm();
  renderAssets();
  renderPreview();
  renderUrlInputs();
}

async function duplicateListing() {
  commitActiveItemFromForm();
  const source = activeItem();
  const copy = JSON.parse(JSON.stringify(source));
  copy.id = uniqueItemId();
  copy.sku_prefix = uniqueSkuPrefix(copy.theme_id || getThemeId());
  copy.listing.product_name = `${copy.listing.product_name || 'Untitled Listing'} Copy`;
  const types = [...new Set((copy.skus||[]).map(sku=>sku.type))];
  const sizes = [...new Set((copy.skus||[]).map(sku=>sku.size))];
  copy.skus = buildSkus(copy.theme_id || getThemeId(), copy.sku_prefix, types.length?types:undefined, sizes.length?sizes:undefined, copy.skus);
  listing.listings.push(copy);
  listing.active_listing_id = copy.id;
  await saveFullConfig(true);
  renderListingTabs();
  populateForm();
  renderAssets();
  renderPreview();
  renderUrlInputs();
}

async function deleteListing() {
  await deleteListingById(listing.active_listing_id);
}

async function deleteListingById(id) {
  if (listing.listings.length <= 1) return;
  listing.listings = listing.listings.filter(item=>item.id!==id);
  if (listing.active_listing_id === id) {
    listing.active_listing_id = listing.listings[0].id;
  }
  await saveFullConfig(true);
  renderListingTabs();
  populateForm();
  renderAssets();
  renderPreview();
  renderUrlInputs();
}

// ─── asset cards ──────────────────────────────────────────────────────────────
function getThemeAssets() {
  const tid = getThemeId();
  return imgState.themes?.find(t=>t.id===tid)?.assets || [];
}

function renderAssets() {
  const container = document.getElementById('assetCards');
  container.innerHTML = '';
  const tid    = getThemeId();
  const assets = getThemeAssets();
  const urls   = activeListingData().images || {};

  if (!assets.length) {
    container.innerHTML = `<div style="color:var(--muted);font-size:12px;padding:20px;text-align:center;border:1px dashed var(--line);border-radius:8px">
      No prompts configured for <strong>${tid}</strong>.<br>
      Add this theme to <code>data/image_workflows.json</code> to enable generation.
    </div>`;
    return;
  }

  ['main_image','image_2','image_3','image_4','image_5','image_6'].forEach(slot => {
    const meta = SLOT_META[slot];
    const info = assets.find(a=>a.slot===slot);
    if (!meta || !info) return;

    const genUrl  = info.image_url;
    const listUrl = urls[slot]||'';
    const dispUrl = genUrl || listUrl;
    const hasImg  = Boolean(dispUrl);

    const badge = hasImg
      ? '<span class="badge ok">✓ Present</span>'
      : `<span class="badge ${meta.required?'miss':'opt'}">${meta.required?'Required':'Optional'}</span>`;

    const thumb = hasImg
      ? `<img src="${dispUrl}?v=${Date.now()}" alt="${slot}"/>`
      : `<div class="ni">No<br>image</div>`;

    const promptSafe = (info.prompt||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    const downloadBtn = genUrl
      ? `<button class="sm" onclick='downloadImage(${JSON.stringify(genUrl)}, ${JSON.stringify(info.filename)})'>Download</button>`
      : '<button class="sm" disabled>Download</button>';

    const card = document.createElement('div');
    card.className = 'ac' + (meta.required?' req':'');
    card.innerHTML = `
      <div class="ac-head">
        <div><div class="ac-slot">${meta.label}</div><div class="ac-sub">${slot}</div></div>
        ${badge}
      </div>
      <div class="ac-body">
        <div class="ac-thumb">${thumb}</div>
        <div class="ac-ctrl">
          <div class="prompt-label">
            <span>Prompt</span>
            <button class="sm" onclick="savePrompt('${tid}','${slot}')">Save Prompt</button>
          </div>
          <textarea class="ac-prompt" id="prompt_${slot}" rows="4">${promptSafe}</textarea>
          <div class="url-row">
            <input type="url" id="url_${slot}" placeholder="Or paste image URL…" value="${listUrl}"/>
            <button class="sm" onclick="applyUrl('${slot}')">Apply URL</button>
          </div>
          <div class="gen-row">
            <button class="sm" onclick="genSlot('${tid}','mock','${slot}')">Mock</button>
            <button class="sm" onclick="genSlot('${tid}','dry-run','${slot}')">Dry Run</button>
            <button class="sm primary" onclick="genSlot('${tid}','live','${slot}')">Generate</button>
            ${downloadBtn}
          </div>
        </div>
      </div>`;
    container.appendChild(card);
  });
}

// ─── gallery of ALL generated images ─────────────────────────────────────────
function renderGallery() {
  const el = document.getElementById('gallery');
  el.innerHTML = '';
  const allAssets = (imgState.themes||[]).flatMap(t =>
    t.assets.filter(a=>a.image_url).map(a=>({...a, theme_id:t.id}))
  );
  if (!allAssets.length) {
    el.innerHTML = '<div style="font-size:11px;color:var(--muted)">No images generated yet.</div>';
    return;
  }
  allAssets.forEach(a => {
    const item = document.createElement('div');
    item.className = 'gallery-item';
    item.title = `${a.theme_id} · ${a.slot}`;
    item.onclick = () => window.open(a.image_url,'_blank');
    item.innerHTML = `<img src="${a.image_url}?v=${Date.now()}" alt="${a.slot}"/>
      <button class="gallery-download" title="Download" onclick='event.stopPropagation(); downloadImage(${JSON.stringify(a.image_url)}, ${JSON.stringify(a.filename)})'>↓</button>
      <div class="gallery-label">${a.theme_id.replace('pets_','')}</div>`;
    el.appendChild(item);
  });
}

// ─── save prompt ──────────────────────────────────────────────────────────────
async function savePrompt(themeId, slot) {
  const prompt = document.getElementById(`prompt_${slot}`)?.value?.trim();
  if (!prompt) return;
  const con = document.getElementById('console');
  try {
    const res = await fetch('/api/prompt', {
      method:'PUT',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({theme_id:themeId, slot, prompt}),
    });
    const d = await res.json();
    con.textContent = d.ok ? `✓ Prompt saved — ${themeId}:${slot}` : '✗ '+d.error;
  } catch(e){ con.textContent='✗ '+e; }
}

// ─── apply URL ────────────────────────────────────────────────────────────────
async function applyUrl(slot, inputId) {
  const id  = inputId || `url_${slot}`;
  const url = document.getElementById(id)?.value?.trim();
  if (!url) return;
  const item = activeItem();
  if (!item.listing) item.listing = {};
  if (!item.listing.images) item.listing.images = {};
  item.listing.images[slot] = url;
  // sync the other input field
  const other = id.startsWith('pvurl') ? `url_${slot}` : `pvurl_${slot}`;
  const otherEl = document.getElementById(other);
  if (otherEl) otherEl.value = url;
  await saveListing(true);
  renderAssets(); renderUrlInputs(); renderPreview();
}

// ─── generation ───────────────────────────────────────────────────────────────
async function genSlot(theme, mode, slot) {
  const promptOverride = document.getElementById(`prompt_${slot}`)?.value?.trim() || null;
  await runGeneration(theme, mode, slot, promptOverride);
}
async function generateAll(mode) {
  await runGeneration(getThemeId(), mode, null, null);
}

async function runGeneration(theme, mode, slot, promptOverride) {
  const con      = document.getElementById('console');
  const provider = document.getElementById('providerSel').value;
  lockBtns(true);
  con.textContent = `Running ${mode} [${provider}] → ${theme}${slot?':'+slot:''}…`;
  try {
    const res = await fetch('/api/generate', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({theme, mode, slot, overwrite:true, provider,
                            prompt_override: promptOverride}),
    });
    const d = await res.json();
    con.textContent = [d.stdout,d.stderr].filter(Boolean).join('\n') || JSON.stringify(d,null,2);
    await loadAll();
  } catch(e){ con.textContent = String(e); }
  finally { lockBtns(false); }
}

function lockBtns(on) {
  document.querySelectorAll('button').forEach(b=>b.disabled=on);
}

// ─── save listing ─────────────────────────────────────────────────────────────
function collectActiveItem() {
  const themeId = getThemeId();
  const sizes = getSizes(), types = getTypes();
  const item = activeItem();
  const skuPrefix = item.sku_prefix || uniqueSkuPrefix(themeId, item.id);
  const priceRows = buildSkus(themeId, skuPrefix, types, sizes, item.skus);
  const skus = priceRows.map(sku => ({
    ...sku,
    price: parseFloat(
      document.querySelector(`.priceinput[data-type="${sku.type}"][data-size="${sku.size}"]`)?.value || sku.price || 0
    ),
  }));

  return {
    ...item,
    theme_id: themeId,
    sku_prefix: skuPrefix,
    listing: {
      category:            activeListingData().category||'Home Decor/Posters & Prints/Prints',
      brand:               activeListingData().brand   ||'No brand',
      product_name:        document.getElementById('fName').value,
      product_description: document.getElementById('fDesc').value,
      images:              activeListingData().images  ||{},
      variation_1_name:'Type', variation_2_name:'Size',
      delivery:'Default', warehouse_quantity_1:100, warehouse_quantity_2:0, status:'Draft(2)',
      attributes:{
        ...(activeListingData().attributes||{}),
        style:    document.getElementById('fAesthetic').value,
        occasion: document.getElementById('fPurpose').value,
      },
    },
    skus,
  };
}

function commitActiveItemFromForm() {
  const item = collectActiveItem();
  const index = listing.listings.findIndex(entry=>entry.id===item.id);
  if (index >= 0) listing.listings[index] = item;
}

function collectConfig() {
  commitActiveItemFromForm();
  return {
    template_path: listing.template_path || 'input_template.xlsx',
    output_path:   listing.output_path   || 'outputs/inkerastory_tiktok_bulk_upload.xlsx',
    active_listing_id: listing.active_listing_id,
    listings: listing.listings,
  };
}

async function saveFullConfig(silent=false) {
  const data = normalizeListingConfig(listing);
  try {
    const res = await fetch('/api/listing',{
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data),
    });
    const r = await res.json();
    listing = normalizeListingConfig(data);
    if (!silent) {
      const el = document.getElementById('saveStatus');
      el.style.color = r.ok?'var(--ok)':'var(--danger)';
      el.textContent = r.ok?'✓ Saved':'✗ '+(r.error||'Failed');
      setTimeout(()=>{el.textContent='';},3000);
    }
    renderListingTabs();
    renderPreview();
    return Boolean(r.ok);
  } catch(e){ if(!silent) document.getElementById('saveStatus').textContent='✗ '+e; return false; }
}

async function saveListing(silent=false) {
  const data = collectConfig();
  try {
    const res = await fetch('/api/listing',{
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data),
    });
    const r = await res.json();
    listing = normalizeListingConfig(data);
    if (!silent) {
      const el = document.getElementById('saveStatus');
      el.style.color = r.ok?'var(--ok)':'var(--danger)';
      el.textContent = r.ok?'✓ Saved':'✗ '+(r.error||'Failed');
      setTimeout(()=>{el.textContent='';},3000);
    }
    renderListingTabs();
    renderPreview();
    return Boolean(r.ok);
  } catch(e){ if(!silent) document.getElementById('saveStatus').textContent='✗ '+e; return false; }
}

// ─── export ───────────────────────────────────────────────────────────────────
async function exportXLSX() {
  const st   = document.getElementById('expStatus');
  const info = document.getElementById('xlsxInfo');
  const selectedIds = getSelectedListingIds();
  if (!selectedIds.length) { st.style.color='var(--danger)'; st.textContent='✗ No listings selected'; return; }
  lockBtns(true);
  st.style.color = 'var(--muted)'; st.textContent = 'Saving…';
  try {
    const saved = await saveListing(true);
    if (!saved) { st.style.color='var(--danger)'; st.textContent='✗ Save failed'; return; }
    const n = selectedIds.length;
    st.textContent = `Building XLSX for ${n} listing${n===1?'':'s'}…`;
    const res = await fetch('/api/export', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({listing_ids: selectedIds}),
    });
    const d = await res.json().catch(()=>({}));
    if (d.ok) {
      st.style.color = 'var(--ok)';
      st.textContent = `✓ Built — ${d.rows} SKU rows`;
      info.textContent = `${d.path}  ·  ${new Date().toLocaleTimeString()}`;
      document.getElementById('xlsxDownloadBtn').disabled = false;
    } else {
      st.style.color = 'var(--danger)';
      st.textContent = '✗ ' + (d.error || 'Build failed');
    }
  } catch(e){ st.style.color='var(--danger)'; st.textContent='✗ '+String(e); }
  finally { lockBtns(false); }
}

async function downloadXLSX() {
  const st = document.getElementById('expStatus');
  st.style.color='var(--muted)'; st.textContent='Downloading…';
  try {
    const res = await fetch('/api/export');
    if (res.ok && res.headers.get('Content-Type')?.includes('spreadsheet')) {
      const blob = await res.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href = url; a.download = 'inkerastory_tiktok_bulk_upload.xlsx'; a.click();
      URL.revokeObjectURL(url);
      st.style.color='var(--ok)'; st.textContent='✓ File saved';
    } else {
      const e = await res.json().catch(()=>({}));
      st.style.color='var(--danger)'; st.textContent='✗ '+(e.error||'Download failed');
    }
  } catch(e){ st.style.color='var(--danger)'; st.textContent='✗ '+String(e); }
}

async function downloadImagesZip() {
  const st = document.getElementById('expStatus');
  const theme = getThemeId();
  lockBtns(true); st.textContent='Preparing image ZIP…';
  try {
    const res = await fetch(`/api/images.zip?theme=${encodeURIComponent(theme)}`);
    if (res.ok && res.headers.get('Content-Type')?.includes('zip')) {
      const blob = await res.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href=url; a.download=`inkerastory_${theme}_images.zip`; a.click();
      URL.revokeObjectURL(url);
      st.textContent='✓ Downloaded images';
    } else {
      const e = await res.json().catch(()=>({}));
      st.textContent='✗ '+(e.error||'No generated images found');
    }
  } catch(e){ st.textContent='✗ '+String(e); }
  finally { lockBtns(false); }
}

async function downloadImage(imageUrl, filename) {
  const con = document.getElementById('console');
  const safeName = filename || imageUrl.split('/').pop() || 'listing-image.png';
  try {
    const res = await fetch(imageUrl);
    if (!res.ok) throw new Error(`Download failed (${res.status})`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = safeName;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    con.textContent = `✓ Downloaded ${safeName}`;
  } catch(e) {
    con.textContent = `✗ ${String(e)}`;
    window.open(imageUrl, '_blank');
  }
}

// ─── preview ──────────────────────────────────────────────────────────────────
function renderPreview() {
  document.getElementById('pvName').textContent = document.getElementById('fName').value||'Product Name';
  document.getElementById('pvDesc').textContent = document.getElementById('fDesc').value||'Description will appear here.';

  const prices=[];
  document.querySelectorAll('.priceinput').forEach(el=>{const v=parseFloat(el.value);if(!isNaN(v))prices.push(v);});
  if (prices.length){
    const lo=Math.min(...prices).toFixed(2),hi=Math.max(...prices).toFixed(2);
    document.getElementById('pvPrice').textContent=lo===hi?`$${lo}`:`$${lo} – $${hi}`;
  }

  const assets   = getThemeAssets();
  const listedU  = activeListingData().images||{};
  cImages = ['main_image','image_2','image_3','image_4','image_5']
    .map(s=>assets.find(a=>a.slot===s)?.image_url||listedU[s])
    .filter(Boolean);
  cIdx = Math.min(cIdx, Math.max(0,cImages.length-1));
  updateCarousel();
}

function updateCarousel() {
  const img=document.getElementById('cImg');
  const ph=document.getElementById('noImgPh');
  const dots=document.getElementById('cDots');
  const prev=document.getElementById('cPrev');
  const next=document.getElementById('cNext');

  if (!cImages.length){
    img.style.display='none'; ph.style.display='flex';
    dots.innerHTML=''; prev.style.display=next.style.display='none'; return;
  }
  img.src=cImages[cIdx]+'?v='+Date.now();
  img.style.display='block'; ph.style.display='none';
  const multi=cImages.length>1;
  prev.style.display=next.style.display=multi?'flex':'none';
  dots.innerHTML='';
  cImages.forEach((_,i)=>{
    const d=document.createElement('div');
    d.className='cdot'+(i===cIdx?' active':'');
    d.onclick=()=>{cIdx=i;updateCarousel();};
    dots.appendChild(d);
  });
}
function shiftC(dir){ cIdx=(cIdx+dir+cImages.length)%cImages.length; updateCarousel(); }

// ─── url inputs in preview panel ─────────────────────────────────────────────
function renderUrlInputs() {
  const el   = document.getElementById('urlInputs');
  const urls = activeListingData().images||{};
  const labels={main_image:'Closeup',image_2:'Scene',image_3:'Mood',image_4:'Room',image_5:'Sizes'};
  el.innerHTML='';
  ['main_image','image_2','image_3','image_4','image_5'].forEach(slot=>{
    const row=document.createElement('div');
    row.style.cssText='display:flex;gap:5px;margin-bottom:5px;align-items:center';
    row.innerHTML=`
      <span style="font-size:11px;color:var(--muted);width:60px;flex-shrink:0">${labels[slot]}</span>
      <input type="url" id="pvurl_${slot}" style="flex:1;font-size:11px"
             placeholder="https://cdn.example.com/…" value="${urls[slot]||''}"/>
      <button class="sm" onclick="applyUrl('${slot}','pvurl_${slot}')">Set</button>`;
    el.appendChild(row);
  });
}

async function checkExistingXLSX() {
  // HEAD the export endpoint to see if a file already exists
  try {
    const res = await fetch('/api/export', {method:'HEAD'});
    if (res.ok) {
      document.getElementById('xlsxDownloadBtn').disabled = false;
      document.getElementById('xlsxInfo').textContent =
        'outputs/inkerastory_tiktok_bulk_upload.xlsx  ·  previously built';
    }
  } catch(_){}
}

init();
</script>
</body>
</html>
"""


# ── HTTP handler ──────────────────────────────────────────────────────────────

class StudioHandler(BaseHTTPRequestHandler):
    def do_HEAD(self) -> None:
        p = urllib.parse.urlparse(self.path).path
        if p == "/":
            body = INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
        elif p == "/api/export":
            out = ROOT / "outputs" / "inkerastory_tiktok_bulk_upload.xlsx"
            code = 200 if out.exists() else 404
            self.send_response(code); self.end_headers()
        else:
            self.send_response(404); self.end_headers()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        p = parsed.path

        if p == "/":
            body = INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if p == "/api/state":
            json_response(self, 200, build_state()); return

        if p == "/api/listing":
            try:   json_response(self, 200, load_listing_config())
            except Exception as e: json_response(self, 500, {"error": str(e)})
            return

        if p == "/api/images.zip":
            params = urllib.parse.parse_qs(parsed.query)
            theme_id = params.get("theme", ["pets"])[0]
            try:
                filename, body, count = build_images_zip(theme_id)
            except FileNotFoundError as e:
                json_response(self, 404, {"ok": False, "error": str(e)}); return
            except Exception as e:
                json_response(self, 400, {"ok": False, "error": str(e)}); return
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Image-Count", str(count))
            self.end_headers()
            self.wfile.write(body)
            return

        if p == "/api/export":
            # Download whatever was last built
            out = ROOT / "outputs" / "inkerastory_tiktok_bulk_upload.xlsx"
            if not out.exists():
                json_response(self, 404, {"error": "No XLSX built yet — click Build first."}); return
            body = out.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            self.send_header("Content-Disposition",
                'attachment; filename="inkerastory_tiktok_bulk_upload.xlsx"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if p.startswith("/files/"):
            self._serve_file(p.removeprefix("/files/")); return

        json_response(self, 404, {"error": "Not found"})

    def do_POST(self) -> None:
        p       = urllib.parse.urlparse(self.path).path
        payload = self._read_json()

        if p == "/api/generate":
            try:
                result = run_generation(
                    theme           = payload.get("theme", "pets"),
                    mode            = payload.get("mode", "dry-run"),
                    slot            = payload.get("slot"),
                    limit           = payload.get("limit"),
                    overwrite       = bool(payload.get("overwrite", True)),
                    provider        = payload.get("provider", "openai"),
                    prompt_override = payload.get("prompt_override"),
                )
            except Exception as e:
                json_response(self, 400, {"ok": False, "error": str(e)}); return
            json_response(self, 200 if result["ok"] else 500, result)
            return

        if p == "/api/listing":
            try:
                save_listing_config(payload)
                json_response(self, 200, {"ok": True})
            except Exception as e:
                json_response(self, 500, {"ok": False, "error": str(e)})
            return

        if p == "/api/export":
            ids = payload.get("listing_ids")  # list[str] | None
            result = run_export(listing_ids=ids)
            json_response(self, 200 if result["ok"] else 500, result); return

        json_response(self, 404, {"error": "Not found"})

    def do_PUT(self) -> None:
        p       = urllib.parse.urlparse(self.path).path
        payload = self._read_json()

        if p == "/api/prompt":
            try:
                update_prompt(
                    theme_id   = payload.get("theme_id", ""),
                    slot       = payload.get("slot", ""),
                    new_prompt = payload.get("prompt", ""),
                )
                json_response(self, 200, {"ok": True})
            except Exception as e:
                json_response(self, 500, {"ok": False, "error": str(e)})
            return

        json_response(self, 404, {"error": "Not found"})

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw    = self.rfile.read(length)
        return json.loads(raw.decode("utf-8") or "{}") if raw else {}

    def _serve_file(self, encoded_rel: str) -> None:
        rel  = urllib.parse.unquote(encoded_rel)
        path = (ROOT / rel).resolve()
        allowed = (ROOT / "outputs").resolve()
        if not path.is_file() or allowed not in path.parents:
            json_response(self, 404, {"error": "File not found"}); return
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {fmt % args}")


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="INKERASTORY Listing Studio.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    load_env_file()
    server = ThreadingHTTPServer((args.host, args.port), StudioHandler)
    print(f"Listing Studio → http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
