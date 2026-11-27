"""Contratos Pydantic para paquetes de país desacoplados (Colombia primero, extensible a LATAM)."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class CityRecord(BaseModel):
    divipola_code: str = Field(..., min_length=5, max_length=6)
    city_name: str
    department: str
    region_macro: str
    urban_tier: str
    is_capital: bool = True
    population_2026: Optional[int] = None
    fixed_internet_accesses: Optional[int] = None
    fixed_internet_penetration_pct: Optional[float] = None
    lat: float
    lon: float
    cultural_archetype_default: str
    source_citation: str

    @field_validator("divipola_code")
    @classmethod
    def validate_divipola(cls, v: str) -> str:
        clean = str(v).strip()
        if len(clean) <= 5 and clean.isdigit():
            clean = clean.zfill(5)
        if not clean.isdigit() or len(clean) not in (5, 6):
            raise ValueError(f"Código territorial inválido: {v}")
        return clean

    @field_validator("lat", "lon")
    @classmethod
    def validate_coords(cls, v: float) -> float:
        if math.isnan(v) or math.isinf(v):
            raise ValueError("Coordenada geográfica inválida (NaN/Inf)")
        return float(v)


class StratumItem(BaseModel):
    code: str
    label: str
    wealth_tier_norm: int = Field(..., ge=1, le=5)
    urban_weight_pct: float = Field(..., ge=0.0, le=100.0)
    income_smmlv_min: float = 0.0
    income_smmlv_max: float = 0.0
    utility_subsidy_role: str = "Neutro"
    price_elasticity_level: str = "Media"
    financial_access_profile: str = ""
    connectivity_mode: str = ""
    source_citation: str = ""


class ArchetypeSpec(BaseModel):
    code: str
    name: str
    region_macro: str
    cities: List[str] = Field(default_factory=list)
    communication_register: str
    controlled_slang: List[str] = Field(default_factory=list)
    purchase_drivers: List[str] = Field(default_factory=list)
    skepticism_triggers: List[str] = Field(default_factory=list)
    social_trust_anchor: str = ""


class OfficialSourceSpec(BaseModel):
    source_id: str
    name: str
    authority: str
    category: str
    tier: str
    socrata_dataset_id: Optional[str] = None
    endpoint_url: str
    max_staleness_days: int = 180
    notes: str = ""


class CountryPack(BaseModel):
    country_code: str
    country_name: str
    status: str = "active"
    currency: str
    locale: str
    timezone: str
    min_wage_local: float
    transport_aid_local: float = 0.0
    min_wage_source: str = ""
    taxonomy_system: str = ""
    cities: List[CityRecord] = Field(default_factory=list)
    strata: List[StratumItem] = Field(default_factory=list)
    archetypes: List[ArchetypeSpec] = Field(default_factory=list)
    sources: List[OfficialSourceSpec] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def get_city_by_name_or_code(self, query: str) -> Optional[CityRecord]:
        q = (query or "").strip().lower()
        if not q:
            return None
        for c in self.cities:
            if c.divipola_code == q or q in c.city_name.lower():
                return c
        return None

    def render_prompt_context(self, target_cities: Optional[List[str]] = None) -> str:
        """Renderiza un bloque compacto en español para inyectar contexto del país en prompts LLM."""
        selected = []
        if target_cities:
            for item in target_cities:
                match = self.get_city_by_name_or_code(item)
                if match and match not in selected:
                    selected.append(match)
        if not selected:
            selected = self.cities[:6]

        city_lines = [
            f"- {c.city_name} (DIVIPOLA {c.divipola_code}, {c.region_macro}, pob. {c.population_2026:,}, internet fijo {c.fixed_internet_penetration_pct}%)"
            for c in selected
            if c.population_2026 is not None
        ]
        strata_lines = [
            f"{s.code} ({s.label}, peso {s.urban_weight_pct}%, {s.income_smmlv_min}-{s.income_smmlv_max} SMMLV)"
            for s in self.strata
        ]
        return (
            f"[PAÍS ACTIVO: {self.country_name} ({self.country_code.upper()}) | Moneda: {self.currency} | "
            f"Salario mínimo ref.: {self.currency} {int(self.min_wage_local):,} ({self.min_wage_source}) | "
            f"Zona horaria: {self.timezone}]\n"
            f"Ciudades objetivo:\n" + "\n".join(city_lines) + "\n"
            f"Taxonomía socioeconómica ({self.taxonomy_system}): " + "; ".join(strata_lines)
        )
