"""Panel setup lokal (web UI): buat token, pilih tunnel, nyalakan/matikan server, dan panduan konektor.

Keamanan:
- Hanya bind ke 127.0.0.1, di port terpisah dari server MCP (tunnel tidak pernah menunjuk ke port panel).
- Akses lewat link berisi kode acak yang dicetak di terminal; setelah itu sesi dipegang cookie
  HttpOnly + SameSite=Strict. Tanpa sesi, semua endpoint API menolak.
- Header Host dicek (anti DNS rebinding); POST wajib JSON + header X-Panel (anti CSRF lintas situs).
- Token tidak pernah ikut di status; hanya dikirim lewat /api/token saat diminta.
"""
import hmac
import http.cookies
import json
import os
import platform
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config, state
from . import tunnel as tn

PAGE_FILE = Path(__file__).with_name("ui.html")
COOKIE = "tmcp_session"
MAX_BODY = 4096
AUTHTOKEN_RE = re.compile(r"^[A-Za-z0-9_\-]{10,200}$")
DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9.\-]*[a-z0-9])?$")


class PanelError(Exception):
    pass


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def cloudflared_install_hint() -> str:
    if shutil.which("pkg"):
        return "pkg install cloudflared"
    arch = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "amd64", "armv7l": "arm", "armv8l": "arm"}.get(platform.machine())
    if not arch:
        return "https://github.com/cloudflare/cloudflared/releases"
    url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}"
    return f"mkdir -p ~/.local/bin && curl -L -o ~/.local/bin/cloudflared {url} && chmod +x ~/.local/bin/cloudflared"


class Panel:
    """Logika panel. Dipisah dari HTTP supaya mudah dites."""

    def __init__(self, mcp_port: int = 8000):
        self.mcp_port = mcp_port
        self.code = secrets.token_urlsafe(12)
        self.sessions: set[str] = set()
        self.child: subprocess.Popen | None = None
        self.log_path = config.CONFIG_DIR / "serve.log"
        self.token_stale = False
        self.lock = threading.RLock()
        self._tools_cache = (0.0, {})
        self._fails: list[float] = []

    # ---- sesi ----
    def locked_out(self) -> bool:
        now = time.time()
        self._fails = [t for t in self._fails if now - t < 60]
        return len(self._fails) >= 10

    def try_code(self, given: str) -> str | None:
        """Tukar kode dari link dengan id sesi baru. None kalau salah."""
        if self.locked_out():
            return None
        if not hmac.compare_digest(given.encode(), self.code.encode()):
            self._fails.append(time.time())
            return None
        sid = secrets.token_urlsafe(24)
        self.sessions.add(sid)
        return sid

    def valid_session(self, sid: str | None) -> bool:
        return bool(sid) and any(hmac.compare_digest(sid.encode(), s.encode()) for s in self.sessions)

    # ---- info ----
    def _tools(self) -> dict:
        ts, cached = self._tools_cache
        if cached and time.time() - ts < 5:
            return cached
        ngrok = bool(tn.find_ngrok())
        info = {
            "ngrok": {"installed": ngrok, "authtoken": ngrok and tn.ngrok_has_authtoken(),
                      "domain": tn.load_settings().get("domain")},
            "cloudflare": {"installed": bool(tn.find_cloudflared())},
            "install": {"cloudflare": cloudflared_install_hint(), "ngrok": "https://ngrok.com/download"},
        }
        self._tools_cache = (time.time(), info)
        return info

    def _log_tail(self, n: int = 12) -> str:
        try:
            lines = [l for l in self.log_path.read_text(errors="replace").splitlines() if l.strip()]
        except OSError:
            return ""
        return "\n".join(lines[-n:])

    def status(self) -> dict:
        with self.lock:
            if self.child:
                self.child.poll()  # panen proses yang sudah mati supaya tidak jadi zombie
            st = state.read()
            running = bool(st)
            provider = st.get("tunnel") if st else None
            url = st.get("url") if st else None
            starting = bool(running and provider and not url and time.time() - st.get("started", 0) < 90)
            out = {
                "running": running,
                "starting": starting,
                "provider": provider,
                "url": (url.rstrip("/") + "/mcp") if url else None,
                "port": st.get("port") if st else self.mcp_port,
                "port_busy": (not running) and port_open(self.mcp_port),
                "token_stale": self.token_stale and running,
                "log": self._log_tail(),
            }
            out.update(self._tools())
            return out

    # ---- aksi ----
    def start(self, provider: str):
        with self.lock:
            if provider not in ("none",) + tn.PROVIDERS:
                raise PanelError("penyedia tunnel tidak dikenal")
            if state.read():
                raise PanelError("server sudah berjalan")
            if port_open(self.mcp_port):
                raise PanelError(f"port {self.mcp_port} sedang dipakai proses lain (mungkin server termux-mcp yang "
                                 "dijalankan dari terminal). Matikan dulu proses itu.")
            tools = self._tools()
            if provider == "ngrok":
                if not tools["ngrok"]["installed"]:
                    raise PanelError("ngrok belum terpasang")
                if not tools["ngrok"]["authtoken"]:
                    raise PanelError("authtoken ngrok belum disimpan")
            if provider == "cloudflare" and not tools["cloudflare"]["installed"]:
                raise PanelError("cloudflared belum terpasang")

            config.ensure_dirs()
            cmd = [sys.executable, "-m", "termux_mcp.cli", "serve", "--port", str(self.mcp_port)]
            if provider != "none":
                cmd += ["--tunnel", provider]
            env = dict(os.environ, PYTHONUNBUFFERED="1")
            with open(self.log_path, "w") as log:
                self.child = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                              start_new_session=True, env=env)
            os.chmod(self.log_path, 0o600)
            self.token_stale = False
            for _ in range(80):  # tunggu sampai port melayani; gagal cepat harus terlihat sebagai error
                if self.child.poll() is not None or (state.read() and port_open(self.mcp_port)):
                    break
                time.sleep(0.1)
            if self.child.poll() is not None:
                raise PanelError("server gagal start. " + (self._log_tail(3) or "tidak ada log"))

    def stop(self):
        with self.lock:
            st = state.read()
            pid = st["pid"] if st else (self.child.pid if self.child and self.child.poll() is None else None)
            if not pid:
                return
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                return
            deadline = time.time() + 10
            while time.time() < deadline:
                if self.child and self.child.pid == pid:
                    self.child.poll()
                if not state.pid_alive(pid) or (self.child and self.child.pid == pid and self.child.returncode is not None):
                    return
                time.sleep(0.2)
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if self.child:
                self.child.poll()

    def get_token(self) -> str:
        return config.load_token()

    def new_token(self) -> str:
        with self.lock:
            token = config.new_token()
            if state.read():
                self.token_stale = True  # server yang jalan masih memegang token lama sampai dimulai ulang
            return token

    def save_ngrok(self, authtoken: str | None, domain: str | None):
        authtoken = (authtoken or "").strip()
        domain = tn.normalize_domain(domain)
        if authtoken and not AUTHTOKEN_RE.match(authtoken):
            raise PanelError("format authtoken tidak valid")
        if domain:
            domain = domain.lower()
            if not DOMAIN_RE.match(domain) or "." not in domain:
                raise PanelError("format domain tidak valid, contoh: nama-lu.ngrok-free.dev")
        if not authtoken and not domain:
            raise PanelError("isi authtoken atau domain dulu")
        if authtoken:
            ok, msg = tn.ngrok_add_authtoken(authtoken)
            if not ok:
                raise PanelError(msg)
        if domain:
            s = tn.load_settings()
            s["domain"] = domain
            tn.save_settings(s)
        self._tools_cache = (0.0, {})


def make_handler(panel: Panel, ui_port: int):
    allowed_hosts = {f"127.0.0.1:{ui_port}", f"localhost:{ui_port}"}

    class Handler(BaseHTTPRequestHandler):
        server_version = "termux-mcp-panel"

        def log_message(self, *args):
            pass

        # ---- util ----
        def _send(self, code, body: bytes, ctype="application/json; charset=utf-8", extra=None, nonce=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            if nonce:
                self.send_header("Content-Security-Policy",
                                 f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
                                 "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code, obj):
            self._send(code, json.dumps(obj).encode())

        def _session(self):
            raw = self.headers.get("Cookie", "")
            try:
                c = http.cookies.SimpleCookie(raw)
            except http.cookies.CookieError:
                return None
            return c[COOKIE].value if COOKIE in c else None

        def _guard(self, need_session=True) -> bool:
            if self.headers.get("Host", "") not in allowed_hosts:
                self._json(403, {"error": "host tidak diizinkan"})
                return False
            if need_session and not panel.valid_session(self._session()):
                self._json(401, {"error": "sesi tidak valid; buka ulang link dari terminal"})
                return False
            return True

        def _body(self) -> dict | None:
            if self.headers.get("X-Panel") != "1" or not (self.headers.get("Content-Type", "")).startswith("application/json"):
                self._json(403, {"error": "permintaan ditolak"})
                return None
            try:
                n = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                n = -1
            if n < 0 or n > MAX_BODY:
                self._json(413, {"error": "body terlalu besar"})
                return None
            try:
                data = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                self._json(400, {"error": "JSON tidak valid"})
                return None
            return data if isinstance(data, dict) else {}

        # ---- GET ----
        def do_GET(self):
            path, _, query = self.path.partition("?")
            if path == "/":
                if not self._guard(need_session=False):
                    return
                m = re.search(r"(?:^|&)k=([^&]+)", query)
                if m:
                    sid = panel.try_code(m.group(1))
                    if not sid:
                        code = 429 if panel.locked_out() else 403
                        return self._send(code, "Kode salah atau kedaluwarsa. Jalankan ulang: termux-mcp ui".encode(),
                                          "text/plain; charset=utf-8")
                    return self._send(302, b"", "text/plain", {
                        "Location": "/", "Set-Cookie": f"{COOKIE}={sid}; HttpOnly; SameSite=Strict; Path=/"})
                if not panel.valid_session(self._session()):
                    return self._send(403, "Buka panel lewat link yang dicetak di terminal (termux-mcp ui).".encode(),
                                      "text/plain; charset=utf-8")
                nonce = secrets.token_urlsafe(12)
                html = PAGE_FILE.read_text().replace("__NONCE__", nonce)
                return self._send(200, html.encode(), "text/html; charset=utf-8", nonce=nonce)
            if not self._guard():
                return
            if path == "/api/status":
                return self._json(200, panel.status())
            if path == "/api/token":
                return self._json(200, {"token": panel.get_token()})
            self._json(404, {"error": "tidak ditemukan"})

        # ---- POST ----
        def do_POST(self):
            if not self._guard():
                return
            body = self._body()
            if body is None:
                return
            try:
                if self.path == "/api/start":
                    panel.start(str(body.get("tunnel", "")))
                elif self.path == "/api/stop":
                    panel.stop()
                elif self.path == "/api/token/new":
                    panel.new_token()
                elif self.path == "/api/ngrok":
                    panel.save_ngrok(body.get("authtoken"), body.get("domain"))
                else:
                    return self._json(404, {"error": "tidak ditemukan"})
            except PanelError as e:
                return self._json(400, {"error": str(e)})
            self._json(200, panel.status())

    return Handler


def run(port: int = 8787, mcp_port: int = 8000):
    from .cli import _copy_clipboard

    if port == mcp_port:
        print("Port panel harus beda dari port server MCP.", file=sys.stderr)
        sys.exit(1)
    panel = Panel(mcp_port)
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(panel, port))
    except OSError as e:
        print(f"Port {port} tidak bisa dipakai ({e}). Coba: termux-mcp ui --port 8788", file=sys.stderr)
        sys.exit(1)
    httpd.daemon_threads = True
    link = f"http://127.0.0.1:{port}/?k={panel.code}"
    copied = _copy_clipboard(link)
    print("\n" + "=" * 54)
    print("Panel setup siap. Buka link ini di browser HP lu:")
    print(f"  {link}" + ("   (sudah disalin)" if copied else ""))
    print("Link berisi kode rahasia dan hanya berlaku selama panel ini jalan.")
    print("Tekan Ctrl+C untuk menutup panel. Server MCP yang sudah dinyalakan tetap jalan.")
    print("=" * 54 + "\n", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        print("Panel ditutup.")
