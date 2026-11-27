<div align="center">

<img src="./frontend/src/assets/logo/prospectica_logo.svg" alt="Prospéctica V3" width="240" />

# Prospéctica V3

**Laboratorio de Pre-Validación de Ideas de Negocio y Estudios de Mercado Sintéticos Calibrados (Colombia → LATAM)**

*Investigación secundaria trazable · Población sintética de 7 capas · Econometría determinística y Monte Carlo · Validación automatizada V-01..V-45*

</div>

---

## Qué es Prospéctica V3

**Prospéctica V3** es una plataforma de inteligencia de mercados diseñada para emprendedores, startups, pymes, corporativos e inversionistas. Combina cuatro capas integradas en un flujo auditable:

1. **Investigación secundaria con evidencia citada (`Evidence Ledger`)**: fuentes oficiales y sectoriales (DANE, MinTIC, Superfinanciera, Banrep, Confecámaras, CCCE, Raddar) con trazabilidad SHA-256, dimensionamiento **TAM / SAM / SOM** (top-down y bottom-up) y matriz competitiva.
2. **Persona Engine V2 (7 capas)**: población sintética construida por capas demográficas, socioeconómicas, psicográficas, conductuales, digitales, de dominio e imperfecciones humanas reales, con semillas únicas por agente y controles anti-repetición.
3. **Motor econométrico y financiero determinístico**: Van Westendorp (PSM + NMS), Gabor-Granger isotónico, modelo de monetización configurable (`tarifa_fija`, `suscripcion`, `comision_pct`, `freemium`, `uso`, `exito`, `mixto`), embudo emergente de 5 etapas, recorrido McKinsey CDJ, economía unitaria (`LTV`, `CAC`, `LTV/CAC`, `Payback`) y simulación **Monte Carlo de 5,000 corridas** (`P10 / P50 / P90`).
4. **Control de calidad, calibración y entregables profesionales**:
   - **45 reglas de validación (`V-01`..`V-45`)** que bloquean inconsistencias antes de publicar.
   - **Banco de 40 anclas empíricas de Colombia** + Gate de Calibración (`APROBADO` / `PARCIAL` / `NO APROBADO`) y recalibración bayesiana con datos reales.
   - **Informe maestro de 18 capítulos** (`Cap. 00` a `Cap. 17`) con **Semáforo de Confianza A–D**, **Ficha de Transparencia Sintética** y exportación directa en **PDF, PPTX, XLSX, ZIP y Markdown**.

> **Principio rector:** Prospéctica no reemplaza encuestas probabilísticas ni investigación primaria con personas reales; entrega un filtro rápido, transparente y calibrable para reducir la incertidumbre antes de invertir y diseñar el plan de validación en campo.

---

## Arquitectura del Proyecto

```text
prospectica-v3/
├── backend/
│   ├── app/
│   │   ├── api/                # Endpoints REST (graph, simulation, report, channels, analytics, v3)
│   │   ├── channels/           # Motor multicanal (WhatsApp 1-a-1, Focus Group, redes, encuestas)
│   │   ├── llm/                # Gateway multi-modelo y compatibilidad OpenAI/FreeLLMAPI
│   │   ├── models/             # Gestión de proyectos, tareas y reportes
│   │   └── services/
│   │       ├── analytics/      # Econometría de precios, CX, embudo emergente, finanzas/Monte Carlo
│   │       ├── backtesting.py  # Tablero de desempeño con 15 casos históricos
│   │       ├── calibration.py  # 40 anclas Colombia + Gate + Recalibración bayesiana
│   │       ├── compliance.py   # Ley 1581 (PII), exclusiones (V-42) y lenguaje permitido (V-40)
│   │       ├── persona_engine_v2.py
│   │       ├── report_builder_v3.py
│   │       ├── report_exporters.py
│   │       ├── secondary_research.py
│   │       └── validators.py   # Motor de 45 reglas V-01..V-45
│   ├── country_packs/          # Paquetes regionales LATAM (co, mx, pe, cl)
│   └── tests/                  # Suites unitarias, E2E y validación V3
└── frontend/                   # Aplicación Vue 3 + Vite + ECharts + Vitest
```

---

## Requisitos e Instalación Local

- **Python** `>= 3.11` con `uv`
- **Node.js** `>= 18` con `npm`

### 1. Instalar dependencias

```bash
# Raíz
npm install

# Backend
cd backend
uv sync

# Frontend
cd ../frontend
npm install
```

### 2. Configurar variables de entorno

Crea `backend/.env` a partir de `.env.example` (nunca subas `.env` al repositorio) con tu proveedor LLM (`LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_NAME`) y credenciales de memoria si aplican.

### 3. Ejecutar en desarrollo

```bash
# Desde la raíz (levanta backend Flask :5001 y frontend Vite :3000)
npm run dev
```

---

## Pruebas Automatizadas

```bash
# Backend (suites V3 Fases 0-6 y aislamiento)
cd backend
uv run pytest tests/test_v3_phase0.py tests/test_v3_phase1.py tests/test_v3_phase2.py tests/test_v3_phase3.py tests/test_v3_phase4_5.py tests/test_v3_phase6.py tests/test_m1_study_context_and_isolation.py -v

# Frontend (Vitest + Build)
cd ../frontend
npm test -- --run
npm run build
```

---

## Licencia y Uso

Repositorio privado de **InteleyenLab** (`https://github.com/InteleyenLab/prospectica-v3`). Todos los derechos reservados.
