# -*- coding: utf-8 -*-
"""#59 验证：Api.pattern / coverage / orbit / export_file 四接口"""
import os, sys, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_app as DA  # noqa: E402

api = DA.Api()
OUT = DA._out_dir()
ok_n = 0

# 1) pattern：相控阵扫描 30°（d=0.7λ 应有栅瓣）+ .grd 导出
r = api.pattern(dict(antenna_type="phased_array", freq_ghz=20.0, n_el=256,
                     d_lam=0.7, scan_theta=30.0, cut_span=15.0,
                     export_grd=True, tag="_t59_array"))
assert r["ok"], r.get("error") + str(r.get("trace", ""))[:300]
res = r["result"]
assert res["has_grating"], "d=0.7λ scan30 应有栅瓣"
assert len(res["grating_in_cut"]) == 0, "栅瓣不应在 ±15° cut 内"
assert os.path.exists(res["grd_file"]["path"]), ".grd 未落盘"
assert "_gain_arr" not in json.dumps(r, default=str), "闭包泄漏进 JSON"
print("pattern OK: G0=%.1fdBi th3=%.3f° GL=%d grd=%s" % (
    res["peak_gain_dbi"], res["beamwidth_3db_deg"], len(res["grating_lobes"]),
    res["grd_file"]["name"]))
ok_n += 1

# 2) pattern：反射面 boresight（无栅瓣）
r2 = api.pattern(dict(antenna_type="reflector", freq_ghz=20.0, D=2.5,
                      scan_theta=0.0, peak_gain_dbi=52.5))
assert r2["ok"], r2.get("error")
assert not r2["result"]["has_grating"]
assert 0.3 < r2["result"]["beamwidth_3db_deg"] < 0.6, r2["result"]["beamwidth_3db_deg"]
print("pattern reflector OK: th3=%.3f° FSL=%.1f" % (
    r2["result"]["beamwidth_3db_deg"], r2["result"]["first_sidelobe_dbr"]))
ok_n += 1

# 3) coverage：GEO 60E → 巴基斯坦(30.5N,69.5E)，point_at_target + CSV 导出
r3 = api.coverage(dict(antenna_type="reflector", freq_ghz=20.0, D=2.5,
                       peak_eirp_dbw=54.0, h_km=35786.0, sat_lat=0.0, sat_lon=60.0,
                       target_lat=30.5, target_lon=69.5, point_at_target=True,
                       el_min_deg=10.0, export_csv=True, tag="_t59_cov"))
assert r3["ok"], r3.get("error") + str(r3.get("trace", ""))[:300]
bc = r3["beam_center"]
assert abs(bc["lat"] - 30.5) < 0.6 and abs(bc["lon"] - 69.5) < 0.6, \
    "波束中心未落在目标: %s" % bc
assert r3["exact"], "未走精确方向图查询"
assert r3["contours"] and any(len(v) > 0 for v in r3["contours"].values()), "无等值线"
assert all(os.path.exists(f["path"]) for f in r3["csv_files"])
print("coverage OK: beam_center=(%.2f,%.2f) scan=%.2f° peak=%.1fdBW contours=%s" % (
    bc["lat"], bc["lon"], r3["scan"]["theta_deg"], r3["peak_ground"]["eirp_dbw"],
    {k: len(v) for k, v in r3["contours"].items()}))
ok_n += 1

# 4) orbit：GEO 评估 + 快照 + .e 导出
r4 = api.orbit(dict(orbit_key="GEO", h_km=35786.0, incl_deg=0.05, geo_lon=60.0,
                    targets=[dict(name="巴基斯坦", lat=30.5, lon=69.5)],
                    el_min_deg=20.0, t_offset_min=90.0, export_stk=True, tag="_t59_orbit"))
assert r4["ok"], r4.get("error") + str(r4.get("trace", ""))[:300]
assert abs(r4["period_min"] - 1436.1) < 2.0, r4["period_min"]
assert r4["assess"]["ok"], r4["assess"]["verdict"]
# 星下点经度应≈geo_lon=60E（raan 反解验证）
assert abs(r4["snapshot"]["sub_lon"] - 60.0) < 1.5, r4["snapshot"]["sub_lon"]
snap = r4["snapshot"]
assert snap["t_utc"].endswith("UTC"), snap["t_utc"]
# el_min=20° → σ=acos(R·cos20/(R+h))−20 ≈ 61.8°
assert abs(snap["sigma_deg"] - 61.8) < 2, snap["sigma_deg"]
assert snap["targets"][0]["visible"], snap["targets"][0]
assert abs(snap["sub_lon"] - 60.0) < 1.0, snap["sub_lon"]
assert os.path.exists(r4["stk_file"]["path"])
assert len(r4["track"]) > 50
print("orbit GEO OK: T=%.1fmin σ=%.2f° snap=%s tgt_el=%.1f° .e=%s(%d pts)" % (
    r4["period_min"], snap["sigma_deg"], snap["t_utc"],
    snap["targets"][0]["el_deg"], r4["stk_file"]["name"], r4["stk_file"]["points"]))
ok_n += 1

# 5) orbit：LEO SSO 倾角自动 + 间歇覆盖判定
r5 = api.orbit(dict(orbit_key="SSO", h_km=700.0, incl_deg=None,
                    targets=[dict(name="喀什", lat=39.5, lon=76.0)],
                    el_min_deg=15.0))
assert r5["ok"], r5.get("error")
assert 97.5 < r5["incl_deg"] < 99.5, "SSO 倾角应≈98°: %s" % r5["incl_deg"]
assert abs(r5["period_min"] - 98.8) < 2, r5["period_min"]
print("orbit SSO OK: incl=%.2f° T=%.1fmin cov=%.0f%% n_win=%d verdict=%.40s" % (
    r5["incl_deg"], r5["period_min"],
    r5["assess"]["results"][0]["cov_pct"], r5["assess"]["results"][0]["n_win"],
    r5["assess"]["verdict"]))
ok_n += 1

# 6) export_file：三种 kind
rf = api.export_file(dict(kind="grd", antenna_type="reflector", freq_ghz=20.0,
                          D=2.5, tag="_t59_x"))
assert rf["ok"] and os.path.exists(rf["file_path"]), rf
re_ = api.export_file(dict(kind="e", orbit_key="LEO", h_km=550.0, incl_deg=53.0,
                           tag="_t59_x"))
assert re_["ok"] and os.path.exists(re_["stk_file"]["path"]), re_
rc = api.export_file(dict(kind="cov_csv", antenna_type="reflector", freq_ghz=20.0,
                          D=1.2, h_km=550.0, peak_eirp_dbw=40.0, tag="_t59_x"))
assert rc["ok"] and all(os.path.exists(f["path"]) for f in rc["csv_files"]), rc
print("export_file OK: .grd / .e / cov_csv 三通道落盘")
ok_n += 1

# 清理测试产物
for fn in os.listdir(OUT):
    if fn.startswith("_t59_"):
        os.remove(os.path.join(OUT, fn))
print("cleanup done")

print("RESULT: %d/6 PASS" % ok_n)
