# -*- coding: utf-8 -*-
"""#63 验证：report_gen 三引擎章节（方向图 grid/cut + EIRP 覆盖 + 轨道仿真）。
rasterize=False 快速构建 → 断言章节/SVG/表存在；再测 LEO(SSO) 场景轨道章。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import design_data as DD                       # noqa: E402
import design_engine as DE                     # noqa: E402
import design_app as DA                        # noqa: E402
import report_gen as RG                        # noqa: E402

ok = fail = 0


def chk(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print("  [OK] %s %s" % (name, extra))
    else:
        fail += 1
        print("  [FAIL] %s %s" % (name, extra))


# ---- 场景 1：GEO 固面（巴基斯坦）----
print("== 场景1 GEO 固面（巴基斯坦）==")
cfg = dict(DD.DEFAULT_CFG, name="报告章节自检", service="高通量宽带", orbit="GEO",
           coverage="巴基斯坦", band="Ka", feeder_band="Ka", mode="数字透明",
           ant_type="固面")
sg = DE.suggest_closed_loop(cfg, DA.KG)
for k, v in (sg.get("values") or {}).items():
    if v != "":
        cfg[k] = v
R = DE.design_all(cfg, DA.KG, skip_compare=True)
R["_cov_meta"] = DD.COVERAGE.get("巴基斯坦", {})
R["_orbit_alt_km"] = DD.ORBITS["GEO"]["alt_km"]
R["_service_meta"] = DD.SERVICES.get(cfg.get("service", "高通量宽带"), {})
icd = DA.PG.generate_icd(R)
doc = RG.build_report(R, icd=icd, world_land=DA.world_land(), rasterize=False)
chk("build ok", len(doc) > 150000, "%d chars" % len(doc))
# 目录含新章
chk("目录含覆盖章", "地面 EIRP 覆盖分析（SATSOFT 等效）" in doc)
chk("目录含轨道章", "轨道覆盖仿真（STK 等效）" in doc)
# 方向图节（第 4 章内）
chk("4.4 次级方向图节", "4.4 天线次级方向图" in doc)
chk("4.x 栅瓣核查节", "栅瓣核查" in doc)
chk("方向图 grid SVG", "grid（boresight 不扫描）" in doc)
chk("方向图 cut SVG", "主瓣切面" in doc and "宽角签名切面" in doc)
chk("Hankel 原理导语", "Hankel" in doc)
# 覆盖章（第 11）
chk("11.1 覆盖投影节", "11.1 地面 EIRP 覆盖投影" in doc)
chk("11.2 足迹度量节", "11.2 覆盖足迹度量" in doc)
chk("覆盖图 SVG", "地面 EIRP 覆盖（GEO 定点" in doc)
chk("覆盖等值线色", "#d6452d" in doc or "#e08214" in doc)
chk("覆盖度量表", "足迹直径 (km)" in doc)
chk("覆盖导出说明", "供 SATSOFT/Excel 交叉核对" in doc)
# 轨道章（第 12）
chk("12.1 轨迹节", "12.1 星下点轨迹与瞬时覆盖" in doc)
chk("12.2 快照节", "12.2 指定时刻覆盖快照" in doc)
chk("12.3 可见窗节", "12.3 24h 可见窗与轨道合理性评估" in doc)
chk("轨道要素表", "升交点赤经" in doc and "轨道周期" in doc)
chk("GEO 连续覆盖判定", "连续可见" in doc or "连续覆盖" in doc)
chk("STK .e 导出说明", "STK Ephemeris" in doc)
_ORB = RG._compute_orbit(R)
chk("GEO 周期≈1436min", abs(_ORB["period_min"] - 1436) < 2, "period=%s" % _ORB["period_min"])
# 章节数=14（目录行；第 13 章稳健性分析）
n_toc = doc.count('class="toc-n"')
chk("目录 14 章", n_toc == 14, "toc-n=%d" % n_toc)
# 稳健性章（第 13）
chk("13 章标题", "方案级稳健性分析" in doc)
chk("13.1 星蚀节", "13.1 星蚀（地影）供电分析" in doc)
chk("13.2 位保节", "13.2 位置保持 ΔV 与推进剂寿命" in doc)
chk("13.3 MC 节", "13.3 链路灵敏度蒙特卡洛" in doc)
chk("13.4 XPD 节", "13.4 雨致去极化" in doc)
chk("13.5 可靠性节", "13.5 载荷可靠性汇总" in doc)
chk("13.6 邻星节", "13.6 邻星干扰" in doc)
chk("三R口径图", "svg_rel_bars" in doc or "可靠性三口径对比" in doc)
chk("整改建议表", "逐项整改措施" in doc or "无需整改" in doc or "整改建议" in doc)
chk("GEO 星蚀锚定说明", "最恶劣历元" in doc)
# SVG 计数（新增 3 类图）
n_svg = doc.count("<svg")
chk("SVG 数增加(≥14)", n_svg >= 14, "svg=%d" % n_svg)

# ---- 场景 2：LEO/SSO 相控阵（扫描态 + 栅瓣 + 间歇覆盖）----
print("== 场景2 LEO 相控阵（SSO）==")
cfg2 = dict(DD.DEFAULT_CFG, name="LEO章节自检", service="宽带互联网", orbit="SSO",
            coverage="中国", band="Ka", feeder_band="Ka", mode="数字透明",
            ant_type="相控阵", N_el=256, d_lam=0.7, θ_scan=30)
R2 = DE.design_all(cfg2, DA.KG, skip_compare=True)
R2["_cov_meta"] = DD.COVERAGE.get("中国", {})
R2["_orbit_alt_km"] = DD.ORBITS["SSO"]["alt_km"]
R2["_service_meta"] = DD.SERVICES.get("宽带互联网", {})
doc2 = RG.build_report(R2, world_land=DA.world_land(), rasterize=False)
chk("LEO build ok", len(doc2) > 150000, "%d chars" % len(doc2))
chk("扫描态方向图节", "4.5 扫描态方向图与栅瓣分析" in doc2)
chk("栅瓣表出现", ("解析栅瓣" in doc2) or ("检出" in doc2) or ("栅瓣阶次" in doc2))
chk("d=0.7λ 有栅瓣", "栅瓣" in doc2)
chk("SSO 太阳同步标注", "太阳同步" in doc2)
chk("LEO 间歇覆盖判定", "间歇覆盖" in doc2 or "星座" in doc2)
chk("SSO 周期≈99min", "98." in doc2 or "99." in doc2)
chk("LEO 覆盖章存在", "11.1 地面 EIRP 覆盖投影" in doc2)

# ---- 场景 3：光栅化通道（Edge headless → PNG）----
print("== 场景3 rasterize=True（Word PNG 通道） ==")
doc3 = RG.build_report(R, icd=icd, world_land=DA.world_land(), rasterize=True)
n_png = doc3.count("data:image/png")
n_svg3 = doc3.count("<svg")
chk("光栅化 PNG", n_png >= 13, "png=%d svg_left=%d" % (n_png, n_svg3))
chk("无残留 SVG", n_svg3 == 0, "svg=%d" % n_svg3)

print("\nRESULT: %s  ok=%d fail=%d" % ("PASS" if fail == 0 else "FAIL", ok, fail))
sys.exit(0 if fail == 0 else 1)
