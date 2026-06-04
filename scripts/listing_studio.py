#!/usr/bin/env python3
"""Local visual control panel for the TikTok listing image workflow."""

from __future__ import annotations

import json
import mimetypes
import os
import subprocess
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "image_workflows.json"
OUTPUT_DIR = ROOT / "outputs" / "generated_images"
THEMES = {"pets", "world_cup"}
MODES = {"dry-run", "mock", "live"}


def load_env_file(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
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
    rel = path.relative_to(ROOT).as_posix()
    return "/files/" + urllib.parse.quote(rel)


def asset_path(theme_id: str, filename: str) -> Path:
    return OUTPUT_DIR / theme_id / Path(filename).name


def read_generation_manifest() -> dict[str, Any] | None:
    path = OUTPUT_DIR / "generation_manifest.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def build_state() -> dict[str, Any]:
    load_env_file()
    config = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    manifest = read_generation_manifest()
    themes = []
    total = 0
    present = 0
    for theme in config["themes"]:
        assets = []
        for asset in theme["assets"]:
            total += 1
            path = asset_path(theme["id"], asset["filename"])
            exists = path.exists()
            present += int(exists)
            assets.append(
                {
                    "slot": asset["slot"],
                    "kind": asset["kind"],
                    "filename": Path(asset["filename"]).name,
                    "hook": asset["hook"],
                    "prompt": asset["prompt"],
                    "exists": exists,
                    "image_url": file_url(path) if exists else None,
                    "path": str(path.relative_to(ROOT)),
                }
            )
        themes.append(
            {
                "id": theme["id"],
                "name": theme["display_name"],
                "positioning": theme["positioning"],
                "assets": assets,
            }
        )

    api_key = os.environ.get("OPENAI_API_KEY", "")
    return {
        "api_key_loaded": bool(api_key),
        "api_key_hint": f"...{api_key[-4:]}" if api_key else "",
        "generated_count": present,
        "asset_count": total,
        "themes": themes,
        "generation_manifest": manifest,
    }


def run_generation(theme: str, mode: str, slot: str | None, limit: int | None, overwrite: bool) -> dict[str, Any]:
    if theme not in THEMES:
        raise ValueError(f"Unsupported theme: {theme}")
    if mode not in MODES:
        raise ValueError(f"Unsupported mode: {mode}")

    command = [sys.executable, "scripts/image_generation_agent.py", "generate", "--theme", theme]
    if mode == "dry-run":
        command.append("--dry-run")
    elif mode == "mock":
        command.append("--mock")
    if slot:
        command.extend(["--slot", slot])
    if limit:
        command.extend(["--limit", str(limit)])
    if overwrite:
        command.append("--overwrite")

    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=600,
        check=False,
    )
    return {
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "ok": result.returncode == 0,
    }


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>INKERASTORY Listing Studio</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #171a1f;
      --muted: #667085;
      --line: #d8dde6;
      --accent: #1677ff;
      --ok: #11845b;
      --warn: #b54708;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
    }
    header {
      position: sticky;
      top: 0;
      z-index: 2;
      background: rgba(255,255,255,.94);
      border-bottom: 1px solid var(--line);
      backdrop-filter: blur(12px);
    }
    .bar {
      max-width: 1320px;
      margin: 0 auto;
      padding: 16px 20px;
      display: flex;
      gap: 16px;
      justify-content: space-between;
      align-items: center;
    }
    h1 { font-size: 20px; line-height: 1.2; margin: 0; }
    .subtitle { color: var(--muted); font-size: 13px; margin-top: 4px; }
    .status { display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }
    .pill {
      border: 1px solid var(--line);
      background: #fff;
      border-radius: 999px;
      padding: 7px 10px;
      font-size: 12px;
      color: var(--muted);
      white-space: nowrap;
    }
    .pill.ok { color: var(--ok); border-color: #a9dec8; background: #f0fbf6; }
    .pill.warn { color: var(--warn); border-color: #fed7aa; background: #fff7ed; }
    main {
      max-width: 1320px;
      margin: 0 auto;
      padding: 18px 20px 40px;
    }
    .toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 18px;
      align-items: center;
    }
    select, button {
      height: 36px;
      border-radius: 6px;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      padding: 0 10px;
      font: inherit;
      font-size: 13px;
    }
    button {
      cursor: pointer;
      font-weight: 600;
    }
    button.primary {
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
    }
    button:disabled { opacity: .55; cursor: wait; }
    .theme {
      margin-bottom: 28px;
    }
    .theme-head {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: end;
      margin: 10px 0 12px;
    }
    .theme h2 { margin: 0 0 4px; font-size: 18px; }
    .theme p { margin: 0; color: var(--muted); font-size: 13px; max-width: 840px; }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
      gap: 14px;
    }
    .card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      min-width: 0;
    }
    .preview {
      aspect-ratio: 1 / 1;
      background: #eef1f5;
      display: grid;
      place-items: center;
      border-bottom: 1px solid var(--line);
      overflow: hidden;
    }
    .preview img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
    .empty {
      color: var(--muted);
      text-align: center;
      padding: 24px;
      font-size: 13px;
    }
    .body { padding: 12px; }
    .meta {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 8px;
    }
    .slot { font-weight: 700; font-size: 13px; }
    .kind { color: var(--muted); font-size: 12px; }
    .hook { color: #303642; font-size: 13px; line-height: 1.35; min-height: 36px; }
    details {
      margin-top: 10px;
      border-top: 1px solid var(--line);
      padding-top: 10px;
    }
    summary {
      cursor: pointer;
      color: var(--accent);
      font-size: 13px;
      font-weight: 650;
    }
    pre {
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      color: #344054;
      background: #f8fafc;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      font-size: 12px;
      line-height: 1.45;
      max-height: 260px;
      overflow: auto;
    }
    .actions {
      display: flex;
      gap: 8px;
      margin-top: 10px;
    }
    .actions button { flex: 1; }
    .console {
      margin-top: 18px;
      background: #101828;
      color: #e4e7ec;
      border-radius: 8px;
      padding: 12px;
      font: 12px/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      min-height: 58px;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    @media (max-width: 720px) {
      .bar, .theme-head { align-items: flex-start; flex-direction: column; }
      .status { justify-content: flex-start; }
      main { padding-inline: 12px; }
    }
  </style>
</head>
<body>
  <header>
    <div class="bar">
      <div>
        <h1>INKERASTORY Listing Studio</h1>
        <div class="subtitle">Visual image workflow for TikTok Shop listing assets</div>
      </div>
      <div class="status" id="status"></div>
    </div>
  </header>
  <main>
    <div class="toolbar">
      <select id="themeSelect">
        <option value="all">All themes</option>
        <option value="pets">Pets</option>
        <option value="world_cup">World Cup</option>
      </select>
      <button id="refreshBtn">Refresh</button>
      <button id="dryRunBtn">Dry Run</button>
      <button id="mockBtn">Generate Mock</button>
      <button class="primary" id="liveBtn">Generate Live</button>
    </div>
    <div id="themes"></div>
    <div class="console" id="console">Ready.</div>
  </main>
  <script>
    const statusEl = document.getElementById('status');
    const themesEl = document.getElementById('themes');
    const consoleEl = document.getElementById('console');
    const themeSelect = document.getElementById('themeSelect');
    let state = null;

    function log(text) {
      consoleEl.textContent = text || 'Done.';
    }

    function selectedTheme() {
      return themeSelect.value;
    }

    function visibleThemes() {
      if (!state) return [];
      const selected = selectedTheme();
      return selected === 'all' ? state.themes : state.themes.filter(t => t.id === selected);
    }

    function renderStatus() {
      statusEl.innerHTML = '';
      const api = document.createElement('span');
      api.className = 'pill ' + (state.api_key_loaded ? 'ok' : 'warn');
      api.textContent = state.api_key_loaded ? `API key loaded ${state.api_key_hint}` : 'API key missing';
      statusEl.appendChild(api);
      const count = document.createElement('span');
      count.className = 'pill';
      count.textContent = `${state.generated_count}/${state.asset_count} images present`;
      statusEl.appendChild(count);
    }

    function card(asset, themeId) {
      const el = document.createElement('article');
      el.className = 'card';
      const preview = asset.exists
        ? `<img src="${asset.image_url}?v=${Date.now()}" alt="${asset.filename}">`
        : `<div class="empty">Missing image<br>${asset.filename}</div>`;
      el.innerHTML = `
        <div class="preview">${preview}</div>
        <div class="body">
          <div class="meta">
            <div>
              <div class="slot">${asset.slot}</div>
              <div class="kind">${asset.kind}</div>
            </div>
            <span class="pill ${asset.exists ? 'ok' : 'warn'}">${asset.exists ? 'present' : 'missing'}</span>
          </div>
          <div class="hook">${asset.hook}</div>
          <div class="actions">
            <button data-copy>Copy Prompt</button>
            <button data-mock>Mock</button>
          </div>
          <details>
            <summary>Prompt</summary>
            <pre>${asset.prompt.replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}</pre>
          </details>
        </div>
      `;
      el.querySelector('[data-copy]').addEventListener('click', async () => {
        await navigator.clipboard.writeText(asset.prompt);
        log(`Copied prompt for ${themeId}:${asset.slot}`);
      });
      el.querySelector('[data-mock]').addEventListener('click', () => runGeneration(themeId, 'mock', asset.slot));
      return el;
    }

    function renderThemes() {
      themesEl.innerHTML = '';
      for (const theme of visibleThemes()) {
        const section = document.createElement('section');
        section.className = 'theme';
        section.innerHTML = `
          <div class="theme-head">
            <div>
              <h2>${theme.name}</h2>
              <p>${theme.positioning}</p>
            </div>
          </div>
          <div class="grid"></div>
        `;
        const grid = section.querySelector('.grid');
        for (const asset of theme.assets) grid.appendChild(card(asset, theme.id));
        themesEl.appendChild(section);
      }
    }

    async function refresh() {
      const res = await fetch('/api/state');
      state = await res.json();
      renderStatus();
      renderThemes();
    }

    async function runGeneration(theme, mode, slot) {
      const buttons = document.querySelectorAll('button');
      buttons.forEach(b => b.disabled = true);
      log(`Running ${mode} for ${theme}${slot ? ':' + slot : ''}...`);
      try {
        const res = await fetch('/api/generate', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ theme, mode, slot, overwrite: true })
        });
        const payload = await res.json();
        log([payload.stdout, payload.stderr].filter(Boolean).join('\n') || JSON.stringify(payload, null, 2));
        await refresh();
      } catch (error) {
        log(String(error));
      } finally {
        buttons.forEach(b => b.disabled = false);
      }
    }

    document.getElementById('refreshBtn').addEventListener('click', refresh);
    document.getElementById('dryRunBtn').addEventListener('click', () => {
      const theme = selectedTheme() === 'all' ? 'pets' : selectedTheme();
      runGeneration(theme, 'dry-run');
    });
    document.getElementById('mockBtn').addEventListener('click', () => {
      const theme = selectedTheme() === 'all' ? 'pets' : selectedTheme();
      runGeneration(theme, 'mock');
    });
    document.getElementById('liveBtn').addEventListener('click', () => {
      const theme = selectedTheme() === 'all' ? 'pets' : selectedTheme();
      runGeneration(theme, 'live');
    });
    themeSelect.addEventListener('change', renderThemes);
    refresh();
  </script>
</body>
</html>
"""


class StudioHandler(BaseHTTPRequestHandler):
    def do_HEAD(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            body = INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return
        if parsed.path.startswith("/files/"):
            rel = urllib.parse.unquote(parsed.path.removeprefix("/files/"))
            path = (ROOT / rel).resolve()
            allowed = (ROOT / "outputs").resolve()
            if path.is_file() and allowed in path.parents:
                self.send_response(200)
                self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
                self.send_header("Content-Length", str(path.stat().st_size))
                self.end_headers()
                return
        self.send_response(404)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            body = INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/state":
            json_response(self, 200, build_state())
            return
        if parsed.path.startswith("/files/"):
            self.serve_file(parsed.path.removeprefix("/files/"))
            return
        json_response(self, 404, {"error": "Not found"})

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/api/generate":
            json_response(self, 404, {"error": "Not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        try:
            result = run_generation(
                theme=payload.get("theme", "pets"),
                mode=payload.get("mode", "dry-run"),
                slot=payload.get("slot"),
                limit=payload.get("limit"),
                overwrite=bool(payload.get("overwrite", True)),
            )
        except Exception as error:
            json_response(self, 400, {"ok": False, "error": str(error)})
            return
        json_response(self, 200 if result["ok"] else 500, result)

    def serve_file(self, encoded_rel_path: str) -> None:
        rel = urllib.parse.unquote(encoded_rel_path)
        path = (ROOT / rel).resolve()
        allowed = (ROOT / "outputs").resolve()
        if not path.is_file() or allowed not in path.parents:
            json_response(self, 404, {"error": "File not found"})
            return
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run the local INKERASTORY Listing Studio.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    load_env_file()
    server = ThreadingHTTPServer((args.host, args.port), StudioHandler)
    print(f"Listing Studio running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Listing Studio.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
