#!/usr/bin/env python3
"""Hasilkan path SVG globe (daratan + garis lintang/bujur) untuk panel web, dari data Natural Earth 110m (domain publik).

Pakai:
    python tools/gen_globe.py land.geojson            # file lokal
    python tools/gen_globe.py --download              # unduh ne_110m_land.geojson dulu
Hasil ditulis ke atribut d milik <path id="land-path"> dan <path id="grat-path"> di src/termux_mcp/ui.html.
Proyeksi ortografis berpusat di (LON0, LAT0); viewBox 360x360, pusat (180,180), jari-jari R.
"""
import json
import math
import re
import sys
import urllib.request
from pathlib import Path

URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_land.geojson"
HTML = Path(__file__).resolve().parent.parent / "src" / "termux_mcp" / "ui.html"
LON0, LAT0, R, CX, CY = 5.0, 26.0, 125.0, 180.0, 180.0
TOL = 0.45  # toleransi penyederhanaan (satuan viewBox)

L0, P0 = math.radians(LON0), math.radians(LAT0)


def project(lon: float, lat: float):
    """Kembalikan (x, y, terlihat). Titik di sisi belakang ditempelkan ke tepi globe."""
    lam, phi = math.radians(lon), math.radians(lat)
    cosc = math.sin(P0) * math.sin(phi) + math.cos(P0) * math.cos(phi) * math.cos(lam - L0)
    x = math.cos(phi) * math.sin(lam - L0)
    y = math.cos(P0) * math.sin(phi) - math.sin(P0) * math.cos(phi) * math.cos(lam - L0)
    if cosc < 0:
        n = math.hypot(x, y) or 1.0
        x, y = x / n, y / n
    return CX + R * x, CY - R * y, cosc >= 0


def rdp(pts, tol):
    if len(pts) < 3:
        return pts
    (x1, y1), (x2, y2) = pts[0], pts[-1]
    dx, dy = x2 - x1, y2 - y1
    norm = math.hypot(dx, dy)
    best, idx = -1.0, 0
    for i in range(1, len(pts) - 1):
        px, py = pts[i]
        d = abs(dy * px - dx * py + x2 * y1 - y2 * x1) / norm if norm else math.hypot(px - x1, py - y1)
        if d > best:
            best, idx = d, i
    if best > tol:
        return rdp(pts[: idx + 1], tol)[:-1] + rdp(pts[idx:], tol)
    return [pts[0], pts[-1]]


def fmt(v: float) -> str:
    s = f"{v:.1f}"
    return s[:-2] if s.endswith(".0") else s


def land_path(data) -> str:
    rings = []
    for feat in data["features"]:
        g = feat["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for poly in polys:
            for ring in poly:
                if max(p[1] for p in ring) < -60:  # Antarktika: bentuknya rusak di proyeksi ini
                    continue
                proj = [project(lon, lat) for lon, lat in ring]
                if not any(v for _, _, v in proj):
                    continue
                pts = [(x, y) for x, y, _ in proj]
                pts = rdp(pts, TOL)
                if len(pts) >= 3:
                    rings.append(pts)
    out = []
    for pts in rings:
        out.append("M" + " ".join(f"{fmt(x)} {fmt(y)}" for x, y in pts) + "Z")
    return "".join(out)


def graticule_path() -> str:
    segs = []

    def run(points):
        cur = []
        for lon, lat in points:
            x, y, vis = project(lon, lat)
            if vis:
                cur.append((x, y))
            elif cur:
                segs.append(cur)
                cur = []
        if cur:
            segs.append(cur)

    for lat in (-60, -30, 0, 30, 60):
        run([(lon, lat) for lon in range(-180, 181, 4)])
    for lon in range(-180, 180, 30):
        run([(lon, lat) for lat in range(-90, 91, 4)])
    return "".join("M" + " ".join(f"{fmt(x)} {fmt(y)}" for x, y in rdp(s, 0.25)) for s in segs if len(s) > 1)


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "--download"
    if arg == "--download":
        with urllib.request.urlopen(URL, timeout=60) as r:
            data = json.load(r)
    else:
        data = json.loads(Path(arg).read_text())
    land, grat = land_path(data), graticule_path()
    html = HTML.read_text()
    for pid, d in (("land-path", land), ("grat-path", grat)):
        pat = re.compile(r'(id="%s"[^>]*?\sd=")[^"]*(")' % pid)
        assert pat.search(html), f"path #{pid} tidak ada di ui.html"
        html = pat.sub(lambda m: m.group(1) + d + m.group(2), html, count=1)
    HTML.write_text(html)
    print(f"land: {len(land)} byte, graticule: {len(grat)} byte -> {HTML}")


if __name__ == "__main__":
    main()
