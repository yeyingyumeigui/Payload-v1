# -*- coding: utf-8 -*-
"""无窗口测试 design_app.Api：meta() + design()（首个场景 + 对比），验证 JSON 可序列化。"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_app

OUT = r"D:\ZWL\文生载荷Workbuddy\tools\_app_test_out.txt"

def main():
    lines = []
    api = design_app.Api()
    m = api.meta()
    s = json.dumps(m, ensure_ascii=False)
    lines.append("meta ok, json %.1f KB, keys=%s" % (len(s.encode('utf-8'))/1024, sorted(m.keys())))

    k0 = list(m["scenarios"].keys())[0]
    sc = m["scenarios"][k0]
    cfg = dict(m["default_cfg"])
    cfg.update(sc["cfg"])
    cfg["name"] = sc["label"]
    cfg["isl_on"] = bool(sc["cfg"].get("isl_on"))
    r = api.design(cfg, with_compare=True)
    lines.append("design ok=%s" % r.get("ok"))
    if not r.get("ok"):
        lines.append(r.get("error", ""))
        lines.append(r.get("trace", ""))
    else:
        js = json.dumps(r, ensure_ascii=False)
        lines.append("result json %.1f KB" % (len(js.encode('utf-8'))/1024))
        res = r["result"]
        summ = res["res"]["summary"]
        lines.append("EIRP=%.2f GT=%.2f M_up=%.2f M_dn=%.2f judge=%s/%s fail=%s" % (
            summ["EIRP"], summ["GT"], summ["M_up"], summ["M_dn"],
            summ["judge_pass"], summ["judge_total"], summ["fail"]))
        lines.append("compare rows=%d labels=%s" % (
            len(res["compare"]), [c.get("label") for c in res["compare"]]))
        lines.append("diagram nodes=%d edges=%d" % (len(res["diagram"]["nodes"]), len(res["diagram"]["edges"])))
        lines.append("flows sg=%d si=%d sn=%d" % (len(res["flows"]["sg"]), len(res["flows"]["si"]), len(res["flows"]["sn"])))
        lines.append("equipment rows=%d items=%d" % (res["totals"]["n_rows"], res["totals"]["n_items"]))
        lines.append("principles=%s" % [p["key"] for p in res["principles"]])
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

if __name__ == "__main__":
    main()
