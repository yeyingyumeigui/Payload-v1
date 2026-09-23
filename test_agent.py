"""文生载荷智能体 测试集 (test_agent.py)

零依赖测试框架（unittest），覆盖:
  T1  意图解析: 载荷类型/轨道/频段/指标提取/歧义检测
  T2  频段识别陷阱: 12m 伞天线、300kg、30 人不得误判为频段
  T3  澄清闸口: 缺项必澄清、warning 放行、blocking 阻断
  T4  天线选型: 五要素评分、频段硬过滤、单波束/多波束模式匹配
  T5  单机选型: 货架优先、频段错配记缺口（不回退错误频段）
  T6  非通信分支: 遥感分辨率判据、SAR、导航、科学
  T7  平台选型: 可行性预筛、SSO→LEO 轨道承接、利用率告警
  T8  运载选型: 入轨能力/经济性/履历/包络
  T9  链路预算: FSPL 物理正确性、余量门槛、自适应 MODCOD、雨衰方向
  T10 三重校验: 语法/语义/合规、频段豁免、平台可行性
  T11 主链路: 各载荷类型端到端、事件流、状态码、人工确认、中止
  T12 Skill 注册表: 11 个 Skill、依赖拓扑、异常分级表
  T13 文档生成: Markdown 章节完整、HTML 渲染（表格/标题/目录）

运行:  python test_agent.py     (或 python -m unittest test_agent -v)
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from payload_agent import (  # noqa: E402
    KeywordIntentParser, build_clarifications, SelectionEngine,
    SelectionRequirement, AntennaSelector, EquipmentSelector,
    PlatformSelector, LauncherSelector, NonCommSelector,
    free_space_loss_db, rain_attenuation_db, select_modcod, orbit_distance_km,
    build_link_budgets, validate_scheme, LinkBudget,
    PayloadDesignChain, SkillRegistry, AnomalyLevel,
    retrieve_context, generate_scheme, export_html, markdown_to_html_body,
    build_toc, get_catalog_summary,
)
from payload_agent.link_budget import MODCOD_LADDER, MARGIN_THRESHOLD_DB  # noqa: E402

PARSER = KeywordIntentParser()
ENGINE = SelectionEngine()


def parse_and_run(text: str):
    it = PARSER.parse(text)
    return it, ENGINE.run(it)


class T1IntentParsing(unittest.TestCase):
    """意图解析"""

    def test_comm_ka_geo(self):
        r = PARSER.parse("设计GEO Ka频段高通量通信载荷，EIRP>=62dBW，G/T>=12，"
                         "48个波束相控阵，DTP柔性体制，容量50Gbps，寿命15年")
        self.assertEqual(r.payload_type, "communication")
        self.assertEqual(r.orbit_type, "GEO")
        self.assertIn("Ka", r.frequency_bands)
        self.assertEqual(r.forwarding_mode, "dtp")
        self.assertIn("相控阵天线", r.key_technologies)
        self.assertIn("数字透明处理", r.key_technologies)
        self.assertAlmostEqual(r.metrics["eirp_dbw"], 62.0)
        self.assertAlmostEqual(r.metrics["gt_dbk"], 12.0)
        self.assertAlmostEqual(r.metrics["beam_num"], 48.0)
        self.assertAlmostEqual(r.metrics["capacity_gbps"], 50.0)
        self.assertAlmostEqual(r.metrics["life_years"], 15.0)

    def test_remote_sensing_subtype(self):
        r = PARSER.parse("设计SSO太阳同步轨道SAR遥感载荷，分辨率优于1m")
        self.assertEqual(r.payload_type, "remote_sensing")
        self.assertEqual(r.orbit_type, "SSO")
        self.assertEqual(r.rs_subtype, "SAR")
        self.assertAlmostEqual(r.metrics["resolution_m"], 1.0)

    def test_navigation_science(self):
        self.assertEqual(PARSER.parse("MEO导航载荷，B1C").payload_type, "navigation")
        self.assertEqual(PARSER.parse("LEO科学实验载荷，磁强计").payload_type, "science")

    def test_ambiguity_dtp_vs_transparent(self):
        r = PARSER.parse("设计GEO透明转发载荷，同时要DTP数字透明处理")
        self.assertIsNotNone(r.ambiguity)

    def test_metric_comparators(self):
        for txt, key, val in [
            ("EIRP≥55dBW", "eirp_dbw", 55.0),
            ("EIRP<=55dBW", "eirp_dbw", 55.0),
            ("EIRP不低于55dBW", "eirp_dbw", 55.0),
            ("质量不超过300kg", "mass_kg", 300.0),
            ("功耗≤8kW", "power_w", 8000.0),
            ("容量20Gbps", "capacity_gbps", 20.0),
            ("容量500Mbps", "capacity_gbps", 0.5),
            ("带宽500MHz", "bandwidth_mhz", 500.0),
            ("幅宽20km", "swath_km", 20.0),
        ]:
            m = PARSER.parse("设计GEO Ka通信载荷 " + txt).metrics
            self.assertIn(key, m, f"未提取 {key}: {txt}")
            self.assertAlmostEqual(m[key], val, places=3, msg=txt)


class T2FrequencyTraps(unittest.TestCase):
    """频段识别陷阱（数值必须带 GHz 上下文）"""

    def test_no_false_band_from_numbers(self):
        r = PARSER.parse("设计LEO载荷，12米伞天线，质量300kg，服务30万人")
        self.assertNotIn("Ka", r.frequency_bands)
        self.assertNotIn("Ku", r.frequency_bands)
        self.assertNotIn("C", r.frequency_bands)

    def test_numeric_ghz_band(self):
        r = PARSER.parse("设计GEO载荷，30GHz上行、20GHz下行")
        self.assertIn("Ka", r.frequency_bands)

    def test_l_band_markers(self):
        r = PARSER.parse("设计载荷，下行1559MHz")
        self.assertIn("L", r.frequency_bands)


class T3ClarifyGate(unittest.TestCase):
    """澄清闸口"""

    def test_vague_request_blocks(self):
        r = PARSER.parse("帮我看看遥感载荷")
        cl = build_clarifications(r)
        fields = {c["field"] for c in cl}
        self.assertIn("orbit_type", fields)
        self.assertTrue(any(c["level"] == "blocking" for c in cl))

    def test_comm_missing_band_blocks(self):
        r = PARSER.parse("设计GEO通信载荷")
        cl = build_clarifications(r)
        self.assertIn("frequency_bands", {c["field"] for c in cl})

    def test_complete_request_no_blocking(self):
        r = PARSER.parse("设计GEO Ka频段通信载荷，EIRP>=58dBW，DTP体制")
        cl = build_clarifications(r)
        self.assertFalse([c for c in cl if c["level"] == "blocking"])

    def test_warning_level_for_missing_eirp(self):
        r = PARSER.parse("设计GEO Ka频段DTP通信载荷")
        cl = build_clarifications(r)
        warns = [c for c in cl if c["level"] == "warning"]
        self.assertTrue(any(c["field"] == "eirp_dbw" for c in warns))


class T4AntennaSelection(unittest.TestCase):
    """天线选型"""

    def test_ka_hts_selected(self):
        it, plan = parse_and_run(
            "设计GEO Ka频段高通量通信载荷，EIRP>=62dBW，G/T>=12，48个波束相控阵，DTP体制")
        self.assertEqual(plan.antenna["model"], "ANT-AESA-KA-HTS")
        self.assertGreaterEqual(plan.antenna["eirp_cap_dbw"], it.metrics["eirp_dbw"])

    def test_single_beam_prefers_reflector(self):
        it, plan = parse_and_run("设计GEO Ku频段透明转发载荷，单波束，EIRP>=52dBW，G/T>=5")
        self.assertEqual(plan.requirement.mode, "单波束")
        self.assertIn("单波束", plan.antenna["modes"])

    def test_band_hard_filter(self):
        it = PARSER.parse("设计GEO Ka频段通信载荷，EIRP>=55dBW，DTP体制")
        req = SelectionRequirement.from_intent(it)
        cands = AntennaSelector().select(req, top_k=5)
        for _, a, _ in cands:
            self.assertIn("ka", a["band"].lower())

    def test_exclude_models(self):
        it = PARSER.parse("设计GEO Ka频段通信载荷，EIRP>=55dBW，DTP体制")
        req = SelectionRequirement.from_intent(it)
        cands = AntennaSelector().select(req, top_k=3,
                                         exclude_models=["ANT-AESA-KA-HTS"])
        self.assertNotIn("ANT-AESA-KA-HTS", [a["model"] for _, a, _ in cands])

    def test_five_factor_weights_sum_100(self):
        from payload_agent.catalog import ANTENNA_SELECTION_CRITERIA
        self.assertEqual(sum(c["weight"] for c in ANTENNA_SELECTION_CRITERIA), 100)


class T5EquipmentSelection(unittest.TestCase):
    """单机选型"""

    def test_ka_chain_complete(self):
        it, plan = parse_and_run(
            "设计GEO Ka频段高通量通信载荷，EIRP>=60dBW，G/T>=10，DTP体制")
        cats = {e["cat"] for e in plan.equipment}
        for need in ("LNA", "DCONV", "UCONV", "DTP", "TTC", "BCN"):
            self.assertIn(need, cats)
        self.assertEqual(plan.gaps, [])

    def test_l_band_no_wrong_band_fallback(self):
        """L 波段载荷不得回退到 Ka/Ku 变频器（工程错误），应记缺口"""
        it = PARSER.parse("设计LEO L波段手机直连通信载荷，EIRP>=48dBW，12米伞天线")
        req = SelectionRequirement.from_intent(it)
        picked, gaps = EquipmentSelector().select(it, req)
        for e in picked:
            if e["cat"] in ("DCONV", "UCONV", "OMUX", "CIRC"):
                self.assertTrue("l" in e["band"].lower() or "全频段" in e["band"],
                                f"{e['model']} 频段错配: {e['band']}")
        gap_cats = {g["cat"] for g in gaps}
        self.assertTrue(gap_cats & {"DCONV", "UCONV", "OMUX", "CIRC"},
                        "L 波段缺口未被检出")

    def test_ttc_bcn_always_present(self):
        it = PARSER.parse("设计LEO L波段通信载荷，EIRP>=45dBW，DTP体制")
        req = SelectionRequirement.from_intent(it)
        picked, _ = EquipmentSelector().select(it, req)
        cats = {e["cat"] for e in picked}
        self.assertIn("TTC", cats)
        self.assertIn("BCN", cats)

    def test_heritage_priority(self):
        """同等条件下飞行继承货架优先"""
        it = PARSER.parse("设计GEO Ka频段透明转发通信载荷，EIRP>=55dBW")
        req = SelectionRequirement.from_intent(it)
        picked, _ = EquipmentSelector().select(it, req)
        lna = [e for e in picked if e["cat"] == "LNA"]
        self.assertTrue(lna and lna[0]["heritage"] >= 3)


class T6NonCommSelection(unittest.TestCase):
    """非通信载荷分支"""

    def test_optical_rs_resolution(self):
        it, plan = parse_and_run("设计SSO太阳同步轨道遥感载荷，全色分辨率优于0.5m，幅宽12km")
        self.assertEqual(plan.payload_type, "remote_sensing")
        self.assertIsNotNone(plan.noncomm_top)
        self.assertEqual(plan.noncomm_top["model"], "RS-PAN-05")
        self.assertIsNone(plan.antenna)
        self.assertFalse(plan.is_comm)

    def test_sar_subtype(self):
        it, plan = parse_and_run("设计SSO太阳同步轨道SAR遥感载荷，分辨率1m")
        self.assertEqual(it.rs_subtype, "SAR")
        self.assertIn("SAR", plan.noncomm_top["subtype"])

    def test_navigation(self):
        it, plan = parse_and_run("设计MEO中轨导航载荷，B1C信号体制，寿命12年")
        self.assertEqual(plan.payload_type, "navigation")
        self.assertIsNotNone(plan.noncomm_top)
        self.assertTrue(plan.feasible)

    def test_science(self):
        it, plan = parse_and_run("设计LEO低轨科学实验载荷，磁强计，寿命5年")
        self.assertEqual(plan.payload_type, "science")
        self.assertIsNotNone(plan.noncomm_top)

    def test_noncomm_criteria_defined(self):
        from payload_agent.catalog import NONCOMM_SELECTION_CRITERIA
        for t in ("remote_sensing", "navigation", "science"):
            self.assertIn(t, NONCOMM_SELECTION_CRITERIA)
            self.assertTrue(NONCOMM_SELECTION_CRITERIA[t])


class T7PlatformSelection(unittest.TestCase):
    """平台选型"""

    def test_geo_platform(self):
        it, plan = parse_and_run(
            "设计GEO Ka频段高通量通信载荷，EIRP>=60dBW，G/T>=10，DTP体制，寿命15年")
        self.assertIn("GEO", plan.platform["orbits"])
        self.assertGreaterEqual(plan.platform["life_years"], 15)

    def test_sso_can_use_leo_platform(self):
        it, plan = parse_and_run("设计SSO太阳同步轨道遥感载荷，全色分辨率优于0.5m")
        self.assertTrue(plan.feasible)
        self.assertTrue({"SSO", "LEO"} & set(plan.platform["orbits"].split("/")))

    def test_feasibility_prefilter(self):
        """载荷超所有平台能力时判不可行"""
        feasible, rejected = PlatformSelector().select(
            payload_mass=5000.0, payload_power=50000.0, orbit="LEO")
        self.assertEqual(feasible, [])
        self.assertTrue(rejected)

    def test_rejected_reasons_recorded(self):
        feasible, rejected = PlatformSelector().select(
            payload_mass=100.0, payload_power=500.0, orbit="GEO")
        for r in rejected:
            self.assertTrue(r["reason"])

    def test_mass_power_within_capacity(self):
        it, plan = parse_and_run(
            "设计GEO Ka频段高通量通信载荷，EIRP>=60dBW，G/T>=10，DTP体制")
        self.assertLessEqual(plan.payload_mass_est, plan.platform["payload_mass_kg"])
        self.assertLessEqual(plan.payload_power_est, plan.platform["payload_power_w"])

    def test_no_fake_default_budget(self):
        """用户未给质量约束时不得虚构硬约束"""
        it = PARSER.parse("设计GEO Ka频段通信载荷，DTP体制")
        req = SelectionRequirement.from_intent(it)
        self.assertIsNone(req.mass_budget_kg)
        self.assertIsNone(req.power_budget_w)

    def test_user_hard_constraint_honored(self):
        it, plan = parse_and_run("设计GEO Ka频段通信载荷，EIRP>=55dBW，DTP体制，质量不超过200kg")
        self.assertAlmostEqual(plan.requirement.mass_budget_kg, 200.0)
        self.assertTrue(any("超用户约束" in w or "轻量化" in w for w in plan.warnings)
                        or plan.payload_mass_est <= 200.0)


class T8LauncherSelection(unittest.TestCase):
    """运载选型"""

    def test_geo_gto_capable(self):
        it, plan = parse_and_run(
            "设计GEO Ka频段高通量通信载荷，EIRP>=60dBW，G/T>=10，DTP体制")
        lv = plan.launcher
        self.assertIsNotNone(lv["gto_kg"])
        self.assertGreaterEqual(lv["gto_kg"], plan.sat_mass_est)

    def test_sso_uses_sso_capability(self):
        it, plan = parse_and_run("设计SSO太阳同步轨道遥感载荷，全色分辨率优于0.5m")
        lv = plan.launcher
        self.assertIsNotNone(lv.get("sso_kg"))
        self.assertGreaterEqual(lv["sso_kg"], plan.sat_mass_est)

    def test_four_factor_weights_sum_100(self):
        self.assertEqual(40 + 25 + 20 + 15, 100)

    def test_oversized_sat_flagged(self):
        out = LauncherSelector().select(sat_mass_kg=99999.0, orbit="LEO")
        self.assertTrue(out)
        reasons = " ".join(out[0][2])
        self.assertIn("不足", reasons)


class T9LinkBudget(unittest.TestCase):
    """链路预算"""

    def test_fspl_geo_ka(self):
        """GEO Ka 下行 FSPL 约 200 dB 量级（工程常识校验）"""
        fspl = free_space_loss_db(20.0, 35786.0)
        self.assertGreater(fspl, 195.0)
        self.assertLess(fspl, 210.0)

    def test_fspl_monotonic(self):
        self.assertLess(free_space_loss_db(12.0, 35786.0),
                        free_space_loss_db(30.0, 35786.0))
        self.assertLess(free_space_loss_db(20.0, 600.0),
                        free_space_loss_db(20.0, 35786.0))

    def test_fspl_invalid_input(self):
        with self.assertRaises(ValueError):
            free_space_loss_db(0.0, 100.0)

    def test_rain_attenuation_availability_direction(self):
        """可用性要求越高（p 越小）所需雨衰余量越大"""
        a999 = rain_attenuation_db("Ka", 30.0, 99.9)
        a9999 = rain_attenuation_db("Ka", 30.0, 99.99)
        self.assertGreater(a9999, a999)

    def test_rain_band_ordering(self):
        self.assertLess(rain_attenuation_db("L", 30.0, 99.9),
                        rain_attenuation_db("Ka", 30.0, 99.9))

    def test_rain_elevation_correction(self):
        """仰角越低路径越长，雨衰越大"""
        self.assertGreater(rain_attenuation_db("Ku", 10.0, 99.9),
                           rain_attenuation_db("Ku", 60.0, 99.9))

    def test_laser_no_rain(self):
        self.assertEqual(rain_attenuation_db("激光", 30.0, 99.9), 0.0)

    def test_modcod_ladder_descending(self):
        effs = [e for _, e, _ in MODCOD_LADDER]
        self.assertEqual(effs, sorted(effs, reverse=True))

    def test_select_modcod_adaptive(self):
        """C/N 越高选越高阶体制；C/N 极低时回落最低阶"""
        hi, eff_hi, _ = select_modcod(30.0)
        lo, eff_lo, _ = select_modcod(6.0)
        self.assertGreater(eff_hi, eff_lo)
        self.assertEqual(hi, MODCOD_LADDER[0][0])
        self.assertEqual(lo, MODCOD_LADDER[-1][0])

    def test_margin_threshold_constant(self):
        self.assertAlmostEqual(MARGIN_THRESHOLD_DB, 3.0)

    def test_orbit_distance_ordering(self):
        self.assertLess(orbit_distance_km("LEO"), orbit_distance_km("GEO"))

    def test_geo_ka_links_close(self):
        it, plan = parse_and_run(
            "设计GEO Ka频段高通量通信载荷，EIRP>=62dBW，G/T>=12，48个波束相控阵，DTP体制")
        budgets = build_link_budgets(plan, it)
        self.assertTrue(budgets)
        for b in budgets:
            self.assertTrue(b.passed, f"{b.direction} 余量 {b.margin_db:.2f} dB 未通过")
            self.assertGreater(b.capacity_mbps, 0)

    def test_laser_isl_fixed_modcod(self):
        it, plan = parse_and_run(
            "设计LEO Ka频段宽带通信载荷，相控阵，EIRP>=45dBW，含激光星间链路，DTP体制")
        budgets = build_link_budgets(plan, it)
        isl = [b for b in budgets if "激光" in b.direction]
        self.assertTrue(isl)
        self.assertEqual(isl[0].modcod, "DPSK_激光")

    def test_noncomm_data_downlink(self):
        it, plan = parse_and_run("设计SSO太阳同步轨道遥感载荷，全色分辨率优于0.5m")
        budgets = build_link_budgets(plan, it)
        self.assertEqual(len(budgets), 1)
        self.assertIn("数传", budgets[0].direction)

    def test_breakdown_nonempty(self):
        b = LinkBudget(direction="t", band="Ka", freq_ghz=20.0, distance_km=35786.0,
                       eirp_dbw=60.0, gt_dbk=10.0, bandwidth_mhz=250.0).compute()
        self.assertTrue(b.breakdown)
        self.assertTrue(b.markdown())


class T10Validation(unittest.TestCase):
    """三重校验"""

    def test_three_categories_present(self):
        it, plan = parse_and_run(
            "设计GEO Ka频段高通量通信载荷，EIRP>=62dBW，G/T>=12，48个波束相控阵，DTP体制")
        budgets = build_link_budgets(plan, it)
        v = validate_scheme(plan, budgets, it)
        cats = {c["category"] for c in v.checks}
        self.assertEqual(cats, {"语法", "语义", "合规"})
        self.assertTrue(v.valid, v.errors)

    def test_ttc_bcn_band_exempt(self):
        """测控/信标固定 S 波段，不得判为频段错配"""
        it, plan = parse_and_run(
            "设计GEO Ka频段高通量通信载荷，EIRP>=60dBW，G/T>=10，DTP体制")
        budgets = build_link_budgets(plan, it)
        v = validate_scheme(plan, budgets, it)
        band_check = [c for c in v.checks if "频段" in c["item"]]
        self.assertTrue(band_check)
        self.assertTrue(band_check[0]["passed"], band_check[0]["detail"])

    def test_infeasible_platform_fails(self):
        it = PARSER.parse("设计LEO Ka频段通信载荷，EIRP>=60dBW，G/T>=10，DTP体制")
        plan = ENGINE.run(it)
        # 人为构造不可行
        plan.feasible = False
        plan.platforms = []
        budgets = build_link_budgets(plan, it)
        v = validate_scheme(plan, budgets, it)
        self.assertFalse(v.valid)

    def test_gaps_produce_warning_not_error(self):
        it, plan = parse_and_run("设计LEO L波段手机直连通信载荷，EIRP>=48dBW，12米伞天线")
        self.assertTrue(plan.gaps)
        budgets = build_link_budgets(plan, it)
        v = validate_scheme(plan, budgets, it)
        self.assertTrue(any("货架" in w for w in v.warnings))

    def test_validation_markdown_and_dict(self):
        it, plan = parse_and_run("设计GEO Ka频段通信载荷，EIRP>=58dBW，G/T>=10，DTP体制")
        budgets = build_link_budgets(plan, it)
        v = validate_scheme(plan, budgets, it)
        self.assertIn("三重校验", v.markdown())
        self.assertIn("valid", v.to_dict())


class T11ChainEndToEnd(unittest.TestCase):
    """主链路端到端"""

    @classmethod
    def setUpClass(cls):
        cls.chain = PayloadDesignChain()

    def test_geo_ka_completed(self):
        r = self.chain.invoke({"user_input":
            "设计GEO Ka频段高通量通信载荷，EIRP>=62dBW，G/T>=12，"
            "48个波束相控阵，DTP柔性体制，容量50Gbps，寿命15年"})
        self.assertEqual(r.status, "completed")
        self.assertTrue(r.validation.valid, r.validation.errors)
        self.assertIn("# ", r.design_scheme)
        self.assertGreater(len(r.design_scheme), 3000)
        self.assertEqual(r.metadata["feasible"], True)

    def test_need_clarify(self):
        r = self.chain.invoke({"user_input": "帮我看看遥感载荷"})
        self.assertEqual(r.status, "need_clarify")
        self.assertTrue(r.clarifications)
        self.assertEqual(r.design_scheme, "")

    def test_skip_clarify_proceeds(self):
        r = self.chain.invoke({"user_input": "帮我看看遥感载荷", "skip_clarify": True})
        self.assertIn(r.status, ("completed", "infeasible"))

    def test_remote_sensing_end_to_end(self):
        r = self.chain.invoke({"user_input":
            "设计SSO太阳同步轨道遥感载荷，全色分辨率优于0.5m，幅宽12km"})
        self.assertEqual(r.status, "completed")
        self.assertEqual(r.metadata["payload_type"], "remote_sensing")
        self.assertIn("遥感载荷选型", r.design_scheme)

    def test_navigation_and_science_end_to_end(self):
        for txt, ptype in [("设计MEO中轨导航载荷，B1C信号体制，寿命12年", "navigation"),
                           ("设计LEO低轨科学实验载荷，磁强计，寿命5年", "science")]:
            r = self.chain.invoke({"user_input": txt})
            self.assertEqual(r.metadata["payload_type"], ptype)
            self.assertIn(r.status, ("completed", "infeasible"))

    def test_events_recorded(self):
        r = self.chain.invoke({"user_input":
            "设计GEO Ka频段高通量通信载荷，EIRP>=60dBW，G/T>=10，DTP体制"})
        evs = self.chain.get_events(r.session_id)
        stages = [e["stage"] for e in evs]
        for need in ("SK-INTENT", "SK-CLARIFY", "SK-RETRIEVE", "SK-SELECT",
                     "SK-BUDGET", "SK-VALID", "SK-DOC"):
            self.assertIn(need, stages)
        self.assertEqual([e["seq"] for e in evs], list(range(1, len(evs) + 1)))

    def test_events_incremental(self):
        r = self.chain.invoke({"user_input":
            "设计GEO Ka频段高通量通信载荷，EIRP>=60dBW，G/T>=10，DTP体制"})
        all_evs = self.chain.get_events(r.session_id)
        tail = self.chain.get_events(r.session_id, after_seq=len(all_evs) - 2)
        self.assertEqual(len(tail), 2)

    def test_confirm_mode_flow(self):
        r = self.chain.invoke({"user_input":
            "设计GEO Ka频段高通量通信载荷，EIRP>=60dBW，G/T>=10，DTP体制",
            "confirm_mode": True})
        self.assertEqual(r.status, "awaiting_confirmation")
        self.assertEqual(r.design_scheme, "")
        r2 = self.chain.confirm_design(r.session_id)
        self.assertEqual(r2.status, "completed")
        self.assertGreater(len(r2.design_scheme), 3000)

    def test_confirm_with_override(self):
        r = self.chain.invoke({"user_input":
            "设计GEO Ka频段高通量通信载荷，EIRP>=60dBW，G/T>=10，DTP体制",
            "confirm_mode": True})
        if r.plan and len(r.plan.platforms) > 1:
            alt = r.plan.platforms[1][0]["model"]
            r2 = self.chain.confirm_design(r.session_id, overrides={"platform": alt})
            self.assertEqual(r2.plan.platform["model"], alt)
        else:
            r2 = self.chain.confirm_design(r.session_id)
            self.assertEqual(r2.status, "completed")

    def test_confirm_without_pending_errors(self):
        r = self.chain.confirm_design("no-such-session")
        self.assertEqual(r.status, "error")

    def test_interrupt(self):
        r = self.chain.invoke({"user_input":
            "设计GEO Ka频段高通量通信载荷，EIRP>=60dBW，G/T>=10，DTP体制",
            "confirm_mode": True})
        self.assertTrue(self.chain.interrupt(r.session_id))
        r2 = self.chain.confirm_design(r.session_id)
        self.assertEqual(r2.status, "interrupted")

    def test_to_dict_serializable(self):
        import json
        r = self.chain.invoke({"user_input":
            "设计GEO Ka频段高通量通信载荷，EIRP>=60dBW，G/T>=10，DTP体制"})
        d = r.to_dict()
        json.dumps(d, ensure_ascii=False, default=str)   # 不应抛异常

    def test_empty_input_safe(self):
        r = self.chain.invoke({"user_input": ""})
        self.assertEqual(r.status, "need_clarify")

    def test_result_status_enum(self):
        r = self.chain.invoke({"user_input":
            "设计GEO Ka频段高通量通信载荷，EIRP>=60dBW，G/T>=10，DTP体制"})
        self.assertIn(r.status, {"completed", "need_clarify", "infeasible",
                                 "awaiting_confirmation", "interrupted", "error"})


class T12SkillRegistry(unittest.TestCase):
    """Skill 注册表"""

    def setUp(self):
        self.reg = SkillRegistry()

    def test_eleven_skills(self):
        self.assertEqual(len(self.reg.list_all()), 11)
        ids = {s.id for s in self.reg.list_all()}
        for need in ("SK-INTENT", "SK-CLARIFY", "SK-RETRIEVE", "SK-ANTSEL",
                     "SK-EQUIP", "SK-BUDGET", "SK-PLAT", "SK-LAUNCH",
                     "SK-VALID", "SK-DOC", "SK-WORD"):
            self.assertIn(need, ids)

    def test_stages_cover_pipeline(self):
        stages = self.reg.stages()
        self.assertIn("需求理解", stages)
        self.assertIn("成果输出", stages)
        self.assertTrue(all(stages.values()))

    def test_dependency_chain_topological(self):
        chain = self.reg.get_dependency_chain("SK-DOC")
        self.assertEqual(chain[0], "SK-INTENT")
        self.assertEqual(chain[-1], "SK-DOC")
        idx = {s: i for i, s in enumerate(chain)}
        for s in chain:
            for dep in self.reg.get(s).deps:
                if dep in idx:
                    self.assertLess(idx[dep], idx[s], f"{dep} 应在 {s} 之前")

    def test_dependency_chain_includes_antsel(self):
        self.assertIn("SK-ANTSEL", self.reg.get_dependency_chain("SK-DOC"))

    def test_anomaly_levels_valid(self):
        rows = self.reg.anomaly_table()
        self.assertGreaterEqual(len(rows), 25)
        levels = {r["level"] for r in rows}
        self.assertTrue(levels <= {"L1", "L2", "L3"})
        self.assertIn("L3", levels)

    def test_every_skill_has_anomaly_rules(self):
        for s in self.reg.list_all():
            self.assertTrue(s.anomaly_map, f"{s.id} 缺异常规则")
            for r in s.anomaly_map:
                self.assertIsInstance(r.level, AnomalyLevel)
                self.assertTrue(r.auto_action and r.manual_action)

    def test_unbound_skill_raises(self):
        with self.assertRaises(RuntimeError):
            self.reg.execute("SK-DOC")

    def test_unknown_skill_raises(self):
        with self.assertRaises(KeyError):
            self.reg.execute("SK-NOPE")

    def test_bind_and_execute(self):
        self.reg.bind("SK-INTENT", lambda user_input, **kw: user_input.upper())
        self.assertEqual(self.reg.execute("SK-INTENT", user_input="abc"), "ABC")

    def test_l1_exception_degrades_to_none(self):
        def boom(**kw):
            raise ValueError("INT-01 关键词命中为空")
        self.reg.bind("SK-INTENT", boom)
        self.assertIsNone(self.reg.execute("SK-INTENT"))

    def test_l3_exception_propagates(self):
        def boom(**kw):
            raise ValueError("PLA-02 所有平台承载不足")
        self.reg.bind("SK-PLAT", boom)
        with self.assertRaises(ValueError):
            self.reg.execute("SK-PLAT")

    def test_chain_binds_all_executable_skills(self):
        chain = PayloadDesignChain()
        bound = [s.id for s in chain.registry.list_all() if s.bound]
        self.assertEqual(len(bound), 10)      # SK-WORD 由外部导出函数承担
        self.assertNotIn("SK-WORD", bound)

    def test_list_skills_schema(self):
        chain = PayloadDesignChain()
        rows = chain.list_skills()
        self.assertEqual(len(rows), 11)
        for r in rows:
            for k in ("id", "name", "stage", "deps", "anomaly_rules"):
                self.assertIn(k, r)


class T13DocGeneration(unittest.TestCase):
    """文档生成与导出"""

    @classmethod
    def setUpClass(cls):
        cls.chain = PayloadDesignChain()
        cls.r = cls.chain.invoke({"user_input":
            "设计GEO Ka频段高通量通信载荷，EIRP>=62dBW，G/T>=12，"
            "48个波束相控阵，DTP柔性体制，容量50Gbps，寿命15年"})

    def test_scheme_sections(self):
        md = self.r.design_scheme
        for sec in ("一、需求分析", "二、选型需求", "三、载荷方案", "四、平台方案",
                    "五、发射方案", "六、指标汇总", "七、链路预算",
                    "八、方案三重校验", "九、风险与异常处置", "十、结论"):
            self.assertIn(sec, md)

    def test_scheme_contains_tables(self):
        self.assertGreater(self.r.design_scheme.count("|---"), 5)

    def test_scheme_contains_selection(self):
        md = self.r.design_scheme
        self.assertIn("ANT-AESA-KA-HTS", md)
        self.assertIn("GEO-MID42", md)
        self.assertIn("货架", md)

    def test_markdown_to_html_table(self):
        h = markdown_to_html_body("| a | b |\n|---|---|\n| 1 | 2 |")
        self.assertIn("<table>", h)
        self.assertIn("<th>a</th>", h)
        self.assertIn("<td>1</td>", h)

    def test_markdown_to_html_heading_and_anchor(self):
        h = markdown_to_html_body("## 三、载荷方案")
        self.assertIn("<h2", h)
        self.assertIn("载荷方案", h)

    def test_markdown_to_html_code_and_list(self):
        h = markdown_to_html_body("```\nA → B\n```\n- x\n- **y**")
        self.assertIn("<pre><code>", h)
        self.assertIn("<li>", h)
        self.assertIn("<strong>y</strong>", h)

    def test_html_escaping(self):
        h = markdown_to_html_body("值 <5> & 更多")
        self.assertIn("&lt;5&gt;", h)
        self.assertIn("&amp;", h)

    def test_details_block(self):
        h = markdown_to_html_body("<details><summary>被筛除的平台</summary>\n\n内容\n\n</details>")
        self.assertIn("<details>", h)
        self.assertIn("<summary>", h)

    def test_toc_from_h2_h3(self):
        toc = build_toc("# T\n## 一、需求分析\n### 子节\n## 二、方案")
        self.assertIn("toc-2", toc)
        self.assertIn("toc-3", toc)
        self.assertIn('href="#一-需求分析"', toc)

    def test_export_html_file(self):
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "output", "_test_export.html")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        export_html(self.r.design_scheme, "测试方案", out)
        self.assertTrue(os.path.exists(out))
        with open(out, encoding="utf-8") as f:
            html = f.read()
        for token in ("<!DOCTYPE html>", '<meta charset="utf-8">',
                      "downloadDoc()", "window.print()", "@media print",
                      '<nav class="toc">', "</html>"):
            self.assertIn(token, html)
        os.remove(out)

    def test_retrieve_context_content(self):
        ctx = retrieve_context(self.r.intent)
        self.assertIn("天线五要素选型判据", ctx)
        self.assertIn("适用标准与规范", ctx)
        self.assertIn("货架产品库规模", ctx)
        self.assertLessEqual(len(ctx), 7000)

    def test_noncomm_doc_uses_noncomm_section(self):
        r = self.chain.invoke({"user_input":
            "设计SSO太阳同步轨道遥感载荷，全色分辨率优于0.5m，幅宽12km"})
        self.assertIn("遥感载荷选型", r.design_scheme)
        self.assertNotIn("天线选型（五要素评分）", r.design_scheme)


class T14CatalogIntegrity(unittest.TestCase):
    """货架产品库完整性"""

    def test_summary_counts(self):
        s = get_catalog_summary()
        self.assertGreaterEqual(s["天线"]["count"], 9)
        self.assertGreaterEqual(s["单机"]["count"], 17)
        self.assertGreaterEqual(s["平台"]["count"], 6)
        self.assertGreaterEqual(s["运载"]["count"], 10)
        self.assertEqual(set(s["转发体制"]), {"transparent", "regenerative", "dtp"})

    def test_no_duplicate_models(self):
        from payload_agent.catalog import (
            CATALOG_ANTENNAS, CATALOG_EQUIPMENT, CATALOG_RS_PAYLOADS,
            CATALOG_NAV_PAYLOADS, CATALOG_SCI_PAYLOADS, SATELLITE_PLATFORMS,
        )
        for name, items in [("天线", CATALOG_ANTENNAS), ("单机", CATALOG_EQUIPMENT),
                            ("遥感", CATALOG_RS_PAYLOADS), ("导航", CATALOG_NAV_PAYLOADS),
                            ("科学", CATALOG_SCI_PAYLOADS), ("平台", SATELLITE_PLATFORMS)]:
            models = [it["model"] for it in items]
            self.assertEqual(len(models), len(set(models)), f"{name} 存在重复型号")

    def test_required_fields(self):
        from payload_agent.catalog import CATALOG_ANTENNAS, CATALOG_EQUIPMENT
        for a in CATALOG_ANTENNAS:
            for k in ("model", "name", "band", "eirp_cap_dbw", "gt_dbk",
                      "mass_kg", "power_w", "modes", "heritage"):
                self.assertIn(k, a, f"{a.get('model')} 缺字段 {k}")
        for e in CATALOG_EQUIPMENT:
            for k in ("model", "name", "cat", "band", "mass_kg", "power_w", "heritage"):
                self.assertIn(k, e, f"{e.get('model')} 缺字段 {k}")

    def test_heritage_range(self):
        from payload_agent.catalog import CATALOG_ANTENNAS, CATALOG_EQUIPMENT
        for it in CATALOG_ANTENNAS + CATALOG_EQUIPMENT:
            self.assertIn(it["heritage"], (1, 2, 3, 4))

    def test_ku_single_beam_product_exists(self):
        """Ku 单波束货架天线存在（支撑单波束选型）"""
        from payload_agent.catalog import CATALOG_ANTENNAS
        ku_single = [a for a in CATALOG_ANTENNAS
                     if "ku" in a["band"].lower() and "单波束" in a["modes"]]
        self.assertTrue(ku_single)

    def test_all_bands_have_lna(self):
        """主要业务频段均应有 LNA 货架品"""
        from payload_agent.catalog import CATALOG_EQUIPMENT
        lna_bands = {e["band"].lower() for e in CATALOG_EQUIPMENT if e["cat"] == "LNA"}
        for b in ("ka", "ku", "l"):
            self.assertTrue(any(b in x for x in lna_bands), f"{b.upper()} 缺 LNA 货架品")


if __name__ == "__main__":
    unittest.main(verbosity=2)
