"""下载 UOM PMTiles / 大疆 GeoJSON。

走 api.github.com 取签名 CDN 直链（主站 github.com 不稳定），
支持断点续传：每次失败后重新取一次签名 URL，从已下载字节处续传。
"""
import json
import os
import sys
import time
import urllib.request

ASSETS = {
    "uom-shifei.pmtiles": 437347577,
    "dji_flysafe.geojson": None,  # 按名字查找
}
API = "https://api.github.com/repos/thezzisu/uomtiles/releases"
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/vnd.github+json"}


def resolve_url(asset_id=None, name=None):
    """取签名直链。asset_id 优先，否则按文件名匹配。"""
    req = urllib.request.Request(API, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        rels = json.load(r)
    for rel in rels:
        for a in rel.get("assets", []):
            if (asset_id and a["id"] == asset_id) or (name and a["name"] == name):
                req2 = urllib.request.Request(
                    a["url"], headers={**UA, "Accept": "application/octet-stream"}
                )

                class NoRedirect(urllib.request.HTTPRedirectHandler):
                    def redirect_request(self, *a, **k):
                        return None

                op = urllib.request.build_opener(NoRedirect)
                try:
                    op.open(req2, timeout=30)
                except urllib.error.HTTPError as e:
                    if e.code in (301, 302, 303, 307, 308):
                        return a["name"], a["size"], e.headers["Location"]
                    raise
    raise SystemExit(f"未找到资源: {asset_id or name}")


def download(name, total):
    path = os.path.join("data", name)
    os.makedirs("data", exist_ok=True)
    for attempt in range(1, 41):
        have = os.path.getsize(path) if os.path.exists(path) else 0
        if total and have >= total:
            print(f"[完成] {name} {have} B", flush=True)
            return True
        try:
            _, _, url = resolve_url(name=name)
            headers = {**UA, "Range": f"bytes={have}-"}
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as r:
                mode = "ab" if have else "wb"
                with open(path, mode) as f:
                    while True:
                        chunk = r.read(262144)
                        if not chunk:
                            break
                        f.write(chunk)
                        have += len(chunk)
                        if have % (5 * 1024 * 1024) < 262144:
                            pct = have / total * 100 if total else 0
                            print(
                                f"  {name}: {have/1048576:.1f}/{(total or 0)/1048576:.1f} MB ({pct:.1f}%)",
                                flush=True,
                            )
        except Exception as e:
            print(f"  [第{attempt}次失败] {e}", flush=True)
            time.sleep(2 + attempt)
            continue
        if os.path.getsize(path) >= total:
            print(f"[完成] {name} {os.path.getsize(path)} B", flush=True)
            return True
    print(f"[失败] {name} 重试耗尽", flush=True)
    return False


if __name__ == "__main__":
    targets = sys.argv[1:] or ["uom-shifei.pmtiles"]
    for t in targets:
        _, size, _u = resolve_url(name=t)
        print(f"目标 {t} ({size/1048576:.1f} MB)", flush=True)
        download(t, size)
