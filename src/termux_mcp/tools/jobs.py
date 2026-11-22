import json
import os
import signal
import subprocess
import time
import uuid
from .. import config, security

_procs = {}


def _meta(jid):
    f = config.JOBDIR / f"{jid}.json"
    if not f.exists():
        raise ValueError(f"job {jid} tidak ada")
    return json.loads(f.read_text())


def _alive(meta):
    p = _procs.get(meta["id"])
    if p is not None:
        return p.poll() is None
    try:
        os.kill(meta["pid"], 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _state(meta):
    exitf = config.JOBDIR / f"{meta['id']}.exit"
    if exitf.exists():
        return f"selesai (exit {exitf.read_text().strip()})"
    return "jalan" if _alive(meta) else "mati (dibunuh/crash)"


def _tail_log(jid, lines):
    log = config.JOBDIR / f"{jid}.log"
    if not log.exists():
        return ""
    with open(log, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - 20000))
        data = f.read().decode("utf-8", errors="replace")
    return "\n".join(data.splitlines()[-lines:])


def register(tool):
    @tool
    def start_job(cmd: str, cwd: str = ".") -> str:
        """Jalankan perintah di background (render video, build, dev server). Balikin job_id. Pantau pakai job_status, hentikan pakai kill_job."""
        config.JOBDIR.mkdir(parents=True, exist_ok=True)
        jid = uuid.uuid4().hex[:8]
        d = security.safe_path(cwd)
        log = config.JOBDIR / f"{jid}.log"
        exitf = config.JOBDIR / f"{jid}.exit"
        wrapped = f"( {cmd}\n) ; echo $? > '{exitf}'"
        with open(log, "wb") as lf:
            p = subprocess.Popen(wrapped, shell=True, executable=config.SHELL, cwd=d,
                stdout=lf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                start_new_session=True)
        _procs[jid] = p
        (config.JOBDIR / f"{jid}.json").write_text(json.dumps(
            {"id": jid, "cmd": cmd, "cwd": str(d), "pid": p.pid, "started": time.time()}))
        return f"job_id={jid} pid={p.pid}"

    @tool
    def job_status(job_id: str, tail: int = 40) -> str:
        """Status job background + N baris terakhir lognya."""
        m = _meta(job_id)
        dur = int(time.time() - m["started"])
        head = f"job {job_id} | {_state(m)} | {dur}s sejak mulai\ncmd: {m['cmd'][:200]}\n--- log ---\n"
        return head + (_tail_log(job_id, max(1, min(tail, 300))) or "(log kosong)")

    @tool
    def list_jobs() -> str:
        """Daftar semua job background beserta statusnya."""
        rows = []
        for f in sorted(config.JOBDIR.glob("*.json"), key=lambda x: x.stat().st_mtime):
            m = json.loads(f.read_text())
            rows.append(f"{m['id']}  {_state(m):<24} {m['cmd'][:60]}")
        return "\n".join(rows) or "(belum ada job)"

    @tool
    def kill_job(job_id: str) -> str:
        """Hentikan job background (SIGTERM ke seluruh process group)."""
        m = _meta(job_id)
        if not _alive(m):
            return f"job {job_id} sudah tidak jalan"
        os.killpg(m["pid"], signal.SIGTERM)
        return f"SIGTERM dikirim ke job {job_id}"
