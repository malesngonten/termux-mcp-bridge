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
_CF_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")

PROVIDERS = ("ngrok", "cloudflare")


def find_ngrok():
    return shutil.which("ngrok")


def find_cloudflared():
    return shutil.which("cloudflared")


def parse_cloudflare_url(line: str) -> str | None:
    """Ambil URL trycloudflare.com dari satu baris log cloudflared."""
    m = _CF_URL_RE.search(line or "")
    return m.group(0) if m else None


def ngrok_add_authtoken(token: str) -> tuple[bool, str]:
    """Simpan authtoken lewat `ngrok config add-authtoken`. Mengembalikan (berhasil, pesan)."""
    binary = find_ngrok()
    if not binary:
        return False, "ngrok belum terpasang"
    try:
        r = subprocess.run([binary, "config", "add-authtoken", token], capture_output=True, text=True, timeout=20,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"gagal menjalankan ngrok: {e}"
    if r.returncode != 0:
        return False, "authtoken ditolak atau gagal disimpan"
    return True, "ok"


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


def _ngrok_config_paths() -> list[Path]:
    paths = []
    binary = find_ngrok()
    if binary:
        try:
            out = subprocess.run([binary, "config", "check"], capture_output=True, text=True, timeout=10,
                                 stdin=subprocess.DEVNULL).stdout
            m = re.search(r"at (\S+)", out)
            if m:
                paths.append(Path(m.group(1)))
        except (OSError, subprocess.TimeoutExpired):
            pass
    paths += [Path.home() / ".config" / "ngrok" / "ngrok.yml", Path.home() / ".ngrok2" / "ngrok.yml"]
    return paths


def ngrok_saved_authtoken() -> str:
    """Authtoken yang tersimpan di config ngrok, atau string kosong. Hanya untuk ditampilkan ke pemilik perangkat."""
    for p in _ngrok_config_paths():
        try:
            m = re.search(r"^\s*authtoken\s*:\s*['\"]?([^\s'\"#]+)", p.read_text(), re.M)
        except OSError:
            continue
        if m:
            return m.group(1)
    return ""


def ngrok_has_authtoken() -> bool:
    """Cek apakah ada authtoken di config ngrok."""
    return bool(ngrok_saved_authtoken())


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
    NAME = "ngrok"

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
            raise RuntimeError(f"{self.NAME} tidak ditemukan. Pasang dulu.")
        self._thread = threading.Thread(target=self._run, name="ngrok-tunnel", daemon=True)
        self._thread.start()

    def _parse(self, line):
        return parse_url(line)

    def _fatal(self, line):
        return fatal_code(line)

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
                self.stopped_reason = f"gagal menjalankan {self.NAME}: {e}"
                print(f"[tunnel] {self.stopped_reason}", file=sys.stderr)
                return
            fatal = None
            for line in self.proc.stdout:
                recent.append(line.strip())
                url = self._parse(line)
                if url and url != self.url:
                    self.url = url
                    if self.on_url:
                        self.on_url(url)
                fatal = fatal or self._fatal(line)
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
                self.stopped_reason = f"{self.NAME} terus berhenti; menyerah. Log terakhir: " + (recent[-1] if recent else "-")
                print(f"[tunnel] {self.stopped_reason}", file=sys.stderr)
                return
            wait = self.backoff(fails)
            print(f"[tunnel] {self.NAME} berhenti (kode {self.proc.returncode}), mencoba lagi dalam {wait}s ({fails}/{self.max_restarts})",
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


class CloudflareTunnel(NgrokTunnel):
    """Cloudflare Quick Tunnel: tanpa akun, URL *.trycloudflare.com acak dan berubah tiap start."""
    NAME = "cloudflared"

    def __init__(self, port: int, domain: str | None = None, on_url=None, binary: str | None = None, **kw):
        super().__init__(port, None, on_url=on_url, binary=binary or find_cloudflared(), **kw)

    def _parse(self, line):
        return parse_cloudflare_url(line)

    def _fatal(self, line):
        return None

    def _cmd(self):
        return [self.binary, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{self.port}"]


def make_tunnel(provider: str, port: int, domain: str | None = None, on_url=None):
    if provider == "ngrok":
        return NgrokTunnel(port, domain, on_url=on_url)
    if provider == "cloudflare":
        return CloudflareTunnel(port, on_url=on_url)
    raise ValueError(f"penyedia tunnel tidak dikenal: {provider}")
