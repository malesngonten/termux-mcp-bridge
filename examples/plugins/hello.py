"""Contoh plugin minimal. Salin ke ~/.config/termux-mcp/plugins/ lalu restart server."""


def register(mcp, tool):
    @tool
    def halo(nama: str = "dunia") -> str:
        """Menyapa. Docstring ini yang dibaca Claude sebagai deskripsi tool."""
        return f"Halo, {nama}!"
