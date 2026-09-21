/* 地名搜索相关的单元测试。
 *
 * 起因：线上实测返回
 *   {"count":0,"resultType":1,"status":{"cndesc":"缺少参数：level","infocode":2003}}
 * —— 天地图 /v2/search 的搜索空间必须被限定，只给 keyWord + queryType 会被拒。
 * 这类"少传一个参数就整个功能不可用"的问题，如果没有测试盯着，改了别处很容易
 * 又漏掉，而且症状是"搜不出来"，跟参数毫无字面关系。
 *
 * 用法: node test_search.js [html文件]
 */
const vm = require('vm');
const { loadScript, extractFn, makeAsserter } = require('./test_util');

const script = loadScript(process.argv[2]);

const fnPost = extractFn(script, 'tdtPostStr');
const fnParse = extractFn(script, 'parseCoord');
const fnLonLat = extractFn(script, 'pickLonLat');
const fnPickNum = extractFn(script, 'pickNum');
if (!fnPost || !fnParse || !fnLonLat || !fnPickNum) {
  console.error('✗ 找不到 tdtPostStr / parseCoord / pickLonLat / pickNum');
  process.exit(1);
}

/* tdtPostStr 依赖地图视野：给个可控替身，顺便验证"视野真的被用上了" */
/* 替身要按 Leaflet LatLngBounds 的真实接口来做：是 getWest() 这类【方法】，
   不是 west 这样的属性。上一版替身只给了属性，于是代码里 b.getWest() 抛错、
   被 try/catch 吞掉，测试就以为"mapBound 本来就没带"—— 替身不忠实会把 bug 藏起来。 */
function makeBounds(w, s, e, n){
  return { getWest: () => w, getSouth: () => s, getEast: () => e, getNorth: () => n };
}
const fakeMap = {
  _b: makeBounds(115.9, 39.5, 116.9, 40.3),
  _z: 12,
  getBounds: function () { return fakeMap._b; },
  getZoom: function () { return fakeMap._z; },
};
/* 直接取 tdtPostStr 里用到的那段（它引用了 map / CONFIG 等外部名字），
   这里只把 map 注进去即可 */
const TDT_PARAM_FALLBACK = {
  level: 12, mapBound: '73.5,3.8,135.1,53.6', specify: '116.39,39.90',
  dataTypes: 'poi', queryType: 1, start: 0, count: 8,
};

const sandbox = {
  console: console,
  Math: Math,
  map: fakeMap,
  TDT_PARAM_FALLBACK: TDT_PARAM_FALLBACK,
};
vm.createContext(sandbox);
/* 两个函数都要真正求值进沙箱 —— extractFn 返回的是【源码字符串】，
   只取出不执行的话，下面拿到的就是字符串而不是函数。 */
vm.runInContext(fnPost + '\n' + fnParse + '\n' + fnLonLat + '\n' + fnPickNum, sandbox, { filename: 'search.js' });

const A = makeAsserter('地名搜索参数与坐标解析正确');
const ok = A.ok;
const post = sandbox.tdtPostStr;
const parseCoord = sandbox.parseCoord;
const pickLonLat = sandbox.pickLonLat;

console.log('=== 地名搜索测试 ===\n');
console.log('— 1. 天地图 postStr 必须限定搜索空间（这次线上就是缺这个）—');
{
  const b = post('首都机场');
  ok(b.keyWord === '首都机场', 'keyWord 正确');
  ok(b.queryType === 1, 'queryType=1（普通搜索）');
  ok(typeof b.level === 'number' && b.level >= 1 && b.level <= 18,
     'level 在 1~18：' + b.level);
  ok(typeof b.mapBound === 'string' && b.mapBound.split(',').length === 4,
     'mapBound 是 4 个数字：' + b.mapBound);
  /* 关键断言：不能只有一个 keyWord。缺 level/mapBound 就会被接口拒。 */
  ok(b.level !== undefined || b.mapBound !== undefined,
     'level 与 mapBound 至少给了一个（否则接口报 infocode 2003）');
}

console.log('\n— 2. level 跟随当前缩放（不是写死的）—');
{
  fakeMap._z = 5;  ok(post('x').level === 5, '缩放 5 -> level 5');
  fakeMap._z = 18; ok(post('x').level === 18, '缩放 18 -> level 18');
  fakeMap._z = 22; ok(post('x').level === 18, '缩放 22 被夹到 18（值域上限）');
  /* 缩放 0 是合法值但 falsy —— 用 || 兜底会把它误改成 12，这条就是防它的 */
  fakeMap._z = 0;  ok(post('x').level === 1, '缩放 0 被夹到 1（不是被误设成 12）');
  fakeMap._z = 12;
}

console.log('\n— 3. mapBound 取自当前视野 —');
{
  fakeMap._b = makeBounds(100.123456, 20.5, 110.9, 30.1);
  const mb = post('x').mapBound.split(',').map(Number);
  ok(Math.abs(mb[0] - 100.123456) < 1e-6, '西边界带上：' + mb[0]);
  ok(Math.abs(mb[3] - 30.1) < 1e-6, '北边界带上：' + mb[3]);
  ok(mb[0] < mb[2] && mb[1] < mb[3], '顺序是 minLon,minLat,maxLon,maxLat');
  fakeMap._b = makeBounds(115.9, 39.5, 116.9, 40.3);
}

console.log('\n— 4. 视野取不到时不能把整个请求弄坏 —');
{
  const saved = fakeMap.getBounds;
  fakeMap.getBounds = function(){ throw new Error('还没初始化'); };
  let b = null;
  try { b = post('x'); } catch(e){ ok(false, '取不到视野时不应抛错', e.message); }
  if (b){
    ok(b.keyWord === 'x', '仍然返回了可用的 postStr');
    ok(b.mapBound === undefined, '拿不到视野就不带 mapBound（由 level 兜底）');
    ok(b.level !== undefined, 'level 仍在');
  }
  fakeMap.getBounds = saved;
}

console.log('\n— 5. 自愈：从接口原话里抠出缺的参数名 —');
{
  /* 这条正则就是"缺什么补什么"的依据，必须能认中英文冒号和空格 */
  const re = /缺少参数[：:]\s*([A-Za-z]+)/;
  const cases = [
    ['缺少参数：level', 'level'],
    ['缺少参数:level', 'level'],
    ['缺少参数： mapBound', 'mapBound'],
    ['缺少参数：dataTypes', 'dataTypes'],
  ];
  for (const [desc, want] of cases) {
    const got = (desc.match(re) || [])[1];
    ok(got === want, `"${desc}" -> ${got}`);
  }
  /* 反向控制：其它错误不该被误判成缺参数 */
  ok(!/缺少参数/.test('非法key'), '权限类错误不会被当成"缺参数"');
  ok(!/缺少参数/.test('key无效或过期'), 'key 过期同理');
  for (const k of ['level', 'mapBound', 'specify', 'dataTypes', 'queryType']){
    ok(TDT_PARAM_FALLBACK[k] !== undefined, `兜底表里有 ${k}`);
  }
}

console.log('\n— 6. 坐标解析（离线检索的第一路）—');
{
  const cases = [
    ['39.9087,116.3975', 39.9087, 116.3975],       // 纬度在前
    ['116.3975,39.9087', 39.9087, 116.3975],       // 经度在前（>60 判定为经度）
    ['39.9087 116.3975', 39.9087, 116.3975],       // 空格分隔
    ['39.9087，116.3975', 39.9087, 116.3975],      // 全角逗号
    ['  39.9087, 116.3975  ', 39.9087, 116.3975],  // 首尾空白
  ];
  for (const [txt, lat, lon] of cases){
    const c = parseCoord(txt);
    ok(c && Math.abs(c.lat - lat) < 1e-6 && Math.abs(c.lon - lon) < 1e-6,
       `"${txt}" -> ${c ? c.lat + ',' + c.lon : 'null'}`);
  }
  /* 不该被当成坐标的输入 */
  for (const txt of ['首都机场', '39.9', 'abc,def', '39.9,', '北京 116.4']){
    ok(parseCoord(txt) === null, `"${txt}" 不解析为坐标`);
  }
  /* 越界要挡住 */
  ok(parseCoord('91,116') === null, '纬度 91 超范围 -> null');
  ok(parseCoord('39.9,181') === null, '经度 181 超范围 -> null');
}

console.log('\n— 7. pickLonLat：吃下天地图真实返回的 lonlat 合并字段 —');
{
  /* 这段形状照抄用户线上真实返回：
       {"count":958,"pois":[{"address":...,"name":...,"lonlat":"116.4,39.9"},...],
        "resultType":1,"status":{"cndesc":"服务正常","infocode":1000}}
     教训：我只认 lon/lat 分开的字段，导致接口给了 8 条 POI 却一条都解析不出来，
     症状和“搜不到”完全一样。所以把真实形状钉成用例。
   */
  const realPoi = {
    address: '北京市顺义区', phone: '', poiType: 0, name: '首都机场',
    source: '0', hotPointID: '', lonlat: '116.406621,40.072647',
  };
  const ll = pickLonLat(realPoi);
  ok(!!ll, 'lonlat 合并字段能被解析出来');
  ok(ll && Math.abs(ll.lon - 116.406621) < 1e-6, '经度取对了：' + (ll && ll.lon));
  ok(ll && Math.abs(ll.lat - 40.072647) < 1e-6, '纬度取对了：' + (ll && ll.lat));
  ok(ll && Math.abs(ll.lon) > 90, '经度落在 |lon|>90 的合理区间（没被当成纬度）');
  ok(pickLonLat({ location: '121.47,31.23' }).lon === 121.47, '高德 location 合并字段');
  ok(pickLonLat({ lonlat: [116.4, 39.9] }).lat === 39.9, '数组形态 [lon,lat]');
  ok(pickLonLat({ lnglat: '39.9,116.4' }).lon === 116.4, '内容明显是 纬度,经度 时能自动纠正');
  ok(pickLonLat({ lon: 116.4, lat: 39.9 }).lon === 116.4, '分开的 lon/lat 仍然支持');
  ok(pickLonLat({ center: { lon: 116.4, lat: 39.9 } }).lat === 39.9, '嵌套对象形态');
  ok(pickLonLat({ name: '首都机场', address: '北京' }) === null, '没有坐标 -> null');
  ok(pickLonLat({ lonlat: 'abc' }) === null, '畸形 lonlat -> null');
  ok(pickLonLat({}) === null, '空对象 -> null');
  ok(pickLonLat(null) === null, 'null -> null');
}

process.exit(A.done());
