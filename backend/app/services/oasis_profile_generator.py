"""
OASIS Agent Profile生成器
将Zep图谱中的实体转换为OASIS模拟平台所需的Agent Profile格式

优化改进：
1. 调用Zep检索功能二次丰富节点信息
2. 优化提示词生成非常详细的人设
3. 区分个人实体和抽象群体实体
"""

import json
import random
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

from openai import OpenAI
from ..config import Config
from ..utils.logger import get_logger
from ..utils.locale import get_language_instruction, get_locale, set_locale, t
from ..utils.openai_chat_compat import create_chat_completion, extract_chat_completion_text
from ..utils.zep import (
    call_zep_read_with_retry,
    get_zep_client,
    is_retryable_zep_error,
    normalize_zep_search_query,
)
from .zep_entity_reader import EntityNode, NON_HUMAN_ENTITY_TYPES_LOWER, ZepEntityReader
from .demographic_sampler import DemographicAllocation, DemographicSampler, MBTI_POOL

logger = get_logger('mirofish.oasis_profile')


def _coerce_to_str(value: Any) -> str:
    """Coerce a value to a plain string.

    Handles dict, list, and other non-string types that may be returned
    by LLM JSON parsing.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ('text', 'value', 'description', 'content', 'summary', 'name'):
            if key in value:
                candidate = _coerce_to_str(value[key])
                if candidate:
                    return candidate
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        str_items = [_coerce_to_str(item) for item in value]
        str_items = [item for item in str_items if item]
        return ', '.join(str_items)
    return str(value)


def _coerce_to_str_list(value: Any) -> List[str]:
    """Coerce a value to a list of strings.

    Handles nested structures that may be returned by LLM JSON parsing.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        result: List[str] = []
        for item in value:
            if isinstance(item, (list, tuple)):
                result.extend(_coerce_to_str_list(item))
            else:
                text = _coerce_to_str(item)
                if text:
                    result.append(text)
        return result
    text = _coerce_to_str(value)
    return [text] if text else []


@dataclass
class OasisAgentProfile:
    """OASIS Agent Profile数据结构"""
    # 通用字段
    user_id: int
    user_name: str
    name: str
    bio: str
    persona: str

    # 可选字段 - Reddit风格
    karma: int = 1000
    
    # 可选字段 - Twitter风格
    friend_count: int = 100
    follower_count: int = 150
    statuses_count: int = 500
    
    # 额外人设信息
    age: Optional[int] = None
    gender: Optional[str] = None
    mbti: Optional[str] = None
    country: Optional[str] = None
    profession: Optional[str] = None
    interested_topics: List[str] = field(default_factory=list)

    # Capas demográfica estática y dinámica por estudio (Fase 2 - retrocompatible)
    country_code: str = "co"
    city_name: Optional[str] = None
    divipola_code: Optional[str] = None
    region_macro: Optional[str] = None
    stratum_code: Optional[str] = None
    wealth_tier_norm: Optional[int] = None
    income_band_local: Optional[str] = None
    static_archetype_code: Optional[str] = None
    dynamic_study_role: Optional[str] = None
    attitude_segment: Optional[str] = None
    digital_trust_level: Optional[str] = None
    preferred_channels: List[str] = field(default_factory=list)
    willingness_to_pay_band: Optional[str] = None
    purchase_probability: Optional[float] = None
    detailed_persona: Optional[str] = None
    
    # 来源实体信息
    source_entity_uuid: Optional[str] = None
    source_entity_type: Optional[str] = None
    
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    
    def __post_init__(self):
        """Normalize structured LLM fields once at the profile boundary."""
        self.bio = _coerce_to_str(self.bio) or self.name
        raw_persona = _coerce_to_str(self.persona) or (
            f"{self.name} participa en conversaciones sociales y evalúa servicios con criterio práctico."
        )
        if not self.detailed_persona:
            self.detailed_persona = raw_persona
        if len(raw_persona) > 600:
            self.persona = raw_persona[:597].rstrip() + "..."
        else:
            self.persona = raw_persona

        country_clean = _coerce_to_str(self.country)
        self.country = country_clean or "Colombia"

        self.profession = _coerce_to_str(self.profession) or None
        self.gender = _coerce_to_str(self.gender) or None
        self.mbti = _coerce_to_str(self.mbti) or None
        self.interested_topics = _coerce_to_str_list(self.interested_topics)
        self.preferred_channels = _coerce_to_str_list(self.preferred_channels)

    def _demographic_extras(self) -> Dict[str, Any]:
        extras: Dict[str, Any] = {
            "country_code": self.country_code,
        }
        optional_fields = {
            "city_name": self.city_name,
            "divipola_code": self.divipola_code,
            "region_macro": self.region_macro,
            "stratum_code": self.stratum_code,
            "wealth_tier_norm": self.wealth_tier_norm,
            "income_band_local": self.income_band_local,
            "static_archetype_code": self.static_archetype_code,
            "dynamic_study_role": self.dynamic_study_role,
            "attitude_segment": self.attitude_segment,
            "digital_trust_level": self.digital_trust_level,
            "willingness_to_pay_band": self.willingness_to_pay_band,
            "purchase_probability": self.purchase_probability,
        }
        for key, val in optional_fields.items():
            if val is not None:
                extras[key] = val
        if self.preferred_channels:
            extras["preferred_channels"] = self.preferred_channels
        return extras

    def to_reddit_format(self) -> Dict[str, Any]:
        """转换为Reddit平台格式"""
        profile = {
            "user_id": self.user_id,
            "username": self.user_name,  # OASIS 库要求字段名为 username（无下划线）
            "name": self.name,
            "bio": self.bio,
            "persona": self.persona,
            "karma": self.karma,
            "created_at": self.created_at,
        }
        
        # 添加额外人设信息（确保关键字段始终存在，防止 OASIS generate_reddit_agent_graph 发生 KeyError）
        profile["age"] = self.age if self.age is not None else 32
        profile["gender"] = self.gender if self.gender else "other"
        profile["mbti"] = self.mbti if self.mbti else "ENTP"
        profile["country"] = self.country if self.country else "Colombia"
        if self.profession:
            profile["profession"] = self.profession
        if self.interested_topics:
            profile["interested_topics"] = self.interested_topics
        profile.update(self._demographic_extras())
        
        return profile
    
    def to_twitter_format(self) -> Dict[str, Any]:
        """转换为Twitter平台格式"""
        profile = {
            "user_id": self.user_id,
            "username": self.user_name,  # OASIS 库要求字段名为 username（无下划线）
            "name": self.name,
            "bio": self.bio,
            "persona": self.persona,
            "friend_count": self.friend_count,
            "follower_count": self.follower_count,
            "statuses_count": self.statuses_count,
            "created_at": self.created_at,
        }
        
        # 添加额外人设信息
        if self.age:
            profile["age"] = self.age
        if self.gender:
            profile["gender"] = self.gender
        if self.mbti:
            profile["mbti"] = self.mbti
        if self.country:
            profile["country"] = self.country
        if self.profession:
            profile["profession"] = self.profession
        if self.interested_topics:
            profile["interested_topics"] = self.interested_topics
        profile.update(self._demographic_extras())
        
        return profile
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为完整字典格式"""
        payload = {
            "user_id": self.user_id,
            "user_name": self.user_name,
            "name": self.name,
            "bio": self.bio,
            "persona": self.persona,
            "detailed_persona": self.detailed_persona,
            "karma": self.karma,
            "friend_count": self.friend_count,
            "follower_count": self.follower_count,
            "statuses_count": self.statuses_count,
            "age": self.age,
            "gender": self.gender,
            "mbti": self.mbti,
            "country": self.country,
            "profession": self.profession,
            "interested_topics": self.interested_topics,
            "source_entity_uuid": self.source_entity_uuid,
            "source_entity_type": self.source_entity_type,
            "created_at": self.created_at,
        }
        payload.update(self._demographic_extras())
        return payload


class OasisProfileGenerator:
    """
    OASIS Profile生成器
    
    将Zep图谱中的实体转换为OASIS模拟所需的Agent Profile
    
    优化特性：
    1. 调用Zep图谱检索功能获取更丰富的上下文
    2. 生成非常详细的人设（包括基本信息、职业经历、性格特征、社交媒体行为等）
    3. 区分个人实体和抽象群体实体
    """
    
    # MBTI类型列表
    MBTI_TYPES = [
        "INTJ", "INTP", "ENTJ", "ENTP",
        "INFJ", "INFP", "ENFJ", "ENFP",
        "ISTJ", "ISFJ", "ESTJ", "ESFJ",
        "ISTP", "ISFP", "ESTP", "ESFP"
    ]
    
    # 常见国家列表 (LATAM / Colombia prioritario)
    COUNTRIES = [
        "Colombia", "México", "Perú", "Chile", "Ecuador", "Argentina"
    ]
    
    # 个人类型实体（需要生成具体人设）
    INDIVIDUAL_ENTITY_TYPES = [
        "student", "alumni", "professor", "person", "publicfigure",
        "expert", "faculty", "official", "journalist", "activist",
        "citizen", "consumer", "driver", "merchant", "claimant", "worker"
    ]
    
    # 群体/机构类型实体（需要生成群体代表人设）
    GROUP_ENTITY_TYPES = [
        "university", "governmentagency", "organization", "ngo",
        "mediaoutlet", "company", "institution", "group", "community",
        "insurancecompany", "regulator", "association"
    ]
    
    def __init__(
        self, 
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        zep_api_key: Optional[str] = None,
        graph_id: Optional[str] = None,
        country_code: str = "co",
        target_cities: Optional[List[str]] = None,
        target_strata: Optional[List[str]] = None,
    ):
        self.api_key = api_key or Config.LLM_API_KEY
        self.base_url = base_url or Config.LLM_BASE_URL
        self.model_name = model_name or Config.LLM_MODEL_NAME
        self.country_code = (country_code or "co").strip().lower()
        self.target_cities = target_cities
        self.target_strata = target_strata
        self.sampler = DemographicSampler(country_code=self.country_code)
        
        if not self.api_key:
            raise ValueError("LLM_API_KEY 未配置")
        
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )
        
        # Zep客户端用于检索丰富上下文
        self.zep_api_key = zep_api_key or Config.ZEP_API_KEY
        self.zep_client = None
        self.graph_id = graph_id
        
        if self.zep_api_key:
            try:
                self.zep_client = get_zep_client(self.zep_api_key)
            except Exception as e:
                logger.warning(f"Zep客户端初始化失败: {e}")
    
    def generate_profile_from_entity(
        self, 
        entity: EntityNode, 
        user_id: int,
        use_llm: bool = True,
        allocation: Optional[DemographicAllocation] = None
    ) -> OasisAgentProfile:
        """
        从Zep实体生成OASIS Agent Profile
        
        Args:
            entity: Zep实体节点
            user_id: 用户ID（用于OASIS）
            use_llm: 是否使用LLM生成详细人设
            allocation: Cuota sociodemográfica estratificada asignada al agente
            
        Returns:
            OasisAgentProfile
        """
        entity_type = entity.get_entity_type() or "Entity"
        alloc = allocation or self.sampler.sample_allocations(
            count=1,
            country_code=self.country_code,
            target_cities=self.target_cities,
            target_strata=self.target_strata,
            entities=[entity],
            seed=42 + user_id,
        )[0]
        
        # 基础信息
        name = entity.name
        user_name = self._generate_username(name)
        
        # 构建上下文信息
        context = self._build_entity_context(entity)
        
        if use_llm:
            # 使用LLM生成详细人设
            profile_data = self._generate_profile_with_llm(
                entity_name=name,
                entity_type=entity_type,
                entity_summary=entity.summary,
                entity_attributes=entity.attributes,
                context=context,
                allocation=alloc,
            )
        else:
            # 使用规则生成基础人设
            profile_data = self._generate_profile_rule_based(
                entity_name=name,
                entity_type=entity_type,
                entity_summary=entity.summary,
                entity_attributes=entity.attributes,
                allocation=alloc,
            )
        
        raw_persona = profile_data.get("persona") or entity.summary or f"{name} ({alloc.city_name}, {alloc.stratum_code})."
        raw_country = profile_data.get("country") or alloc.country_name
        if str(raw_country).strip() in {"", "中国", "China"}:
            raw_country = alloc.country_name
        raw_mbti = profile_data.get("mbti") or alloc.mbti

        return OasisAgentProfile(
            user_id=user_id,
            user_name=user_name,
            name=name,
            bio=profile_data.get("bio", f"{alloc.dynamic_study_role} en {alloc.city_name} ({alloc.stratum_code})"),
            persona=raw_persona,
            detailed_persona=raw_persona,
            karma=profile_data.get("karma", random.randint(500, 5000)),
            friend_count=profile_data.get("friend_count", random.randint(50, 500)),
            follower_count=profile_data.get("follower_count", random.randint(100, 1000)),
            statuses_count=profile_data.get("statuses_count", random.randint(100, 2000)),
            age=profile_data.get("age") or alloc.age,
            gender=profile_data.get("gender") or alloc.gender,
            mbti=raw_mbti,
            country=raw_country,
            profession=profile_data.get("profession") or alloc.dynamic_study_role,
            interested_topics=profile_data.get("interested_topics", []),
            country_code=alloc.country_code,
            city_name=alloc.city_name,
            divipola_code=alloc.divipola_code,
            region_macro=alloc.region_macro,
            stratum_code=alloc.stratum_code,
            wealth_tier_norm=alloc.wealth_tier_norm,
            income_band_local=alloc.income_band_local,
            static_archetype_code=alloc.static_archetype_code,
            dynamic_study_role=alloc.dynamic_study_role,
            attitude_segment=alloc.attitude_segment,
            digital_trust_level=alloc.digital_trust_level,
            preferred_channels=alloc.preferred_channels,
            willingness_to_pay_band=alloc.willingness_to_pay_band,
            purchase_probability=alloc.purchase_probability,
            source_entity_uuid=entity.uuid,
            source_entity_type=entity_type,
        )
    
    def _generate_username(self, name: str) -> str:
        """生成用户名"""
        # 移除特殊字符，转换为小写
        username = name.lower().replace(" ", "_")
        username = ''.join(c for c in username if c.isalnum() or c == '_')
        
        # 添加随机后缀避免重复
        suffix = random.randint(100, 999)
        return f"{username}_{suffix}"
    
    def _search_zep_for_entity(self, entity: EntityNode) -> Dict[str, Any]:
        """
        使用Zep图谱混合搜索功能获取实体相关的丰富信息
        
        Zep没有内置混合搜索接口，需要分别搜索edges和nodes然后合并结果。
        使用并行请求同时搜索，提高效率。
        
        Args:
            entity: 实体节点对象
            
        Returns:
            包含facts, node_summaries, context的字典
        """
        import concurrent.futures
        
        if not self.zep_client:
            return {"facts": [], "node_summaries": [], "context": ""}
        
        entity_name = entity.name
        
        results = {
            "facts": [],
            "node_summaries": [],
            "context": ""
        }
        
        # 必须有graph_id才能进行搜索
        if not self.graph_id:
            logger.debug(f"跳过Zep检索：未设置graph_id")
            return results
        
        comprehensive_query = normalize_zep_search_query(
            t('progress.zepSearchQuery', name=entity_name)
        )
        
        def search_edges():
            """搜索边（事实/关系）- 带重试机制"""
            return call_zep_read_with_retry(
                lambda: self.zep_client.graph.search(
                        query=comprehensive_query,
                        graph_id=self.graph_id,
                        limit=30,
                        scope="edges",
                        reranker="rrf"
                ),
                operation_name=f"profile edge search ({entity.uuid})",
            )
        
        def search_nodes():
            """搜索节点（实体摘要）- 带重试机制"""
            return call_zep_read_with_retry(
                lambda: self.zep_client.graph.search(
                        query=comprehensive_query,
                        graph_id=self.graph_id,
                        limit=20,
                        scope="nodes",
                        reranker="rrf"
                ),
                operation_name=f"profile node search ({entity.uuid})",
            )
        
        try:
            # 并行执行edges和nodes搜索
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                edge_future = executor.submit(search_edges)
                node_future = executor.submit(search_nodes)
                
                # 获取结果
                # Each request already has the configured HTTP timeout and
                # typed retry budget. A second hard-coded 30s future timeout
                # discarded late successes while the executor still waited.
                edge_result = edge_future.result()
                node_result = node_future.result()
            
            # 处理边搜索结果
            all_facts = set()
            if edge_result and hasattr(edge_result, 'edges') and edge_result.edges:
                for edge in edge_result.edges:
                    if hasattr(edge, 'fact') and edge.fact:
                        all_facts.add(edge.fact)
            results["facts"] = list(all_facts)
            
            # 处理节点搜索结果
            all_summaries = set()
            if node_result and hasattr(node_result, 'nodes') and node_result.nodes:
                for node in node_result.nodes:
                    if hasattr(node, 'summary') and node.summary:
                        all_summaries.add(node.summary)
                    if hasattr(node, 'name') and node.name and node.name != entity_name:
                        all_summaries.add(f"相关实体: {node.name}")
            results["node_summaries"] = list(all_summaries)
            
            # 构建综合上下文
            context_parts = []
            if results["facts"]:
                context_parts.append("事实信息:\n" + "\n".join(f"- {f}" for f in results["facts"][:20]))
            if results["node_summaries"]:
                context_parts.append("相关实体:\n" + "\n".join(f"- {s}" for s in results["node_summaries"][:10]))
            results["context"] = "\n\n".join(context_parts)
            
            logger.info(f"Zep混合检索完成: {entity_name}, 获取 {len(results['facts'])} 条事实, {len(results['node_summaries'])} 个相关节点")
            
        except Exception as e:
            logger.warning(f"Zep检索失败 ({entity_name}): {e}")
            if not is_retryable_zep_error(e):
                raise
        
        return results
    
    def _build_entity_context(self, entity: EntityNode) -> str:
        """
        构建实体的完整上下文信息
        
        包括：
        1. 实体本身的边信息（事实）
        2. 关联节点的详细信息
        3. Zep混合检索到的丰富信息
        """
        context_parts = []
        
        # 1. 添加实体属性信息
        if entity.attributes:
            attrs = []
            for key, value in entity.attributes.items():
                if value and str(value).strip():
                    attrs.append(f"- {key}: {value}")
            if attrs:
                context_parts.append("### 实体属性\n" + "\n".join(attrs))
        
        # 2. 添加相关边信息（事实/关系）
        existing_facts = set()
        if entity.related_edges:
            relationships = []
            for edge in entity.related_edges:  # 不限制数量
                fact = edge.get("fact", "")
                edge_name = edge.get("edge_name", "")
                direction = edge.get("direction", "")
                
                if fact:
                    relationships.append(f"- {fact}")
                    existing_facts.add(fact)
                elif edge_name:
                    if direction == "outgoing":
                        relationships.append(f"- {entity.name} --[{edge_name}]--> (相关实体)")
                    else:
                        relationships.append(f"- (相关实体) --[{edge_name}]--> {entity.name}")
            
            if relationships:
                context_parts.append("### 相关事实和关系\n" + "\n".join(relationships))
        
        # 3. 添加关联节点的详细信息
        if entity.related_nodes:
            related_info = []
            for node in entity.related_nodes:  # 不限制数量
                node_name = node.get("name", "")
                node_labels = node.get("labels", [])
                node_summary = node.get("summary", "")
                
                # 过滤掉默认标签
                custom_labels = [l for l in node_labels if l not in ["Entity", "Node"]]
                label_str = f" ({', '.join(custom_labels)})" if custom_labels else ""
                
                if node_summary:
                    related_info.append(f"- **{node_name}**{label_str}: {node_summary}")
                else:
                    related_info.append(f"- **{node_name}**{label_str}")
            
            if related_info:
                context_parts.append("### 关联实体信息\n" + "\n".join(related_info))
        
        # 4. 使用Zep混合检索获取更丰富的信息
        zep_results = self._search_zep_for_entity(entity)
        
        if zep_results.get("facts"):
            # 去重：排除已存在的事实
            new_facts = [f for f in zep_results["facts"] if f not in existing_facts]
            if new_facts:
                context_parts.append("### Zep检索到的事实信息\n" + "\n".join(f"- {f}" for f in new_facts[:15]))
        
        if zep_results.get("node_summaries"):
            context_parts.append("### Zep检索到的相关节点\n" + "\n".join(f"- {s}" for s in zep_results["node_summaries"][:10]))
        
        return "\n\n".join(context_parts)
    
    def _is_individual_entity(self, entity_type: str) -> bool:
        """判断是否是个人类型实体"""
        return entity_type.lower() in self.INDIVIDUAL_ENTITY_TYPES
    
    def _is_group_entity(self, entity_type: str) -> bool:
        """判断是否是群体/机构类型实体"""
        return entity_type.lower() in self.GROUP_ENTITY_TYPES
    
    def _generate_profile_with_llm(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        entity_attributes: Dict[str, Any],
        context: str,
        allocation: Optional[DemographicAllocation] = None
    ) -> Dict[str, Any]:
        """
        Genera el perfil detallado usando LLM con restricción demográfica y actitudinal.
        """
        is_individual = self._is_individual_entity(entity_type)
        
        if is_individual:
            prompt = self._build_individual_persona_prompt(
                entity_name, entity_type, entity_summary, entity_attributes, context, allocation
            )
        else:
            prompt = self._build_group_persona_prompt(
                entity_name, entity_type, entity_summary, entity_attributes, context, allocation
            )

        max_attempts = 3
        last_error = None
        
        for attempt in range(max_attempts):
            try:
                response = create_chat_completion(
                    self.client,
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": self._get_system_prompt(is_individual)},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.65 - (attempt * 0.1),
                    max_tokens=700,
                )
                
                content = extract_chat_completion_text(response)
                finish_reason = response.choices[0].finish_reason
                if finish_reason == 'length':
                    logger.warning(f"Salida LLM truncada (intento {attempt+1}), intentando reparar...")
                    content = self._fix_truncated_json(content)
                
                try:
                    result = json.loads(content)
                    if "bio" not in result or not result["bio"]:
                        result["bio"] = entity_summary[:200] if entity_summary else f"{entity_type}: {entity_name}"
                    if "persona" not in result or not result["persona"]:
                        result["persona"] = entity_summary or f"{entity_name} ({entity_type})."
                    return result
                except json.JSONDecodeError as je:
                    logger.warning(f"Fallo al parsear JSON de perfil (intento {attempt+1}): {str(je)[:80]}")
                    result = self._try_fix_json(content, entity_name, entity_type, entity_summary)
                    if result.get("_fixed"):
                        del result["_fixed"]
                        return result
                    last_error = je
                    
            except Exception as e:
                logger.warning(f"Error en llamada LLM de perfil (intento {attempt+1}): {str(e)[:80]}")
                last_error = e
                time.sleep(1 * (attempt + 1))
        
        logger.warning(f"Fallo LLM generando perfil tras {max_attempts} intentos: {last_error}; usando respaldo por reglas.")
        return self._generate_profile_rule_based(
            entity_name, entity_type, entity_summary, entity_attributes, allocation=allocation
        )
    
    def _fix_truncated_json(self, content: str) -> str:
        """修复被截断的JSON（输出被max_tokens限制截断）"""
        import re
        
        # 如果JSON被截断，尝试闭合它
        content = content.strip()
        
        # 计算未闭合的括号
        open_braces = content.count('{') - content.count('}')
        open_brackets = content.count('[') - content.count(']')
        
        # 检查是否有未闭合的字符串
        # 简单检查：如果最后一个引号后没有逗号或闭合括号，可能是字符串被截断
        if content and content[-1] not in '",}]':
            # 尝试闭合字符串
            content += '"'
        
        # 闭合括号
        content += ']' * open_brackets
        content += '}' * open_braces
        
        return content
    
    def _try_fix_json(self, content: str, entity_name: str, entity_type: str, entity_summary: str = "") -> Dict[str, Any]:
        """尝试修复损坏的JSON"""
        import re
        
        # 1. 首先尝试修复被截断的情况
        content = self._fix_truncated_json(content)
        
        # 2. 尝试提取JSON部分
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            json_str = json_match.group()
            
            # 3. 处理字符串中的换行符问题
            # 找到所有字符串值并替换其中的换行符
            def fix_string_newlines(match):
                s = match.group(0)
                # 替换字符串内的实际换行符为空格
                s = s.replace('\n', ' ').replace('\r', ' ')
                # 替换多余空格
                s = re.sub(r'\s+', ' ', s)
                return s
            
            # 匹配JSON字符串值
            json_str = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', fix_string_newlines, json_str)
            
            # 4. 尝试解析
            try:
                result = json.loads(json_str)
                result["_fixed"] = True
                return result
            except json.JSONDecodeError as e:
                # 5. 如果还是失败，尝试更激进的修复
                try:
                    # 移除所有控制字符
                    json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', json_str)
                    # 替换所有连续空白
                    json_str = re.sub(r'\s+', ' ', json_str)
                    result = json.loads(json_str)
                    result["_fixed"] = True
                    return result
                except:
                    pass
        
        # 6. 尝试从内容中提取部分信息
        bio_match = re.search(r'"bio"\s*:\s*"([^"]*)"', content)
        persona_match = re.search(r'"persona"\s*:\s*"([^"]*)', content)  # 可能被截断
        
        bio = bio_match.group(1) if bio_match else (entity_summary[:200] if entity_summary else f"{entity_type}: {entity_name}")
        persona = persona_match.group(1) if persona_match else (entity_summary or f"{entity_name}是一个{entity_type}。")
        
        # 如果提取到了有意义的内容，标记为已修复
        if bio_match or persona_match:
            logger.info(f"从损坏的JSON中提取了部分信息")
            return {
                "bio": bio,
                "persona": persona,
                "_fixed": True
            }
        
        # 7. 完全失败，返回基础结构
        logger.warning(f"JSON修复失败，返回基础结构")
        return {
            "bio": entity_summary[:200] if entity_summary else f"{entity_type}: {entity_name}",
            "persona": entity_summary or f"{entity_name}是一个{entity_type}。"
        }
    
    def _get_system_prompt(self, is_individual: bool) -> str:
        """Prompt de sistema 100% en español para perfiles socio-demográficos realistas."""
        role_hint = "ciudadanos y consumidores reales" if is_individual else "actores institucionales, empresas o gremios"
        base_prompt = (
            f"Eres un especialista en investigación de mercados y construcción de perfiles sintéticos ({role_hint}) "
            "para LATAM/Colombia. Devuelve ÚNICAMENTE un objeto JSON válido, sin markdown ni saltos de línea sin escapar."
        )
        return f"{base_prompt}\n\n{get_language_instruction()}"
    
    def _build_individual_persona_prompt(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        entity_attributes: Dict[str, Any],
        context: str,
        allocation: Optional[DemographicAllocation] = None
    ) -> str:
        """Construye prompt para perfil individual aterrizado a ciudad, estrato y postura."""
        attrs_str = json.dumps(entity_attributes, ensure_ascii=False) if entity_attributes else "Ninguno"
        context_str = context[:2200] if context else "Sin contexto adicional"
        pack_ctx = ""
        demo_ctx = ""
        if allocation:
            pack_ctx = self.sampler.pack.render_prompt_context([allocation.divipola_code])
            demo_ctx = (
                f"\nCuota sociodemográfica obligatoria:\n"
                f"- País: {allocation.country_name} | Ciudad: {allocation.city_name} (DIVIPOLA {allocation.divipola_code}, {allocation.region_macro})\n"
                f"- Estrato: {allocation.stratum_code} | Ingreso hogar: {allocation.income_band_local}\n"
                f"- Arquetipo cultural: {allocation.static_archetype_name} (modismos moderados: {', '.join(allocation.controlled_slang)})\n"
                f"- Rol en el estudio: {allocation.dynamic_study_role}\n"
                f"- Segmento actitudinal obligatorio: {allocation.attitude_segment} ({allocation.digital_trust_level})\n"
                f"- Edad sugerida: {allocation.age} | Género sugerido: {allocation.gender} | MBTI sugerido: {allocation.mbti}\n"
                f"- Canales preferidos: {', '.join(allocation.preferred_channels)}\n"
            )
        
        return f"""Genera un perfil sintético realista y crítico en español para la entidad indicada.

Entidad: {entity_name} ({entity_type})
Resumen: {entity_summary}
Atributos: {attrs_str}
{pack_ctx}
{demo_ctx}
Contexto del grafo:
{context_str}

Devuelve un JSON con exactamente estas claves:
1. "bio": Descripción breve (máx. 140 caracteres) en español.
2. "persona": Párrafo denso y concreto (entre 260 y 520 caracteres, SIN exceder 580 caracteres) que refleje su ciudad, estrato, preocupación real por dinero/tiempo, postura ({allocation.attitude_segment if allocation else 'esceptico'}), objeciones reales y estilo comunicativo colombiano natural sin exagerar modismos.
3. "age": entero.
4. "gender": "male" o "female".
5. "mbti": código MBTI de 4 letras (mantener {allocation.mbti if allocation else 'ENTP'}).
6. "country": "{allocation.country_name if allocation else 'Colombia'}".
7. "profession": ocupación concreta coherente con su estrato y rol.
8. "interested_topics": lista de 3 a 5 temas cortos en español.
"""

    def _build_group_persona_prompt(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        entity_attributes: Dict[str, Any],
        context: str,
        allocation: Optional[DemographicAllocation] = None
    ) -> str:
        """Construye prompt para actor organizacional/institucional en español."""
        attrs_str = json.dumps(entity_attributes, ensure_ascii=False) if entity_attributes else "Ninguno"
        context_str = context[:2200] if context else "Sin contexto adicional"
        city_label = allocation.city_name if allocation else "Bogotá D.C."
        country_label = allocation.country_name if allocation else "Colombia"
        mbti_label = allocation.mbti if allocation else "ENTJ"
        
        return f"""Genera la ficha operativa en español para la organización o cuenta institucional indicada.

Entidad: {entity_name} ({entity_type})
Resumen: {entity_summary}
Atributos: {attrs_str}
Ubicación operativa: {city_label}, {country_label}

Contexto del grafo:
{context_str}

Devuelve un JSON válido con:
1. "bio": Perfil institucional breve (máx. 140 caracteres) en español.
2. "persona": Descripción concisa (entre 240 y 500 caracteres, máx. 580 caracteres) con función en el ecosistema colombiano, criterios de cumplimiento/riesgo y estilo de respuesta.
3. "age": 35
4. "gender": "other"
5. "mbti": "{mbti_label}"
6. "country": "{country_label}"
7. "profession": rol institucional en español.
8. "interested_topics": lista de 3 a 5 temas clave en español.
"""
    
    def _generate_profile_rule_based(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        entity_attributes: Dict[str, Any],
        allocation: Optional[DemographicAllocation] = None
    ) -> Dict[str, Any]:
        """Genera perfil determinista colombiano/LATAM libre de sesgos chinos/ISTJ."""
        alloc = allocation or self.sampler.sample_allocations(count=1, country_code=self.country_code)[0]
        is_group = self._is_group_entity(entity_type)

        slang_hint = ", ".join(alloc.controlled_slang[:2]) if alloc.controlled_slang else "claro"
        if is_group:
            bio = f"{entity_type} en {alloc.city_name} ({alloc.country_name})"[:140]
            persona = (
                f"{entity_name} opera como {entity_type} en {alloc.city_name} ({alloc.region_macro}). "
                f"Mantiene postura {alloc.attitude_segment} frente al servicio, evalúa cumplimiento normativo, "
                f"trazabilidad documental y tarifas en {alloc.income_band_local.split(' ')[0]}."
            )
            return {
                "bio": bio,
                "persona": persona[:580],
                "age": 35,
                "gender": "other",
                "mbti": alloc.mbti,
                "country": alloc.country_name,
                "profession": entity_type,
                "interested_topics": ["Regulación Colombia", "Consumidor", "Calidad de Servicio"],
            }

        attitude_desc = {
            "promotor": "dispuesto a probar orientación digital si hay contrato claro",
            "neutral": "compara precios y pide evidencia antes de decidir",
            "esceptico": "muy cauteloso ante cobros anticipados y exige soporte verificable",
            "critico_hate": "desconfía abiertamente de intermediarios y cuestiona el valor frente a ir gratis",
            "outlier": "toma decisiones atípicas basadas en experiencia propia o voz a voz",
        }.get(alloc.attitude_segment, "evalúa pros y contras con pragmatismo")

        bio = f"{alloc.dynamic_study_role} · {alloc.city_name} ({alloc.stratum_code})"[:140]
        persona = (
            f"{entity_name} vive en {alloc.city_name} ({alloc.region_macro}), {alloc.stratum_code} "
            f"(hogar {alloc.income_band_local}). Rol: {alloc.dynamic_study_role}. "
            f"Arquetipo {alloc.static_archetype_code} (expresiones: {slang_hint}). "
            f"Postura {alloc.attitude_segment}: {attitude_desc}. "
            f"Canales: {', '.join(alloc.preferred_channels[:3])}. "
            f"Sensibilidad precio: {alloc.willingness_to_pay_band}."
        )
        return {
            "bio": bio,
            "persona": persona[:580],
            "age": alloc.age,
            "gender": alloc.gender,
            "mbti": alloc.mbti,
            "country": alloc.country_name,
            "profession": entity_attributes.get("occupation") or alloc.dynamic_study_role,
            "interested_topics": ["Economía familiar", "Consumo y Calidad", "Confianza digital"],
        }
    
    def set_graph_id(self, graph_id: str):
        """设置图谱ID用于Zep检索"""
        self.graph_id = graph_id
    
    def generate_profiles_from_entities(
        self,
        entities: List[EntityNode],
        use_llm: bool = True,
        progress_callback: Optional[callable] = None,
        graph_id: Optional[str] = None,
        parallel_count: int = 5,
        realtime_output_path: Optional[str] = None,
        output_platform: str = "reddit"
    ) -> List[OasisAgentProfile]:
        """
        批量从实体生成Agent Profile（支持并行生成）
        
        Args:
            entities: 实体列表
            use_llm: 是否使用LLM生成详细人设
            progress_callback: 进度回调函数 (current, total, message)
            graph_id: 图谱ID，用于Zep检索获取更丰富上下文
            parallel_count: 并行生成数量，默认5
            realtime_output_path: 实时写入的文件路径（如果提供，每生成一个就写入一次）
            output_platform: 输出平台格式 ("reddit" 或 "twitter")
            
        Returns:
            Agent Profile列表
        """
        import concurrent.futures
        from threading import Lock
        
        # 设置graph_id用于Zep检索
        if graph_id:
            self.graph_id = graph_id
        
        # Defensa en profundidad: excluir entidades no humanas (Service, Channel, Claim, métricas)
        filtered_entities = [
            e for e in entities
            if ((e.get_entity_type() or "").lower() not in NON_HUMAN_ENTITY_TYPES_LOWER)
        ]
        if not filtered_entities and entities:
            filtered_entities = list(entities)

        entities = filtered_entities
        total = len(entities)
        seed = self.sampler.stable_seed_for_entities(graph_id or self.country_code, entities)
        allocations = self.sampler.sample_allocations(
            count=total,
            country_code=self.country_code,
            target_cities=self.target_cities,
            target_strata=self.target_strata,
            entities=entities,
            seed=seed,
        )
        profiles = [None] * total  # 预分配列表保持顺序
        completed_count = [0]  # 使用列表以便在闭包中修改
        lock = Lock()
        
        # 实时写入文件的辅助函数
        def save_profiles_realtime():
            """实时保存已生成的 profiles 到文件"""
            if not realtime_output_path:
                return
            
            with lock:
                # 过滤出已生成的 profiles
                existing_profiles = [p for p in profiles if p is not None]
                if not existing_profiles:
                    return
                
                try:
                    if output_platform == "reddit":
                        # Reddit JSON 格式
                        profiles_data = [p.to_reddit_format() for p in existing_profiles]
                        with open(realtime_output_path, 'w', encoding='utf-8') as f:
                            json.dump(profiles_data, f, ensure_ascii=False, indent=2)
                    else:
                        # Twitter CSV 格式
                        import csv
                        profiles_data = [p.to_twitter_format() for p in existing_profiles]
                        if profiles_data:
                            fieldnames = list(profiles_data[0].keys())
                            with open(realtime_output_path, 'w', encoding='utf-8', newline='') as f:
                                writer = csv.DictWriter(f, fieldnames=fieldnames)
                                writer.writeheader()
                                writer.writerows(profiles_data)
                except Exception as e:
                    logger.warning(f"实时保存 profiles 失败: {e}")
        
        # Capture locale before spawning thread pool workers
        current_locale = get_locale()

        def generate_single_profile(idx: int, entity: EntityNode) -> tuple:
            """Genera el perfil individual con su cuota demográfica estratificada."""
            set_locale(current_locale)
            entity_type = entity.get_entity_type() or "Entity"
            alloc = allocations[idx] if idx < len(allocations) else None
            
            try:
                profile = self.generate_profile_from_entity(
                    entity=entity,
                    user_id=idx,
                    use_llm=use_llm,
                    allocation=alloc,
                )
                
                # 实时输出生成的人设到控制台和日志
                self._print_generated_profile(entity.name, entity_type, profile)
                
                return idx, profile, None
                
            except Exception as e:
                logger.error(f"Error generando perfil de {entity.name}: {str(e)}")
                rule_data = self._generate_profile_rule_based(
                    entity.name, entity_type, entity.summary, entity.attributes, allocation=alloc
                )
                fallback_profile = OasisAgentProfile(
                    user_id=idx,
                    user_name=self._generate_username(entity.name),
                    name=entity.name,
                    bio=rule_data["bio"],
                    persona=rule_data["persona"],
                    age=rule_data["age"],
                    gender=rule_data["gender"],
                    mbti=rule_data["mbti"],
                    country=rule_data["country"],
                    profession=rule_data["profession"],
                    interested_topics=rule_data["interested_topics"],
                    country_code=alloc.country_code if alloc else self.country_code,
                    city_name=alloc.city_name if alloc else None,
                    divipola_code=alloc.divipola_code if alloc else None,
                    region_macro=alloc.region_macro if alloc else None,
                    stratum_code=alloc.stratum_code if alloc else None,
                    wealth_tier_norm=alloc.wealth_tier_norm if alloc else None,
                    income_band_local=alloc.income_band_local if alloc else None,
                    static_archetype_code=alloc.static_archetype_code if alloc else None,
                    dynamic_study_role=alloc.dynamic_study_role if alloc else None,
                    attitude_segment=alloc.attitude_segment if alloc else None,
                    digital_trust_level=alloc.digital_trust_level if alloc else None,
                    preferred_channels=alloc.preferred_channels if alloc else [],
                    willingness_to_pay_band=alloc.willingness_to_pay_band if alloc else None,
                    purchase_probability=alloc.purchase_probability if alloc else None,
                    source_entity_uuid=entity.uuid,
                    source_entity_type=entity_type,
                )
                return idx, fallback_profile, str(e)
        
        logger.info(f"开始并行生成 {total} 个Agent人设（并行数: {parallel_count}）...")
        print(f"\n{'='*60}")
        print(f"开始生成Agent人设 - 共 {total} 个实体，并行数: {parallel_count}")
        print(f"{'='*60}\n")
        
        # 使用线程池并行执行
        with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_count) as executor:
            # 提交所有任务
            future_to_entity = {
                executor.submit(generate_single_profile, idx, entity): (idx, entity)
                for idx, entity in enumerate(entities)
            }
            
            # 收集结果
            for future in concurrent.futures.as_completed(future_to_entity):
                idx, entity = future_to_entity[future]
                entity_type = entity.get_entity_type() or "Entity"
                
                try:
                    result_idx, profile, error = future.result()
                    profiles[result_idx] = profile
                    
                    with lock:
                        completed_count[0] += 1
                        current = completed_count[0]
                    
                    # 实时写入文件
                    save_profiles_realtime()
                    
                    if progress_callback:
                        progress_callback(
                            current, 
                            total, 
                            f"已完成 {current}/{total}: {entity.name}（{entity_type}）"
                        )
                    
                    if error:
                        logger.warning(f"[{current}/{total}] {entity.name} 使用备用人设: {error}")
                    else:
                        logger.info(f"[{current}/{total}] 成功生成人设: {entity.name} ({entity_type})")
                        
                except Exception as e:
                    logger.error(f"处理实体 {entity.name} 时发生异常: {str(e)}")
                    with lock:
                        completed_count[0] += 1
                    profiles[idx] = OasisAgentProfile(
                        user_id=idx,
                        user_name=self._generate_username(entity.name),
                        name=entity.name,
                        bio=f"{entity_type}: {entity.name}",
                        persona=entity.summary or "A participant in social discussions.",
                        source_entity_uuid=entity.uuid,
                        source_entity_type=entity_type,
                    )
                    # 实时写入文件（即使是备用人设）
                    save_profiles_realtime()
        
        print(f"\n{'='*60}")
        print(f"人设生成完成！共生成 {len([p for p in profiles if p])} 个Agent")
        print(f"{'='*60}\n")
        
        return profiles
    
    def _print_generated_profile(self, entity_name: str, entity_type: str, profile: OasisAgentProfile):
        """实时输出生成的人设到控制台（完整内容，不截断）"""
        separator = "-" * 70
        
        # 构建完整输出内容（不截断）
        topics_str = ', '.join(profile.interested_topics) if profile.interested_topics else '无'
        
        output_lines = [
            f"\n{separator}",
            t('progress.profileGenerated', name=entity_name, type=entity_type),
            f"{separator}",
            f"用户名: {profile.user_name}",
            f"",
            f"【简介】",
            f"{profile.bio}",
            f"",
            f"【详细人设】",
            f"{profile.persona}",
            f"",
            f"【基本属性】",
            f"年龄: {profile.age} | 性别: {profile.gender} | MBTI: {profile.mbti}",
            f"职业: {profile.profession} | 国家: {profile.country}",
            f"兴趣话题: {topics_str}",
            separator
        ]
        
        output = "\n".join(output_lines)
        
        # 只输出到控制台（避免重复，logger不再输出完整内容）
        print(output)
    
    def save_profiles(
        self,
        profiles: List[OasisAgentProfile],
        file_path: str,
        platform: str = "reddit"
    ):
        """
        保存Profile到文件（根据平台选择正确格式）
        
        OASIS平台格式要求：
        - Twitter: CSV格式
        - Reddit: JSON格式
        
        Args:
            profiles: Profile列表
            file_path: 文件路径
            platform: 平台类型 ("reddit" 或 "twitter")
        """
        if platform == "twitter":
            self._save_twitter_csv(profiles, file_path)
        else:
            self._save_reddit_json(profiles, file_path)

        # Guardar ficha extendida + resumen demográfico en profiles_enriched.json
        import os as _os
        enriched_path = _os.path.join(_os.path.dirname(file_path), "profiles_enriched.json")
        enriched_payload = {
            "summary": self.sampler.summarize_profiles(profiles),
            "profiles": [p.to_dict() for p in profiles],
        }
        with open(enriched_path, 'w', encoding='utf-8') as f:
            json.dump(enriched_payload, f, ensure_ascii=False, indent=2)
    
    def _save_twitter_csv(self, profiles: List[OasisAgentProfile], file_path: str):
        """
        保存Twitter Profile为CSV格式（符合OASIS官方要求）
        
        OASIS Twitter要求的CSV字段：
        - user_id: 用户ID（根据CSV顺序从0开始）
        - name: 用户真实姓名
        - username: 系统中的用户名
        - user_char: 详细人设描述（注入到LLM系统提示中，指导Agent行为）
        - description: 简短的公开简介（显示在用户资料页面）
        
        user_char vs description 区别：
        - user_char: 内部使用，LLM系统提示，决定Agent如何思考和行动
        - description: 外部显示，其他用户可见的简介
        """
        import csv
        
        # 确保文件扩展名是.csv
        if not file_path.endswith('.csv'):
            file_path = file_path.replace('.json', '.csv')
        
        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # 写入OASIS要求的表头
            headers = ['user_id', 'name', 'username', 'user_char', 'description']
            writer.writerow(headers)
            
            # 写入数据行
            for idx, profile in enumerate(profiles):
                # user_char: 完整人设（bio + persona），用于LLM系统提示
                user_char = profile.bio
                if profile.persona and profile.persona != profile.bio:
                    user_char = f"{profile.bio} {profile.persona}"
                # 处理换行符（CSV中用空格替代）
                user_char = user_char.replace('\n', ' ').replace('\r', ' ')
                
                # description: 简短简介，用于外部显示
                description = profile.bio.replace('\n', ' ').replace('\r', ' ')
                
                row = [
                    idx,                    # user_id: 从0开始的顺序ID
                    profile.name,           # name: 真实姓名
                    profile.user_name,      # username: 用户名
                    user_char,              # user_char: 完整人设（内部LLM使用）
                    description             # description: 简短简介（外部显示）
                ]
                writer.writerow(row)
        
        logger.info(f"已保存 {len(profiles)} 个Twitter Profile到 {file_path} (OASIS CSV格式)")
    
    def _normalize_gender(self, gender: Optional[str]) -> str:
        """
        标准化gender字段为OASIS要求的英文格式
        
        OASIS要求: male, female, other
        """
        if not gender:
            return "other"
        
        gender_lower = gender.lower().strip()
        
        # 中文映射
        gender_map = {
            "男": "male",
            "女": "female",
            "机构": "other",
            "其他": "other",
            # 英文已有
            "male": "male",
            "female": "female",
            "other": "other",
        }
        
        return gender_map.get(gender_lower, "other")
    
    def _save_reddit_json(self, profiles: List[OasisAgentProfile], file_path: str):
        """
        保存Reddit Profile为JSON格式
        
        使用与 to_reddit_format() 一致的格式，确保 OASIS 能正确读取。
        必须包含 user_id 字段，这是 OASIS agent_graph.get_agent() 匹配的关键！
        
        必需字段：
        - user_id: 用户ID（整数，用于匹配 initial_posts 中的 poster_agent_id）
        - username: 用户名
        - name: 显示名称
        - bio: 简介
        - persona: 详细人设
        - age: 年龄（整数）
        - gender: "male", "female", 或 "other"
        - mbti: MBTI类型
        - country: 国家
        """
        data = []
        for idx, profile in enumerate(profiles):
            item = profile.to_reddit_format()
            item["user_id"] = profile.user_id if profile.user_id is not None else idx
            item["bio"] = (profile.bio or "")[:150]
            item["gender"] = self._normalize_gender(profile.gender)
            item["mbti"] = profile.mbti if profile.mbti else "ENTP"
            item["country"] = profile.country if (profile.country and profile.country not in {"中国", "China"}) else "Colombia"
            data.append(item)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"已保存 {len(profiles)} 个Reddit Profile到 {file_path} (JSON格式，包含user_id字段)")
    
    # 保留旧方法名作为别名，保持向后兼容
    def save_profiles_to_json(
        self,
        profiles: List[OasisAgentProfile],
        file_path: str,
        platform: str = "reddit"
    ):
        """[已废弃] 请使用 save_profiles() 方法"""
        logger.warning("save_profiles_to_json已废弃，请使用save_profiles方法")
        self.save_profiles(profiles, file_path, platform)
