"""Paquetes de país desacoplados para contexto demográfico, económico y cultural (Colombia y LATAM)."""

from .base_contracts import (
    ArchetypeSpec,
    CityRecord,
    CountryPack,
    OfficialSourceSpec,
    StratumItem,
)
from .registry import get_country_pack, list_country_packs

__all__ = [
    "ArchetypeSpec",
    "CityRecord",
    "CountryPack",
    "OfficialSourceSpec",
    "StratumItem",
    "get_country_pack",
    "list_country_packs",
]
