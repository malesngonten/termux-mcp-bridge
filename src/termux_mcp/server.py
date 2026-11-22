"""Perakit aplikasi: FastMCP + tool bawaan + plugin + middleware token."""
import importlib.util
import sys
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from . import config
from .auth import Auth
from .registry import make_tool_decorator


def load_plugins(mcp, tool):
    """Muat semua *.py di folder plugin. Plugin berjalan dengan hak penuh: pasang hanya yang lu percaya."""
    loaded = []
    if not config.PLUGIN_DIR.is_dir():
        return loaded
    for f in sorted(config.PLUGIN_DIR.glob("*.py")):
        try:
            spec = importlib.util.spec_from_file_location(f"termux_mcp_plugin_{f.stem}", f)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "register"):
                mod.register(mcp, tool)
                loaded.append(f.name)
        except Exception as e:  # satu plugin rusak tidak boleh menjatuhkan server
            print(f"[plugin] gagal memuat {f.name}: {e}", file=sys.stderr)
    return loaded


def build_app(token: str | None = None):
    config.ensure_dirs()
    mcp = FastMCP("termux-mcp", transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False))
    tool = make_tool_decorator(mcp)

    from .tools import shell, files, jobs, explore, web
    for module in (shell, files, jobs, explore, web):
        module.register(tool)

    plugins = load_plugins(mcp, tool)
    app = mcp.streamable_http_app()
    app.add_middleware(Auth, token=token or config.load_token())
    return app, mcp, plugins
