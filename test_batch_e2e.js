/* 端到端测量：客户端攒批 + Worker 区间合并，到底减少多少 HTTP 请求。
 *
 * 做法：在 Node 里把「客户端攒批代码」和「Worker 代码」都跑起来，
 * 用包装过的 fetch 统计真实请求数，再与逐张请求的旧方式对比。
 * 同时校验取回的瓦片内容正确。
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const BASE = 'http://127.0.0.1:8080';
const ROOT = __dirname;
const wait = (ms) => new Promise(r => setTimeout(r, ms));

/* ---- 统计真实 HTTP 请求 ---- */
let reqCount = 0, bytesDown = 0;
const realFetch = async (url, init) => {
  reqCount++;
  const r = await fetch(url, init);
  const buf = await r.arrayBuffer();
  bytesDown += buf.byteLength;
  return new Response(buf, { status: r.status, statusText: r.statusText, headers: r.headers });
};

/* ---- 启动 Worker 沙箱 ---- */
function makeWorker() {
  const sb = {
    DecompressionStream, Blob, Response, Request, Headers, AbortController,
    URL, TextDecoder, TextEncoder, console, setTimeout, clearTimeout,
    Promise, Map, Set, Array, Object, Math, JSON, Number, String,
    DataView, Uint8Array, ArrayBuffer, Error, TypeError, performance,
    navigator: { userAgent: 'Mozilla/5.0 (Windows NT 10.0) Chrome/120.0' },
    fetch: (input, init) => realFetch(
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

/* ---- 客户端攒批（与 index.html 中一致）---- */
function makeClient(worker) {
  let seq = 0;
  const batchPending = new Map();
  const inflight = new Map();
  let timer = null;
  function flush() {
    timer = null;
    if (!batchPending.size) return;
    const items = [], resolvers = [];
    for (const rec of batchPending.values()) {
      items.push([rec.z, rec.x, rec.y]); resolvers.push(rec.resolvers);
    }
    batchPending.clear();
    const id = ++seq;
    inflight.set(id, resolvers);
    worker.postMessage({ batch: true, id, tiles: items });
    client.sent++;
  }
  const client = {
    sent: 0,
    get(z, x, y) {
      return new Promise((resolve, reject) => {
        const key = z + '/' + x + '/' + y;
        let rec = batchPending.get(key);
        if (!rec) { rec = { z, x, y, resolvers: [] }; batchPending.set(key, rec); }
        rec.resolvers.push({ resolve, reject });
        if (!timer) timer = setTimeout(flush, 0);
      });
    },
    deliver(m) {
      if (!m.results) return;
      const rs = inflight.get(m.id);
      if (!rs) return;
      inflight.delete(m.id);
      m.results.forEach((r, i) => {
        const list = rs[i]; if (!list) return;
        for (const res of list) {
          if (r && r.error) res.reject(new Error(r.error));
          else res.resolve(r ? r.data : null);
        }
      });
    },
  };
  return client;
}

(async () => {
  let fail = 0;
  const ok = (c, m) => { console.log(`  ${c ? '✓' : '✗'} ${m}`); if (!c) fail++; };

  const worker = makeWorker();
  const client = makeClient(worker);
  const pending = [];
  const origPost = worker.postMessage;
  worker.postMessage = (m) => { origPost(m); if (m.batch) pending.push(m); };

  // 等目录就绪
  await wait(1500);
  ok(worker.posted.some(m => m.ready), 'Worker 目录就绪');

  /* ---- 场景：一屏 z13 瓦片（陕西附近）---- */
  const tiles = [];
  for (let x = 6724; x < 6732; x++)
    for (let y = 3140; y < 3146; y++) tiles.push([13, x, y]);

  console.log(`\n  场景：一屏 ${tiles.length} 张瓦片 (z13)`);
  reqCount = 0; bytesDown = 0;

  const proms = tiles.map(t => client.get(t[0], t[1], t[2]));
  await wait(30);
  ok(client.sent === 1, `客户端只发了 ${client.sent} 个 Worker 消息`);

  // 驱动 Worker 处理
  for (const m of pending) {
    reqCount = 0; bytesDown = 0;                  // 重置以统计这一批
    worker.onmessage({ data: m });                // 驱动 Worker 处理
    let out = null;
    for (let i = 0; i < 100 && !out; i++) {
      await wait(100);
      // 注意：拦截器把「发出的请求」也记进了 posted，必须排除掉，
    // 否则会匹配到请求本身而不是回包（这里踩过）
    out = worker.posted.find(x => x.id === m.id && x.results);
    }
    if (out) client.deliver(out);
  }

  const vals = await Promise.all(proms);
  const withData = vals.filter(v => v).length;

  console.log(`\n  ── 结果 ──`);
  ok(reqCount > 0, `本批真实 HTTP 请求数：${reqCount}（逐张方式需 ${tiles.length} 个）`);
  ok(reqCount <= tiles.length / 2,
     `请求数降到 ${(tiles.length / reqCount).toFixed(1)}x`);
  console.log(`     传输字节：${(bytesDown / 1024).toFixed(1)} KB`);
  ok(vals.length === tiles.length, `全部 ${vals.length} 个 Promise 完成`);
  console.log(`     其中 ${withData} 张有数据，${vals.length - withData} 张为空`);

  // 校验内容
  const PNG = [0x89, 0x50, 0x4E, 0x47];
  let pngOK = 0;
  const local = fs.readFileSync(path.join(ROOT, 'data', 'uom-shifei.pmtiles'));
  let inLocal = 0;
  for (const v of vals) {
    if (!v) continue;
    const b = new Uint8Array(v);
    if (b[0]===PNG[0] && b[1]===PNG[1] && b[2]===PNG[2] && b[3]===PNG[3]) pngOK++;
    if (local.includes(Buffer.from(v))) inLocal++;
  }
  ok(pngOK === withData, `${withData} 张有数据的都是合法 PNG`);
  ok(inLocal === withData, `${withData} 张内容都能在本地文件中找到（无错位）`);

  const st = worker.posted.find(m => m.stat);
  if (st) console.log(`     Worker 统计：${st.batches} 批 / ${st.tiles} 张 / ${st.ranges} 个 Range 段`);

  console.log(`\n=== ${fail === 0 ? '全部通过' : fail + ' 项失败'} ===`);
  process.exit(fail === 0 ? 0 : 1);
})().catch(e => { console.error('致命错误:', e); process.exit(1); });
