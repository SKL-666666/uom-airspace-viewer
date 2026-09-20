"""镜像前端判定逻辑，用已知点做端到端验证。

前端 index.html 的 queryAt() 做的事：
  1. 经纬度 → z13 瓦片 + 像素，读 alpha 判 UOM 适飞
  2. 点在多边形内 判大疆禁飞/限飞
  3. 点在多边形内 判 ZB(SR)801
这里用完全相同的算法复算一遍，确认数据和逻辑自洽。
"""
import json
import math

from pmtiles_tool import PMTiles, png_pixel

NATIVE_MAX_Z = 13


def lonlat_to_tile_pixel(lon, lat, z):
    n = 2 ** z
    xf = (lon + 180.0) / 360.0 * n
    yf = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    x, y = int(xf), int(yf)
    px = min(255, max(0, int((xf - x) * 256)))
    py = min(255, max(0, int((yf - y) * 256)))
    return x, y, px, py


def point_in_ring(pt, ring):
    x, y = pt
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def point_in_polygon(pt, poly):
    if not point_in_ring(pt, poly[0]):
        return False
    for hole in poly[1:]:
        if point_in_ring(pt, hole):
            return False
    return True


def point_in_feature(pt, geom):
    if not geom:
        return False
    if geom["type"] == "Polygon":
        return point_in_polygon(pt, geom["coordinates"])
    if geom["type"] == "MultiPolygon":
        return any(point_in_polygon(pt, p) for p in geom["coordinates"])
    return False


def main():
    pm = PMTiles("data/uom-shifei.pmtiles")
    with open("data/dji_flysafe.geojson", encoding="utf-8") as f:
        dji = json.load(f)
    with open("data/custom_zones.geojson", encoding="utf-8") as f:
        zones = json.load(f)

    # 只保留中国及周边的要素，与前端一致
    def in_cn(ft):
        geom = ft["geometry"]
        rings = geom["coordinates"] if geom["type"] == "Polygon" else [
            r for p in geom["coordinates"] for r in p]
        lons = [c[0] for r in rings for c in r]
        lats = [c[1] for r in rings for c in r]
        return min(lats) < 55 and max(lats) > 15 and min(lons) < 136 and max(lons) > 72

    cn_dji = [ft for ft in dji["features"] if in_cn(ft)]
    print(f"大疆要素: 全部 {len(dji['features'])} -> 中国周边 {len(cn_dji)}")
    print()

    zone_geom = zones["features"][0]["geometry"]

    tests = [
        ("北京天安门", 116.3908, 39.9028),
        ("天津市区", 117.1900, 39.1256),
        ("石家庄", 114.5149, 38.0428),
        ("济南(应圈外)", 117.1201, 36.6512),
        ("深圳", 114.0579, 22.5431),
        ("乌鲁木齐", 87.6168, 43.8256),
        ("大兴机场", 116.4109, 39.5098),
        ("上海浦东机场", 121.8083, 31.1434),
    ]

    print(f"{'地点':<18}{'UOM适飞':<10}{'ZB801':<9}{'大疆命中'}")
    print("-" * 72)
    for name, lon, lat in tests:
        # UOM
        x, y, px, py = lonlat_to_tile_pixel(lon, lat, NATIVE_MAX_Z)
        data = pm.get_tile(NATIVE_MAX_Z, x, y)
        if data is None:
            uom = "否(无瓦片)"
        else:
            r, g, b, a = png_pixel(data, px, py)
            uom = "是" if a == 255 else "否"

        in_zone = point_in_feature([lon, lat], zone_geom)

        hits = [ft["properties"] for ft in cn_dji
                if point_in_feature([lon, lat], ft["geometry"])]
        hit_str = ", ".join(f"{h.get('type')}:{h.get('name') or '-'}" for h in hits[:2])
        if len(hits) > 2:
            hit_str += f" (+{len(hits)-2})"
        if not hit_str:
            hit_str = "-"

        print(f"{name:<18}{uom:<12}{'在范围内' if in_zone else '否':<11}{hit_str}")


if __name__ == "__main__":
    main()
