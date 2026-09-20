"""模拟浏览器通过 HTTP Range 访问 PMTiles 的完整流程，验证服务端正确性。

复刻 pmtiles.js 的 FetchSource.getBytes(offset, length)：
    fetch(url, {headers:{range: f"bytes={offset}-{offset+length-1}"}})
然后把每一步取回的字节与本地文件比对。任何一步不一致，
就说明 serve.py 的 Range 实现有问题。
"""
import gzip
import struct
import sys
import urllib.request

import pmtiles_tool as pt

URL = "http://127.0.0.1:8080/data/uom-shifei.pmtiles"
LOCAL = "data/uom-shifei.pmtiles"

local = open(LOCAL, "rb").read()
stats = {"n": 0, "bad": 0, "bytes": 0}


def get_bytes(offset, length):
    """完全按 FetchSource 的方式发请求。"""
    req = urllib.request.Request(
        URL, headers={"Range": f"bytes={offset}-{offset + length - 1}"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        status = r.status
        data = r.read()
    stats["n"] += 1
    stats["bytes"] += len(data)
    return status, data


def check(label, offset, length):
    try:
        status, data = get_bytes(offset, length)
    except Exception as e:
        print(f"  ✗ {label}: 请求失败 {e}")
        stats["bad"] += 1
        return None
    expect = local[offset:offset + length]
    if status != 206:
        print(f"  ✗ {label}: 状态码 {status}（期望 206）")
        stats["bad"] += 1
        return None
    if len(data) != length:
        print(f"  ✗ {label}: 长度 {len(data)}（期望 {length}）")
        stats["bad"] += 1
        return None
    if data != expect:
        print(f"  ✗ {label}: 内容与本地文件不一致")
        stats["bad"] += 1
        return None
    print(f"  ✓ {label}: 206 / {length}B / 内容一致")
    return data


print("=== 模拟浏览器 PMTiles 访问流程 ===\n")

# 1. 头部 127 字节
h = check("① 头部 127B", 0, 127)
if not h:
    sys.exit("头部取不到，中止")

magic = h[:7]
print(f"     魔数 {magic}, 版本 {h[7]}")
root_off, root_len = struct.unpack("<QQ", h[8:24])
leaf_off, leaf_len = struct.unpack("<QQ", h[40:56])
data_off, data_len = struct.unpack("<QQ", h[56:72])
print(f"     根目录 off={root_off} len={root_len}")
print(f"     叶目录 off={leaf_off} len={leaf_len}")
print(f"     数据区 off={data_off} len={data_len}\n")

# 2. 根目录
raw = check("② 根目录", root_off, root_len)
if raw:
    root = pt.deserialize_index(gzip.decompress(raw))
    print(f"     解出 {len(root)} 项\n")

# 3. 叶子目录
raw2 = check("③ 叶子目录[0]", leaf_off, root[0]["length"])
if raw2:
    leaf = pt.deserialize_index(gzip.decompress(raw2))
    print(f"     解出 {len(leaf)} 项\n")

# 4. 取一个已知存在的瓦片（z5/25/12）
pm = pt.PMTiles(LOCAL)
e = pm._find(pt.zxy_to_tileid(5, 25, 12))
if e:
    off = data_off + e["offset"]
    t = check(f"④ 瓦片 z5/25/12", off, e["length"])
    if t:
        print(f"     PNG: {t[:4] == b'\\x89PNG'}  大小 {len(t)}B")
        px = pt.png_pixel(t, 128, 128)
        print(f"     (128,128) 像素 RGBA={px}")
else:
    print("  ✗ 本地也找不到该瓦片")

# 5. 连续随机 Range（模拟并发取瓦片）
print()
import random
random.seed(1)
ok = True
for i in range(30):
    off = random.randrange(0, len(local) - 4096)
    ln = random.randrange(256, 4096)
    try:
        st, d = get_bytes(off, ln)
        if st != 206 or d != local[off:off + ln]:
            print(f"  ✗ 随机 Range #{i} off={off} len={ln} 不一致")
            stats["bad"] += 1
            ok = False
            break
    except Exception as ex:
        print(f"  ✗ 随机 Range #{i} 异常 {ex}")
        stats["bad"] += 1
        ok = False
        break
if ok:
    print("  ✓ 30 次随机 Range 全部一致")

print(f"\n=== 小结 ===")
print(f"  请求次数: {stats['n']}")
print(f"  失败次数: {stats['bad']}")
print(f"  传输字节: {stats['bytes']:,}")
print("  服务端 Range 实现:", "正确" if stats["bad"] == 0 else "有问题")
