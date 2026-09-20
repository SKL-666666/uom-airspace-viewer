"""最小 PMTiles v3 读取器 —— 用于本地校验瓦片内容与判定逻辑。

只做读取，不做写入。参照 PMTiles v3 规范与 pmtiles.js 的实现。
"""
import gzip
import math
import struct
import zlib

PNG_SIG = b"\x89PNG\r\n\x1a\n"

TILE_TYPES = {0: "unknown", 1: "mvt", 2: "png", 3: "jpeg", 4: "webp", 5: "avif"}
COMPRESSIONS = {0: "unknown", 1: "none", 2: "gzip", 3: "brotli", 4: "zstd"}


# tzValues[z] = 4^0 + 4^1 + ... + 4^(z-1)，即该层级之前所有瓦片数
TZ = [0]
for _z in range(1, 27):
    TZ.append(TZ[-1] + (1 << (2 * (_z - 1))))


def _rotate(n, xy, rx, ry):
    if ry == 0:
        if rx == 1:
            xy[0] = n - 1 - xy[0]
            xy[1] = n - 1 - xy[1]
        xy[0], xy[1] = xy[1], xy[0]


def zxy_to_tileid(z, x, y):
    acc = TZ[z]
    n = 1 << z
    d = 0
    xy = [x, y]
    s = n // 2
    while s > 0:
        rx = 1 if (xy[0] & s) > 0 else 0
        ry = 1 if (xy[1] & s) > 0 else 0
        d += s * s * ((3 * rx) ^ ry)
        _rotate(s, xy, rx, ry)
        s //= 2
    return acc + d


def _read_varint(buf, pos):
    result = 0
    shift = 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return result, pos


def deserialize_index(buf):
    pos = 0
    num, pos = _read_varint(buf, pos)
    entries = []
    last_id = 0
    for _ in range(num):
        v, pos = _read_varint(buf, pos)
        last_id += v
        entries.append({"tile_id": last_id, "offset": 0, "length": 0, "run_length": 1})
    for i in range(num):
        entries[i]["run_length"], pos = _read_varint(buf, pos)
    for i in range(num):
        entries[i]["length"], pos = _read_varint(buf, pos)
    for i in range(num):
        v, pos = _read_varint(buf, pos)
        if v == 0 and i > 0:
            entries[i]["offset"] = entries[i - 1]["offset"] + entries[i - 1]["length"]
        else:
            entries[i]["offset"] = v - 1
    return entries


class PMTiles:
    def __init__(self, path):
        self.f = open(path, "rb")
        h = self.f.read(127)
        assert h[:7] == b"PMTiles", "不是 PMTiles 文件"
        self.version = h[7]
        (self.root_off, self.root_len, self.meta_off, self.meta_len,
         self.leaf_off, self.leaf_len, self.data_off, self.data_len) = struct.unpack(
            "<8Q", h[8:72])
        (self.addressed, self.entries, self.contents) = struct.unpack("<3Q", h[72:96])
        self.clustered = h[96]
        self.internal_comp = h[97]
        self.tile_comp = h[98]
        self.tile_type = h[99]
        self.min_zoom, self.max_zoom = h[100], h[101]
        self.min_lon, self.min_lat, self.max_lon, self.max_lat = (
            struct.unpack("<4i", h[102:118])[i] / 1e7 for i in range(4))
        self.center_zoom = h[118]
        self.center_lon = struct.unpack("<i", h[119:123])[0] / 1e7
        self.center_lat = struct.unpack("<i", h[123:127])[0] / 1e7
        raw = self._read_at(self.root_off, self.root_len)
        self.root = deserialize_index(self._decompress(raw, self.internal_comp))
        # 叶子目录解析结果缓存。叶子目录解压后是上百 KB 的 varint 数据，
        # 每次 get_tile 都重新读盘+gunzip+解析会累积成几十毫秒
        # （服务端合成一张 512px 瓦片要查 4 次 => 实测 47ms 全花在这里）。
        self._leaf_cache = {}

    @staticmethod
    def _decompress(data, comp):
        if comp == 2:
            return gzip.decompress(data)
        if comp == 1:
            return data
        try:
            return gzip.decompress(data)
        except Exception:
            return data

    def _read_at(self, off, length):
        self.f.seek(off)
        return self.f.read(length)

    def _search(self, entries, tile_id, base_off, depth):
        """在目录里找 tile_id。run_length==0 表示这是叶子目录指针，需递归。

        用二分查找而非线性扫描：叶子目录有 4096 项，而服务端每合成一张
        512px 瓦片要查 4 次，线性扫描会累积成上百毫秒（实测 163ms）。
        """
        if not entries:
            return None
        lo, hi, m = 0, len(entries) - 1, -1
        while lo <= hi:
            mid = (lo + hi) // 2
            if entries[mid]["tile_id"] <= tile_id:
                m = mid
                lo = mid + 1
            else:
                hi = mid - 1
        if m == -1:
            return None
        e = entries[m]
        if e["run_length"] == 0:  # 目录指针
            if depth >= 4:
                return None
            ck = (base_off + e["offset"], e["length"])
            sub = self._leaf_cache.get(ck)
            if sub is None:
                raw = self._read_at(ck[0], ck[1])
                sub = deserialize_index(self._decompress(raw, self.internal_comp))
                self._leaf_cache[ck] = sub
            return self._search(sub, tile_id, self.leaf_off, depth + 1)
        # 数据项：确认落在 run_length 覆盖范围内
        if e["tile_id"] <= tile_id < e["tile_id"] + e["run_length"]:
            return e
        return None

    def _find(self, tile_id):
        return self._search(self.root, tile_id, self.leaf_off, 0)

    def get_tile(self, z, x, y):
        tid = zxy_to_tileid(z, x, y)
        e = self._find(tid)
        if e is None:
            return None
        data = self._read_at(self.data_off + e["offset"], e["length"])
        return self._decompress(data, self.tile_comp)


def lonlat_to_tile(lon, lat, z):
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    lat_r = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n)
    return x, y


def lonlat_to_tile_pixel(lon, lat, z):
    """经纬度 -> (瓦片x, 瓦片y, 瓦片内像素x, 瓦片内像素y)"""
    n = 2 ** z
    xf = (lon + 180.0) / 360.0 * n
    yf = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    x, y = int(xf), int(yf)
    px = min(255, max(0, int((xf - x) * 256)))
    py = min(255, max(0, int((yf - y) * 256)))
    return x, y, px, py


def png_pixel(data, px, py):
    """解 PNG 取单像素 RGBA（仅支持非隔行、8bit、调色板/灰度/RGBA）。"""
    pos = 8
    w = h = None
    bitdepth = colortype = None
    idat = b""
    plte = None
    trns = None
    while pos < len(data):
        ln = struct.unpack(">I", data[pos:pos + 4])[0]
        typ = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            w, h, bitdepth, colortype, comp, filt, interlace = struct.unpack(">IIBBBBB", chunk)
            if interlace:
                raise ValueError("隔行 PNG 不支持")
        elif typ == b"PLTE":
            plte = chunk
        elif typ == b"tRNS":
            trns = chunk
        elif typ == b"IDAT":
            idat += chunk
        elif typ == b"IEND":
            break
        pos += 12 + ln

    raw = zlib.decompress(idat)
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[colortype]
    bpp = max(1, channels * bitdepth // 8)
    stride = (w * channels * bitdepth + 7) // 8

    # 反滤波，只需目标行之前的所有行
    prev = bytearray(stride)
    for row in range(py + 1):
        ft = raw[row * (stride + 1)]
        line = bytearray(raw[row * (stride + 1) + 1: row * (stride + 1) + 1 + stride])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if ft == 1:
                line[i] = (line[i] + a) & 0xFF
            elif ft == 2:
                line[i] = (line[i] + b) & 0xFF
            elif ft == 3:
                line[i] = (line[i] + (a + b) // 2) & 0xFF
            elif ft == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        prev = line
        if row == py:
            target = line

    if colortype == 3:
        idx = target[px]
        r, g, b = plte[idx * 3], plte[idx * 3 + 1], plte[idx * 3 + 2]
        a = trns[idx] if trns and idx < len(trns) else 255
        return r, g, b, a
    if colortype == 6:
        o = px * 4
        return target[o], target[o + 1], target[o + 2], target[o + 3]
    if colortype == 2:
        o = px * 3
        return target[o], target[o + 1], target[o + 2], 255
    if colortype == 0:
        v = target[px]
        return v, v, v, 255
    if colortype == 4:
        o = px * 2
        return target[o], target[o], target[o], target[o + 1]
    raise ValueError(f"未支持的颜色类型 {colortype}")


def sample_tile(pm, lon, lat, z=13):
    """取指定经纬度所在瓦片的像素（256x256 内的相对位置）。"""
    n = 2 ** z
    xf = (lon + 180.0) / 360.0 * n
    yf = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    x, y = int(xf), int(yf)
    px = min(255, max(0, int((xf - x) * 256)))
    py = min(255, max(0, int((yf - y) * 256)))
    data = pm.get_tile(z, x, y)
    if data is None:
        return None, (z, x, y, px, py)
    return png_pixel(data, px, py), (z, x, y, px, py)


if __name__ == "__main__":
    import sys
    pm = PMTiles("data/uom-shifei.pmtiles")
    print(f"版本 v{pm.version} | 类型 {TILE_TYPES.get(pm.tile_type)} | "
          f"内部压缩 {COMPRESSIONS.get(pm.internal_comp)} | 瓦片压缩 {COMPRESSIONS.get(pm.tile_comp)}")
    print(f"zoom {pm.min_zoom}~{pm.max_zoom} | 目录项 {len(pm.root)} | 瓦片数 {pm.addressed}")
    print(f"范围: {pm.min_lon:.3f},{pm.min_lat:.3f} ~ {pm.max_lon:.3f},{pm.max_lat:.3f}")
    print()
    tests = [
        ("北京天安门", 116.3908, 39.9028),
        ("内蒙草原(疑无适飞)", 111.0, 42.0),
        ("上海", 121.4737, 31.2304),
        ("深圳", 114.0579, 22.5431),
        ("新疆戈壁", 85.0, 41.0),
    ]
    for name, lon, lat in tests:
        px, info = sample_tile(pm, lon, lat)
        z, x, y, ix, iy = info
        if px is None:
            print(f"{name:22s} 无瓦片   (z{z}/{x}/{y} 内点 {ix},{iy})")
        else:
            r, g, b, a = px
            print(f"{name:22s} RGBA=({r:3d},{g:3d},{b:3d},{a:3d})  z{z}/{x}/{y} 内点 {ix},{iy}")
