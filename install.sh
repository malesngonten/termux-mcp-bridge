#!/usr/bin/env bash
# Installer termux-mcp-bridge. Sengaja pendek dan mudah dibaca: baca dulu sebelum dijalankan.
# Yang dilakukan: (1) pasang python/git kalau belum ada, (2) buat venv di ~/.local/share/termux-mcp,
# (3) pasang paket ini, (4) buat perintah `termux-mcp`, (5) buat token acak.
set -euo pipefail

REPO_URL="${TERMUX_MCP_REPO:-https://github.com/malesngonten/termux-mcp-bridge.git}"
REF="${TERMUX_MCP_REF:-main}"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/termux-mcp"
BIN="$HOME/.local/bin"

say() { printf '\n==> %s\n' "$*"; }
as_root() { if [ "$(id -u)" -eq 0 ] || ! command -v sudo >/dev/null 2>&1; then "$@"; else sudo "$@"; fi; }

say "Cek python dan git"
need=0
command -v python3 >/dev/null 2>&1 || need=1
command -v git >/dev/null 2>&1 || need=1
python3 -c 'import venv, ensurepip' >/dev/null 2>&1 || need=1
if [ "$need" -eq 1 ]; then
  if command -v pkg >/dev/null 2>&1; then
    pkg install -y python git
  elif command -v apt-get >/dev/null 2>&1; then
    as_root apt-get update -y
    as_root apt-get install -y python3 python3-venv python3-pip git
  else
    echo "Paket manager tidak dikenali. Pasang python3 (>=3.10, dengan venv) dan git secara manual." >&2
    exit 1
  fi
fi
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || { echo "Butuh Python 3.10 atau lebih baru." >&2; exit 1; }

say "Ambil kode"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -n "$HERE" ] && grep -qs 'name = "termux-mcp-bridge"' "$HERE/pyproject.toml"; then
  SRC="$HERE"
  echo "Memakai kode lokal: $SRC"
else
  SRC="$DATA/src"
  mkdir -p "$DATA"
  if [ -d "$SRC/.git" ]; then
    git -C "$SRC" fetch --depth 1 origin "$REF"
    git -C "$SRC" checkout -q FETCH_HEAD
  else
    rm -rf "$SRC"
    git clone --depth 1 --branch "$REF" "$REPO_URL" "$SRC"
  fi
fi

say "Pasang paket (venv: $DATA/venv)"
mkdir -p "$DATA"
python3 -m venv "$DATA/venv"
"$DATA/venv/bin/pip" install --quiet --upgrade pip
"$DATA/venv/bin/pip" install --quiet "$SRC"

say "Buat perintah termux-mcp"
mkdir -p "$BIN"
ln -sf "$DATA/venv/bin/termux-mcp" "$BIN/termux-mcp"
"$DATA/venv/bin/termux-mcp" token >/dev/null 2>&1   # buat token kalau belum ada

case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo "Tambahkan ke ~/.bashrc:  export PATH=\"$BIN:\$PATH\"" ;;
esac

cat <<MSG

Selesai. Langkah berikutnya:
  1. termux-mcp doctor        # cek kesiapan
  2. termux-mcp serve         # nyalakan server (port 8000)
  3. Buat tunnel HTTPS ke port 8000 (lihat README), lalu tambahkan konektor kustom di Claude
  4. termux-mcp token         # nilai untuk header x-api-key

Baca SECURITY.md: tool ini memberi Claude akses shell ke perangkat ini.
MSG
