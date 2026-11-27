"""Pruebas de Fase 1 para CountryPack, ciudades colombianas, taxonomía y endpoints."""

from __future__ import annotations

import math

import pytest

from app import create_app
from app.models.project import Project
from country_packs import get_country_pack, list_country_packs


def test_colombia_pack_loads_33_cities_and_valid_weights():
    pack = get_country_pack("co")
    assert pack.country_code == "co"
    assert pack.currency == "COP"
    assert pack.min_wage_local == 1750905
    assert pack.transport_aid_local == 249095
    assert len(pack.cities) == 33

    codes = {c.divipola_code for c in pack.cities}
    assert "11001" in codes  # Bogotá
    assert "05001" in codes  # Medellín
    assert "76001" in codes  # Cali
    assert "25754" in codes  # Soacha
    for c in pack.cities:
        assert len(c.divipola_code) in (5, 6)
        assert c.divipola_code.isdigit()
        assert not math.isnan(c.lat) and not math.isnan(c.lon)

    total_weight = sum(s.urban_weight_pct for s in pack.strata)
    assert abs(total_weight - 100.0) <= 0.1

    assert len(pack.archetypes) == 7
    assert len(pack.sources) >= 10


def test_latam_extensibility_includes_planned_mx_pack():
    packs = list_country_packs()
    codes = {p["country_code"]: p for p in packs}
    assert "co" in codes and codes["co"]["status"] == "active"
    assert "mx" in codes and codes["mx"]["status"] == "planned"

    mx = get_country_pack("mx")
    assert mx.currency == "MXN"


def test_country_pack_endpoints_http_200():
    app = create_app()
    client = app.test_client()

    r_list = client.get("/api/country-packs")
    assert r_list.status_code == 200
    assert r_list.get_json()["success"] is True

    r_co = client.get("/api/country-packs/co")
    assert r_co.status_code == 200
    assert len(r_co.get_json()["data"]["cities"]) == 33

    r_cities = client.get("/api/country-packs/co/cities?q=medell")
    assert r_cities.status_code == 200
    assert r_cities.get_json()["count"] == 1
    assert r_cities.get_json()["data"][0]["divipola_code"] == "05001"

    r_strata = client.get("/api/country-packs/co/strata")
    assert r_strata.status_code == 200
    assert r_strata.get_json()["count"] == 7

    r_404 = client.get("/api/country-packs/zz")
    assert r_404.status_code == 404


def test_project_from_dict_legacy_backward_compatible():
    legacy_payload = {
        "project_id": "proj_legacy_01",
        "name": "Legacy Project",
        "status": "graph_completed",
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
    }
    proj = Project.from_dict(legacy_payload)
    assert proj.project_id == "proj_legacy_01"
    assert proj.country_code == "co"
    assert proj.target_cities == []
    assert proj.target_strata == []
    assert proj.quant_store_path is None
    assert proj.extraction_audit is None
