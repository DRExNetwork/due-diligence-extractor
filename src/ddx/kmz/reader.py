from __future__ import annotations
from pathlib import Path
from typing import List

def _count_polygons_in_kml_bytes(kml_bytes: bytes) -> int:
    from xml.etree import ElementTree as ET
    try:
        root = ET.fromstring(kml_bytes)
    except Exception:
        return 0
    ns = {"kml": "http://www.opengis.net/kml/2.2"}
    polys = root.findall(".//kml:Polygon", ns)
    if polys:
        return len(polys)
    polys = root.findall(".//Polygon")
    return len(polys) if polys else 0

def parse_kmz_for_polygon(path: Path) -> bool:
    import zipfile
    try:
        with zipfile.ZipFile(path, "r") as zf:
            for name in zf.namelist():
                if name.lower().endswith(".kml"):
                    try:
                        kml_bytes = zf.read(name)
                    except Exception:
                        continue
                    if _count_polygons_in_kml_bytes(kml_bytes) > 0:
                        return True
        return False
    except Exception:
        return False

def read_kmz_file(path: Path) -> List[str]:
    import zipfile
    summary = []
    try:
        with zipfile.ZipFile(path, "r") as zf:
            kml_names = [n for n in zf.namelist() if n.lower().endswith(".kml")]
            if not kml_names:
                return [f"[KMZ] No KML files found in {path.name}."]
            total_polys = 0
            per_file = []
            for n in kml_names:
                try:
                    cnt = _count_polygons_in_kml_bytes(zf.read(n))
                except Exception:
                    cnt = 0
                total_polys += cnt
                per_file.append(f"{n}({cnt})")
            summary.append(f"[KMZ] Found {total_polys} polygons in {', '.join(per_file)}.")
    except Exception as e:
        summary.append(f"[KMZ] Failed to read {path.name}: {e}")
    return summary or [f"[KMZ] No polygons found in {path.name}."]