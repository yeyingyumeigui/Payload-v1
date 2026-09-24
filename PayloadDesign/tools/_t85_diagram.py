# -*- coding: utf-8 -*-
"""#85 验证：block_diagram 细化（馈电网络节点 BFN/FEED + T_sys 按族取值 + 边完整性）。"""
import sys
import json
import io
sys.path.insert(0, r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\tools")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import design_engine as DE

KG = json.load(open(r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\output\通信有效载荷知识图谱_2026-09-20.json", encoding="utf-8"))
NPASS, NFAIL = 0, 0


def ck(cond, msg):
    global NPASS, NFAIL
    if cond:
        NPASS += 1
        print("  PASS %s" % msg)
    else:
        NFAIL += 1
        print("  FAIL %s" % msg)


def check(name, cfg, expect_feed, feed_kind):
    print("[%s]" % name)
    R = DE.design_all(cfg, KG, skip_compare=True)
    D = R["diagram"]
    ids = {nd["id"] for nd in D["nodes"]}
    # 边端点完整性
    bad = [(e["f"], e["t"]) for e in D["edges"] if e["f"] not in ids or e["t"] not in ids]
    ck(not bad, "边端点全部存在（bad=%s）" % bad)
    # 馈电节点
    ck(expect_feed in ids, "%s 节点存在（天线体制=%s）" % (expect_feed, cfg.get("ant_type")))
    nd = next((n for n in D["nodes"] if n["id"] == expect_feed), None)
    if nd:
        print("    %s: %s ×%s | %s" % (nd["id"], nd["cn"].replace("\n", "/"), nd["qty"], nd["note"]))
        ck(nd["kind"] == feed_kind, "节点 kind=%s" % nd["kind"])
    # 上行链路 ANT→feed→CIRC
    up = [(e["f"], e["t"]) for e in D["edges"] if e["kind"] == "rf_up"]
    ck(("ANT", expect_feed) in up, "上行 ANT→%s" % expect_feed)
    ck((expect_feed, "CIRC") in up, "上行 %s→CIRC" % expect_feed)
    # 下行链路 OMUX→feed→ANT
    dn = [(e["f"], e["t"]) for e in D["edges"] if e["kind"] == "rf_dn"]
    ck(("OMUX", expect_feed) in dn, "下行 OMUX→%s" % expect_feed)
    ck((expect_feed, "ANT") in dn, "下行 %s→ANT" % expect_feed)
    # T_sys 标注非零且随体制变化
    ln = next((e for e in D["edges"] if e["f"] == "LNA"), None)
    ck(ln and "T_sys=" in (ln.get("label") or ""), "LNA→DCON 含 T_sys 标注：%s" % (ln or {}).get("label"))
    tsys = float((ln.get("label") or "T_sys=0K").split("=")[1].replace("K", "") or 0)
    ck(tsys > 0, "T_sys > 0（=%sK）" % tsys)
    return tsys


t1 = check("相控阵（期望 BFN）", dict(
    service="高通量宽带", orbit="GEO", geo_lon=110.5, coverage="巴基斯坦",
    band="Ka", ant_type="相控阵", array_subtype="数字模拟混合", mode="数字透明",
    N_el=1024, cov_r_km=600, el_deg=15, A_avail=99.5, M_target=3, life_yr=15),
    "BFN", "rf")
t2 = check("固面（期望 FEED）", dict(
    service="高通量宽带", orbit="GEO", geo_lon=110.5, coverage="巴基斯坦",
    band="Ka", ant_type="固面", D_ap=2.5, mode="数字透明",
    cov_r_km=600, el_deg=15, A_avail=99.5, M_target=3, life_yr=15),
    "FEED", "rf")
ck(abs(t1 - t2) > 1, "T_sys 随天线族变化（相控阵 %.0fK vs 固面 %.0fK，相控阵含 T/R 噪声应更高）" % (t1, t2))

# 三体制均验证节点/边完整性
for m in ("透明", "数字透明", "再生"):
    R = DE.design_all(dict(service="高通量宽带", orbit="GEO", geo_lon=110.5, coverage="巴基斯坦",
                           band="Ka", ant_type="固面", D_ap=2.5, mode=m,
                           cov_r_km=600, el_deg=15, A_avail=99.5, M_target=3, life_yr=15),
                      KG, skip_compare=True)
    D = R["diagram"]
    ids = {nd["id"] for nd in D["nodes"]}
    bad = [(e["f"], e["t"]) for e in D["edges"] if e["f"] not in ids or e["t"] not in ids]
    ck(not bad, "体制=%s 边完整（节点%d 边%d）" % (m, len(D["nodes"]), len(D["edges"])))

print("\nRESULT: %s (%d pass / %d fail)" % ("PASS" if NFAIL == 0 else "FAIL", NPASS, NFAIL))
