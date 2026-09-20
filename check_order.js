/* 检查 index.html 内联脚本的顶层声明顺序。
 *
 * 起因：我两次用 "updateLayerBadge();" / 位置估算做插入锚点，把代码插到了
 * 声明之前或函数体内部，造成 TDZ 报错和函数被截断。这个脚本用来在提交前
 * 快速确认关键符号的声明都在使用之前。
 *
 * 用法: node check_order.js
 */
const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
const m = html.match(/<script>([\s\S]*?)<\/script>/g);
if (!m) { console.error('未找到内联脚本'); process.exit(1); }
const js = m[m.length - 1].replace(/^<script>/, '').replace(/<\/script>$/, '');
const lines = js.split('\n');

/** 找某个符号的顶层声明行号。
 *  需同时处理两种写法：
 *    const map = L.map(...)            单声明
 *    let pm = null, uomLayer = null;   逗号连声明
 */
function declLine(name) {
  const single = new RegExp('^(?:const|let|var|function|async function)\\s+' + name + '\\b');
  const inList = new RegExp('^(?:const|let|var)\\s+.*(?:^|[,\\s])' + name + '\\s*=');
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    if (single.test(l)) return i + 1;
    if (/^(?:const|let|var)\s/.test(l) && inList.test(l)) return i + 1;
  }
  return null;
}

/** 找顶层（行首无缩进）首次出现某模式的行号 */
function topLevelUse(re) {
  for (let i = 0; i < lines.length; i++) if (re.test(lines[i])) return i + 1;
  return null;
}

const symbols = ['map', 'baseLayer', 'tileStore', 'tileWorker', 'uomLayer',
                 'djiJudge', 'zoneLayer', 'prefetchToken', 'getTileEntry',
                 'prefetchNeighborZooms', 'syncDjiVisibility', 'queryAt'];

console.log('符号声明位置：');
const decls = {};
for (const s of symbols) {
  decls[s] = declLine(s);
  console.log('  ' + s.padEnd(24) + (decls[s] === null ? '(未找到)' : decls[s]));
}

/* 检查：顶层直接执行的语句是否在依赖之前 */
const checks = [
  { name: "map.on('moveend zoomend')", use: /^map\.on\('moveend zoomend'/, dep: 'map' },
  { name: "map.on('click')",           use: /^map\.on\('click'/,           dep: 'map' },
  { name: "updateLayerBadge()",        use: /^updateLayerBadge\(\);/,       dep: 'uomLayer' },
];

console.log('\n顺序检查：');
let bad = 0;
for (const c of checks) {
  const u = topLevelUse(c.use);
  const d = decls[c.dep];
  if (u === null) { console.log('  ' + c.name.padEnd(30) + '未找到，跳过'); continue; }
  if (d === null) { console.log('  ' + c.name.padEnd(30) + '依赖 ' + c.dep + ' 未声明  ✗'); bad++; continue; }
  const ok = u > d;
  if (!ok) bad++;
  console.log('  ' + c.name.padEnd(30) + '使用@' + u + '  依赖 ' + c.dep + '@' + d + '  ' + (ok ? '✓' : '✗ 声明前使用！'));
}

/* 语法有效性：交给 V8 真正解析一次。
   这里原本是手工数括号，但正则字面量、字符串、注释里的括号会让它误报
   （实测报了"花括号 +2 不配平"，而脚本其实是合法的，只是显示被截断）。
   直接编译一次最可靠：能过就是能过，不能过会给出确切位置。 */
console.log('\n语法解析（V8）:');
try {
  new (require('vm').Script)(js, { filename: 'inline-script.js' });
  console.log('  解析通过  ✓');
} catch (e) {
  bad++;
  console.log('  解析失败  ✗ ' + e.message);
}

console.log('\n' + (bad === 0 ? '=== 通过 ===' : '=== 发现 ' + bad + ' 处问题 ==='));
process.exit(bad === 0 ? 0 : 1);
