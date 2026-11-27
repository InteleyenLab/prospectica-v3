"""Constructor dinámico de StudyContext y extractor de identidad real del proyecto.

Extrae de forma determinística (con enriquecimiento LLM opcional) el nombre real
de la empresa/proyecto y todos los parámetros de negocio en Colombia a partir de
`extracted_text`, `simulation_requirement`, `filenames` y `quant_indicators`.
Generaliza desde una miscelánea de barrio hasta plataformas SaaS o fintech nacionales.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from ..channels.base import CANONICAL_CHANNEL_IDS
from ..config import Config
from ..models.project import ProjectManager
from ..utils.logger import get_logger

logger = get_logger("prospectica.study_context_builder")

_PLACEHOLDER_NAMES = {
    "",
    "unnamed project",
    "proyecto sin titulo",
    "proyecto",
    "new project",
    "sin titulo",
    "untitled",
    "prospectica",
    "prospectica inc.",
    "prospectica inc",
    "estudio de mercado",
    "este servicio o producto",
    "mirofish",
    "n/a",
    "na",
    "none",
    "null",
}

_BOILERPLATE_NAME_PATTERNS = [
    re.compile(r"^bloque\s+\d+", re.IGNORECASE),
    re.compile(r"^(?:servicio|fase|etapa|paso|parte|capitulo|cap[ií]tulo|anexo)\s+[a-z0-9]{1,3}$", re.IGNORECASE),
    re.compile(r"^documento\s+estrat[eé]gico\s+integral", re.IGNORECASE),
    re.compile(r"^versi[oó]n\s+ampliada", re.IGNORECASE),
    re.compile(r"^[•\-*]"),
    re.compile(r"^#+\s*(rol|contexto|objetivo|mercado|reglas|metodolog|formato|autocr[ií]tica)", re.IGNORECASE),
    re.compile(r"^(rol|misi[oó]n|tu\s+misi[oó]n|tarea|contexto|instrucciones|objetivo)\s*:", re.IGNORECASE),
    re.compile(r"^(act[uú]a\s+como|simula\s+y\s+predice|analiza\s+si\s+la\s+idea|vas\s+a\s+simular|dise[nñ]ar\s+un\s+plan|necesito\s+hacer\s+un\s+estudio)", re.IGNORECASE),
    re.compile(r"especializado\s+en", re.IGNORECASE),
    re.compile(r"con\s+colombia\s+como\s+mercado\s+inicial", re.IGNORECASE),
    re.compile(r"permite\s+decidir\s+si\s+la\s+idea|permita\s+decidir\s+si\s+la\s+idea", re.IGNORECASE),
    re.compile(r"avanzar,\s*pivotar\s*o\s*detenerse", re.IGNORECASE),
    re.compile(r"prohibido\s+simular|entrega\s+una\s+fase", re.IGNORECASE),
    re.compile(r"^(?:[a-z]\s+){3,}[a-z](?:\s|$)", re.IGNORECASE),  # banners espaciados tipo D E S C R I P C I O N
    re.compile(r"^p[aá]gina\s+\d+$", re.IGNORECASE),
    re.compile(r"^===.+===$"),
    re.compile(r"^\d+(?:\.\d+)*[.)]\s+"),
    re.compile(r"^(?:plan\s+de\s+negocio|especificaciones\s+de|documento\s+de\s+trabajo)\b", re.IGNORECASE),
    re.compile(r"(?<!\w)(?:y|e|o|u|de|del|para|con|por|en|a|sin|que)$", re.IGNORECASE),
]

_GENERIC_DOC_HEADERS = {
    "documento estrategico integral",
    "documento de proyecto",
    "manual de marca",
    "manual tecnico de marca",
    "guia de marca",
    "descripcion del proyecto",
    "resumen ejecutivo",
    "plan de negocio",
    "plan de negocio aterrizado",
    "tabla de contenido",
    "alcance de esta version",
    "objetivos de la simulacion",
    "introduccion",
    "propuesta de valor",
    "publico objetivo",
    "contexto del negocio",
    "contexto de la idea",
    "prompts y guia de implementacion",
}

_GENERIC_FILENAME_TOKENS = {
    "descripcion",
    "prompt",
    "prompts",
    "validacion",
    "documento",
    "estrategico",
    "integral",
    "version",
    "ampliada",
    "reconstruida",
    "manual",
    "marca",
    "guia",
    "analisis",
    "ia",
    "plan",
    "negocio",
    "final",
    "borrador",
    "v1",
    "v2",
    "v3",
    "source",
    "brief",
    "test",
    "archivo",
    "file",
    "doc",
    "estudio",
    "proyecto",
    "verificacion",
    "reclamaciones",
    "miscelanea",
    "clinica",
    "tienda",
    "restaurante",
    "cafeteria",
    "panaderia",
    "drogueria",
    "ferreteria",
    "academia",
    "consultorio",
    "negocio",
    "local",
    "empresa",
    "colombia",
    "barrio",
    "del",
    "de",
    "la",
    "el",
    "y",
    "en",
    "para",
    "con",
}

_SPANISH_STOPWORDS = {
    "para", "como", "con", "los", "las", "del", "una", "uno", "unos", "unas",
    "que", "por", "sobre", "entre", "desde", "hasta", "cada", "todo", "toda",
    "todos", "todas", "este", "esta", "estos", "estas", "ese", "esa", "esos",
    "pero", "más", "mas", "sin", "nos", "sus", "son", "ser", "fue", "han",
    "hay", "puede", "pueden", "debe", "deben", "tiene", "tienen", "hacer",
    "colombia", "mercado", "estudio", "simulacion", "simulación", "negocio",
    "empresa", "proyecto", "servicio", "servicios", "cliente", "clientes",
    "usuario", "usuarios", "producto", "productos", "personas", "datos",
    "informacion", "información", "proceso", "casos", "caso", "forma",
    "donde", "cuando", "quien", "cual", "cuales", "solo", "también", "tambien",
    "muy", "bien", "aqui", "aquí", "hoy", "paso", "pasos", "nivel", "tipo",
    "bloque", "fase", "reglas", "formato", "objetivo", "mision", "misión",
    "actua", "actúa", "analista", "senior", "investigacion", "investigación",
    "validacion", "validación", "inicial", "ejemplo", "ejemplos", "archivo",
}

_SECTOR_PROFILES: Dict[str, Dict[str, Any]] = {
    "fintech_escrow": {
        "keywords": [
            "fintech", "escrow", "custodia", "pago protegido", "billetera",
            "nequi", "daviplata", "pse", "pasarela", "transaccion", "transacciones",
            "comercio social", "acuerdo", "liberacion del pago", "credito", "microcredito",
            "remesas", "transferencia",
        ],
        "unit_label": "transacciones/mes",
        "price_ladder_cop": [5000, 12000, 25000, 45000, 80000],
        "var_cost_ratio": 0.24,
        "opex_by_scope": {"Barrio / Local": 2_200_000.0, "Ciudad principal": 3_400_000.0, "Colombia nacional": 4_600_000.0, "Colombia y LATAM": 5_400_000.0},
        "roles": ["Comprador_Comercio_Social", "Vendedor_Instagram_WhatsApp", "Emprendedor_Digital", "Comerciante_PyME", "Comprador_Esceptico", "Aliado_Pagos_Digitales"],
        "competitors": ["Transferencia directa Nequi / Daviplata", "Mercado Pago / Pago Protegido", "PayU / Wompi", "Pago contraentrega (COD)"],
        "objections": ["Miedo a que el dinero quede retenido sin respuesta", "Comisión percibida frente a transferencia directa sin costo", "Desconfianza ante plataforma nueva sin respaldo bancario visible", "Fricción del vendedor para adoptar pasos adicionales"],
        "regulatory": ["Superintendencia Financiera de Colombia (SFC) - Custodia de fondos", "UIAF / SARLAFT (Prevención de lavado de activos)", "Ley 1480 de 2011 (Estatuto del Consumidor)", "Ley 1581 de 2012 (Protección de Datos Personales)"],
    },
    "comercio_minorista": {
        "keywords": [
            "miscelanea", "miscelánea", "papeleria", "papelería", "tienda de barrio",
            "minimercado", "supermercado", "ferreteria", "ferretería", "drogueria",
            "droguería", "bazar", "utiles escolares", "útiles escolares", "abarrotes",
            "recargas", "fotocopias", "tienda", "retail", "vecindario", "barrio",
        ],
        "unit_label": "ventas/mes",
        "price_ladder_cop": [2000, 5000, 10000, 15000, 25000],
        "var_cost_ratio": 0.62,
        "opex_by_scope": {"Barrio / Local": 1_450_000.0, "Ciudad principal": 2_400_000.0, "Colombia nacional": 3_800_000.0, "Colombia y LATAM": 4_500_000.0},
        "roles": ["Vecino_Comprador", "Padre_Madre_Familia", "Estudiante_Escolar", "Trabajador_Zona", "Comerciante_Local", "Comprador_Ocasional"],
        "competitors": ["Tiendas D1 / Ara / Ísimo", "Papelerías y misceláneas del sector", "Supermercados de cadena", "Comercio informal de la zona"],
        "objections": ["Precios percibidos más altos que tiendas de descuento D1/Ara", "Falta de medios de pago digitales (Nequi/Daviplata/QR)", "Horario de atención o disponibilidad de inventario", "Preferencia por compra al por mayor en el centro"],
    "regulatory": ["Ley 1480 de 2011 (Estatuto del Consumidor y precios visibles)", "Registro Mercantil Cámara de Comercio y RUT DIAN", "Normativa local de uso de suelo y bomberos", "Ley 1581 de 2012 (Protección de Datos Personales)"],
    },
    "alimentos_bebidas": {
        "keywords": [
            "restaurante", "cafeteria", "cafetería", "panaderia", "panadería",
            "comida", "almuerzo", "bebida", "gastronomia", "gastronomía", "cafe",
            "café", "reposteria", "repostería", "cocina oculta", "dark kitchen",
            "snacks", "menu", "menú", "rappi", "hamburguesa", "arepa",
        ],
        "unit_label": "pedidos/mes",
        "price_ladder_cop": [8000, 15000, 22000, 32000, 48000],
        "var_cost_ratio": 0.52,
        "opex_by_scope": {"Barrio / Local": 1_850_000.0, "Ciudad principal": 2_900_000.0, "Colombia nacional": 4_200_000.0, "Colombia y LATAM": 5_000_000.0},
        "roles": ["Trabajador_Oficina", "Familia_Barrio", "Joven_Universitario", "Cliente_Domicilios", "Comprador_Frecuente", "Cliente_Esceptico_Higiene"],
        "competitors": ["Restaurantes y corrientazos de la zona", "Rappi / Domicilios locales", "Cadenas de comida rápida", "Cocinas ocultas vecinas"],
        "objections": ["Relación porción-precio frente a opciones del sector", "Tiempo de entrega o temperatura del pedido a domicilio", "Consistencia en sabor y estándares de higiene", "Costo adicional de empaque y envío"],
        "regulatory": ["Registro sanitario INVIMA y manipulación de alimentos (Res. 2674/2013)", "Concepto sanitario Secretaría de Salud local", "Ley 1480 de 2011 (Estatuto del Consumidor)", "Ley 1581 de 2012 (Protección de Datos Personales)"],
    },
    "movilidad_seguros": {
        "keywords": [
            "reclamacion", "reclamación", "reclamaciones", "aseguradora", "aseguradoras",
            "poliza", "póliza", "siniestro", "responsabilidad civil", "choque",
            "accidente", "soat", "peritaje", "indemnizacion", "indemnización",
            "orientacion inicial", "acompanamiento y gestion", "nexo",
        ],
        "unit_label": "casos/mes",
        "price_ladder_cop": [35000, 50000, 70000, 100000, 140000],
        "var_cost_ratio": 0.30,
        "opex_by_scope": {"Barrio / Local": 2_200_000.0, "Ciudad principal": 3_200_000.0, "Colombia nacional": 4_200_000.0, "Colombia y LATAM": 4_900_000.0},
        "roles": ["Conductor_Vehiculo_Moto", "Propietario_Inmueble", "Comerciante_Afectado", "Afectado_Siniestro", "Aliado_Taller_Perito", "Cliente_Esceptico_Tramite"],
        "competitors": ["Trámite directo ante aseguradora", "Abogados independientes de tránsito/civil", "Tramitadores informales", "Aseguradora propia / asistencia jurídica"],
        "objections": ["Temor a pagar sin garantía de indemnización", "Creer que el trámite puede hacerse gratis directamente", "Desconfianza por experiencias previas con tramitadores", "Duda sobre límites legales frente a un abogado"],
        "regulatory": ["Decreto 196 de 1971 (Límites al ejercicio de la abogacía)", "Ley 1480 de 2011 (Estatuto del Consumidor y publicidad)", "Ley 1581 de 2012 (Protección de Datos y expedientes)", "Código de Comercio (Contrato de Seguro y prescripción)"],
    },
    "tecnologia_saas": {
        "keywords": [
            "saas", "software", "plataforma web", "aplicacion web", "aplicación web",
            "app", "inteligencia artificial", "prompt", "prompts", "llm", "chatgpt",
            "automatizacion", "automatización", "suscripcion", "suscripción", "api",
            "extension", "extensión", "crm", "erp", "dashboard", "digital",
        ],
        "unit_label": "suscripciones/mes",
        "price_ladder_cop": [19000, 39000, 59000, 99000, 149000],
        "var_cost_ratio": 0.18,
        "opex_by_scope": {"Barrio / Local": 2_000_000.0, "Ciudad principal": 3_200_000.0, "Colombia nacional": 4_400_000.0, "Colombia y LATAM": 5_500_000.0},
        "roles": ["Emprendedor_PyME", "Profesional_Independiente", "Creador_Contenido", "Estudiante_Universitario", "Lider_Equipo_Digital", "Usuario_Esceptico_Pago"],
        "competitors": ["Herramientas gratuitas genéricas (ChatGPT free / hojas de cálculo)", "Alternativas SaaS internacionales en USD", "Plantillas manuales sin automatización", "Consultores o agencias tradicionales"],
        "objections": ["Resistencia a pagar si existe una opción gratuita suficiente", "Curva de aprendizaje o pereza de adoptar una herramienta intermedia", "Preocupación por privacidad de datos cargados", "Fricción con suscripciones recurrentes en tarjeta"],
        "regulatory": ["Ley 1581 de 2012 (Protección de Datos Personales y Habeas Data)", "Ley 527 de 1999 (Comercio electrónico)", "Ley 1480 de 2011 (Estatuto del Consumidor digital)", "Derechos de autor y propiedad intelectual (DNDA)"],
    },
    "salud_bienestar": {
        "keywords": [
            "salud", "clinica", "clínica", "consultorio", "odontologia", "odontología",
            "psicologia", "psicología", "medicina", "telemedicina", "spa", "gimnasio",
            "bienestar", "nutricion", "nutrición", "fisioterapia", "estetica", "estética",
        ],
        "unit_label": "consultas/mes",
        "price_ladder_cop": [40000, 70000, 100000, 150000, 220000],
        "var_cost_ratio": 0.35,
        "opex_by_scope": {"Barrio / Local": 2_100_000.0, "Ciudad principal": 3_400_000.0, "Colombia nacional": 4_600_000.0, "Colombia y LATAM": 5_500_000.0},
        "roles": ["Paciente_Particular", "Adulto_Cuidado_Preventivo", "Madre_Padre_Familia", "Profesional_Estresado", "Usuario_EPS_Insatisfecho", "Paciente_Esceptico"],
        "competitors": ["EPS / Medicina prepagada", "Consultorios particulares de la zona", "Plataformas de telemedicina", "Centros de bienestar y estética"],
        "objections": ["Precio de consulta particular frente a cuota moderadora EPS", "Desconfianza sobre credenciales o habilitación sanitaria", "Disponibilidad de agenda y ubicación", "Temor a costos ocultos de exámenes o sesiones adicionales"],
        "regulatory": ["Resolución 3100 de 2019 (Habilitación de servicios de salud)", "Ley 1581 de 2012 (Historia clínica y datos sensibles)", "Ley 1480 de 2011 (Publicidad e información en salud)", "Secretaría de Salud / Ministerio de Salud"],
    },
    "educacion_formacion": {
        "keywords": [
            "educacion", "educación", "academia", "curso", "cursos", "colegio",
            "universidad", "tutoria", "tutoría", "capacitacion", "capacitación",
            "preicfes", "ingles", "inglés", "bootcamp", "taller", "formacion", "formación",
        ],
        "unit_label": "inscripciones/mes",
        "price_ladder_cop": [30000, 60000, 110000, 180000, 280000],
        "var_cost_ratio": 0.28,
        "opex_by_scope": {"Barrio / Local": 1_700_000.0, "Ciudad principal": 2_800_000.0, "Colombia nacional": 3_900_000.0, "Colombia y LATAM": 4_800_000.0},
        "roles": ["Estudiante_Universitario", "Profesional_Recalificacion", "Padre_Madre_Familia", "Emprendedor_Aprendiz", "Docente_Aliado", "Estudiante_Esceptico"],
        "competitors": ["Cursos gratuitos en YouTube / Coursera", "SENA / universidades tradicionales", "Academias locales e institutos", "Tutores particulares"],
        "objections": ["Disponibilidad de contenido gratuito en internet", "Duda sobre retorno laboral o certificación válida", "Falta de tiempo para completar el programa", "Capacidad de pago mensual o deserción"],
        "regulatory": ["Ley 115 de 1994 / Educación informal (Decreto 1075 de 2015)", "Ley 1480 de 2011 (Estatuto del Consumidor educativo)", "Ley 1581 de 2012 (Protección de Datos Personales)", "Secretaría de Educación (si aplica formación formal)"],
    },
    "logistica_domicilios": {
        "keywords": [
            "logistica", "logística", "mensajeria", "mensajería", "envios", "envíos",
            "encomienda", "domicilio", "domicilios", "ultima milla", "última milla",
            "paqueteria", "paquetería", "transporte", "carga", "bodega",
        ],
        "unit_label": "envíos/mes",
        "price_ladder_cop": [6000, 10000, 15000, 24000, 38000],
        "var_cost_ratio": 0.55,
        "opex_by_scope": {"Barrio / Local": 1_650_000.0, "Ciudad principal": 2_900_000.0, "Colombia nacional": 4_500_000.0, "Colombia y LATAM": 5_600_000.0},
        "roles": ["Comerciante_Ecommerce", "Tienda_Social_Commerce", "Comprador_Final", "Mensajero_Aliado", "PyME_Distribuidora", "Cliente_Urgente"],
        "competitors": ["Servientrega / Interrapidísimo / Coordinadora", "Mensajeros urbanos independientes", "RappiFavor / Picap / InDrive envíos", "Flota propia del comercio"],
        "objections": ["Riesgo de pérdida, daño o demora en la entrega", "Costo del flete frente al ticket del producto", "Falta de trazabilidad en tiempo real", "Comisiones de recaudo contraentrega"],
        "regulatory": ["Ministerio de Transporte y regulación de carga/mensajería", "Ley 1369 de 2009 (Servicios postales cuando aplique)", "Ley 1480 de 2011 (Estatuto del Consumidor)", "Ley 1581 de 2012 (Protección de Datos)"],
    },
    "servicios_legales": {
        "keywords": [
            "abogado", "abogados", "bufete", "juridico", "jurídico", "derecho",
            "tutela", "contrato", "contratos", "notaria", "notaría", "asesoria legal",
            "asesoría legal", "decreto 196", "conciliacion", "demanda",
        ],
        "unit_label": "casos/mes",
        "price_ladder_cop": [60000, 120000, 200000, 350000, 600000],
        "var_cost_ratio": 0.28,
        "opex_by_scope": {"Barrio / Local": 2_000_000.0, "Ciudad principal": 3_100_000.0, "Colombia nacional": 4_200_000.0, "Colombia y LATAM": 5_000_000.0},
        "roles": ["Ciudadano_Consultante", "PyME_Empresario", "Persona_Con_Conflicto", "Cliente_Preventivo", "Abogado_Aliado", "Cliente_Esceptico_Honorarios"],
        "competitors": ["Consultorios jurídicos universitarios gratuitos", "Abogados independientes tradicionales", "Legaltech de plantillas digitales", "Cámaras de Comercio / conciliación"],
        "objections": ["Incertidumbre sobre duración y costo total del proceso", "Desconfianza en honorarios por adelantado", "Creencia de poder radicar trámites sin asesoría", "Falta de claridad en lenguaje jurídico"],
        "regulatory": ["Decreto 196 de 1971 y Ley 1123 de 2007 (Ejercicio de la abogacía)", "Ley 1581 de 2012 (Confidencialidad y datos personales)", "Ley 1480 de 2011 (Información transparente de honorarios)"],
    },
    "servicios_profesionales": {
        "keywords": [
            "consultoria", "consultoría", "agencia", "diseno", "diseño", "contabilidad",
            "marketing", "asesoria", "asesoría", "freelance", "servicio tecnico",
            "servicio técnico", "mantenimiento", "reparacion", "reparación", "taller",
        ],
        "unit_label": "servicios/mes",
        "price_ladder_cop": [45000, 85000, 140000, 220000, 350000],
        "var_cost_ratio": 0.34,
        "opex_by_scope": {"Barrio / Local": 1_800_000.0, "Ciudad principal": 2_900_000.0, "Colombia nacional": 4_000_000.0, "Colombia y LATAM": 4_900_000.0},
        "roles": ["Emprendedor_PyME", "Cliente_Hogar", "Gerente_Area", "Comprador_Recurrente", "Referido_Local", "Cliente_Esceptico"],
        "competitors": ["Freelancers independientes", "Agencias o talleres establecidos", "Solución interna (hazlo tú mismo)", "Plataformas de servicios por demanda"],
        "objections": ["Comparación de precio con oferta informal", "Duda sobre tiempos de entrega y garantía del servicio", "Falta de portafolio o casos verificables", "Comunicación poco clara sobre entregables"],
        "regulatory": ["Ley 1480 de 2011 (Estatuto del Consumidor y garantías)", "Ley 1581 de 2012 (Protección de Datos Personales)", "Código de Comercio y facturación electrónica DIAN"],
    },
}

_DEFAULT_SECTOR = "servicios_profesionales"


def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def slugify_project_name(name: str) -> str:
    """Convierte el nombre del proyecto a un slug seguro para rutas y archivos."""
    ascii_norm = _strip_accents(name or "").lower()
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_norm).strip("_")
    if len(slug) > 64:
        slug = slug[:64].strip("_")
    return slug or "proyecto_estudio"


def is_placeholder_project_name(name: Optional[str]) -> bool:
    """Determina si un nombre es un marcador vacío, URL o fragmento de prompt."""
    if not name:
        return True
    cleaned = re.sub(r"\s+", " ", str(name)).strip()
    if len(cleaned) < 2:
        return True
    norm = _strip_accents(cleaned).lower()
    if norm in _PLACEHOLDER_NAMES:
        return True
    if norm in _GENERIC_DOC_HEADERS:
        return True
    if norm.startswith(("http://", "https://", "www.")):
        return True
    if any(pat.search(cleaned) for pat in _BOILERPLATE_NAME_PATTERNS):
        return True
    if len(cleaned) > 150:
        return True
    return False


_ABBREV_BEFORE_DOT = {
    "dr", "dra", "sr", "sra", "ing", "lic", "st", "prof", "arq", "abg",
    "ltda", "cia", "cía", "inc", "corp", "s.a.s", "s.a",
}

_PRESERVE_TRAILING_DOT_ABBREV = ("s.a.s.", "s.a.", "ltda.", "inc.", "cia.", "cía.")

_GENERIC_DEFINITIONAL_STARTERS = {
    "la empresa", "esta empresa", "nuestra empresa", "tu empresa",
    "este proyecto", "el proyecto", "nuestro proyecto",
    "el negocio", "este negocio", "nuestro negocio", "tu negocio",
    "la plataforma", "esta plataforma", "nuestra plataforma",
    "el servicio", "este servicio", "nuestro servicio",
    "la marca", "esta marca", "nuestra marca",
    "la iniciativa", "esta iniciativa", "nuestra iniciativa",
    "la compania", "esta compania", "nuestra compania",
    "el sistema", "este sistema", "la solucion", "esta solucion",
    "la herramienta", "esta herramienta", "la aplicacion", "esta aplicacion",
    "el producto", "este producto", "nuestro producto",
    "la app", "esta app", "nuestra app",
    "colombia", "el mercado", "este mercado", "el pais", "la ciudad",
    "el usuario", "el cliente", "los clientes", "las empresas",
    "muchas personas", "esta idea", "la idea", "el equipo", "nuestro equipo",
}


def _split_sentence_preserving_abbrevs(text: str) -> str:
    """Corta en el primer punto de fin de oración sin truncar abreviaturas (Dr., Sr., S.A.S., iniciales)."""
    for m in re.finditer(r"\s*\.\s+(?=[A-ZÁÉÍÓÚÑ])", text):
        prefix = text[: m.start()]
        tok_match = re.search(r"([A-Za-zÁÉÍÓÚÑáéíóúñ.]+)$", prefix)
        if tok_match:
            tok = tok_match.group(1).strip(".")
            tok_low = tok.lower()
            if len(tok) == 1 or tok_low in _ABBREV_BEFORE_DOT:
                continue
        return prefix
    return text


def _clean_candidate_name(raw: str) -> str:
    """Limpia puntuación, paréntesis geográficos y artefactos de un nombre candidato."""
    text = re.sub(r"[*_`\"“”]+", "", raw or "").strip()
    text = re.sub(r"\s+", " ", text)
    # Cortar sufijos tipo ". Lema: ..." o ". Validar ..." o "(Colombia)" o "- Descripción..."
    text = _split_sentence_preserving_abbrevs(text)
    text = re.split(r"\s*\.\s*(?:lema|slogan|descripci[oó]n|prop[oó]sito)\b", text, maxsplit=1, flags=re.IGNORECASE)[0]
    text = re.split(r"\s+[|\-–—]\s+(?:manual|descripci[oó]n|gu[ií]a|documento|plan|prompt|estudio)\b", text, maxsplit=1, flags=re.IGNORECASE)[0]
    text = re.sub(r"\s*\((?:colombia|latam|piloto|mvp|bogot[aá]|medell[ií]n|cali)[^)]*\)\s*$", "", text, flags=re.IGNORECASE)
    preserve_dot = any(text.lower().endswith(abbr) for abbr in _PRESERVE_TRAILING_DOT_ABBREV)
    text = text.strip(" \t\r\n,;:-|–—'\"")
    if not preserve_dot:
        text = text.rstrip(".")
    text = text.strip()

    # Normalizar frases totalmente en mayúsculas de varias palabras (p. ej. NEXO RECLAMACIONES -> NEXO Reclamaciones)
    words = text.split()
    if len(words) >= 2 and text.isupper():
        normalized_words: List[str] = []
        for idx, w in enumerate(words):
            if idx == 0 and len(w) <= 6:
                normalized_words.append(w)
            elif len(w) <= 2 and w.lower() in {"de", "la", "el", "y", "en"}:
                normalized_words.append(w.lower())
            else:
                normalized_words.append(w.capitalize())
        text = " ".join(normalized_words)
    elif len(words) == 1 and text.islower() and len(text) <= 8:
        text = text.upper()
    elif len(words) >= 2 and text.islower():
        text = " ".join(w.lower() if (i > 0 and w in {"de", "la", "el", "y", "en"}) else w.capitalize() for i, w in enumerate(words))

    return text


def _strip_doc_noise_lines(text: str) -> List[str]:
    """Devuelve líneas limpias de un documento excluyendo separadores, paginación y banners espaciados."""
    clean_lines: List[str] = []
    for raw_line in (text or "").splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        if line.startswith("===") and line.endswith("==="):
            continue
        if re.match(r"^p[aá]gina\s+\d+\b", line, re.IGNORECASE):
            continue
        # Banners tipo "D E S C R I P C I O N  D E L  P R O Y E C T O"
        if re.match(r"^(?:[A-ZÁÉÍÓÚÑ0-9]\s+){3,}[A-ZÁÉÍÓÚÑ0-9](?:\s|$)", line):
            continue
        if line in {"---", "***", "___"} or line.startswith("|"):
            continue
        clean_lines.append(line)
    return clean_lines


def _upgrade_short_name_from_text(candidate: str, extracted_text: str) -> str:
    """Si el prompt menciona solo 'nexo' y el PDF contiene 'NEXO Reclamaciones', preserva la forma completa."""
    if not candidate or not extracted_text:
        return candidate
    if len(candidate.split()) == 1 and len(candidate) <= 8:
        pattern = re.compile(
            rf"\b({re.escape(candidate)}(?:[ \t]+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{{3,22}})?)\b"
        )
        matches = pattern.findall(extracted_text)
        # Preferir variante de 2 palabras en la misma línea si no es sustantivo genérico
        skip_second = {
            "es", "se", "en", "para", "como", "tiene", "ofrece", "permite",
            "colombia", "infraestructura", "capa", "sistema", "plataforma", "activo",
        }
        two_word = [
            m for m in matches
            if len(m.split()) == 2 and _strip_accents(m.split()[1]).lower() not in skip_second
        ]
        if two_word:
            return _clean_candidate_name(two_word[0])
        exact_upper = [m for m in matches if m.isupper()]
        if exact_upper:
            return exact_upper[0]
    return candidate


def extract_real_project_name(
    extracted_text: str = "",
    simulation_requirement: str = "",
    filenames: Optional[List[str]] = None,
    project_name_hint: Optional[str] = None,
) -> str:
    """Extrae el nombre real de la empresa, idea o negocio evitando fragmentos de prompt."""
    # 1. Hint explícito del usuario si es válido y no es marcador/boilerplate
    if project_name_hint:
        hint_clean = _clean_candidate_name(project_name_hint)
        if not is_placeholder_project_name(hint_clean):
            return hint_clean[:80]

    req = simulation_requirement or ""
    doc = extracted_text or ""

    # 2. Patrones explícitos en simulation_requirement y extracted_text
    labeled_patterns = [
        re.compile(
            r"(?im)^[ \t]*(?:empresa|negocio|nombre\s+comercial|nombre\s+del?\s+(?:negocio|proyecto|empresa|emprendimiento|local|tienda|marca)|marca|startup|iniciativa|idea|emprendimiento|tienda|miscel[aá]nea|cl[ií]nica|consultorio|restaurante|panader[ií]a|cafeter[ií]a|droguer[ií]a|ferreter[ií]a|academia|taller|veterinaria)\s*:\s*([^\n\r•|]+)"
        ),
        re.compile(
            r"(?i)\b(?:la|el)\s+(?:empresa|negocio|proyecto|marca|local|tienda|panader[ií]a|cafeter[ií]a|restaurante|cl[ií]nica|consultorio|academia|startup|plataforma|app|miscel[aá]nea|ferreter[ií]a|taller|droguer[ií]a|veterinaria)\s+se\s+llama\s+[\"“']?([A-ZÁÉÍÓÚÑa-záéíóúñ0-9][A-Za-zÁÉÍÓÚÑáéíóúñ0-9 \t.&'-]{1,45}?)[\"”']?(?=\s*(?:[,.!;:\n\r]|\by\s+(?:necesito|quiero|vende|ofrece|presta|tiene|est[aá]|repara)|necesito\s+|en\s+colombia|es\s+un|\(|$))"
        ),
        re.compile(r"(?i)contexto\s+de\s+la\s+idea\s*\(([^)\n]{2,50})\)"),
        re.compile(
            r"(?i)\binvestigar\s+el\s+mercado\s+de\s+([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ0-9\s.&'-]{1,40}?)(?=\s+(?:y\s+dise[nñ]|y\s+evalu|en\s+colombia|[,.!;\n\r]|$))"
        ),
        re.compile(
            r"(?i)(?:apertura|lanzamiento|validaci[oó]n|creaci[oó]n|estudio)\s+de\s+(?:la|el|un|una)\s+(?:miscel[aá]nea|tienda|restaurante|cafeter[ií]a|panader[ií]a|droguer[ií]a|ferreter[ií]a|cl[ií]nica|academia|empresa|plataforma|app|marca|negocio)(?:\s+de\s+barrio)?\s+([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ0-9\s.&'-]{2,45}?)(?=\s+(?:en\s+[A-ZÁÉÍÓÚÑ]|con\s+|[,.!;\n\r]|$))"
        ),
    ]

    for source_text in (req, doc):
        if not source_text:
            continue
        for pat in labeled_patterns:
            for match in pat.finditer(source_text):
                cand = _clean_candidate_name(match.group(1))
                if not is_placeholder_project_name(cand) and len(cand.split()) <= 6:
                    cand = _upgrade_short_name_from_text(cand, doc)
                    if not is_placeholder_project_name(cand):
                        return cand[:80]

    # 3. Estructura documental en extracted_text
    doc_lines = _strip_doc_noise_lines(doc)
    for line in doc_lines[:40]:
        # 3a. Encabezado Markdown "# PROMPTA: ..." o "# Miscelánea La Esperanza"
        if line.startswith("#"):
            heading = re.sub(r"^#+\s*", "", line).strip()
            if ":" in heading:
                left, right = heading.split(":", 1)
                if len(right.strip()) >= 12 and not is_placeholder_project_name(left):
                    heading = left.strip()
            cand = _clean_candidate_name(heading)
            if not is_placeholder_project_name(cand) and len(cand.split()) <= 6:
                return cand[:80]

        # 3b. Encabezado con pipe o guion: "NEXO RECLAMACIONES | MANUAL..." o "COFRE - Descripcion..."
        sep_match = re.match(r"^([A-ZÁÉÍÓÚÑ0-9][A-Za-zÁÉÍÓÚÑáéíóúñ0-9\s.&'-]{1,42}?)\s*(?:\||—|–|\s-\s)\s*(.+)$", line)
        if sep_match:
            left_cand = _clean_candidate_name(sep_match.group(1))
            if not is_placeholder_project_name(left_cand) and len(left_cand.split()) <= 5:
                return left_cand[:80]

    # 3c. Oración definicional: "<MARCA> es/ofrece/vende/presta..." (solo horizontal whitespace en marca)
    def_pat = re.compile(
        r"(?m)^(?:\*\*)?([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ0-9 \t.&'-]{1,45}?)(?:\*\*)?[ \t]+(?:\([^)\n]{2,80}\)[ \t]+)?(?:es[ \t]+(?:una?|el|la)[ \t]+(?:capa|plataforma|infraestructura|empresa|negocio|miscel[aá]nea|tienda|restaurante|cafeter[ií]a|panader[ií]a|droguer[ií]a|cl[ií]nica|academia|servicio|app|aplicaci[oó]n|emprendimiento|soluci[oó]n|sistema|herramienta|marca|comercio|estudio)\b|(?:ofrece|vende|presta|brinda|gestiona|protege|desarrolla|conecta|combina|centraliza)\b)"
    )
    req_lines = _strip_doc_noise_lines(req)
    for text_block in ("\n".join(doc_lines[:60]), "\n".join(req_lines[:30])):
        if not text_block:
            continue
        for m in def_pat.finditer(text_block):
            cand = _clean_candidate_name(m.group(1))
            cand_norm = _strip_accents(cand).lower()
            if cand_norm in _GENERIC_DEFINITIONAL_STARTERS:
                continue
            if not is_placeholder_project_name(cand) and len(cand.split()) <= 5:
                return cand[:80]

    # 3d. Línea corta independiente de marca al inicio del PDF (ej. "COFRE")
    for line in doc_lines[:15]:
        if any(ch in line for ch in ".,;:?!"):
            continue
        if 2 <= len(line) <= 36 and len(line.split()) <= 4 and line[0].isupper():
            cand = _clean_candidate_name(line)
            if not is_placeholder_project_name(cand):
                return cand[:80]

    # 4. Heurística sobre nombres de archivos subidos (sin tokens genéricos)
    for fname in filenames or []:
        stem = Path(str(fname)).stem
        tokens = [tok for tok in re.split(r"[_\-\s.]+", stem) if tok]
        kept = [tok for tok in tokens if _strip_accents(tok).lower() not in _GENERIC_FILENAME_TOKENS and len(tok) >= 2]
        if kept and (len(kept) >= 2 or (len(kept) == 1 and len(kept[0]) >= 3)):
            cand = _clean_candidate_name(" ".join(kept))
            if not is_placeholder_project_name(cand):
                return cand[:80]

    # 5. Respaldo descriptivo limpio (nunca URL, fragmentos truncados ni instrucciones de prompt)
    for line in req_lines + doc_lines[:20]:
        if not line[0].isupper():
            continue
        if is_placeholder_project_name(line):
            continue
        low = _strip_accents(line).lower()
        if re.match(r"^(?:simular|analizar|evaluar|investigar|validar|disenar|diseñar)\b", low):
            continue
        if any(k in low for k in ("http://", "https://", "actua como", "bloque ", "rol ", "mision", "simula", "analista ", "instruccion", "mercado objetivo", "el mercado")):
            continue
        if 8 <= len(line) <= 65 and len(line.split()) <= 7 and not line.endswith("?"):
            cand = _clean_candidate_name(line)
            if not is_placeholder_project_name(cand):
                return cand[:80]

    return "Estudio de Mercado"


def clean_study_topic(
    requirement: str,
    project_name: str = "",
    extracted_text: str = "",
    filenames: Optional[List[str]] = None,
) -> str:
    """Devuelve un tema de estudio limpio y legible, unificado entre canales, encuesta e informe."""
    name = extract_real_project_name(
        extracted_text=extracted_text,
        simulation_requirement=requirement,
        filenames=filenames,
        project_name_hint=project_name,
    )
    if name and not is_placeholder_project_name(name):
        return name[:80]
    return "este servicio o producto"


def _detect_sector(combined_text: str) -> str:
    norm = _strip_accents(combined_text).lower()
    best_sector = _DEFAULT_SECTOR
    best_score = 0
    for sector, cfg in _SECTOR_PROFILES.items():
        score = 0
        for kw in cfg["keywords"]:
            kw_norm = _strip_accents(kw).lower()
            hits = len(re.findall(rf"(?<!\w){re.escape(kw_norm)}(?!\w)", norm))
            if hits:
                # Dar más peso a coincidencias exactas multi-palabra o repetidas
                weight = 3 if " " in kw_norm else 2
                score += min(hits, 4) * weight
        if score > best_score:
            best_score = score
            best_sector = sector
    return best_sector


def _detect_geographic_scope(combined_text: str) -> str:
    norm = _strip_accents(combined_text).lower()
    has_latam = any(k in norm for k in ("latam", "latinoamerica", "america latina", "hispanoamerica", "hispanohablante"))
    colombia_cities = [
        "bogota", "medellin", "cali", "barranquilla", "cartagena",
        "bucaramanga", "monteria", "pereira", "manizales", "santa marta", "ibague", "cucuta",
    ]
    city_hits = sum(1 for c in colombia_cities if re.search(rf"(?<!\w){re.escape(c)}(?!\w)", norm))
    is_local_micro = any(
        k in norm
        for k in (
            "de barrio", "en el barrio", "vecindario", "local comercial", "esquina",
            "tienda de barrio", "miscelanea", "cuadra", "localidad de", "suba", "kennedy", "engativa", "chapinero",
        )
    )
    if has_latam:
        return "Colombia y LATAM"
    if city_hits >= 3 or "alcance nacional" in norm or "todo el pais" in norm or "colombia como mercado inicial" in norm:
        return "Colombia nacional"
    if is_local_micro and city_hits <= 1:
        return "Barrio / Local"
    if city_hits == 1 or city_hits == 2:
        return "Ciudad principal"
    if "colombia" in norm:
        return "Colombia nacional"
    return "Barrio / Local" if is_local_micro else "Ciudad principal"


def _detect_business_model(combined_text: str, sector: str, geo_scope: str) -> str:
    norm = _strip_accents(combined_text).lower()
    if any(k in norm for k in ("b2b2c", "comprador y vendedor", "compradores y vendedores", "dos lados", "marketplace", "comercio social")):
        return "B2B2C"
    if geo_scope == "Barrio / Local" or sector in {"comercio_minorista", "alimentos_bebidas"} and not any(k in norm for k in ("franquicia", "plataforma", "b2b")):
        return "comercio_local"
    if any(k in norm for k in ("empresas", "pymes", "corporativo", "b2b", "gerentes", "compañias", "companias")):
        if any(k in norm for k in ("personas naturales", "consumidor final", "ciudadanos", "b2c")):
            return "B2B2C"
        return "B2B"
    return "B2C"


def _detect_revenue_mechanism(combined_text: str, sector: str) -> str:
    norm = _strip_accents(combined_text).lower()
    has_comm = any(k in norm for k in ("comision", "take rate", "por transaccion protegida", "escrow", "custodia", "marketplace", "intermediacion"))
    has_sub = any(k in norm for k in ("suscripcion", "mensualidad", "saas", "plan mensual", "membresia", "recurrente"))
    if has_comm and has_sub:
        return "mixto"
    if has_comm or sector == "fintech_escrow":
        return "comision_pct"
    if has_sub or sector == "tecnologia_saas":
        return "suscripcion"
    if any(k in norm for k in ("freemium", "version gratuita")):
        return "freemium"
    if any(k in norm for k in ("por uso", "creditos", "consumo", "api")):
        return "uso"
    if any(k in norm for k in ("cuota de exito", "honorario de exito")):
        return "exito"
    return "tarifa_fija"


def _build_business_model_template(
    combined_text: str,
    sector: str,
    business_model: str,
    unit_label: str,
    reference_price_cop: int,
    competitors: List[str],
    regulatory_scope: List[str],
) -> Dict[str, Any]:
    rev_mech = _detect_revenue_mechanism(combined_text, sector)
    is_comm = rev_mech in ("comision_pct", "mixto")
    return {
        "client_type": business_model,
        "what_is_sold": "Capa de confianza y transacción protegida" if sector == "fintech_escrow" else f"Oferta principal ({sector})",
        "revenue_mechanism": rev_mech,
        "commission_ladder_pct": [1.5, 2.5, 3.5, 5.0, 7.0] if is_comm else [],
        "commission_pct": 0.035 if is_comm else 0.0,
        "avg_gmv_ticket_cop": max(60_000, reference_price_cop * 2) if is_comm else reference_price_cop,
        "who_pays": "Comprador y/o vendedor" if business_model == "B2B2C" else "Cliente comprador",
        "who_uses": "Compradores y vendedores" if business_model == "B2B2C" else "Usuario final",
        "economic_unit": unit_label,
        "current_alternative": competitors[0] if competitors else "Alternativa tradicional o no hacer nada",
        "legal_barriers": regulatory_scope,
    }


def _parse_cop_number(raw: str) -> Optional[int]:
    text = re.sub(r"[^\d]+$", "", (raw or "").strip())
    # Quitar centavos decimales finales (,00 / .00) sin romper separadores de miles (.000 / ,000)
    text = re.sub(r"[.,]\d{2}$", "", text)
    cleaned = re.sub(r"[^\d]", "", text)
    if not cleaned:
        return None
    return int(cleaned)


def _round_nice_cop(value: float) -> int:
    if value <= 0:
        return 1000
    if value < 10_000:
        step = 500
    elif value < 50_000:
        step = 1000
    elif value < 250_000:
        step = 5000
    else:
        step = 10000
    return max(500, int(round(value / step) * step))


def _extract_prices_and_ladder(
    combined_text: str,
    sector: str,
    quant_indicators: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[List[int], int]:
    """Extrae precios COP reales de productos/servicios y construye escalera de 5 peldaños."""
    candidates: List[int] = []
    anchor_candidates: List[int] = []

    # 1. Revisar quant_indicators (Fuente C: USER_STUDY)
    for item in quant_indicators or []:
        if not isinstance(item, dict):
            continue
        if item.get("source_tier") == "USER_STUDY" or str(item.get("metric_key", "")).startswith("user_study_price"):
            val = item.get("value_num")
            if isinstance(val, (int, float)) and 500 <= val <= 5_000_000:
                candidates.append(int(round(val)))
                anchor_candidates.append(int(round(val)))

    # 2. Buscar menciones explícitas de precio/tarifa/ticket en COP o $
    # Anclas explícitas (precio único de referencia/tarifa/ticket/plan/mensualidad/cuota/valor)
    # separadas de rangos (entre $X y $Y, desde $X hasta $Y) para no anclar en el límite inferior.
    anchor_pattern = re.compile(
        r"(?:precio(?:\s+de\s+referencia)?(?:\s+no\s+validado)?|tarifa|ticket(?:\s+promedio)?|valor|cuota|mensualidad|plan)\s*(?:de|:)?\s*(?:cop\s*\$?|\$)\s*([\d.,]{3,15})(?![\d.,])(?!\s*(?:y|a|-|hasta)\s*(?:cop\s*)?\$?\s*\d)",
        re.IGNORECASE,
    )
    price_patterns = [
        anchor_pattern,
        re.compile(
            r"(?:(?:entre|desde)\s*(?:de|:)?\s*(?:cop\s*\$?|\$)|cop\s*\$?)\s*([\d.,]{3,15})(?![\d.,])(?:\s*(?:y|a|-|hasta)\s*(?:cop\s*\$?|\$)\s*([\d.,]{3,15})(?![\d.,]))?",
            re.IGNORECASE,
        ),
        re.compile(r"\$\s*([\d]{1,3}(?:[.,][\d]{3})+(?:[.,]\d{2})?|\d{4,7}(?:[.,]\d{2})?)(?!\d|[.,]\d)(?!\s*usd\b)", re.IGNORECASE),
    ]

    for pat_idx, pat in enumerate(price_patterns):
        for match in pat.finditer(combined_text or ""):
            start = max(0, match.start() - 90)
            end = min(len(combined_text), match.end() + 25)
            window = _strip_accents(combined_text[start:end]).lower()
            if any(noise in window for noise in (
                "smmlv", "salario minimo", "tam ", "sam ", "som ", "usd", "dolares",
                "millones", "capital", "opex", "arriendo", "costo variable",
                "servicios publicos", "gastos fijos", "nomina", "inversion",
            )):
                continue
            for grp in match.groups():
                if not grp:
                    continue
                val = _parse_cop_number(grp)
                if val is None:
                    continue
                if 500 <= val <= 20_000_000 and val not in {2023, 2024, 2025, 2026, 2027}:
                    candidates.append(val)
                    if pat_idx == 0:
                        anchor_candidates.append(val)

    # Deduplicar manteniendo rango razonable
    uniq = sorted({c for c in candidates if 500 <= c <= 20_000_000})
    default_ladder = list(_SECTOR_PROFILES[sector]["price_ladder_cop"])

    if not uniq:
        return default_ladder, default_ladder[2]

    anchor = anchor_candidates[0] if anchor_candidates else None

    if len(uniq) >= 5:
        # Seleccionar 5 puntos representativos espaciados entre mínimo y máximo
        lo, hi = uniq[0], uniq[-1]
        if hi > lo:
            step = (hi - lo) / 4.0
            ladder = [_round_nice_cop(lo + i * step) for i in range(5)]
        else:
            ladder = default_ladder
    elif len(uniq) >= 2:
        lo, hi = uniq[0], uniq[-1]
        if hi <= lo * 1.15:
            p = anchor if anchor is not None else uniq[len(uniq) // 2]
            ladder = [
                _round_nice_cop(p * 0.50),
                _round_nice_cop(p * 0.75),
                _round_nice_cop(p),
                _round_nice_cop(p * 1.40),
                _round_nice_cop(p * 2.00),
            ]
        else:
            span_lo = max(500, _round_nice_cop(lo * 0.85))
            span_hi = _round_nice_cop(hi * 1.25)
            step = (span_hi - span_lo) / 4.0
            ladder = [_round_nice_cop(span_lo + i * step) for i in range(5)]
    else:
        p = uniq[0]
        ladder = [
            _round_nice_cop(p * 0.50),
            _round_nice_cop(p * 0.75),
            _round_nice_cop(p),
            _round_nice_cop(p * 1.40),
            _round_nice_cop(p * 2.00),
        ]

    # Garantizar estrictamente ascendente (5 peldaños int)
    strict_ladder: List[int] = []
    for val in ladder:
        v = int(val)
        if strict_ladder and v <= strict_ladder[-1]:
            bump = 500 if strict_ladder[-1] < 10_000 else (1000 if strict_ladder[-1] < 50_000 else 5000)
            v = strict_ladder[-1] + bump
        strict_ladder.append(v)

    if anchor is not None and strict_ladder[0] <= anchor <= strict_ladder[-1]:
        ref_price = int(anchor)
    else:
        ref_price = int(strict_ladder[2])
    return strict_ladder, ref_price


def _extract_value_proposition(extracted_text: str, simulation_requirement: str, project_name: str) -> Tuple[str, str]:
    """Extrae una propuesta de valor y un resumen conciso de oferta sin ruido del prompt."""
    doc_lines = _strip_doc_noise_lines(extracted_text)
    req_lines = _strip_doc_noise_lines(simulation_requirement)

    def _clean_vp_line(text: str) -> str:
        return re.sub(r"^#+\s*", "", text or "").strip()

    # 1. Buscar etiquetas explícitas ("Qué hace:", "Propuesta de valor:", "Concepto del negocio:", "Resumen ejecutivo:")
    labeled_vp = re.compile(
        r"(?i)^(?:qu[eé]\s+hace|propuesta\s+de\s+valor|promesa(?:\s+central|\s+defendible)?|objetivo\s+principal)\s*:\s*(.+)$"
    )
    for raw_line in req_lines + doc_lines:
        line = _clean_vp_line(raw_line)
        m = labeled_vp.match(line)
        if m:
            vp = _clean_vp_line(m.group(1))
            if len(vp) >= 20 and not is_placeholder_project_name(vp[:40]):
                return vp[:280], vp[:135].rstrip(".,;:")

    # 2. Oración definicional del proyecto o servicio
    for raw_line in doc_lines[:80]:
        line = _clean_vp_line(raw_line)
        if is_placeholder_project_name(line[:50]):
            continue
        low = _strip_accents(line).lower()
        if any(w in low for w in ("es la capa", "es una aplicacion", "es una plataforma", "es un servicio", "es una tienda", "es una miscelanea", "organiza cada", "orienta, asesora", "servicio especializado", "ofrece ")):
            return line[:280], line[:135].rstrip(".,;:")

    # 3. Primera línea descriptiva limpia del requirement o del documento
    for raw_line in req_lines + doc_lines[:40]:
        line = _clean_vp_line(raw_line)
        low = _strip_accents(line).lower()
        if any(skip in low for skip in ("bloque ", "actua como", "tu mision", "http://", "https://", "simula y predice", "entrega una fase", "reglas de rigor", "metodologia")):
            continue
        if is_placeholder_project_name(line[:50]):
            continue
        if 25 <= len(line) <= 260:
            return line[:280], line[:135].rstrip(".,;:")

    fallback = f"Propuesta de valor de {project_name} orientada al mercado colombiano."
    return fallback, fallback[:135]


def _extract_upsell_offer(combined_text: str, sector: str, reference_price: int) -> Optional[Dict[str, Any]]:
    """Extrae oferta secundaria/upsell únicamente si existe evidencia en el texto."""
    text = combined_text or ""
    # Caso explícito tipo "Servicio B, Acompañamiento y gestión: ..."
    svc_b = re.search(
        r"(?im)^[-•*]?\s*(Servicio\s*B[^:\n—–-]*)(?:[:—–-]\s*([^\n.]{10,160}))?",
        text,
    )
    if svc_b:
        name = re.sub(r"\s+", " ", svc_b.group(1)).strip(" :-–—")
        desc = (svc_b.group(2) or "Acompañamiento integral y gestión avanzada").strip()
        return {
            "name": name,
            "description": desc[:160],
            "estimated_price_cop": _round_nice_cop(reference_price * 2.5),
            "pricing_model": "tarifa_fija_o_complejidad",
        }

    # Caso planes pro / premium / combos / suscripción / domicilio
    upsell_match = re.search(
        r"(?i)(servicios?\s+premium|versi[oó]n\s+pro|plan\s+pro|plan\s+premium|combos?\s+familiares?|servicio\s+a\s+domicilio|paquete\s+empresarial)",
        text,
    )
    if upsell_match:
        label = upsell_match.group(1).strip().capitalize()
        return {
            "name": label,
            "description": f"Oferta complementaria de mayor valor ({label}) identificada en los documentos del estudio.",
            "estimated_price_cop": _round_nice_cop(reference_price * (1.8 if sector == "comercio_minorista" else 2.2)),
            "pricing_model": "upsell_complementario",
        }

    return None


def _extract_competitors(combined_text: str, sector: str) -> List[str]:
    defaults = list(_SECTOR_PROFILES[sector]["competitors"])
    found: List[str] = []
    known_brands = [
        "Nequi", "Daviplata", "Mercado Pago", "Mercado Libre", "PSE", "PayU", "Wompi",
        "D1", "Ara", "Ísimo", "Éxito", "Rappi", "ChatGPT", "Claude", "Gemini",
        "Servientrega", "Interrapidísimo", "Sura", "Bolívar", "Mapfre", "Fasecolda",
    ]
    text = combined_text or ""
    for b in known_brands:
        if b == "Éxito":
            qualified = bool(
                re.search(
                    r"(?<![A-Za-zÁÉÍÓÚÑáéíóúñ0-9_])(?:(?:Almacenes|Grupo|Supermercados?|Tiendas?|Hipermercados?)\s+[EÉeé]xito|(?:compite\s+con|frente\s+a|competencia\s+de)\s+Éxito)(?![A-Za-zÁÉÍÓÚÑáéíóúñ0-9_])",
                    text,
                )
            )
            retail_capitalized = sector in {"comercio_minorista", "alimentos_bebidas"} and bool(
                re.search(
                    r"(?<![A-Za-zÁÉÍÓÚÑáéíóúñ0-9_])Éxito(?![A-Za-zÁÉÍÓÚÑáéíóúñ0-9_])",
                    text,
                )
            )
            matched = qualified or retail_capitalized
        else:
            matched = bool(
                re.search(
                    rf"(?<![A-Za-z0-9_]){re.escape(b)}(?![A-Za-z0-9_])",
                    text,
                    re.IGNORECASE,
                )
            )
        if matched and b not in found:
            found.append(b)
    # Combinar menciones directas con alternativas sectoriales sin duplicar
    merged = found[:]
    for d in defaults:
        if not any(b.lower() in d.lower() for b in found):
            merged.append(d)
    return merged[:6]


def _extract_key_channels(combined_text: str) -> List[str]:
    norm = _strip_accents(combined_text).lower()
    mapping = [
        ("whatsapp_1on1", ["whatsapp", "wa", "chat"]),
        ("instagram", ["instagram", "ig", "stories", "historias"]),
        ("tiktok", ["tiktok", "reels", "video corto"]),
        ("facebook_groups", ["facebook", "grupos", "marketplace"]),
        ("colombian_web", ["web", "landing", "seo", "google", "sitio"]),
        ("advertising", ["meta ads", "google ads", "pauta", "anuncios", "publicidad"]),
        ("street_survey", ["barrio", "presencial", "punto fisico", "local", "tienda", "calle"]),
        ("focus_group", ["focus group", "entrevistas", "videollamada", "reunion"]),
        ("news_portals", ["prensa", "portales", "noticias", "editorial"]),
        ("radio", ["radio", "emisora"]),
        ("tv", ["tv", "television"]),
    ]
    prioritized: List[str] = []
    for cid, kws in mapping:
        if (
            any(re.search(rf"(?<!\w){re.escape(_strip_accents(kw).lower())}(?!\w)", norm) for kw in kws)
            and cid in CANONICAL_CHANNEL_IDS
        ):
            prioritized.append(cid)
    for cid in ["whatsapp_1on1", "instagram", "facebook_groups", "tiktok", "colombian_web", "advertising"]:
        if cid not in prioritized:
            prioritized.append(cid)
    return prioritized[:8]


def _extract_risks_objections(combined_text: str, sector: str) -> List[str]:
    defaults = list(_SECTOR_PROFILES[sector]["objections"])
    extracted: List[str] = []
    for raw_line in (combined_text or "").splitlines():
        line = raw_line.strip(" \t•-*")
        low = _strip_accents(line).lower()
        if any(tok in low for tok in ("objecion", "desconfianza", "miedo", "riesgo", "estafa", "fraude", "gratis", "no compran", "rechazo")):
            if 15 <= len(line) <= 130 and not is_placeholder_project_name(line[:50]):
                extracted.append(line)
    merged: List[str] = []
    for item in extracted + defaults:
        if item not in merged:
            merged.append(item)
    return merged[:6]


def _extract_domain_keywords(combined_text: str, project_name: str, sector: str) -> List[str]:
    tokens = re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{4,24}", combined_text or "")
    counts: Dict[str, int] = {}
    for tok in tokens:
        low = _strip_accents(tok).lower()
        if low in _SPANISH_STOPWORDS or len(low) < 4:
            continue
        counts[tok.lower()] = counts.get(tok.lower(), 0) + 1
    ranked = [w for w, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
    seed_kws = [w.lower() for w in re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ0-9]{3,}", project_name or "")]
    sector_kws = [k for k in _SECTOR_PROFILES[sector]["keywords"][:6] if " " not in k]
    out: List[str] = []
    for w in seed_kws + ranked + sector_kws:
        w_clean = w.strip()
        if w_clean and w_clean not in out:
            out.append(w_clean)
        if len(out) >= 15:
            break
    return out


def _build_codebook_rules(
    project_name: str,
    sector: str,
    domain_keywords: List[str],
    competitors: List[str],
    regulatory_scope: List[str],
) -> List[Dict[str, Any]]:
    brand_tokens = [re.escape(t.lower()) for t in project_name.split() if len(t) >= 3]
    comp_tokens = [
        re.escape(w.lower())
        for c in competitors[:4]
        for w in re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{4,}", c)
        if _strip_accents(w).lower() not in _SPANISH_STOPWORDS
    ][:6]
    reg_tokens = [
        re.escape(w.lower())
        for r in regulatory_scope[:4]
        for w in re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{4,}", r)
        if _strip_accents(w).lower() not in _SPANISH_STOPWORDS
    ][:5]
    dom_tokens = [re.escape(k) for k in domain_keywords[:6]]

    rules = [
        {
            "code": "PRECIO_VALOR",
            "label": "Sensibilidad al precio y percepción de valor",
            "patterns": ["precio", "caro", "barato", "tarifa", "costo", "pagar", "cop", "descuento", "presupuesto"],
        },
        {
            "code": "CONFIANZA_SEGURIDAD",
            "label": "Confianza, credibilidad y reducción de riesgo",
            "patterns": ["confianza", "seguro", "estafa", "fraude", "garant", "respaldo", "transparencia", "duda"],
        },
        {
            "code": "CANAL_ACCESO",
            "label": "Fricción de canal y experiencia de acceso",
            "patterns": ["whatsapp", "instagram", "tiktok", "web", "horario", "domicilio", "rapido", "facil", "demora"],
        },
        {
            "code": "COMPETENCIA_ALTERNATIVA",
            "label": "Comparación con alternativas existentes",
            "patterns": sorted(set(["gratis", "directo", "competencia", "otro", "solo"] + comp_tokens)),
        },
        {
            "code": "ADOPCION_PROPUESTA",
            "label": f"Adopción de la propuesta ({project_name})",
            "patterns": sorted(set(["probar", "sirve", "necesito", "util", "recomiendo"] + brand_tokens + dom_tokens[:4])),
        },
        {
            "code": "MARCO_OPERATIVO_LEGAL",
            "label": "Cumplimiento operativo, sanitario o normativo",
            "patterns": sorted(set(["legal", "datos", "norma", "permiso", "ley", "seguridad"] + reg_tokens)),
        },
    ]
    return rules


def _build_dofa_seed(
    project_name: str,
    sector: str,
    geo_scope: str,
    value_proposition: str,
    competitors: List[str],
    objections: List[str],
    regulatory_scope: List[str],
) -> Dict[str, Any]:
    return {
        "fortalezas": [
            f"Propuesta diferenciada de {project_name}: {value_proposition[:110]}",
            f"Enfoque adaptado al contexto de mercado ({geo_scope}) y hábitos digitales colombianos",
            "Estructura de precios parametrizada en COP según disposición a pagar por segmento",
        ],
        "oportunidades": [
            f"Demanda desatendida en el segmento {sector.replace('_', ' ')} en {geo_scope}",
            "Captación ágil mediante canales conversacionales (WhatsApp) y redes locales",
            "Alianzas con actores complementarios y referidos de clientes satisfechos",
        ],
        "debilidades": [
            objections[0] if objections else "Necesidad de construir confianza inicial sin historial previo",
            "Dependencia de validación de conversión real frente a intención declarada",
            "Capacidad operativa limitada en etapa temprana de lanzamiento",
        ],
        "amenazas": [
            f"Presión competitiva de alternativas establecidas ({', '.join(competitors[:2])})",
            objections[1] if len(objections) > 1 else "Sensibilidad macroeconómica del hogar colombiano al gasto",
            f"Exigencias de cumplimiento normativo ({regulatory_scope[0] if regulatory_scope else 'Ley 1480 / Ley 1581'})",
        ],
        "scores": {
            "fortalezas": 72,
            "oportunidades": 78,
            "debilidades": 48,
            "amenazas": 54,
        },
    }


def _enrich_with_llm(base_ctx: Dict[str, Any], extracted_text: str, simulation_requirement: str) -> Dict[str, Any]:
    """Enriquece campos cualitativos con LLM opcionalmente sin romper invariantes numéricos ni identidad."""
    from ..utils.llm_client import LLMClient

    snippet_doc = (extracted_text or "")[:2200]
    snippet_req = (simulation_requirement or "")[:1200]
    prompt = (
        "Analiza este estudio de mercado en Colombia y devuelve ÚNICAMENTE un JSON válido con las claves opcionales: "
        "value_proposition (string <= 240 chars), offer_summary (string <= 130 chars), "
        "target_roles (lista de 4 a 6 roles breves tipo Rol_Descriptor), "
        "competitors (lista de 3 a 5 competidores reales en Colombia), "
        "key_risks_objections (lista de 3 a 5 objeciones concretas de clientes). "
        f"Proyecto ya identificado: {base_ctx['project_name']}. Sector: {base_ctx['sector']}.\n\n"
        f"[REQUISITO]\n{snippet_req}\n\n[DOCUMENTO]\n{snippet_doc}"
    )
    client = LLMClient()
    parsed = client.chat_json(
        messages=[
            {"role": "system", "content": "Eres analista senior de mercados en Colombia. Responde solo JSON válido."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=900,
        max_attempts=1,
    )
    if not isinstance(parsed, dict):
        return base_ctx

    updated = dict(base_ctx)
    vp = parsed.get("value_proposition")
    if isinstance(vp, str) and len(vp.strip()) >= 20 and not is_placeholder_project_name(vp[:45]):
        updated["value_proposition"] = vp.strip()[:280]
    osumm = parsed.get("offer_summary")
    if isinstance(osumm, str) and len(osumm.strip()) >= 15 and not is_placeholder_project_name(osumm[:45]):
        updated["offer_summary"] = osumm.strip()[:140]
    for list_key in ("target_roles", "competitors", "key_risks_objections"):
        val = parsed.get(list_key)
        if isinstance(val, list):
            cleaned_list = [str(x).strip() for x in val if isinstance(x, str) and str(x).strip()]
            min_len = 4 if list_key == "target_roles" else 3
            max_len = 8 if list_key == "target_roles" else 6
            if len(cleaned_list) >= min_len:
                updated[list_key] = cleaned_list[:max_len]
    return updated


def _resolve_project_dir(project_id: str, project_dir: Optional[Union[str, Path]] = None) -> Path:
    if project_dir is not None:
        return Path(project_dir)
    return Path(ProjectManager._get_project_dir(project_id))


def load_study_context(
    project_id: str,
    project_dir: Optional[Union[str, Path]] = None,
) -> Optional[Dict[str, Any]]:
    """Carga `study_context.json` del directorio del proyecto si existe y es válido."""
    if not project_id and project_dir is None:
        return None
    pdir = _resolve_project_dir(project_id, project_dir)
    path = pdir / "study_context.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"No se pudo leer study_context.json en {path}: {exc}")
        return None


def save_study_context(
    project_id: str,
    study_context: Dict[str, Any],
    project_dir: Optional[Union[str, Path]] = None,
) -> Path:
    """Persiste `study_context.json` en el directorio del proyecto."""
    pdir = _resolve_project_dir(project_id, project_dir)
    pdir.mkdir(parents=True, exist_ok=True)
    path = pdir / "study_context.json"
    tmp_path = pdir / "study_context.json.tmp"
    tmp_path.write_text(json.dumps(study_context, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)
    return path


def extract_and_build_study_context(
    project_id: str,
    project_name_hint: Optional[str] = None,
    extracted_text: str = "",
    simulation_requirement: str = "",
    filenames: Optional[List[str]] = None,
    quant_indicators: Optional[List[Dict[str, Any]]] = None,
    use_llm: bool = True,
    project_dir: Optional[Union[str, Path]] = None,
    save: bool = True,
) -> Dict[str, Any]:
    """Construye el StudyContext completo de 22 campos para cualquier negocio colombiano."""
    combined_text = "\n".join(part for part in [simulation_requirement or "", extracted_text or ""] if part).strip()

    project_name = extract_real_project_name(
        extracted_text=extracted_text,
        simulation_requirement=simulation_requirement,
        filenames=filenames,
        project_name_hint=project_name_hint,
    )
    project_slug = slugify_project_name(project_name)
    sector = _detect_sector(combined_text)
    sector_cfg = _SECTOR_PROFILES[sector]
    geographic_scope = _detect_geographic_scope(combined_text)
    business_model = _detect_business_model(combined_text, sector, geographic_scope)
    value_proposition, offer_summary = _extract_value_proposition(extracted_text, simulation_requirement, project_name)

    price_ladder_cop, reference_price_cop = _extract_prices_and_ladder(
        combined_text=combined_text,
        sector=sector,
        quant_indicators=quant_indicators,
    )
    var_ratio = float(sector_cfg["var_cost_ratio"])
    unit_var_cost_cop = float(max(200.0, min(reference_price_cop * 0.85, round(reference_price_cop * var_ratio, -2))))
    if unit_var_cost_cop >= reference_price_cop:
        unit_var_cost_cop = float(max(100.0, round(reference_price_cop * 0.5, 2)))

    opex_map = sector_cfg["opex_by_scope"]
    monthly_opex_cop = float(opex_map.get(geographic_scope, opex_map["Ciudad principal"]))
    opex_match = re.search(
        r"(?:arriendo|opex|gastos?\s+fijos?|servicios?\s+p[uú]blicos?)[^\d\n]{0,60}(?:cop\s*\$?|\$)\s*([\d.,]{5,15})",
        combined_text or "",
        re.IGNORECASE,
    )
    if opex_match:
        parsed_opex = _parse_cop_number(opex_match.group(1))
        if parsed_opex and 200_000 <= parsed_opex <= 50_000_000:
            monthly_opex_cop = float(parsed_opex)
    if reference_price_cop < 25_000 and monthly_opex_cop > 2_000_000:
        monthly_opex_cop = min(monthly_opex_cop, 1_800_000.0)
    elif reference_price_cop >= 1_000_000 and monthly_opex_cop < 5_500_000:
        monthly_opex_cop = max(monthly_opex_cop, 8_500_000.0)
    unit_label = str(sector_cfg["unit_label"])
    upsell_offer = _extract_upsell_offer(combined_text, sector, reference_price_cop)

    target_roles = list(sector_cfg["roles"])
    competitors = _extract_competitors(combined_text, sector)
    key_channels = _extract_key_channels(combined_text)
    key_risks_objections = _extract_risks_objections(combined_text, sector)
    regulatory_scope = list(sector_cfg["regulatory"])
    domain_keywords = _extract_domain_keywords(combined_text, project_name, sector)
    codebook_rules = _build_codebook_rules(
        project_name=project_name,
        sector=sector,
        domain_keywords=domain_keywords,
        competitors=competitors,
        regulatory_scope=regulatory_scope,
    )
    dofa_seed = _build_dofa_seed(
        project_name=project_name,
        sector=sector,
        geo_scope=geographic_scope,
        value_proposition=value_proposition,
        competitors=competitors,
        objections=key_risks_objections,
        regulatory_scope=regulatory_scope,
    )

    bm_template = _build_business_model_template(
        combined_text=combined_text,
        sector=sector,
        business_model=business_model,
        unit_label=unit_label,
        reference_price_cop=int(reference_price_cop),
        competitors=competitors,
        regulatory_scope=regulatory_scope,
    )

    study_context: Dict[str, Any] = {
        "project_id": project_id,
        "project_name": project_name,
        "project_slug": project_slug,
        "sector": sector,
        "business_model": business_model,
        "business_model_template": bm_template,
        "confirmed": False,
        "confirmed_by": None,
        "confirmed_at": None,
        "geographic_scope": geographic_scope,
        "value_proposition": value_proposition,
        "offer_summary": offer_summary,
        "price_ladder_cop": [int(p) for p in price_ladder_cop],
        "reference_price_cop": int(reference_price_cop),
        "unit_var_cost_cop": float(unit_var_cost_cop),
        "monthly_opex_cop": float(monthly_opex_cop),
        "unit_label": unit_label,
        "upsell_offer": upsell_offer,
        "target_roles": target_roles,
        "competitors": competitors,
        "key_channels": key_channels,
        "key_risks_objections": key_risks_objections,
        "regulatory_scope": regulatory_scope,
        "domain_keywords": domain_keywords,
        "codebook_rules": codebook_rules,
        "dofa_seed": dofa_seed,
    }

    if use_llm and Config.LLM_API_KEY:
        try:
            study_context = _enrich_with_llm(study_context, extracted_text, simulation_requirement)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Enriquecimiento LLM de StudyContext omitido (respaldo determinístico): {exc}")

    if save:
        save_study_context(project_id=project_id, study_context=study_context, project_dir=project_dir)

    return study_context


def ensure_study_context(
    project_id: str,
    project_dir: Optional[Union[str, Path]] = None,
    use_llm: bool = False,
) -> Optional[Dict[str, Any]]:
    """Carga `study_context.json` o lo construye determinísticamente para proyectos existentes."""
    if not project_id:
        return None
    existing = load_study_context(project_id=project_id, project_dir=project_dir)
    if existing:
        return existing

    project = ProjectManager.get_project(project_id)
    if not project:
        return None

    extracted_text = ProjectManager.get_extracted_text(project_id) or ""
    filenames = [f.get("filename", "") for f in (project.files or []) if isinstance(f, dict)]
    return extract_and_build_study_context(
        project_id=project_id,
        project_name_hint=project.name,
        extracted_text=extracted_text,
        simulation_requirement=project.simulation_requirement or "",
        filenames=filenames,
        quant_indicators=None,
        use_llm=use_llm,
        project_dir=project_dir,
        save=True,
    )


def confirm_study_context(
    project_id: str,
    updates: Optional[Dict[str, Any]] = None,
    confirmed_by: str = "cliente",
    project_dir: Optional[Union[str, Path]] = None,
) -> Optional[Dict[str, Any]]:
    """Confirma y opcionalmente ajusta el StudyContext y su plantilla de modelo de negocio (V3 §5.2)."""
    from datetime import datetime, timezone

    ctx = load_study_context(project_id, project_dir=project_dir) or ensure_study_context(project_id, project_dir=project_dir, use_llm=False)
    if not ctx:
        return None
    if updates:
        for k, v in updates.items():
            if k == "business_model_template" and isinstance(v, dict):
                ctx.setdefault("business_model_template", {}).update(v)
            elif k in ctx:
                ctx[k] = v
        if "project_name" in updates and updates["project_name"]:
            ctx["project_slug"] = slugify_project_name(str(updates["project_name"]))
    ctx["confirmed"] = True
    ctx["confirmed_by"] = confirmed_by
    ctx["confirmed_at"] = datetime.now(timezone.utc).isoformat()
    save_study_context(project_id, ctx, project_dir=project_dir)
    return ctx
