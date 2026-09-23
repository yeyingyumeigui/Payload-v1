# -*- coding: utf-8 -*-
"""把 Natural Earth 110m 陆地轮廓简化为轻量 JSON（world_land.json），供覆盖区示意图使用。

合规说明：
- 仅使用海岸线陆地轮廓（ne_110m_land），不绘制任何政治边界/国界；
- 输出为卫星覆盖示意图底图，非测绘意义地图；
- 反经线（±180°）跨接多边形拆段，避免横穿地图的直线。
"""
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "_land_raw.geojson")
OUT = os.path.join(HERE, "world_land.json")

EPS = 0.35          # 简化容差（度）
MIN_AREA = 1.0      # 最小保留面积（度²，过滤小岛）
LAT_CLIP = 85.5     # 纬度截断（墨卡托式投影极区无意义）
Q = 4.0             # 量化步长（度）：坐标存 round(v*Q) 整数


def radial_simplify(pts, eps_deg):
    """径向距离简化（保留形状特征，去掉冗余点）。"""
    if len(pts) < 3:
        return pts
    keep = [pts[0]]
    for p in pts[1:-1]:
        if abs(p[0] - keep[-1][0]) >= eps_deg or abs(p[1] - keep[-1][1]) >= eps_deg:
            keep.append(p)
    keep.append(pts[-1])
    return keep


def ring_area(pts):
    a = 0.0
    for i in range(len(pts) - 1):
        a += pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1]
    return abs(a) / 2.0


def split_antimeridian(pts):
    """跨 ±180° 的多边形按经度跳变拆段（每段独立绘制）。"""
    segs, cur = [], [pts[0]]
    for p in pts[1:]:
        if abs(p[0] - cur[-1][0]) > 180:
            segs.append(cur)
            cur = [p]
        else:
            cur.append(p)
    if len(cur) > 2:
        segs.append(cur)
    return segs


def clip_lat(pts, lat_max):
    out = []
    for lon, lat in pts:
        lat = max(-lat_max, min(lat_max, lat))
        out.append((lon, lat))
    return out


def main():
    with open(SRC, "r", encoding="utf-8") as f:
        gj = json.load(f)

    polys = []
    n_src = 0
    for feat in gj.get("features", []):
        geom = feat.get("geometry") or {}
        gtype = geom.get("type")
        coords = geom.get("coordinates") or []
        rings = []
        if gtype == "Polygon":
            rings = [coords[0]]
        elif gtype == "MultiPolygon":
            rings = [poly[0] for poly in coords]
        for ring in rings:
            n_src += 1
            pts = clip_lat([(float(p[0]), float(p[1])) for p in ring], LAT_CLIP)
            if ring_area(pts) < MIN_AREA:
                continue
            pts = radial_simplify(pts, EPS)
            if len(pts) < 4:
                continue
            for seg in split_antimeridian(pts):
                if len(seg) < 3:
                    continue
                flat = []
                for lon, lat in seg:
                    flat.append(int(round(lon * Q)))
                    flat.append(int(round(lat * Q)))
                polys.append(flat)

    # 按点数排序（大多边形优先），限制总量
    polys.sort(key=len, reverse=True)
    total = sum(len(p) for p in polys)
    data = {"q": Q, "n": len(polys), "polys": polys}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
    size = os.path.getsize(OUT)
    print("rings src=%d kept=%d coords_total=%d size=%.1fKB -> %s"
          % (n_src, len(polys), total, size / 1024, OUT))
    assert size < 400 * 1024, "world_land.json 过大（%d KB），提高 EPS 或 MIN_AREA" % (size // 1024)


if __name__ == "__main__":
    main()
