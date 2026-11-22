import shutil
from .. import config
from ..security import safe_path


def register(tool):
    @tool
    def read_file(path: str) -> str:
        """Baca file di workspace (maks 20000 karakter)."""
        return safe_path(path).read_text()[:20000]

    @tool
    def read_lines(path: str, start: int = 1, end: int = 200) -> str:
        """Baca file dengan nomor baris. start/end (1-based, inklusif). Cocok buat file besar."""
        lines = safe_path(path).read_text(errors="replace").splitlines()
        total = len(lines)
        if total == 0:
            return "(file kosong)"
        start = max(1, start)
        end = min(end, total)
        body = "\n".join(f"{i}\t{lines[i - 1]}" for i in range(start, end + 1))
        return f"[{path}: baris {start}-{end} dari {total}]\n" + body[:20000]

    @tool
    def write_file(path: str, content: str) -> str:
        """Tulis file di workspace (menimpa kalau sudah ada)."""
        f = safe_path(path)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)
        return "ok"

    @tool
    def append_file(path: str, content: str) -> str:
        """Tambahkan teks ke akhir file (dibuat kalau belum ada)."""
        f = safe_path(path)
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(f, "a") as fh:
            fh.write(content)
        return "ok"

    @tool
    def edit_file(path: str, old: str, new: str, replace_all: bool = False) -> str:
        """Ganti teks `old` dengan `new` di file. `old` harus unik kecuali replace_all=true."""
        if not old:
            return "gagal: old kosong"
        f = safe_path(path)
        s = f.read_text()
        n = s.count(old)
        if n == 0:
            return "gagal: teks lama tidak ditemukan"
        if n > 1 and not replace_all:
            return f"gagal: ditemukan {n}x. Perpanjang konteks atau set replace_all=true"
        f.write_text(s.replace(old, new) if replace_all else s.replace(old, new, 1))
        return f"ok ({n if replace_all else 1} penggantian)"

    @tool
    def move_path(src: str, dst: str) -> str:
        """Pindah/rename file atau folder (keduanya di dalam workspace)."""
        d = safe_path(dst)
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(safe_path(src)), str(d))
        return "ok"

    @tool
    def delete_path(path: str) -> str:
        """Hapus file atau folder (rekursif) di dalam workspace. Tidak bisa menghapus workspace itu sendiri."""
        f = safe_path(path)
        if f == config.WORKSPACE.resolve():
            return "ditolak: tidak boleh hapus workspace"
        if f.is_dir() and not f.is_symlink():
            shutil.rmtree(f)
        else:
            f.unlink()
        return "ok"
