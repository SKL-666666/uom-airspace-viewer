/* 静态排查：找出几类"成类出现"的 bug。
 *
 * 这几类我在本项目里都实际犯过，通常不会只犯一次：
 *   1. 选项展开顺序 —— { ...SPREAD, key: v } 里 SPREAD 也含 key 时会覆盖
 *   2. 空 catch / 静默吞异常 —— 出错时页面上毫无迹象
 *   3. createObjectURL 没有对应的 revoke
 *   4. 重复 setTimeout 没有 clear
 *   5. addEventListener 没有 remove（累积泄漏）
 *   6. 语义混同 —— 不同结果映射到同一个值
 */
const fs = require('fs');
const path = require('path');

const files = {
  'index.html': fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8'),
  'tile-worker.js': fs.readFileSync(path.join(__dirname, 'tile-worker.js'), 'utf8'),
};
const js = files['index.html'].match(/<script>([\s\S]*?)<\/script>/g).pop()
  .replace(/^<script>/, '').replace(/<\/script>$/, '');

let issues = 0;
const report = (sev, msg) => { issues++; console.log(`  [${sev}] ${msg}`); };

/* ---------- 1. 选项覆盖：...SPREAD 在显式键之前，且 SPREAD 含同名键 ---------- */
console.log('\n=== 1. 选项展开顺序 ===');
const spreadSources = {
  TILE_OPTS: ['updateWhenIdle', 'updateWhenZooming'],
  DJI_STYLE: ['color', 'weight', 'opacity', 'fillColor', 'fillOpacity'],
};
// 找 { ...X, ... } 的块，检查块内是否有 X 也含的键
for (const [name, keys] of Object.entries(spreadSources)) {
  const re = new RegExp('\\.\\.\\.' + name + '\\b', 'g');
  let m;
  while ((m = re.exec(js))) {
    // 取该对象字面量的剩余部分（到匹配的 } 或行尾若干行）
    const tail = js.slice(m.index, m.index + 400);
    for (const k of keys) {
      // 展开之后再出现同名键 => 该键被覆盖（这是无意的概率高）
      const after = tail.slice(tail.indexOf('...' + name) + name.length + 3);
      const km = new RegExp('(^|[^\\w.])' + k + '\\s*:');
      if (km.test(after.slice(0, 200))) {
        report('注意', `{ ...${name} } 之后又出现 ${k}:，会覆盖展开值（${name} 含该键）`);
      }
    }
  }
}
if (!issues) console.log('  ✓ 未发现可疑的选项覆盖');

/* ---------- 2. 空 catch / 静默吞异常 ---------- */
console.log('\n=== 2. 静默吞异常 ===');
const before2 = issues;
const emptyCatch = /catch\s*(\([^)]*\))?\s*\{\s*(\/\*[^*]*\*\/\s*)?\}/g;
let c;
while ((c = emptyCatch.exec(js))) {
  const line = js.slice(0, c.index).split('\n').length;
  const ctx = js.slice(Math.max(0, c.index - 90), c.index).split('\n').pop().trim();
  report('检查', `第 ${line} 行附近空 catch：…${ctx.slice(-60)}`);
}
if (issues === before2) console.log('  ✓ 没有空 catch');

/* ---------- 3. createObjectURL / revokeObjectURL 配对 ---------- */
console.log('\n=== 3. objectURL 配对 ===');
const creates = (js.match(/createObjectURL/g) || []).length;
const revokes = (js.match(/revokeObjectURL/g) || []).length;
console.log(`  createObjectURL ${creates} 次 / revokeObjectURL ${revokes} 次`);
if (revokes < creates) {
  report('风险', `revoke 少于 create，可能泄漏（create ${creates} / revoke ${revokes}）`);
} else {
  console.log('  ✓ 数量匹配（具体是否都释放需人工确认）');
}

/* ---------- 4. setTimeout 重复使用同一变量但没有 clearTimeout ---------- */
console.log('\n=== 4. 定时器清理 ===');
const timerVars = new Set();
let t;
const assignRe = /(\w+)\s*=\s*setTimeout\(/g;
while ((t = assignRe.exec(js))) timerVars.add(t[1]);
for (const v of timerVars) {
  const clears = (js.match(new RegExp('clearTimeout\\s*\\(\\s*' + v + '\\s*\\)', 'g')) || []).length;
  const assigns = (js.match(new RegExp(v + '\\s*=\\s*setTimeout\\(', 'g')) || []).length;
  const guard = new RegExp('if\\s*\\(\\s*' + v + '\\s*\\)\\s*(return|\\{)').test(js);
  if (assigns >= 1 && clears === 0 && !guard) {
    report('风险', `${v} 被 setTimeout 赋值 ${assigns} 次，没有 clearTimeout 也没有"已存在则跳过"的保护`);
  } else {
    console.log(`  ✓ ${v}: 赋值 ${assigns} 次，clear ${clears} 次${guard ? '，有守卫' : ''}`);
  }
}

/* ---------- 5. addEventListener 没有 remove ---------- */
console.log('\n=== 5. 事件监听清理 ===');
const adds = (js.match(/addEventListener\(/g) || []).length;
const rems = (js.match(/removeEventListener\(/g) || []).length;
console.log(`  addEventListener ${adds} 次 / removeEventListener ${rems} 次`);
console.log('  （页面级监听只注册一次，不清理是正常的；需确认没有在循环/回调里重复注册）');

/* ---------- 6. report() 调用是否可能在 report 定义前执行 ---------- */
console.log('\n=== 6. 关键函数的定义与首次调用顺序 ===');
function firstIndexOf(re) { const m = js.match(re); return m ? js.slice(0, m.index).split('\n').length : null; }
const defLine = firstIndexOf(/^function report\(/m);
console.log(`  report 定义于第 ${defLine} 行`);
// 找所有 report( 调用里，第一个的所在行
let callIdx = null;
const callRe = /(^|[^\w.])report\(/gm;
let cm;
while ((cm = callRe.exec(js))) {
  const ln = js.slice(0, cm.index).split('\n').length;
  if (ln > defLine + 2 && callIdx === null) { callIdx = ln; break; }
}
console.log(`  首次 report() 调用约在第 ${callIdx} 行`);
if (callIdx !== null && callIdx < defLine) report('风险', 'report 在定义前被调用');

/* ---------- 7. 硬编码的瓦片层级/坐标一致性 ---------- */
console.log('\n=== 7. 层级常量一致性 ===');
const consts = {};
for (const k of ['NATIVE_MAX_Z', 'DJI_MIN_ZOOM']) {
  const m = js.match(new RegExp('(?:const|let)\\s+' + k + '\\s*=\\s*(\\d+)'));
  if (m) consts[k] = m[1];
}
console.log('  ', JSON.stringify(consts));
const maxNative = js.match(/maxNativeZoom:\s*(\w+|\d+)/g);
console.log('  maxNativeZoom 用法:', maxNative);
console.log(`  NATIVE_MAX_Z=${consts.NATIVE_MAX_Z}，检查各处是否一致`);

/* ---------- 8. 未使用的变量/死代码 ---------- */
console.log('\n=== 8. 疑似死代码 ===');
const declared = [...js.matchAll(/^(?:const|let)\s+([A-Za-z_$][\w$]*)/gm)].map(m => m[1]);
const unused = declared.filter(n => {
  const uses = (js.match(new RegExp('\\b' + n + '\\b', 'g')) || []).length;
  return uses <= 1 && n.length > 2;
});
if (unused.length) console.log('  仅声明未使用:', unused.join(', '));
else console.log('  ✓ 无');

console.log(`\n=== 共 ${issues} 项待确认 ===`);
