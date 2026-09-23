# -*- coding: utf-8 -*-
"""v4 冒烟：GRASP 桥 / beam 端点 / worldmap / export_html / 新工作模式 / HTTP 新路由"""
import json
import sys
import time
import urllib.request

sys.path.insert(0, r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\tools")

import design_data as DD
import design_engine as DE
import design_app as DA
import grasp_bridge as GB

KG = DA.KG
fails = []


def check(name, cond, msg=""):
    print(("PASS " if cond else "FAIL ") + name + (" | " + msg if msg else ""))
    if not cond:
        fails.append(name)


# ---- 1. 新工作模式 ----
check("MODE_CAP 含常用模式", all(k in DE.MODE_CAP for k in
      ["全球覆盖", "单波束", "区域赋形", "多波束", "点波束", "波束跳变", "相控扫描", "在轨重构"]),
      str(sorted(DE.MODE_CAP)))
# 五维选型在新模式下正常
cfg = dict(DD.DEFAULT_CFG, name="新模式测试", service="高通量宽带", orbit="GEO",
           coverage="印度", band="Ka", feeder_band="Ka", mode="数字透明",
           ant_type="大容量多波束", Mode="区域赋形", N_beam=233, B_beam=42,
           k_reuse=4, n_pol=2, D_ap=3.5, amp_type="MPA")
r = DE.design_all(cfg, KG, skip_compare=True)
s = r["res"]["summary"]
check("区域赋形模式全流程可算", s["judge_total"] >= 15 and not s["fail"], str(s["fail"]))
# suggest 对新模式输出
sg = DE.suggest_params(dict(DD.DEFAULT_CFG, orbit="GEO", coverage="印度", band="Ka",
                            ant_type="相控阵", service="高通量宽带"), KG)
check("suggest Mode 为新常用模式之一",
      sg["values"]["Mode"] in DE.MODE_CAP, str(sg["values"]["Mode"]))

# ---- 2. GRASP 桥（解析路径必过；grasp 路径按安装情况）----
a = GB.beam_performance(2.4, 14.0, prefer="analytic")
check("解析方向图", a["ok"] and 48 < a["peak_gain_dbi"] < 51 and 0.3 < a["beamwidth_3db_deg"] < 1.5,
      "G0=%.2f th3=%.3f" % (a["peak_gain_dbi"], a["beamwidth_3db_deg"]))
solver, info = GB.find_grasp()
if solver:
    t0 = time.time()
    g = GB.beam_performance(2.4, 14.0, prefer="grasp")
    dt = time.time() - t0
    check("GRASP 实测", g["source"] == "grasp" and g["ok"],
          "src=%s G0=%.2f th3=%.3f %.1fs" % (g.get("source"), g.get("peak_gain_dbi", 0),
                                             g.get("beamwidth_3db_deg", 0), dt))
    check("GRASP θ3dB 物理合理（0.3~1.5°@2.4m/14GHz）",
          0.3 < g.get("beamwidth_3db_deg", 0) < 1.5, str(g.get("beamwidth_3db_deg")))
else:
    print("SKIP GRASP 实测（未找到求解器）")

# ---- 3. world_land ----
wl = DA.world_land()
check("world_land 加载", wl.get("n", 0) > 50, "polys=%d" % wl.get("n", 0))

# ---- 4. export_html ----
api = DA._api_singleton
exp = api.export_html({"name": "测试方案", "kpi": "EIRP 60dBW", "sections": [
    {"title": "方案总览", "html": "<table><tr><th>项</th><th>值</th></tr><tr><td>EIRP</td><td>60</td></tr></table>"},
    {"title": "链路预算", "html": "<p>余量 3.2dB</p>"}]})
check("export_html ok", exp["ok"] and "WordDocument" in exp["html"] and "测试方案" in exp["html"],
      "len=%d" % len(exp.get("html", "")))

# ---- 5. beam Api 方法（抽稀）----
b = api.beam({"D_ap": 2.5, "freq_ghz": 20.0, "prefer": "analytic"})
check("Api.beam 抽稀", b["ok"] and len(b["result"]["theta"]) <= 245,
      "n=%d" % len(b.get("result", {}).get("theta", [])))

# ---- 6. HTTP 新路由 ----
port = DA.start_http_server("127.0.0.1", 0)


def get(p):
    with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, p), timeout=20) as f:
        return json.loads(f.read().decode())


def post(p, o):
    rq = urllib.request.Request("http://127.0.0.1:%d%s" % (port, p),
                                data=json.dumps(o).encode(),
                                headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(rq, timeout=300) as f:
        return json.loads(f.read().decode())


wm = get("/api/worldmap")
check("HTTP /api/worldmap", wm["ok"] and wm["land"]["n"] > 50)
bb = post("/api/beam", {"D_ap": 2.4, "freq_ghz": 14.0, "prefer": "analytic"})
check("HTTP /api/beam", bb["ok"] and bb["result"]["source"] == "analytic")
ee = post("/api/export", {"name": "HTTP导出", "sections": [{"title": "t", "html": "<p>x</p>"}]})
check("HTTP /api/export", ee["ok"] and "HTTP导出" in ee["html"])
# GRASP 经 HTTP（耗时 ~1-3s）
if solver:
    bg = post("/api/beam", {"D_ap": 3.5, "freq_ghz": 20.0, "prefer": "grasp"})
    check("HTTP /api/beam GRASP", bg["ok"] and bg["result"]["source"] == "grasp",
          str(bg["result"].get("source")) + " G0=%s" % bg["result"].get("peak_gain_dbi"))

print()
if fails:
    print("SMOKE V4 FAIL: %d -> %s" % (len(fails), fails))
    sys.exit(1)
print("SMOKE V4 ALL PASS")
