# termux-mcp-bridge

Hubungkan **aplikasi Claude** ke **terminal di perangkat Anda** (Termux / Ubuntu proot / Linux) lewat MCP.
Claude yang berpikir dan mengawasi, terminal Anda yang mengeksekusi: jalankan perintah, kelola file,
proses di background (render, build), dan tambahkan kemampuan lewat plugin.

> ⚠️ **Baca [SECURITY.md](SECURITY.md) dulu.** Tool ini membuka akses shell ke perangkat Anda lewat URL publik.
> Token yang bocor berarti akses penuh. Jangan dipasang tanpa memahami risikonya.

## Cara kerja

```
Aplikasi Claude ──internet──▶ tunnel (mis. ngrok) ──▶ termux-mcp di perangkat Anda ──▶ shell, file, job
```

Yang memanggil server Anda adalah cloud Anthropic, bukan HP Anda, jadi server butuh alamat HTTPS publik yang stabil. Itulah fungsi tunnel.

## Instalasi

Perlu Python 3.10+ dan git. Dari dalam folder repo:

```bash
bash install.sh
```

Skrip ini pendek dan sengaja mudah dibaca. Baca dulu sebelum menjalankan. Ia akan membuat venv di
`~/.local/share/termux-mcp`, memasang paket, dan membuat perintah `termux-mcp`.

Cek kesiapan: `termux-mcp doctor`

## Menjalankan

```bash
termux-mcp serve            # http://127.0.0.1:8000/mcp
termux-mcp token            # tampilkan token (dibuat otomatis, acak)
```

Folder kerja default: `~/workspace` (ubah dengan `TERMUX_MCP_WORKSPACE`).
Di Termux, jalankan `termux-wake-lock` supaya Android tidak mematikan proses di background.

## Tunnel (otomatis dengan ngrok)

Perlu akun ngrok (gratis) dan binary `ngrok` terpasang (https://ngrok.com/download).

```bash
termux-mcp tunnel setup           # sekali saja: authtoken ngrok + domain tetap (opsional)
termux-mcp serve --tunnel ngrok   # server dan tunnel sekaligus
```

Server mencetak URL dan nama header untuk konektor Claude. Token tidak dicetak secara default:
pakai `termux-mcp token`, atau `--show-token`. Kalau `termux-clipboard-set` (Termux:API) tersedia, URL ikut disalin.

- **Domain tetap**: akun ngrok gratis mendapat satu dev domain (lihat dashboard ngrok). Isi saat `tunnel setup`
  supaya URL konektor tidak berubah. Tanpa domain, URL acak tiap start dan konektor harus diedit ulang.
- **Authtoken** disimpan oleh ngrok sendiri (`ngrok config add-authtoken`), bukan oleh termux-mcp.
- **Putus sambung**: tunnel dinyalakan ulang otomatis (maks. 5 kali berturut-turut). Error fatal
  (authtoken salah, batas sesi akun, domain sedang dipakai) menghentikan percobaan dan menampilkan petunjuk.
- Batas dan harga ngrok bisa berubah. Cek dashboard mereka. Akun gratis biasanya dibatasi jumlah sesi agent.

Tanpa `--tunnel`, Anda bisa menjalankan tunnel sendiri (`ngrok http 8000`) dan memakai URL-nya.

## Menambah konektor di Claude

Di pengaturan Claude, tambahkan **konektor kustom** (nama menu bisa berbeda antar versi aplikasi):

- **URL**: `https://<alamat-tunnel-anda>/mcp`
- **Header**: `x-api-key` dengan nilai dari `termux-mcp token`

Catatan: saat project ini dibuat, form konektor menolak nama header `Authorization` (dicadangkan untuk OAuth),
makanya server membaca `x-api-key`. Buka chat baru setelah konektor ditambahkan agar daftar tool ter-refresh.

## Tool bawaan

| Kelompok | Tool |
|---|---|
| Shell | `run` |
| Job background | `start_job`, `job_status`, `list_jobs`, `kill_job` |
| File | `read_file`, `read_lines`, `write_file`, `append_file`, `edit_file`, `move_path`, `delete_path` |
| Eksplorasi | `list_dir`, `find_files`, `search_text` |
| Web | `http_fetch` |

## Konfigurasi (environment variable)

| Variabel | Fungsi | Default |
|---|---|---|
| `TERMUX_MCP_WORKSPACE` | Folder kerja untuk tool file | `~/workspace` |
| `TERMUX_MCP_HOME` | Lokasi token, audit log, plugin | `~/.config/termux-mcp` |
| `TERMUX_MCP_DISABLE` | Tool yang dimatikan (pisah koma) | kosong |
| `TERMUX_MCP_TUNNEL` | Nyalakan tunnel otomatis (`ngrok`), setara `--tunnel` | kosong |
| `TERMUX_MCP_NGROK_DOMAIN` | Domain tetap ngrok (menimpa `tunnel setup`) | kosong |

## Plugin

Lihat [plugins/README.md](plugins/README.md) dan `examples/plugins/hello.py`.

## Status

Versi awal (0.1.0). Sudah ada: server, auth token, audit log, tool dasar, plugin, `doctor`, tunnel ngrok otomatis.
Tes otomatis (`PYTHONPATH=src python -m unittest discover -s tests -v`) memakai ngrok tiruan untuk logika tunnel;
belum diuji dengan ngrok asli di berbagai jenis akun.
Belum ada: tunnel Cloudflare, mode non-root, konfirmasi tool berbahaya, tool khusus video/audio.

## Lisensi

MIT. Isi nama pemegang hak cipta di [LICENSE](LICENSE).
