"""Pengaman path: tool file tidak boleh keluar dari WORKSPACE."""
from pathlib import Path
from . import config


def safe_path(p: str) -> Path:
    base = config.WORKSPACE.resolve()
    f = (base / p).resolve()
    if f != base and base not in f.parents:
        raise ValueError("path di luar workspace")
    return f


def rel(p) -> str:
    try:
        return str(Path(p).resolve().relative_to(config.WORKSPACE.resolve()))
    except ValueError:
        return str(p)
