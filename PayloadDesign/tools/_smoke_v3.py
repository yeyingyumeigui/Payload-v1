# -*- coding: utf-8 -*-
"""冒烟测试：国家覆盖库 / 新天线体制 / suggest_params / diagnose_result / HTTP 服务"""
import json
import sys
import time

sys.path.insert(0, r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\tools")

import design_data as DD
import design_engine as DE
import design_app as DA

KG = DA.KG
fails = []


def check(name, cond, msg=""):
    print(("PASS " if cond else "FAIL ") + name + (" | " + msg if msg else ""))
    if not cond:
        fails.append(name)


# ---- 1. 数据库 ----
check("ANT_TYPE_KEYS 5 项", DD.ANT_TYPE_KEYS == ["固面", "相控阵", "伞状", "大容量多波束", "混合多波束"], str(DD.ANT_TYPE_KEYS))
check("COVERAGE_KEYS>=60", len(DD.COVERAGE_KEYS) >= 60, str(len(DD.COVERAGE_KEYS)))
check("巴基斯坦保留", "巴基斯坦" in DD.COVERAGE and DD.COVERAGE["巴基斯坦"].get("el_min_deg", 0) > 40)
check("国家带 country 标记", DD.COVERAGE.get("印度", {}).get("country") is True)
check("货架 VHTS/HYB", any(u[0] == "ANT-VHTS-KA" for u in DD.SHELF_UNITS) and any(u[0] == "ANT-HYB-KA" for u in DD.SHELF_UNITS))

# ---- 2. 国家覆盖 + 大容量多波束：建议值应用后全流程必须闭合 ----
base = dict(DD.DEFAULT_CFG)
cfg = dict(base, name="印度VHTS", service="高通量宽带", orbit="GEO", coverage="印度",
           band="Ka", feeder_band="Ka", mode="数字透明", ant_type="大容量多波束",
           array_subtype="", N_beam="", B_beam="", k_reuse="", n_pol="",
           D_ap="", N_el="", θ_scan="", η_ill="", C_req_ovr="", M_target="",
           platform_pref="自动", amp_type="", P_out="", isl_type="", isl_r_gbps="",
           life_yr="", EIRP_gs="", el_deg="", A_avail="", B_carrier="", GT_term="",
           EIRP_term="", Mode="", cov_r_km="", beam_r_km="")
sg = DE.suggest_params(cfg, KG)
cfg_s = dict(cfg, **{k: v for k, v in sg["auto"].items()})
print("  建议值: N_beam=%s B_beam=%s k=%s D_ap=%s amp=%s" % (
    cfg_s.get("N_beam"), cfg_s.get("B_beam"), cfg_s.get("k_reuse"), cfg_s.get("D_ap"), cfg_s.get("amp_type")))
check("VHTS 建议 B_beam 不超频谱上限",
      cfg_s["N_beam"] * cfg_s["B_beam"] <= 2500 * cfg_s["k_reuse"] + 1,
      "N*B=%s vs cap=%s" % (cfg_s["N_beam"] * cfg_s["B_beam"], 2500 * cfg_s["k_reuse"]))
r = DE.design_all(cfg_s, KG, skip_compare=True)
s = r["res"]["summary"]
print("  印度VHTS(建议值): EIRP=%.1f GT=%.1f M_up=%.2f M_dn=%.2f judge=%s/%s fail=%s" % (
    s["EIRP"], s["GT"], s["M_up"], s["M_dn"], s["judge_pass"], s["judge_total"], s["fail"]))
check("VHTS 建议值方案全闭合", not s["fail"], str(s["fail"]))
check("diagnosis 字段存在", "diagnosis" in r and r["diagnosis"].get("level") in ("ok", "warn", "bad"), str(r.get("diagnosis", {}).get("level")))
check("VHTS diagnosis 非 bad", r["diagnosis"]["level"] != "bad", str([i["id"] for i in r["diagnosis"]["issues"]]))

# ---- 3. 混合多波束（尼日利亚）----
cfg2 = dict(cfg, name="尼日利亚混合", coverage="尼日利亚", ant_type="混合多波束")
sg2 = DE.suggest_params(cfg2, KG)
cfg2s = dict(cfg2, **{k: v for k, v in sg2["auto"].items()})
r2 = DE.design_all(cfg2s, KG, skip_compare=True)
s2 = r2["res"]["summary"]
print("  混合多波束(建议值): N=%s B=%s EIRP=%.1f GT=%.1f judge=%s/%s fail=%s diag=%s" % (
    cfg2s.get("N_beam"), cfg2s.get("B_beam"), s2["EIRP"], s2["GT"],
    s2["judge_pass"], s2["judge_total"], s2["fail"], r2["diagnosis"]["level"]))
check("混合多波束建议值方案可算", s2["judge_total"] >= 15)
if s2["fail"]:
    for it in r2["diagnosis"]["issues"][:5]:
        print("   [%s][%s] %s :: %s" % (it["sev"], it["id"], it["title"], it["detail"][:150]))

# ---- 4. suggest_params ----
sg = DE.suggest_params(cfg, KG)
check("suggest 返回结构", set(sg.keys()) == {"values", "notes", "auto"} and len(sg["values"]) >= 15, str(len(sg["values"])))
print("  suggest(印度VHTS): N_beam=%s B_beam=%s D_ap=%s amp=%s Mode=%s" % (
    sg["values"].get("N_beam"), sg["values"].get("B_beam"), sg["values"].get("D_ap"),
    sg["values"].get("amp_type"), sg["values"].get("Mode")))
sg2 = DE.suggest_params(dict(cfg, ant_type="相控阵", array_subtype="数字模拟混合"), KG)
check("相控阵建议含 N_el", isinstance(sg2["values"].get("N_el"), (int, float)) and sg2["values"]["N_el"] >= 64, str(sg2["values"].get("N_el")))

# 空白 cfg 不炸
sg3 = DE.suggest_params({}, KG)
check("空 cfg suggest 不炸", "values" in sg3)

# ---- 5. 诊断器：故意造功率墙（GEO 小平台 + 大相控阵）----
cfg_bad = dict(cfg, name="功率墙测试", ant_type="相控阵", array_subtype="直射阵",
               N_el=4000, D_ap="", amp_type="SSPA")
r3 = DE.design_all(cfg_bad, KG, skip_compare=True)
d3 = r3["diagnosis"]
print("  功率墙: level=%s issues=%d" % (d3["level"], len(d3["issues"])))
for it in d3["issues"][:6]:
    print("   [%s][%s] %s" % (it["sev"], it["id"], it["title"]))
check("功率墙被诊断为 bad", d3["level"] == "bad" and any(i["id"] == "c-17" for i in d3["issues"]))

# ---- 6. HTTP 服务 ----
port = DA.start_http_server("127.0.0.1", 0)
import urllib.request


def get(path):
    with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=15) as f:
        return json.loads(f.read().decode("utf-8"))


def post(path, obj):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path),
                                 data=json.dumps(obj).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as f:
        return json.loads(f.read().decode("utf-8"))


t0 = time.time()
meta = get("/api/meta")
check("HTTP /api/meta", meta.get("coverage_keys") and len(meta["coverage_keys"]) >= 60, "%.2fs" % (time.time() - t0))
t0 = time.time()
dr = post("/api/design", {"cfg": cfg, "with_compare": False})
check("HTTP /api/design", dr.get("ok") is True, "%.2fs" % (time.time() - t0))
t0 = time.time()
sr = post("/api/suggest", {"cfg": cfg})
check("HTTP /api/suggest", sr.get("ok") is True and "values" in sr.get("result", {}), "%.2fs" % (time.time() - t0))
# 首页 HTML
with urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=10) as f:
    html = f.read().decode("utf-8")
check("HTTP / 首页含新前端", "apiCall" in html and "diagMask" in html and "btnSuggest" in html and "covSelectHTML" in html)

# NaN 消毒检查：diagnosis JSON 可序列化（已经过 _clean）
check("design 结果 JSON 无 NaN", "NaN" not in json.dumps(dr, ensure_ascii=False)[:200000])

print()
if fails:
    print("SMOKE FAIL: %d 项 -> %s" % (len(fails), fails))
    sys.exit(1)
print("SMOKE ALL PASS")
