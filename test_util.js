/* 测试公共工具：从 index.html 里把真实代码切出来跑。
 *
 * 为什么要这么绕：这些测试如果各自抄一份实现，实现改了测试还在验旧逻辑，
 * 等于没测。之前就吃过这个亏 —— 我用替身 currentBaseCfg 做测试，替身忽略参数，
 * 于是掩盖了"真实函数必须传参"这个会导致点击即崩的 bug。所以：
 *   1) 一切被测代码都从 index.html 现场切出来；
 *   2) 替身要核对自己的入参，不做"照单全收"的宽松假货。
 *
 * 用法: const { loadScript, extractFn } = require('./test_util');
 */
const fs = require('fs');
const path = require('path');

/** 取出 index.html 里最后一个 <script> 块的内容（与 check_order.js 一致）。 */
function loadScript(file) {
  const f = file || path.join(__dirname, 'index.html');
  const html = fs.readFileSync(f, 'utf8');
  const m = html.match(/<script>([\s\S]*?)<\/script>/g);
  if (!m) throw new Error('未找到内联脚本: ' + f);
  return m[m.length - 1].replace(/^<script>/, '').replace(/<\/script>$/, '');
}

/** 按花括号配平取出一段函数声明源码。
 *  支持注释、单/双引号与模板字符串；不支持正则字面量（被测函数里没有）。 */
function extractFn(src, name) {
  const re = new RegExp('(?:^|\\n)(async\\s+)?function\\s+' + name + '\\s*\\(');
  const hit = re.exec(src);
  if (!hit) return null;
  const open = src.indexOf('{', hit.index);
  if (open < 0) return null;
  let depth = 0, i = open, inS = null, inLineC = false, inBlockC = false;
  for (; i < src.length; i++) {
    const c = src[i], n = src[i + 1];
    if (inLineC) { if (c === '\n') inLineC = false; continue; }
    if (inBlockC) { if (c === '*' && n === '/') { inBlockC = false; i++; } continue; }
    if (inS) {
      if (c === '\\') { i++; continue; }
      if (c === inS) inS = null;
      continue;
    }
    if (c === '/' && n === '/') { inLineC = true; i++; continue; }
    if (c === '/' && n === '*') { inBlockC = true; i++; continue; }
    if (c === "'" || c === '"' || c === '`') { inS = c; continue; }
    if (c === '{') depth++;
    else if (c === '}') { depth--; if (depth === 0) return src.slice(hit.index, i + 1); }
  }
  return null;
}

/** 取两个标记之间的整段代码（用于成节切分）。 */
function extractSection(src, startMarker, endMarker) {
  const a = src.indexOf(startMarker);
  if (a < 0) return null;
  const b = endMarker ? src.indexOf(endMarker, a) : src.length;
  if (b < 0 || b <= a) return null;
  return src.slice(a, b);
}

/** 极简断言器：返回 ok 函数并累计失败数。 */
function makeAsserter(label) {
  const state = { fail: 0, total: 0 };
  function ok(cond, text, extra) {
    state.total++;
    if (cond) console.log('  ✓ ' + text);
    else { state.fail++; console.log('  ✗ ' + text + (extra ? '  ' + extra : '')); }
  }
  state.ok = ok;
  state.done = function () {
    console.log('\n' + (state.fail === 0
      ? '=== 全部通过：' + label + ' ==='
      : '=== ' + state.fail + '/' + state.total + ' 项失败 ==='));
    return state.fail === 0 ? 0 : 1;
  };
  return state;
}

module.exports = { loadScript, extractFn, extractSection, makeAsserter };
