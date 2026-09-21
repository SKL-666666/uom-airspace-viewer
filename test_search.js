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
vm.runInContext(fnPost + '\n' + fnParse + '\n' + fnLonLat + '\n' + fnPickNum,
  sandbox, { filename: 'search.js' });

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

console.log('\n— 2. 视野取不到时，level 退回用缩放级别 —');
{
  /* level 的首选来源是 mapBound 的跨度（见第 8 节）：地图缩放级别和实际可见
     范围在中文底图上经常对不上。只有拿不到视野时才退回用缩放。
     两个来源都要能工作，也都要夹在 1~18。 */
  const saved = fakeMap.getBounds;
  fakeMap.getBounds = function(){ throw new Error('还没初始化'); };

  fakeMap._z = 5;  ok(post('x').level === 5, '拿不到视野时：缩放 5 -> level 5');
  fakeMap._z = 18; ok(post('x').level === 18, '缩放 18 -> level 18');
  fakeMap._z = 22; ok(post('x').level === 18, '缩放 22 被夹到 18（值域上限）');
  /* 缩放 0 是合法值但 falsy —— 用 || 兜底会把它误改成 12，这条就是防它的 */
  fakeMap._z = 0;  ok(post('x').level === 1, '缩放 0 被夹到 1（不是被误设成 12）');

  fakeMap.getBounds = saved;
  fakeMap._z = 12;
  /* 有视野时必须优先按 mapBound 推 level，而不是照抄缩放级别 */
  fakeMap._b = makeBounds(63.0, 14.7, 147.0, 52.0);
  ok(post('x').level !== 12,
     '有视野时不再照抄缩放级别 12（实际 level ' + post('x').level + '）');
  fakeMap._b = makeBounds(115.9, 39.5, 116.9, 40.3);
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

console.log('\n— 8. level 必须与 mapBound 自洽 —');
{
  /* 实测到过一次矛盾组合：level 5 配 mapBound 63.0,14.7,147.0,52.1（东亚整片）。
     北京(116.4,39.9) 并不在那个范围里 —— 能搜到纯属运气。原因是我把地图缩放
     级别直接当 level，而中文底图在缩放 5 时的可见范围远大于
     '缩放级别 × 视口尺寸'。现在 level 由 mapBound 跨度反推。
   */
  const cases = [
    [{ west: 114.87, south: 38.13, east: 117.49, north: 39.26 }, '城市级视野'],
    [{ west: 63.0,   south: 14.7,  east: 147.0,  north: 52.0 }, '东亚整片视野'],
    [{ west: 73.0,   south: 3.8,   east: 135.1,  north: 53.6 }, '全国视野'],
  ];
  const levels = [];
  for (const [b, label] of cases){
    fakeMap._b = makeBounds(b.west, b.south, b.east, b.north);
    const p = post('x');
    levels.push(p.level);
    ok(p.level >= 1 && p.level <= 18, label + ' -> level ' + p.level + ' 在值域内');
    /* 自洽性：按 level 算出来的经度分辨率，不能比视野跨度还粗 */
    const spanLon = b.east - b.west;
    const cellAtLevel = 360 / Math.pow(2, p.level);
    ok(cellAtLevel <= spanLon * 1.5,
       label + '：level ' + p.level + ' 的格子 ' + cellAtLevel.toFixed(2)
       + '° 与跨度 ' + spanLon.toFixed(2) + '° 相称');
  }
  /* 单调性：视野经度跨度越大，level 越小。
     注意不能按数组下标比 —— 上面三个用例里"东亚整片"的经度跨度(84°)
     比"全国"(62.1°)还大，所以它的 level 更小是【正确】的。
     测试数据本身要按跨度排序，否则是在测一个不成立的前提。 */
  const spans = cases.map(([b]) => b.east - b.west);
  const bySpan = cases.map((c, i) => ({ span: spans[i], level: levels[i] }))
                      .sort((x, y) => x.span - y.span);
  let mono = true;
  for (let i = 1; i < bySpan.length; i++){
    if (!(bySpan[i].level <= bySpan[i - 1].level)) mono = false;
  }
  ok(mono, '跨度越大 level 越小：' +
     bySpan.map(v => v.span.toFixed(1) + '°/' + v.level).join('  '));
  ok(levels[0] === Math.max.apply(null, levels),
     '最小视野拿到最大 level（城市级 ' + levels[0] + '）');
  fakeMap._b = makeBounds(115.9, 39.5, 116.9, 40.3);
}

console.log('\n— 10. pickLonLat 兜底：字段名没见过也要能认 —');
{
  /* 实测：同一个接口，关键词「首都机场」返回的条目带 lonlat 能解析，
     而命中数更多的宽关键词，条目一条都解析不出来 —— 说明那种条目用了
     别的字段名。写死字段名总会漏，所以留一条按【内容】认的路。 */
  const r1 = pickLonLat({ name:'某地', whateverField:'116.406,40.072' });
  ok(!!r1 && Math.abs(r1.lon - 116.406) < 1e-6, '未知字段名的 "经,纬" 字符串');
  const r2 = pickLonLat({ name:'某地', someArray:[116.406, 40.072] });
  ok(!!r2 && Math.abs(r2.lat - 40.072) < 1e-6, '未知字段名的数组');
  const r3 = pickLonLat({ name:'某地', pair:'40.072,116.406' });
  ok(!!r3 && Math.abs(r3.lon - 116.406) < 1e-6, '顺序反了也能纠正（|>90 的是经度）');
  /* 关键：不能瞎认。这些都不是坐标，必须返回 null，否则会把无关数值当位置 */
  ok(pickLonLat({ name:'某地', count:'2196' }) === null, '单个数字不算坐标');
  ok(pickLonLat({ name:'某地', code:'1,2' }) === null, '不在中国范围内的数字对不算坐标');
  ok(pickLonLat({ name:'某地', tel:'010,8888' }) === null, '号码不算坐标');
  ok(pickLonLat({ name:'某地', note:'12.5,13.7' }) === null, '境外范围的数字对不算坐标');
  /* 已知字段名优先，且不受范围限制（境外 POI 也要能用已知字段解析） */
  const r4 = pickLonLat({ lonlat:'139.7,35.6' });
  ok(!!r4 && Math.abs(r4.lat - 35.6) < 1e-6, '已知字段名不受境内范围限制（境外点也能用）');
}

process.exit(A.done());