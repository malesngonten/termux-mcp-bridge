import os
import signal
import subprocess
from .. import config, security


def _exec(cmd, cwd, timeout):
    p = subprocess.Popen(cmd, shell=True, executable=config.SHELL, cwd=cwd,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        text=True, errors="replace", start_new_session=True)
    try:
        out, _ = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        out, _ = p.communicate()
        return (out or "")[-8000:] + f"\n[timeout {timeout}s, proses dibunuh. Untuk proses lama pakai start_job]"
    out = out or ""
    prefix = f"[exit {p.returncode}]\n" if p.returncode else ""
    return prefix + (out[-8000:] or "(tanpa output)")


def register(tool):
    @tool
    def run(cmd: str, timeout: int = 120, cwd: str = ".") -> str:
        """Jalankan perintah shell (bash) di workspace. timeout detik (maks 600), cwd relatif ke workspace. Untuk proses lama (render/build/server) pakai start_job."""
        timeout = max(1, min(int(timeout), 600))
        return _exec(cmd, security.safe_path(cwd), timeout)
