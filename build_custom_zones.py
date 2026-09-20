"""生成自定义管制区 GeoJSON。

数据来源：民航华北空管局飞行前资料公告（NOTAM）C0903/26，禁飞区名称 ZB(SR)801。
圆心/半径依据微信公众号「优凯飞行」发布的解读文章转述：
    以北纬 39°54′10″、东经 116°23′27″（天安门）为中心，半径 300 千米。
    生效 2026-09-20 00:00 UTC，标注 PERM（永久），全天 24 小时，地面至无限高。

注意：文章原文自称"以上距离为依据圆心半径的推算值，最终边界以官方发布为准"，
本文件是依据该转述生成的近似圆，不等于官方边界。仅供标注参考。

输出的 custom_zones.geojson 与 UOM 官方数据物理隔离，永不混入。
"""
import json
import math

# 天安门 39°54'10"N 116°23'27"E
CENTER_LAT = 39 + 54 / 60 + 10 / 3600
CENTER_LON = 116 + 23 / 60 + 27 / 3600
RADIUS_KM = 300.0
EARTH_R = 6371.0088

METADATA = {
    "source": "用户自定义 · 非官方数据",
    "basis": "NOTAM C0903/26 (民航华北空管局) — 转述自微信公众号「优凯飞行」2026-09-20 文章",
    "zone_name": "ZB(SR)801",
    "effective_from": "2026-09-20T00:00:00Z",
    "validity": "PERM（原文标注永久，全天24小时）",
    "vertical_limit": "地（水）面至无限高",
    "accuracy_note": "依据转述的圆心+半径生成的近似圆，未取得官方边界矢量，最终以官方发布为准",
}


def circle_polygon(lat, lon, radius_km, steps=360):
    """按大圆航线生成圆形多边形，比平面近似更准。"""
    pts = []
    for i in range(steps + 1):
        brg = math.radians(i * (360 / steps))
        p1, l1 = math.radians(lat), math.radians(lon)
        dr = radius_km / EARTH_R
        p2 = math.asin(
            math.sin(p1) * math.cos(dr) + math.cos(p1) * math.sin(dr) * math.cos(brg)
        )
        l2 = l1 + math.atan2(
            math.sin(brg) * math.sin(dr) * math.cos(p1),
            math.cos(dr) - math.sin(p1) * math.sin(p2),
        )
        pts.append([round(math.degrees(l2), 6), round(math.degrees(p2), 6)])
    return [pts]


def main():
    ring = circle_polygon(CENTER_LAT, CENTER_LON, RADIUS_KM)
    feat = {
        "type": "Feature",
        "properties": {
            "name": "ZB(SR)801 首都禁飞区（近似）",
            "type": "custom_restricted",
            "source": METADATA["source"],
            "basis": METADATA["basis"],
            "effective_from": METADATA["effective_from"],
            "validity": METADATA["validity"],
            "vertical_limit": METADATA["vertical_limit"],
            "center": [round(CENTER_LON, 6), round(CENTER_LAT, 6)],
            "radius_km": RADIUS_KM,
            "accuracy_note": METADATA["accuracy_note"],
        },
        "geometry": {"type": "Polygon", "coordinates": ring},
    }
    fc = {
        "type": "FeatureCollection",
        "metadata": METADATA,
        "features": [feat],
    }
    out = "data/custom_zones.geojson"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False, indent=1)

    lons = [p[0] for p in ring[0]]
    lats = [p[1] for p in ring[0]]
    print(f"已生成 {out}")
    print(f"  圆心: {CENTER_LAT:.6f}N, {CENTER_LON:.6f}E  半径: {RADIUS_KM} km")
    print(f"  顶点: {len(ring[0])}  外接矩形: {min(lons):.3f}~{max(lons):.3f}E, {min(lats):.3f}~{max(lats):.3f}N")
    print(f"  面积(约): {math.pi * RADIUS_KM ** 2:,.0f} km2")


if __name__ == "__main__":
    main()
