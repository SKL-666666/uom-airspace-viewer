"""排查天地图 key 到底哪里出问题。

用法（在项目目录下）：
    python check_tdt_key.py 你的tk参数

它会：
  1. 用你的 key 请求一张天地图瓦片，打印**确切的 HTTP 状态码**
  2. 用「不带 key」和「带一个明显错误的 key」做对照
  3. 根据状态码给出判断

为什么要单独做这个工具：浏览器里 <img> 加载失败只能知道"失败了"，
拿不到状态码（跨域图片读不到）。而这个区别很关键 ——
418 是 WAF 拦截，403 是 key 被拒，429 是配额，200 才是正常。
"""
import sys
import urllib.error
import urllib.request

SUB = 0          # 用 t0 测
LAYER = "vec"
ZOOM, ROW, COL = 5, 12, 25          # 中国境内一张有内容的瓦片


def probe(tk, note):
    url = (f"https://t{SUB}.tianditu.gov.cn/{LAYER}_w/wmts"
           f"?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
           f"&LAYER={LAYER}&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles"
           f"&TILEMATRIX={ZOOM}&TILEROW={ROW}&TILECOL={COL}&tk={tk}")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Referer": "http://127.0.0.1:8080/",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = r.read()
            kind = ("JPEG" if data[:2] == b"\xff\xd8"
                    else "PNG" if data[:4] == b"\x89PNG"
                    else "HTML" if b"<" in data[:200] else "OTHER")
            print(f"  {note:26s} HTTP {r.status}  {len(data):6d}B  {kind}")
            return r.status, data
    except urllib.error.HTTPError as e:
        body = e.read()
        print(f"  {note:26s} HTTP {e.code}  {len(body):6d}B  "
              f"{e.headers.get('Content-Type', '')}")
        return e.code, body
    except Exception as e:
        print(f"  {note:26s} 请求失败: {type(e).__name__} {e}")
        return None, b""


def main():
    tk = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    if not tk:
        print("用法: python check_tdt_key.py 你的tk参数")
        print("（tk 在 UOM 页面左侧「API Key」区填写过的那个值）")
        return 1

    print("=== 天地图 key 检测 ===")
    print(f"  key 长度 {len(tk)}，前 4 位 {tk[:4]}****\n")

    print("  对照：")
    probe("", "不带 key")
    probe("0000000000000000000000000000FFFF", "明显错误的 key")
    print()
    print("  你的 key：")
    code, body = probe(tk, "你的 key")

    print("\n=== 判断 ===")
    if code == 200 and body[:4] == b"\x89PNG":
        print("  ✓ key 可用，接口返回了正常瓦片。")
        print("    那么浏览器里加载失败就是别的原因：")
        print("    - 该 key 的 referrer/域名白名单不包含当前页面源")
        print("      （天地图申请时可限定域名，为 A 域名申请的换 B 会失效）")
        print("    - 或浏览器侧网络/代理干扰")
    elif code == 418:
        print("  ✗ HTTP 418 —— 被天地图的 WAF 拦截。")
        print("    不带 key 和用错 key 也会得到同样的 418，所以这个码")
        print("    只说明「请求被拦」，不能区分是 key 的问题还是其它拦截。")
        print("    如果你的 key 在上面显示 418，而正确配置的 key 应该是 200，")
        print("    那基本可以判定该 key 已失效/额度用尽。")
    elif code in (401, 403):
        print(f"  ✗ HTTP {code} —— key 被拒绝。")
        print("    常见原因：key 已过期、被停用、或限定了域名/referrer。")
    elif code == 429:
        print("  ✗ HTTP 429 —— 请求过多，当日配额或 QPS 用尽。")
    elif code is None:
        print("  ✗ 连不上。网络层面就不通。")
    else:
        print(f"  ? HTTP {code} —— 少见的状态码，把上面的输出发给开发者。")

    print("\n  参考：天地图正确的响应应当是 HTTP 200 + PNG 图片。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
