#!/usr/bin/env python3
"""
YTDownloader - Backend Flask server optimizado para la Nube (Render/Railway)
Procesamiento en caché temporal con auto-destrucción.
"""

import re
import sys
import threading
import time
import random
import uuid
import traceback
import tempfile
from pathlib import Path
from flask import Flask, request, jsonify, send_file

import yt_dlp
from yt_dlp.networking.impersonate import ImpersonateTarget

# ─────────────────────────────────────────────
# Rutas y Caché Temporal
# ─────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
static_dir = BASE_DIR / "static"

app = Flask(__name__, static_folder=str(static_dir))

# Usamos la carpeta temporal del sistema (ej. /tmp en Linux) para no ocupar almacenamiento persistente
CACHE_DIR = Path(tempfile.gettempdir()) / "yt_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

jobs: dict[str, dict] = {}

# ─────────────────────────────────────────────
# Limpiador Automático (Libera espacio de la nube)
# ─────────────────────────────────────────────
def cleanup_worker():
    """Revisa cada 3 minutos y elimina archivos creados hace más de 10 minutos"""
    while True:
        try:
            now = time.time()
            for f in CACHE_DIR.glob('*'):
                if f.is_file() and f.stat().st_mtime < (now - 600): # 600 seg = 10 minutos
                    try:
                        f.unlink()
                        print(f"[Caché] Archivo auto-eliminado para liberar espacio: {f.name}")
                    except:
                        pass
        except Exception as e:
            print(f"[Caché] Error en limpieza: {e}")
        time.sleep(180) # Espera 3 minutos

# ─────────────────────────────────────────────
# Configuración Anti-Ban (Proxy + Rotación)
# ─────────────────────────────────────────────
PROXY = "http://smart-dehavfs0n22y_area-US:owmC8IbJwqcend8a@proxy.smartproxy.net:3120"
_BROWSER_TARGETS = ["chrome-110", "chrome-116", "chrome-120", "chrome-131", "edge-101", "safari-15.5", "safari-17.0"]

# ─────────────────────────────────────────────
# Lógica yt-dlp
# ─────────────────────────────────────────────
TIKTOK_RE = re.compile(r"tiktok\.com|vm\.tiktok\.com|vt\.tiktok\.com", re.IGNORECASE)

def is_tiktok(url: str) -> bool:
    return bool(TIKTOK_RE.search(url))

def clean_url(url: str) -> str:
    if is_tiktok(url) and "?" in url:
        return url.split("?")[0]
    return url

def make_progress_hook(job_id: str):
    def hook(d):
        job = jobs.get(job_id)
        if not job: return
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            percent = int(downloaded / total * 100) if total else 0
            job.update(status="downloading", percent=percent, speed=d.get("_speed_str", "—"), eta=d.get("_eta_str", "—"))
        elif d["status"] == "finished":
            job.update(status="processing", percent=99, speed="—", eta="—")
        elif d["status"] == "error":
            job.update(status="error", error=str(d.get("error", "Unknown error")))
    return hook

def _base_opts(job_id: str) -> dict:
    return {
        "outtmpl": str(CACHE_DIR / "%(title)s.%(ext)s"), # Guardamos directo en el caché temporal
        "progress_hooks": [make_progress_hook(job_id)],
        "quiet": True, "no_warnings": True, "nocheckcertificate": True,
        "retries": 5, "fragment_retries": 5, "proxy": PROXY,
    }

def _opts_youtube(job_id: str, fmt: str, quality: str) -> dict:
    opts = _base_opts(job_id)
    if fmt == "mp3":
        opts.update({"format": "bestaudio/best", "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": quality}]})
    else:
        fmt_str = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" if quality == "best" else f"bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]/best[height<={quality}][ext=mp4]/best"
        opts.update({"format": fmt_str, "merge_output_format": "mp4"})
    return opts

def _opts_tiktok(job_id: str, fmt: str, quality: str, target: str) -> dict:
    opts = _base_opts(job_id)
    opts["impersonate"] = ImpersonateTarget.from_str(target)
    if fmt == "mp3":
        opts.update({"format": "bestaudio[format_note!*=watermark][format_id!*=download]/bestaudio/best", "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": quality}]})
    else:
        opts.update({"format": "bestvideo[format_id!*=download][format_note!*=watermark]+bestaudio[format_note!*=watermark]/best[format_id=play_addr_h264]/best[format_id=play_addr]/best", "merge_output_format": "mp4", "format_sort": ["res", "vcodec:h264", "acodec:aac"]})
    return opts

def get_ydl_opts(job_id: str, url: str, fmt: str, quality: str, target: str = "chrome-116") -> dict:
    return _opts_tiktok(job_id, fmt, quality, target) if is_tiktok(url) else _opts_youtube(job_id, fmt, quality)

def download_worker(job_id: str, url: str, fmt: str, quality: str):
    job = jobs[job_id]
    max_retries = 4
    last_error = None

    for attempt in range(max_retries):
        try:
            target = random.choice(_BROWSER_TARGETS)
            opts = get_ydl_opts(job_id, url, fmt, quality, target)
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get("title", "video")
                ext = "mp3" if fmt == "mp3" else "mp4"
                safe_title = ydl.prepare_filename(info)
                final_path = Path(safe_title).with_suffix(f".{ext}")
                
                if not final_path.exists():
                    candidates = sorted(CACHE_DIR.glob(f"*.{ext}"), key=lambda p: p.stat().st_mtime, reverse=True)
                    final_path = candidates[0] if candidates else final_path

            job.update(status="done", percent=100, filename=final_path.name, title=title)
            return

        except Exception as e:
            last_error = str(e).strip() or type(e).__name__
            if "403" in last_error or "404" in last_error or "Forbidden" in last_error:
                job.update(status="downloading", speed=f"Reintentando... ({attempt+1}/{max_retries})")
                time.sleep(random.uniform(1.5, 3.5))
                continue
            else:
                break 

    jobs[job_id].update(status="error", error=f"Fallo tras {max_retries} intentos. Detalle: {last_error}")

# ─────────────────────────────────────────────
# Rutas API
# ─────────────────────────────────────────────
@app.route("/")
def index():
    return app.send_static_file("index.html")

@app.route("/api/info", methods=["POST"])
def video_info():
    data = request.get_json(silent=True) or {}
    url = clean_url(data.get("url", "").strip())
    if not url: return jsonify(error="URL requerida"), 400

    for attempt in range(3):
        try:
            opts = {"quiet": True, "no_warnings": True, "skip_download": True, "nocheckcertificate": True, "proxy": PROXY}
            if is_tiktok(url): opts["impersonate"] = ImpersonateTarget.from_str(random.choice(_BROWSER_TARGETS))
            with yt_dlp.YoutubeDL(opts) as ydl: info = ydl.extract_info(url, download=False)
            
            formats = info.get("formats", [])
            if is_tiktok(url):
                clean = [f for f in formats if "watermark" not in (f.get("format_note") or "").lower() and "download" not in (f.get("format_id") or "").lower()]
                heights = sorted({f["height"] for f in clean if f.get("height") and f["height"] >= 240}, reverse=True)
            else:
                heights = sorted({f["height"] for f in formats if f.get("height") and f["height"] >= 360}, reverse=True)

            thumb = info.get("thumbnail")
            if not thumb and info.get("thumbnails"): thumb = info["thumbnails"][-1].get("url", "")

            return jsonify(
                title=info.get("title", "Sin título"), thumbnail=thumb or "",
                duration=info.get("duration_string") or str(info.get("duration", "?")),
                channel=info.get("uploader") or info.get("channel") or "—",
                heights=heights[:6], is_tiktok=is_tiktok(url),
            )
        except Exception as e:
            if "403" in str(e) or "404" in str(e): time.sleep(1.5); continue
            break
    return jsonify(error="No se pudo extraer información."), 400

@app.route("/api/download", methods=["POST"])
def start_download():
    data = request.get_json(silent=True) or {}
    url = clean_url(data.get("url", "").strip())
    fmt, quality = data.get("format", "mp4"), data.get("quality", "best")
    if not url: return jsonify(error="URL requerida"), 400

    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "queued", "percent": 0, "speed": "—", "eta": "—", "filename": None, "title": None, "error": None}
    threading.Thread(target=download_worker, args=(job_id, url, fmt, quality), daemon=True).start()
    return jsonify(job_id=job_id)

@app.route("/api/status/<job_id>")
def job_status(job_id: str):
    return jsonify(jobs.get(job_id)) if job_id in jobs else (jsonify(error="Job no encontrado"), 404)

@app.route("/api/file/<filename>")
def serve_file(filename: str):
    path = CACHE_DIR / filename
    if not path.exists():
        return jsonify(error="El archivo expiró de la memoria caché. Intenta descargarlo de nuevo."), 404
    return send_file(str(path), as_attachment=True, download_name=filename)


if __name__ == "__main__":
    # Arranca el limpiador de caché que mantendrá el almacenamiento vacío
    threading.Thread(target=cleanup_worker, daemon=True).start()
    # Ya no abrimos el navegador local, pues esto estará en la nube
    app.run(host="0.0.0.0", port=5055)