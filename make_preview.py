"""导出指定层级的全国预览图，用于肉眼校验 PMTiles 内容。"""
import io
import math
import sys

from PIL import Image

from pmtiles_tool import PMTiles

LON0, LAT0, LON1, LAT1 = 72.0, 55.0, 136.0, 17.0  # 中国大致范围


def ll2t(lon, lat, z):
    n = 1 << z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return x, y


def mosaic(pm, z, scale_to=1400):
    x0, y0 = ll2t(LON0, LAT0, z)
    x1, y1 = ll2t(LON1, LAT1, z)
    W, H = (x1 - x0 + 1) * 256, (y1 - y0 + 1) * 256
    canvas = Image.new("RGBA", (W, H), (235, 235, 235, 255))
    # 适飞区是半透明叠色，铺一层白底便于观察
    got = 0
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            data = pm.get_tile(z, x, y)
            if not data:
                continue
            try:
                img = Image.open(io.BytesIO(data)).convert("RGBA")
            except Exception:
                continue
            canvas.paste(img, ((x - x0) * 256, (y - y0) * 256), img)
            got += 1
    out = canvas.convert("RGB")
    if W > scale_to:
        out = out.resize((scale_to, int(H * scale_to / W)), Image.LANCZOS)
    fn = f"preview_z{z}.png"
    out.save(fn)
    print(f"z{z}: 命中 {got} 个瓦片 -> {fn} ({out.size[0]}x{out.size[1]})")
    return fn


if __name__ == "__main__":
    pm = PMTiles("data/uom-shifei.pmtiles")
    for z in [int(a) for a in sys.argv[1:]] or [5, 8, 10]:
        mosaic(pm, z)
