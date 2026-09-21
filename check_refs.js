/* 检查内联脚本里的函数调用是否都指向真实存在的东西。
 *
 * 起因：这一轮我写了 currentBaseCrs()，里面调 currentBaseCfg() 时忘了传参。
 * 单测没发现，因为我在测试里用替身顶掉了 currentBaseCfg —— 替身忽略入参，
 * 于是把 bug 藏住了。而它在浏览器里的表现是"点一下地图就报错"。
 * 语法检查、id 校验、声明顺序检查都抓不到这类问题，所以单独加这一个。
 *
 * 两类检查：
 *   [必须] 裸调用的名字要么是本脚本声明的函数/方法/形参，要么是已知内建/全局。
 *          抓拼写错误和"删了实现忘了删调用"。
 *   [必须] 零参数调用一个"声明了形参、且形参确实在函数体里被用到"的函数。
 *          少传参必然拿到 undefined —— currentBaseCfg() 就是这么崩的。
 *
 * 踩过的坑（都体现在实现里）：
 *   · 字符串要整体换成占位符而不是纯空格，否则 setBase('x') 会被看成零参数调用；
 *   · 正则字面量要识别，否则 /[&<>"']/g 里的单引号会吞掉后面一大段代码；
 *   · IIFE (function f(){})()、async () =>、对象方法简写 f(){}、
 *     const X = L.GridLayer.extend({}) 这几种"声明"都要认，否则误报；
 *   · 回调形参（done、resolve 之类）也要算已知名字。
 *
 * 用法: node check_refs.js [html文件]   默认 index.html
 */
const fs = require('fs');
const path = require('path');

const target = process.argv[2] ? path.resolve(process.argv[2]) : path.join(__dirname, 'index.html');
const html = fs.readFileSync(target, 'utf8');
const m = html.match(/<script>([\s\S]*?)<\/script>/g);
if (!m) { console.error('未找到内联脚本'); process.exit(1); }
const js = m[m.length - 1].replace(/^<script>/, '').replace(/<\/script>$/, '');

/* ------------------------------------------------------------------
   遮蔽：注释、字符串、正则字面量 -> 等长占位
   字符串保留【一个】非空字符 '0' 作为"这里有个值"的标志，其余补空格。
   否则 setBase('tdt_vec') 会变成 setBase(        )，被误判为零参数调用。
   ------------------------------------------------------------------ */
const PLACEHOLDER = '0';
function blank(s) {
  const out = s.split('');
  const isWord = (ch) => ch != null && /[\w$]/.test(ch);
  const fill = (from, to) => { for (let k = from; k <= to && k < s.length; k++) if (s[k] !== '\n') out[k] = ' '; };
  let i = 0, inLineC = false, inBlockC = false, prev = '';

  while (i < s.length) {
    const c = s[i], n = s[i + 1];

    if (inLineC) { if (c === '\n') inLineC = false; else out[i] = ' '; i++; continue; }
    if (inBlockC) {
      if (c === '*' && n === '/') { out[i] = ' '; out[i + 1] = ' '; i += 2; inBlockC = false; continue; }
      if (c !== '\n') out[i] = ' ';
      i++; continue;
    }
    if (c === '/' && n === '/') { out[i] = ' '; out[i + 1] = ' '; inLineC = true; i += 2; continue; }
    if (c === '/' && n === '*') { out[i] = ' '; out[i + 1] = ' '; inBlockC = true; i += 2; continue; }

    /* 正则字面量：/ 前不是标识符字符、也不是 ) ] 时判定为正则开头 */
    if (c === '/' && !isWord(prev) && prev !== ')' && prev !== ']') {
      let j = i + 1, inClass = false;
      while (j < s.length) {
        const d = s[j];
        if (d === '\\') { j += 2; continue; }
        if (d === '\n') break;
        if (d === '[') inClass = true;
        else if (d === ']') inClass = false;
        else if (d === '/' && !inClass) break;
        j++;
      }
      if (j < s.length && s[j] === '/') {
        fill(i, j);
        out[i] = PLACEHOLDER;
        i = j + 1;
        let fl = i;
        while (i < s.length && /[a-z]/i.test(s[i])) { out[i] = ' '; i++; }
        if (fl === i) { /* 无 flags */ }
        prev = '/'; continue;
      }
    }
    if (c === "'" || c === '"' || c === '`') {
      const q = c; let j = i + 1;
      while (j < s.length) {
        if (s[j] === '\\') { j += 2; continue; }
        if (s[j] === q) break;
        j++;
      }
      const end = Math.min(j, s.length - 1);
      fill(i, end);
      out[i] = PLACEHOLDER;
      i = j + 1; prev = q; continue;
    }
    if (!/\s/.test(c)) prev = c;
    i++;
  }
  return out.join('');
}

const code = blank(js);
const lineOf = (idx) => code.slice(0, idx).split('\n').length;

/* ------------------------------------------------------------------
   收集函数声明。形参名也收集起来 —— 回调形参（done/resolve/…）也是合法调用目标。
   ------------------------------------------------------------------ */
const declared = new Map();     // name -> { params, hasDefault, defLine, body }
const paramNames = new Set();

function takeBody(from) {
  const open = code.indexOf('{', from);
  if (open < 0) return '';
  let depth = 0;
  for (let i = open; i < code.length; i++) {
    if (code[i] === '{') depth++;
    else if (code[i] === '}') { depth--; if (depth === 0) return code.slice(open, i + 1); }
  }
  return '';
}
function addDecl(name, rawParams, defLine, bodyFrom, bodyText) {
  const params = (rawParams || '').trim()
    ? rawParams.split(',').map(s => s.trim()).filter(Boolean) : [];
  for (const p of params) {
    const pn = p.replace(/^\.{3}/, '').replace(/\s*=.*$/, '').trim();
    if (/^[A-Za-z_$][\w$]*$/.test(pn)) paramNames.add(pn);
  }
  if (declared.has(name)) return;
  declared.set(name, {
    params: params,
    hasDefault: (rawParams || '').indexOf('=') >= 0,
    defLine: defLine,
    body: bodyText != null ? bodyText : takeBody(bodyFrom),
  });
}

const DECL_PATTERNS = [
  /* function name(a){} —— 也覆盖 (function name(){})() 这种 IIFE */
  /(?:^|\n)[ \t]*\(?[ \t]*(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(([^)]*)\)/g,
  /* const name = function(a){} / = async function(a){} */
  /(?:^|\n)[ \t]*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?function\s*\(([^)]*)\)/g,
  /* const name = (a, b) => */
  /(?:^|\n)[ \t]*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>/g,
  /* const name = a => */
  /(?:^|\n)[ \t]*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?([A-Za-z_$][\w$]*(?:\s*,\s*[A-Za-z_$][\w$]*)*)\s*=>/g,
  /* const name = 别的表达式 || function(a){} / ? (a) => ... —— 同行内任意表达式后再接函数 */
  /(?:^|\n)[ \t]*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=[^\n]*?(?:function\s*\(([^)]*)\)|\(([^)]*)\)\s*=>)/g,
  /* 对象方法简写 name(a){} —— UomLayer 的 createTile 就是这种。
     允许出现在行内（前面是空白/逗号/花括号），但不跨行匹配 `{`，
     否则 foo(a) 换行后的一个代码块也会被当成函数定义。 */
  /(?:^|[\s,{;])([A-Za-z_$][\w$]*)[ \t]*\(([^)]*)\)[ \t]*\{/g,
  /* 对象访问器简写 get name(){} / set name(v){} —— basemapUi 的 value 就是这种，
     且常写在单行的对象字面量里，所以不能要求行首。 */
  /(?:^|[\s,{;])(?:get|set)[ \t]+([A-Za-z_$][\w$]*)[ \t]*\(([^)]*)\)[ \t]*\{/g,
  /* const X = L.GridLayer.extend({...}) / = SomeClass.extend({...}) */
  /(?:^|\n)[ \t]*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*[\w$.]+\.extend\s*\(/g,
  /* class X ... */
  /(?:^|\n)[ \t]*class\s+([A-Za-z_$][\w$]*)/g,
];
/* 这些"名字"其实是关键字，方法简写模式会把它们也匹配进来 */
const KEYWORDS = new Set(['if', 'for', 'while', 'switch', 'catch', 'function', 'return',
  'typeof', 'new', 'do', 'else', 'delete', 'void', 'in', 'of', 'instanceof',
  'case', 'await', 'try', 'yield', 'throw', 'super', 'import', 'async']);

for (const re of DECL_PATTERNS) {
  let r;
  while ((r = re.exec(code))) {
    if (KEYWORDS.has(r[1])) continue;
    addDecl(r[1], r[2], lineOf(r.index), re.lastIndex);
  }
}

/* 独立收集箭头函数形参（含 .then(r => ...) 这类回调），只用于补充 paramNames */
{
  const re = /\(([^()]*)\)\s*=>/g;
  let r;
  while ((r = re.exec(code))) {
    for (const p of r[1].split(',')) {
      const pn = p.trim().replace(/^\.{3}/, '').replace(/\s*=.*$/, '');
      if (/^[A-Za-z_$][\w$]*$/.test(pn)) paramNames.add(pn);
    }
  }
  const re2 = /([A-Za-z_$][\w$]*)\s*=>/g;
  while ((r = re2.exec(code))) paramNames.add(r[1]);
}

/* ------------------------------------------------------------------
   已知的内建 / 宿主全局
   ------------------------------------------------------------------ */
const GLOBALS = new Set([
  'Math', 'JSON', 'Object', 'Array', 'String', 'Number', 'Boolean', 'Promise',
  'Map', 'Set', 'WeakMap', 'Date', 'RegExp', 'Error', 'TypeError', 'Symbol',
  'parseInt', 'parseFloat', 'isNaN', 'isFinite', 'encodeURIComponent',
  'decodeURIComponent', 'structuredClone', 'queueMicrotask',
  'setTimeout', 'clearTimeout', 'setInterval', 'clearInterval',
  'requestAnimationFrame', 'cancelAnimationFrame', 'requestIdleCallback',
  'fetch', 'alert', 'confirm', 'prompt', 'console',
  'Image', 'Blob', 'URL', 'FileReader', 'File', 'TextDecoder', 'TextEncoder',
  'DecompressionStream', 'ResizeObserver', 'IntersectionObserver', 'Worker',
  'Function', 'Uint8Array', 'ArrayBuffer', 'DataView', 'Float64Array',
  'performance', 'navigator', 'document', 'window', 'localStorage',
  'getComputedStyle', 'matchMedia', 'CustomEvent', 'Event', 'Node',
  'L', 'pmtiles', 'crypto', 'btoa', 'atob', 'Intl', 'AggregateError',
  'createImageBitmap', 'PerformanceObserver', 'MutationObserver', 'AbortController',
  'DOMParser', 'XMLSerializer', 'FormData', 'Headers', 'Request', 'Response',
  'Blob', 'URLSearchParams', 'Notification', 'navigator',
]);

/* ------------------------------------------------------------------
   收集裸调用（前面不能是 . 或标识符字符）
   ------------------------------------------------------------------ */
const calls = [];
{
  const re = /(^|[^\w$.])([A-Za-z_$][\w$]*)\s*\(/g;
  let r;
  while ((r = re.exec(code))) {
    const name = r[2];
    if (KEYWORDS.has(name) || GLOBALS.has(name)) continue;
    let depth = 1, i = re.lastIndex, args = 0, sawAny = false;
    for (; i < code.length; i++) {
      const c = code[i];
      if (c === '(' || c === '[' || c === '{') depth++;
      else if (c === ')' || c === ']' || c === '}') { depth--; if (depth === 0) break; }
      else if (c === ',' && depth === 1) args++;
      else if (!/\s/.test(c)) sawAny = true;
    }
    calls.push({ name: name, argc: sawAny ? args + 1 : 0, line: lineOf(r.index) });
  }
}

let bad = 0;
console.log('— 声明的函数/方法/类：' + declared.size + ' 个 —');
console.log('— 回调形参：' + paramNames.size + ' 个 —');
console.log('— 裸函数调用点：' + calls.length + ' 处 —\n');

console.log('— 检查 1：调用的名字有没有出处 —');
{
  const unknown = [];
  const seen = new Set();
  for (const c of calls) {
    if (declared.has(c.name) || paramNames.has(c.name) || seen.has(c.name)) continue;
    seen.add(c.name);
    unknown.push(c);
  }
  if (unknown.length) {
    bad += unknown.length;
    console.log('  ✗ 找不到出处（拼错？还是删了实现？）:');
    for (const c of unknown) console.log(`      ${c.name}()  第 ${c.line} 行`);
  } else {
    console.log('  ✓ 每处函数调用都能找到出处');
  }
}

console.log('\n— 检查 2：有没有"零参数调用但有形参要用" —');
{
  const zeroArg = [];
  for (const c of calls) {
    const d = declared.get(c.name);
    if (!d || c.argc !== 0 || d.params.length === 0 || d.hasDefault) continue;
    const used = d.params.some(p => {
      const pn = p.replace(/^\.{3}/, '').replace(/\s*=.*$/, '');
      if (!/^[A-Za-z_$][\w$]*$/.test(pn)) return false;
      return new RegExp('[^\\w$.]' + pn + '[^\\w$]').test(d.body);
    });
    if (used) zeroArg.push({ name: c.name, params: d.params, callLine: c.line, defLine: d.defLine });
  }
  if (zeroArg.length) {
    bad += zeroArg.length;
    console.log('  ✗ 零参数调用，但形参在函数体里被用到（会拿到 undefined）:');
    for (const z of zeroArg) {
      console.log(`      ${z.name}()  第 ${z.callLine} 行调用；`
        + `声明在第 ${z.defLine} 行，形参 (${z.params.join(', ')})`);
    }
  } else {
    console.log('  ✓ 没有少传形参的零参数调用');
  }
}

/* 统计一下解析规模，太小说明遮蔽或正则坏了（曾经只解析出 3 个函数） */
if (declared.size < 20 || calls.length < 50) {
  console.log('\n✗ 解析出的规模异常小（函数 ' + declared.size + ' 个 / 调用 '
    + calls.length + ' 处），遮蔽逻辑或正则可能失效了，本检查结果不可信');
  bad++;
}

console.log('\n' + (bad === 0
  ? '=== 通过：函数引用一致 ==='
  : `=== 发现 ${bad} 处问题 ===`));
process.exit(bad === 0 ? 0 : 1);
