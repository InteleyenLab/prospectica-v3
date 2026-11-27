"""Endpoints REST para consultar paquetes de país, ciudades y estratos socioeconómicos."""

from flask import jsonify, request

from . import country_packs_bp
from country_packs import get_country_pack, list_country_packs


@country_packs_bp.route("", methods=["GET"])
def get_all_country_packs():
    """Lista los paquetes de país disponibles."""
    packs = list_country_packs()
    return jsonify({"success": True, "data": packs, "count": len(packs)})


@country_packs_bp.route("/<iso2>", methods=["GET"])
def get_single_country_pack(iso2: str):
    """Obtiene el resumen completo de un paquete de país."""
    try:
        pack = get_country_pack(iso2)
    except FileNotFoundError:
        return jsonify({"success": False, "error": f"País '{iso2}' no soportado"}), 404

    return jsonify(
        {
            "success": True,
            "data": {
                "country_code": pack.country_code,
                "country_name": pack.country_name,
                "status": pack.status,
                "currency": pack.currency,
                "locale": pack.locale,
                "timezone": pack.timezone,
                "min_wage_local": pack.min_wage_local,
                "transport_aid_local": pack.transport_aid_local,
                "min_wage_source": pack.min_wage_source,
                "taxonomy_system": pack.taxonomy_system,
                "cities": [c.model_dump() for c in pack.cities],
                "strata": [s.model_dump() for s in pack.strata],
                "archetypes": [a.model_dump() for a in pack.archetypes],
                "sources": [src.model_dump() for src in pack.sources],
            },
        }
    )


@country_packs_bp.route("/<iso2>/cities", methods=["GET"])
def get_country_cities(iso2: str):
    """Lista las ciudades oficiales disponibles para el país indicado (filtrable con `?q=` o `?region=`)."""
    try:
        pack = get_country_pack(iso2)
    except FileNotFoundError:
        return jsonify({"success": False, "error": f"País '{iso2}' no soportado"}), 404

    q = (request.args.get("q") or "").strip().lower()
    region = (request.args.get("region") or "").strip().lower()
    cities = pack.cities
    if q:
        cities = [
            c
            for c in cities
            if q in c.city_name.lower() or q in c.department.lower() or q in c.divipola_code
        ]
    if region:
        cities = [c for c in cities if region in c.region_macro.lower()]

    return jsonify(
        {
            "success": True,
            "data": [c.model_dump() for c in cities],
            "count": len(cities),
        }
    )


@country_packs_bp.route("/<iso2>/strata", methods=["GET"])
def get_country_strata(iso2: str):
    """Devuelve la taxonomía socioeconómica oficial del país."""
    try:
        pack = get_country_pack(iso2)
    except FileNotFoundError:
        return jsonify({"success": False, "error": f"País '{iso2}' no soportado"}), 404

    return jsonify(
        {
            "success": True,
            "data": [s.model_dump() for s in pack.strata],
            "taxonomy_system": pack.taxonomy_system,
            "count": len(pack.strata),
        }
    )
