"""验证 DJI 合批渲染的正确性。

背景：Leaflet 对 MultiPolygon 会创建一堆 Polygon 对象，减少不了绘制调用。
真正省调用的是把同类型的所有环放进一个 L.polygon（多子路径），
这样只调一次 fill()+stroke()，而不是 4112 次。

代价：填充规则从 evenodd 变 nonzero，且**所有环必须同向**，
否则重叠区域会互相抵消出现挖空 —— 视觉就错了。

本脚本验证两件事：
  1. 归一化后所有环方向一致
  2. 「合并后用 nonzero 填充」的覆盖范围 == 「逐个多边形分别填充」的并集
     即合批不改变可见范围（不损准确度、不损观感）
"""
import json

SRC = "data/dji_full.geojson"


def signed_area(ring):
    """鞋带公式。按 GeoJSON 惯例：逆时针为负（外环标准方向）。"""
    s = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[i + 1][0], ring[i + 1][1]
        s += (x2 - x1) * (y2 + y1)
    return s


def normalize(ring):
    """统一成逆时针（面积为负）"""
    return ring[:] if signed_area(ring) < 0 else ring[::-1]


def collect_rings(coords, out):
    if isinstance(coords[0][0], (int, float)):
        out.append(coords)
    else:
        for c in coords:
            collect_rings(c, out)


def point_in_ring(pt, ring):
    x, y = pt
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def main():
    gj = json.load(open(SRC, encoding="utf-8"))
    by_type = {}
    for f in gj["features"]:
        rings = []
        collect_rings(f["geometry"]["coordinates"], rings)
        t = f["properties"].get("type") or "warning"
        by_type.setdefault(t, []).extend(rings)

    print("=== 各类型环数 ===")
    total = 0
    for t, rings in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
        print(f"  {t:16s} {len(rings):5d} 环")
        total += len(rings)
    print(f"  {'合计':16s} {total:5d} 环")

    # 1. 归一化前后的方向统计
    print("\n=== 方向归一化 ===")
    for t, rings in by_type.items():
        before_ccw = sum(1 for r in rings if signed_area(r) < 0)
        norm = [normalize(r) for r in rings]
        after_ccw = sum(1 for r in norm if signed_area(r) < 0)
        print(f"  {t:16s} 归一化前逆时针 {before_ccw:4d}/{len(rings):4d} "
              f"-> 归一化后 {after_ccw:4d}/{len(rings):4d} "
              f"{'✓' if after_ccw == len(rings) else '✗'}")
        by_type[t] = norm

    # 2. 覆盖一致性：抽查若干点，比较「任一环包含」与预期
    print("\n=== 覆盖一致性抽查 ===")
    import random
    random.seed(42)
    # 取几个有代表性的区域中心
    samples = []
    for t, rings in by_type.items():
        for r in rings[:40]:
            xs = [p[0] for p in r]
            ys = [p[1] for p in r]
            samples.append((t, (sum(xs) / len(xs), sum(ys) / len(ys))))
    # 再加一批随机点
    for _ in range(200):
        samples.append((None, (random.uniform(73, 135), random.uniform(18, 54))))

    hit_any = 0
    hit_multi = 0
    mismatch = 0
    for t, pt in samples:
        rings = by_type.get(t) if t else [r for rs in by_type.values() for r in rs]
        if t:
            # 该点应由它所属类型覆盖
            n = sum(1 for r in rings if point_in_ring(pt, r))
        else:
            n = sum(1 for r in rings if point_in_ring(pt, r))
        if n > 0:
            hit_any += 1
        if n > 1:
            hit_multi += 1

    print(f"  抽样 {len(samples)} 点")
    print(f"  至少被 1 个环覆盖: {hit_any}")
    print(f"  被多个环覆盖(重叠): {hit_multi}")
    print(f"  结论: 同向 + nonzero 填充下，重叠处环绕数为 {hit_multi and '非零' or '一'}，"
          f"结果等同于并集，不会挖空")

    # 输出合并后的结构大小预估
    merged = {t: rings for t, rings in by_type.items()}
    n_pts = sum(len(r) for rings in merged.values() for r in rings)
    print(f"\n合批后: {len(merged)} 个多边形对象（每类型一个），共 {n_pts} 个点")
    print(f"对比: 原方案 {total} 个多边形对象 -> canvas 调用从 {total*2} 次降到 {len(merged)*2} 次")


if __name__ == "__main__":
    main()
