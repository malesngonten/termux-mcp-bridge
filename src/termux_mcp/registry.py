"""Pendaftaran tool: audit log tiap panggilan + kemampuan mematikan tool lewat konfigurasi."""
import functools
import json
import time
from . import config


def audit(tool: str, args: dict):
    try:
        line = json.dumps({
            "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "tool": tool,
            "args": {k: str(v)[:200] for k, v in args.items()},
        }, ensure_ascii=False)
        with open(config.LOG_FILE, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def make_tool_decorator(mcp):
    """Dekorator `@tool`: daftarkan fungsi sebagai tool MCP, kecuali ada di TERMUX_MCP_DISABLE."""
    def tool(fn):
        if fn.__name__ in config.DISABLED:
            return fn

        @functools.wraps(fn)
        def wrapper(*a, **kw):
            audit(fn.__name__, kw)
            return fn(*a, **kw)

        mcp.tool()(wrapper)
        return fn
    return tool
