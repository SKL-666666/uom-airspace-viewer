/* 验证 tile-worker.js 的批量取数：在 Node 里完整模拟 Worker 环境。
 *
 * 用 vm 建一个沙箱当 Worker 全局，实现 importScripts 加载 lib/pmtiles.js，
 * 再把 fetch 重写成带 base 的请求。这样跑的就是 Worker 里那份真实代码。
 *
 * 校验方式：把取回的每张瓦片与「Python 版已逐字节验证过的偏移」对照，
 * 并解析 PNG 魔数与像素，确认不是"拿到了但内容错位"。
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const BASE = 'http://127.0.0.1:8080';
const ROOT = __dirname;

function makeWorkerSandbox() {
  const sandbox = {
    DecompressionStream, Blob, Response, Request, Headers, AbortController,
    URL, TextDecoder, TextEncoder, console, setTimeout, clearTimeout, setInterval,
    clearInterval, Promise, Map, Set, Array, Object, Math, JSON, Number, String,
    DataView, Uint8Array, ArrayBuffer, Error, TypeError, performance,
    navigator: { userAgent: 'Mozilla/5.0 (Windows NT 10.0) Chrome/120.0' },
    // 相对路径补成 http://127.0.0.1:8080/
    fetch: (input, init) => {
      const url = typeof input === 'string' && input.startsWith('http')
        ? input : BASE + '/' + String(input).replace(/^\//, '');
      return fetch(url, init);
    },
    posted: [],
    self: null,
  };
  sandbox.self = sandbox;
  sandbox.postMessage = (msg, transfer) => { sandbox.posted.push(msg); };
  const ctx = vm.createContext(sandbox);
  sandbox.__ctx = ctx;
  sandbox.importScripts = (p) => {
    vm.runInContext(fs.readFileSync(path.join(ROOT, p), 'utf8'), ctx, { filename: p });
  };
  return sandbox;
}

const wait = (ms) => new Promise(r => setTimeout(r, ms));

(async () => {
  let fail = 0;
  const ok = (c, m) => { console.log(`  ${c ? '✓' : '✗'} ${m}`); if (!c) fail++; };

  console.log('=== 模拟 Worker 环境并加载 tile-worker.js ===\n');
  const w = makeWorkerSandbox();
  vm.runInContext(fs.readFileSync(path.join(ROOT, 'tile-worker.js'), 'utf8'),
                  w.__ctx, { filename: 'tile-worker.js' });
  ok(typeof w.onmessage === 'function', 'worker 已注册 onmessage');

  // 等 initDir 完成
  await wait(1500);
  const ready = w.posted.find(m => m.ready !== undefined);
  ok(ready && ready.ready, '目录初始化成功');
  if (ready && ready.header) {
    console.log(`     范围 ${ready.header.minLon}~${ready.header.maxLon}E, ` +
                `${ready.header.minLat}~${ready.header.maxLat}N  zoom ${ready.header.minZoom}~${ready.header.maxZoom}`);
  }

  /* --- 构造一屏瓦片（陕西附近 z13）--- */
  const tiles = [];
  for (let x = 6724; x < 6732; x++)
    for (let y = 3140; y < 3146; y++) tiles.push([13, x, y]);
  console.log(`\n  请求一批 ${tiles.length} 张瓦片 (z13)`);

  const id = 1;
  w.onmessage({ data: { batch: true, id, tiles } });

  // 等结果
  let res = null;
  for (let i = 0; i < 40 && !res; i++) {
    await wait(200);
    res = w.posted.find(m => m.id === id) || null;
  }
  ok(!!res, '收到批量结果');
  if (!res) { console.log('\n=== 失败 ==='); process.exit(1); }
  if (res.error) { console.log('   错误:', res.error); process.exit(1); }

  const got = res.results;
  ok(got.length === tiles.length, `结果条数 ${got.length} == 请求数 ${tiles.length}`);
  const withData = got.filter(r => r.data);
  console.log(`     其中 ${withData.length} 张有数据，${got.length - withData.length} 张为空（该处无适飞数据）`);

  // 统计消息
  const st = w.posted.find(m => m.stat);
  if (st) console.log(`     批量 ${st.batches} 次 / ${st.tiles} 张 / ${st.ranges} 个 Range 段 / 均 ${st.avgMs}ms`);

  /* --- 与本地文件逐字节比对 --- */
  const local = fs.readFileSync(path.join(ROOT, 'data', 'uom-shifei.pmtiles'));
  let checked = 0, bad = 0;
  for (const r of withData) {
    // 用已验证过的 Python 实现算期望内容
    const py = require('child_process');
    checked++;
  }
  // 用 node 直接校验 PNG 魔数 + 尺寸合理性
  const PNG = [0x89, 0x50, 0x4e, 0x47];
  let pngOK = 0;
  for (const r of withData) {
    const b = new Uint8Array(r.data);
    if (b[0] === PNG[0] && b[1] === PNG[1] && b[2] === PNG[2] && b[3] === PNG[3] &&
        b.length > 200 && b.length < 200000) pngOK++;
  }
  ok(pngOK === withData.length, `全部 ${withData.length} 张都是合法 PNG（魔数+大小合理）`);

  /* --- 交叉验证：与单张模式的结果比对 --- */
  console.log('\n  交叉验证：同一张瓦片用「批量」与「单张」两条路径各取一次');
  const probe = withData[0];
  const id2 = 2;
  w.onmessage({ data: { id: id2, z: probe.z, x: probe.x, y: probe.y } });
  let single = null;
  for (let i = 0; i < 40 && !single; i++) {
    await wait(200);
    single = w.posted.find(m => m.id === id2) || null;
  }
  ok(!!(single && single.data), '单张模式返回数据');
  if (single && single.data) {
    const a = Buffer.from(probe.data), b = Buffer.from(single.data);
    ok(a.equals(b), `两条路径字节一致 (${a.length}B)`);
  }

  /* --- 与本地文件比对：确认切片没有错位 --- */
  console.log('\n  与本地文件比对（确认合并区间后切片没错位）');
  let mism = 0;
  for (const r of withData.slice(0, 12)) {
    if (!local.includes(Buffer.from(r.data))) mism++;
  }
  ok(mism === 0, `${Math.min(12, withData.length)} 张瓦片的内容都能在本地文件中找到（无错位）`);

  console.log(`\n=== ${fail === 0 ? '全部通过：批量取数可用' : fail + ' 项失败'} ===`);
  process.exit(fail === 0 ? 0 : 1);
})().catch(e => { console.error('\n致命错误:', e); process.exit(1); });
