# 验证 LocalAssetServer 的 Range 实现逻辑是否正确。
#
# 为什么需要它：Android 代码我无法在本机运行（没有 Android SDK 模拟器环境），
# 而 Range 处理是内置数据方案的关键 —— 一旦算错，表现为"PMTiles 读不了、
# 地图一片空白"，却看不出是哪里错。
# 所以把 LocalAssetServer 里那段 parse 逻辑【逐条照搬】成 Python 再测，
# 保证：越界回 416、bytes=a-b / a- / -n 三种形式都对、边界值不差一。
#
# 注意：这是"逻辑等价"的移植，不是跑真实 Java。它能抓住逻辑错误，
# 不能替代真机验证 —— 这一点在 README 里明确写了。
#
# 用法: python test_range_server.py
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
PM = os.path.join(ROOT, 'android', 'app', 'src', 'main', 'assets',
                  'data', 'uom-shifei.pmtiles')
if not os.path.isfile(PM):
    PM = os.path.join(ROOT, 'data', 'uom-shifei.pmtiles')
SIZE = os.path.getsize(PM)


def parse_range(spec, size):
    """照搬 LocalAssetServer.handle 里的解析。
    返回 (partial, start, end) 或 ('416',) 或 None（无 Range）。"""
    if spec is None or not spec.startswith('bytes='):
        return None
    s = spec[6:].strip()
    dash = s.find('-')
    if dash < 0:
        return None
    a = s[:dash].strip()
    b = s[dash + 1:].strip()
    start, end = 0, size - 1
    if a == '' and b != '':
        try:
            n = int(b)
        except ValueError:
            return ('416',)
        if n <= 0:
            return ('416',)
        start = max(0, size - n)
        end = size - 1
    elif a != '':
        try:
            start = int(a)
            end = size - 1 if b == '' else min(int(b), size - 1)
        except ValueError:
            return ('416',)
    else:
        return ('416',)
    if start < 0 or start >= size or end < start:
        return ('416',)
    return (True, start, end)


fail = 0
total = 0


def ok(cond, label, extra=''):
    global fail, total
    total += 1
    if cond:
        print('  ✓ ' + label)
    else:
        fail += 1
        print('  ✗ ' + label + ('  ' + extra if extra else ''))


print('=== Range 解析逻辑测试（PMTiles 大小 %d 字节）===\n' % SIZE)

print('— 1. 不带 Range -> 整体 200 —')
ok(parse_range(None, SIZE) is None, '无 Range 头返回 None（走 200 全量）')
ok(parse_range('bytes=', SIZE) is None, '"bytes=" 视为无有效范围')

print('\n— 2. PMTiles 实际会用的取法 —')
# PMTiles 读头部：前 127 字节
r = parse_range('bytes=0-126', SIZE)
ok(r == (True, 0, 126), 'bytes=0-126 -> 0..126', repr(r))
ok(r[2] - r[1] + 1 == 127, '长度正好 127')
# 读某个中间区间
r = parse_range('bytes=1000-1999', SIZE)
ok(r == (True, 1000, 1999), 'bytes=1000-1999 -> 1000..1999')

print('\n— 3. 开放式与后缀式 —')
r = parse_range('bytes=%d-' % (SIZE - 10), SIZE)
ok(r == (True, SIZE - 10, SIZE - 1), 'bytes=N- 到最后')
r = parse_range('bytes=-100', SIZE)
ok(r == (True, SIZE - 100, SIZE - 1), 'bytes=-100 取末尾 100 字节')

print('\n— 4. 越界必须回 416（PMTiles 靠它判断读到头）—')
ok(parse_range('bytes=%d-' % SIZE, SIZE) == ('416',), '起点等于文件大小 -> 416')
ok(parse_range('bytes=%d-' % (SIZE + 1000), SIZE) == ('416',), '起点超出 -> 416')
ok(parse_range('bytes=100-50', SIZE) == ('416',), '起点>终点 -> 416')
ok(parse_range('bytes=-0', SIZE) == ('416',), 'bytes=-0 -> 416（0 字节无意义）')

print('\n— 5. 终点超出时钳到文件末尾（不是 416）—')
r = parse_range('bytes=%d-%d' % (SIZE - 10, SIZE + 9999), SIZE)
ok(r == (True, SIZE - 10, SIZE - 1), '终点超界被钳到 SIZE-1', repr(r))

print('\n— 6. 畸形输入不能崩 —')
for bad in ['bytes=abc-def', 'units=0-10', 'bytes=', 'bytes=-', 'bytes=a-',
            'bytes=--', 'no-range-header']:
    try:
        parse_range(bad, SIZE)
        ok(True, '不抛错: %r' % bad)
    except Exception as e:
        ok(False, '抛错了: %r' % bad, str(e))

print('\n— 7. 与真实文件对照：按解析出的区间读，内容必须对得上 —')
with open(PM, 'rb') as f:
    head = f.read(127)
r = parse_range('bytes=0-126', SIZE)
with open(PM, 'rb') as f:
    f.seek(r[1])
    got = f.read(r[2] - r[1] + 1)
ok(got == head, '前面 127 字节读取一致')
ok(head[:7] == b'PMTiles', '确实是 PMTiles 文件（魔数正确）')

# 抽三个随机区间做字节级校验（模拟 PMTiles 跳着读的行为）
import random
random.seed(42)
allgood = True
for _ in range(3):
    a = random.randrange(0, SIZE - 5000)
    b = a + 4095
    r = parse_range('bytes=%d-%d' % (a, b), SIZE)
    with open(PM, 'rb') as f:
        f.seek(r[1]); got = f.read(r[2] - r[1] + 1)
        f.seek(a); want = f.read(b - a + 1)
    if got != want:
        allgood = False
        break
ok(allgood, '随机区间的字节内容与直接读取一致')

if fail == 0:
    print('\n=== 全部通过：%d 项 ===' % total)
else:
    print('\n=== %d/%d 项失败 ===' % (fail, total))
sys.exit(0 if fail == 0 else 1)
