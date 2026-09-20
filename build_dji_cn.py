"""生成「仅中国境内」的大疆数据，并派生低缩放概览版。

两步：
  A. 只保留中国境内（含港澳台）：CN + HK + TW + MO
     原先的 bbox 过滤是无效的 —— 中国外接矩形（73~135.5E）本身就覆盖
     印度、日本、韩国，任何非零缓冲都会把 4112 条全放回来。只能用
     country 字段。注意必须带上 HK/TW/MO，否则会漏掉港澳台。
     4112 -> 1509（降 63%）
  C. 低缩放只画大区域：按「在 z5 下屏幕尺寸 >= 3px」筛选，
     全国视图下用这份，开销再降一个数量级。
     被剔除的都是在屏幕上不到 3 像素、肉眼看不见的，不影响观感。

输出：
  data/dji_cn_full.geojson   境内全量（同时用于绘制与点击判定）
  data/dji_cn_low.geojson    境内概览（z<=5 绘制用）
"""
import json
import os

SRC = "data/dji_full.geojson"
KEEP_COUNTRY = {"CN", "HK", "TW", "MO"}
LOW_ZOOM = 5          # 概览版服务的最大缩放
MIN_PX = 3.0          # 该缩放下要求的最小屏幕像素


def collect(coords, out):
    if isinstance(coords[0][0], (int, float)):
        out.append(coords)
    else:
        for c in coords:
            collect(c, out)


def bbox_of(geom):
    xs, ys = [], []
    rings = []
    collect(geom["coordinates"], rings)
    for r in rings:
        for p in r:
            xs.append(p[0])
            ys.append(p[1])
    return min(xs), min(ys), max(xs), max(ys)


def center_of(geom):
    x0, y0, x1, y1 = bbox_of(geom)
    return (round((x0 + x1) / 2, 4), round((y0 + y1) / 2, 4))


def round_coords(coords, nd):
    if isinstance(coords[0], (int, float)):
        return [round(coords[0], nd), round(coords[1], nd)]
    return [round_coords(c, nd) for c in coords]


def main():
    src = json.load(open(SRC, encoding="utf-8"))
    feats = src["features"]
    print(f"源数据 {len(feats)} 个要素")

    # --- A. 只保留中国境内 ---
    kept = []
    seen = set()
    dropped_dup = 0
    for f in feats:
        p = f["properties"]
        if p.get("country") not in KEEP_COUNTRY:
            continue
        key = (p.get("country"), p.get("name"), center_of(f["geometry"]))
        if key in seen:                 # 去重
            dropped_dup += 1
            continue
        seen.add(key)
        kept.append({
            "type": "Feature",
            "properties": p,
            "geometry": {
                "type": f["geometry"]["type"],
                "coordinates": round_coords(f["geometry"]["coordinates"], 5),
            },
        })

    from collections import Counter
    print(f"\nA. 仅中国境内（含港澳台）: {len(kept)} 个  "
          f"(原 {len(feats)}，降 {(1 - len(kept) / len(feats)) * 100:.0f}%)")
    print("   明细:", dict(Counter(f["properties"]["country"] for f in kept)))
    print("   类型:", dict(Counter(f["properties"]["type"] for f in kept)))
    if dropped_dup:
        print(f"   去重 {dropped_dup} 条")

    with open("data/dji_cn_full.geojson", "w", encoding="utf-8") as fp:
        json.dump({
            "type": "FeatureCollection",
            "metadata": {
                "derived_from": "dji_full.geojson",
                "filter": "country in CN/HK/TW/MO",
                "source": "DJI flysafe",
            },
            "features": kept,
        }, fp, ensure_ascii=False, separators=(",", ":"))

    # --- C. 低缩放概览版 ---
    deg_per_px = 360.0 / (256 * (2 ** LOW_ZOOM))
    limit = MIN_PX * deg_per_px
    low = []
    for f in kept:
        try:
            x0, y0, x1, y1 = bbox_of(f["geometry"])
        except Exception:
            continue
        if max(x1 - x0, y1 - y0) >= limit:
            low.append(f)

    print(f"\nC. 概览版（z<={LOW_ZOOM} 用，阈值 {limit:.4f}°）: {len(low)} 个 "
          f"({len(low) / len(kept) * 100:.1f}% of 境内)")
    print("   类型:", dict(Counter(f["properties"]["type"] for f in low)))
    with open("data/dji_cn_low.geojson", "w", encoding="utf-8") as fp:
        json.dump({
            "type": "FeatureCollection",
            "metadata": {
                "derived_from": "dji_cn_full.geojson",
                "purpose": f"z<={LOW_ZOOM} 使用，仅屏幕尺寸>={MIN_PX}px 的要素",
                "source": "DJI flysafe",
            },
            "features": low,
        }, fp, ensure_ascii=False, separators=(",", ":"))

    print("\n文件:")
    for fn in ["data/dji_cn_full.geojson", "data/dji_cn_low.geojson"]:
        print(f"  {fn}: {os.path.getsize(fn) / 1024:.0f} KB")


if __name__ == "__main__":
    main()
