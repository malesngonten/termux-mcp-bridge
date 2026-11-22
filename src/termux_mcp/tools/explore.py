import fnmatch
import os
import re
from .. import config
from ..security import safe_path, rel


def register(tool):
    @tool
    def list_dir(path: str = ".", depth: int = 2) -> str:
        """Tampilkan struktur folder (pohon) sampai kedalaman `depth`. node_modules, .git, target, dll dilewati."""
        root = safe_path(path)
        if not root.is_dir():
            return "bukan direktori"
        lines = []

        def walk(d, level):
            try:
                entries = sorted(d.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
            except PermissionError:
                return
            for e in entries:
                if len(lines) >= 300:
                    return
                pad = "  " * level
                if e.is_dir():
                    skipped = e.name in config.SKIP_DIRS
                    lines.append(f"{pad}{e.name}/" + ("  (dilewati)" if skipped else ""))
                    if not skipped and level + 1 < depth:
                        walk(e, level + 1)
                else:
                    lines.append(f"{pad}{e.name}  ({e.stat().st_size}B)")

        walk(root, 0)
        if len(lines) >= 300:
            lines.append("... (dipotong di 300 entri)")
        return "\n".join(lines) or "(kosong)"

    @tool
    def find_files(pattern: str, path: str = ".") -> str:
        """Cari file berdasarkan nama pakai pola glob, contoh '*.rs' atau 'package.json'."""
        root = safe_path(path)
        res = []
        for dp, dn, fn in os.walk(root):
            dn[:] = [d for d in dn if d not in config.SKIP_DIRS]
            for name in fn:
                if fnmatch.fnmatch(name, pattern):
                    res.append(rel(os.path.join(dp, name)))
                    if len(res) >= 200:
                        return "\n".join(res) + "\n... (dipotong di 200)"
        return "\n".join(res) or "(tidak ada yang cocok)"

    @tool
    def search_text(pattern: str, path: str = ".", file_glob: str = "*",
                    ignore_case: bool = False, regex: bool = True) -> str:
        """Cari teks di dalam file (kayak grep -rn). Hasil: file:baris: isi. Maks 200 hasil."""
        rx = re.compile(pattern if regex else re.escape(pattern), re.I if ignore_case else 0)
        root = safe_path(path)
        res = []
        for dp, dn, fn in os.walk(root):
            dn[:] = [d for d in dn if d not in config.SKIP_DIRS]
            for name in fn:
                if not fnmatch.fnmatch(name, file_glob):
                    continue
                fp = os.path.join(dp, name)
                try:
                    if os.path.getsize(fp) > 1_000_000:
                        continue
                    with open(fp, "rb") as fh:
                        raw = fh.read()
                    if b"\0" in raw[:1024]:
                        continue
                    for i, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), 1):
                        if rx.search(line):
                            res.append(f"{rel(fp)}:{i}: {line.strip()[:200]}")
                            if len(res) >= 200:
                                return "\n".join(res) + "\n... (dipotong di 200)"
                except OSError:
                    continue
        return "\n".join(res) or "(tidak ada yang cocok)"
