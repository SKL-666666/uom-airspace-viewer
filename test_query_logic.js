/* 判定逻辑的单元测试。
 *
 * 为什么单独测：结论的优先级（管制区 > 大疆禁飞 > 适飞 > 非适飞）是安全相关的，
 * 而且极容易在重构中被"顺手调换"—— 界面上只会显示一个不一样的结论，不会报错。
 * 上一轮把判定从 queryAt 里抽成 evaluatePoint/decideVerdict，这个测试把语义钉住。
 *
 * 被测函数直接从 index.html 里切出来跑（不是抄一份）。
 *
 * 用法: node test_query_logic.js [html文件]   默认 index.html
 */
const vm = require('vm');
const { loadScript, extractFn, makeAsserter } = require('./test_util');

const script = loadScript(process.argv[2]);

const srcEval = extractFn(script, 'evaluatePoint');
const srcDecide = extractFn(script, 'decideVerdict');
if (!srcEval || !srcDecide) {
  console.error('✗ 找不到 evaluatePoint / decideVerdict —— 函数被改名或挪动了？');
  process.exit(1);
}

const A = makeAsserter('判定优先级与取数正确');
const ok = A.ok;

/* ============ 第一部分：decideVerdict 的优先级 ============ */
const boxDecide = { console: console };
vm.createContext(boxDecide);
vm.runInContext(srcEval + '\n' + srcDecide, boxDecide, { filename: 'logic.js' });

/* 构造一个"判定输入"。默认值取最保守的组合，用例只覆盖关心的字段。 */
function R(o) {
  return Object.assign({
    lat: 39.9, lon: 116.4,
    uom: { state: 'no' },
    dji: [], djiReady: true, inZone: false,
  }, o);
}

console.log('=== 判定逻辑测试 ===\n');
console.log('— 1. 优先级（自上而下，先命中者胜）—');
{
  /* 四个条件同时成立时，必须判管制空域 —— 这是最高优先级 */
  const v = boxDecide.decideVerdict(R({
    inZone: true, uom: { state: 'yes' }, dji: [{ type: 'restricted' }],
  }));
  ok(v.big === '管制空域' && v.cls === 'v-no',
     '① 管制区 压过 大疆禁飞 + UOM适飞 -> ' + v.big);

  const v2 = boxDecide.decideVerdict(R({
    uom: { state: 'yes' }, dji: [{ type: 'restricted' }],
  }));
  ok(v2.big === '禁飞区' && v2.cls === 'v-no',
     '② 大疆禁飞 压过 UOM适飞 -> ' + v2.big);

  const v3 = boxDecide.decideVerdict(R({ uom: { state: 'yes' } }));
  ok(v3.big === '适飞空域' && v3.cls === 'v-ok', '③ UOM适飞 -> ' + v3.big);

  const v4 = boxDecide.decideVerdict(R({ uom: { state: 'no' } }));
  ok(v4.big === '非适飞空域' && v4.cls === 'v-no', '④ 非适飞 -> ' + v4.big);

  const v5 = boxDecide.decideVerdict(R({ uom: { state: 'unknown' } }));
  ok(v5.big === '无法判定' && v5.cls === 'v-unk', '⑤ 取数失败 -> ' + v5.big);
}

console.log('\n— 2. 只有 restricted 才算"禁飞" —');
{
  for (const t of ['warning', 'authorization', 'recommended']) {
    const v = boxDecide.decideVerdict(R({ uom: { state: 'yes' }, dji: [{ type: t }] }));
    ok(v.big === '适飞空域', `${t} 不触发禁飞结论（应为适飞空域）-> ${v.big}`);
  }
  const vr = boxDecide.decideVerdict(R({
    uom: { state: 'no' }, dji: [{ type: 'restricted' }],
  }));
  ok(vr.big === '禁飞区', 'restricted 在非适飞区之上仍判禁飞区 -> ' + vr.big);
}

console.log('\n— 3. "适飞但命中大疆警示"必须带提示语 —');
{
  const withWarn = boxDecide.decideVerdict(R({
    uom: { state: 'yes' }, dji: [{ type: 'warning' }],
  }));
  const without = boxDecide.decideVerdict(R({ uom: { state: 'yes' } }));
  ok(withWarn.small !== without.small && withWarn.small.indexOf('大疆') >= 0,
     '命中警示/限飞区时补一句提示：' + withWarn.small);
  ok(without.small.indexOf('大疆') < 0, '未命中时不带这句：' + without.small);
}

/* ============ 第二部分：evaluatePoint 的取数与判定 ============ */
console.log('\n— 4. evaluatePoint：取数、几何命中、结论 —');
const calls = { uom: 0, geom: 0 };
const seenArgs = [];

function makeBox(opts) {
  const box = {
    console: console,
    Math: Math,
    djiJudge: opts.djiJudge,
    zoneData: opts.zoneData,
    queryUom: async function (lat, lon) {
      calls.uom++;
      /* 入参必须是数字：坐标写反或传了字符串都会在这里露馅 */
      if (typeof lat !== 'number' || typeof lon !== 'number') {
        throw new Error('queryUom 收到非数字坐标: ' + lat + ',' + lon);
      }
      return opts.uom || { state: 'yes', tile: '13/1/2', pixel: '3,4' };
    },
    /* 记录入参：GeoJSON 顺序是 [经度, 纬度]，写反是经典错误 */
    pointInFeature: function (pt, geom) {
      calls.geom++;
      seenArgs.push({ pt: pt.slice(), geom: geom });
      return opts.hit ? opts.hit(pt, geom) : false;
    },
  };
  vm.createContext(box);
  vm.runInContext(srcEval + '\n' + srcDecide, box, { filename: 'logic.js' });
  return box;
}

function reset() { calls.uom = 0; calls.geom = 0; seenArgs.length = 0; }

(async function () {
  reset();
  let box = makeBox({ djiJudge: null, zoneData: null, uom: { state: 'yes' } });
  let r = await box.evaluatePoint(39.9087, 116.3975);
  ok(calls.uom === 1, '调用了一次 queryUom');
  ok(r.uom.state === 'yes', 'uom 结果被带出');
  ok(r.djiReady === false, 'djiJudge 为空时 djiReady=false（界面显示"数据加载中…"）');
  ok(r.dji.length === 0 && r.inZone === false, '无数据时 dji/inZone 为空');
  ok(r.verdict.big === '适飞空域', '结论已填好 -> ' + r.verdict.big);
  ok(r.lat === 39.9087 && r.lon === 116.3975, '回填了原始坐标（批量查询要用）');

  reset();
  box = makeBox({
    djiJudge: [{ geometry: { g: 'A' }, properties: { type: 'restricted', name: '甲' } }],
    zoneData: { features: [{ geometry: { g: 'Z' } }] },
    hit: () => true,
  });
  r = await box.evaluatePoint(39.9087, 116.3975);
  ok(seenArgs.length && seenArgs[0].pt[0] === 116.3975 && seenArgs[0].pt[1] === 39.9087,
     '几何判定入参是 [lon, lat]（GeoJSON 顺序）-> [' + seenArgs[0].pt.join(', ') + ']');
  ok(r.dji.length === 1 && r.dji[0].name === '甲', '命中的大疆要素被收集');
  ok(r.inZone === true, '命中管制区');

  /* 多要素全收集（不能只取第一个） */
  reset();
  box = makeBox({
    djiJudge: [
      { geometry: {}, properties: { type: 'warning', name: 'a' } },
      { geometry: {}, properties: { type: 'restricted', name: 'b' } },
      { geometry: {}, properties: { type: 'warning', name: 'c' } },
    ],
    zoneData: null,
    hit: () => true,
  });
  r = await box.evaluatePoint(39.9087, 116.3975);
  ok(r.dji.length === 3, '三个重叠区域全部收集（期望 3，实际 ' + r.dji.length + '）');
  ok(r.verdict.big === '禁飞区', '其中含 restricted -> 禁飞区');

  /* 管制区命中后应提前跳出，不做无谓扫描 */
  reset();
  box = makeBox({ djiJudge: null, zoneData: { features: [{}, {}, {}, {}, {}] }, hit: () => true });
  r = await box.evaluatePoint(39.9087, 116.3975);
  ok(calls.geom === 1, '管制区命中即 break（几何判定只跑 1 次，实际 ' + calls.geom + '）');

  /* 不命中时要把所有管制区要素都走一遍 */
  reset();
  box = makeBox({ djiJudge: null, zoneData: { features: [{}, {}, {}, {}, {}] }, hit: () => false });
  r = await box.evaluatePoint(39.9087, 116.3975);
  ok(calls.geom === 5, '未命中时遍历全部 5 个（实际 ' + calls.geom + '）');

  /* 无 zoneData / 无 djiJudge 时不能抛错 */
  reset();
  box = makeBox({ djiJudge: undefined, zoneData: undefined, uom: { state: 'unknown' } });
  try {
    r = await box.evaluatePoint(0, 0);
    ok(r.verdict.big === '无法判定', '两者都未加载时安全退化 -> ' + r.verdict.big);
  } catch (e) {
    ok(false, '两者都未加载时不应抛错', e.message);
  }

  /* 坐标写反（lat/lon 互换）必须能被发现：北京点以纬度 116 传入应判为境外无数据。
     这里只验证 evaluatePoint 原样把坐标交给 queryUom，不做自己的解读。 */
  reset();
  box = makeBox({ djiJudge: null, zoneData: null, uom: { state: 'no' } });
  let got = null;
  box.queryUom = async function (lat, lon) { got = [lat, lon]; return { state: 'no' }; };
  await box.evaluatePoint(39.9, 116.4);
  ok(got && got[0] === 39.9 && got[1] === 116.4, '坐标顺序原样透传（lat, lon）');

  process.exit(A.done());
})();
