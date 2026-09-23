"""Skill 注册与异常分级体系 (SK-* / AnomalyLevel)

文生载荷智能体的可插拔能力单元。每个 Skill 封装一个原子能力，
声明依赖、输入输出契约与异常处置规则（L1 自动重试 / L2 降级上报 / L3 保护转人工）。

Skill 清单（11 个，与业务流程节点一一对应）:
  SK-INTENT    意图解析    → intent.IntentChain
  SK-CLARIFY   需求澄清    → intent.build_clarifications   （流程闸口，禁止擅自假设）
  SK-RETRIEVE  知识检索    → knowledge.retrieve_context
  SK-ANTSEL    天线选型    → selection.AntennaSelector
  SK-EQUIP     单机选型    → selection.EquipmentSelector / NonCommSelector
  SK-BUDGET    链路预算    → link_budget.build_link_budgets
  SK-PLAT      平台选型    → selection.PlatformSelector
  SK-LAUNCH    运载选型    → selection.LauncherSelector
  SK-VALID     方案校验    → link_budget.validate_scheme
  SK-DOC       方案生成    → docgen.generate_scheme
  SK-WORD      文档导出    → docgen.export_html / export_doc

用法:
  reg = SkillRegistry()
  reg.bind("SK-INTENT", handler)
  result = reg.execute("SK-INTENT", user_input="设计 GEO Ka 载荷…")
  chain = reg.get_dependency_chain("SK-DOC")   # 拓扑序依赖链
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ============================================================
# 异常分级
# ============================================================

class AnomalyLevel(Enum):
    """异常处置等级

    L1  自动重试/降级，不中断业务，不扰民
    L2  自动降级 + 事件上报，链路继续但结果带告警，等待地面/人工决策
    L3  自动保护，中止当前分支，切换候选或转人工处置
    """
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


LEVEL_DESC = {
    AnomalyLevel.L1: "自动重试/降级，不中断业务",
    AnomalyLevel.L2: "自动降级并上报，结果附告警，等待人工决策",
    AnomalyLevel.L3: "自动保护，中止或切换候选，转人工处置",
}


@dataclass(frozen=True)
class AnomalyRule:
    """单条异常处置规则"""
    code: str                    # 异常码，如 "INT-01"
    description: str             # 触发条件描述
    level: AnomalyLevel
    auto_action: str             # 智能体自动处置动作
    manual_action: str           # 人工处置建议

    def to_dict(self) -> dict:
        return {"code": self.code, "description": self.description,
                "level": self.level.value, "auto_action": self.auto_action,
                "manual_action": self.manual_action}


# ============================================================
# Skill 定义
# ============================================================

@dataclass
class SkillDef:
    """Skill 元数据 + 执行函数"""
    id: str
    name: str
    stage: str                                    # 所属业务阶段
    description: str = ""
    trigger: str = ""
    input_schema: Dict[str, str] = field(default_factory=dict)
    output_schema: Dict[str, str] = field(default_factory=dict)
    deps: List[str] = field(default_factory=list)
    anomaly_map: List[AnomalyRule] = field(default_factory=list)
    version: str = "1.0"
    handler: Optional[Callable] = None

    def bind(self, handler: Callable) -> "SkillDef":
        self.handler = handler
        return self

    @property
    def bound(self) -> bool:
        return self.handler is not None

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "stage": self.stage,
            "version": self.version, "description": self.description,
            "trigger": self.trigger, "deps": self.deps,
            "input": self.input_schema, "output": self.output_schema,
            "bound": self.bound,
            "anomaly_rules": [r.to_dict() for r in self.anomaly_map],
        }


# ============================================================
# 预置 Skill 清单
# ============================================================

def _default_skill_defs() -> List[SkillDef]:
    return [
        SkillDef(
            id="SK-INTENT", name="意图解析", stage="需求理解",
            description="从自然语言需求提取结构化要素：载荷类型、轨道、频段、"
                        "关键技术、转发体制、数值指标（EIRP/G-T/质量/功耗/寿命/容量/波束数）",
            trigger="用户提交载荷设计需求文本",
            input_schema={"user_input": "需求原文"},
            output_schema={"intent": "IntentResult"},
            anomaly_map=[
                AnomalyRule("INT-01", "关键词命中为空", AnomalyLevel.L1,
                            "回退 LLM 意图解析", "无需干预"),
                AnomalyRule("INT-02", "LLM 解析失败/超时", AnomalyLevel.L1,
                            "降级关键词后端，标记 backend=fallback", "无需干预"),
                AnomalyRule("INT-03", "频段/轨道识别冲突", AnomalyLevel.L2,
                            "写入 ambiguity 字段，保留多候选", "人工澄清"),
                AnomalyRule("INT-04", "数值指标提取失败", AnomalyLevel.L1,
                            "留空该指标，由下游按轨道/频段推算", "无需干预"),
            ],
        ),
        SkillDef(
            id="SK-CLARIFY", name="需求澄清", stage="需求理解",
            description="缺项与歧义闸口：载荷类型/轨道未识别、通信载荷缺频段、"
                        "转发体制未定、解析器标记歧义时生成澄清问题。"
                        "铁律——禁止擅自假设用户需求。",
            trigger="意图解析完成后",
            input_schema={"intent": "IntentResult"},
            output_schema={"clarifications": "澄清问题列表（blocking/warning）"},
            deps=["SK-INTENT"],
            anomaly_map=[
                AnomalyRule("CLA-01", "存在 blocking 级缺项", AnomalyLevel.L3,
                            "中断流程，返回 need_clarify 等待用户补充", "用户补充需求后重跑"),
                AnomalyRule("CLA-02", "仅 warning 级缺项", AnomalyLevel.L2,
                            "按工程默认值继续，方案中标注假设来源", "确认默认值是否可接受"),
            ],
        ),
        SkillDef(
            id="SK-RETRIEVE", name="知识检索", stage="知识支撑",
            description="按意图检索货架产品库、选型判据、行业标准与体制模板，"
                        "输出压缩上下文供方案生成引用",
            trigger="澄清闸口通过后",
            input_schema={"intent": "IntentResult", "top_k": "检索条数"},
            output_schema={"context": "知识上下文字符串"},
            deps=["SK-CLARIFY"],
            anomaly_map=[
                AnomalyRule("RET-01", "检索结果为空", AnomalyLevel.L1,
                            "回退全量目录摘要注入", "无需干预"),
                AnomalyRule("RET-02", "上下文超长", AnomalyLevel.L1,
                            "按相关度截断至预算内", "无需干预"),
            ],
        ),
        SkillDef(
            id="SK-ANTSEL", name="天线选型", stage="载荷方案",
            description="通信载荷按五要素评分选天线：EIRP 30 + G/T 25 + 重量 20 "
                        "+ 功耗 15 + 工作模式 10，频段硬过滤，货架水平加权",
            trigger="载荷方案设计（通信类）",
            input_schema={"requirement": "SelectionRequirement"},
            output_schema={"antennas": "评分排序候选 [(score, antenna, reasons)]"},
            deps=["SK-RETRIEVE"],
            anomaly_map=[
                AnomalyRule("ANT-01", "无频段匹配天线", AnomalyLevel.L2,
                            "返回降权候选并标记需定制", "人工确认放宽频段或立项定制"),
                AnomalyRule("ANT-02", "工作模式完全不匹配", AnomalyLevel.L2,
                            "标记模式冲突，评分不给模式分", "人工确认工作模式需求"),
                AnomalyRule("ANT-03", "EIRP/G-T 能力均不足", AnomalyLevel.L3,
                            "中止本分支，回环换候选或提升口径", "人工重估指标可达性"),
            ],
        ),
        SkillDef(
            id="SK-EQUIP", name="单机选型", stage="载荷方案",
            description="按转发体制与频段组链选货架单机（LNA/变频/多工/DTP/功放/环行器/测控/信标），"
                        "货架优先：飞行继承货架 > 飞行继承 > 货架 > 定制；"
                        "非通信载荷走分辨率/幅宽/信号体制判据",
            trigger="天线（或载荷单机）选型后",
            input_schema={"intent": "IntentResult", "requirement": "SelectionRequirement"},
            output_schema={"equipment": "单机列表", "gaps": "定制缺口列表"},
            deps=["SK-RETRIEVE"],
            anomaly_map=[
                AnomalyRule("EQU-01", "该频段无货架单机", AnomalyLevel.L2,
                            "记为定制缺口，不回退到错误频段产品", "人工确认定制或放宽频段"),
                AnomalyRule("EQU-02", "功放体制冲突（SSPA/TWTA）", AnomalyLevel.L2,
                            "保留首选，备选记入候选", "人工确认功放体制"),
                AnomalyRule("EQU-03", "单机汇总超平台包络", AnomalyLevel.L3,
                            "触发校核回环换候选", "人工评估降配方案"),
            ],
        ),
        SkillDef(
            id="SK-BUDGET", name="链路预算", stage="指标校核",
            description="逐链路计算 FSPL/C-N0/C-N/余量，调制体制由 C/N 自适应反推"
                        "（DVBS2X 阶梯），输出可达容量；余量门槛 ≥3 dB",
            trigger="选型完成后、方案生成前",
            input_schema={"plan": "SelectionPlan", "intent": "IntentResult"},
            output_schema={"budgets": "LinkBudget 列表"},
            deps=["SK-EQUIP", "SK-ANTSEL"],
            anomaly_map=[
                AnomalyRule("BUD-01", "链路余量 < 3 dB", AnomalyLevel.L2,
                            "标记不通过并给出调整建议（口径/带宽/可用性/体制）",
                            "人工调整天线口径或功放功率"),
                AnomalyRule("BUD-02", "体制已降至最低阶仍不闭合", AnomalyLevel.L3,
                            "触发回环换更大口径天线候选", "人工重估链路可达性"),
                AnomalyRule("BUD-03", "链路参数缺失", AnomalyLevel.L1,
                            "按轨道典型值填充并标注", "无需干预"),
            ],
        ),
        SkillDef(
            id="SK-PLAT", name="平台选型", stage="平台运载",
            description="可行性预筛（轨道/承载/供电）后五因子评分："
                        "轨道适配 15 + 承载贴合 30 + 供电贴合 25 + 寿命匹配 15 + 飞行成熟度 15",
            trigger="载荷包络确定后",
            input_schema={"payload_mass": "kg", "payload_power": "W", "orbit": "轨道",
                          "life_years": "任务寿命（可选）"},
            output_schema={"platforms": "可行平台排序", "rejected": "被筛除项及原因"},
            deps=["SK-EQUIP"],
            anomaly_map=[
                AnomalyRule("PLA-01", "该轨道无匹配平台", AnomalyLevel.L2,
                            "返回空可行集，触发回环换载荷候选", "人工评估定制平台"),
                AnomalyRule("PLA-02", "所有平台承载/供电不足", AnomalyLevel.L3,
                            "标记 feasible=False，中止并给拆分/换轨/定制建议",
                            "人工重新评估载荷包络"),
                AnomalyRule("PLA-03", "平台利用率 > 90%", AnomalyLevel.L2,
                            "标注裕度风险告警", "评估升级平台或减重"),
            ],
        ),
        SkillDef(
            id="SK-LAUNCH", name="运载选型", stage="平台运载",
            description="四因子评分：入轨能力 40 + 经济性 25 + 飞行履历 20 + 整流罩包络 15；"
                        "能力余量 >50% 时提示搭载/拼单降本机会",
            trigger="平台选型完成后",
            input_schema={"sat_mass_kg": "整星质量", "orbit": "目标轨道",
                          "sat_envelope_m": "整星包络直径（可选）"},
            output_schema={"launchers": "运载候选排序"},
            deps=["SK-PLAT"],
            anomaly_map=[
                AnomalyRule("LAU-01", "无入轨能力匹配火箭", AnomalyLevel.L2,
                            "返回最接近候选并标记能力不足", "人工评估减重或拆分发射"),
                AnomalyRule("LAU-02", "整流罩包络超限", AnomalyLevel.L2,
                            "候选降分并标记超限", "人工评估折叠/拆分或改大整流罩"),
                AnomalyRule("LAU-03", "能力余量 > 50%", AnomalyLevel.L1,
                            "提示搭载/拼单机会", "评估搭载发射降本"),
            ],
        ),
        SkillDef(
            id="SK-VALID", name="方案校验", stage="指标校核",
            description="三重校验闸门：语法（要素完整性）/ 语义（指标一致性）/ "
                        "合规（余量门槛、频段匹配、货架优先、平台可行性）",
            trigger="链路预算完成后",
            input_schema={"plan": "SelectionPlan", "budgets": "LinkBudget 列表",
                          "intent": "IntentResult"},
            output_schema={"validation": "ValidationResult"},
            deps=["SK-BUDGET", "SK-PLAT", "SK-LAUNCH"],
            anomaly_map=[
                AnomalyRule("VAL-01", "语义校验不达标（EIRP/G-T/包络）", AnomalyLevel.L2,
                            "标记不达标项，进入回环", "人工确认是否接受偏差"),
                AnomalyRule("VAL-02", "合规校验失败（频段错配/余量不足）", AnomalyLevel.L2,
                            "标记违规项，触发回环调整", "人工调整方案"),
                AnomalyRule("VAL-03", "平台可行性判负", AnomalyLevel.L3,
                            "中止，标记方案不可行", "人工重新设计"),
            ],
        ),
        SkillDef(
            id="SK-DOC", name="方案生成", stage="成果输出",
            description="将选型与校核结果装配为完整 Markdown 方案文档"
                        "（需求分析→总体方案→天线/单机/平台/运载→链路预算→校验→风险→演进）",
            trigger="校验通过后（或带告警放行）",
            input_schema={"intent": "IntentResult", "plan": "SelectionPlan",
                          "budgets": "LinkBudget 列表", "validation": "ValidationResult",
                          "context": "知识上下文"},
            output_schema={"design_scheme": "Markdown 方案文档"},
            deps=["SK-VALID"],
            anomaly_map=[
                AnomalyRule("DOC-01", "选型结果为空", AnomalyLevel.L2,
                            "生成模板骨架并标注缺失章节", "人工补充"),
                AnomalyRule("DOC-02", "LLM 润色失败", AnomalyLevel.L1,
                            "回退确定性模板装配", "无需干预"),
            ],
        ),
        SkillDef(
            id="SK-WORD", name="文档导出", stage="成果输出",
            description="Markdown → HTML（中文排版，含目录/打印样式）与 .doc 兼容导出",
            trigger="方案文档生成后",
            input_schema={"markdown": "方案 Markdown", "title": "文档标题"},
            output_schema={"html_path": "HTML 路径", "doc_path": "DOC 路径"},
            deps=["SK-DOC"],
            anomaly_map=[
                AnomalyRule("WOR-01", "导出目录不可写", AnomalyLevel.L2,
                            "改写入临时目录并返回实际路径", "人工指定输出目录"),
                AnomalyRule("WOR-02", "转换失败", AnomalyLevel.L2,
                            "返回原始 Markdown 内容", "人工排查格式"),
            ],
        ),
    ]


# ============================================================
# 注册表
# ============================================================

class SkillRegistry:
    """Skill 注册中心：注册 / 查询 / 依赖拓扑 / 带异常分级的执行"""

    def __init__(self):
        self._skills: Dict[str, SkillDef] = {}
        for s in _default_skill_defs():
            self._skills[s.id] = s

    # ---------- 注册与查询 ----------

    def bind(self, skill_id: str, handler: Callable) -> SkillDef:
        s = self._skills.get(skill_id)
        if s is None:
            raise KeyError(f"Skill 不存在: {skill_id}")
        return s.bind(handler)

    def register(self, skill: SkillDef) -> None:
        self._skills[skill.id] = skill

    def get(self, skill_id: str) -> Optional[SkillDef]:
        return self._skills.get(skill_id)

    def list_all(self) -> List[SkillDef]:
        return list(self._skills.values())

    def stages(self) -> Dict[str, List[str]]:
        """按业务阶段归组"""
        out: Dict[str, List[str]] = {}
        for s in self._skills.values():
            out.setdefault(s.stage, []).append(s.id)
        return out

    def get_dependency_chain(self, skill_id: str) -> List[str]:
        """拓扑序依赖链（依赖在前）"""
        visited: set = set()
        chain: List[str] = []

        def dfs(sid: str):
            if sid in visited or sid not in self._skills:
                return
            visited.add(sid)
            for dep in self._skills[sid].deps:
                dfs(dep)
            chain.append(sid)

        dfs(skill_id)
        return chain

    def anomaly_table(self) -> List[dict]:
        """全部异常规则平铺（用于业务流程文档的异常分级表）"""
        rows = []
        for s in self._skills.values():
            for r in s.anomaly_map:
                rows.append({"skill": s.id, "skill_name": s.name, **r.to_dict()})
        return rows

    # ---------- 执行 ----------

    def execute(self, skill_id: str, **kwargs) -> Any:
        """执行 Skill，按异常分级捕获

        L1/L2 → 记录告警后返回 None（由调用方降级）
        L3    → 重新抛出，由上层链路做保护/回环/转人工
        """
        s = self._skills.get(skill_id)
        if s is None:
            raise KeyError(f"Skill 不存在: {skill_id}")
        if s.handler is None:
            raise RuntimeError(f"Skill {skill_id} 未绑定执行函数")
        try:
            return s.handler(**kwargs)
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            for rule in s.anomaly_map:
                if rule.code in msg:
                    logger.warning("[%s] %s %s → %s", skill_id,
                                   rule.level.value, rule.description, rule.auto_action)
                    if rule.level == AnomalyLevel.L3:
                        raise
                    return None
            logger.warning("[%s] 未分类异常（按 L1 降级）: %s", skill_id, e)
            return None


_registry: Optional[SkillRegistry] = None


def get_skill_registry() -> SkillRegistry:
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
    return _registry


if __name__ == "__main__":
    reg = SkillRegistry()
    print(f"Skill 总数: {len(reg.list_all())}\n")
    for stage, ids in reg.stages().items():
        print(f"[{stage}]")
        for sid in ids:
            s = reg.get(sid)
            print(f"  {sid:<12} {s.name:<6} deps={s.deps or '-'}  "
                  f"异常规则 {len(s.anomaly_map)} 条")
    print("\nSK-DOC 依赖链:", " → ".join(reg.get_dependency_chain("SK-DOC")))
    print(f"\n异常规则总数: {len(reg.anomaly_table())}")
    from collections import Counter
    lv = Counter(r["level"] for r in reg.anomaly_table())
    print("分级统计:", dict(lv))
