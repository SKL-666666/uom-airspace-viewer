# 生成应用图标：单色几何符号。
#
# 设计：一个圆角方块底 + 白色"定位/空域"几何符号。
# 符号用最少的笔画表达"在某个位置查空域"：
#   · 一个靶心（两个同心圆 + 中心点）= 定位/选点
#   · 左右两道弧 = 空域边界/范围
# 不用文字（小尺寸下会糊），不用渐变（缩放后容易脏），单色为主。
#
# 为什么用 PIL 直接画而不用 SVG 再转：本机没有 SVG 渲染器
# （cairosvg / rsvg / inkscape 都没有），装了也不一定和最终观感一致。
# 直接用 PIL 画圆和弧，尺寸与位置完全可控，也不会引入构建依赖。
#
# 用法: python make_icons.py     （输出到 _icons/ 与两个平台各自的目录）
import os
import math
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.abspath(__file__))

# 配色：与工具主色一致的适飞蓝，配近白符号。
# 单色几何 + 高对比，保证在 48px 这种极小尺寸下依然认得出。
BG = (41, 128, 185, 255)      # #2980b9 —— 就是适飞层用的那个蓝
FG = (255, 255, 255, 255)

SS = 8                        # 超采样倍数，先画大图再缩，边缘才干净


def draw_icon(size):
    """画出 size×size 的图标（返回 RGBA）。"""
    S = size * SS
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # ---- 底：圆角方块 ----
    # 圆角半径取边长的 22%（Android/iOS 图标的常见比例），
    # 太小显得方，太大在圆形遮罩下会被裁掉边角。
    r = int(S * 0.22)
    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=r, fill=BG)

    cx, cy = S / 2, S / 2
    lw = max(2, int(S * 0.062))          # 统一线宽，随尺寸等比

    # ---- 左右两道弧：表示"空域范围" ----
    # 用 arc 画半环，开口朝外，形成"夹住一个点"的观感。
    ar = int(S * 0.335)                  # 弧的半径
    box = [cx - ar, cy - ar, cx + ar, cy + ar]
    d.arc(box, start=118, end=242, fill=FG, width=lw)
    d.arc(box, start=-62, end=62, fill=FG, width=lw)

    # ---- 靶心：同心圆 ----
    r1 = int(S * 0.175)                  # 外圈
    d.ellipse([cx - r1, cy - r1, cx + r1, cy + r1], outline=FG, width=lw)
    r2 = int(S * 0.062)                  # 中心实心点
    d.ellipse([cx - r2, cy - r2, cx + r2, cy + r2], fill=FG)

    return img.resize((size, size), Image.LANCZOS)


def save_all():
    out_dirs = {}
    # 平台目录
    android_res = os.path.join(ROOT, 'android', 'app', 'src', 'main', 'res')
    harmony_media = os.path.join(ROOT, 'harmony', 'AppScope', 'resources', 'base', 'media')
    preview = os.path.join(ROOT, '_icons')
    for p in (preview, android_res, harmony_media):
        if os.path.isdir(os.path.dirname(p)) or p == preview:
            os.makedirs(p, exist_ok=True)

    # Android：mipmap-*dpi 需要 48/72/96/144/192
    android_sizes = {
        'mipmap-mdpi': 48, 'mipmap-hdpi': 72, 'mipmap-xhdpi': 96,
        'mipmap-xxhdpi': 144, 'mipmap-xxxhdpi': 192,
    }
    for dpi, px in android_sizes.items():
        d = os.path.join(android_res, dpi)
        os.makedirs(d, exist_ok=True)
        draw_icon(px).save(os.path.join(d, 'ic_launcher.png'))
        print('  android/%s/ic_launcher.png  %dpx' % (dpi, px))

    # HarmonyOS：AppScope 的 app_icon 需要 216px；
    # 分层图标 foreground/background 也用同一套（符号居中、留出安全边距）
    for name, px in (('app_icon.png', 216), ('foreground.png', 216), ('background.png', 216)):
        draw_icon(px).save(os.path.join(harmony_media, name))
        print('  harmony/AppScope/.../%s  %dpx' % (name, px))

    # 预览：给 README 和人工核对用
    for px in (48, 72, 96, 144, 192, 216, 384):
        draw_icon(px).save(os.path.join(preview, 'icon_%d.png' % px))
    # 一张拼版，方便一眼看各尺寸是否都还认得出
    tiles = [draw_icon(s) for s in (48, 72, 96, 144, 192, 216, 384)]
    pad = 12
    W = sum(t.width for t in tiles) + pad * (len(tiles) + 1)
    H = max(t.height for t in tiles) + pad * 2
    sheet = Image.new('RGBA', (W, H), (245, 246, 248, 255))
    x = pad
    for t in tiles:
        sheet.paste(t, (x, pad + (H - pad * 2 - t.height) // 2), t)
        x += t.width + pad
    sheet.save(os.path.join(preview, 'preview_sheet.png'))
    print('  _icons/preview_sheet.png  各尺寸拼版')


if __name__ == '__main__':
    print('生成图标（单色几何符号）…')
    save_all()
    print('完成')
