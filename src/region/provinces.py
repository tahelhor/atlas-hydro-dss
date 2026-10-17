"""Static geography of the Béni Mellal–Khénifra region (5 provinces).

Boundaries: ``data/reference/bmk_provinces.geojson`` (geoBoundaries gbOpen MAR ADM2,
OpenStreetMap / Wambacher, ODbL 1.0). Climate series are sampled at each provincial capital.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

from src.config import DATA_DIR

REFERENCE_DIR = DATA_DIR / "reference"
PROVINCES_GEOJSON = REFERENCE_DIR / "bmk_provinces.geojson"


@dataclass(frozen=True)
class Province:
    province_id: str
    name_fr: str
    name_en: str
    name_ar: str
    capital: str
    lat: float  # provincial capital (climate sampling point)
    lon: float
    landscape_en: str
    landscape_fr: str


PROVINCES: tuple[Province, ...] = (
    Province("KHENIFRA", "Khénifra", "Khenifra", "خنيفرة", "Khénifra", 32.9394, -5.6686,
             "Middle Atlas mountains · Oum Er-Rbia headwaters",
             "Moyen Atlas · sources de l'Oum Er-Rbia"),
    Province("BENI_MELLAL", "Béni Mellal", "Beni Mellal", "بني ملال", "Béni Mellal", 32.3373, -6.3498,
             "Atlas piedmont · Tadla plain (Beni Moussa)",
             "Piémont de l'Atlas · plaine du Tadla (Beni Moussa)"),
    Province("AZILAL", "Azilal", "Azilal", "أزيلال", "Azilal", 31.9614, -6.5714,
             "High Atlas mountains · Bin El Ouidane lake",
             "Haut Atlas · lac de Bin El Ouidane"),
    Province("FQUIH_BEN_SALAH", "Fquih Ben Salah", "Fquih Ben Salah", "الفقيه بن صالح", "Fquih Ben Salah",
             32.5017, -6.6906,
             "Tadla irrigated plain (Beni Amir / Beni Moussa)",
             "Plaine irriguée du Tadla (Beni Amir / Beni Moussa)"),
    Province("KHOURIBGA", "Khouribga", "Khouribga", "خريبكة", "Khouribga", 32.8811, -6.9063,
             "Phosphate plateau · OCP mining basin",
             "Plateau des phosphates · bassin minier OCP"),
)
PROVINCES_BY_ID: dict[str, Province] = {p.province_id: p for p in PROVINCES}
PROVINCE_IDS: tuple[str, ...] = tuple(PROVINCES_BY_ID)


@lru_cache(maxsize=1)
def province_geojson() -> dict:
    with PROVINCES_GEOJSON.open(encoding="utf-8") as f:
        return json.load(f)
