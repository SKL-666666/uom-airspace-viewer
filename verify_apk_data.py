# 校验 APK 里确实含内置数据，且数据没有被压缩。
#
# 为什么要有这个独立脚本（而不是塞在 CI 的 YAML 里）：
#   1) YAML 里嵌 heredoc 极易被缩进/转义搞坏，我实际踩过一次 ——
#      一个 \n 被展开成真换行，整个 workflow 变成非法 YAML，CI 直接不跑；
#   2) 抽出成脚本后本地也能跑，构建前后都能自查，不必等 CI。
#
# 校验两件事：
#   · 必需文件都在（缺任何一个都会导致地图空白或图层失效）
#   · .pmtiles 必须是 STORED（未压缩）：
#     assets 里的文件默认会被压缩，而 AssetManager.openFd 只对未压缩条目有效。
#     一旦被压缩，本地服务只能退化成"整文件读一遍来数长度"，
#     85MB 每处理一个 Range 请求都要读一遍 —— 直接不可用。
#
# 用法: python verify_apk_data.py [apk所在目录或apk文件]
import glob
import os
import sys
import zipfile

DEFAULT_DIR = os.path.join('android', 'app', 'build', 'outputs', 'apk', 'release')

# 进包必需的文件（相对 apk 根）
NEED = [
    'assets/index.html',
    'assets/tile-worker.js',
    'assets/lib/leaflet.js',
    'assets/lib/leaflet.css',
    'assets/lib/pmtiles.js',
    'assets/data/uom-shifei.pmtiles',
    'assets/data/dji_cn_full.geojson',
    'assets/data/dji_cn_low.geojson',
    'assets/data/custom_zones.geojson',
]

# 体积下限，用来抓"文件在但内容不完整"
MIN_SIZE = {
    'assets/data/uom-shifei.pmtiles': 50 * 1024 * 1024,
    'assets/index.html': 50 * 1024,
    'assets/lib/leaflet.js': 50 * 1024,
    'assets/lib/pmtiles.js': 20 * 1024,
}


def find_apk(target):
    if os.path.isfile(target):
        return target
    cands = sorted(glob.glob(os.path.join(target, '*.apk')), key=os.path.getmtime)
    return cands[-1] if cands else None


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DIR
    apk = find_apk(target)
    if not apk:
        print('❌ 在 %s 下没找到 APK' % target)
        return 1

    print('校验 %s (%.1f MB)\n' % (os.path.basename(apk), os.path.getsize(apk) / 1024 / 1024))
    z = zipfile.ZipFile(apk)
    names = set(z.namelist())
    bad = []

    for n in NEED:
        if n not in names:
            bad.append('缺失: ' + n)
            print('  ✗ %-44s 缺失' % n)
            continue
        info = z.getinfo(n)
        note = ''
        if n.endswith('.pmtiles') and info.compress_type != zipfile.ZIP_STORED:
            bad.append('被压缩（openFd 会失败）: ' + n)
            note = '  ← 被压缩！'
        lo = MIN_SIZE.get(n)
        if lo and info.file_size < lo:
            bad.append('体积异常(%d < %d): %s' % (info.file_size, lo, n))
            note += '  ← 体积异常'
        print('  ✓ %-44s %10.1f KB  method=%d%s' % (
            n, info.file_size / 1024, info.compress_type, note))

    # 顺带确认图标存在（缺图标不影响功能，但影响上架与桌面显示）
    icons = [n for n in names if n.startswith('res/') and n.endswith('.png')]
    print('\n  图标资源 %d 个' % len(icons))
    if not icons:
        bad.append('没有任何图标资源')

    print()
    if bad:
        print('❌ 校验失败：')
        for b in bad:
            print('   -', b)
        return 1
    print('✓ 内置数据校验通过')
    return 0


if __name__ == '__main__':
    sys.exit(main())
