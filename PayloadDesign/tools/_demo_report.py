# -*- coding: utf-8 -*-
"""演示：闭环建议值 → design_all → 完整 Word 报告（光栅化）+ 抽出关键插图存 PNG 供目视终检。"""
import base64
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_app as DA          # noqa: E402
import design_data as DD         # noqa: E402
import design_engine as DE       # noqa: E402
import protocol_gen as PG        # noqa: E402
import report_gen as RG          # noqa: E402

OUT = r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\output"

cfg = dict(DD.DEFAULT_CFG, name="巴基斯坦GEO高通量宽带", service="高通量宽带", orbit="GEO",
           coverage="巴基斯坦", band="Ka", feeder_band="Ka", mode="数字透明", ant_type="固面")

print("== 1. 一键建议值闭环 ==")
sg = DE.suggest_closed_loop(cfg, DA.KG)
cl = sg.get("closed") or {}
print("   grade=%s iters=%s feasible=%s pass_hard=%s pass_soft=%s"
      % (cl.get("grade"), cl.get("iters"), cl.get("feasible"),
         cl.get("pass_hard"), cl.get("pass_soft")))
print("   conclusion:", cl.get("conclusion"))
for a in (cl.get("adjustments") or []):
    print("   adjust:", a)
for k, v in (sg.get("values") or {}).items():
    if v != "":
        cfg[k] = v

R = DE.design_all(cfg, DA.KG, skip_compare=True)
R["_cov_meta"] = DD.COVERAGE.get("巴基斯坦", {})
R["_orbit_alt_km"] = DD.ORBITS["GEO"]["alt_km"]
ev = R.get("eval") or {}
print("== 2. 方案评价 == grade=%s feasible=%s hard=%s soft=%s score=%s"
      % (ev.get("grade"), ev.get("feasible"), ev.get("pass_hard"),
         ev.get("pass_soft"), ev.get("score_total")))
for c in ev.get("criteria") or []:
    print("   %s %-4s %-18s %s | %s vs %s"
          % ("✓" if c["ok"] else "✗", c["id"], c["name"],
             "硬" if c["kind"] == "hard" else "软", c["got"], c["need"]))

print("== 3. 生成完整 Word 报告（SVG→PNG 光栅化） ==")
icd = PG.generate_icd(R)
doc = RG.build_report(R, icd=icd, world_land=DA.world_land(),
                      shelf_count=len(DA.SHELF_UNITS))
fname = "演示_巴基斯坦GEO高通量_载荷方案报告.doc"
fpath = os.path.join(OUT, fname)
with io.open(fpath, "w", encoding="utf-8") as fh:
    fh.write("\ufeff" + doc)
print("   ->", fpath, "%.2f MB" % (os.path.getsize(fpath) / 1e6))
print("   PNG=%d  残留<svg>=%d" % (doc.count("data:image/png"), doc.count("<svg")))

print("== 4. 抽关键插图存独立 PNG（目视终检） ==")
# 逐节重建 SVG 以拿到未光栅化原文，便于单独存图
imgs = {
    "globe3d_三维覆盖": RG.svg_globe_3d(R, DA.world_land()),
    "framework_功能框架": RG.svg_payload_framework(R),
    "linkchain_链路原理": RG.svg_link_chain(R),
    "freqplan_频率规划": RG.svg_freq_plan(R),
    "radar_评分雷达": RG.svg_eval_radar(ev, R.get("score")),
    "infoflow_信息流框架": RG.svg_info_flow(R.get("flows"), R.get("cfg")),
}
D_m = R["res"]["antenna"].get("D_m") or 2.5
f_ghz = (R["res"].get("downlink") or {}).get("f_ghz") or 20.0
beam = RG.GB.beam_performance(D_m, f_ghz, prefer="grasp", tag="demo")
imgs["beam1d_GRASP一维方向图"] = RG.svg_pattern_1d(beam)
b2, _p2 = RG.svg_pattern_2d(beam, D_m, f_ghz, n=51)
imgs["beam2d_GRASP二维方向图"] = b2

saved = []
for nm, svg in imgs.items():
    uri = RG.svg_to_png_b64(svg)
    if not uri:
        print("   [MISS] %s（Edge 光栅化失败）" % nm)
        continue
    raw = base64.b64decode(uri.split(",", 1)[1])
    p = os.path.join(OUT, "_chk_%s.png" % nm)
    with open(p, "wb") as fh:
        fh.write(raw)
    saved.append(p)
    print("   [OK] %s  %s  %.0f KB  sig=%s"
          % (nm, os.path.basename(p), len(raw) / 1024,
             raw[:8] == b"\x89PNG\r\n\x1a\n"))
print("beam source=%s G0=%s th3=%s" % (beam.get("source"), beam.get("peak_gain_dbi"),
                                       beam.get("beamwidth_3db_deg")))
print("SAVED=%d" % len(saved))
