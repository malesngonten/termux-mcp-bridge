"""Status server yang sedang berjalan (state.json). Ditulis oleh `serve`, dibaca oleh web UI dan CLI."""
import json
import os
import time
from . import config

STATE_FILE = config.CONFIG_DIR / "state.json"


def pid_alive(pid) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read() -> dict | None:
    """Status server yang masih hidup; file basi (proses sudah mati) diabaikan dan dibersihkan."""
    try:
        data = json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not pid_alive(data.get("pid")):
        try:
            STATE_FILE.unlink()
        except OSError:
            pass
        return None
    return data


def write(**data):
    config.ensure_dirs()
    data.setdefault("started", int(time.time()))
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    os.chmod(tmp, 0o600)
    os.replace(tmp, STATE_FILE)


def update(**fields):
    cur = read()
    if cur and cur.get("pid") == os.getpid():
        cur.update(fields)
        write(**cur)


def clear():
    """Hapus status hanya kalau milik proses ini."""
    try:
        cur = json.loads(STATE_FILE.read_text())
        if cur.get("pid") == os.getpid():
            STATE_FILE.unlink()
    except (OSError, ValueError):
        pass
