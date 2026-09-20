"""压测 serve.py：模拟浏览器加载一屏瓦片时的并发 Range 请求。

目的：确认瓶颈是否在服务器。
浏览器对同一域名最多开 6 条并发连接（HTTP/1.1），所以分别测
并发 6 和并发 1 的吞吐，看是否被服务器拖住。
"""
import statistics
import threading
import time
import urllib.request

URL = "http://127.0.0.1:8080/data/uom-shifei.pmtiles"
N = 240              # 一屏瓦片数量级
SIZE = 2600          # 典型瓦片字节数


def one(offsets, results, idx):
    """在一条连接上顺序发请求（urllib 默认会复用连接池）"""
    import http.client
    from urllib.parse import urlparse
    u = urlparse(URL)
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=30)
    lat = []
    try:
        for off in offsets:
            t = time.perf_counter()
            conn.request("GET", u.path, headers={"Range": f"bytes={off}-{off+SIZE-1}"})
            r = conn.getresponse()
            r.read()
            lat.append((time.perf_counter() - t) * 1000)
    finally:
        conn.close()
    results[idx] = lat


def bench(concurrency, label):
    offsets = [1000 + i * 4096 for i in range(N)]
    # 把 N 个请求分给 concurrency 条连接
    chunks = [offsets[i::concurrency] for i in range(concurrency)]
    results = [None] * concurrency
    threads = [threading.Thread(target=one, args=(c, results, i))
               for i, c in enumerate(chunks)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    total = time.perf_counter() - t0
    lat = [x for r in results if r for x in r]
    print(f"\n{label}")
    print(f"  请求数 {len(lat)}  并发 {concurrency}  总耗时 {total*1000:.0f} ms")
    print(f"  吞吐 {len(lat)/total:.0f} req/s")
    if lat:
        lat_sorted = sorted(lat)
        print(f"  单请求延迟: 中位 {statistics.median(lat):.1f} ms | "
              f"均值 {statistics.mean(lat):.1f} ms | "
              f"p95 {lat_sorted[int(len(lat)*0.95)]:.1f} ms | "
              f"最大 {max(lat):.1f} ms")
    return total


if __name__ == "__main__":
    print("=== serve.py 并发压测 ===")
    print(f"目标 {URL}")
    bench(1, "① 串行（1 连接）")
    bench(6, "② 并发 6 连接（浏览器实际行为）")
    bench(6, "③ 并发 6 连接（复测）")
