"""Colombian business fixtures & dynamic PyMuPDF builders for Prospéctica E2E tests.

Provides:
- Read-only loader for the real COFRE fixture (`proj_9972d0d47dbc`).
- Dynamic PyMuPDF (`fitz`) UTF-8 PDF builders for diverse Colombian businesses
  and edge-case inputs (boilerplate prompts, micro/high COP tickets, accents,
  long titles, minimal/noisy PDFs).
"""

from __future__ import annotations

import html
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import fitz  # PyMuPDF

REPO_ROOT = Path(__file__).resolve().parents[3]
COFRE_SOURCE_DIR = REPO_ROOT / "backend" / "uploads" / "projects" / "proj_9972d0d47dbc"
COFRE_SOURCE_PDF = COFRE_SOURCE_DIR / "files" / "d5165656.pdf"
COFRE_SOURCE_PROJECT_JSON = COFRE_SOURCE_DIR / "project.json"


@dataclass(frozen=True)
class ColombianBusinessFixture:
    """Self-contained opaque-box input bundle for a Colombian market study."""

    key: str
    expected_name: str
    expected_slug: str
    pdf_filename: str
    pdf_bytes: bytes
    simulation_requirement: str
    country_code: str
    target_cities: List[str]
    target_strata: List[str]
    expected_min_cop: int
    expected_max_cop: int
    domain_keywords: List[str]
    forbidden_cross_keywords: List[str]
    explicit_project_name: Optional[str] = None


def build_pdf_bytes(title: str, paragraphs: List[str]) -> bytes:
    """Render a clean UTF-8 PDF in memory via PyMuPDF `insert_htmlbox`."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    safe_title = html.escape(title)
    body_html = "".join(f"<p style='font-size:11pt; line-height:1.4;'>{html.escape(p)}</p>" for p in paragraphs)
    full_html = (
        "<div style='font-family: sans-serif; color: #111;'>"
        f"<h1 style='font-size:16pt; margin-bottom:12px;'>{safe_title}</h1>"
        f"{body_html}"
        "</div>"
    )
    rect = fitz.Rect(48, 48, 547, 794)
    page.insert_htmlbox(rect, full_html)
    try:
        return doc.tobytes()
    finally:
        doc.close()


def build_5block_prompt(
    brand_name: str,
    sector_desc: str,
    idea_summary: str,
    price_text: str,
    competitors_text: str,
    regulations_text: str,
    extra_footer: str = "",
) -> str:
    """Build a 5-block Prospéctica validation prompt matching real Home uploads."""
    return (
        "BLOQUE 1 - ROL Y MISION\r\n"
        f"Actua como un analista senior de investigacion de mercados y validacion de startups, "
        f"especializado en {sector_desc}, con Colombia como mercado inicial. "
        f"Tu mision: investigar el mercado de {brand_name} y disenar un plan de validacion que permita "
        "decidir si la idea debe avanzar, pivotar o detenerse. Usa busqueda web para apoyar cada afirmacion en fuentes verificables.\r\n\r\n"
        f"BLOQUE 2 - CONTEXTO DE LA IDEA ({brand_name})\r\n"
        f"{idea_summary} Estructura de precios evaluada: {price_text}.\r\n\r\n"
        "BLOQUE 3 - TAREAS DE INVESTIGACION DE MERCADO\r\n"
        f"Estima TAM/SAM/SOM en Colombia, analiza competidores como {competitors_text}, "
        f"y revisa el marco regulatorio aplicable ({regulations_text}).\r\n\r\n"
        "BLOQUE 4 - TAREAS DE VALIDACION DE LA IDEA\r\n"
        "Define 3 hipotesis criticas, buyer personas colombianos y experimentos rapidos de traccion.\r\n\r\n"
        "BLOQUE 5 - FORMATO DE SALIDA Y REGLAS\r\n"
        f"Responde en espanol con cifras en COP y USD, y veredicto AVANZAR / PIVOTAR / DETENER. {extra_footer}".strip()
    )


def load_cofre_fixture(tmp_path: Path) -> ColombianBusinessFixture:
    """Read-only loader copying `d5165656.pdf` into `tmp_path` and reading `project.json`."""
    assert COFRE_SOURCE_PDF.exists(), f"Missing COFRE reference PDF: {COFRE_SOURCE_PDF}"
    assert COFRE_SOURCE_PROJECT_JSON.exists(), f"Missing COFRE project.json: {COFRE_SOURCE_PROJECT_JSON}"

    dest_pdf = tmp_path / "COFRE_Descripcion_y_Prompt_Validacion.pdf"
    shutil.copyfile(COFRE_SOURCE_PDF, dest_pdf)
    pdf_bytes = dest_pdf.read_bytes()

    proj_meta = json.loads(COFRE_SOURCE_PROJECT_JSON.read_text(encoding="utf-8"))
    sim_req = str(proj_meta["simulation_requirement"])

    return ColombianBusinessFixture(
        key="cofre",
        expected_name="COFRE",
        expected_slug="cofre",
        pdf_filename="COFRE_Descripcion_y_Prompt_Validacion.pdf",
        pdf_bytes=pdf_bytes,
        simulation_requirement=sim_req,
        country_code=str(proj_meta.get("country_code") or "co"),
        target_cities=list(proj_meta.get("target_cities") or ["Bogotá", "Medellín", "Cali", "Barranquilla", "Cartagena", "Bucaramanga"]),
        target_strata=list(proj_meta.get("target_strata") or ["E1", "E2", "E3", "E4"]),
        expected_min_cop=1000,
        expected_max_cop=250_000,
        domain_keywords=["cofre", "comercio social", "pago protegido", "social finder", "vendedor", "comprador"],
        forbidden_cross_keywords=["Conductor_Movilidad", "Decreto 196/1971", "Miscelánea La Esperanza", "AgroCafé", "RutaFácil"],
        explicit_project_name=None,
    )


def build_miscelanea_esperanza_fixture() -> ColombianBusinessFixture:
    """Scenario 2: Neighborhood variety/stationery shop in Bogotá (micro-tickets COP 2,000-20,000)."""
    title = "Miscelánea La Esperanza — Papelería, Dulcería y Fotocopias de Barrio en Bogotá"
    paragraphs = [
        "Miscelánea La Esperanza es un comercio minorista de barrio ubicado en la localidad de Kennedy, Bogotá D.C.",
        "Atiende familias, estudiantes de colegio y vecinos de estratos E2 y E3 con útiles escolares, impresiones a color, recargas, papelería básica, snacks y detalles de regalo.",
        "Precios típicos de venta al detal: fotocopias e impresiones desde COP 2.000, combos escolares básicos COP 5.000, útiles y papelería COP 10.000, anchetas pequeñas COP 15.000 y paquetes familiares COP 20.000.",
        "Costo variable promedio por pedido: COP 2.800. Arriendo local de barrio y servicios públicos mensuales estimados en COP 1.400.000.",
        "Competencia directa: papelerías de esquina, tiendas de barrio, Dollarcity y supermercados locales.",
        "Canales clave: venta presencial en mostrador, pedidos por WhatsApp del barrio, grupos de Facebook vecinales y voz a voz.",
        "Riesgos y objeciones frecuentes: sensibilidad al precio frente a cadenas de descuento, fiado informal en efectivo y falta de pago con Nequi o Daviplata.",
        "Marco normativo aplicable: Cámara de Comercio de Bogotá, RUT DIAN régimen simple, Estatuto del Consumidor Ley 1480 de 2011 y factura o soporte POS.",
    ]
    sim_req = build_5block_prompt(
        brand_name="Miscelánea La Esperanza",
        sector_desc="comercio minorista de barrio, papelería y tienda escolar",
        idea_summary="Miscelánea La Esperanza ofrece útiles escolares, impresiones, snacks y recargas por mostrador y WhatsApp vecinal en Kennedy, Bogotá, con combos entre COP 2.000 y COP 20.000.",
        price_text="COP 2.000, COP 5.000, COP 10.000, COP 15.000 y COP 20.000 por compra",
        competitors_text="papelerías vecinales, tiendas de barrio y Dollarcity",
        regulations_text="Ley 1480 de 2011, RUT DIAN y registro mercantil local",
    )
    return ColombianBusinessFixture(
        key="miscelanea_esperanza",
        expected_name="Miscelánea La Esperanza",
        expected_slug="miscelanea_la_esperanza",
        pdf_filename="Miscelanea_La_Esperanza_Bogota.pdf",
        pdf_bytes=build_pdf_bytes(title, paragraphs),
        simulation_requirement=sim_req,
        country_code="co",
        target_cities=["11001"],
        target_strata=["E2", "E3"],
        expected_min_cop=1000,
        expected_max_cop=40_000,
        domain_keywords=["miscelánea", "esperanza", "papelería", "barrio", "kennedy", "útiles", "nequi"],
        forbidden_cross_keywords=["COFRE", "SOCIAL FINDER", "escrow", "Conductor_Movilidad", "Decreto 196/1971", "aseguradora"],
    )


def build_nexo_legal_vial_fixture() -> ColombianBusinessFixture:
    """Scenario 3: NEXO Asistencia Legal Vial (6 cities, tickets COP 35,000-140,000)."""
    title = "NEXO Asistencia Legal Vial — Orientación Jurídica y Reclamaciones de Tránsito en Colombia"
    paragraphs = [
        "NEXO Asistencia Legal Vial brinda orientación jurídica inicial y gestión documental ante reclamaciones de accidentes de tránsito, SOAT y pólizas todo riesgo en 6 ciudades de Colombia.",
        "Escalones de tarifa evaluados para consulta y diagnóstico de expediente vial: COP 35.000, COP 50.000, COP 70.000, COP 100.000 y COP 140.000.",
        "Costo variable de revisión jurídica inicial estimado en COP 18.000 por expediente. OPEX mensual operativo proyectado en COP 4.200.000.",
        "Actores clave: conductores particulares, motociclistas, propietarios de vehículos, abogados litigantes y aseguradoras.",
        "Competencia y alternativas: arreglo directo tras choque, tramitadores informales y abogados independientes.",
        "Regulación aplicable: Decreto 196 de 1971 (ejercicio de la abogacía), Ley 1581 de 2012 (Habeas Data) y Ley 1480 de 2011.",
    ]
    sim_req = build_5block_prompt(
        brand_name="NEXO Asistencia Legal Vial",
        sector_desc="servicios jurídicos de movilidad, reclamaciones viales y seguros",
        idea_summary="NEXO Asistencia Legal Vial ofrece diagnóstico de reclamaciones de tránsito y acompañamiento documental frente a aseguradoras en Bogotá, Medellín, Cali, Barranquilla, Bucaramanga y Cartagena.",
        price_text="COP 35.000, COP 50.000, COP 70.000, COP 100.000 y COP 140.000",
        competitors_text="arreglo directo, tramitadores y firmas tradicionales",
        regulations_text="Decreto 196/1971, Ley 1581 de 2012 y Ley 1480 de 2011",
    )
    return ColombianBusinessFixture(
        key="nexo_legal_vial",
        expected_name="NEXO Asistencia Legal Vial",
        expected_slug="nexo_asistencia_legal_vial",
        pdf_filename="NEXO_Asistencia_Legal_Vial.pdf",
        pdf_bytes=build_pdf_bytes(title, paragraphs),
        simulation_requirement=sim_req,
        country_code="co",
        target_cities=["11001", "05001", "76001", "08001", "68001", "13001"],
        target_strata=["E3", "E4", "E5"],
        expected_min_cop=25_000,
        expected_max_cop=180_000,
        domain_keywords=["nexo", "reclamaciones", "vial", "tránsito", "jurídica"],
        forbidden_cross_keywords=["COFRE", "SOCIAL FINDER", "escrow", "Miscelánea La Esperanza", "papelería", "odontología"],
    )


def build_agrocafe_tolima_fixture() -> ColombianBusinessFixture:
    """Scenario 4: AgroCafé Origen Tolima (specialty coffee B2B2C, COP 28,000-95,000)."""
    title = "AgroCafé Origen Tolima — Café Especial Tostado en Origen B2B2C"
    paragraphs = [
        "AgroCafé Origen Tolima es una cooperativa de caficultores de Ibagué y Líbano (Tolima) que comercializa café especial tostado de altura directamente a cafeterías de especialidad y consumidores finales.",
        "Presentaciones y precios evaluados: bolsa de 250g COP 28.000, bolsa de 500g COP 48.000, kit degustación COP 65.000, suscripción mensual 1kg COP 80.000 y lote institucional 2kg COP 95.000.",
        "Costo variable de tueste, empaque valvulado y envío: COP 16.500 por pedido. OPEX mensual de planta tostadora cooperativa: COP 3.200.000.",
        "Actores: caficultores del Tolima, baristas independientes, dueños de cafeterías en Bogotá y Medellín, y compradores gourmet.",
        "Riesgos y objeciones: variabilidad de cosecha por clima, tiempos de logística para preservar frescura de tueste y competencia de marcas comerciales.",
        "Regulación: registro sanitario INVIMA para alimentos tostados, Federación Nacional de Cafeteros y Ley 1480 de 2011.",
    ]
    sim_req = build_5block_prompt(
        brand_name="AgroCafé Origen Tolima",
        sector_desc="agroindustria de café especial colombiano B2B2C",
        idea_summary="AgroCafé Origen Tolima conecta caficultores del Tolima con cafeterías y hogares en Colombia mediante bolsas y suscripciones de café recién tostado.",
        price_text="COP 28.000, COP 48.000, COP 65.000, COP 80.000 y COP 95.000",
        competitors_text="Juan Valdez, Pergamino, Amor Perfecto y tostadores artesanales",
        regulations_text="Registro INVIMA, normativa agrícola ICA/FNC y Ley 1480 de 2011",
    )
    return ColombianBusinessFixture(
        key="agrocafe_tolima",
        expected_name="AgroCafé Origen Tolima",
        expected_slug="agrocafe_origen_tolima",
        pdf_filename="AgroCafe_Origen_Tolima.pdf",
        pdf_bytes=build_pdf_bytes(title, paragraphs),
        simulation_requirement=sim_req,
        country_code="co",
        target_cities=["73001", "11001", "05001", "66001"],
        target_strata=["E3", "E4", "E5"],
        expected_min_cop=20_000,
        expected_max_cop=120_000,
        domain_keywords=["agrocafé", "café", "tolima", "tostado", "invima", "cosecha"],
        forbidden_cross_keywords=["COFRE", "NEXO", "escrow", "Conductor_Movilidad", "Decreto 196/1971", "aseguradora"],
    )


def build_clinica_dental_fixture() -> ColombianBusinessFixture:
    """Scenario 5: Clínica Dental Sonrisa Bogotá (private dentistry, E3-E5, COP 90,000-450,000)."""
    title = "Clínica Dental Sonrisa Bogotá — Odontología Preventiva y Alineadores"
    paragraphs = [
        "Clínica Dental Sonrisa Bogotá ofrece valoraciones integrales, higiene ultrasónica, blanqueamiento clínico y planes de alineadores transparentes en Chapinero y Usaquén, Bogotá.",
        "Escalones tarifarios evaluados: valoración + profilaxis COP 90.000, paquete preventivo familiar COP 150.000, blanqueamiento LED COP 240.000, estudio 3D ortodoncia COP 340.000 y cuota inicial de alineadores COP 450.000.",
        "Costo variable de insumos clínicos y honorarios por cita: COP 52.000. Arriendo de consultorio habilitado y esterilización mensual: COP 6.800.000.",
        "Actores: pacientes adultos E3-E5, familias jóvenes, odontólogos especialistas y auxiliares de salud oral.",
        "Objeciones frecuentes: temor a dolor o cobros ocultos en tratamientos, tiempos de espera y comparación frente a EPS o medicina prepagada.",
        "Marco regulatorio: habilitación sanitaria Secretaría de Salud de Bogotá (Resolución 3100), historia clínica y Ley 1581 de Habeas Data sensible.",
    ]
    sim_req = build_5block_prompt(
        brand_name="Clínica Dental Sonrisa Bogotá",
        sector_desc="salud oral y odontología privada estética y preventiva",
        idea_summary="Clínica Dental Sonrisa Bogotá presta servicios de odontología preventiva y ortodoncia transparente con precios transparentes en Bogotá.",
        price_text="COP 90.000, COP 150.000, COP 240.000, COP 340.000 y COP 450.000",
        competitors_text="Dentix, Sonría, odontólogos independientes y planes prepagados",
        regulations_text="Resolución 3100 habilitación sanitaria, Secretaría de Salud y Ley 1581 datos de salud",
    )
    return ColombianBusinessFixture(
        key="clinica_dental",
        expected_name="Clínica Dental Sonrisa Bogotá",
        expected_slug="clinica_dental_sonrisa_bogota",
        pdf_filename="Clinica_Dental_Sonrisa_Bogota.pdf",
        pdf_bytes=build_pdf_bytes(title, paragraphs),
        simulation_requirement=sim_req,
        country_code="co",
        target_cities=["11001"],
        target_strata=["E3", "E4", "E5"],
        expected_min_cop=70_000,
        expected_max_cop=550_000,
        domain_keywords=["clínica", "dental", "sonrisa", "odontología", "pacientes", "habilitación"],
        forbidden_cross_keywords=["COFRE", "NEXO", "escrow", "Conductor_Movilidad", "Decreto 196/1971", "choque"],
    )


def build_rutafacil_saas_fixture() -> ColombianBusinessFixture:
    """Scenario 6: RutaFácil Logística SaaS (B2B SME fleets in Colombia, COP 180,000-650,000/month)."""
    title = "RutaFácil Logística SaaS — Optimización B2B de Última Milla para Pymes en Colombia"
    paragraphs = [
        "RutaFácil Logística SaaS es una plataforma B2B por suscripción mensual diseñada para pymes distribuidoras en Bogotá, Medellín, Cali y Barranquilla que gestionan entre 3 y 30 vehículos de reparto.",
        "Planes mensuales evaluados: Plan Inicial COP 180.000/mes, Plan Pyme COP 280.000/mes, Plan Flota COP 390.000/mes, Plan Multi-bodega COP 520.000/mes y Plan Empresarial COP 650.000/mes.",
        "Costo variable cloud, mapas GPS y mensajería WhatsApp por cliente activo: COP 42.000/mes. OPEX mensual de ingeniería y soporte: COP 9.500.000.",
        "Actores clave: gerentes de operaciones, jefes de logística pyme, despachadores y conductores de entrega.",
        "Competencia: hojas de Excel manuales, SimpliRoute, Driv.in y ERP locales.",
        "Regulación: facturación electrónica DIAN, Ley 1581 de 2012 (datos de clientes finales) y contratos SaaS B2B.",
    ]
    sim_req = build_5block_prompt(
        brand_name="RutaFácil Logística SaaS",
        sector_desc="software B2B SaaS de logística y última milla para pymes",
        idea_summary="RutaFácil Logística SaaS optimiza rutas de despacho, trazabilidad GPS y pruebas de entrega para distribuidoras pymes en Colombia mediante suscripción mensual.",
        price_text="COP 180.000, COP 280.000, COP 390.000, COP 520.000 y COP 650.000 mensuales",
        competitors_text="Excel manual, SimpliRoute y Driv.in",
        regulations_text="Facturación electrónica DIAN, Ley 1581 de 2012 y términos de servicio SaaS",
    )
    return ColombianBusinessFixture(
        key="rutafacil_saas",
        expected_name="RutaFácil Logística SaaS",
        expected_slug="rutafacil_logistica_saas",
        pdf_filename="RutaFacil_Logistica_SaaS.pdf",
        pdf_bytes=build_pdf_bytes(title, paragraphs),
        simulation_requirement=sim_req,
        country_code="co",
        target_cities=["11001", "05001", "76001", "08001"],
        target_strata=["E3", "E4", "E5"],
        expected_min_cop=140_000,
        expected_max_cop=800_000,
        domain_keywords=["rutafácil", "logística", "saas", "flota", "pymes", "rutas"],
        forbidden_cross_keywords=["COFRE", "NEXO", "escrow", "Conductor_Movilidad", "Decreto 196/1971", "aseguradora"],
    )


def build_edge_micro_ticket_fixture() -> ColombianBusinessFixture:
    """Edge Case: Micro-ticket neighborhood empanada stand (COP 1,500-8,000)."""
    title = "Empanadas Doña Luz — Puesto de Comida Rápida Artesanal"
    paragraphs = [
        "Empanadas Doña Luz vende empanadas de iglesia, papas rellenas y ají casero en Envigado.",
        "Precios evaluados: unidad COP 1.500, combo de 2 COP 3.000, combo con gaseosa COP 5.000, caja x6 COP 8.000 y bandeja x10 COP 12.000.",
        "Costo unitario de ingredientes COP 750. Arriendo de punto ambulante COP 450.000/mes.",
    ]
    sim_req = (
        "Validar precios y demanda local de Empanadas Doña Luz en Envigado con tickets entre "
        "COP 1.500 y COP 12.000 por compra."
    )
    return ColombianBusinessFixture(
        key="empanadas_dona_luz",
        expected_name="Empanadas Doña Luz",
        expected_slug="empanadas_dona_luz",
        pdf_filename="Empanadas_Dona_Luz.pdf",
        pdf_bytes=build_pdf_bytes(title, paragraphs),
        simulation_requirement=sim_req,
        country_code="co",
        target_cities=["05001"],
        target_strata=["E2", "E3"],
        expected_min_cop=1000,
        expected_max_cop=20_000,
        domain_keywords=["empanadas", "doña luz", "envigado"],
        forbidden_cross_keywords=["COFRE", "NEXO", "Decreto 196/1971", "Conductor_Movilidad"],
    )


def build_edge_high_ticket_b2b_fixture() -> ColombianBusinessFixture:
    """Edge Case: High-ticket B2B industrial machinery (COP 2,000,000 - 10,000,000)."""
    title = "Maquinaria Andina S.A.S. — Automatización Agroindustrial"
    paragraphs = [
        "Maquinaria Andina S.A.S. fabrica e instala líneas semiautomáticas de empaque para plantas de alimentos en Cundinamarca y Valle del Cauca.",
        "Planes de mantenimiento y módulos de contrato: COP 2.000.000, COP 3.500.000, COP 5.000.000, COP 7.500.000 y COP 10.000.000.",
        "Costo variable de instalación y repuestos COP 1.800.000. OPEX mensual de taller e ingeniería COP 24.000.000.",
    ]
    sim_req = (
        "Evaluar adopción B2B y disposición a pagar para Maquinaria Andina S.A.S. "
        "en contratos entre COP 2.000.000 y COP 10.000.000."
    )
    return ColombianBusinessFixture(
        key="maquinaria_andina",
        expected_name="Maquinaria Andina S.A.S.",
        expected_slug="maquinaria_andina_sas",
        pdf_filename="Maquinaria_Andina.pdf",
        pdf_bytes=build_pdf_bytes(title, paragraphs),
        simulation_requirement=sim_req,
        country_code="co",
        target_cities=["11001", "76001"],
        target_strata=["E4", "E5", "E6"],
        expected_min_cop=1_000_000,
        expected_max_cop=15_000_000,
        domain_keywords=["maquinaria", "andina", "empaque", "agroindustrial"],
        forbidden_cross_keywords=["COFRE", "NEXO", "Decreto 196/1971", "Conductor_Movilidad"],
    )


def build_edge_special_chars_fixture(
    brand_name: str = "Panadería & Café El Trébol S.A.S.",
    expected_slug: str = "panaderia_cafe_el_trebol_sas",
) -> ColombianBusinessFixture:
    """Edge Case: Accents, ampersand, legal suffix, or regex meta-characters in brand name."""
    title = f"{brand_name} — Estudio de Mercado en Colombia"
    paragraphs = [
        f"{brand_name} ofrece productos artesanales y servicios especializados en Bogotá y Medellín.",
        "Rango de precios evaluados: COP 12.000, COP 18.000, COP 25.000, COP 35.000 y COP 45.000.",
        "Costo variable unitario COP 7.500. Canales: tienda física, WhatsApp y domicilios locales.",
    ]
    sim_req = build_5block_prompt(
        brand_name=brand_name,
        sector_desc="panadería artesanal y cafetería local",
        idea_summary=f"{brand_name} vende pan de masa madre, café filtrado y desayunos corporativos en Bogotá.",
        price_text="COP 12.000, COP 18.000, COP 25.000, COP 35.000 y COP 45.000",
        competitors_text="panaderías tradicionales y Tostao",
        regulations_text="INVIMA y Ley 1480 de 2011",
    )
    return ColombianBusinessFixture(
        key="special_chars",
        expected_name=brand_name,
        expected_slug=expected_slug,
        pdf_filename="Especial_Brand.pdf",
        pdf_bytes=build_pdf_bytes(title, paragraphs),
        simulation_requirement=sim_req,
        country_code="co",
        target_cities=["11001", "05001"],
        target_strata=["E3", "E4"],
        expected_min_cop=8000,
        expected_max_cop=60_000,
        domain_keywords=["panadería", "café", "trébol"],
        forbidden_cross_keywords=["COFRE", "NEXO", "Decreto 196/1971"],
    )


def build_edge_minimal_noisy_fixture() -> ColombianBusinessFixture:
    """Edge Case: Minimal 2-sentence prompt + noisy/unstructured PDF without explicit prices."""
    title = "Taller Mecánico El Rayo"
    paragraphs = [
        "Taller Mecánico El Rayo   repara   frenos y suspensión   en Cali   sin precios publicados   en este volante.",
    ]
    sim_req = "Evaluar demanda de Taller Mecánico El Rayo en Cali. Determinar aceptación de mantenimiento preventivo."
    return ColombianBusinessFixture(
        key="minimal_noisy",
        expected_name="Taller Mecánico El Rayo",
        expected_slug="taller_mecanico_el_rayo",
        pdf_filename="Taller_El_Rayo.pdf",
        pdf_bytes=build_pdf_bytes(title, paragraphs),
        simulation_requirement=sim_req,
        country_code="co",
        target_cities=["76001"],
        target_strata=["E2", "E3"],
        expected_min_cop=1000,
        expected_max_cop=5_000_000,
        domain_keywords=["taller", "mecánico", "frenos", "cali"],
        forbidden_cross_keywords=["COFRE", "NEXO", "Decreto 196/1971", "Conductor_Movilidad"],
    )


ALL_SCENARIO_FACTORIES = [
    ("cofre", load_cofre_fixture),
    ("miscelanea_esperanza", lambda _tmp: build_miscelanea_esperanza_fixture()),
    ("nexo_legal_vial", lambda _tmp: build_nexo_legal_vial_fixture()),
    ("agrocafe_tolima", lambda _tmp: build_agrocafe_tolima_fixture()),
    ("clinica_dental", lambda _tmp: build_clinica_dental_fixture()),
    ("rutafacil_saas", lambda _tmp: build_rutafacil_saas_fixture()),
]
