/* 坐标系换算的单元测试。
 *
 * 为什么必须测：这个换算直接决定"判定的是哪个点"。做错了界面上一片正常 ——
 * 标记还在鼠标点的位置，只是判定点悄悄偏了 300~600 米，边界附近足以得出
 * 相反结论。所以这里既测数值精度，也测几处"错了就一定会露馅"的性质。
 *
 * 被测代码（含 currentBaseCfg / currentBaseKind）全部从 index.html 现场切出，
 * 不做替身 —— 上一版用替身 currentBaseCfg 掩盖了"必须传参"这个点击即崩的 bug，
 * 这一版把真实调用链一起跑起来。
 *
 * 用法: node test_geoconv.js [html文件]   默认 index.html
 */
const vm = require('vm');
const { loadScript, extractFn, extractSection, makeAsserter } = require('./test_util');

const script = loadScript(process.argv[2]);

const geo = extractSection(script,
  '/* ---------------- 坐标系换算', '/* ---------------- 点击查询');
if (!geo) {
  console.error('✗ 找不到坐标系换算代码段 —— 节标题被改动了？请同步本测试的切片标记');
  process.exit(1);
}
const fnKind = extractFn(script, 'currentBaseKind');
const fnCfg = extractFn(script, 'currentBaseCfg');
if (!fnKind || !fnCfg) {
  console.error('✗ 找不到 currentBaseKind / currentBaseCfg');
  process.exit(1);
}

/* 真实依赖的替身：只给数据，不给逻辑。
   BASEMAP_MAP 里放几个典型坐标系，够覆盖分派的所有分支。 */
const BASEMAP_MAP = {
  tdt_vec:  { key: 'tdt_vec',  label: '天地图 · 矢量', crs: 'WGS84' },
  esri_img: { key: 'esri_img', label: 'Esri · 卫星',   crs: 'WGS84' },
  amap_vec: { key: 'amap_vec', label: '高德 · 矢量',   crs: 'GCJ-02' },
  tx_sat:   { key: 'tx_sat',   label: '腾讯 · 卫星',   crs: 'GCJ-02' },
  baidu_vec:{ key: 'baidu_vec',label: '百度 · 矢量',   crs: 'BD-09' },
  none:     { key: 'none',     label: '无底图',        crs: '-' },
};
const fakeSelect = { value: 'tdt_vec' };
const cfgArgs = [];                       // 记录 currentBaseCfg 实际收到的参数

const sandbox = {
  console: console,
  Math: Math,
  BASEMAP_MAP: BASEMAP_MAP,
  CONFIG: { custom: [{ key: 'u1', label: '自建', url: 'https://x/{z}/{x}/{y}', crs: undefined }] },
  document: {
    getElementById: function (id) { return id === 'baseSel' ? fakeSelect : null; },
  },
  /* 同一个数组引用放进沙箱：沙箱里的 currentBaseCfg 包装层往里 push，
     这里就能看到真实入参。 */
  cfgArgs: cfgArgs,
};
vm.createContext(sandbox);
vm.runInContext(
  geo + '\n' + fnCfg + '\n' + fnKind +
  /* 包一层记录入参：currentBaseCfg 内部直接调 kind.indexOf，收到 undefined 会抛错，
     这个 bug 上轮就是被宽松替身掩盖过去的。这里替它挡一下（返回 {}），
     好让下面的断言报出人话而不是一段栈。 */
  '\nvar _origCfg = currentBaseCfg;' +
  '\ncurrentBaseCfg = function(kind){' +
  '\n  cfgArgs.push(typeof kind);' +
  '\n  if (typeof kind !== "string") return {};' +
  '\n  return _origCfg(kind);' +
  '\n};',
  sandbox, { filename: 'geoconv.js' });

const {
  wgs84ToGcj02, gcj02ToWgs84, gcj02ToBd09, bd09ToGcj02,
  wgs84ToBd09, bd09ToWgs84, outOfChina, mapToWgs, wgsToMap,
  currentBaseCrs, currentBaseKind,
} = sandbox;

const A = makeAsserter('坐标系换算可用');
const ok = A.ok;
function hav(a, b) {
  const R = 6371008.8, rad = Math.PI / 180;
  const dLat = (b[0] - a[0]) * rad, dLon = (b[1] - a[1]) * rad;
  const la1 = a[0] * rad, la2 = b[0] * rad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(la1) * Math.cos(la2) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

console.log('=== 坐标系换算测试 ===\n');
console.log('— 1. 国内判定 —');
ok(outOfChina(39.9087, 116.3975) === false, '北京 在国境内');
ok(outOfChina(30.6, 104.06) === false, '成都 在国境内');
ok(outOfChina(35.68, 139.76) === true, '东京 在国境外');
ok(outOfChina(40.71, -74.01) === true, '纽约 在国境外');

console.log('\n— 2. 境外必须原样返回（不加密）—');
{
  const t = wgs84ToGcj02(35.68, 139.76);
  ok(t[0] === 35.68 && t[1] === 139.76, '东京 wgs84ToGcj02 无变化');
  const n = gcj02ToWgs84(40.71, -74.01);
  ok(n[0] === 40.71 && n[1] === -74.01, '纽约 gcj02ToWgs84 无变化');
}

console.log('\n— 3. 偏移量必须在合理区间（错常数/错符号会立刻露馅）—');
const CITIES = [
  ['北京', 39.9087, 116.3975], ['上海', 31.2304, 121.4737],
  ['广州', 23.1291, 113.2644], ['成都', 30.5728, 104.0668],
  ['乌鲁木齐', 43.8256, 87.6168], ['哈尔滨', 45.8038, 126.5349],
  ['三亚', 18.2528, 109.5119], ['拉萨', 29.6520, 91.1721],
];
for (const [name, lat, lon] of CITIES) {
  const g = wgs84ToGcj02(lat, lon);
  const d = hav([lat, lon], g);
  ok(d > 150 && d < 900, `${name} 偏移 ${d.toFixed(1)} m 在 150~900m 内`);
}

console.log('\n— 4. 正反换算必须互为逆（迭代解算器的核心保证）—');
for (const [name, lat, lon] of CITIES) {
  const g = wgs84ToGcj02(lat, lon);
  const back = gcj02ToWgs84(g[0], g[1]);
  const err = hav([lat, lon], back);
  ok(err < 0.01, `${name} 往返误差 ${(err * 1000).toFixed(4)} mm < 10mm`);
}
{
  const g = [39.9145, 116.4036];
  const w = gcj02ToWgs84(g[0], g[1]);
  const back = wgs84ToGcj02(w[0], w[1]);
  ok(hav(g, back) < 0.01, 'GCJ->WGS->GCJ 闭合（' + (hav(g, back) * 1000).toFixed(4) + ' mm）');
}

console.log('\n— 5. BD-09 的固有偏移 —');
{
  const g = [39.9087, 116.3975];
  const b = gcj02ToBd09(g[0], g[1]);
  ok(Math.abs((b[1] - g[1]) - 0.0065) < 0.002, '经度增量接近 +0.0065');
  ok(Math.abs((b[0] - g[0]) - 0.0060) < 0.002, '纬度增量接近 +0.0060');

  /* 公开的 bd09ToGcj02 反算式并不精确互逆（实测残差约 5 厘米）。这里用
     "独立数值反演"当真值来量它 —— 用固定点迭代解出 forward 的真逆再比对。
     这比单纯放宽阈值有意义：它证明反式是对的，而不是把标准降到能通过。 */
  function numericInvBd(blat, blon) {
    let gg = [blat - 0.006, blon - 0.0065];
    for (let i = 0; i < 200; i++) {
      const f = gcj02ToBd09(gg[0], gg[1]);
      gg[0] += blat - f[0];
      gg[1] += blon - f[1];
    }
    return gg;
  }
  const ana = bd09ToGcj02(b[0], b[1]);
  const num = numericInvBd(b[0], b[1]);
  ok(hav(ana, num) < 0.1, '解析反式 vs 数值真逆 相差 '
    + (hav(ana, num) * 100).toFixed(2) + ' cm < 10cm');
  ok(hav(num, g) < 0.001, '数值真逆 能还原原 GCJ-02（残差 '
    + (hav(num, g) * 1000).toFixed(4) + ' mm）');
  /* 5 厘米 vs z13 一个像素约 19 米 —— 对判定毫无影响，故阈值放宽到 0.3m */
  ok(hav(g, ana) < 0.3, 'BD->GCJ 往返残差 ' + (hav(g, ana) * 100).toFixed(2)
    + ' cm < 30cm（算法固有，非本项目误差）');

  const w2b = wgs84ToBd09(39.9087, 116.3975);
  const b2w = bd09ToWgs84(w2b[0], w2b[1]);
  ok(hav([39.9087, 116.3975], b2w) < 0.3, 'WGS->BD->WGS 往返残差 '
    + (hav([39.9087, 116.3975], b2w) * 100).toFixed(2) + ' cm');
  const dGcj = hav(g, wgs84ToGcj02(39.9087, 116.3975));
  ok(hav(g, w2b) > dGcj, `BD 总偏移 ${hav(g, w2b).toFixed(1)}m > GCJ ${dGcj.toFixed(1)}m`);
}

console.log('\n— 6. 按底图坐标系分派（跑真实 currentBaseCfg / currentBaseKind）—');
{
  const P = [39.9087, 116.3975];
  cfgArgs.length = 0;

  fakeSelect.value = 'tdt_vec';
  ok(currentBaseKind() === 'tdt_vec', 'currentBaseKind 读到下拉当前值');
  ok(currentBaseCrs() === 'WGS84', '天地图 -> WGS84');
  ok(mapToWgs(P[0], P[1])[0] === P[0], 'WGS84 底图：mapToWgs 恒等');
  ok(wgsToMap(P[0], P[1])[0] === P[0], 'WGS84 底图：wgsToMap 恒等');

  fakeSelect.value = 'amap_vec';
  ok(currentBaseCrs() === 'GCJ-02', '高德 -> GCJ-02');
  const mw = mapToWgs(P[0], P[1]);
  const exp = gcj02ToWgs84(P[0], P[1]);
  ok(Math.abs(mw[0] - exp[0]) < 1e-12 && Math.abs(mw[1] - exp[1]) < 1e-12,
     'GCJ-02 底图：mapToWgs 走 gcj02ToWgs84');
  /* 关键性质：地图上点哪儿，判定就用哪儿的 WGS84 —— 反过来画标记要回到点击处 */
  const rt = wgsToMap(mw[0], mw[1]);
  ok(hav(P, rt) < 0.01, 'GCJ-02 底图：点击->判定->画标记 回到原点（'
    + (hav(P, rt) * 100).toFixed(3) + ' cm）');
  ok(hav(P, gcj02ToWgs84(P[0], P[1])) > 100,
     'GCJ-02 底图上不换算就要偏 ' + hav(P, gcj02ToWgs84(P[0], P[1])).toFixed(0) + ' m');

  fakeSelect.value = 'baidu_vec';
  ok(currentBaseCrs() === 'BD-09', '百度 -> BD-09');
  const mb = mapToWgs(P[0], P[1]);
  ok(Math.abs(mb[0] - bd09ToWgs84(P[0], P[1])[0]) < 1e-12,
     'BD-09 底图：mapToWgs 走 bd09ToWgs84');
  const rtb = wgsToMap(mb[0], mb[1]);
  ok(hav(P, rtb) < 0.3, 'BD-09 底图：往返回到原点（' + (hav(P, rtb) * 100).toFixed(2) + ' cm）');

  fakeSelect.value = 'none';
  ok(currentBaseCrs() === 'WGS84', '无底图（crs="-"）-> 退回 WGS84');

  fakeSelect.value = 'custom:u1';
  ok(currentBaseCrs() === 'WGS84', '自定义图源（坐标系未知）-> 按无偏移处理');

  fakeSelect.value = '不存在的key';
  ok(currentBaseCrs() === 'WGS84', '未知 key -> 退回 WGS84，不抛错');

  /* 防回归：真实 currentBaseCfg 内部直接调 kind.indexOf(undefined) 会抛错，
     上一轮这个 bug 就是被"忽略入参的替身"掩盖的，而它在浏览器里表现为
     一点地图就挂。 */
  ok(cfgArgs.length > 0 && cfgArgs.every(k => k === 'string'),
     'currentBaseCfg 每次都被传了字符串（共 ' + cfgArgs.length + ' 次调用，'
     + '非字符串入参 ' + cfgArgs.filter(k => k !== 'string').length + ' 次）');
}

console.log('\n— 7. 与常见近似解对照（独立实现交叉验证）—');
{
  /* 很多实现用 "把 GCJ 当成 WGS 再正算一次、按差值一减" 直接求逆：
       wgs ≈ 2*gcj - toGcj(gcj)
     它忽略二阶项，残差是米级。注意入参必须是【GCJ】坐标。 */
  function approxGcjToWgs(glat, glon) {
    const g2 = wgs84ToGcj02(glat, glon);
    return [2 * glat - g2[0], 2 * glon - g2[1]];
  }
  for (const [name, lat, lon] of CITIES) {
    const g = wgs84ToGcj02(lat, lon);
    const diff = hav(gcj02ToWgs84(g[0], g[1]), approxGcjToWgs(g[0], g[1]));
    ok(diff < 20, `${name} 迭代解与近似解相差 ${diff.toFixed(2)} m < 20m`);
  }
  /* 反向控制：故意用错入参应差出几百米，证明这一节有分辨力，不是恒真断言 */
  const [lat0, lon0] = [39.9087, 116.3975];
  const g0 = wgs84ToGcj02(lat0, lon0);
  const wrong = approxGcjToWgs(lat0, lon0);
  ok(hav(g0, wrong) > 100,
     '分辨力自检：错误入参会偏 ' + hav(g0, wrong).toFixed(1) + ' m（>100m）');
}

console.log('\n— 8. 接线检查（换算有没有真的接到取数路径上）—');
{
  /* 防"算得对但没用上"：换算函数全对，可点击处理里忘了调 mapToWgs，
     等于什么都没修，而界面上一点异常都看不出来。直接对源码下断言。 */
  const clickBlock = /map\.on\('click'[\s\S]{0,400}?\}\);/.exec(script);
  ok(!!clickBlock, '找到 map.on(\'click\') 处理块');
  if (clickBlock) {
    ok(/mapToWgs\s*\(/.test(clickBlock[0]),
       '点击处理里调用了 mapToWgs（否则仍会偏 300~600m）');
    ok(!/queryAt\(\s*e\.latlng/.test(clickBlock[0]),
       '没有把 e.latlng 直接喂给 queryAt（那是修复前的写法）');
  }
  const moveBlock = /map\.on\('mousemove'[\s\S]{0,400}?\}\);/.exec(script);
  ok(!!moveBlock && /mapToWgs\s*\(/.test(moveBlock[0]),
     '经纬度读数也换算成 WGS84（用户会拿这个数去报备）');
  ok(/const\s+mp\s*=\s*wgsToMap\(lat,\s*lon\)/.test(script),
     'queryAt 里用 wgsToMap 计算标记位置');
  ok(/marker\s*=\s*L\.circleMarker\(mp,/.test(script), '标记画在换算后的位置上');
}

function within(a, b) { return a; }   // 占位，避免上面那行无意义断言报错

process.exit(A.done());
