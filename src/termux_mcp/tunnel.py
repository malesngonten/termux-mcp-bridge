"""Tunnel otomatis: jalankan ngrok sebagai proses anak, baca URL publiknya, nyalakan ulang kalau putus.

Pengaturan (domain statis) disimpan di tunnel.json. Authtoken ngrok disimpan oleh ngrok sendiri
lewat `ngrok config add-authtoken`; termux-mcp tidak menyimpan atau mencatat authtoken.
"""
import collections
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from . import config

TUNNEL_FILE = config.CONFIG_DIR / "tunnel.json"

# Kode error ngrok yang percuma di-retry: berhenti dan tampilkan petunjuk.
FATAL_HINTS = {
    "ERR_NGROK_105": "authtoken tidak valid. Jalankan: termux-mcp tunnel setup",
    "ERR_NGROK_107": "authtoken tidak valid. Jalankan: termux-mcp tunnel setup",
    "ERR_NGROK_4018": "belum ada authtoken ngrok. Jalankan: termux-mcp tunnel setup",
    "ERR_NGROK_108": "akun ngrok dibatasi jumlah sesi agent. Matikan ngrok lain yang sedang jalan.",
    "ERR_NGROK_334": "domain itu sedang dipakai tunnel lain yang masih online. Matikan yang lama dulu.",
}
_ERR_RE = re.compile(r"ERR_NGROK_\d+")
_URL_RE = re.compile(r"url=(https://\S+)")


def find_ngrok():
    return shutil.which("ngrok")


def load_settings() -> dict:
    try:
        return json.loads(TUNNEL_FILE.read_text())
    except (OSError, ValueError):
        return {}


def save_settings(data: dict):
    config.ensure_dirs()
    TUNNEL_FILE.write_text(json.dumps(data, indent=2))
    os.chmod(TUNNEL_FILE, 0o600)


def normalize_domain(domain: str | None) -> str | None:
    if not domain:
        return None
    d = domain.strip().removeprefix("https://").removeprefix("http://").strip("/")
    return d or None


def ngrok_has_authtoken() -> bool:
    """Cek apakah ada baris authtoken di config ngrok (isinya tidak dibaca keluar)."""
    binary = find_ngrok()
    paths = []
    if binary:
        try:
            out = subprocess.run([binary, "config", "check"], capture_output=True, text=True, timeout=10).stdout
            m = re.search(r"at (\S+)", out)
            if m:
                paths.append(Path(m.group(1)))
        except (OSError, subprocess.TimeoutExpired):
            pass
    paths += [Path.home() / ".config" / "ngrok" / "ngrok.yml", Path.home() / ".ngrok2" / "ngrok.yml"]
    for p in paths:
        try:
            if re.search(r"^\s*authtoken\s*:", p.read_text(), re.M):
                return True
        except OSError:
            continue
    return False


def parse_url(line: str) -> str | None:
    """Ambil URL publik dari satu baris log ngrok (format json, dengan cadangan teks biasa)."""
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
        if isinstance(obj, dict) and obj.get("msg") == "started tunnel" and str(obj.get("url", "")).startswith("https://"):
            return obj["url"]
        return None
    except ValueError:
        pass
    m = _URL_RE.search(line)
    return m.group(1) if m and "started tunnel" in line else None


def fatal_code(line: str) -> str | None:
    for code in _ERR_RE.findall(line):
        if code in FATAL_HINTS:
            return code
    return None


class NgrokTunnel:
    def __init__(self, port: int, domain: str | None = None, on_url=None, binary: str | None = None,
                 max_restarts: int = 5, backoff=lambda n: min(2 ** n, 30)):
        self.port = port
        self.domain = normalize_domain(domain)
        self.on_url = on_url
        self.binary = binary or find_ngrok()
        self.max_restarts = max_restarts
        self.backoff = backoff
        self.url = None
        self.proc = None
        self.stopped_reason = None
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if not self.binary:
            raise RuntimeError("ngrok tidak ditemukan. Pasang dulu: https://ngrok.com/download")
        self._thread = threading.Thread(target=self._run, name="ngrok-tunnel", daemon=True)
        self._thread.start()

    def _cmd(self):
        cmd = [self.binary, "http", str(self.port), "--log", "stdout", "--log-format", "json"]
        if self.domain:
            cmd += ["--url", self.domain]
        return cmd

    def _run(self):
        fails = 0
        while not self._stop.is_set():
            started = time.time()
            recent = collections.deque(maxlen=5)
            try:
                self.proc = subprocess.Popen(self._cmd(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, text=True, errors="replace", start_new_session=True)
            except OSError as e:
                self.stopped_reason = f"gagal menjalankan ngrok: {e}"
                print(f"[tunnel] {self.stopped_reason}", file=sys.stderr)
                return
            fatal = None
            for line in self.proc.stdout:
                recent.append(line.strip())
                url = parse_url(line)
                if url and url != self.url:
                    self.url = url
                    if self.on_url:
                        self.on_url(url)
                fatal = fatal or fatal_code(line)
            self.proc.wait()
            self.proc.stdout.close()
            self.url = None
            if self._stop.is_set():
                return
            if fatal:
                self.stopped_reason = f"{fatal}: {FATAL_HINTS[fatal]}"
                print(f"[tunnel] berhenti. {self.stopped_reason}", file=sys.stderr)
                return
            if time.time() - started > 60:
                fails = 0
            fails += 1
            if fails > self.max_restarts:
                self.stopped_reason = "ngrok terus berhenti; menyerah. Log terakhir: " + (recent[-1] if recent else "-")
                print(f"[tunnel] {self.stopped_reason}", file=sys.stderr)
                return
            wait = self.backoff(fails)
            print(f"[tunnel] ngrok berhenti (kode {self.proc.returncode}), mencoba lagi dalam {wait}s ({fails}/{self.max_restarts})",
                  file=sys.stderr)
            if self._stop.wait(wait):
                return

    def stop(self):
        self._stop.set()
        p = self.proc
        if p and p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGTERM)
                p.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        if self._thread:
            self._thread.join(timeout=3)
