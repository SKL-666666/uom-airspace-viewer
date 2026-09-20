"""生成大疆数据的分级版本，供不同缩放级别使用。

原因：全国概览（z4~z5）时 94% 的多边形在屏幕上不到 3 像素，肉眼看不见，
但 Leaflet 的 canvas 每次重绘仍要为它们各付一次 fill() + stroke()。
4112 个要素 = 8224 次 canvas 调用，实测每次重绘约 160ms，这就是卡顿来源。

做法：按「在目标缩放下屏幕尺寸是否够看」筛出子集，坐标适度取整。
低缩放用小子集，高缩放用全量，保持"看得见的都在"。
"""
import json
import math

SRC = "data/dji_flysafe.geojson"

# 分级的缩放上限 -> 该级别下要求的最小屏幕像素
TIERS = [
    ("data/dji_low.geojson", 5, 3.0),   # z<=5 使用：屏幕尺寸 >=3px 的要素
    ("data/dji_mid.geojson", 7, 3.0),   # z6~7 使用
]


def walk_coords(coords, fn):
    if isinstance(coords[0], (int, float)):
        fn(coords)
    else:
        for c in coords:
            walk_coords(c, fn)


def bbox_of(geom):
    xs, ys = [], []
    walk_coords(geom["coordinates"], lambda p: (xs.append(p[0]), ys.append(p[1])))
    return min(xs), min(ys), max(xs), max(ys)


def deg_per_px(zoom):
    """1 像素对应多少度（经度方向，Web Mercator 赤道近似；高纬偏保守）"""
    return 360.0 / (256 * (2 ** zoom))


def round_coords(coords, nd):
    if isinstance(coords[0], (int, float)):
        return [round(coords[0], nd), round(coords[1], nd)]
    return [round_coords(c, nd) for c in coords]


def main():
    src = json.load(open(SRC, encoding="utf-8"))
    feats = src["features"]
    print(f"源数据 {len(feats)} 个要素")

    for out_path, max_zoom, min_px in TIERS:
        limit_deg = min_px * deg_per_px(max_zoom)
        kept = []
        for f in feats:
            try:
                x0, y0, x1, y1 = bbox_of(f["geometry"])
            except Exception:
                continue
            if max(x1 - x0, y1 - y0) >= limit_deg:
                kept.append({
                    "type": "Feature",
                    "properties": f["properties"],
                    "geometry": {
                        "type": f["geometry"]["type"],
                        "coordinates": round_coords(f["geometry"]["coordinates"], 4),
                    },
                })
        out = {
            "type": "FeatureCollection",
            "metadata": {
                "derived_from": "dji_flysafe.geojson",
                "purpose": f"z<={max_zoom} 使用，仅保留屏幕尺寸>={min_px}px 的要素",
                "source": "DJI flysafe",
            },
            "features": kept,
        }
        with open(out_path, "w", encoding="utf-8") as fp:
            json.dump(out, fp, ensure_ascii=False, separators=(",", ":"))
        import os
        size = os.path.getsize(out_path) / 1024
        print(f"  {out_path}: {len(kept)} 个要素 "
              f"({len(kept)/len(feats)*100:.1f}%)  阈值 {limit_deg:.4f}度  {size:.0f} KB")

    # 全量文件的精简版：坐标取整，减小解析体积
    small = {
        "type": "FeatureCollection",
        "metadata": src.get("metadata", {}),
        "features": [{
            "type": "Feature",
            "properties": f["properties"],
            "geometry": {
                "type": f["geometry"]["type"],
                "coordinates": round_coords(f["geometry"]["coordinates"], 5),
            },
        } for f in feats],
    }
    with open("data/dji_full.geojson", "w", encoding="utf-8") as fp:
        json.dump(small, fp, ensure_ascii=False, separators=(",", ":"))
    import os
    print(f"  data/dji_full.geojson: {len(feats)} 个要素  "
          f"{os.path.getsize('data/dji_full.geojson')/1024:.0f} KB")


if __name__ == "__main__":
    main()
