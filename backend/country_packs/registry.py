"""Registro y cargador dinámico de paquetes de país (`backend/country_packs/<iso2>/`)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

import yaml

from .base_contracts import (
    ArchetypeSpec,
    CityRecord,
    CountryPack,
    OfficialSourceSpec,
    StratumItem,
)

PACKS_ROOT = Path(__file__).resolve().parent


def _load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


@lru_cache(maxsize=16)
def get_country_pack(iso2: str = "co") -> CountryPack:
    """Carga y valida con Pydantic el CountryPack solicitado."""
    code = (iso2 or "co").strip().lower()
    pack_dir = PACKS_ROOT / code
    pack_yaml = pack_dir / "pack.yaml"
    if not pack_yaml.exists():
        raise FileNotFoundError(f"CountryPack no encontrado para '{code}'")

    meta = _load_yaml(pack_yaml)
    cities_raw: List[Dict[str, Any]] = []
    cities_path = pack_dir / "cities.json"
    if cities_path.exists():
        cities_raw = json.loads(cities_path.read_text(encoding="utf-8"))

    strata_doc = _load_yaml(pack_dir / "taxonomy_stratum.yaml")
    archetypes_doc = _load_yaml(pack_dir / "archetypes.yaml")
    sources_doc = _load_yaml(pack_dir / "sources.yaml")

    return CountryPack(
        country_code=meta.get("country_code", code),
        country_name=meta.get("country_name", code.upper()),
        status=meta.get("status", "active"),
        currency=meta.get("currency", "USD"),
        locale=meta.get("locale", "es-419"),
        timezone=meta.get("timezone", "America/Bogota"),
        min_wage_local=float(meta.get("min_wage_local", 0)),
        transport_aid_local=float(meta.get("transport_aid_local", 0)),
        min_wage_source=str(meta.get("min_wage_source", "")),
        taxonomy_system=str(strata_doc.get("taxonomy_system", meta.get("taxonomy_system", ""))),
        cities=[CityRecord(**c) for c in cities_raw],
        strata=[StratumItem(**s) for s in strata_doc.get("strata", [])],
        archetypes=[ArchetypeSpec(**a) for a in archetypes_doc.get("archetypes", [])],
        sources=[OfficialSourceSpec(**src) for src in sources_doc.get("sources", [])],
        metadata=meta.get("metadata", {}),
    )


def list_country_packs() -> List[Dict[str, Any]]:
    """Lista todos los paquetes de país disponibles en `backend/country_packs/`."""
    packs: List[Dict[str, Any]] = []
    for sub in sorted(PACKS_ROOT.iterdir()):
        if not sub.is_dir():
            continue
        pack_yaml = sub / "pack.yaml"
        if not pack_yaml.exists():
            continue
        meta = _load_yaml(pack_yaml)
        cities_count = 0
        cities_path = sub / "cities.json"
        if cities_path.exists():
            cities_count = len(json.loads(cities_path.read_text(encoding="utf-8")))
        packs.append(
            {
                "country_code": meta.get("country_code", sub.name),
                "country_name": meta.get("country_name", sub.name.upper()),
                "status": meta.get("status", "active"),
                "currency": meta.get("currency", ""),
                "locale": meta.get("locale", ""),
                "timezone": meta.get("timezone", ""),
                "min_wage_local": meta.get("min_wage_local", 0),
                "cities_count": cities_count,
            }
        )
    return packs
