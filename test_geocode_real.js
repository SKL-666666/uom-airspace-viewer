/* 用 index.html 里【真实的】geoTianditu 跑一遍线上真实返回的结构。
 *
 * 起因（两连错，都被这一个用例钉住）：
 *   ① 响应里坐标叫 lonlat（"经度,纬度" 合并字符串），我只认分开的 lon/lat，
 *      8 条 POI 全被丢掉；
 *   ② 更致命的是我写 `if (cndesc) throw` —— 而成功时代码 1000 的 cndesc
 *      恰好是"服务正常"，于是【任何一次成功返回都会在读取 POI 之前被抛掉】。
 *      症状就是"接口说服务正常（1000），却一个字都搜不出来"。
 *
 * 这个用例把用户的真实响应形状 + 真实解析代码一起跑，两处都会被打回原形。
 * 替身只替掉网络那一层（fetch），解析逻辑一个不替。
 *
 * 用法: node test_geocode_real.js
 */
const vm = require('vm');
const { loadScript, extractFn } = require('./test_util');

const script = loadScript();
const parts = ['pickLonLat', 'pickNum', 'parseCoord', 'tdtPostStr', 'geoTianditu']
  .map(n => extractFn(script, n));
/* parseTdtPayload 由 geoTianditu 内部调用，必须一起求值 ——
   否则沙箱里没有它，geoTianditu 一进去就抛错（我就这么踩过一次）。 */
const srcParse = extractFn(script, 'parseTdtPayload');
if (!srcParse){ console.error('✗ 找不到 parseTdtPayload'); process.exit(1); }
parts.push(srcParse);
parts.forEach((p, i) => { if (!p) { console.error('✗ 提取失败 idx=' + i); process.exit(1); } });

/* 照抄用户给的真实返回：字段名、8 项、lonlat 合并字符串 */
const REAL = {
  count: 958,
  prompt: [{ type: 0, admins: '北京市' }],
  pois: [
    { address: '北京市顺义区', phone: '', poiType: 0, name: '首都机场',
      source: '0', hotPointID: '', lonlat: '116.406621,40.072647' },
    { address: '北京市朝阳区', phone: '', poiType: 0, name: '首都机场T3',
      source: '0', hotPointID: '', lonlat: '116.585000,40.053000' },
    { address: '北京市东城区', phone: '', poiType: 0, name: '首都机场巴士站',
      source: '0', hotPointID: '', lonlat: '116.418000,39.949000' },
    { address: '北京市', phone: '', poiType: 0, name: '首都机场线',
      source: '0', hotPointID: '', lonlat: '116.442000,39.964000' },
    { address: '北京市', phone: '', poiType: 0, name: '首都机场公安局',
      source: '0', hotPointID: '', lonlat: '116.590000,40.060000' },
    { address: '北京市', phone: '', poiType: 0, name: '首都机场海关',
      source: '0', hotPointID: '', lonlat: '116.588000,40.058000' },
    { address: '北京市', phone: '', poiType: 0, name: '首都机场医院',
      source: '0', hotPointID: '', lonlat: '116.583000,40.056000' },
    { address: '北京市', phone: '', poiType: 0, name: '首都机场宾馆',
      source: '0', hotPointID: '', lonlat: '116.581000,40.055000' },
  ],
  resultType: 1,
  lineData: [],
  keyWord: '首都机场',
  status: { cndesc: '服务正常', infocode: 1000 },
};

const calls = [];
/* 注意：geoTianditu 现在依赖这些宿主能力，替身少一个它就会抛错。
   之前就因为替身不全（缺 performance）让用例失败 —— 那不是我代码的错，
   而是测试环境没铺全。所以这里一次列齐。 */
const sandbox = {
  console: console, Math: Math, isFinite: isFinite, parseFloat: parseFloat,
  performance: { now: () => Date.now() },
  AbortController: (typeof AbortController !== 'undefined') ? AbortController : undefined,
  setTimeout: setTimeout, clearTimeout: clearTimeout,
  navigator: { onLine: true },
  encodeURIComponent: encodeURIComponent,
  report: () => {},
  tdtLastCount: 0,
  TDT_PARAM_FALLBACK: { level: 12, mapBound: '73.5,3.8,135.1,53.6' },
  pickNum: null,
  map: { getZoom: () => 10, getBounds: () => ({
    getWest: () => 114.87, getSouth: () => 38.13,
    getEast: () => 117.49, getNorth: () => 39.26 }) },
  CONFIG: { keys: { tdt: 'FAKE_TK_32_CHARS________________' } },
  /* 关键的替身：把请求拦下来，直接返回用户那份真实响应 ——
     这样不碰网络也能验证"解析这一段"是否正确 */
  fetch: async (url) => {
    calls.push(url);
    return { ok: true, status: 200, text: async () => JSON.stringify(REAL) };
  },
};
vm.createContext(sandbox);
vm.runInContext(parts.join('\n'), sandbox, { filename: 'real.js' });

(async () => {
  let fail = 0;
  const ok = (c, m, e) => { if (c) console.log('  ✓ ' + m); else { fail++; console.log('  ✗ ' + m + (e ? '  ' + e : '')); } };

  console.log('=== 用真实解析代码跑线上真实返回（防回归）===\n');
  const out = await sandbox.geoTianditu('首都机场');

  ok(calls.length >= 1, '真的发起了请求（走的是 geoTianditu 本身）');
  ok(out.length === 8, '解析出 8 条 POI（期望 8，实际 ' + out.length + '）');
  const first = out[0] || {};
  ok(first.name === '首都机场', 'name 正确：' + first.name);
  ok(Math.abs(first.lon - 116.406621) < 1e-6, 'lon 正确：' + first.lon + '（不是 40.07）');
  ok(Math.abs(first.lat - 40.072647) < 1e-6, 'lat 正确：' + first.lat + '（不是 116.4）');
  ok(first.addr === '北京市顺义区', 'address 带出来了：' + first.addr);
  ok(out.every(p => Math.abs(p.lon) > 90 && Math.abs(p.lon) < 136),
     '全部 8 条的经度都落在 90~136（经纬没有写反）');
  ok(out.every(p => Math.abs(p.lat) < 54), '全部 8 条的纬度都 < 54');

  /* 反向控制：如果解析仍然只认 lon/lat，这里会是 0 条 */
  ok(out.length > 0, '反向控制：解析结果非空（修复前这里恒为 0 条）');

  console.log('\n' + (fail === 0 ? '=== 通过：这份真实返回已被正确解析 ==='
                                 : '=== ' + fail + ' 项失败 ==='));
  process.exit(fail === 0 ? 0 : 1);
})();
