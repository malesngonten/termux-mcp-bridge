# Plugin

Tool tambahan dimuat dari `~/.config/termux-mcp/plugins/*.py` saat server dinyalakan.
Setiap file harus punya fungsi `register(mcp, tool)`. Lihat `examples/plugins/hello.py`.

Gunakan dekorator `@tool` (bukan `@mcp.tool()`) supaya tool Anda ikut tercatat di audit log
dan bisa dimatikan lewat `TERMUX_MCP_DISABLE`.

> Plugin berjalan dengan hak penuh sama seperti server. Pasang hanya plugin yang Anda percaya.

Rencana: plugin resmi untuk video/audio (TTS, ekstrak frame, cek durasi), perangkat (Termux:API), dan lainnya.
