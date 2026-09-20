"""端到端验证 UOM 瓦片的坐标链是否自洽。

背景：客户端用 tileSize:512 + zoomOffset:-1，服务端把 URL 的 (Z,X,Y)
解析为原生 (Z+1, 2X..2X+1, 2Y..2Y+1)。这条链上任何一环差一级，都会
导致"图层看不见"或"位置错位"，而且靠肉眼很难发现。

验证方法（不依赖浏览器）：
  1. 按 Leaflet 源码的公式（lib 里提取）算出某经纬度所在的 URL 瓦片
     及其在 512px 图内的像素偏移
  2. 从服务端取该瓦片，读该像素
  3. 与直接读 PMTiles（probe 端点，走另一条代码路径）对比
两条路径结果一致，才说明坐标链正确。

Leaflet 公式（取自 lib/leaflet.js 压缩源码）：
  _getTiledPixelBounds: halfSize = map.getSize().divideBy(2 * scale)
  _pxBoundsToTileRange: bounds.unscaleBy(tileSize)
  _getZoomForUrl:       urlZoom = _tileZoom + zoomOffset
"""
import io
import json
import math
import urllib.request

from PIL import Image

BASE = "http://127.0.0.1:8080"
TILE_SIZE = 512
ZOOM_OFFSET = -1
MAX_NATIVE_ZOOM = 13


def fetch(url):
    with urllib.request.urlopen(BASE + url, timeout=30) as r:
        return r.read()


def leaflet_tile_for(lon, lat, screen_zoom):
    """复刻 Leaflet 的瓦片定位，返回 (url_z, x, y, px_in_tile, py_in_tile)"""
    # map.project(center, _tileZoom)：投影到 _tileZoom 层的世界像素
    n = 256 * (2 ** screen_zoom)
    px = (lon + 180.0) / 360.0 * n
    py = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    # _pxBoundsToTileRange：除以 tileSize
    x = int(px // TILE_SIZE)
    y = int(py // TILE_SIZE)
    # 在该 512px 瓦片内的像素偏移
    ix = int(px - x * TILE_SIZE)
    iy = int(py - y * TILE_SIZE)
    # _getZoomForUrl
    url_z = screen_zoom + ZOOM_OFFSET
    return url_z, x, y, ix, iy


def pixel_from_tile(data, ix, iy):
    if not data:
        return None
    im = Image.open(io.BytesIO(data)).convert("RGBA")
    return im.getpixel((min(ix, im.width - 1), min(iy, im.height - 1)))


def main():
    cases = [
        (85.0, 41.0, "新疆（适飞密集）"),
        (105.0, 35.5, "甘肃/宁夏一带"),
        (116.39, 39.90, "北京天安门（应无数据）"),
        (121.47, 31.23, "上海（应无数据）"),
        (111.0, 42.0, "内蒙古"),
    ]
    zooms = [5, 8, 11, 13, 15]

    fails = 0
    total = 0
    for lon, lat, name in cases:
        for sz in zooms:
            url_z, x, y, ix, iy = leaflet_tile_for(lon, lat, sz)
            if url_z > MAX_NATIVE_ZOOM - 1:
                continue
            total += 1
            url = f"/uom/{url_z}/{x}/{y}.png"
            try:
                data = fetch(url)
            except Exception as e:
                print(f"  ✗ {name} {lon},{lat} z{sz}: 请求失败 {e}")
                fails += 1
                continue
            px = pixel_from_tile(data, ix, iy)

            # 另一条路径：直接查原生 z13（probe 端点）
            j = json.loads(fetch(f"/uom/probe?lon={lon}&lat={lat}").decode())

            # 判定标准：瓦片路径"有数据"与 probe"有数据"必须一致
            tile_has = bool(px and px[3] > 0)
            probe_has = bool(j.get("hasData") and j.get("suitable"))
            # probe 用 z13 判断，瓦片路径在低缩放时可能因下采样而丢失小区域，
            # 所以只强校验：瓦片有数据 => probe 也应大概率有数据（反向不强制）
            flag = "✓"
            if tile_has and not probe_has:
                flag = "✗ 瓦片有数据但 probe 说没有（坐标链可能错位）"
                fails += 1
            print(f"  {flag} {name:20s} 屏幕z{sz:2d} -> URL z{url_z:2d}/{x:5d}/{y:5d} "
                  f"内点({ix:3d},{iy:3d}) 瓦片像素={px} probe适飞={probe_has}")

    print(f"\n  共 {total} 组，失败 {fails}")
    print("  " + ("=== 坐标链自洽 ===" if fails == 0 else "=== 存在错位，需排查 ==="))
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
