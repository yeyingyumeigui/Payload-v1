# -*- coding: utf-8 -*-
"""design_engine 冒烟测试：8 个场景预设全流程跑通 + 关键指标检查。"""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from design_data import SCENARIOS, DEFAULT_CFG
from design_engine import design_all

KG = r"D:\ZWL\文生载荷Workbuddy\output\通信有效载荷知识图谱_2026-09-20.json"

def main():
    with open(KG, encoding="utf-8") as f:
        kg = json.load(f)
    n_ok = 0
    lines = []
    for key, sc in SCENARIOS.items():
        cfg = dict(DEFAULT_CFG)
        cfg.update(sc["cfg"])
        cfg["name"] = key
        try:
            r = design_all(cfg, kg, skip_compare=True)
            s = r["res"]["summary"]
            t = r["totals"]
            fail = s.get("fail", [])
            lines.append(f"[{key}] {sc['label']}")
            lines.append(f"  EIRP={s['EIRP']:.2f}dBW (req {r['params']['EIRP_req']:.1f}) "
                         f"G/T={s['GT']:.2f} (req {r['params']['GT_req']:.1f}) "
                         f"M_up={s['M_up']:.2f} M_dn={s['M_dn']:.2f} "
                         f"C_sys={s.get('C_sys')}Gbps 判据 {s['judge_pass']}/{s['judge_total']} fail={fail}")
            lines.append(f"  质量={t['m_pay']}kg 功耗={t['p_pay']}W 货架H={t['H_scheme']} 定制={t['n_custom']} "
                         f"单机{t['n_rows']}种/{t['n_items']}件 平台={r['platform'][1]['cn'] if r['platform'] else '—'} "
                         f"运载={r['launcher'][1]['cn'] if r['launcher'] else '—'} 评分={r['score']['total']}")
            lines.append(f"  天线推荐={r['ant_rec'][1]['id']} 自研={r['is_custom_ant']} 框图节点={len(r['diagram']['nodes'])} 信息流=星地{len(r['flows']['sg'])}/星间{len(r['flows']['si'])}/星内{len(r['flows']['sn'])}")
            n_ok += 1
        except Exception as e:
            import traceback
            lines.append(f"[{key}] FAILED: {e}")
            lines.append(traceback.format_exc())
    lines.append(f"\n{n_ok}/{len(SCENARIOS)} 场景跑通")
    out = "\n".join(lines)
    with open(r"D:\ZWL\文生载荷Workbuddy\tools\_design_smoke_out.txt", "w", encoding="utf-8") as f:
        f.write(out)
    print(out)

if __name__ == "__main__":
    main()
