from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path
from typing import NamedTuple

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "ui"


class City(NamedTuple):
    geonameid: int
    name: str
    asciiname: str
    latitude: float
    longitude: float
    country_code: str
    admin1_code: str
    population: int
    feature_code: str


def parse_cities1000() -> list[City]:
    zippath = DATA_DIR / "cities1000.zip"
    with zipfile.ZipFile(zippath) as z, z.open("cities1000.txt") as f:
        reader = csv.reader(io.TextIOWrapper(f, encoding="utf-8"), delimiter="\t")
        cities: list[City] = []
        for row in reader:
            if len(row) < 15:
                continue
            cities.append(
                City(
                    geonameid=int(row[0]),
                    name=row[1],
                    asciiname=row[2],
                    latitude=float(row[4]),
                    longitude=float(row[5]),
                    country_code=row[8],
                    admin1_code=row[10],
                    population=int(row[14]) if row[14] else 0,
                    feature_code=row[7],
                )
            )
    return cities


def parse_admin1_codes() -> dict[str, str]:
    path = DATA_DIR / "admin1CodesASCII.txt"
    result: dict[str, str] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                result[parts[0]] = parts[1]
    return result


def parse_country_info() -> dict[str, tuple[str, int]]:
    path = DATA_DIR / "countryInfo.txt"
    result: dict[str, tuple[str, int]] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.startswith("#"):
                continue
            parts = line.strip().split("\t")
            if len(parts) >= 8:
                iso = parts[0]
                name = parts[4]
                pop = int(parts[7]) if parts[7] and parts[7].isdigit() else 0
                result[iso] = (name, pop)
    return result


def parse_alternate_names(
    valid_geonameids: set[int],
) -> dict[int, list[str]]:
    zippath = DATA_DIR / "alternateNamesV2.zip"
    result: dict[int, list[str]] = {}
    with zipfile.ZipFile(zippath) as z, z.open("alternateNamesV2.txt") as f:
        reader = csv.reader(io.TextIOWrapper(f, encoding="utf-8"), delimiter="\t")
        for row in reader:
            if len(row) < 3:
                continue
            try:
                geonameid = int(row[1])
            except (ValueError, IndexError):
                continue
            if geonameid in valid_geonameids:
                alt_name = row[3] if len(row) > 3 else ""
                if alt_name and alt_name.strip():
                    result.setdefault(geonameid, []).append(alt_name.strip())
    return result
