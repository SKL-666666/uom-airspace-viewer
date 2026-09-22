# 把网页资源与数据同步进 HarmonyOS 的 rawfile 目录。
#
# 与 sync_assets.py 同样的理由：APK/HAP 内置数据要求这些文件在包的资源目录里，
# 但它们的【源】在仓库根目录（网页端用同一份），不能复制进版本库 ——
# 85MB 数据存两份既浪费又必然不同步。所以构建前从这里拷过去，目标目录 gitignore。
#
# 用法: python sync_rawfile.py
#   harmony/scripts/build_hap.sh 会先调用它。
#
# 目录结构：rawfile/web/ 下放网页端全部内容。
#   加一层 web/ 是为了和 RangeHttpServer.kt 里的 RAW_PREFIX 对应，
#   避免网页资源与其它 rawfile 内容混在同一层。
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
RAWFILE = os.path.join(ROOT, 'harmony', 'entry', 'src', 'main', 'resources', 'rawfile')
WEB = os.path.join(RAWFILE, 'web')

INCLUDE_FILES = ['index.html', 'tile-worker.js']
INCLUDE_DIRS = ['lib', 'data']

# 仓库里有、但页面不请求的（不进包）
EXCLUDE_NAMES = {
    'dji_flysafe.geojson',   # 全球原始数据 5.4MB，页面只用 dji_cn_*.geojson
}


def human(n):
    for u in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or u == 'GB':
            return '%d B' % n if u == 'B' else '%.1f %s' % (n, u)
        n /= 1024.0


def main():
    if os.path.isdir(WEB):
        shutil.rmtree(WEB)
    os.makedirs(WEB)

    total = 0
    missing = []

    for f in INCLUDE_FILES:
        src = os.path.join(ROOT, f)
        if not os.path.isfile(src):
            missing.append(f)
            continue
        dst = os.path.join(WEB, f)
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
                    print('  %-28s %10s  (跳过)' % (
                        os.path.join(rel, fn).replace('\\', '/'), '-'))
                    continue
                src = os.path.join(base, fn)
                dst = os.path.join(WEB, rel, fn)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                n = os.path.getsize(dst)
                total += n
                print('  %-28s %10s' % (
                    os.path.join(rel, fn).replace('\\', '/'), human(n)))

    # AppScope 与 entry 都放了图标；module.json5 引用的 startIcon 需要存在
    media_dirs = [
        os.path.join(ROOT, 'harmony', 'AppScope', 'resources', 'base', 'media'),
        os.path.join(ROOT, 'harmony', 'entry', 'src', 'main', 'resources', 'base', 'media'),
    ]
    icon_src = os.path.join(ROOT, '_icons', 'icon_216.png')
    if os.path.isfile(icon_src):
        for md in media_dirs:
            os.makedirs(md, exist_ok=True)
            for name in ('app_icon.png', 'startIcon.png', 'foreground.png'):
                shutil.copy2(icon_src, os.path.join(md, name))
            background = os.path.join(md, 'background.png')
            shutil.copy2(icon_src, background)
        print('  图标已同步到 AppScope / entry 的 media 目录')

    if missing:
        print('\n❌ 缺少必需文件/目录：')
        for m in missing:
            print('   -', m)
        return 1

    pm = os.path.join(WEB, 'data', 'uom-shifei.pmtiles')
    if not os.path.isfile(pm):
        print('\n❌ rawfile 里没有 uom-shifei.pmtiles —— 内置数据不完整')
        return 1
    pm_size = os.path.getsize(pm)
    if pm_size < 50 * 1024 * 1024:
        print('\n❌ PMTiles 只有 %s，明显不完整（应约 85MB）' % human(pm_size))
        return 1

    files = sum(len(fs) for _, _, fs in os.walk(WEB))
    print('\n✓ rawfile 就绪：%d 个文件，合计 %s' % (files, human(total)))
    print('  位置: %s' % WEB)
    return 0


if __name__ == '__main__':
    print('同步网页资源与数据到 HarmonyOS rawfile …')
    sys.exit(main())
