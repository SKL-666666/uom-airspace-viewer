"""根据浏览器上报的 center/zoom/视口尺寸，算出该视野内「应该」有多少适飞内容。

用来区分两种情况：
  - 视野内本就没有适飞数据 → 看不到蓝色属正常，问题在地图位置
  - 视野内适飞内容很多却看不到 → 才是渲染问题

每个瓦片用 PIL 解码一次后整体统计，避免逐像素重复解析 PNG。
"""
import io
import math

import numpy as np
from PIL import Image

from pmtiles_tool import PMTiles

pm = PMTiles("data/uom-shifei.pmtiles")


def ll_to_world(lon, lat, z):
    n = 256 * (2 ** z)
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    return x, y


def analyze(center_lat, center_lon, zoom, w, h, label):
    print(f"\n=== {label} ===")
    print(f"  中心 {center_lat}N {center_lon}E  zoom {zoom}  视口 {w}x{h}")

    cx, cy = ll_to_world(center_lon, center_lat, zoom)
    tx0 = int((cx - w / 2) // 256)
    ty0 = int((cy - h / 2) // 256)
    tx1 = int((cx + w / 2) // 256)
    ty1 = int((cy + h / 2) // 256)

    total = 0
    with_data = 0
    total_px = 0
    suitable = 0

    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            total += 1
            data = pm.get_tile(zoom, tx, ty)
            if not data:
                continue
            with_data += 1
            a = np.array(Image.open(io.BytesIO(data)).convert("RGBA"))
            alpha = a[:, :, 3]
            total_px += alpha.size
            suitable += int((alpha == 255).sum())

    print(f"  视野瓦片 {total} 块，其中有数据 {with_data} 块")
    if total_px:
        pct = suitable / total_px * 100
        print(f"  适飞像素占比 {pct:.2f}%")
        if pct < 0.5:
            print("  → 几乎无适飞空域，看不到蓝色属正常")
        elif pct < 5:
            print("  → 适飞较少，只能看到零星蓝斑")
        else:
            print("  → 适飞明显，应能清楚看到蓝色")
    else:
        print("  → 视野内完全无数据")


analyze(34.62, 129.262, 5, 1911, 1053, "上报① v6 首次打开（经度 129E）")
analyze(37.506, 115.164, 7, 1911, 1053, "上报② v6 之后（河北）")
analyze(35.5, 105.0, 5, 1911, 1053, "对照：代码里的默认视野")
analyze(41.0, 85.0, 7, 1911, 1053, "对照：新疆（适飞密集）")
analyze(38.05, 114.5, 8, 1911, 1053, "对照：河北省会")
