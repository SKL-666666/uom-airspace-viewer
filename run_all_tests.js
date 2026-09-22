/* 一次跑完所有检查与测试。
 *
 * 之前是每次手工敲一长串 node/python 命令，容易漏跑。这里统一入口，
 * 并自动确认本地服务是否在跑（有 4 个用例依赖 HTTP Range）。
 *
 * 用法: node run_all_tests.js [--fast]
 *   --fast  跳过耗时的批量取数/端到端测量（改了前端逻辑时够用）
 *
 * 注意：需要先起服务才能跑全部用例：
 *   python serve.py 8080
 */
const { spawnSync } = require('child_process');
const http = require('http');

const FAST = process.argv.indexOf('--fast') >= 0;

/* [名称, 命令, 参数, 是否需要本地服务, 是否耗时] */
const SUITE = [
  ['接口一致性  check_ids',      'node', ['check_ids.js'],            false],
  ['函数引用    check_refs',     'node', ['check_refs.js'],           false],
  ['声明顺序    check_order',    'node', ['check_order.js'],          false],
  ['静态审计    audit',          'node', ['audit.js'],                false],
  ['坐标换算    geoconv',        'node', ['test_geoconv.js'],         false],
  ['判定逻辑    query_logic',    'node', ['test_query_logic.js'],     false],
  ['地名搜索    search',         'node', ['test_search.js'],         false],
  ['真实返回    geocode_real',   'node', ['test_geocode_real.js'],   false],
  ['瓦片缓存    tile_cache',     'node', ['test_tile_cache.js'],      false],
  ['客户端攒批  batch_client',   'node', ['test_batch_client.js'],    false],
  ['Worker 路径 worker_path',    'node', ['test_worker_path.js'],     true],
  ['批量取数    batch_worker',   'node', ['test_batch_worker.js'],    true],
  ['批量真值    batch_truth',    'node', ['test_batch_truth.js'],     true,  true],
  ['端到端测量  batch_e2e',      'node', ['test_batch_e2e.js'],       true,  true],
  ['HTTP Range  http_range',     'python', ['test_http_range.py'],    true],
  ['判定参考    verify_logic',   'python', ['verify_logic.py'],       false],
  /* 内置数据方案专用的两项：Range 解析逻辑（与 Android/Harmony 两端
     实现保持同一套用例）、APK 内数据完整性（构建后校验）。 */
  ['Range 逻辑  range_server',   'python', ['test_range_server.py'],  false],
  /* 移动端定位配置：权限声明 + 运行时申请 + WebView 回调三处缺一不可，
     缺任一处都表现为"权限问题"，现象一样、原因不同，静态检查能挡住漏项。 */
  ['定位权限    mobile_perm',    'python', ['check_mobile_permissions.py'], false],
  /* 真实浏览器里的 UI 自检（需要本机 Chrome + 本地服务）。
     这一步是唯一能发现"标记/事件接线错了"的检查 —— 静态分析只能证明
     名字对得上，证明不了点下去有反应。放在最后，因为它最慢。 */
  ['浏览器自检  ui_probe',     'node', ['cdp_ui_test.js'],          true, true],
];

function serverUp() {
  return new Promise(resolve => {
    const req = http.get({ host: '127.0.0.1', port: 8080, path: '/', timeout: 1500 },
      res => { res.resume(); resolve(true); });
    req.on('error', () => resolve(false));
    req.on('timeout', () => { req.destroy(); resolve(false); });
  });
}

/* 判定一个用例是否通过：优先看退出码，没有退出码时扫关键字兜底 */
function verdict(r) {
  if (r.error) return { ok: false, note: '无法执行: ' + r.error.message };
  const out = (r.stdout || '') + (r.stderr || '');
  /* 浏览器自检：必须真的跑到结尾且没有捕获到 JS 错误 */
  if (/__probe|final_errs=/.test(out) || /浏览器自检|ui_probe/.test(out)) {
    if (/final_errs=\[\]/.test(out)) return { ok: true, note: '' };
    if (/final_errs=\[/.test(out)) return { ok: false, note: '页面里有未捕获错误' };
    if (/❌/.test(out)) return { ok: false, note: '探针未完成' };
  }
  if (r.status !== 0) {
    /* 已知环境缺陷：test_worker_path.js 在 Node 24 + Windows 上退出时会在 libuv
       里崩（"Assertion failed: !(handle->flags & UV_HANDLE_CLOSING)" 位于
       src\win\async.c），把退出码变成 3221226505(0xC0000409)。它发生在所有断言
       打印完之后，且该用例根本不读 index.html —— 与前端改动无关。
       这里只在【同时】满足"打出成功标记"且"崩在 libuv 断言"时放行，
       并且仍标成"退出码异常"让它保持可见，不会被当成干净的通过。 */
    if (r.status === 3221226505 &&
        /=== 全部通过/.test(out) &&
        /UV_HANDLE_CLOSING/.test(out)) {
      return { ok: true, note: '退出码异常（Node/Win libuv 缺陷，断言全过）' };
    }
    return { ok: false, note: '退出码 ' + r.status };
  }
  /* audit.js 是提示性的，不算失败 */
  if (/发现\s*\d+\s*处问题/.test(out) && !/共\s*\d+\s*项待确认/.test(out)) {
    return { ok: false, note: '报告了问题' };
  }
  return { ok: true, note: '' };
}

(async function () {
  const up = await serverUp();
  console.log('本地服务 127.0.0.1:8080  ' + (up ? '在线' : '离线'));
  if (!up) {
    console.log('  （依赖服务的用例会被跳过；先运行: python serve.py 8080）');
  }
  console.log('模式: ' + (FAST ? '快速（跳过耗时用例）' : '完整') + '\n');

  const results = [];
  for (const [name, cmd, args, needServer, slow] of SUITE) {
    if (needServer && !up) { results.push([name, 'skip', '无服务']); continue; }
    if (FAST && slow) { results.push([name, 'skip', '--fast']); continue; }

    process.stdout.write(name.padEnd(30));
    const r = spawnSync(cmd, args, { encoding: 'utf8', timeout: 600000, shell: false });
    const v = verdict(r);
    results.push([name, v.ok ? 'pass' : 'FAIL', v.note]);
    console.log(v.ok ? '✓' + (v.note ? '  (' + v.note + ')' : '') : '✗  ' + v.note);
    if (!v.ok) {
      const tail = ((r.stdout || '') + (r.stderr || '')).trim().split('\n').slice(-12);
      for (const l of tail) console.log('      ' + l);
    }
  }

  const pass = results.filter(r => r[1] === 'pass').length;
  const fail = results.filter(r => r[1] === 'FAIL').length;
  const skip = results.filter(r => r[1] === 'skip').length;
  console.log('\n' + '='.repeat(52));
  console.log(`通过 ${pass}   失败 ${fail}   跳过 ${skip}   共 ${results.length}`);
  if (fail) {
    console.log('\n失败项:');
    for (const [n, s, note] of results) if (s === 'FAIL') console.log('  ' + n + '  ' + note);
  }
  process.exit(fail === 0 ? 0 : 1);
})();
