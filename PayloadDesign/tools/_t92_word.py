# -*- coding: utf-8 -*-
"""#92 Word 集成验证：N_sat≥2 GEO 场景 → 报告第10章含"多星协同覆盖单一服务区"。"""
import sys, io, re, traceback
TOOLS = r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\tools"
sys.path.insert(0, TOOLS)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

NPASS = NFAIL = 0
def ck(cond, msg):
    global NPASS, NFAIL
    if cond: NPASS += 1; print("  PASS %s" % msg)
    else:    NFAIL += 1; print("  FAIL %s" % msg)

# 导入自检（确保 report_gen 无语法错误）
try:
    import report_gen as RG
    ck(hasattr(RG, "_constellation_chapter"), "report_gen 导入 OK，含 _constellation_chapter")
except Exception:
    traceback.print_exc(); ck(False, "report_gen 导入失败"); sys.exit(1)

import design_data as DD, design_engine as DE, design_app as DA, protocol_gen as PG

cfg = dict(DD.DEFAULT_CFG, name="多星协同覆盖单区", service="高通量宽带", orbit="GEO",
           coverage="省域", band="Ka", feeder_band="Ka", mode="数字透明",
           ant_type="固面", N_sat=2)
sg = DE.suggest_closed_loop(cfg, DA.KG)
for k, v in (sg.get("values") or {}).items():
    if v != "" and k != "N_sat":
        cfg[k] = v
cfg["N_sat"] = 2
R = DE.design_all(cfg, DA.KG, skip_compare=True)
R["_cov_meta"] = DD.COVERAGE.get("省域", {})
R["_orbit_alt_km"] = DD.ORBITS["GEO"]["alt_km"]
icd = PG.generate_icd(R)

ck(bool(R.get("regional_coverage")), "R.regional_coverage 存在")

print("[生成] 第10章 _constellation_chapter ...")
try:
    chap = RG._constellation_chapter(R)
    ck(len(chap) > 200, "第10章生成（%d 字符）" % len(chap))
    ck("多星协同覆盖单一服务区" in chap, "含'多星协同覆盖单一服务区'标题")
    ck("GEO 空间分区" in chap or "时间接力" in chap, "含协同体制说明")
    ck("覆盖率" in chap, "含覆盖率指标")
    ck("<table" in chap, "含表格")
except Exception:
    traceback.print_exc(); ck(False, "第10章生成异常")

print("[生成] 完整 build_report(rasterize=False) ...")
try:
    doc = RG.build_report(R, icd=icd, world_land=DA.world_land(), rasterize=False)
    ck(len(doc) > 5000, "完整报告生成（%d 字符）" % len(doc))
    ck("多星协同覆盖单一服务区" in doc, "完整报告含多星协同章节")
    ck("在轨同类卫星对标" in doc, "完整报告含在轨对标章节")
    ck("星座组网、多覆盖区与在轨对标" in doc, "第10章标题已更新")
except Exception:
    traceback.print_exc(); ck(False, "build_report 异常")

print("\nRESULT: %s (%d pass / %d fail)" % ("PASS" if NFAIL == 0 else "FAIL", NPASS, NFAIL))
