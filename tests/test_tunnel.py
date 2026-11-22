"""Tes logika tunnel memakai ngrok palsu (stub). Tidak menyentuh ngrok asli.

Jalankan: PYTHONPATH=src python -m unittest discover -s tests -v
"""
import json
import tempfile
import time
import unittest
from pathlib import Path

from termux_mcp import tunnel as tn

URL_LINE = json.dumps({"msg": "started tunnel", "url": "https://abc123.ngrok-free.dev", "lvl": "info"})


def make_stub(d: Path, body: str) -> str:
    p = d / "ngrok"
    p.write_text("#!/usr/bin/env bash\n" + body)
    p.chmod(0o755)
    return str(p)


def wait_for(cond, timeout=6.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


class ParsingTests(unittest.TestCase):
    def test_parse_url_json(self):
        self.assertEqual(tn.parse_url(URL_LINE), "https://abc123.ngrok-free.dev")

    def test_parse_url_ignores_other_lines(self):
        self.assertIsNone(tn.parse_url(json.dumps({"msg": "starting web service", "addr": "127.0.0.1:4040"})))
        self.assertIsNone(tn.parse_url("sampah bukan json"))
        self.assertIsNone(tn.parse_url(""))

    def test_parse_url_plain_text_fallback(self):
        self.assertEqual(tn.parse_url('lvl=info msg="started tunnel" url=https://x.ngrok.dev'), "https://x.ngrok.dev")

    def test_fatal_code(self):
        self.assertEqual(tn.fatal_code("... ERR_NGROK_108 ..."), "ERR_NGROK_108")
        self.assertIsNone(tn.fatal_code("... ERR_NGROK_9999 ..."))
        self.assertIsNone(tn.fatal_code("baris biasa"))

    def test_normalize_domain(self):
        self.assertEqual(tn.normalize_domain("https://a.ngrok-free.dev/"), "a.ngrok-free.dev")
        self.assertEqual(tn.normalize_domain("  a.ngrok-free.dev "), "a.ngrok-free.dev")
        self.assertIsNone(tn.normalize_domain(""))
        self.assertIsNone(tn.normalize_domain(None))


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_gets_url_calls_back_and_stops(self):
        stub = make_stub(self.dir, f"echo '{URL_LINE}'\nexec sleep 30\n")
        seen = []
        t = tn.NgrokTunnel(8123, on_url=seen.append, binary=stub)
        t.start()
        self.assertTrue(wait_for(lambda: t.url), "URL tidak terbaca")
        self.assertEqual(t.url, "https://abc123.ngrok-free.dev")
        self.assertEqual(seen, ["https://abc123.ngrok-free.dev"])
        t.stop()
        self.assertIsNotNone(t.proc.poll(), "proses ngrok masih hidup setelah stop()")

    def test_passes_port_log_flags_and_domain(self):
        stub = make_stub(self.dir, f"echo \"$@\" > '{self.dir}/argv.txt'\necho '{URL_LINE}'\nexec sleep 30\n")
        t = tn.NgrokTunnel(8123, domain="https://tetap.ngrok-free.dev/", binary=stub)
        t.start()
        self.assertTrue(wait_for(lambda: (self.dir / "argv.txt").exists() and t.url))
        argv = (self.dir / "argv.txt").read_text().strip()
        t.stop()
        self.assertIn("http 8123", argv)
        self.assertIn("--log stdout --log-format json", argv)
        self.assertIn("--url tetap.ngrok-free.dev", argv)

    def test_fatal_error_does_not_restart(self):
        stub = make_stub(self.dir, f"echo run >> '{self.dir}/runs.txt'\necho 'ERR_NGROK_108 batas sesi'\nexit 1\n")
        t = tn.NgrokTunnel(8123, binary=stub, backoff=lambda n: 0)
        t.start()
        t._thread.join(timeout=8)
        self.assertFalse(t._thread.is_alive())
        self.assertEqual(len((self.dir / "runs.txt").read_text().split()), 1)
        self.assertIn("ERR_NGROK_108", t.stopped_reason)

    def test_restarts_then_gives_up(self):
        stub = make_stub(self.dir, f"echo run >> '{self.dir}/runs.txt'\necho 'koneksi putus'\nexit 1\n")
        t = tn.NgrokTunnel(8123, binary=stub, max_restarts=2, backoff=lambda n: 0)
        t.start()
        t._thread.join(timeout=10)
        self.assertFalse(t._thread.is_alive())
        self.assertEqual(len((self.dir / "runs.txt").read_text().split()), 3)  # 1 awal + 2 percobaan ulang
        self.assertIn("menyerah", t.stopped_reason)

    def test_missing_binary_raises(self):
        t = tn.NgrokTunnel(8123, binary=None)
        t.binary = None
        with self.assertRaises(RuntimeError):
            t.start()


if __name__ == "__main__":
    unittest.main()
