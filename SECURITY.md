# Keamanan

termux-mcp-bridge memberi Claude **akses shell** ke perangkat Anda lewat URL publik.
Anggap ini setara membuka SSH. Pahami risikonya sebelum dipakai.

## Model ancaman singkat
- **Token bocor = akses penuh.** Siapa pun yang punya token bisa menjalankan perintah apa saja sebagai user yang menjalankan server.
- **Prompt injection.** Isi halaman web, file, atau pesan yang dibaca Claude bisa berisi instruksi jahat. Tool `run` tetap bisa dipakai di luar workspace, karena itu pertimbangkan apa yang Anda minta Claude baca.
- **Root.** Di Ubuntu proot biasanya Anda root. Lebih baik buat user biasa.

## Yang sudah ada
- Token acak 256-bit, disimpan dengan izin `600`, dibandingkan dengan `hmac.compare_digest`.
- Pembatas percobaan gagal per IP (HTTP 429).
- Tool file dikunci ke satu folder workspace.
- Audit log semua panggilan tool: `~/.config/termux-mcp/audit.log`.
- Tool bisa dimatikan: `TERMUX_MCP_DISABLE=delete_path,http_fetch`.
- Server hanya mendengarkan `127.0.0.1` secara default.

## Yang belum ada (roadmap)
- Pembatasan perintah/allowlist untuk `run`.
- Konfirmasi manusia untuk tool berbahaya.
- Mode user non-root otomatis.
- Pembatasan IP ke rentang Anthropic.

## Praktik yang disarankan
- Putar token berkala: `termux-mcp token --new` (lalu perbarui konektor).
- Matikan server dan tunnel kalau tidak dipakai.
- Jangan jalankan di perangkat dengan data sensitif tanpa isolasi.

## Melaporkan celah
Buka security advisory privat di GitHub repo ini, jangan lewat issue publik.
