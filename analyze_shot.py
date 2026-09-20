"""分析用户截图，在不看图的情况下推断页面状态。

思路：页面各元素的颜色是我自己定义的，因此可以根据颜色占比与空间分布
反推：地图区域是否有内容、顶栏徽章是什么状态、有没有错误横幅。
"""
import sys

import numpy as np
from PIL import Image

img = sys.argv[1]
a = np.array(Image.open(img).convert("RGB"))
H, W, _ = a.shape
print(f"截图尺寸 {W}x{H}\n")

print("=== 8x8 网格：每格中「亮像素(亮度>200)」占比 % ===")
print("       " + "".join(f"{int(c * W / 8):>6d}" for c in range(8)))
for r in range(8):
    y0, y1 = int(r * H / 8), int((r + 1) * H / 8)
    row = ""
    for c in range(8):
        x0, x1 = int(c * W / 8), int((c + 1) * W / 8)
        cell = a[y0:y1, x0:x1].reshape(-1, 3)
        lum = cell.mean(axis=1)
        row += f"{(lum > 200).mean() * 100:6.0f}"
    print(f"y{int(r * H / 8):>5d}" + row)

print("\n=== 关键颜色统计（这些色值都取自 index.html 的样式定义）===")


def cnt(rgb, tol=20):
    d = np.abs(a.astype(int) - np.array(rgb)).sum(axis=2)
    m = d < tol
    return int(m.sum()), m.sum() / (H * W) * 100


targets = [
    ("页面背景 #0d1117", (13, 17, 23)),
    ("面板 #1b2129", (27, 33, 41)),
    ("警示黄 数据日期徽章", (245, 158, 11)),
    ("错误红 横幅/徽章", (239, 68, 68)),
    ("成功绿 徽章", (74, 222, 128)),
    ("适飞蓝 41,128,185", (41, 128, 185)),
    ("底图米白", (244, 234, 228)),
    ("纯白", (255, 255, 255)),
]
for name, rgb in targets:
    n, p = cnt(rgb)
    print(f"  {name:24s} {n:>9,} px  {p:6.2f}%")

print("\n=== 顶栏区域（y 0~110）的颜色构成 ===")
top = a[:110].reshape(-1, 3)
cols, counts = np.unique(top[::3], axis=0, return_counts=True)
for i in np.argsort(-counts)[:8]:
    pct = counts[i] / len(top[::3]) * 100
    if pct > 0.4:
        print(f"  {tuple(int(v) for v in cols[i])}  {pct:5.2f}%")

print("\n=== 中央区域（地图主体 y 300~900, x 250~1900）===")
mid = a[300:900, 250:1900].reshape(-1, 3)
cols2, counts2 = np.unique(mid[::5], axis=0, return_counts=True)
for i in np.argsort(-counts2)[:8]:
    pct = counts2[i] / len(mid[::5]) * 100
    print(f"  {tuple(int(v) for v in cols2[i])}  {pct:5.2f}%")
