# -*- coding: utf-8 -*-
"""设计器 HTML 数据层：汇总 design_data + infoflow_data + 知识图谱链路链 → 内嵌 JSON。

JS 侧 DATA 同时服务两个引擎：
  · ENGINE_JS（infoflow 引擎移植）: UNITS/BANDS/MODCOD/LINK_META/CHAINS
  · DESIGN_JS（design 引擎移植）  : ORBITS/COVERAGE/SERVICES/MODES/ANT_TYPES/
                                    ARRAY_SUBTYPES/SHELF/UNIT_PRINCIPLES/PLATFORMS/
                                    LAUNCHERS/SCENARIOS/DEFAULT_CFG/BAND_FREQ/BAND_RAIN
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from infoflow_data import UNITS, BANDS, MODCOD, PARAMS, LINK_META
import design_data as dd

SRC = r"D:\ZWL\文生载荷Workbuddy\output\通信有效载荷知识图谱_2026-09-20.json"


def build_data():
    with open(SRC, "r", encoding="utf-8") as f:
        kg = json.load(f)
    chains = {}
    for o in kg["ontologies"]:
        if o.get("chain"):
            chains[o["id"]] = dict(name=o.get("name", o["id"]),
                                   desc=o.get("description", ""), chain=o["chain"])
    shelf = [dict(zip(("id", "cn", "cat", "bands", "level", "mass", "power", "specs", "note"), u))
             for u in dd.SHELF_UNITS]
    data = dict(
        # ---- infoflow 引擎依赖 ----
        UNITS=UNITS, BANDS=BANDS, MODCOD=MODCOD, PARAMS=PARAMS,
        LINK_META=LINK_META, CHAINS=chains,
        # ---- 设计层数据 ----
        ORBITS=dd.ORBITS, COVERAGE=dd.COVERAGE, SERVICES=dd.SERVICES,
        MODES=dd.MODES, ANT_TYPES=dd.ANT_TYPES, ARRAY_SUBTYPES=dd.ARRAY_SUBTYPES,
        SHELF=shelf, UNIT_PRINCIPLES=dd.UNIT_PRINCIPLES,
        PLATFORMS=dd.PLATFORMS, LAUNCHERS=dd.LAUNCHERS,
        SCENARIOS=dd.SCENARIOS, DEFAULT_CFG=dd.DEFAULT_CFG,
        BAND_FREQ={k: list(v) for k, v in dd.BAND_FREQ.items()},
        BAND_RAIN={k: list(v) for k, v in dd.BAND_RAIN.items()},
        MODE_HPA=dd.MODE_HPA,
        SHELF_LEVELS={str(k): v for k, v in dd.SHELF_LEVELS.items()},
        ORBIT_KEYS=dd.ORBIT_KEYS, COVERAGE_KEYS=dd.COVERAGE_KEYS,
        SERVICE_KEYS=dd.SERVICE_KEYS, MODE_KEYS=dd.MODE_KEYS,
        ANT_TYPE_KEYS=dd.ANT_TYPE_KEYS, ARRAY_SUBTYPE_KEYS=dd.ARRAY_SUBTYPE_KEYS,
        BAND_KEYS=dd.BAND_KEYS, SHELF_CATS=dd.SHELF_CATS,
        kg_meta=dict(version=kg.get("version"), name=kg.get("name")),
    )
    return data, kg


if __name__ == "__main__":
    d, k = build_data()
    s = json.dumps(d, ensure_ascii=False)
    print("DATA keys:", len(d), "json size: %.1f KB" % (len(s.encode("utf-8")) / 1024))
