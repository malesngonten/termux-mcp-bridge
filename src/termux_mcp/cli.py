"""CLI: termux-mcp serve | token | doctor"""
import argparse
import os
import shutil
import sys
from . import __version__, config


def cmd_serve(a):
    import uvicorn
    from .server import build_app

    if hasattr(os, "geteuid") and os.geteuid() == 0:
        print("PERINGATAN: berjalan sebagai root. Pemegang token punya akses penuh ke sistem ini.", file=sys.stderr)
    if a.host not in ("127.0.0.1", "localhost", "::1"):
        print("PERINGATAN: host bukan loopback. Server bisa dijangkau dari jaringan lokal tanpa tunnel.", file=sys.stderr)
    app, _, plugins = build_app()
    print(f"termux-mcp {__version__} -> http://{a.host}:{a.port}/mcp")
    print(f"workspace: {config.WORKSPACE}")
    if plugins:
        print("plugin: " + ", ".join(plugins))
    uvicorn.run(app, host=a.host, port=a.port)


def cmd_token(a):
    token = config.new_token() if a.new else config.load_token()
    print(token)
    print("Simpan rahasia. Pakai sebagai nilai header x-api-key di konektor Claude.", file=sys.stderr)


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
    print(f"[{'OK' if config.WORKSPACE.is_dir() else '--'}] workspace: {config.WORKSPACE}" + ("" if config.WORKSPACE.is_dir() else " (dibuat otomatis saat serve)"))
    if config.TOKEN_FILE.exists():
        mode = config.TOKEN_FILE.stat().st_mode & 0o777
        check("token ada & izin file 600", mode == 0o600, f"chmod 600 {config.TOKEN_FILE}")
    else:
        check("token ada", False, "jalankan: termux-mcp token")
    root = hasattr(os, "geteuid") and os.geteuid() == 0
    print(f"[{'..' if root else 'OK'}] {'berjalan sebagai root (risiko lebih tinggi)' if root else 'bukan root'}")
    for tool, why in (("ffmpeg", "video/audio"), ("node", "Remotion/HyperFrames"), ("git", "git"), ("ngrok", "tunnel")):
        print(f"[{'OK' if shutil.which(tool) else '--'}] {tool} ({why})" + ("" if shutil.which(tool) else " tidak ditemukan (opsional)"))
    sys.exit(0 if ok else 1)


def main():
    p = argparse.ArgumentParser(prog="termux-mcp", description="Jembatan MCP: Claude <-> terminal di perangkat lu")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="jalankan server")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(fn=cmd_serve)

    t = sub.add_parser("token", help="tampilkan token (dibuat otomatis kalau belum ada)")
    t.add_argument("--new", action="store_true", help="buat token baru (yang lama tidak berlaku)")
    t.set_defaults(fn=cmd_token)

    d = sub.add_parser("doctor", help="cek kesiapan lingkungan")
    d.set_defaults(fn=cmd_doctor)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
