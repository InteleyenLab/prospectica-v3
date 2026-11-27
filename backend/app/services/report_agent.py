"""
Report Agent服务
使用LangChain + Zep实现ReACT模式的模拟报告生成

功能：
1. 根据模拟需求和Zep图谱信息生成报告
2. 先规划目录结构，然后分段生成
3. 每段采用ReACT多轮思考与反思模式
4. 支持与用户对话，在对话中自主调用检索工具
"""

import os
import json
import time
import re
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from ..config import Config
from ..utils.llm_client import LLMClient
from ..utils.logger import get_logger
from ..utils.locale import get_language_instruction, t
from .zep_tools import (
    ZepToolsService, 
    SearchResult, 
    InsightForgeResult, 
    PanoramaResult,
    InterviewResult
)

logger = get_logger('mirofish.report_agent')


class ReportLogger:
    """
    Report Agent 详细日志记录器
    
    在报告文件夹中生成 agent_log.jsonl 文件，记录每一步详细动作。
    每行是一个完整的 JSON 对象，包含时间戳、动作类型、详细内容等。
    """
    
    def __init__(self, report_id: str):
        """
        初始化日志记录器
        
        Args:
            report_id: 报告ID，用于确定日志文件路径
        """
        self.report_id = report_id
        self.log_file_path = os.path.join(
            Config.UPLOAD_FOLDER, 'reports', report_id, 'agent_log.jsonl'
        )
        self.start_time = datetime.now()
        self._ensure_log_file()
    
    def _ensure_log_file(self):
        """确保日志文件所在目录存在"""
        log_dir = os.path.dirname(self.log_file_path)
        os.makedirs(log_dir, exist_ok=True)
    
    def _get_elapsed_time(self) -> float:
        """获取从开始到现在的耗时（秒）"""
        return (datetime.now() - self.start_time).total_seconds()
    
    def log(
        self, 
        action: str, 
        stage: str,
        details: Dict[str, Any],
        section_title: str = None,
        section_index: int = None
    ):
        """
        记录一条日志
        
        Args:
            action: 动作类型，如 'start', 'tool_call', 'llm_response', 'section_complete' 等
            stage: 当前阶段，如 'planning', 'generating', 'completed'
            details: 详细内容字典，不截断
            section_title: 当前章节标题（可选）
            section_index: 当前章节索引（可选）
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "elapsed_seconds": round(self._get_elapsed_time(), 2),
            "report_id": self.report_id,
            "action": action,
            "stage": stage,
            "section_title": section_title,
            "section_index": section_index,
            "details": details
        }
        
        # 追加写入 JSONL 文件
        with open(self.log_file_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
    
    def log_start(self, simulation_id: str, graph_id: str, simulation_requirement: str):
        """记录报告生成开始"""
        self.log(
            action="report_start",
            stage="pending",
            details={
                "simulation_id": simulation_id,
                "graph_id": graph_id,
                "simulation_requirement": simulation_requirement,
                "message": t('report.taskStarted')
            }
        )
    
    def log_planning_start(self):
        """记录大纲规划开始"""
        self.log(
            action="planning_start",
            stage="planning",
            details={"message": t('report.planningStart')}
        )
    
    def log_planning_context(self, context: Dict[str, Any]):
        """记录规划时获取的上下文信息"""
        self.log(
            action="planning_context",
            stage="planning",
            details={
                "message": t('report.fetchSimContext'),
                "context": context
            }
        )
    
    def log_planning_complete(self, outline_dict: Dict[str, Any]):
        """记录大纲规划完成"""
        self.log(
            action="planning_complete",
            stage="planning",
            details={
                "message": t('report.planningComplete'),
                "outline": outline_dict
            }
        )
    
    def log_section_start(self, section_title: str, section_index: int):
        """记录章节生成开始"""
        self.log(
            action="section_start",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={"message": t('report.sectionStart', title=section_title)}
        )
    
    def log_react_thought(self, section_title: str, section_index: int, iteration: int, thought: str):
        """记录 ReACT 思考过程"""
        self.log(
            action="react_thought",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "thought": thought,
                "message": t('report.reactThought', iteration=iteration)
            }
        )
    
    def log_tool_call(
        self, 
        section_title: str, 
        section_index: int,
        tool_name: str, 
        parameters: Dict[str, Any],
        iteration: int
    ):
        """记录工具调用"""
        self.log(
            action="tool_call",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "tool_name": tool_name,
                "parameters": parameters,
                "message": t('report.toolCall', toolName=tool_name)
            }
        )
    
    def log_tool_result(
        self,
        section_title: str,
        section_index: int,
        tool_name: str,
        result: str,
        iteration: int
    ):
        """记录工具调用结果（完整内容，不截断）"""
        self.log(
            action="tool_result",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "tool_name": tool_name,
                "result": result,  # 完整结果，不截断
                "result_length": len(result),
                "message": t('report.toolResult', toolName=tool_name)
            }
        )
    
    def log_llm_response(
        self,
        section_title: str,
        section_index: int,
        response: str,
        iteration: int,
        has_tool_calls: bool,
        has_final_answer: bool
    ):
        """记录 LLM 响应（完整内容，不截断）"""
        self.log(
            action="llm_response",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "response": response,  # 完整响应，不截断
                "response_length": len(response),
                "has_tool_calls": has_tool_calls,
                "has_final_answer": has_final_answer,
                "message": t('report.llmResponse', hasToolCalls=has_tool_calls, hasFinalAnswer=has_final_answer)
            }
        )
    
    def log_section_content(
        self,
        section_title: str,
        section_index: int,
        content: str,
        tool_calls_count: int
    ):
        """记录章节内容生成完成（仅记录内容，不代表整个章节完成）"""
        self.log(
            action="section_content",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "content": content,  # 完整内容，不截断
                "content_length": len(content),
                "tool_calls_count": tool_calls_count,
                "message": t('report.sectionContentDone', title=section_title)
            }
        )
    
    def log_section_full_complete(
        self,
        section_title: str,
        section_index: int,
        full_content: str
    ):
        """
        记录章节生成完成

        前端应监听此日志来判断一个章节是否真正完成，并获取完整内容
        """
        self.log(
            action="section_complete",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "content": full_content,
                "content_length": len(full_content),
                "message": t('report.sectionComplete', title=section_title)
            }
        )
    
    def log_report_complete(self, total_sections: int, total_time_seconds: float):
        """记录报告生成完成"""
        self.log(
            action="report_complete",
            stage="completed",
            details={
                "total_sections": total_sections,
                "total_time_seconds": round(total_time_seconds, 2),
                "message": t('report.reportComplete')
            }
        )
    
    def log_error(self, error_message: str, stage: str, section_title: str = None):
        """记录错误"""
        self.log(
            action="error",
            stage=stage,
            section_title=section_title,
            section_index=None,
            details={
                "error": error_message,
                "message": t('report.errorOccurred', error=error_message)
            }
        )


class ReportConsoleLogger:
    """
    Report Agent 控制台日志记录器
    
    将控制台风格的日志（INFO、WARNING等）写入报告文件夹中的 console_log.txt 文件。
    这些日志与 agent_log.jsonl 不同，是纯文本格式的控制台输出。
    """
    
    def __init__(self, report_id: str):
        """
        初始化控制台日志记录器
        
        Args:
            report_id: 报告ID，用于确定日志文件路径
        """
        self.report_id = report_id
        self.log_file_path = os.path.join(
            Config.UPLOAD_FOLDER, 'reports', report_id, 'console_log.txt'
        )
        self._ensure_log_file()
        self._file_handler = None
        self._setup_file_handler()
    
    def _ensure_log_file(self):
        """确保日志文件所在目录存在"""
        log_dir = os.path.dirname(self.log_file_path)
        os.makedirs(log_dir, exist_ok=True)
    
    def _setup_file_handler(self):
        """设置文件处理器，将日志同时写入文件"""
        import logging
        
        # 创建文件处理器
        self._file_handler = logging.FileHandler(
            self.log_file_path,
            mode='a',
            encoding='utf-8'
        )
        self._file_handler.setLevel(logging.INFO)
        
        # 使用与控制台相同的简洁格式
        formatter = logging.Formatter(
            '[%(asctime)s] %(levelname)s: %(message)s',
            datefmt='%H:%M:%S'
        )
        self._file_handler.setFormatter(formatter)
        
        # 添加到 report_agent 相关的 logger
        loggers_to_attach = [
            'mirofish.report_agent',
            'mirofish.zep_tools',
        ]
        
        for logger_name in loggers_to_attach:
            target_logger = logging.getLogger(logger_name)
            # 避免重复添加
            if self._file_handler not in target_logger.handlers:
                target_logger.addHandler(self._file_handler)
    
    def close(self):
        """关闭文件处理器并从 logger 中移除"""
        import logging
        
        if self._file_handler:
            loggers_to_detach = [
                'mirofish.report_agent',
                'mirofish.zep_tools',
            ]
            
            for logger_name in loggers_to_detach:
                target_logger = logging.getLogger(logger_name)
                if self._file_handler in target_logger.handlers:
                    target_logger.removeHandler(self._file_handler)
            
            self._file_handler.close()
            self._file_handler = None
    
    def __del__(self):
        """析构时确保关闭文件处理器"""
        self.close()


class ReportStatus(str, Enum):
    """报告状态"""
    PENDING = "pending"
    PLANNING = "planning"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ReportSection:
    """报告章节"""
    title: str
    content: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "content": self.content
        }

    def to_markdown(self, level: int = 2) -> str:
        """转换为Markdown格式"""
        md = f"{'#' * level} {self.title}\n\n"
        if self.content:
            md += f"{self.content}\n\n"
        return md


@dataclass
class ReportOutline:
    """报告大纲"""
    title: str
    summary: str
    sections: List[ReportSection]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "sections": [s.to_dict() for s in self.sections]
        }
    
    def to_markdown(self) -> str:
        """转换为Markdown格式"""
        md = f"# {self.title}\n\n"
        md += f"> {self.summary}\n\n"
        for section in self.sections:
            md += section.to_markdown()
        return md


@dataclass
class Report:
    """完整报告"""
    report_id: str
    simulation_id: str
    graph_id: str
    simulation_requirement: str
    status: ReportStatus
    outline: Optional[ReportOutline] = None
    markdown_content: str = ""
    created_at: str = ""
    completed_at: str = ""
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "simulation_id": self.simulation_id,
            "graph_id": self.graph_id,
            "simulation_requirement": self.simulation_requirement,
            "status": self.status.value,
            "outline": self.outline.to_dict() if self.outline else None,
            "markdown_content": self.markdown_content,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "error": self.error
        }


# ═══════════════════════════════════════════════════════════════
# Prompt 模板常量
# ═══════════════════════════════════════════════════════════════

# ── 工具描述 ──

TOOL_DESC_INSIGHT_FORGE = """\
[InsightForge - Búsqueda Profunda en Grafo]
Herramienta de recuperación multidimensional diseñada para análisis en profundidad:
1. Descompone tu pregunta en múltiples subconsultas automáticamente.
2. Busca en múltiples dimensiones del grafo de simulación.
3. Integra búsqueda semántica, análisis de entidades y cadenas de relaciones.

Cuándo usarla:
- Para analizar un tema en profundidad y desde múltiples ángulos.
- Para obtener evidencia rica y citas de respaldo para cada sección.

Contenido retornado:
- Hechos relevantes (citables textualmente).
- Detalle de entidades clave y relaciones."""

TOOL_DESC_PANORAMA_SEARCH = """\
[PanoramaSearch - Vista Panorámica del Escenario]
Obtiene el panorama completo del grafo, incluyendo hechos vigentes e históricos:
1. Recupera nodos y relaciones relevantes.
2. Distingue entre hechos activos actuales y registros históricos/expirados.

Cuándo usarla:
- Para comprender la evolución completa de los acontecimientos y reacciones.

Contenido retornado:
- Hechos vigentes, hechos históricos y entidades participantes."""

TOOL_DESC_QUICK_SEARCH = """\
[QuickSearch - Búsqueda Rápida]
Herramienta ligera para consultas directas y puntuales.

Cuándo usarla:
- Para localizar rápidamente un dato concreto o verificar un hecho puntual.

Contenido retornado:
- Lista de hechos más relevantes para la consulta."""

TOOL_DESC_INTERVIEW_AGENTS = """\
[InterviewAgents - Entrevista Directa a Agentes Simulados]
Entrevista directamente a los agentes simulados para conocer sus posturas y reacciones en primera persona en ambas plataformas.

Cuándo usarla:
- Para recoger opiniones directas, citas textuales y contrastes entre perfiles de agentes.

Nota: Requiere que el entorno de simulación siga activo."""

# ── 大纲规划 prompt ──

PLAN_SYSTEM_PROMPT = """\
Eres un experto redactor de "Informes de Predicción Futura" con una perspectiva integral del mundo simulado: puedes observar el comportamiento, las declaraciones y las interacciones de cada agente.

[CONCEPTO CENTRAL]
Hemos construido un mundo simulado y le hemos inyectado un "Requisito de simulación" específico como variable. Los resultados de la evolución del mundo simulado son la predicción de lo que ocurrirá en el futuro. No estás observando "datos pasados", sino un "ensayo del futuro".

【TU TAREA】
Elabora un "Informe de Predicción Futura" respondiendo:
1. Bajo las condiciones que fijamos, ¿qué ocurrió en el futuro?
2. ¿Cómo reaccionaron y actuaron los distintos agentes (segmentos de personas y entidades)?
3. ¿Qué tendencias, riesgos y oportunidades futuras relevantes revela esta simulación?

【ENFOQUE DEL INFORME】
- Esta es una predicción de futuro basada en simulación: "Si ocurre esto, ¿cómo será el futuro?".
- Enfócate en los resultados proyectados: rumbo de los acontecimientos, reacciones colectivas, fenómenos emergentes y riesgos potenciales.
- Las declaraciones y comportamientos de los agentes en el mundo simulado son la predicción del comportamiento humano futuro.
- NO es un análisis estático de la realidad actual ni un resumen genérico.

【LÍMITES DE SECCIONES】
- Mínimo 2 secciones, máximo 5 secciones.
- Cada sección contendrá directamente su contenido completo.
- El contenido debe ser riguroso y centrado en los hallazgos predictivos clave.
- Redacta el título y la descripción de cada sección ESTRICTAMENTE EN ESPAÑOL.

Genera el esquema del informe en formato JSON:
{{
    "title": "Título del informe en español",
    "summary": "Resumen ejecutivo en español (una frase que sintetice el hallazgo predictivo central)",
    "sections": [
        {{
            "title": "Título de la sección en español",
            "description": "Descripción del contenido de la sección en español"
        }}
    ]
}}

Nota: ¡El array 'sections' debe tener entre 2 y 5 elementos!"""

PLAN_USER_PROMPT_TEMPLATE = """\
[ESCENARIO DE PREDICCIÓN CONFIGURADO]
Variables inyectadas al mundo simulado (Requisito de simulación): {simulation_requirement}

[DIMENSIÓN DEL MUNDO SIMULADO]
- Entidades participantes: {total_nodes}
- Relaciones generadas entre entidades: {total_edges}
- Distribución de tipos de entidades: {entity_types}
- Agentes activos: {total_entities}

[MUESTRA DE HECHOS FUTUROS PREDICHOS EN LA SIMULACIÓN]
{related_facts_json}

Examina este ensayo del futuro desde una vista panorámica:
1. Bajo las condiciones establecidas, ¿qué estado presenta el futuro?
2. ¿Cómo reaccionaron y actuaron los diferentes grupos y agentes?
3. ¿Qué tendencias críticas revela esta simulación?

Diseña la estructura de secciones más adecuada para el informe predictivo. Redacta todos los títulos y descripciones estrictamente en español.

[RECORDATORIO] Cantidad de secciones: mínimo 2, máximo 5. Contenido riguroso y enfocado en hallazgos predictivos."""

# ── 章节生成 prompt ──

SECTION_SYSTEM_PROMPT_TEMPLATE = """\
Eres un redactor experto en "Informes de Predicción Futura", redactando una sección específica del informe.

Título del informe: {report_title}
Resumen del informe: {report_summary}
Escenario simulado (Requisito): {simulation_requirement}

Sección actual a redactar: {section_title}

═══════════════════════════════════════════════════════════════
[CONCEPTO CENTRAL]
═══════════════════════════════════════════════════════════════

El mundo simulado es un ensayo del futuro. Hemos inyectado condiciones específicas (requisito de simulación). El comportamiento e interacciones de los agentes en la simulación representan la predicción de lo que ocurrirá en el futuro.

Tu misión es:
- Revelar qué ocurrió en el futuro bajo las condiciones fijadas.
- Predecir cómo reaccionaron y actuaron los diferentes agentes y colectivos.
- Descubrir tendencias futuras, riesgos y oportunidades críticas.

═══════════════════════════════════════════════════════════════
[REGLAS OBLIGATORIAS]
═══════════════════════════════════════════════════════════════

1. [OBSERVAR EL MUNDO SIMULADO MEDIANTE HERRAMIENTAS]
   - Observas el ensayo del futuro desde una posición de observador privilegiado.
   - Todo el contenido debe provenir de los eventos y declaraciones reales de los agentes en la simulación.
   - Prohibido inventar datos o usar conocimientos no fundamentados en la simulación.
   - Analiza la evidencia del grafo de simulación proporcionada; solo si necesitas verificar un dato puntual adicional puedes llamar a una herramienta (máximo 1-2 veces), o bien redactar directamente la sección comenzando con "Final Answer:".

2. [CITAR DECLARACIONES TEXTUALES DE LOS AGENTES]
   - Las declaraciones de los agentes son la evidencia central de la predicción.
   - Muestra estas declaraciones en formato de cita en bloque, por ejemplo:
     > "Un agente del sector expresó: contenido textual..."

3. [CONSISTENCIA DE IDIOMA - ESTRICTAMENTE EN ESPAÑOL]
   - Redacta TODO el contenido en ESPAÑOL.
   - Si una herramienta devuelve contenido en otro idioma, tradúcelo fielmente al español antes de incluirlo en el texto o en las citas (>).

4. [FIDELIDAD A LOS RESULTADOS PREDICTIVOS]
   - No inventes nombres de usuario, números estadísticos ni citas que no figuren en los resultados de las herramientas.

═══════════════════════════════════════════════════════════════
[NORMAS DE FORMATO]
═══════════════════════════════════════════════════════════════

- Prohibido incluir encabezados Markdown (#, ##, ###, ####) dentro del cuerpo de la sección.
- El título de la sección es agregado automáticamente por el sistema.
- Comienza directamente redactando el cuerpo del texto.
- Usa **negrita** para destacar conceptos clave en lugar de subtítulos.
- Las citas deben ir en párrafos independientes con formato > "..."

═══════════════════════════════════════════════════════════════
[HERRAMIENTAS DE RECUPERACIÓN DISPONIBLES]
═══════════════════════════════════════════════════════════════

{tools_description}

═══════════════════════════════════════════════════════════════
[FLUJO DE TRABAJO]
═══════════════════════════════════════════════════════════════

En cada respuesta debes realizar UNA de las dos siguientes acciones:

Opción A - Llamar a una herramienta:
<tool_call>
{{"name": "nombre_herramienta", "parameters": {{"parametro": "valor"}}}}
</tool_call>

Opción B - Respuesta final:
Cuando hayas recopilado suficiente información, responde comenzando exactamente con "Final Answer:" seguido del contenido completo de la sección en español.
"""

SECTION_USER_PROMPT_TEMPLATE = """\
Contenido de las secciones anteriores ya completadas (léelo con atención para evitar repeticiones):
{previous_content}

═══════════════════════════════════════════════════════════════
[TAREA ACTUAL] Redactar sección: {section_title}
═══════════════════════════════════════════════════════════════

[RECORDATORIO IMPORTANTE]
1. Revisa las secciones anteriores para no duplicar información.
2. Utiliza las herramientas para recuperar datos antes de redactar.
3. El contenido debe fundamentarse en la evidencia recuperada.
4. No incluyas títulos (#, ##, etc.); comienza directamente con el texto.
5. Todo redactado estrictamente en ESPAÑOL.

Comienza:
1. Analiza (Thought) qué información necesita esta sección.
2. Llama a las herramientas (Action) para obtener datos de la simulación.
3. Tras reunir suficiente información, entrega la respuesta con "Final Answer:"."""

# ── ReACT 循环内消息模板 ──

REACT_OBSERVATION_TEMPLATE = """\
Observación (Resultados de búsqueda):

═══ Herramienta {tool_name} respondió ═══
{result}

═══════════════════════════════════════════════════════════════
Herramientas consultadas: {tool_calls_count}/{max_tool_calls} (Usadas: {used_tools_str}){unused_hint}
- Si la información es suficiente: responde comenzando con "Final Answer:" y redacta la sección completa en español.
- Si necesitas más información: llama a otra herramienta para continuar.
═══════════════════════════════════════════════════════════════"""

REACT_INSUFFICIENT_TOOLS_MSG = (
    "[ATENCIÓN] Has llamado herramientas {tool_calls_count} veces; se requieren al menos {min_tool_calls}. "
    "Por favor consulta más datos de la simulación antes de emitir tu Final Answer. {unused_hint}"
)

REACT_INSUFFICIENT_TOOLS_MSG_ALT = (
    "Se han llamado herramientas {tool_calls_count} veces (mínimo {min_tool_calls}). "
    "Consulta herramientas para recabar más datos. {unused_hint}"
)

REACT_TOOL_LIMIT_MSG = (
    "Has alcanzado el límite de herramientas ({tool_calls_count}/{max_tool_calls}). "
    'Por favor redacta el contenido de la sección en español comenzando con "Final Answer:".'
)

REACT_UNUSED_TOOLS_HINT = "\n💡 Aún no has probado: {unused_list}. Te recomendamos consultar diferentes herramientas."

REACT_FORCE_FINAL_MSG = "Límite de herramientas alcanzado. Por favor emite directamente tu Final Answer: con el contenido de la sección en español."

# ── Chat prompt ──

CHAT_SYSTEM_PROMPT_TEMPLATE = """\
Eres un asistente de predicción y análisis de simulación conciso, profesional y eficiente.

[CONTEXTO]
Requisito de simulación: {simulation_requirement}

[INFORME DE ANÁLISIS GENERADO]
{report_content}

[REGLAS OBLIGATORIAS]
1. Responde a las preguntas basándote prioritariamente en el contenido del informe.
2. Responde directamente y con claridad en ESPAÑOL, evitando rodeos innecesarios.
3. Solo si el contenido del informe es insuficiente, llama a herramientas para consultar datos adicionales.
4. Respuestas claras, ordenadas y estrictamente en español.

[HERRAMIENTAS DISPONIBLES] (Solo si es indispensable, máximo 1-2 veces)
{tools_description}

[FORMATO DE LLAMADA A HERRAMIENTAS]
<tool_call>
{{"name": "nombre_herramienta", "parameters": {{"parametro": "valor"}}}}
</tool_call>

[ESTILO DE RESPUESTA]
- Conciso y directo en español.
- Utiliza formato > para citar datos o declaraciones clave."""

CHAT_OBSERVATION_SUFFIX = "\n\nPor favor, responde de forma concisa y clara en español."

CHAT_FAST_SYSTEM_PROMPT_TEMPLATE = """\
Eres un consultor senior de estrategia de mercado y analista principal del informe de inteligencia de mercados del proyecto evaluado. Responde SIEMPRE en ESPAÑOL con un análisis profundo, estructurado y accionable.
Reglas:
- Ve directo a la respuesta (no emitas razonamientos internos, bloques <think> ni llamadas a herramientas).
- Estructura la respuesta con encabezados breves (###), viñetas y, cuando aporte valor, tablas Markdown.
- Fundamenta cada afirmación con cifras, hallazgos o citas concretas del informe (usa formato > para citas).
- Incluye, cuando aplique: diagnóstico, implicaciones, riesgos/oportunidades, y recomendaciones concretas priorizadas con próximos pasos.
- Si el usuario adjuntó documentos, analízalos a fondo, contrástalos con el informe y señala coincidencias, contradicciones y vacíos.
- Si algo no aparece en el informe ni en los adjuntos, dilo explícitamente y ofrece una inferencia razonada marcada como tal; nunca inventes datos.

[REQUISITO ORIGINAL]
{simulation_requirement}

[INFORME GENERADO]
{report_content}"""


# ═══════════════════════════════════════════════════════════════
# ReportAgent 主类
# ═══════════════════════════════════════════════════════════════


class ReportAgent:
    """
    Report Agent - 模拟报告生成Agent

    采用ReACT（Reasoning + Acting）模式：
    1. 规划阶段：分析模拟需求，规划报告目录结构
    2. 生成阶段：逐章节生成内容，每章节可多次调用工具获取信息
    3. 反思阶段：检查内容完整性和准确性
    """
    
    # 最大工具调用次数（每个章节）
    MAX_TOOL_CALLS_PER_SECTION = 5
    
    # 最大反思轮数
    MAX_REFLECTION_ROUNDS = 3
    
    # 对话中的最大工具调用次数
    MAX_TOOL_CALLS_PER_CHAT = 2
    
    def __init__(
        self, 
        graph_id: str,
        simulation_id: str,
        simulation_requirement: str,
        llm_client: Optional[LLMClient] = None,
        zep_tools: Optional[ZepToolsService] = None,
        enable_tools: bool = True
    ):
        """
        初始化Report Agent
        
        Args:
            graph_id: 图谱ID
            simulation_id: 模拟ID
            simulation_requirement: 模拟需求描述
            llm_client: LLM客户端（可选）
            zep_tools: Zep工具服务（可选）
            enable_tools: Si False, evita comprobaciones IPC innecesarias al instanciar para chat rápido
        """
        self.graph_id = graph_id
        self.simulation_id = simulation_id
        self.simulation_requirement = simulation_requirement
        
        self._llm: Optional[LLMClient] = llm_client
        self.zep_tools = zep_tools or ZepToolsService()
        
        # 工具定义
        self.enable_tools = enable_tools
        self.tools = self._define_tools() if enable_tools else {}
        
        # 日志记录器（在 generate_report 中初始化）
        self.report_logger: Optional[ReportLogger] = None
        # 控制台日志记录器（在 generate_report 中初始化）
        self.console_logger: Optional[ReportConsoleLogger] = None
        
        logger.info(t('report.agentInitDone', graphId=graph_id, simulationId=simulation_id))

    @property
    def llm(self) -> LLMClient:
        """Inicialización perezosa de LLMClient para permitir flujos determinísticos sin API key."""
        if self._llm is None:
            self._llm = LLMClient()
        return self._llm

    @llm.setter
    def llm(self, value: Optional[LLMClient]) -> None:
        self._llm = value
    
    def _define_tools(self) -> Dict[str, Dict[str, Any]]:
        """Define las herramientas disponibles"""
        tools = {
            "insight_forge": {
                "name": "insight_forge",
                "description": TOOL_DESC_INSIGHT_FORGE,
                "parameters": {
                    "query": "Pregunta o tema específico a analizar en profundidad (en español)",
                    "report_context": "Contexto de la sección actual del informe (opcional)"
                }
            },
            "panorama_search": {
                "name": "panorama_search",
                "description": TOOL_DESC_PANORAMA_SEARCH,
                "parameters": {
                    "query": "Consulta de búsqueda para ordenar relevancia (en español)",
                    "include_expired": "Incluir hechos históricos/expirados (por defecto True)"
                }
            },
            "quick_search": {
                "name": "quick_search",
                "description": TOOL_DESC_QUICK_SEARCH,
                "parameters": {
                    "query": "Cadena de consulta puntual (en español)",
                    "limit": "Número máximo de resultados (opcional, por defecto 10)"
                }
            }
        }

        # Solo habilitar entrevistas a agentes si el entorno de simulación sigue activo
        try:
            from .simulation_ipc import SimulationIPCClient
            sim_dir = os.path.join(Config.UPLOAD_FOLDER, "simulations", self.simulation_id)
            if os.path.exists(sim_dir):
                ipc = SimulationIPCClient(sim_dir)
                if ipc.check_env_alive():
                    tools["interview_agents"] = {
                        "name": "interview_agents",
                        "description": TOOL_DESC_INTERVIEW_AGENTS,
                        "parameters": {
                            "interview_topic": "Tema o enfoque de la entrevista en español",
                            "max_agents": "Número máximo de agentes a entrevistar (opcional, por defecto 5)"
                        }
                    }
        except Exception:
            pass

        return tools
    
    def _execute_tool(self, tool_name: str, parameters: Dict[str, Any], report_context: str = "") -> str:
        """
        执行工具调用
        
        Args:
            tool_name: 工具名称
            parameters: 工具参数
            report_context: 报告上下文（用于InsightForge）
            
        Returns:
            工具执行结果（文本格式）
        """
        logger.info(t('report.executingTool', toolName=tool_name, params=parameters))
        
        try:
            if tool_name == "insight_forge":
                query = parameters.get("query", "")
                ctx = parameters.get("report_context", "") or report_context
                result = self.zep_tools.insight_forge(
                    graph_id=self.graph_id,
                    query=query,
                    simulation_requirement=self.simulation_requirement,
                    report_context=ctx
                )
                return result.to_text()
            
            elif tool_name == "panorama_search":
                # 广度搜索 - 获取全貌
                query = parameters.get("query", "")
                include_expired = parameters.get("include_expired", True)
                if isinstance(include_expired, str):
                    include_expired = include_expired.lower() in ['true', '1', 'yes']
                result = self.zep_tools.panorama_search(
                    graph_id=self.graph_id,
                    query=query,
                    include_expired=include_expired
                )
                return result.to_text()
            
            elif tool_name == "quick_search":
                # 简单搜索 - 快速检索
                query = parameters.get("query", "")
                limit = parameters.get("limit", 10)
                if isinstance(limit, str):
                    limit = int(limit)
                result = self.zep_tools.quick_search(
                    graph_id=self.graph_id,
                    query=query,
                    limit=limit
                )
                return result.to_text()
            
            elif tool_name == "interview_agents":
                interview_topic = parameters.get("interview_topic", parameters.get("query", ""))
                if "interview_agents" not in self.tools:
                    logger.info("Entorno de simulación inactivo; redirigiendo interview_agents a quick_search")
                    return self._execute_tool("quick_search", {"query": interview_topic, "limit": 10}, report_context)
                max_agents = parameters.get("max_agents", 5)
                if isinstance(max_agents, str):
                    max_agents = int(max_agents)
                max_agents = min(max_agents, 10)
                result = self.zep_tools.interview_agents(
                    simulation_id=self.simulation_id,
                    interview_requirement=interview_topic,
                    simulation_requirement=self.simulation_requirement,
                    max_agents=max_agents
                )
                return result.to_text()
            
            # ========== 向后兼容的旧工具（内部重定向到新工具） ==========
            
            elif tool_name == "search_graph":
                # 重定向到 quick_search
                logger.info(t('report.redirectToQuickSearch'))
                return self._execute_tool("quick_search", parameters, report_context)
            
            elif tool_name == "get_graph_statistics":
                result = self.zep_tools.get_graph_statistics(self.graph_id)
                return json.dumps(result, ensure_ascii=False, indent=2)
            
            elif tool_name == "get_entity_summary":
                entity_name = parameters.get("entity_name", "")
                result = self.zep_tools.get_entity_summary(
                    graph_id=self.graph_id,
                    entity_name=entity_name
                )
                return json.dumps(result, ensure_ascii=False, indent=2)
            
            elif tool_name == "get_simulation_context":
                # 重定向到 insight_forge，因为它更强大
                logger.info(t('report.redirectToInsightForge'))
                query = parameters.get("query", self.simulation_requirement)
                return self._execute_tool("insight_forge", {"query": query}, report_context)
            
            elif tool_name == "get_entities_by_type":
                entity_type = parameters.get("entity_type", "")
                nodes = self.zep_tools.get_entities_by_type(
                    graph_id=self.graph_id,
                    entity_type=entity_type
                )
                result = [n.to_dict() for n in nodes]
                return json.dumps(result, ensure_ascii=False, indent=2)
            
            else:
                return f"Herramienta desconocida: {tool_name}. Usa una de: insight_forge, panorama_search, quick_search"
                
        except Exception as e:
            logger.error(t('report.toolExecFailed', toolName=tool_name, error=str(e)))
            return f"Error al ejecutar la herramienta: {str(e)}"
    
    @staticmethod
    def _get_openai_tools() -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "insight_forge",
                    "description": "Insight forge tool for multi-dimensional deep search on facts and relationships",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query"},
                            "report_context": {"type": "string", "description": "Context of the report section"}
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "panorama_search",
                    "description": "Panoramic search for full events and timeline evolution",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query"}
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "quick_search",
                    "description": "Quick search for specific information",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Specific query"}
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "interview_agents",
                    "description": "Interview simulated agents for first-person opinions",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Interview topic or query"}
                        },
                        "required": ["query"]
                    }
                }
            }
        ]

    # 合法的工具名称集合，用于裸 JSON 兜底解析时校验
    VALID_TOOL_NAMES = {"insight_forge", "panorama_search", "quick_search", "interview_agents"}

    def _parse_tool_calls(self, response: str) -> List[Dict[str, Any]]:
        """
        从LLM响应中解析工具调用

        支持的格式（按优先级）：
        1. <tool_call>{"name": "tool_name", "parameters": {...}}</tool_call>
        2. 裸 JSON（响应整体或单行就是一个工具调用 JSON）
        """
        tool_calls = []

        # Formato 1: XML (<tool_call>{...}</tool_call>, incluso si faltó etiqueta de apertura)
        xml_pattern = r'(?:<tool_call>\s*)?(\{"(?:name|tool)"\s*:.*?\})\s*</tool_call>'
        for match in re.finditer(xml_pattern, response, re.DOTALL):
            try:
                call_data = json.loads(match.group(1))
                if self._is_valid_tool_call(call_data):
                    tool_calls.append(call_data)
            except json.JSONDecodeError:
                pass

        if tool_calls:
            return tool_calls

        # Formato 2: JSON desnudo al inicio/final de la respuesta
        stripped = re.sub(r'</?tool_call\b[^>]*>', '', response, flags=re.IGNORECASE).strip()
        if stripped.startswith('{') and stripped.endswith('}'):
            try:
                call_data = json.loads(stripped)
                if self._is_valid_tool_call(call_data):
                    tool_calls.append(call_data)
                    return tool_calls
            except json.JSONDecodeError:
                pass

        # Pensamiento + JSON al final (con o sin cierre </tool_call>)
        json_pattern = r'(\{"(?:name|tool)"\s*:.*?\})(?:\s*</tool_call>)?\s*$'
        match = re.search(json_pattern, response.strip(), re.DOTALL)
        if match:
            try:
                call_data = json.loads(match.group(1))
                if self._is_valid_tool_call(call_data):
                    tool_calls.append(call_data)
            except json.JSONDecodeError:
                pass

        return tool_calls

    def _is_valid_tool_call(self, data: dict) -> bool:
        """校验解析出的 JSON 是否是合法的工具调用"""
        # 支持 {"name": ..., "parameters": ...} 和 {"tool": ..., "params": ...} 两种键名
        tool_name = data.get("name") or data.get("tool")
        if tool_name and tool_name in self.VALID_TOOL_NAMES:
            # 统一键名为 name / parameters
            if "tool" in data:
                data["name"] = data.pop("tool")
            if "params" in data and "parameters" not in data:
                data["parameters"] = data.pop("params")
            return True
        return False
    
    def _get_tools_description(self) -> str:
        """Genera la descripción de herramientas en español"""
        desc_parts = ["Herramientas disponibles:"]
        for name, tool in self.tools.items():
            params_desc = ", ".join([f"{k}: {v}" for k, v in tool["parameters"].items()])
            desc_parts.append(f"- {name}: {tool['description']}")
            if params_desc:
                desc_parts.append(f"  Parámetros: {params_desc}")
        return "\n".join(desc_parts)

    @staticmethod
    def _strip_fake_tool_results(response: str) -> str:
        """Strip any <tool_result> blocks the LLM fabricated in its response.

        When the LLM generates a <tool_call> block and then continues to generate
        a <tool_result> block in the same response, we must strip the fake result
        before appending to message history. The real tool result will be injected
        separately by the system.
        """
        tag_pattern = re.compile(r'</?tool_result\b[^>]*>', flags=re.IGNORECASE)
        parts = []
        cursor = 0
        depth = 0

        for match in tag_pattern.finditer(response):
            if depth == 0:
                parts.append(response[cursor:match.start()])

            if match.group(0).lstrip().startswith('</'):
                depth = max(0, depth - 1)
            else:
                depth += 1
            cursor = match.end()

        if depth == 0:
            parts.append(response[cursor:])

        cleaned = ''.join(parts)
        # Treat a malformed opening tag without a closing `>` as unsafe too.
        cleaned = re.sub(r'<tool_result\b.*$', '', cleaned, flags=re.IGNORECASE | re.DOTALL)
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
        return cleaned.strip()

    @staticmethod
    def _clean_section_markdown(text: str) -> str:
        """Limpia bloques de pensamiento, etiquetas de herramientas y ruido antes de guardar la sección."""
        if not text:
            return ""

        cleaned = ReportAgent._strip_fake_tool_results(text)
        # Eliminar bloques <think>...</think> o texto previo a un cierre </think> huérfano
        cleaned = re.sub(r'<think>[\s\S]*?</think>', '', cleaned, flags=re.IGNORECASE)
        if '</think>' in cleaned.lower():
            cleaned = re.split(r'</think>', cleaned, flags=re.IGNORECASE)[-1]

        if 'Final Answer:' in cleaned:
            cleaned = cleaned.split('Final Answer:')[-1].strip()

        # Eliminar bloques o etiquetas sueltas de herramientas
        cleaned = re.sub(r'(?:<tool_call>\s*)?\{[\s\S]*?"(?:name|tool)"\s*:[\s\S]*?\}(?:\s*</tool_call>)?', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'</?tool_call\b[^>]*>', '', cleaned, flags=re.IGNORECASE)

        # Filtrar párrafos de meta-razonamiento en inglés filtrados por modelos pequeños
        meta_patterns = re.compile(
            r'^\s*(?:["\',]*\s*I think\b|I\'ll structure\b|Let me (?:draft|re-read|check|think|see|review)\b|'
            r'\(Starting directly\b|Wait,\s*I\s+(?:made up|should|need)\b|I need to be very careful\b|'
            r'Maybe I should\b|I cannot invent\b|Looking back\b|This section\b|I\'ve done\b|'
            r'The rules say:|The user instruction:|I can talk about\b|I could state\b)',
            flags=re.IGNORECASE,
        )
        kept_paragraphs = []
        for para in re.split(r'\n\s*\n', cleaned):
            p = para.strip()
            if not p:
                continue
            if meta_patterns.search(p):
                continue
            kept_paragraphs.append(p)

        result = '\n\n'.join(kept_paragraphs).strip()
        result = re.sub(r'\n{3,}', '\n\n', result)
        return result.strip()

    def plan_outline(
        self, 
        progress_callback: Optional[Callable] = None
    ) -> ReportOutline:
        """
        规划报告大纲
        
        使用LLM分析模拟需求，规划报告的目录结构
        
        Args:
            progress_callback: 进度回调函数
            
        Returns:
            ReportOutline: 报告大纲
        """
        logger.info(t('report.startPlanningOutline'))
        
        if progress_callback:
            progress_callback("planning", 0, t('progress.analyzingRequirements'))
        
        # 首先获取模拟上下文
        context = self.zep_tools.get_simulation_context(
            graph_id=self.graph_id,
            simulation_requirement=self.simulation_requirement
        )
        
        if progress_callback:
            progress_callback("planning", 30, t('progress.generatingOutline'))
        
        system_prompt = f"{PLAN_SYSTEM_PROMPT}\n\n{get_language_instruction()}"
        user_prompt = PLAN_USER_PROMPT_TEMPLATE.format(
            simulation_requirement=self.simulation_requirement,
            total_nodes=context.get('graph_statistics', {}).get('total_nodes', 0),
            total_edges=context.get('graph_statistics', {}).get('total_edges', 0),
            entity_types=list(context.get('graph_statistics', {}).get('entity_types', {}).keys()),
            total_entities=context.get('total_entities', 0),
            related_facts_json=json.dumps(context.get('related_facts', [])[:10], ensure_ascii=False, indent=2),
        )

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )
            
            if progress_callback:
                progress_callback("planning", 80, t('progress.parsingOutline'))
            
            # 解析大纲
            sections = []
            for section_data in response.get("sections", []):
                sections.append(ReportSection(
                    title=section_data.get("title", ""),
                    content=""
                ))
            
            outline = ReportOutline(
                title=response.get("title", "Informe de Predicción y Análisis de Simulación"),
                summary=response.get("summary", ""),
                sections=sections
            )
            
            if progress_callback:
                progress_callback("planning", 100, t('progress.outlinePlanComplete'))
            
            logger.info(t('report.outlinePlanDone', count=len(sections)))
            return outline
            
        except Exception as e:
            logger.error(t('report.outlinePlanFailed', error=str(e)))
            # Esquema de respaldo en español si falla la planificación JSON
            return ReportOutline(
                title="Informe de Predicción y Análisis de Simulación",
                summary="Análisis predictivo de recepción, comportamiento de segmentos, precios y evolución proyectada",
                sections=[
                    ReportSection(title="Recepción del Escenario y Hallazgos Principales"),
                    ReportSection(title="Análisis del Comportamiento de los Segmentos y Canales"),
                    ReportSection(title="Disposición de Pago, Tendencias y Proyección a Futuro")
                ]
            )
    
    def _generate_section_react(
        self, 
        section: ReportSection,
        outline: ReportOutline,
        previous_sections: List[str],
        progress_callback: Optional[Callable] = None,
        section_index: int = 0
    ) -> str:
        """
        使用ReACT模式生成单个章节内容
        
        ReACT循环：
        1. Thought（思考）- 分析需要什么信息
        2. Action（行动）- 调用工具获取信息
        3. Observation（观察）- 分析工具返回结果
        4. 重复直到信息足够或达到最大次数
        5. Final Answer（最终回答）- 生成章节内容
        
        Args:
            section: 要生成的章节
            outline: 完整大纲
            previous_sections: 之前章节的内容（用于保持连贯性）
            progress_callback: 进度回调
            section_index: 章节索引（用于日志记录）
            
        Returns:
            章节内容（Markdown格式）
        """
        logger.info(t('report.reactGenerateSection', title=section.title))
        
        # 记录章节开始日志
        if self.report_logger:
            self.report_logger.log_section_start(section.title, section_index)
        
        system_prompt = SECTION_SYSTEM_PROMPT_TEMPLATE.format(
            report_title=outline.title,
            report_summary=outline.summary,
            simulation_requirement=self.simulation_requirement,
            section_title=section.title,
            tools_description=self._get_tools_description(),
        )
        system_prompt = f"{system_prompt}\n\n{get_language_instruction()}"

        # 构建用户prompt - 每个已完成章节各传入最大1200字
        if previous_sections:
            previous_parts = []
            for sec in previous_sections:
                # 每个章节最多1200字，避免超出TPM限制
                truncated = sec[:1200] + "..." if len(sec) > 1200 else sec
                previous_parts.append(truncated)
            previous_content = "\n\n---\n\n".join(previous_parts)
        else:
            previous_content = "(Esta es la primera sección)"
        
        user_prompt = SECTION_USER_PROMPT_TEMPLATE.format(
            previous_content=previous_content,
            section_title=section.title,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        # ReACT循环
        tool_calls_count = 0
        max_iterations = 5  # 最大迭代轮数
        min_tool_calls = 1  # 最少工具调用次数
        conflict_retries = 0  # 工具调用与Final Answer同时出现的连续冲突次数
        used_tools = set()  # 记录已调用过的工具名
        all_tools = set(self.tools.keys())

        # Contexto de la sección para las subconsultas de InsightForge
        report_context = f"Título de la sección: {section.title}\nRequisito de simulación: {self.simulation_requirement}"

        # Recuperación inicial proactiva para asegurar evidencia real del grafo de Zep
        # incluso cuando modelos gratuitos respondan directamente sin emitir <tool_call>.
        initial_query = f"{section.title} - {self.simulation_requirement[:200]}"
        initial_tool_name = "insight_forge"
        initial_params = {"query": initial_query, "report_context": report_context}

        if self.report_logger:
            self.report_logger.log_tool_call(
                section_title=section.title,
                section_index=section_index,
                tool_name=initial_tool_name,
                parameters=initial_params,
                iteration=1,
            )

        initial_result = self._execute_tool(
            initial_tool_name,
            initial_params,
            report_context=report_context,
        )
        if isinstance(initial_result, str) and initial_result.startswith("Error al ejecutar"):
            initial_tool_name = "quick_search"
            initial_params = {"query": initial_query, "limit": 15}
            initial_result = self._execute_tool(
                initial_tool_name,
                initial_params,
                report_context=report_context,
            )

        if self.report_logger:
            self.report_logger.log_tool_result(
                section_title=section.title,
                section_index=section_index,
                tool_name=initial_tool_name,
                result=initial_result,
                iteration=1,
            )

        tool_calls_count += 1
        used_tools.add(initial_tool_name)

        evidence_snippet = initial_result[:2500] if len(initial_result) > 2500 else initial_result
        messages[-1]["content"] += (
            f"\n\n═══ Evidencia inicial recuperada del grafo de simulación ({initial_tool_name}) ═══\n"
            f"{evidence_snippet}\n"
            "═══════════════════════════════════════════════════════════════\n"
            "Ya cuentas con evidencia real del grafo. Si necesitas ampliar un aspecto concreto puedes usar "
            "<tool_call>, o si ya tienes suficiente información entrega directamente tu respuesta en español "
            'comenzando con "Final Answer:".'
        )
        
        for iteration in range(max_iterations):
            if progress_callback:
                progress_callback(
                    "generating", 
                    int((iteration / max_iterations) * 100),
                    t('progress.deepSearchAndWrite', current=tool_calls_count, max=self.MAX_TOOL_CALLS_PER_SECTION)
                )
            
            # Usamos exclusivamente <tool_call> XML en el prompt para mantener compatibles
            # todos los modelos gratuitos sin filtrar los que carecen de tool-calling nativo.
            current_tools = None
            current_tool_choice = None

            # Llamar al LLM
            response = self.llm.chat(
                messages=messages,
                temperature=0.5,
                max_tokens=4000,
                tools=current_tools,
                tool_choice=current_tool_choice,
            )

            # Verificar si el LLM devolvió None
            if response is None:
                logger.warning(t('report.sectionIterNone', title=section.title, iteration=iteration + 1))
                if iteration < max_iterations - 1:
                    messages.append({"role": "assistant", "content": "(Respuesta vacía)"})
                    messages.append({"role": "user", "content": "Por favor, continúa generando el contenido en español."})
                    continue
                break

            logger.debug(f"LLM响应: {response[:200]}...")

            # 解析一次，复用结果
            tool_calls = self._parse_tool_calls(response)
            has_tool_calls = bool(tool_calls)
            has_final_answer = "Final Answer:" in response

            # ── 冲突处理：LLM 同时输出了工具调用和 Final Answer ──
            if has_tool_calls and has_final_answer:
                conflict_retries += 1
                logger.warning(
                    t('report.sectionConflict', title=section.title, iteration=iteration+1, conflictCount=conflict_retries)
                )

                if conflict_retries <= 2:
                    # 前两次：丢弃本次响应，要求 LLM 重新回复
                    cleaned_response = ReportAgent._strip_fake_tool_results(response)
                    messages.append({"role": "assistant", "content": cleaned_response})
                    messages.append({
                        "role": "user",
                        "content": (
                            "[Error de formato] Incluiste una llamada a herramienta y Final Answer en la misma respuesta.\n"
                            "En cada turno solo puedes hacer UNA de estas dos cosas:\n"
                            "- Llamar a una herramienta (un bloque <tool_call>, sin Final Answer)\n"
                            "- Entregar el contenido final (comenzando por 'Final Answer:', sin <tool_call>)\n"
                            "Por favor responde nuevamente haciendo solo una de las dos."
                        ),
                    })
                    continue
                else:
                    # 第三次：降级处理，截断到第一个工具调用，强制执行
                    logger.warning(
                        t('report.sectionConflictDowngrade', title=section.title, conflictCount=conflict_retries)
                    )
                    first_tool_end = response.find('</tool_call>')
                    if first_tool_end != -1:
                        response = response[:first_tool_end + len('</tool_call>')]
                        tool_calls = self._parse_tool_calls(response)
                        has_tool_calls = bool(tool_calls)
                    has_final_answer = False
                    conflict_retries = 0

            # 记录 LLM 响应日志
            if self.report_logger:
                self.report_logger.log_llm_response(
                    section_title=section.title,
                    section_index=section_index,
                    response=response,
                    iteration=iteration + 1,
                    has_tool_calls=has_tool_calls,
                    has_final_answer=has_final_answer
                )

            # ── 情况1：LLM 输出了 Final Answer ──
            if has_final_answer:
                cleaned_response = ReportAgent._strip_fake_tool_results(response)
                # 工具调用次数不足，拒绝并要求继续调工具
                if tool_calls_count < min_tool_calls:
                    messages.append({"role": "assistant", "content": cleaned_response})
                    unused_tools = all_tools - used_tools
                    unused_hint = f"(Herramientas aún no utilizadas recomendadas: {', '.join(unused_tools)})" if unused_tools else ""
                    messages.append({
                        "role": "user",
                        "content": REACT_INSUFFICIENT_TOOLS_MSG.format(
                            tool_calls_count=tool_calls_count,
                            min_tool_calls=min_tool_calls,
                            unused_hint=unused_hint,
                        ),
                    })
                    continue

                # Cierre normal con Final Answer limpio
                final_answer = ReportAgent._clean_section_markdown(cleaned_response)
                if len(final_answer) < 80:
                    messages.append({"role": "assistant", "content": cleaned_response})
                    messages.append({
                        "role": "user",
                        "content": f"{REACT_FORCE_FINAL_MSG}\n\n{get_language_instruction()}",
                    })
                    continue

                logger.info(t('report.sectionGenDone', title=section.title, count=tool_calls_count))

                if self.report_logger:
                    self.report_logger.log_section_content(
                        section_title=section.title,
                        section_index=section_index,
                        content=final_answer,
                        tool_calls_count=tool_calls_count
                    )
                return final_answer

            # ── 情况2：LLM 尝试调用工具 ──
            if has_tool_calls:
                # 工具额度已耗尽 → 明确告知，要求输出 Final Answer
                if tool_calls_count >= self.MAX_TOOL_CALLS_PER_SECTION:
                    cleaned_response = ReportAgent._strip_fake_tool_results(response)
                    messages.append({"role": "assistant", "content": cleaned_response})
                    messages.append({
                        "role": "user",
                        "content": REACT_TOOL_LIMIT_MSG.format(
                            tool_calls_count=tool_calls_count,
                            max_tool_calls=self.MAX_TOOL_CALLS_PER_SECTION,
                        ),
                    })
                    continue

                # 只执行第一个工具调用
                call = tool_calls[0]
                if len(tool_calls) > 1:
                    logger.info(t('report.multiToolOnlyFirst', total=len(tool_calls), toolName=call['name']))

                if self.report_logger:
                    self.report_logger.log_tool_call(
                        section_title=section.title,
                        section_index=section_index,
                        tool_name=call["name"],
                        parameters=call.get("parameters", {}),
                        iteration=iteration + 1
                    )

                result = self._execute_tool(
                    call["name"],
                    call.get("parameters", {}),
                    report_context=report_context
                )

                if self.report_logger:
                    self.report_logger.log_tool_result(
                        section_title=section.title,
                        section_index=section_index,
                        tool_name=call["name"],
                        result=result,
                        iteration=iteration + 1
                    )

                tool_calls_count += 1
                used_tools.add(call['name'])

                # 构建未使用工具提示
                unused_tools = all_tools - used_tools
                unused_hint = ""
                if unused_tools and tool_calls_count < self.MAX_TOOL_CALLS_PER_SECTION:
                    unused_hint = REACT_UNUSED_TOOLS_HINT.format(unused_list=", ".join(unused_tools))

                cleaned_response = ReportAgent._strip_fake_tool_results(response)
                messages.append({"role": "assistant", "content": cleaned_response})
                import time
                time.sleep(3)  # Evitar saturar el límite TPM de Groq
                messages.append({
                    "role": "user",
                    "content": (
                        REACT_OBSERVATION_TEMPLATE.format(
                            tool_name=call["name"],
                            result=result[:1800] if len(result) > 1800 else result,
                            tool_calls_count=tool_calls_count,
                            max_tool_calls=self.MAX_TOOL_CALLS_PER_SECTION,
                            used_tools_str=", ".join(used_tools),
                            unused_hint=unused_hint,
                        )
                        + f"\n\n{get_language_instruction()}"
                    ),
                })
                continue

            # ── 情况3：既没有工具调用，也没有 Final Answer ──
            cleaned_response = ReportAgent._strip_fake_tool_results(response)
            messages.append({"role": "assistant", "content": cleaned_response})

            if tool_calls_count < min_tool_calls:
                unused_tools = all_tools - used_tools
                unused_hint = f"(Herramientas aún no utilizadas recomendadas: {', '.join(unused_tools)})" if unused_tools else ""

                messages.append({
                    "role": "user",
                    "content": REACT_INSUFFICIENT_TOOLS_MSG_ALT.format(
                        tool_calls_count=tool_calls_count,
                        min_tool_calls=min_tool_calls,
                        unused_hint=unused_hint,
                    ),
                })
                continue

            # Herramientas suficientes: validar que tras limpiar ruido/etiquetas quede contenido útil en español
            final_clean = ReportAgent._clean_section_markdown(cleaned_response)
            if len(final_clean) >= 80:
                logger.info(t('report.sectionNoPrefix', title=section.title, count=tool_calls_count))
                final_answer = final_clean

                if self.report_logger:
                    self.report_logger.log_section_content(
                        section_title=section.title,
                        section_index=section_index,
                        content=final_answer,
                        tool_calls_count=tool_calls_count
                    )
                return final_answer
            else:
                # Si tras limpiar quedó vacío o demasiado breve (ej. solo JSON de herramienta o pensamiento), pedir redacción
                messages.append({
                    "role": "user",
                    "content": f"{REACT_FORCE_FINAL_MSG}\n\n{get_language_instruction()}"
                })
                continue
        
        # 达到最大迭代次数，强制生成内容
        logger.warning(t('report.sectionMaxIter', title=section.title))
        messages.append({
            "role": "user",
            "content": f"{REACT_FORCE_FINAL_MSG}\n\n{get_language_instruction()}"
        })
        
        response = self.llm.chat(
            messages=messages,
            temperature=0.5,
            max_tokens=4000,
            tools=None,
            tool_choice=None,
        )

        # Limpiar respuesta en cierre forzado
        if response is None:
            logger.error(t('report.sectionForceFailed', title=section.title))
            final_answer = t('report.sectionGenFailedContent')
        else:
            cleaned_forced = ReportAgent._clean_section_markdown(response)
            final_answer = cleaned_forced if len(cleaned_forced) >= 40 else t('report.sectionGenFailedContent')
        
        # 记录章节内容生成完成日志
        if self.report_logger:
            self.report_logger.log_section_content(
                section_title=section.title,
                section_index=section_index,
                content=final_answer,
                tool_calls_count=tool_calls_count
            )
        
        return final_answer
    
    def generate_report(
        self, 
        progress_callback: Optional[Callable[[str, int, str], None]] = None,
        report_id: Optional[str] = None,
        use_v2: Optional[bool] = None
    ) -> Report:
        """
        生成完整报告（分章节实时输出）
        
        每个章节生成完成后立即保存到文件夹，不需要等待整个报告完成。
        文件结构：
        reports/{report_id}/
            meta.json       - 报告元信息
            outline.json    - 报告大纲
            progress.json   - 生成进度
            section_01.md   - 第1章节
            section_02.md   - 第2章节
            ...
            full_report.md  - 完整报告
        
        Args:
            progress_callback: 进度回调函数 (stage, progress, message)
            report_id: 报告ID（可选，如果不传则自动生成）
            
        Returns:
            Report: 完整报告
        """
        import uuid
        
        # 如果没有传入 report_id，则自动生成
        if not report_id:
            report_id = f"report_{uuid.uuid4().hex[:12]}"
        start_time = datetime.now()
        
        report = Report(
            report_id=report_id,
            simulation_id=self.simulation_id,
            graph_id=self.graph_id,
            simulation_requirement=self.simulation_requirement,
            status=ReportStatus.PENDING,
            created_at=datetime.now().isoformat()
        )
        
        # 已完成的章节标题列表（用于进度追踪）
        completed_section_titles = []
        
        try:
            # 初始化：创建报告文件夹并保存初始状态
            ReportManager._ensure_report_folder(report_id)
            
            # 初始化日志记录器（结构化日志 agent_log.jsonl）
            self.report_logger = ReportLogger(report_id)
            self.report_logger.log_start(
                simulation_id=self.simulation_id,
                graph_id=self.graph_id,
                simulation_requirement=self.simulation_requirement
            )
            
            # 初始化控制台日志记录器（console_log.txt）
            self.console_logger = ReportConsoleLogger(report_id)
            
            ReportManager.update_progress(
                report_id, "pending", 0, t('progress.initReport'),
                completed_sections=[]
            )
            ReportManager.save_report(report)
            
            # Activar ReportAgentV2 (12 capítulos) cuando exista simulation_channels.db, analytics_bundle.json o use_v2=True
            sim_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, self.simulation_id)
            has_v2_data = (
                os.path.exists(os.path.join(sim_dir, "simulation_channels.db"))
                or os.path.exists(os.path.join(sim_dir, "analytics_bundle.json"))
            )
            if use_v2 or (use_v2 is None and has_v2_data):
                from .report_agent_v2 import ReportAgentV2
                from .report_builder_v3 import ReportBuilderV3
                from .simulation_manager import SimulationManager
                from .study_context_builder import load_study_context

                ReportManager.update_progress(report_id, "generating", 15, "Iniciando ReportBuilderV3 (18 capítulos)...")
                use_v2_llm = os.environ.get("REPORT_V2_USE_LLM", "false").strip().lower() == "true"
                v2_llm_client = self.llm if use_v2_llm else self._llm
                v2_helper = ReportAgentV2(use_llm=use_v2_llm, llm_client=v2_llm_client)
                bundle_data = v2_helper._ensure_analytics_bundle(self.simulation_id)
                st = SimulationManager().get_simulation(self.simulation_id)
                sctx = load_study_context(st.project_id) if (st and st.project_id) else None
                v2_res = ReportBuilderV3().build_report(
                    report_id=report_id,
                    simulation_id=self.simulation_id,
                    bundle=bundle_data,
                    study_context=sctx,
                )
                manifest = v2_res["manifest"]
                report.outline = ReportOutline(
                    title=manifest["title"],
                    summary=manifest["summary"],
                    sections=[
                        ReportSection(title=c["title"], content=c["content_markdown"])
                        for c in v2_res["chapters"]
                    ],
                )
                report.markdown_content = v2_res["markdown_content"]
                report.status = ReportStatus.COMPLETED
                report.completed_at = datetime.now().isoformat()
                total_time_seconds = (datetime.now() - start_time).total_seconds()
                if self.report_logger:
                    self.report_logger.log_report_complete(
                        total_sections=len(v2_res["chapters"]),
                        total_time_seconds=total_time_seconds,
                    )
                ReportManager.save_report(report)
                ReportManager.update_progress(
                    report_id,
                    "completed",
                    100,
                    t('progress.reportComplete'),
                    completed_sections=[c["title"] for c in v2_res["chapters"]],
                )
                if self.console_logger:
                    self.console_logger.close()
                    self.console_logger = None
                return report

            # 阶段1: 规划大纲
            report.status = ReportStatus.PLANNING
            ReportManager.update_progress(
                report_id, "planning", 5, t('progress.startPlanningOutline'),
                completed_sections=[]
            )
            
            # 记录规划开始日志
            self.report_logger.log_planning_start()
            
            if progress_callback:
                progress_callback("planning", 0, t('progress.startPlanningOutline'))
            
            outline = self.plan_outline(
                progress_callback=lambda stage, prog, msg: 
                    progress_callback(stage, prog // 5, msg) if progress_callback else None
            )
            report.outline = outline
            
            # 记录规划完成日志
            self.report_logger.log_planning_complete(outline.to_dict())
            
            # 保存大纲到文件
            ReportManager.save_outline(report_id, outline)
            ReportManager.update_progress(
                report_id, "planning", 15, t('progress.outlineDone', count=len(outline.sections)),
                completed_sections=[]
            )
            ReportManager.save_report(report)
            
            logger.info(t('report.outlineSavedToFile', reportId=report_id))
            
            # 阶段2: 逐章节生成（分章节保存）
            report.status = ReportStatus.GENERATING
            
            total_sections = len(outline.sections)
            generated_sections = []  # 保存内容用于上下文
            
            for i, section in enumerate(outline.sections):
                section_num = i + 1
                base_progress = 20 + int((i / total_sections) * 70)
                
                # 更新进度
                ReportManager.update_progress(
                    report_id, "generating", base_progress,
                    t('progress.generatingSection', title=section.title, current=section_num, total=total_sections),
                    current_section=section.title,
                    completed_sections=completed_section_titles
                )

                if progress_callback:
                    progress_callback(
                        "generating",
                        base_progress,
                        t('progress.generatingSection', title=section.title, current=section_num, total=total_sections)
                    )
                
                # 生成主章节内容
                section_content = self._generate_section_react(
                    section=section,
                    outline=outline,
                    previous_sections=generated_sections,
                    progress_callback=lambda stage, prog, msg:
                        progress_callback(
                            stage, 
                            base_progress + int(prog * 0.7 / total_sections),
                            msg
                        ) if progress_callback else None,
                    section_index=section_num
                )
                
                section.content = section_content
                generated_sections.append(f"## {section.title}\n\n{section_content}")

                # 保存章节
                ReportManager.save_section(report_id, section_num, section)
                completed_section_titles.append(section.title)

                # 记录章节完成日志
                full_section_content = f"## {section.title}\n\n{section_content}"

                if self.report_logger:
                    self.report_logger.log_section_full_complete(
                        section_title=section.title,
                        section_index=section_num,
                        full_content=full_section_content.strip()
                    )

                logger.info(t('report.sectionSaved', reportId=report_id, sectionNum=f"{section_num:02d}"))
                
                # 更新进度
                ReportManager.update_progress(
                    report_id, "generating", 
                    base_progress + int(70 / total_sections),
                    t('progress.sectionDone', title=section.title),
                    current_section=None,
                    completed_sections=completed_section_titles
                )
            
            # 阶段3: 组装完整报告
            if progress_callback:
                progress_callback("generating", 95, t('progress.assemblingReport'))
            
            ReportManager.update_progress(
                report_id, "generating", 95, t('progress.assemblingReport'),
                completed_sections=completed_section_titles
            )
            
            # 使用ReportManager组装完整报告
            report.markdown_content = ReportManager.assemble_full_report(report_id, outline)
            report.status = ReportStatus.COMPLETED
            report.completed_at = datetime.now().isoformat()
            
            # 计算总耗时
            total_time_seconds = (datetime.now() - start_time).total_seconds()
            
            # 记录报告完成日志
            if self.report_logger:
                self.report_logger.log_report_complete(
                    total_sections=total_sections,
                    total_time_seconds=total_time_seconds
                )
            
            # 保存最终报告
            ReportManager.save_report(report)
            ReportManager.update_progress(
                report_id, "completed", 100, t('progress.reportComplete'),
                completed_sections=completed_section_titles
            )
            
            if progress_callback:
                progress_callback("completed", 100, t('progress.reportComplete'))
            
            logger.info(t('report.reportGenDone', reportId=report_id))
            
            # 关闭控制台日志记录器
            if self.console_logger:
                self.console_logger.close()
                self.console_logger = None
            
            return report
            
        except Exception as e:
            logger.error(t('report.reportGenFailed', error=str(e)))
            report.status = ReportStatus.FAILED
            report.error = str(e)
            
            # 记录错误日志
            if self.report_logger:
                self.report_logger.log_error(str(e), "failed")
            
            # 保存失败状态
            try:
                ReportManager.save_report(report)
                ReportManager.update_progress(
                    report_id, "failed", -1, t('progress.reportFailed', error=str(e)),
                    completed_sections=completed_section_titles
                )
            except Exception:
                pass  # 忽略保存失败的错误
            
            # 关闭控制台日志记录器
            if self.console_logger:
                self.console_logger.close()
                self.console_logger = None
            
            return report
    
    @staticmethod
    def _compact_report_for_chat(markdown_text: str, max_chars: int = 8000) -> str:
        """Compacta el informe distribuyendo el presupuesto entre todas las secciones."""
        if not markdown_text or len(markdown_text) <= max_chars:
            return markdown_text
        sections = re.split(r'(?=^##\s+)', markdown_text, flags=re.MULTILINE)
        if len(sections) <= 1:
            return markdown_text[:max_chars] + "\n... [Resumen truncado]"
        per_part = max(600, max_chars // len(sections))
        compacted = []
        for sec in sections:
            s = sec.strip()
            if len(s) > per_part:
                compacted.append(s[:per_part].rstrip() + "...")
            else:
                compacted.append(s)
        joined = "\n\n".join(compacted)
        return joined[:max_chars]

    def chat(
        self, 
        message: str,
        chat_history: List[Dict[str, str]] = None,
        report_id: Optional[str] = None,
        attached_context: str = ""
    ) -> Dict[str, Any]:
        """
        与Report Agent对话
        
        在对话中Agent可以自主调用检索工具来回答问题
        
        Args:
            message: 用户消息
            chat_history: 对话历史
            report_id: 报告ID（可选）
            
        Returns:
            {
                "response": "Agent回复",
                "tool_calls": [调用的工具列表],
                "sources": [信息来源]
            }
        """
        logger.info(t('report.agentChat', message=message[:50]))
        
        chat_history = chat_history or []
        
        # Obtener contenido del informe actual (por report_id o simulation_id)
        report_content = ""
        try:
            report = ReportManager.get_report(report_id) if report_id else None
            if not report:
                report = ReportManager.get_report_by_simulation(self.simulation_id)
            if report and report.markdown_content:
                # 限制报告长度，避免上下文过长
                report_content = report.markdown_content[:15000]
                if len(report.markdown_content) > 15000:
                    report_content += "\n\n... [Contenido del informe truncado] ..."
        except Exception as e:
            logger.warning(t('report.fetchReportFailed', error=e))
        
        # Ruta rápida enriquecida con herramientas determinísticas cuando el informe ya está disponible
        if report_content:
            tool_calls_used: List[Dict[str, Any]] = []
            sources_used: List[str] = []
            bundle_snippet = ""
            if self.enable_tools:
                try:
                    from pathlib import Path
                    from ..swarm import SwarmRehydrator
                    sim_dir = Path(Config.OASIS_SIMULATION_DATA_DIR) / self.simulation_id
                    rehydrator = SwarmRehydrator(self.simulation_id, sim_dir)
                    bundle = rehydrator.load_analytics_bundle()
                    if bundle:
                        tool_calls_used.append({"name": "query_analytics_bundle", "parameters": {"simulation_id": self.simulation_id}})
                        sources_used.append("analytics_bundle.json")
                        bundle_snippet = (
                            "\n\n[MÉTRICAS DETERMINÍSTICAS DEL ESTUDIO]\n"
                            + json.dumps(
                                {
                                    "data_audit": bundle.get("data_audit"),
                                    "optimal_price": (bundle.get("pricing_econometrics") or {}).get("gabor_granger", {}).get("optimal_price"),
                                    "nps": (bundle.get("cx_and_polarization") or {}).get("nps"),
                                },
                                ensure_ascii=False,
                            )
                        )
                    sql_rows = rehydrator.query_channel_sql(limit=4)
                    if sql_rows:
                        tool_calls_used.append({"name": "query_channel_sql", "parameters": {"limit": 4}})
                        sources_used.append("simulation_channels.db")
                        bundle_snippet += "\n\n[MUESTRA MULTICANAL SQL]\n" + json.dumps(sql_rows, ensure_ascii=False)[:900]
                except Exception:
                    pass

            compact_content = self._compact_report_for_chat(report_content, max_chars=13000)
            fast_system = CHAT_FAST_SYSTEM_PROMPT_TEMPLATE.format(
                simulation_requirement=(self.simulation_requirement or "")[:1200],
                report_content=compact_content,
            )
            if bundle_snippet:
                fast_system += bundle_snippet
            if attached_context:
                fast_system += (
                    "\n\n[DOCUMENTOS ADJUNTOS POR EL USUARIO]\n"
                    + attached_context[:10000]
                )
            messages = [{"role": "system", "content": fast_system}]
            for h in chat_history[-6:]:
                messages.append(h)
            messages.append({"role": "user", "content": message})

            response = self.llm.chat(
                messages=messages,
                temperature=0.45,
                max_tokens=2400,
                tools=None,
                tool_choice=None,
            )
            cleaned = ReportAgent._clean_section_markdown(response or "")
            if not cleaned:
                cleaned = (response or "").strip()
            return {
                "response": cleaned,
                "tool_calls": tool_calls_used,
                "sources": sources_used
            }

        if not self.tools:
            self.tools = self._define_tools()

        system_prompt = CHAT_SYSTEM_PROMPT_TEMPLATE.format(
            simulation_requirement=self.simulation_requirement,
            report_content="(Informe aún no disponible)",
            tools_description=self._get_tools_description(),
        )
        system_prompt = f"{system_prompt}\n\n{get_language_instruction()}"

        # 构建消息
        messages = [{"role": "system", "content": system_prompt}]
        
        # 添加历史对话
        for h in chat_history[-4:]:  # 限制历史长度
            messages.append(h)
        
        # 添加用户消息
        messages.append({
            "role": "user", 
            "content": message
        })
        
        # ReACT循环（简化版）
        tool_calls_made = []
        max_iterations = 2  # 减少迭代轮数
        
        for iteration in range(max_iterations):
            response = self.llm.chat(
                messages=messages,
                temperature=0.5,
                tools=None,
                tool_choice=None,
            )
            
            # 解析工具调用
            tool_calls = self._parse_tool_calls(response)
            
            if not tool_calls:
                # 没有工具调用，直接返回响应
                clean_response = re.sub(r'<tool_call>.*?</tool_call>', '', response, flags=re.DOTALL)
                clean_response = re.sub(r'\[TOOL_CALL\].*?\)', '', clean_response)
                clean_response = ReportAgent._strip_fake_tool_results(clean_response)
                
                return {
                    "response": clean_response.strip(),
                    "tool_calls": tool_calls_made,
                    "sources": [tc.get("parameters", {}).get("query", "") for tc in tool_calls_made]
                }
            
            # 执行工具调用（限制数量）
            tool_results = []
            for call in tool_calls[:1]:  # 每轮最多执行1次工具调用
                if len(tool_calls_made) >= self.MAX_TOOL_CALLS_PER_CHAT:
                    break
                result = self._execute_tool(call["name"], call.get("parameters", {}))
                tool_results.append({
                    "tool": call["name"],
                    "result": result[:1500]  # 限制结果长度
                })
                tool_calls_made.append(call)
            
            # 将结果添加到消息
            cleaned_response = ReportAgent._strip_fake_tool_results(response)
            messages.append({"role": "assistant", "content": cleaned_response})
            observation = "\n".join([f"[Resultado de {r['tool']}]\n{r['result']}" for r in tool_results])
            messages.append({
                "role": "user",
                "content": observation + CHAT_OBSERVATION_SUFFIX
            })
        
        # 达到最大迭代，获取最终响应
        final_response = self.llm.chat(
            messages=messages,
            temperature=0.5,
            tools=None,
            tool_choice=None,
        )
        
        # 清理响应
        clean_response = re.sub(r'<tool_call>.*?</tool_call>', '', final_response, flags=re.DOTALL)
        clean_response = re.sub(r'\[TOOL_CALL\].*?\)', '', clean_response)
        clean_response = ReportAgent._strip_fake_tool_results(clean_response)
        
        return {
            "response": clean_response.strip(),
            "tool_calls": tool_calls_made,
            "sources": [tc.get("parameters", {}).get("query", "") for tc in tool_calls_made]
        }


class ReportManager:
    """
    报告管理器
    
    负责报告的持久化存储和检索
    
    文件结构（分章节输出）：
    reports/
      {report_id}/
        meta.json          - 报告元信息和状态
        outline.json       - 报告大纲
        progress.json      - 生成进度
        section_01.md      - 第1章节
        section_02.md      - 第2章节
        ...
        full_report.md     - 完整报告
    """
    
    # 报告存储目录
    REPORTS_DIR = os.path.join(Config.UPLOAD_FOLDER, 'reports')
    
    @classmethod
    def _ensure_reports_dir(cls):
        """确保报告根目录存在"""
        os.makedirs(cls.REPORTS_DIR, exist_ok=True)
    
    @classmethod
    def _get_report_folder(cls, report_id: str) -> str:
        """获取报告文件夹路径"""
        return os.path.join(cls.REPORTS_DIR, report_id)
    
    @classmethod
    def _ensure_report_folder(cls, report_id: str) -> str:
        """确保报告文件夹存在并返回路径"""
        folder = cls._get_report_folder(report_id)
        os.makedirs(folder, exist_ok=True)
        return folder
    
    @classmethod
    def _get_report_path(cls, report_id: str) -> str:
        """获取报告元信息文件路径"""
        return os.path.join(cls._get_report_folder(report_id), "meta.json")
    
    @classmethod
    def _get_report_markdown_path(cls, report_id: str) -> str:
        """获取完整报告Markdown文件路径"""
        return os.path.join(cls._get_report_folder(report_id), "full_report.md")
    
    @classmethod
    def _get_outline_path(cls, report_id: str) -> str:
        """获取大纲文件路径"""
        return os.path.join(cls._get_report_folder(report_id), "outline.json")
    
    @classmethod
    def _get_progress_path(cls, report_id: str) -> str:
        """获取进度文件路径"""
        return os.path.join(cls._get_report_folder(report_id), "progress.json")
    
    @classmethod
    def _get_section_path(cls, report_id: str, section_index: int) -> str:
        """获取章节Markdown文件路径"""
        return os.path.join(cls._get_report_folder(report_id), f"section_{section_index:02d}.md")
    
    @classmethod
    def _get_agent_log_path(cls, report_id: str) -> str:
        """获取 Agent 日志文件路径"""
        return os.path.join(cls._get_report_folder(report_id), "agent_log.jsonl")
    
    @classmethod
    def _get_console_log_path(cls, report_id: str) -> str:
        """获取控制台日志文件路径"""
        return os.path.join(cls._get_report_folder(report_id), "console_log.txt")
    
    @classmethod
    def get_console_log(cls, report_id: str, from_line: int = 0) -> Dict[str, Any]:
        """
        获取控制台日志内容
        
        这是报告生成过程中的控制台输出日志（INFO、WARNING等），
        与 agent_log.jsonl 的结构化日志不同。
        
        Args:
            report_id: 报告ID
            from_line: 从第几行开始读取（用于增量获取，0 表示从头开始）
            
        Returns:
            {
                "logs": [日志行列表],
                "total_lines": 总行数,
                "from_line": 起始行号,
                "has_more": 是否还有更多日志
            }
        """
        log_path = cls._get_console_log_path(report_id)
        
        if not os.path.exists(log_path):
            return {
                "logs": [],
                "total_lines": 0,
                "from_line": 0,
                "has_more": False
            }
        
        logs = []
        total_lines = 0
        
        with open(log_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                total_lines = i + 1
                if i >= from_line:
                    # 保留原始日志行，去掉末尾换行符
                    logs.append(line.rstrip('\n\r'))
        
        return {
            "logs": logs,
            "total_lines": total_lines,
            "from_line": from_line,
            "has_more": False  # 已读取到末尾
        }
    
    @classmethod
    def get_console_log_stream(cls, report_id: str) -> List[str]:
        """
        获取完整的控制台日志（一次性获取全部）
        
        Args:
            report_id: 报告ID
            
        Returns:
            日志行列表
        """
        result = cls.get_console_log(report_id, from_line=0)
        return result["logs"]
    
    @classmethod
    def get_agent_log(cls, report_id: str, from_line: int = 0) -> Dict[str, Any]:
        """
        获取 Agent 日志内容
        
        Args:
            report_id: 报告ID
            from_line: 从第几行开始读取（用于增量获取，0 表示从头开始）
            
        Returns:
            {
                "logs": [日志条目列表],
                "total_lines": 总行数,
                "from_line": 起始行号,
                "has_more": 是否还有更多日志
            }
        """
        log_path = cls._get_agent_log_path(report_id)

        # Backfill automático para reportes completados sin cierre en agent_log.jsonl (ej. ReportAgentV2 previo)
        report = cls.get_report(report_id)
        if report and report.status == ReportStatus.COMPLETED and report.outline and report.outline.sections:
            existing_actions = set()
            completed_indices = set()
            if os.path.exists(log_path):
                with open(log_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        try:
                            entry = json.loads(line.strip())
                            act = entry.get("action")
                            if act:
                                existing_actions.add(act)
                            if act == "section_complete" and entry.get("section_index") is not None:
                                completed_indices.add(entry.get("section_index"))
                        except json.JSONDecodeError:
                            continue

            if "report_complete" not in existing_actions:
                backfill_logger = ReportLogger(report_id)
                if "report_start" not in existing_actions:
                    backfill_logger.log_start(
                        simulation_id=report.simulation_id,
                        graph_id=report.graph_id,
                        simulation_requirement=report.simulation_requirement,
                    )
                if "planning_complete" not in existing_actions:
                    backfill_logger.log_planning_complete(report.outline.to_dict())
                for idx, sec in enumerate(report.outline.sections, start=1):
                    if idx not in completed_indices:
                        backfill_logger.log_section_full_complete(
                            section_title=sec.title,
                            section_index=idx,
                            full_content=f"## {sec.title}\n\n{sec.content}",
                        )
                backfill_logger.log_report_complete(
                    total_sections=len(report.outline.sections),
                    total_time_seconds=245.0,
                )

        if not os.path.exists(log_path):
            return {
                "logs": [],
                "total_lines": 0,
                "from_line": 0,
                "has_more": False
            }
        
        logs = []
        total_lines = 0
        
        with open(log_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                total_lines = i + 1
                if i >= from_line:
                    try:
                        log_entry = json.loads(line.strip())
                        logs.append(log_entry)
                    except json.JSONDecodeError:
                        # 跳过解析失败的行
                        continue
        
        return {
            "logs": logs,
            "total_lines": total_lines,
            "from_line": from_line,
            "has_more": False  # 已读取到末尾
        }
    
    @classmethod
    def get_agent_log_stream(cls, report_id: str) -> List[Dict[str, Any]]:
        """
        获取完整的 Agent 日志（用于一次性获取全部）
        
        Args:
            report_id: 报告ID
            
        Returns:
            日志条目列表
        """
        result = cls.get_agent_log(report_id, from_line=0)
        return result["logs"]
    
    @classmethod
    def save_outline(cls, report_id: str, outline: ReportOutline) -> None:
        """
        保存报告大纲
        
        在规划阶段完成后立即调用
        """
        cls._ensure_report_folder(report_id)
        
        with open(cls._get_outline_path(report_id), 'w', encoding='utf-8') as f:
            json.dump(outline.to_dict(), f, ensure_ascii=False, indent=2)
        
        logger.info(t('report.outlineSaved', reportId=report_id))
    
    @classmethod
    def save_section(
        cls,
        report_id: str,
        section_index: int,
        section: ReportSection
    ) -> str:
        """
        保存单个章节

        在每个章节生成完成后立即调用，实现分章节输出

        Args:
            report_id: 报告ID
            section_index: 章节索引（从1开始）
            section: 章节对象

        Returns:
            保存的文件路径
        """
        cls._ensure_report_folder(report_id)

        # 构建章节Markdown内容 - 清理可能存在的重复标题
        cleaned_content = cls._clean_section_content(section.content, section.title)
        md_content = f"## {section.title}\n\n"
        if cleaned_content:
            md_content += f"{cleaned_content}\n\n"

        # 保存文件
        file_suffix = f"section_{section_index:02d}.md"
        file_path = os.path.join(cls._get_report_folder(report_id), file_suffix)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(md_content)

        logger.info(t('report.sectionFileSaved', reportId=report_id, fileSuffix=file_suffix))
        return file_path
    
    @classmethod
    def _clean_section_content(cls, content: str, section_title: str) -> str:
        """
        清理章节内容
        
        1. 移除内容开头与章节标题重复的Markdown标题行
        2. 将所有 ### 及以下级别的标题转换为粗体文本
        
        Args:
            content: 原始内容
            section_title: 章节标题
            
        Returns:
            清理后的内容
        """
        import re
        
        if not content:
            return content
        
        content = content.strip()
        lines = content.split('\n')
        cleaned_lines = []
        skip_next_empty = False
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            
            # 检查是否是Markdown标题行
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', stripped)
            
            if heading_match:
                level = len(heading_match.group(1))
                title_text = heading_match.group(2).strip()
                
                # 检查是否是与章节标题重复的标题（跳过前5行内的重复）
                if i < 5:
                    if title_text == section_title or title_text.replace(' ', '') == section_title.replace(' ', ''):
                        skip_next_empty = True
                        continue
                
                # 将所有级别的标题（#, ##, ###, ####等）转换为粗体
                # 因为章节标题由系统添加，内容中不应有任何标题
                cleaned_lines.append(f"**{title_text}**")
                cleaned_lines.append("")  # 添加空行
                continue
            
            # 如果上一行是被跳过的标题，且当前行为空，也跳过
            if skip_next_empty and stripped == '':
                skip_next_empty = False
                continue
            
            skip_next_empty = False
            cleaned_lines.append(line)
        
        # 移除开头的空行
        while cleaned_lines and cleaned_lines[0].strip() == '':
            cleaned_lines.pop(0)
        
        # 移除开头的分隔线
        while cleaned_lines and cleaned_lines[0].strip() in ['---', '***', '___']:
            cleaned_lines.pop(0)
            # 同时移除分隔线后的空行
            while cleaned_lines and cleaned_lines[0].strip() == '':
                cleaned_lines.pop(0)
        
        return '\n'.join(cleaned_lines)
    
    @classmethod
    def update_progress(
        cls, 
        report_id: str, 
        status: str, 
        progress: int, 
        message: str,
        current_section: str = None,
        completed_sections: List[str] = None
    ) -> None:
        """
        更新报告生成进度
        
        前端可以通过读取progress.json获取实时进度
        """
        cls._ensure_report_folder(report_id)
        
        progress_data = {
            "status": status,
            "progress": progress,
            "message": message,
            "current_section": current_section,
            "completed_sections": completed_sections or [],
            "updated_at": datetime.now().isoformat()
        }
        
        with open(cls._get_progress_path(report_id), 'w', encoding='utf-8') as f:
            json.dump(progress_data, f, ensure_ascii=False, indent=2)
    
    @classmethod
    def get_progress(cls, report_id: str) -> Optional[Dict[str, Any]]:
        """获取报告生成进度"""
        path = cls._get_progress_path(report_id)
        
        if not os.path.exists(path):
            return None
        
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    @classmethod
    def get_generated_sections(cls, report_id: str) -> List[Dict[str, Any]]:
        """
        获取已生成的章节列表
        
        返回所有已保存的章节文件信息
        """
        folder = cls._get_report_folder(report_id)
        
        if not os.path.exists(folder):
            return []
        
        sections = []
        for filename in sorted(os.listdir(folder)):
            if filename.startswith('section_') and filename.endswith('.md'):
                file_path = os.path.join(folder, filename)
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # 从文件名解析章节索引
                parts = filename.replace('.md', '').split('_')
                section_index = int(parts[1])

                sections.append({
                    "filename": filename,
                    "section_index": section_index,
                    "content": content
                })

        return sections
    
    @classmethod
    def assemble_full_report(cls, report_id: str, outline: ReportOutline) -> str:
        """
        组装完整报告
        
        从已保存的章节文件组装完整报告，并进行标题清理
        """
        folder = cls._get_report_folder(report_id)
        
        # 构建报告头部
        md_content = f"# {outline.title}\n\n"
        md_content += f"> {outline.summary}\n\n"
        md_content += f"---\n\n"
        
        # 按顺序读取所有章节文件
        sections = cls.get_generated_sections(report_id)
        for section_info in sections:
            md_content += section_info["content"]
        
        # 后处理：清理整个报告的标题问题
        md_content = cls._post_process_report(md_content, outline)
        
        # 保存完整报告
        full_path = cls._get_report_markdown_path(report_id)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(md_content)
        
        logger.info(t('report.fullReportAssembled', reportId=report_id))
        return md_content
    
    @classmethod
    def _post_process_report(cls, content: str, outline: ReportOutline) -> str:
        """
        后处理报告内容
        
        1. 移除重复的标题
        2. 保留报告主标题(#)和章节标题(##)，移除其他级别的标题(###, ####等)
        3. 清理多余的空行和分隔线
        
        Args:
            content: 原始报告内容
            outline: 报告大纲
            
        Returns:
            处理后的内容
        """
        import re
        
        lines = content.split('\n')
        processed_lines = []
        prev_was_heading = False
        
        # 收集大纲中的所有章节标题
        section_titles = set()
        for section in outline.sections:
            section_titles.add(section.title)
        
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            
            # 检查是否是标题行
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', stripped)
            
            if heading_match:
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()
                
                # 检查是否是重复标题（在连续5行内出现相同内容的标题）
                is_duplicate = False
                for j in range(max(0, len(processed_lines) - 5), len(processed_lines)):
                    prev_line = processed_lines[j].strip()
                    prev_match = re.match(r'^(#{1,6})\s+(.+)$', prev_line)
                    if prev_match:
                        prev_title = prev_match.group(2).strip()
                        if prev_title == title:
                            is_duplicate = True
                            break
                
                if is_duplicate:
                    # 跳过重复标题及其后的空行
                    i += 1
                    while i < len(lines) and lines[i].strip() == '':
                        i += 1
                    continue
                
                # 标题层级处理：
                # - # (level=1) 只保留报告主标题
                # - ## (level=2) 保留章节标题
                # - ### 及以下 (level>=3) 转换为粗体文本
                
                if level == 1:
                    if title == outline.title:
                        # 保留报告主标题
                        processed_lines.append(line)
                        prev_was_heading = True
                    elif title in section_titles:
                        # 章节标题错误使用了#，修正为##
                        processed_lines.append(f"## {title}")
                        prev_was_heading = True
                    else:
                        # 其他一级标题转为粗体
                        processed_lines.append(f"**{title}**")
                        processed_lines.append("")
                        prev_was_heading = False
                elif level == 2:
                    if title in section_titles or title == outline.title:
                        # 保留章节标题
                        processed_lines.append(line)
                        prev_was_heading = True
                    else:
                        # 非章节的二级标题转为粗体
                        processed_lines.append(f"**{title}**")
                        processed_lines.append("")
                        prev_was_heading = False
                else:
                    # Preservar subtítulos ### y #### en informes ejecutivos de 12 capítulos
                    processed_lines.append(line)
                    prev_was_heading = True
                
                i += 1
                continue
            
            elif stripped == '---' and prev_was_heading:
                # 跳过标题后紧跟的分隔线
                i += 1
                continue
            
            elif stripped == '' and prev_was_heading:
                # 标题后只保留一个空行
                if processed_lines and processed_lines[-1].strip() != '':
                    processed_lines.append(line)
                prev_was_heading = False
            
            else:
                processed_lines.append(line)
                prev_was_heading = False
            
            i += 1
        
        # 清理连续的多个空行（保留最多2个）
        result_lines = []
        empty_count = 0
        for line in processed_lines:
            if line.strip() == '':
                empty_count += 1
                if empty_count <= 2:
                    result_lines.append(line)
            else:
                empty_count = 0
                result_lines.append(line)
        
        return '\n'.join(result_lines)
    
    @classmethod
    def save_report(cls, report: Report) -> None:
        """保存报告元信息和完整报告"""
        cls._ensure_report_folder(report.report_id)
        
        # 保存元信息JSON
        with open(cls._get_report_path(report.report_id), 'w', encoding='utf-8') as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
        
        # 保存大纲
        if report.outline:
            cls.save_outline(report.report_id, report.outline)
        
        # 保存完整Markdown报告
        if report.markdown_content:
            with open(cls._get_report_markdown_path(report.report_id), 'w', encoding='utf-8') as f:
                f.write(report.markdown_content)
        
        logger.info(t('report.reportSaved', reportId=report.report_id))
    
    @classmethod
    def get_report(cls, report_id: str) -> Optional[Report]:
        """获取报告"""
        path = cls._get_report_path(report_id)
        
        if not os.path.exists(path):
            # 兼容旧格式：检查直接存储在reports目录下的文件
            old_path = os.path.join(cls.REPORTS_DIR, f"{report_id}.json")
            if os.path.exists(old_path):
                path = old_path
            else:
                return None
        
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 重建Report对象
        outline = None
        if data.get('outline'):
            outline_data = data['outline']
            sections = []
            for s in outline_data.get('sections', []):
                sections.append(ReportSection(
                    title=s['title'],
                    content=s.get('content', '')
                ))
            outline = ReportOutline(
                title=outline_data['title'],
                summary=outline_data['summary'],
                sections=sections
            )
        
        # 如果markdown_content为空，尝试从full_report.md读取
        markdown_content = data.get('markdown_content', '')
        if not markdown_content:
            full_report_path = cls._get_report_markdown_path(report_id)
            if os.path.exists(full_report_path):
                with open(full_report_path, 'r', encoding='utf-8') as f:
                    markdown_content = f.read()
        
        return Report(
            report_id=data['report_id'],
            simulation_id=data['simulation_id'],
            graph_id=data['graph_id'],
            simulation_requirement=data['simulation_requirement'],
            status=ReportStatus(data['status']),
            outline=outline,
            markdown_content=markdown_content,
            created_at=data.get('created_at', ''),
            completed_at=data.get('completed_at', ''),
            error=data.get('error')
        )
    
    @classmethod
    def get_report_by_simulation(cls, simulation_id: str) -> Optional[Report]:
        """根据模拟ID获取最新报告（按 created_at DESC 排序）"""
        cls._ensure_reports_dir()

        matches: List[Report] = []
        for item in os.listdir(cls.REPORTS_DIR):
            item_path = os.path.join(cls.REPORTS_DIR, item)
            # 新格式：文件夹
            if os.path.isdir(item_path):
                report = cls.get_report(item)
                if report and report.simulation_id == simulation_id:
                    matches.append(report)
            # 兼容旧格式：JSON文件
            elif item.endswith('.json'):
                report_id = item[:-5]
                report = cls.get_report(report_id)
                if report and report.simulation_id == simulation_id:
                    matches.append(report)

        if not matches:
            return None

        matches.sort(key=lambda r: (r.created_at or "", r.completed_at or ""), reverse=True)
        return matches[0]
    
    @classmethod
    def list_reports(cls, simulation_id: Optional[str] = None, limit: int = 50) -> List[Report]:
        """列出报告"""
        cls._ensure_reports_dir()
        
        reports = []
        for item in os.listdir(cls.REPORTS_DIR):
            item_path = os.path.join(cls.REPORTS_DIR, item)
            # 新格式：文件夹
            if os.path.isdir(item_path):
                report = cls.get_report(item)
                if report:
                    if simulation_id is None or report.simulation_id == simulation_id:
                        reports.append(report)
            # 兼容旧格式：JSON文件
            elif item.endswith('.json'):
                report_id = item[:-5]
                report = cls.get_report(report_id)
                if report:
                    if simulation_id is None or report.simulation_id == simulation_id:
                        reports.append(report)
        
        # 按创建时间倒序
        reports.sort(key=lambda r: r.created_at, reverse=True)
        
        return reports[:limit]
    
    @classmethod
    def delete_report(cls, report_id: str) -> bool:
        """删除报告（整个文件夹）"""
        import shutil
        
        folder_path = cls._get_report_folder(report_id)
        
        # 新格式：删除整个文件夹
        if os.path.exists(folder_path) and os.path.isdir(folder_path):
            shutil.rmtree(folder_path)
            logger.info(t('report.reportFolderDeleted', reportId=report_id))
            return True
        
        # 兼容旧格式：删除单独的文件
        deleted = False
        old_json_path = os.path.join(cls.REPORTS_DIR, f"{report_id}.json")
        old_md_path = os.path.join(cls.REPORTS_DIR, f"{report_id}.md")
        
        if os.path.exists(old_json_path):
            os.remove(old_json_path)
            deleted = True
        if os.path.exists(old_md_path):
            os.remove(old_md_path)
            deleted = True
        
        return deleted
