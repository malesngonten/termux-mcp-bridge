"""CLI: termux-mcp serve | ui | token | tunnel setup | doctor"""
import argparse
import getpass
import os
import shutil
import subprocess
import sys
from . import __version__, config
from . import state
from . import tunnel as tn


def _copy_clipboard(text: str) -> bool:
    exe = shutil.which("termux-clipboard-set")  # dari paket Termux:API
    if not exe:
        return False
    try:
        subprocess.run([exe], input=text, text=True, timeout=5, check=True)
        return True
    except Exception:
        return False


def _announce(url: str, show_token: bool, stable: bool, provider: str = "ngrok"):
    full = url.rstrip("/") + "/mcp"
    copied = _copy_clipboard(full)
    print("\n" + "=" * 54)
    print("Tunnel aktif. Isi konektor kustom di Claude:")
    print(f"  URL    : {full}" + ("   (sudah disalin)" if copied else ""))
    print("  Header : x-api-key")
    if show_token:
        print(f"  Nilai  : {config.load_token()}")
    else:
        print("  Nilai  : token lu. Tampilkan dengan: termux-mcp token")
    if provider == "cloudflare":
        print("  Catatan: URL Cloudflare berubah tiap start; edit konektor kalau server dinyalakan ulang.")
        print("           Untuk URL tetap: pakai ngrok (termux-mcp tunnel setup).")
    elif not stable:
        print("  Catatan: URL ini acak dan berubah tiap start.")
        print("           Untuk URL tetap: termux-mcp tunnel setup --domain <domain-ngrok-lu>")
    print("=" * 54 + "\n", flush=True)


def cmd_serve(a):
    import uvicorn
    from .server import build_app

    if hasattr(os, "geteuid") and os.geteuid() == 0:
        print("PERINGATAN: berjalan sebagai root. Pemegang token punya akses penuh ke sistem ini.", file=sys.stderr)
    if a.host not in ("127.0.0.1", "localhost", "::1"):
        print("PERINGATAN: host bukan loopback. Server bisa dijangkau dari jaringan lokal tanpa tunnel.", file=sys.stderr)

    tunnel = None
    if a.tunnel == "ngrok":
        if not tn.find_ngrok():
            print("ngrok tidak ditemukan. Pasang dulu: https://ngrok.com/download lalu jalankan: termux-mcp tunnel setup", file=sys.stderr)
            sys.exit(1)
        if not tn.ngrok_has_authtoken():
            print("Authtoken ngrok belum diatur. Jalankan: termux-mcp tunnel setup", file=sys.stderr)
            sys.exit(1)
    elif a.tunnel == "cloudflare":
        if not tn.find_cloudflared():
            print("cloudflared tidak ditemukan. Di Termux: pkg install cloudflared", file=sys.stderr)
            sys.exit(1)

    app, _, plugins = build_app()
    print(f"termux-mcp {__version__} -> http://{a.host}:{a.port}/mcp")
    print(f"workspace: {config.WORKSPACE}")
    if plugins:
        print("plugin: " + ", ".join(plugins))

    state.write(pid=os.getpid(), port=a.port, tunnel=a.tunnel or None, url=None)
    if a.tunnel:
        domain = None
        if a.tunnel == "ngrok":
            domain = tn.normalize_domain(a.tunnel_domain or os.environ.get("TERMUX_MCP_NGROK_DOMAIN")
                                         or tn.load_settings().get("domain"))

        def on_url(u):
            state.update(url=u)
            _announce(u, a.show_token, bool(domain), a.tunnel)

        tunnel = tn.make_tunnel(a.tunnel, a.port, domain, on_url=on_url)
        tunnel.start()
        print(f"menyalakan tunnel {a.tunnel}..." + (f" (domain tetap: {domain})" if domain else ""))
    try:
        uvicorn.run(app, host=a.host, port=a.port)
    finally:
        if tunnel:
            tunnel.stop()
        state.clear()


def cmd_ui(a):
    from . import webui
    webui.run(port=a.port, mcp_port=a.mcp_port, open_browser=not a.no_open)


def cmd_token(a):
    token = config.new_token() if a.new else config.load_token()
    print(token)
    print("Simpan rahasia. Pakai sebagai nilai header x-api-key di konektor Claude.", file=sys.stderr)


def cmd_tunnel_setup(a):
    binary = tn.find_ngrok()
    if not binary:
        print("ngrok tidak ditemukan. Pasang dulu dari https://ngrok.com/download lalu ulangi perintah ini.", file=sys.stderr)
        sys.exit(1)
    interactive = sys.stdin.isatty()

    token = a.authtoken
    if not token and not tn.ngrok_has_authtoken() and interactive:
        print("Ambil authtoken di https://dashboard.ngrok.com/get-started/your-authtoken")
        token = getpass.getpass("Authtoken ngrok (input disembunyikan): ").strip()
    if token:
        # Catatan: argumen ini sempat terlihat di daftar proses selama sepersekian detik.
        r = subprocess.run([binary, "config", "add-authtoken", token])
        if r.returncode != 0:
            print("Gagal menyimpan authtoken.", file=sys.stderr)
            sys.exit(1)
    elif tn.ngrok_has_authtoken():
        print("Authtoken ngrok sudah terpasang, dilewati.")
    else:
        print("Authtoken belum diatur (jalankan ulang di terminal interaktif atau pakai --authtoken).", file=sys.stderr)
        sys.exit(1)

    domain = tn.normalize_domain(a.domain)
    if domain is None and interactive:
        domain = tn.normalize_domain(input(
            "Domain statis ngrok (opsional, contoh nama-lu.ngrok-free.dev; kosong = acak tiap start): "))
    if domain:
        s = tn.load_settings()
        s["domain"] = domain
        tn.save_settings(s)
        print(f"Domain tetap disimpan: {domain}")
    print("Siap. Jalankan: termux-mcp serve --tunnel ngrok")


def cmd_doctor(a):
    ok = True

    def check(label, passed, hint=""):
        nonlocal ok
        ok = ok and passed
        print(f"[{'OK' if passed else '!!'}] {label}" + (f"  -> {hint}" if hint and not passed else ""))

    check("Python >= 3.10", sys.version_info >= (3, 10), f"versi sekarang {sys.version.split()[0]}")
    try:
        import mcp  # noqa: F401
        check("paket mcp terpasang", True)
    except ImportError:
        check("paket mcp terpasang", False, "pip install 'mcp>=1.30,<2'")
    print(f"[{'OK' if config.WORKSPACE.is_dir() else '--'}] workspace: {config.WORKSPACE}"
          + ("" if config.WORKSPACE.is_dir() else " (dibuat otomatis saat serve)"))
    if config.TOKEN_FILE.exists():
        mode = config.TOKEN_FILE.stat().st_mode & 0o777
        check("token ada & izin file 600", mode == 0o600, f"chmod 600 {config.TOKEN_FILE}")
    else:
        check("token ada", False, "jalankan: termux-mcp token")
    root = hasattr(os, "geteuid") and os.geteuid() == 0
    print(f"[{'..' if root else 'OK'}] {'berjalan sebagai root (risiko lebih tinggi)' if root else 'bukan root'}")
    for tool, why in (("ffmpeg", "video/audio"), ("node", "Remotion/HyperFrames"), ("git", "git")):
        found = shutil.which(tool)
        print(f"[{'OK' if found else '--'}] {tool} ({why})" + ("" if found else " tidak ditemukan (opsional)"))

    if tn.find_ngrok():
        has = tn.ngrok_has_authtoken()
        print(f"[{'OK' if has else '--'}] ngrok terpasang, authtoken {'ada' if has else 'belum diatur -> termux-mcp tunnel setup'}")
        dom = tn.load_settings().get("domain")
        print(f"[{'OK' if dom else '--'}] domain tetap: {dom or 'belum diatur (URL acak tiap start)'}")
    else:
        print("[--] ngrok tidak ditemukan (opsional, untuk serve --tunnel ngrok)")
    print(f"[{'OK' if tn.find_cloudflared() else '--'}] cloudflared "
          + ("terpasang (serve --tunnel cloudflare, tanpa akun)" if tn.find_cloudflared()
             else "tidak ditemukan (opsional, untuk serve --tunnel cloudflare)"))
    sys.exit(0 if ok else 1)


def main():
    p = argparse.ArgumentParser(prog="termux-mcp", description="Jembatan MCP: Claude <-> terminal di perangkat lu")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="jalankan server")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--tunnel", nargs="?", const="ngrok", choices=list(tn.PROVIDERS), default=os.environ.get("TERMUX_MCP_TUNNEL"),
                   help="nyalakan tunnel publik sekalian: ngrok (URL tetap, perlu akun) atau cloudflare (tanpa akun, URL berubah)")
    s.add_argument("--tunnel-domain", help="domain statis ngrok (menimpa pengaturan tersimpan)")
    s.add_argument("--show-token", action="store_true", help="cetak token bersama info konektor (default: disembunyikan)")
    s.set_defaults(fn=cmd_serve)

    u = sub.add_parser("ui", help="buka panel setup di browser (hanya bisa diakses dari perangkat ini)")
    u.add_argument("--port", type=int, default=8787, help="port panel (default 8787; harus beda dari port server MCP)")
    u.add_argument("--mcp-port", type=int, default=8000, help="port server MCP yang dikelola panel")
    u.add_argument("--no-open", action="store_true", help="jangan coba membuka browser otomatis")
    u.set_defaults(fn=cmd_ui)

    t = sub.add_parser("token", help="tampilkan token (dibuat otomatis kalau belum ada)")
    t.add_argument("--new", action="store_true", help="buat token baru (yang lama tidak berlaku)")
    t.set_defaults(fn=cmd_token)

    tu = sub.add_parser("tunnel", help="pengaturan tunnel")
    tsub = tu.add_subparsers(dest="tcmd", required=True)
    ts = tsub.add_parser("setup", help="atur authtoken ngrok dan domain tetap (opsional)")
    ts.add_argument("--authtoken", help="authtoken ngrok (kalau kosong akan ditanya, input disembunyikan)")
    ts.add_argument("--domain", help="domain statis ngrok, contoh nama-lu.ngrok-free.dev")
    ts.set_defaults(fn=cmd_tunnel_setup)

    d = sub.add_parser("doctor", help="cek kesiapan lingkungan")
    d.set_defaults(fn=cmd_doctor)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
