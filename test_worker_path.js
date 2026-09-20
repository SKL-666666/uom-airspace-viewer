/* 在 Node 里复现 tile-worker.js 的核心逻辑，验证 Worker 代码路径可用。
 *
 * 关键点：lib/pmtiles.js 是 `var pmtiles = (()=>{...})()` 形式，没有 UMD 包装。
 *   - 浏览器 <script>      -> window.pmtiles
 *   - Worker importScripts -> self.pmtiles（顶层 var 挂到全局）
 *   - Node require         -> 拿不到（模块作用域）
 * 所以必须用 vm 在「全局作用域」里执行，才能真实还原 importScripts 的行为。
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const libCode = fs.readFileSync(path.join(__dirname, 'lib', 'pmtiles.js'), 'utf8');
const URL_ = 'http://127.0.0.1:8080/data/uom-shifei.pmtiles';

(async () => {
  let fail = 0;
  const ok = (c, m) => { console.log(`  ${c ? '✓' : '✗'} ${m}`); if (!c) fail++; };

  console.log('=== 模拟 tile-worker.js 运行环境（importScripts 全局作用域）===\n');

  ok(typeof fetch === 'function', 'Node 提供 fetch');
  ok(typeof DecompressionStream === 'function', 'Node 提供 DecompressionStream');

  /* 构造一个尽量贴近 Worker 全局的上下文 */
  const sandbox = {
    fetch, DecompressionStream, Response, Request, Headers, AbortController,
    Blob, URL, TextDecoder, TextEncoder, console,
    setTimeout, clearTimeout, Promise, Map, Set, Array, Object, Math, JSON,
    navigator: { userAgent: 'Worker-sim' },
    self: null,
  };
  sandbox.self = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);

  /* 等同于 importScripts('lib/pmtiles.js') */
  vm.runInContext(libCode, sandbox, { filename: 'pmtiles.js' });
  const pmtiles = sandbox.pmtiles;
  ok(!!pmtiles, '全局 pmtiles 已定义（importScripts 行为）');
  ok(typeof pmtiles.PMTiles === 'function', 'PMTiles 构造函数可用');
  ok(typeof pmtiles.SharedPromiseCache === 'function', 'SharedPromiseCache 可用');
  if (!pmtiles || typeof pmtiles.PMTiles !== 'function') {
    console.log('\n=== 库加载失败，中止 ===');
    process.exit(1);
  }

  const pm = new pmtiles.PMTiles(URL_, new pmtiles.SharedPromiseCache(1000));

  // 1. header
  let t = Date.now();
  const h = await pm.getHeader();
  const ms0 = Date.now() - t;
  ok(h.tileType === 2, `tileType=${h.tileType} (2=PNG)，header 耗时 ${ms0}ms`);
  ok(h.minZoom === 0 && h.maxZoom === 13, `zoom ${h.minZoom}~${h.maxZoom}`);
  console.log(`     bounds ${h.minLon}~${h.maxLon}E, ${h.minLat}~${h.maxLat}N`);

  // 2. 取一块已知存在的瓦片，校验 PNG 魔数
  t = Date.now();
  const r = await pm.getZxy(5, 25, 12);
  ok(!!(r && r.data), `getZxy(5,25,12) 成功，耗时 ${Date.now() - t}ms`);
  if (r && r.data) {
    const b = new Uint8Array(r.data);
    ok(b[0] === 0x89 && b[1] === 0x50 && b[2] === 0x4E && b[3] === 0x47,
       `PNG 魔数正确 ${Array.from(b.slice(0, 4)).join(',')}`);
    ok(r.data.byteLength > 500, `大小 ${r.data.byteLength}B`);
  } else {
    fail++;
  }

  // 3. 批量取（模拟一屏）
  t = Date.now();
  let got = 0, miss = 0;
  const jobs = [];
  for (let x = 22; x < 30; x++)
    for (let y = 10; y < 20; y++)
      jobs.push(pm.getZxy(5, x, y).then(v => { (v && v.data) ? got++ : miss++; }));
  await Promise.all(jobs);
  ok(got > 0, `批量 ${jobs.length} 块：命中 ${got}，无数据 ${miss}，耗时 ${Date.now() - t}ms`);

  // 4. 不存在的瓦片应返回空而不是抛错
  let emptyOK = false;
  try {
    const e = await pm.getZxy(13, 0, 0);
    emptyOK = !e || !e.data;
  } catch (err) { console.log('     抛错:', err.message); }
  ok(emptyOK, '不存在的瓦片返回空（未抛错）');

  console.log(`\n=== ${fail === 0 ? '全部通过：Worker 代码路径可用' : fail + ' 项失败'} ===`);
  process.exit(fail === 0 ? 0 : 1);
})().catch(e => { console.error('\n致命错误:', e); process.exit(1); });
