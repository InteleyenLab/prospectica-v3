# PROMPTA: Generador Inteligente de Prompts Estructurados en Español

## 1. Resumen del Proyecto y Concepto
**Prompta** (desarrollado en `E:\.orkas\userWorkSpace\editar-prompta-generador-de-prom`) es una aplicación web ligera diseñada específicamente para la comunidad hispanohablante que utiliza modelos de inteligencia artificial (ChatGPT, Claude, Gemini, DeepSeek, etc.). Su objetivo principal es resolver la frustración de obtener respuestas mediocres o genéricas de la IA debido a solicitudes mal formuladas.

Sin requerir registro ni instalación, el usuario escribe su necesidad en lenguaje natural cotidiano y la herramienta la descompone y reestructura automáticamente en una plantilla profesional y ejecutable de **seis bloques semánticos**.

---

## 2. El Problema que Resuelve
* **Respuestas vagas de la IA:** La mayoría de los usuarios no obtienen buenos resultados porque no saben cómo contextualizar, asignar roles o limitar las respuestas al interactuar con LLMs.
* **Fricción en herramientas complejas:** Muchas herramientas de ingeniería de prompts están en inglés, son de pago, requieren crear cuentas complejas o son excesivamente técnicas para un usuario común.
* **Falta de claridad en las solicitudes:** El usuario a menudo olvida especificar detalles esenciales (como el público al que se dirige, el tono deseado, el formato exacto o las restricciones de lo que la IA NO debe hacer).

---

## 3. Propuesta de Valor y Características Principales
1. **Estructura Modular de Seis Bloques:**
   - **Rol:** Asigna a la IA una identidad experta (ej. copywriter persuasivo, analista de datos sénior).
   - **Tarea:** Instrucción clara y no ambigua de lo que debe realizar.
   - **Contexto:** Información de fondo del negocio, proyecto o situación real sin inventar datos.
   - **Tono y Estilo:** Tono deseado (profesional, juvenil, pedagógico) y pautas de expresión.
   - **Formato de Salida:** Estructura de entrega (tabla markdown, lista de viñetas, máximo 3 párrafos, json).
   - **Restricciones y Límites:** Lo que queda estrictamente prohibido (ej. no usar palabras clichés, no inventar fuentes, no exceder 200 palabras).

2. **Tres Modalidades de Uso:**
   - **Modo Básico:** Conversión instantánea de la idea escrita a los 6 bloques editables.
   - **Modo Guiado:** El motor analiza qué información falta en la solicitud original y genera preguntas dinámicas de aclaración en español paso a paso antes de construir el prompt.
   - **Modo Avanzado:** Profundización estratégica con cuestionarios más detallados para tareas críticas o proyectos corporativos.

3. **Experiencia de Usuario (UX) sin Barreras:**
   - 100% en español (optimizado para expresiones de América Latina y España).
   - Completamente gratuito y accesible desde el navegador web y móvil.
   - Sin registro de cuenta, sin almacenar datos personales en servidores (procesamiento cliente).
   - Edición interactiva de cada bloque en tiempo real.
   - Botón de copia al portapapeles en un clic y conteo de palabras/caracteres.

---

## 4. Público Objetivo
- **Emprendedores y Pequeños Negocios:** Para generar copys publicitarios, correos de ventas, posts de Instagram/TikTok sin contratar redactores caros.
- **Estudiantes y Académicos:** Para resumir textos, preparar esquemas de estudio y formular preguntas de investigación.
- **Profesionales y Oficinistas:** Para redactar informes, minutas de reuniones y propuestas comerciales estructuradas.
- **Creadores de Contenido:** Para idear guiones de YouTube, hilos de X (Twitter) y contenidos virales.

---

## 5. Objetivos de la Simulación y Preguntas Clave a Predecir en MiroFish
La simulación de agentes en MiroFish debe predecir y responder:
1. **Adopción Real:** ¿Los usuarios hispanohablantes realmente adoptarían Prompta como herramienta diaria o preferirán seguir escribiendo directamente en la ventana de ChatGPT sin estructurar?
2. **Percepción de Valor:** ¿Ven útil la estructura de 6 bloques o les resulta abrumador tener que revisar bloques y responder preguntas aclaratorias?
3. **Puntos de Fricción y Críticas:** ¿Qué quejas, sospechas o rechazos expresan los usuarios en redes sociales (Twitter/Reddit simulados)? ¿Desconfianza, dudas sobre si es necesario pagar en el futuro, o pereza de usar una herramienta intermedia?
4. **Disposición al Pago vs Gratuidad:** ¿Existe disposición a pagar por una versión Pro (por ejemplo, con biblioteca de plantillas guardadas, integración por extensión de Chrome o conexión directa con API), o solo lo usarían si es 100% gratis?
5. **Funcionalidades Críticas Faltantes:** ¿Qué funciones adicionales exigiría la comunidad para convertir Prompta en una herramienta indispensable (ej. extensión de navegador, app móvil, integración con WhatsApp o Telegram)?
