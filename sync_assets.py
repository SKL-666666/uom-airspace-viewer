# 把网页端资源与数据同步进 Android 的 assets 目录。
#
# 为什么要有这一步：APK 内置数据要求 index.html / lib / data 都在 assets 里，
# 但这些东西的【源】在仓库根目录（网页端用的同一份），不能复制一份进版本库 ——
# 85MB 数据 + 网页文件各存两份，既浪费又必然不同步（改了网页忘了同步）。
# 所以用脚本从根目录拷进构建目录，构建目录整体 gitignore。
#
# 用法: python sync_assets.py
#   构建 APK 前必须先跑这个（CI 里也一样）。
import io
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
ANDROID = os.path.join(ROOT, 'android')
ASSETS = os.path.join(ANDROID, 'app', 'src', 'main', 'assets')

# 需要打包进 APK 的东西（相对仓库根）
# 注意：不拷 serve.py / build_*.py / *.spec / android / harmony 等，
# 那些是开发或其它平台用的，进包只会增大体积。
INCLUDE_FILES = ['index.html', 'tile-worker.js']
INCLUDE_DIRS = ['lib', 'data']

# 数据里不需要进包的（仓库里有，但页面不请求）
EXCLUDE_NAMES = {
    'dji_flysafe.geojson',   # 全球原始数据 5.4MB，页面只用 dji_cn_*.geojson
}


def human(n):
    for u in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or u == 'GB':
            return '%.1f %s' % (n, u) if u != 'B' else '%d B' % n
        n /= 1024.0


def main():
    if os.path.isdir(ASSETS):
        shutil.rmtree(ASSETS)
    os.makedirs(ASSETS)

    total = 0
    missing = []

    for f in INCLUDE_FILES:
        src = os.path.join(ROOT, f)
        if not os.path.isfile(src):
            missing.append(f)
            continue
        dst = os.path.join(ASSETS, f)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        n = os.path.getsize(dst)
        total += n
        print('  %-28s %10s' % (f, human(n)))

    for d in INCLUDE_DIRS:
        sd = os.path.join(ROOT, d)
        if not os.path.isdir(sd):
            missing.append(d + '/')
            continue
        for base, dirs, files in os.walk(sd):
            dirs[:] = [x for x in dirs if x not in ('__pycache__', '.git')]
            rel = os.path.relpath(base, ROOT)
            for fn in files:
                if fn in EXCLUDE_NAMES:
                    print('  %-28s %10s  (跳过: 页面不请求)' % (
                        os.path.join(rel, fn).replace('\\', '/'), '-'))
                    continue
                src = os.path.join(base, fn)
                dst = os.path.join(ASSETS, rel, fn)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                n = os.path.getsize(dst)
                total += n
                print('  %-28s %10s' % (
                    os.path.join(rel, fn).replace('\\', '/'), human(n)))

    if missing:
        print('\n❌ 缺少以下必需文件/目录，无法构建：')
        for m in missing:
            print('   -', m)
        return 1

    # 自检：PMTiles 必须存在且大小合理（否则装出来的包读不到数据）
    pm = os.path.join(ASSETS, 'data', 'uom-shifei.pmtiles')
    if not os.path.isfile(pm):
        print('\n❌ assets/data 里没有 uom-shifei.pmtiles —— 内置数据不完整')
        return 1
    pm_size = os.path.getsize(pm)
    if pm_size < 50 * 1024 * 1024:
        print('\n❌ PMTiles 只有 %s，明显不完整（应为约 85MB）' % human(pm_size))
        return 1

    print('\n✓ assets 就绪：%d 个文件，合计 %s' % (
        sum(len(fs) for _, _, fs in os.walk(ASSETS)), human(total)))
    print('  位置: %s' % ASSETS)
    return 0


if __name__ == '__main__':
    print('同步网页资源与数据到 Android assets …')
    sys.exit(main())
