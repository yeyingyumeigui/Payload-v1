"""主链路编排 (PayloadDesignChain)

端到端流水线，串联全部 Skill：

  用户需求
    → SK-INTENT   意图解析
    → SK-CLARIFY  澄清闸口（blocking 缺项 → 中断等待用户，禁止擅自假设）
    → SK-RETRIEVE 知识检索
    → SK-ANTSEL/SK-EQUIP 载荷选型 ─┐
    → SK-PLAT/SK-LAUNCH 平台运载   ├ 校核回环（内环：平台不可行换天线）
    → SK-BUDGET   链路预算         │ （外环：链路余量不足换天线重选型）
    → SK-VALID    三重校验 ────────┘
    → SK-DOC      方案生成
    → 返回 Markdown 方案 + 结构化结果 + 事件流

设计原则:
  1. 确定性可复现：无 LLM 也能跑通全链路（LLM 仅可选增强意图解析）
  2. 双回环：内环在 SelectionEngine（平台可行性），外环在本链（链路余量）
  3. 事件追踪：每步记录 checkpoint，前端可增量拉取展示进度
  4. 人工确认：confirm_mode=True 时选型后暂停，confirm_design() 继续
  5. 异常分级：L1 降级 / L2 告警放行 / L3 中止转人工

用法:
  chain = PayloadDesignChain()
  r = chain.invoke({"user_input": "设计GEO Ka频段高通量通信载荷…"})
  if r["status"] == "need_clarify": ...
  print(r["design_scheme"])
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .intent import IntentChain, IntentResult, build_clarifications
from .knowledge import retrieve_context
from .selection import SelectionEngine, SelectionPlan
from .link_budget import (
    build_link_budgets, validate_scheme, LinkBudget, ValidationResult,
)
from .docgen import generate_scheme
from .skill_registry import get_skill_registry

logger = logging.getLogger(__name__)

# 外环（链路余量回环）最大次数
MAX_LINK_RETRY = 2


# ============================================================
# 事件与会话状态
# ============================================================

@dataclass
class SessionState:
    """单次设计会话的状态容器"""
    session_id: str
    events: List[dict] = field(default_factory=list)
    pending: Optional[dict] = None       # confirm_mode 暂停点数据
    interrupted: bool = False

    def log(self, stage: str, message: str, level: str = "info",
            data: Optional[dict] = None, check_interrupt: bool = True) -> dict:
        ev = {"seq": len(self.events) + 1, "stage": stage,
              "message": message, "level": level,
              "ts": time.time(), "data": data}
        self.events.append(ev)
        if check_interrupt and self.interrupted:
            raise ChainInterrupted(stage)
        return ev

    def events_after(self, after_seq: int = 0) -> List[dict]:
        return [e for e in self.events if e["seq"] > after_seq]


class ChainInterrupted(Exception):
    """人工中止信号"""
    def __init__(self, stage: str):
        super().__init__(f"链路在 {stage} 阶段被人工中止")
        self.stage = stage


class SessionStore:
    """会话仓库（内存级，骨架用；生产可换 Redis/DB）"""

    def __init__(self):
        self._sessions: Dict[str, SessionState] = {}

    def get(self, session_id: str) -> SessionState:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionState(session_id=session_id)
        return self._sessions[session_id]


# ============================================================
# 结果对象
# ============================================================

@dataclass
class DesignResult:
    """一次完整设计的产出"""
    status: str                          # completed / need_clarify / infeasible / interrupted / awaiting_confirmation / error
    session_id: str
    user_input: str = ""
    intent: Optional[IntentResult] = None
    clarifications: List[dict] = field(default_factory=list)
    context: str = ""
    plan: Optional[SelectionPlan] = None
    budgets: List[LinkBudget] = field(default_factory=list)
    validation: Optional[ValidationResult] = None
    design_scheme: str = ""              # Markdown 方案
    link_retry: int = 0                  # 外环回环次数
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self, include_scheme: bool = True) -> dict:
        d = {
            "status": self.status,
            "session_id": self.session_id,
            "user_input": self.user_input,
            "intent": self.intent.to_dict() if self.intent else None,
            "clarifications": self.clarifications,
            "validation": self.validation.to_dict() if self.validation else None,
            "plan": self.plan.to_dict() if self.plan else None,
            "budgets": [b.to_dict() for b in self.budgets],
            "link_retry": self.link_retry,
            "error": self.error,
            "metadata": self.metadata,
        }
        if include_scheme:
            d["design_scheme"] = self.design_scheme
        return d


# ============================================================
# 主链路
# ============================================================

class PayloadDesignChain:
    """文生载荷方案 编排链（零依赖可运行）"""

    def __init__(self, llm_api_key: str = "", llm_base_url: str = "",
                 llm_model: str = "gpt-4o"):
        self.registry = get_skill_registry()
        self.intent_chain = IntentChain(use_llm=bool(llm_api_key),
                                        api_key=llm_api_key,
                                        base_url=llm_base_url,
                                        model=llm_model)
        self.engine = SelectionEngine()
        self.store = SessionStore()
        self._bind_skills()

    # ---------- Skill 绑定 ----------

    def _bind_skills(self):
        reg = self.registry
        reg.bind("SK-INTENT", lambda user_input, **kw: self.intent_chain.parse(user_input))
        reg.bind("SK-CLARIFY", lambda intent, **kw: build_clarifications(intent))
        reg.bind("SK-RETRIEVE", lambda intent, **kw: retrieve_context(intent))
        reg.bind("SK-ANTSEL", lambda requirement, **kw:
                 self.engine.antenna_selector.select(requirement))
        reg.bind("SK-EQUIP", lambda intent, requirement, **kw:
                 self.engine.equipment_selector.select(intent, requirement))
        reg.bind("SK-PLAT", lambda payload_mass, payload_power, orbit, **kw:
                 self.engine.platform_selector.select(
                     payload_mass, payload_power, orbit, kw.get("life_years")))
        reg.bind("SK-LAUNCH", lambda sat_mass_kg, orbit, **kw:
                 self.engine.launcher_selector.select(
                     sat_mass_kg, orbit, kw.get("sat_envelope_m")))
        reg.bind("SK-BUDGET", lambda plan, intent, **kw:
                 build_link_budgets(plan, intent))
        reg.bind("SK-VALID", lambda plan, budgets, intent, **kw:
                 validate_scheme(plan, budgets, intent))
        reg.bind("SK-DOC", lambda intent, plan, **kw: generate_scheme(
            intent, plan, kw.get("budgets"), kw.get("validation"),
            kw.get("user_input", "")))

    # ---------- 主入口 ----------

    def invoke(self, inputs: Dict[str, Any]) -> DesignResult:
        """执行完整流水线

        inputs:
          user_input    str   需求原文（必填）
          session_id    str   会话 ID（可选，默认生成）
          confirm_mode  bool  选型后暂停等待人工确认
          skip_clarify  bool  跳过澄清闸口（调试用；warning 级缺项始终放行）
        """
        user_input = inputs.get("user_input", "")
        session_id = inputs.get("session_id") or uuid.uuid4().hex[:8]
        confirm_mode = bool(inputs.get("confirm_mode", False))
        skip_clarify = bool(inputs.get("skip_clarify", False))

        sess = self.store.get(session_id)
        sess.interrupted = False
        sess.pending = None

        result = DesignResult(status="completed", session_id=session_id,
                              user_input=user_input)
        t0 = time.time()

        try:
            # ── Step 1: 意图解析 (SK-INTENT) ──
            sess.log("SK-INTENT", "开始解析设计需求")
            intent = self.registry.execute("SK-INTENT", user_input=user_input)
            if intent is None:                       # L1 降级失败兜底
                intent = self.intent_chain.parse(user_input)
            result.intent = intent
            sess.log("SK-INTENT", f"意图解析完成（{intent.backend} 后端）: {intent.summary()}",
                     data=intent.to_dict())

            # ── Step 2: 澄清闸口 (SK-CLARIFY) ──
            if not skip_clarify:
                clarifications = self.registry.execute("SK-CLARIFY", intent=intent) \
                    or build_clarifications(intent)
                blocking = [c for c in clarifications if c.get("level") == "blocking"]
                result.clarifications = clarifications
                if blocking:
                    sess.log("SK-CLARIFY",
                             f"检测到 {len(blocking)} 项阻断级缺项，中断等待用户澄清",
                             level="warn")
                    result.status = "need_clarify"
                    result.metadata["elapsed_s"] = round(time.time() - t0, 3)
                    return result
                if clarifications:
                    sess.log("SK-CLARIFY",
                             f"{len(clarifications)} 项 warning 级缺项，按工程默认值放行",
                             level="warn", data={"items": clarifications})
                else:
                    sess.log("SK-CLARIFY", "需求完整，进入选型")

            # ── Step 3: 知识检索 (SK-RETRIEVE) ──
            context = self.registry.execute("SK-RETRIEVE", intent=intent) or ""
            result.context = context
            sess.log("SK-RETRIEVE", f"知识检索完成（{len(context)} 字符）")

            # ── Step 4: 选型 + 校核双回环 ──
            plan, budgets, validation, excluded, link_retry = \
                self._select_and_validate(intent, sess)
            result.plan = plan
            result.budgets = budgets
            result.validation = validation
            result.link_retry = link_retry

            # 人工确认模式：选型后暂停
            if confirm_mode:
                sess.pending = {"user_input": user_input, "intent": intent,
                                "context": context, "plan": plan,
                                "budgets": budgets, "validation": validation,
                                "link_retry": link_retry,
                                "excluded": excluded}
                sess.log("HUMAN", "人工确认模式：已暂停，等待用户确认选型结果",
                         level="warn")
                result.status = "awaiting_confirmation"
                result.metadata["elapsed_s"] = round(time.time() - t0, 3)
                return result

            # ── Step 5: 方案生成 (SK-DOC) ──
            self._finish(result, sess, intent, context, plan, budgets,
                         validation, t0)
            return result

        except Exception as e:  # noqa: BLE001 — L3 或未分类异常统一出口
            logger.exception("链路执行异常")
            sess.log("ERROR", f"链路异常中止: {e}", level="error")
            result.status = "error"
            result.error = str(e)
            result.metadata["elapsed_s"] = round(time.time() - t0, 3)
            return result

    # ---------- 选型 + 校核双回环 ----------

    def _select_and_validate(self, intent: IntentResult, sess: SessionState):
        """外环：选型 → 链路预算 → 校验；链路余量不足时否决当前天线换下一候选

        Returns: (plan, budgets, validation, excluded_models, link_retry)
        """
        excluded: List[str] = []
        link_retry = 0

        while True:
            sess.log("SK-SELECT",
                     f"三级选型开始（链路回环第 {link_retry + 1} 轮"
                     + (f"，已否决 {excluded}" if excluded else "") + "）")
            plan = self.engine.run(intent, exclude_models=excluded or None)
            top = plan.antenna or (plan.noncomm_top if plan.noncomm_items else None)
            sess.log("SK-SELECT",
                     f"选型完成（内环迭代 {plan.iteration} 次）: "
                     f"载荷={top['model'] if top else '无'}, "
                     f"单机={len(plan.equipment)}台+缺口{len(plan.gaps)}项, "
                     f"包络={plan.payload_mass_est:.0f}kg/{plan.payload_power_est:.0f}W, "
                     f"平台={plan.platform['model'] if plan.platform else '无'}, "
                     f"运载={plan.launcher['name'] if plan.launcher else '无'}, "
                     f"可行性={'通过' if plan.feasible else '未通过'}")

            budgets = build_link_budgets(plan, intent)
            sess.log("SK-BUDGET",
                     f"链路预算完成: {len(budgets)} 条链路，"
                     f"{sum(1 for b in budgets if b.passed)} 条通过")

            validation = validate_scheme(plan, budgets, intent)
            sess.log("SK-VALID",
                     f"三重校验: {'通过' if validation.valid else '未通过'}"
                     f"（错误 {len(validation.errors)}，告警 {len(validation.warnings)}）",
                     level="info" if validation.valid else "warn")

            if validation.valid:
                return plan, budgets, validation, excluded, link_retry

            # ── 外环回环判定：链路余量不足 → 否决天线换下一候选 (BUD-02/VAL-02) ──
            link_failed = [b for b in budgets if not b.passed]
            can_retry = (link_failed and plan.is_comm and plan.antenna
                         and link_retry < MAX_LINK_RETRY)
            if can_retry:
                dead = plan.antenna["model"]
                excluded.append(dead)
                link_retry += 1
                sess.log("SK-VALID",
                         f"链路余量不足（{len(link_failed)} 条不通过），"
                         f"否决天线 {dead}，第 {link_retry} 次回环换候选重选型",
                         level="warn")
                continue

            # 无法回环 → 按校验结果定级放行/中止
            if not plan.feasible:
                sess.log("SK-VALID", "平台不可行（L3）：中止，转人工处置", level="error")
                return plan, budgets, validation, excluded, link_retry
            sess.log("SK-VALID",
                     "校验存在阻断项且无候选可换（L2/L3）：带告警生成方案，标注不通过项",
                     level="warn")
            return plan, budgets, validation, excluded, link_retry

    # ---------- 收尾 ----------

    def _finish(self, result: DesignResult, sess: SessionState,
                intent: IntentResult, context: str, plan: SelectionPlan,
                budgets: List[LinkBudget], validation: ValidationResult,
                t0: float) -> None:
        sess.log("SK-DOC", "开始装配方案文档")
        scheme = self.registry.execute(
            "SK-DOC", intent=intent, plan=plan, budgets=budgets,
            validation=validation, user_input=result.user_input)
        if scheme is None:                            # L1 降级兜底
            scheme = generate_scheme(intent, plan, budgets, validation,
                                     result.user_input)
        result.design_scheme = scheme
        result.context = context
        if not plan.feasible:
            result.status = "infeasible"
        sess.log("SK-DOC", f"方案文档生成完成（{len(scheme)} 字符）")
        result.metadata = {
            "elapsed_s": round(time.time() - t0, 3),
            "intent_backend": intent.backend,
            "payload_type": intent.payload_type,
            "link_retry": result.link_retry,
            "selection_iteration": plan.iteration,
            "feasible": plan.feasible,
            "validation": {"valid": validation.valid,
                           "n_errors": len(validation.errors),
                           "n_warnings": len(validation.warnings)},
            "skills_used": [s.id for s in self.registry.list_all()],
        }

    # ---------- 人工确认 / 中止 / 事件 ----------

    def confirm_design(self, session_id: str,
                       overrides: Optional[Dict[str, str]] = None) -> DesignResult:
        """人工确认选型结果后继续（可指定平台/运载候选重排）"""
        sess = self.store.get(session_id)
        if not sess.pending:
            return DesignResult(status="error", session_id=session_id,
                                error="当前会话没有待确认的选型结果")
        if sess.interrupted:
            return DesignResult(status="interrupted", session_id=session_id,
                                error="链路已被人工中止",
                                metadata={"interrupted_at": "HUMAN"})
        p = sess.pending
        sess.pending = None
        overrides = overrides or {}

        plan: SelectionPlan = p["plan"]
        if overrides.get("platform") and plan.platforms:
            plan.platforms.sort(key=lambda t: 0 if t[0]["model"] == overrides["platform"] else 1)
            sess.log("HUMAN", f"人工接管: 平台调整为 {plan.platforms[0][0]['model']}",
                     level="warn")
        if overrides.get("launcher") and plan.launchers:
            plan.launchers.sort(key=lambda t: 0 if t[0]["name"] == overrides["launcher"] else 1)
            sess.log("HUMAN", f"人工接管: 运载调整为 {plan.launchers[0][0]['name']}",
                     level="warn")
        sess.log("HUMAN", "用户已确认选型结果，继续生成方案")

        result = DesignResult(status="completed", session_id=session_id,
                              user_input=p["user_input"], intent=p["intent"],
                              plan=plan, budgets=p["budgets"],
                              validation=p["validation"],
                              link_retry=p.get("link_retry", 0))
        try:
            self._finish(result, sess, p["intent"], p["context"], plan,
                         p["budgets"], p["validation"], time.time())
        except ChainInterrupted as e:
            result.status = "interrupted"
            result.error = str(e)
            result.metadata["interrupted_at"] = e.stage
        return result

    def interrupt(self, session_id: str) -> bool:
        sess = self.store.get(session_id)
        sess.interrupted = True
        sess.log("HUMAN", "收到人工中止指令", level="warn", check_interrupt=False)
        return True

    def get_events(self, session_id: str, after_seq: int = 0) -> List[dict]:
        return self.store.get(session_id).events_after(after_seq)

    # ---------- 工具 ----------

    def list_skills(self) -> List[dict]:
        return [s.to_dict() for s in self.registry.list_all()]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    chain = PayloadDesignChain()
    r = chain.invoke({"user_input":
                      "设计GEO Ka频段高通量通信载荷，EIRP>=62dBW，G/T>=12，"
                      "48个波束相控阵，DTP柔性体制，容量50Gbps，寿命15年"})
    print("\nSTATUS:", r.status)
    print("EVENTS:")
    for e in chain.get_events(r.session_id):
        print(f"  [{e['seq']:02d}] {e['stage']:<12} {e['message']}")
    print(f"\n方案文档 {len(r.design_scheme)} 字符")
    print(r.design_scheme[:800])
