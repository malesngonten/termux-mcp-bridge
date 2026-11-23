"""Tes panel web UI: keamanan gerbang akses, logika Panel, dan start/stop end-to-end dengan cloudflared palsu.

Jalankan: PYTHONPATH=src python -m unittest discover -s tests -v
"""
import http.client
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from termux_mcp import config, state
from termux_mcp import tunnel as tn
from termux_mcp import webui


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(cond, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return False


class PanelBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / "cfg"
        self.bin = Path(self._tmp.name) / "bin"
        self.bin.mkdir()
        patches = [
            mock.patch.object(config, "CONFIG_DIR", self.home),
            mock.patch.object(config, "TOKEN_FILE", self.home / "token"),
            mock.patch.object(config, "WORKSPACE", Path(self._tmp.name) / "ws"),
            mock.patch.object(config, "JOBDIR", Path(self._tmp.name) / "ws" / ".jobs"),
            mock.patch.object(state, "STATE_FILE", self.home / "state.json"),
            mock.patch.object(tn, "TUNNEL_FILE", self.home / "tunnel.json"),
            # PATH hanya berisi folder stub, jadi ngrok/cloudflared asli tidak ikut terdeteksi
            mock.patch.dict(os.environ, {"PATH": f"{self.bin}:{os.environ.get('PATH', '')}".replace("/usr/local/bin", "/nonexistent"),
                                         "TERMUX_MCP_HOME": str(self.home),
                                         "TERMUX_MCP_WORKSPACE": str(Path(self._tmp.name) / "ws")}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def stub(self, name, body):
        p = self.bin / name
        p.write_text("#!/usr/bin/env bash\n" + body)
        p.chmod(0o755)


class HttpTests(PanelBase):
    def setUp(self):
        super().setUp()
        self.panel = webui.Panel(mcp_port=free_port())
        self.ui_port = free_port()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.ui_port), webui.make_handler(self.panel, self.ui_port))
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def req(self, method, path, body=None, headers=None, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.ui_port, timeout=5)
        h = {"Host": host or f"127.0.0.1:{self.ui_port}"}
        h.update(headers or {})
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r, data

    def login(self):
        r, _ = self.req("GET", f"/?k={self.panel.code}")
        self.assertEqual(r.status, 302)
        cookie = r.getheader("Set-Cookie").split(";")[0]
        return {"Cookie": cookie}

    def post(self, path, obj, cookie, extra=None):
        h = {"Content-Type": "application/json", "X-Panel": "1", **cookie, **(extra or {})}
        return self.req("POST", path, json.dumps(obj), h)

    def test_no_session_is_rejected(self):
        r, _ = self.req("GET", "/")
        self.assertEqual(r.status, 403)
        for path in ("/api/status", "/api/token"):
            r, _ = self.req("GET", path)
            self.assertEqual(r.status, 401)

    def test_wrong_code_rejected_and_lockout(self):
        for _ in range(9):
            r, _ = self.req("GET", "/?k=salah")
            self.assertEqual(r.status, 403)
        self.req("GET", "/?k=salah")  # percobaan ke-10 memicu kunci
        r, _ = self.req("GET", f"/?k={self.panel.code}")  # bahkan kode benar ditolak selama terkunci
        self.assertEqual(r.status, 429)

    def test_activity_notifications(self):
        events = []
        self.panel.notify = events.append
        self.req("GET", "/?k=salah")
        cookie = self.login()
        self.post("/api/stop", {}, cookie)
        self.post("/api/token/new", {}, cookie)
        self.post("/api/start", {"tunnel": "aneh"}, cookie)
        self.assertEqual(events[0], "!Percobaan masuk dengan kode salah")
        self.assertIn("Browser tersambung", events)
        self.assertIn("Server dimatikan", events)
        self.assertIn("Token baru dibuat", events)
        self.assertTrue(any(e.startswith("!") and "tidak dikenal" in e for e in events))
        self.assertFalse(any(self.panel.get_token() in e or self.panel.code in e for e in events))

    def test_host_header_checked(self):
        cookie = self.login()
        r, _ = self.req("GET", "/api/status", headers=cookie, host="evil.example.com")
        self.assertEqual(r.status, 403)
        r, _ = self.req("GET", "/api/status", headers=cookie, host=f"localhost:{self.ui_port}")
        self.assertEqual(r.status, 200)

    def test_login_cookie_flags_and_page(self):
        r, _ = self.req("GET", f"/?k={self.panel.code}")
        cookie = r.getheader("Set-Cookie")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        r, body = self.req("GET", "/", headers={"Cookie": cookie.split(";")[0]})
        self.assertEqual(r.status, 200)
        text = body.decode()
        self.assertNotIn("__NONCE__", text)
        csp = r.getheader("Content-Security-Policy")
        self.assertIn("frame-ancestors 'none'", csp)
        nonce = csp.split("script-src 'nonce-")[1].split("'")[0]
        self.assertIn(f'nonce="{nonce}"', text)

    def test_page_has_no_borders_or_inline_styles(self):
        html = webui.PAGE_FILE.read_text()
        self.assertNotRegex(html, r"\bborder(?!-radius)(-[a-z-]+)?\s*:\s*(?!0\b|none)")
        self.assertNotIn("outline:", html.replace("outline:none", ""))
        self.assertNotIn('style="', html)

    def test_status_never_contains_token(self):
        cookie = self.login()
        token = self.panel.get_token()
        r, body = self.req("GET", "/api/status", headers=cookie)
        self.assertEqual(r.status, 200)
        self.assertNotIn(token, body.decode())
        r, body = self.req("GET", "/api/token", headers=cookie)
        self.assertEqual(json.loads(body)["token"], token)

    def test_post_requires_json_and_custom_header(self):
        cookie = self.login()
        r, _ = self.req("POST", "/api/stop", "{}", {"Content-Type": "text/plain", **cookie})
        self.assertEqual(r.status, 403)
        r, _ = self.req("POST", "/api/stop", "{}", {"Content-Type": "application/json", **cookie})
        self.assertEqual(r.status, 403)
        r, _ = self.post("/api/stop", {}, cookie)
        self.assertEqual(r.status, 200)

    def test_new_token_changes_token(self):
        cookie = self.login()
        old = self.panel.get_token()
        r, _ = self.post("/api/token/new", {}, cookie)
        self.assertEqual(r.status, 200)
        self.assertNotEqual(self.panel.get_token(), old)

    def test_ngrok_save_validation(self):
        cookie = self.login()
        r, body = self.post("/api/ngrok", {"domain": "bukan domain!"}, cookie)
        self.assertEqual(r.status, 400)
        r, body = self.post("/api/ngrok", {}, cookie)
        self.assertEqual(r.status, 400)
        r, body = self.post("/api/ngrok", {"authtoken": "pendek"}, cookie)
        self.assertEqual(r.status, 400)

    def test_ngrok_save_domain_and_authtoken(self):
        self.stub("ngrok", 'echo "$@" >> "$(dirname "$0")/ngrok.calls"\nexit 0\n')
        cookie = self.login()
        r, _ = self.post("/api/ngrok", {"authtoken": "2abcDEF_ghi-JKL0123456789", "domain": "https://Nama-Gue.ngrok-free.dev/"}, cookie)
        self.assertEqual(r.status, 200)
        self.assertEqual(tn.load_settings()["domain"], "nama-gue.ngrok-free.dev")
        self.assertIn("config add-authtoken 2abcDEF_ghi-JKL0123456789", (self.bin / "ngrok.calls").read_text())

    def test_start_validation_errors(self):
        cookie = self.login()
        r, body = self.post("/api/start", {"tunnel": "ngrok"}, cookie)
        self.assertEqual(r.status, 400)
        self.assertIn("ngrok", json.loads(body)["error"])
        r, body = self.post("/api/start", {"tunnel": "cloudflare"}, cookie)
        self.assertEqual(r.status, 400)
        self.assertIn("cloudflared", json.loads(body)["error"])
        r, body = self.post("/api/start", {"tunnel": "aneh"}, cookie)
        self.assertEqual(r.status, 400)

    def test_port_busy_blocks_start(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", self.panel.mcp_port))
            s.listen(1)
            self.assertTrue(self.panel.status()["port_busy"])
            with self.assertRaises(webui.PanelError):
                self.panel.start("none")


class StateTests(PanelBase):
    def test_stale_state_is_ignored_and_cleared(self):
        state.write(pid=999999, port=8000, tunnel=None, url=None)
        self.assertIsNone(state.read())
        self.assertFalse(state.STATE_FILE.exists())

    def test_live_state_is_read(self):
        state.write(pid=os.getpid(), port=8000, tunnel="cloudflare", url="https://a.trycloudflare.com")
        self.assertEqual(state.read()["url"], "https://a.trycloudflare.com")
        state.update(url="https://b.trycloudflare.com")
        self.assertEqual(state.read()["url"], "https://b.trycloudflare.com")
        state.clear()
        self.assertIsNone(state.read())


class CloudflareParseTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(tn.parse_cloudflare_url("2026 INF |  https://quiet-river-1234.trycloudflare.com  |"),
                         "https://quiet-river-1234.trycloudflare.com")
        self.assertIsNone(tn.parse_cloudflare_url("INF Requesting new quick Tunnel on trycloudflare.com..."))
        self.assertIsNone(tn.parse_cloudflare_url(""))

    def test_make_tunnel(self):
        self.assertIsInstance(tn.make_tunnel("ngrok", 8000), tn.NgrokTunnel)
        self.assertIsInstance(tn.make_tunnel("cloudflare", 8000), tn.CloudflareTunnel)
        with self.assertRaises(ValueError):
            tn.make_tunnel("lain", 8000)


class EndToEndTests(PanelBase):
    """Menjalankan `termux-mcp serve` sungguhan sebagai proses anak, dengan cloudflared palsu."""

    def test_start_status_stop_with_cloudflare_stub(self):
        self.stub("cloudflared",
                  'echo "INF |  https://stub-demo-1234.trycloudflare.com  |" >&2\nexec sleep 300\n')
        panel = webui.Panel(mcp_port=free_port())
        self.addCleanup(panel.stop)
        self.assertTrue(panel.status()["cloudflare"]["installed"])

        panel.start("cloudflare")
        self.assertTrue(wait_for(lambda: panel.status()["url"]), panel.status()["log"])
        st = panel.status()
        self.assertTrue(st["running"])
        self.assertEqual(st["provider"], "cloudflare")
        self.assertEqual(st["url"], "https://stub-demo-1234.trycloudflare.com/mcp")
        self.assertTrue(wait_for(lambda: webui.port_open(panel.mcp_port)))

        with self.assertRaises(webui.PanelError):  # tidak boleh start dua kali
            panel.start("cloudflare")

        panel.new_token()
        self.assertTrue(panel.status()["token_stale"])

        panel.stop()
        self.assertTrue(wait_for(lambda: not panel.status()["running"]))
        self.assertTrue(wait_for(lambda: not webui.port_open(panel.mcp_port)))
        self.assertFalse(panel.status()["token_stale"])

    def test_start_local_only(self):
        panel = webui.Panel(mcp_port=free_port())
        self.addCleanup(panel.stop)
        panel.start("none")
        self.assertTrue(wait_for(lambda: panel.status()["running"]))
        self.assertIsNone(panel.status()["url"])
        panel.stop()
        self.assertTrue(wait_for(lambda: not panel.status()["running"]))


class TerminalUiTests(PanelBase):
    LINK = "http://127.0.0.1:8787/?k=abc123"

    def test_plain_banner_has_no_escape_codes(self):
        text = webui.render_banner(webui.Style(False), self.LINK, 8787, opened=False, copied=False, width=45)
        self.assertNotIn("\033", text)
        self.assertIn(self.LINK, text)
        self.assertLessEqual(max(len(l) for l in text.splitlines()), 45)

    def test_color_banner_has_green_link_and_osc8(self):
        text = webui.render_banner(webui.Style(True), self.LINK, 8787, opened=True, copied=False, width=45)
        self.assertIn("\033[4;92m" + self.LINK, text)
        self.assertIn("\033]8;;" + self.LINK, text)
        self.assertIn("Dibuka otomatis", text)

    def test_banner_never_contains_box_borders(self):
        text = webui.render_banner(webui.Style(False), self.LINK, 8787, opened=False, copied=True, width=45)
        self.assertNotRegex(text, r"[=─━│┃┌┐└┘╭╮╰╯]{3,}")

    def test_no_color_env_disables_color(self):
        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}):
            self.assertFalse(webui.supports_color())

    def test_open_in_browser_uses_termux_open_url(self):
        out = Path(self._tmp.name) / "opened.txt"
        self.stub("termux-open-url", f'echo "$1" > {out}\n')
        self.assertTrue(webui.open_in_browser(self.LINK))
        self.assertEqual(out.read_text().strip(), self.LINK)

    def test_open_in_browser_failure_returns_false(self):
        self.stub("termux-open-url", "exit 1\n")
        with mock.patch("termux_mcp.webui.os.access", side_effect=lambda p, m: str(p).startswith(str(self.bin))):
            self.assertFalse(webui.open_in_browser(self.LINK))


class StubMcp:
    """Server MCP palsu: membalas 200 hanya kalau header x-api-key sesuai token."""

    def __init__(self, token: str):
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length", "0"))
                outer.last_body = json.loads(self.rfile.read(n) or b"{}")
                ok = self.path == "/mcp" and self.headers.get("x-api-key") == token
                self.send_response(200 if ok else 401)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

        self.last_body = None
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class ConnectionTests(PanelBase):
    def setUp(self):
        super().setUp()
        self.panel = webui.Panel(mcp_port=free_port())
        self.stub = StubMcp(self.panel.get_token())
        self.addCleanup(self.stub.close)

    def test_probe_ok_and_handshake_shape(self):
        r = webui.Panel._probe(f"http://127.0.0.1:{self.stub.port}/mcp", self.panel.get_token(), 3)
        self.assertTrue(r["ok"])
        self.assertEqual(self.stub.last_body["method"], "initialize")
        self.assertNotIn(self.panel.get_token(), json.dumps(r))

    def test_probe_wrong_token_explains(self):
        r = webui.Panel._probe(f"http://127.0.0.1:{self.stub.port}/mcp", "salah", 3)
        self.assertFalse(r["ok"])
        self.assertEqual(r["status"], 401)
        self.assertIn("token", r["detail"])

    def test_probe_connection_refused(self):
        r = webui.Panel._probe(f"http://127.0.0.1:{free_port()}/mcp", "x", 3)
        self.assertFalse(r["ok"])
        self.assertIn("tidak bisa terhubung", r["detail"])

    def test_test_connection_requires_running_server(self):
        with self.assertRaises(webui.PanelError):
            self.panel.test_connection()

    def test_test_connection_ok_local_and_public(self):
        state.write(pid=os.getpid(), port=self.stub.port, tunnel="cloudflare", url=f"http://127.0.0.1:{self.stub.port}")
        res = self.panel.test_connection()
        self.assertTrue(res["ok"], res)
        self.assertTrue(res["local"]["ok"] and res["public"]["ok"])
        self.assertIn("aman", res["message"])

    def test_test_connection_without_tunnel(self):
        state.write(pid=os.getpid(), port=self.stub.port, tunnel=None, url=None)
        res = self.panel.test_connection()
        self.assertFalse(res["ok"])
        self.assertTrue(res["public"]["skipped"])
        self.assertIn("tunnel", res["message"])

    def test_test_connection_public_down(self):
        state.write(pid=os.getpid(), port=self.stub.port, tunnel="ngrok", url=f"http://127.0.0.1:{free_port()}")
        res = self.panel.test_connection()
        self.assertFalse(res["ok"])
        self.assertTrue(res["local"]["ok"])
        self.assertIn("jalur publik gagal", res["message"])


class PageTests(unittest.TestCase):
    html = webui.PAGE_FILE.read_text()

    def script(self):
        return re.search(r"<script[^>]*>(.*?)</script>", self.html, re.S).group(1)

    def test_every_id_used_by_script_exists(self):
        ids = set(re.findall(r'\bid="([^"]+)"', self.html))
        used = set(re.findall(r"\$\$?\('#([A-Za-z0-9_-]+)", self.script()))
        dynamic = {"power", "tester"}  # dibuat oleh JS (powerHTML)
        self.assertEqual(used - ids - dynamic, set())

    def test_every_icon_reference_exists(self):
        ids = set(re.findall(r'\bid="(i-[a-z]+)"', self.html))
        used = set(re.findall(r'#(i-[a-z]+)', self.html)) | {f"i-{n}" for n in ("key", "route", "plug", "power", "pulse", "check", "x")}
        self.assertEqual(used - ids, set())

    def test_globe_data_present(self):
        for pid in ("land-path", "grat-path"):
            d = re.search(r'id="%s"[^>]*?\sd="([^"]*)"' % pid, self.html).group(1)
            self.assertGreater(len(d), 1000, pid)

    def test_script_is_valid_javascript(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node tidak ada")
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "ui.js"
            f.write_text(self.script())
            r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True, stdin=subprocess.DEVNULL)
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_build_runs_before_handlers_that_need_dynamic_buttons(self):
        js = self.script()
        self.assertLess(js.index("build();"), js.index("$('#power').onclick"))

    def test_ui_smoke_with_jsdom(self):
        node = shutil.which("node")
        jsdom = os.environ.get("JSDOM_PATH")
        if not node or not jsdom:
            self.skipTest("butuh node dan JSDOM_PATH (npm i jsdom)")
        smoke = Path(__file__).resolve().parent.parent / "tools" / "ui_smoke.js"
        r = subprocess.run([node, str(smoke)], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=90)
        self.assertEqual(r.returncode, 0, r.stdout[-1500:] + r.stderr[-500:])

    def test_no_external_resources(self):
        self.assertNotRegex(self.html, r'(src|href)="https?://')
        self.assertNotIn("@import", self.html)


if __name__ == "__main__":
    unittest.main()
