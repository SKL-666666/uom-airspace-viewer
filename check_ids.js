/* 检查 index.html 的「标记 ↔ 脚本」接口一致性。
 *
 * 起因：这一轮要把 7 个折叠区、顶部栏、结果卡片全部重排，而脚本里有 30 多处
 * 是直接按 id 取元素的（document.getElementById('baseSel') 之类）。改标记时
 * 漏掉或改错一个 id，脚本不会报语法错、测试脚本也照样通过，只在运行时静默
 * 失效 —— 正是这轮改动最大的风险。所以先立这道护栏。
 *
 * 检查项：
 *   [必须] 脚本里 getElementById('X') / querySelector('#X') 引用的每个 id，
 *          标记里都要有 id="X"
 *   [必须] id 不能重复定义（重复时 getElementById 只返回第一个，静默出错）
 *   [必须] 脚本对这些元素 add/toggle 的 class，样式表里要有对应规则
 *          （例如 .on 没有规则 -> 面板永远打不开，且不报错）
 *   [提示] 定义了但脚本从不引用的 id（重排后可以顺手清掉）
 *
 * 用法: node check_ids.js [html文件]   默认 index.html
 */
const fs = require('fs');
const path = require('path');

const target = process.argv[2] ? path.resolve(process.argv[2]) : path.join(__dirname, 'index.html');
const html = fs.readFileSync(target, 'utf8');

/* ---- 取出内联脚本（取最后一个 <script> 块，与 check_order.js 一致）---- */
const sm = html.match(/<script>([\s\S]*?)<\/script>/g);
if (!sm) { console.error('未找到内联脚本'); process.exit(1); }
const jsRaw = sm[sm.length - 1];
const js = jsRaw.replace(/^<script>/, '').replace(/<\/script>$/, '');

/* ---- 取出样式块 ---- */
const styleM = html.match(/<style>([\s\S]*?)<\/style>/);
const css = styleM ? styleM[1] : '';

/* ---- 标记部分 = 整份文档去掉内联脚本，避免把 JS 里的字符串当标记 ---- */
const markup = html.replace(jsRaw, '');

/* ---- 收集标记里的 id 定义 ---- */
const defined = new Map();          // id -> [出现次数]
const idRe = /\sid\s*=\s*"([^"]+)"/g;
let m;
while ((m = idRe.exec(markup))) {
  const id = m[1];
  defined.set(id, (defined.get(id) || 0) + 1);
}

/* ---- 收集脚本里的 id 引用 ---- */
const referenced = new Map();       // id -> 首个引用的行号
const refPatterns = [
  /getElementById\(\s*'([^']+)'\s*\)/g,
  /getElementById\(\s*"([^"]+)"\s*\)/g,
  /querySelector\(\s*'#([A-Za-z][\w-]*)'\s*\)/g,
];
for (const re of refPatterns) {
  let r;
  while ((r = re.exec(js))) {
    const line = js.slice(0, r.index).split('\n').length;
    if (!referenced.has(r[1])) referenced.set(r[1], line);
  }
}

/* ---- 判定某个 id 是否由脚本自己动态创建 ----
   有两处是脚本用 innerHTML 插进去的（errbar 的关闭按钮、底图重试按钮），
   它们在标记里查不到属于正常。识别特征：脚本里出现 id="X" 或 .id = 'X'。 */
function selfCreated(id) {
  const esc = id.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&');
  return new RegExp('id\\s*=\\s*["\']' + esc + '["\']').test(js)
      || new RegExp('\\.id\\s*=\\s*["\']' + esc + '["\']').test(js);
}

/* ---- 检查 1：引用的 id 都有定义（或由脚本动态创建）---- */
console.log('— 脚本引用的 id：' + referenced.size + ' 个 —');
let bad = 0;
const missing = [], dynamic = [];
for (const [id, line] of referenced) {
  if (defined.has(id)) continue;
  (selfCreated(id) ? dynamic : missing).push({ id, line });
}
if (missing.length) {
  bad += missing.length;
  console.log('  ✗ 标记里缺少这些 id（脚本会取到 null）：');
  for (const x of missing) console.log(`      id="${x.id}"  脚本第 ${x.line} 行引用`);
} else {
  console.log('  ✓ 全部都能在标记里找到');
}
if (dynamic.length) {
  console.log('  · 由脚本动态创建（不计入失败）：' +
    dynamic.map(x => x.id).join(', '));
}

/* ---- 检查 2：id 不重复 ---- */
const dupes = [...defined].filter(([, n]) => n > 1);
if (dupes.length) {
  bad += dupes.length;
  console.log('  ✗ id 重复定义（getElementById 只会拿到第一个）：');
  for (const [id, n] of dupes) console.log(`      id="${id}" 出现 ${n} 次`);
} else {
  console.log('  ✓ id 无重复（标记里共 ' + defined.size + ' 个）');
}

/* ---- 检查 3：脚本对某元素 toggle/add 的 class，样式表里要有【针对该元素】的规则 ----
   只处理能静态解析的形态：
     document.getElementById('X').classList.toggle('on', ...)
     document.getElementById('X').classList.add('on')
     document.getElementById('X').className = 'verdict v-unk'
   取不到的元素（先存成变量再操作）无法静态判定，单独列出不计入失败。

   判定要够严：只检查"样式表里出现过 .on"是不够的 —— 删掉 #result.on 之后
   #side.on / #errbar.on 还在，粗检查照样通过，可是结果卡片就再也打不开了。
   所以按选择器逐个匹配：某个选择器必须同时含 #该id 和 .该类，或者存在一条
   不含任何 #id 的通用 .该类 规则。 */
const classNeeds = new Map();       // "id|class" -> 行号

/* 把  const box = document.getElementById('amapWarn')  这种绑定也认出来。
   否则一旦代码从 getElementById('x').classList 改成先存变量再操作，
   这个检查就悄悄失效了 —— 我重构时正好发生了一次，所以要补上。

   两个必须的约束，否则会大量误报（都实测踩过）：
     · 变量名如果同时是某个函数的形参，就不能按 id 绑定来解读
       （makeUiSelect(host) 的 host 和 getElementById('toast') 的 host 重名）；
     · 一个变量名绑定到多个 id 时直接放弃（box 同时指过 amapWarn 和 favList），
       宁可少查，也不能把 A 元素的 class 误判到 B 元素头上。 */
const paramNames = new Set();
{
  const res = [
    /(?:^|\n)[ \t]*\(?[ \t]*(?:async\s+)?function\s+[A-Za-z_$][\w$]*\s*\(([^)]*)\)/g,
    /(?:^|\n)[ \t]*(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>/g,
    /(?:^|\n)[ \t]*([A-Za-z_$][\w$]*)\s*\(([^)]*)\)[ \t]*\{/g,
  ];
  for (const re of res) {
    let r;
    while ((r = re.exec(js))) {
      const raw = r[r.length - 1] || '';
      for (const p of raw.split(',')) {
        const pn = p.trim().replace(/^\.{3}/, '').replace(/\s*=.*$/, '');
        if (/^[A-Za-z_$][\w$]*$/.test(pn)) paramNames.add(pn);
      }
    }
  }
}
const varBindings = new Map();      // name -> Set<id>
{
  const re = /(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*document\.getElementById\(\s*'([^']+)'\s*\)/g;
  let r;
  while ((r = re.exec(js))) {
    if (!varBindings.has(r[1])) varBindings.set(r[1], new Set());
    varBindings.get(r[1]).add(r[2]);
  }
}

const cPatterns = [
  { re: /getElementById\(\s*'([^']+)'\s*\)\s*\.\s*classList\s*\.\s*(?:add|toggle|remove)\(\s*'([^']+)'/g,
    idIdx: 1, clsIdx: 2 },
  { re: /getElementById\(\s*'([^']+)'\s*\)\s*\.\s*className\s*=\s*'([^']+)'/g,
    idIdx: 1, clsIdx: 2, multi: true },
];
for (const p of cPatterns) {
  let r;
  while ((r = p.re.exec(js))) {
    const line = js.slice(0, r.index).split('\n').length;
    const classes = p.multi ? r[p.clsIdx].split(/\s+/) : [r[p.clsIdx]];
    for (const c of classes) {
      if (!c) continue;
      const k = r[p.idIdx] + '|' + c;
      if (!classNeeds.has(k)) classNeeds.set(k, line);
    }
  }
}
/* 变量形式：NAME.classList.add/toggle/remove('cls')，NAME 唯一绑定到某个 id */
{
  const re = /(?:^|[^\w$.])([A-Za-z_$][\w$]*)\s*\.\s*classList\s*\.\s*(?:add|toggle|remove)\(\s*'([^']+)'/g;
  let r;
  while ((r = re.exec(js))) {
    const name = r[1];
    if (paramNames.has(name)) continue;               // 可能是形参，来源不确定
    const ids = varBindings.get(name);
    if (!ids || ids.size !== 1) continue;             // 没绑定 / 绑定多个 -> 放弃
    const id = ids.values().next().value;
    const line = js.slice(0, r.index).split('\n').length;
    const k = id + '|' + r[2];
    if (!classNeeds.has(k)) classNeeds.set(k, line);
  }
}

/* 取出每个 id 所属元素的标签名与 class 列表，供选择器匹配用。 */
const elemInfo = new Map();         // id -> { tag, classes:[...] }
{
  const tagRe = /<([a-zA-Z][\w-]*)\b[^>]*>/g;
  let t;
  while ((t = tagRe.exec(markup))) {
    const tag = t[0];
    const idM = tag.match(/\sid\s*=\s*"([^"]+)"/);
    if (!idM) continue;
    const clsM = tag.match(/\sclass\s*=\s*"([^"]*)"/);
    elemInfo.set(idM[1], {
      tag: t[1].toLowerCase(),
      classes: clsM ? clsM[1].trim().split(/\s+/).filter(Boolean) : [],
    });
  }
}

/* 拆出样式表里的选择器（取每个 { 之前那段，再按逗号分）。 */
const selectors = [];
{
  const noComments = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const re = /([^{}]+)\{/g;
  let r;
  while ((r = re.exec(noComments))) {
    const chunk = r[1].trim();
    /* 跳过 @media / @keyframes 的前导行和百分比关键帧 */
    if (!chunk || chunk.startsWith('@') || /^[\d.\s%]+$/.test(chunk)) continue;
    for (const s of chunk.split(',')) {
      const x = s.trim();
      if (x) selectors.push(x);
    }
  }
}

const escCls = (c) => c.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&');

/* 判断一个选择器的【最后一个复合选择器】是否可能命中该元素。
   只做保守判断：含 .目标类，且其余约束（#id / .其他类 / 标签名）都要与元素相符。
   不评估后代/兄弟等组合条件（那是 CSS 引擎的活），命中即认为"这条规则管得着它"。 */
function lastCompoundCouldMatch(sel, info, wantCls) {
  const last = sel.split(/[\s>+~]+/).filter(Boolean).pop();
  if (!last) return false;
  if (!new RegExp('\\.' + escCls(wantCls) + '(?![\\w-])').test(last)) return false;

  /* 逐项核对 last 里的约束 */
  const parts = last.match(/[#.]?[\w-]+|\[[^\]]*\]|::?[\w-]+(\([^)]*\))?/g) || [];
  let ok = true;
  for (const p of parts) {
    if (p.startsWith('#')) { if (p.slice(1) !== info.id) { ok = false; break; } }
    /* 目标类本身要在元素【切换后】的类里，所以不能在"现有类"里找它，直接放行 */
    else if (p.startsWith('.') && p.slice(1) === wantCls) { /* skip */ }
    else if (p.startsWith('.')) { if (!info.classes.includes(p.slice(1))) { ok = false; break; } }
    else if (p.startsWith(':')) { /* 伪类（:focus 等）不参与判定 */ }
    else if (p.startsWith('[')) { /* 属性选择器无法静态判定，放行 */ }
    else if (p === info.tag) { /* 标签名相符 */ }
    else { ok = false; break; }        // 标签名不符
  }
  return ok;
}

console.log('\n— 脚本切换的 class：' + classNeeds.size + ' 处 —');
const clsMissing = [], clsResolved = [];
for (const [k, line] of classNeeds) {
  const [id, c] = k.split('|');
  const info = elemInfo.get(id) || { id, tag: '', classes: [] };
  info.id = id;
  const hit = selectors.find(s => lastCompoundCouldMatch(s, info, c));
  if (hit) clsResolved.push(`${id}.${c} ← ${hit}`);
  else clsMissing.push({ id, c, line });
}
if (clsMissing.length) {
  bad += clsMissing.length;
  console.log('  ✗ 找不到能命中该元素的规则（切换后看不出变化，且不报错）：');
  for (const x of clsMissing) {
    console.log(`      #${x.id} 加 .${x.c}  （脚本第 ${x.line} 行切换）`);
  }
} else {
  console.log('  ✓ 每条都有能命中该元素的规则');
}
for (const r of clsResolved) console.log('      ' + r);

/* ---- 检查 3b：按 id 传参的【字符串字面量】也必须存在 ----
   openPanel('side','btnLayers','secUi')、setBtnOn('btnMeasure', on) 这类调用
   传的是字符串 id。写错了不报错、只是"点了没反应"，最难查。
   check_ids 原本只看 getElementById，抓不到这一类，所以单独补一条。 */
function lineOfIdx(idx) { return js.slice(0, idx).split('\n').length; }
const idLiterals = [];
{
  const patterns = [
    /openPanel\(\s*'([^']+)'\s*,\s*'([^']+)'\s*(?:,\s*'([^']+)')?/g,
    /setBtnOn\(\s*'([^']+)'/g,
    /getElementById\(\s*'([^']+)'\s*\)/g,
  ];
  for (const re of patterns) {
    let r;
    while ((r = re.exec(js))) {
      for (let i = 1; i < r.length; i++) {
        if (r[i]) idLiterals.push({ id: r[i], line: lineOfIdx(r.index) });
      }
    }
  }
  /* PANELS 之类的 id 清单数组 */
  const arrRe = /(?:const|let|var)\s+([A-Z_]*PANELS?[A-Z_]*)\s*=\s*\[([^\]]*)\]/g;
  let a;
  while ((a = arrRe.exec(js))) {
    for (const s of a[2].matchAll(/'([^']+)'/g)) {
      idLiterals.push({ id: s[1], line: lineOfIdx(a.index) });
    }
  }
}
console.log('\n— 以字符串形式传递的 id：' + idLiterals.length + ' 处 —');
const litMissing = [];
for (const it of idLiterals) {
  if (!defined.has(it.id) && !selfCreated(it.id)) litMissing.push(it);
  referenced.set(it.id, referenced.get(it.id) || it.line);   // 计入"已引用"
}
if (litMissing.length) {
  bad += litMissing.length;
  console.log('  ✗ 这些 id 以字符串传入但标记里不存在（点了不会有反应）：');
  for (const x of litMissing) console.log(`      '${x.id}'  第 ${x.line} 行`);
} else {
  console.log('  ✓ 都以字符串传入的 id 都能找到');
}

/* ---- 检查 4（提示）：定义了但脚本不引用的 id ---- */
const unused = [...defined.keys()].filter(id => !referenced.has(id));
console.log('\n— 提示：定义了但脚本未引用的 id：' + unused.length + ' 个 —');
console.log('  ' + (unused.length ? unused.join(', ') : '（无）'));
console.log('  （重排标记后这些可以顺手清掉；CSS 选择器仍可能用到，删前确认）');

/* ---- 汇总 ---- */
console.log('\n' + (bad === 0
  ? '=== 通过：标记与脚本的接口一致 ==='
  : `=== 发现 ${bad} 处不一致 ===`));
process.exit(bad === 0 ? 0 : 1);
