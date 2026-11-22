"""Konfigurasi dan lokasi file. Semua bisa diubah lewat environment variable."""
import os
import secrets
from pathlib import Path

APP = "termux-mcp"

CONFIG_DIR = Path(os.environ.get("TERMUX_MCP_HOME", Path.home() / ".config" / APP)).expanduser()
TOKEN_FILE = CONFIG_DIR / "token"
LOG_FILE = CONFIG_DIR / "audit.log"
PLUGIN_DIR = CONFIG_DIR / "plugins"

# Folder kerja: semua tool file hanya boleh menyentuh isi folder ini.
WORKSPACE = Path(os.environ.get("TERMUX_MCP_WORKSPACE", Path.home() / "workspace")).expanduser()
JOBDIR = WORKSPACE / ".jobs"

# Matikan tool tertentu, contoh: TERMUX_MCP_DISABLE=delete_path,http_fetch
DISABLED = {t.strip() for t in os.environ.get("TERMUX_MCP_DISABLE", "").split(",") if t.strip()}

SHELL = "/bin/bash" if os.path.exists("/bin/bash") else "/bin/sh"
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".jobs", "target", ".cache"}


def ensure_dirs():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(CONFIG_DIR, 0o700)
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    JOBDIR.mkdir(parents=True, exist_ok=True)


def new_token() -> str:
    ensure_dirs()
    token = secrets.token_urlsafe(32)
    TOKEN_FILE.write_text(token)
    os.chmod(TOKEN_FILE, 0o600)
    return token


def load_token() -> str:
    """Baca token; kalau belum ada, bikin yang baru (acak, 256-bit)."""
    if TOKEN_FILE.exists():
        t = TOKEN_FILE.read_text().strip()
        if t:
            return t
    return new_token()
