/* 关键验证：批量取数报告的"无数据"，是不是真的无数据。
 *
 * 之前的测试只验证了「有数据的瓦片内容正确」，存在盲区：
 * 如果 Worker 因为目录解析的 bug 找不到某块瓦片，它会返回 data:null，
 * 客户端就当成"此处无数据"缓存下来 —— 那块瓦片永远不会再请求，
 * 表现为"原本应该是蓝色的区域一直是白的且刷不出来"。
 *
 * 本测试把 Worker 对每一块瓦片的判定，与 Python 参考实现
 * （已在别处逐字节验证过）逐一对比。
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { execFileSync } = require('child_process');

const BASE = 'http://127.0.0.1:8080';
const ROOT = __dirname;
const wait = (ms) => new Promise(r => setTimeout(r, ms));

/* ---- 用 Python 参考实现算出「每块瓦片到底有没有数据」---- */
function pythonTruth(tiles) {
  const py = `
import sys, json
sys.path.insert(0, '.')
import pmtiles_tool as pt
pm = pt.PMTiles('data/uom-shifei.pmtiles')
tiles = json.loads(sys.argv[1])
out = []
for z, x, y in tiles:
    out.append(pm.get_tile(z, x, y) is not None)
print(json.dumps(out))
`;
  const r = execFileSync('python', ['-c', py, JSON.stringify(tiles)],
                         { cwd: ROOT, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });
  return JSON.parse(r.trim());
}

function makeWorker() {
  const sb = {
    DecompressionStream, Blob, Response, Request, Headers, AbortController,
    URL, TextDecoder, TextEncoder, console, setTimeout, clearTimeout,
    Promise, Map, Set, Array, Object, Math, JSON, Number, String,
    DataView, Uint8Array, ArrayBuffer, Error, TypeError, performance,
    navigator: { userAgent: 'Mozilla/5.0 (Windows NT 10.0) Chrome/120.0' },
    fetch: (input, init) => fetch(
      typeof input === 'string' && input.startsWith('http')
        ? input : BASE + '/' + String(input).replace(/^\//, ''), init),
    posted: [], self: null,
  };
  sb.self = sb;
  sb.postMessage = (m) => sb.posted.push(m);
  const ctx = vm.createContext(sb);
  sb.__ctx = ctx;
  sb.importScripts = (p) => vm.runInContext(
    fs.readFileSync(path.join(ROOT, p), 'utf8'), ctx, { filename: p });
  vm.runInContext(fs.readFileSync(path.join(ROOT, 'tile-worker.js'), 'utf8'),
                  ctx, { filename: 'tile-worker.js' });
  return sb;
}

(async () => {
  let fail = 0;
  const ok = (c, m) => { console.log(`  ${c ? '✓' : '✗'} ${m}`); if (!c) fail++; };

  const w = makeWorker();
  await wait(1500);
  ok(w.posted.some(m => m.ready), 'Worker 目录就绪');

  /* 覆盖多个区域与层级，尤其包含"应该有数据"的地方 */
  const cases = [
    { name: '新疆 z11（适飞密集）', z: 11, cx: 85.0, lat: 41.0, nx: 6, ny: 5 },
    { name: '甘肃/内蒙 z9',        z: 9,  cx: 105.0, lat: 40.0, nx: 6, ny: 5 },
    { name: '陕西 z13',            z: 13, cx: 108.0, lat: 34.0, nx: 5, ny: 4 },
    { name: '黑龙江 z10',          z: 10, cx: 128.0, lat: 47.0, nx: 5, ny: 4 },
  ];

  for (const c of cases) {
    const n = 1 << c.z;
    const x0 = Math.floor((c.cx + 180) / 360 * n) - Math.floor(c.nx / 2);
    const y0 = Math.floor((1 - Math.asinh(Math.tan(c.lat * Math.PI / 180)) / Math.PI) / 2 * n)
             - Math.floor(c.ny / 2);
    const tiles = [];
    for (let x = x0; x < x0 + c.nx; x++)
      for (let y = y0; y < y0 + c.ny; y++) tiles.push([c.z, x, y]);

    const truth = pythonTruth(tiles);            // Python 参考实现

    const id = Math.floor(Math.random() * 1e6) + 1;
    w.onmessage({ data: { batch: true, id, tiles } });
    let res = null;
    for (let i = 0; i < 60 && !res; i++) {
      await wait(150);
      res = w.posted.find(m => m.id === id && m.results);
    }
    if (!res) { console.log(`  ✗ ${c.name}: 未收到结果`); fail++; continue; }

    const mine = res.results.map(r => !!(r && r.data));
    let mismatch = 0;
    const detail = [];
    mine.forEach((v, i) => {
      if (v !== truth[i]) {
        mismatch++;
        if (detail.length < 6)
          detail.push(`z${tiles[i][0]}/${tiles[i][1]}/${tiles[i][2]} ` +
                      `Worker=${v ? '有' : '无'} Python=${truth[i] ? '有' : '无'}`);
      }
    });
    const haveData = truth.filter(Boolean).length;
    console.log(`\n  ${c.name}: ${tiles.length} 块，Python 说有数据的 ${haveData} 块`);
    ok(mismatch === 0,
       mismatch === 0
         ? 'Worker 的判定与 Python 参考实现完全一致'
         : `有 ${mismatch} 块判定不一致`);
    detail.forEach(d => console.log(`      ${d}`));
  }

  console.log(`\n=== ${fail === 0 ? '全部通过：批量取数没有漏判' : fail + ' 项失败 —— 存在漏判！'} ===`);
  process.exit(fail === 0 ? 0 : 1);
})().catch(e => { console.error('致命错误:', e); process.exit(1); });
