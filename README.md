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

## Panel setup (web UI)

Cara termudah untuk pemula: semua langkah (token, tunnel, nyalakan server, panduan konektor) dalam satu halaman.

```bash
termux-mcp ui
```

Buka link yang dicetak di terminal (berisi kode rahasia sekali jalan) di browser HP. Di halaman itu:

1. Salin atau buat token.
2. Pilih tunnel: **Cloudflare** (tanpa akun, alamat berubah tiap start) atau **ngrok** (alamat tetap, perlu akun gratis).
3. Tekan **Nyalakan server**, lalu ikuti panduan mengisi konektor di app Claude (nilai siap salin).

Semua yang bisa dilakukan panel tetap bisa lewat perintah (`serve`, `token`, `tunnel setup`). Panel memanggil logika yang sama.

Keamanan panel: hanya bind ke `127.0.0.1` di port terpisah (default 8787) dari server MCP, jadi tunnel tidak pernah
menunjuk ke panel. Akses butuh link berisi kode acak dari terminal, lalu sesi dipegang cookie `HttpOnly` + `SameSite=Strict`;
header Host dan header permintaan dicek. Token hanya dikirim ke halaman saat lu menekan Tampilkan atau Salin.
Server yang dinyalakan lewat panel tetap hidup setelah panel ditutup; matikan dari panel.

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

## Tunnel Cloudflare (tanpa akun)

Alternatif tanpa daftar: Cloudflare Quick Tunnel. Perlu binary `cloudflared` (Termux: `pkg install cloudflared`).

```bash
termux-mcp serve --tunnel cloudflare
```

Alamatnya `*.trycloudflare.com` dan **berubah setiap server dinyalakan ulang**, jadi konektor di Claude harus
diperbarui tiap kali. Untuk alamat tetap, pakai ngrok. Ketentuan Quick Tunnel dari Cloudflare bisa berubah; cek dokumentasi mereka.

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

Versi awal (0.1.0). Sudah ada: server, auth token, audit log, tool dasar, plugin, `doctor`, tunnel ngrok dan
Cloudflare otomatis, panel setup web (`termux-mcp ui`).
Tes otomatis (`PYTHONPATH=src python -m unittest discover -s tests -v`) memakai ngrok dan cloudflared tiruan;
belum diuji dengan keduanya yang asli, dan tampilan panel belum diuji lintas browser.
Belum ada: mode non-root, konfirmasi tool berbahaya, tool khusus video/audio.

## Lisensi

MIT. Isi nama pemegang hak cipta di [LICENSE](LICENSE).
