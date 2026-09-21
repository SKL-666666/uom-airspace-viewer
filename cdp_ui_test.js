/* 用 Chrome DevTools Protocol 在【真实时间】里跑 _probe.html 并取回观测结果。
 *
 * 为什么不继续用 --dump-dom + --virtual-time-budget：
 *   虚拟时间让 setTimeout 飞快推进，而 Web Worker 里的真实网络请求还没回来，
 *   于是页面里那些"超时保护"会误触发。实测自检因此报"批量取数超时" ——
 *   看上去像 bug，其实是测试环境的假象。要判定"取数链路的超时保护是否合理"，
 *   就必须在真实时间里跑。
 *
 * 只用 Node 内置能力（fetch + 全局 WebSocket，Node 22+ 自带），不引入依赖。
 *
 * 用法:
 *   python make_probe.py
 *   node cdp_ui_test.js [url] [总超时毫秒]
 */
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const CHROME = process.env.CHROME_PATH
  || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const PORT = 9333;
const TARGET = process.argv[2] || 'http://127.0.0.1:8080/_probe.html';
const TOTAL_MS = Number(process.argv[3] || 180000);
/* 窗口尺寸可覆盖，用来验证窄屏断点：
     UI_PROBE_WINDOW=390,844 node cdp_ui_test.js
   桌面与窄屏走的是两套布局（抽屉 / 折叠区），只测一种等于没测。 */
const WINDOW_SIZE = process.env.UI_PROBE_WINDOW || '1440,900';

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

async function getJson(pathname){
  const r = await fetch(`http://127.0.0.1:${PORT}${pathname}`);
  return r.json();
}

/* 极简 CDP 客户端：一条 WebSocket，按 id 关联请求与响应 */
function connect(wsUrl){
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    const pending = new Map();
    let seq = 0;
    ws.addEventListener('open', () => {
      resolve({
        send(method, params){
          const id = ++seq;
          return new Promise((res, rej) => {
            pending.set(id, { res, rej });
            ws.send(JSON.stringify({ id, method, params: params || {} }));
          });
        },
        close(){ try { ws.close(); } catch(e){} },
      });
    });
    ws.addEventListener('message', (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch(e){ return; }
      if (msg.id && pending.has(msg.id)){
        const p = pending.get(msg.id);
        pending.delete(msg.id);
        if (msg.error) p.rej(new Error(JSON.stringify(msg.error)));
        else p.res(msg.result);
      }
    });
    ws.addEventListener('error', (e) => reject(new Error('WebSocket 连接失败')));
  });
}

async function evaluate(client, expr){
  const r = await client.send('Runtime.evaluate', {
    expression: expr, returnByValue: true, awaitPromise: true,
  });
  if (r && r.exceptionDetails){
    return { error: r.exceptionDetails.text || 'evaluate 异常' };
  }
  return { value: r && r.result ? r.result.value : undefined };
}

(async function main(){
  const userDir = path.join(os.tmpdir(), 'uom-cdp-' + Date.now());
  const child = spawn(CHROME, [
    '--headless=new', '--disable-gpu', '--no-sandbox',
    '--remote-debugging-port=' + PORT,
    '--user-data-dir=' + userDir,
    '--window-size=' + WINDOW_SIZE,
    '--no-first-run', '--disable-extensions',
    TARGET,
  ], { stdio: 'ignore' });

  let client = null;
  let failed = 1;
  try {
    /* 等调试端口起来 */
    let ver = null;
    for (let i = 0; i < 60; i++){
      try { ver = await getJson('/json/version'); break; } catch(e){ await sleep(300); }
    }
    if (!ver){ throw new Error('Chrome 调试端口没起来（' + PORT + '）'); }
    process.stdout.write('浏览器已启动\n');

    /* 找到页面 target */
    let target = null;
    for (let i = 0; i < 40; i++){
      const list = await getJson('/json/list');
      target = list.find(t => t.type === 'page' && t.url.indexOf('_probe') >= 0)
            || list.find(t => t.type === 'page');
      if (target && target.webSocketDebuggerUrl) break;
      await sleep(300);
    }
    if (!target) throw new Error('找不到页面 target');

    client = await connect(target.webSocketDebuggerUrl);
    await client.send('Runtime.enable');
    process.stdout.write('已连接，等待探针跑完（最多 ' + Math.round(TOTAL_MS / 1000) + ' 秒）…\n');

    const t0 = Date.now();
    let text = '';
    while (Date.now() - t0 < TOTAL_MS){
      const r = await evaluate(client, 'window.__probeText || ""');
      if (r.error){ process.stdout.write('evaluate 出错: ' + r.error + '\n'); break; }
      if (typeof r.value === 'string' && r.value){
        text = r.value;
        break;
      }
      await sleep(1000);
    }
    if (!text){
      /* 兜底：也许探针只写了 DOM 没写 window，读一把 DOM */
      const r = await evaluate(client,
        '(function(){var e=document.getElementById("__probe");' +
        'return e ? e.textContent : "";})()');
      text = (r && r.value) || '';
    }
    if (!text){
      const r = await evaluate(client, 'JSON.stringify(window.__errs || [])');
      console.log('❌ 探针没有产出结果。已捕获错误：' + (r && r.value));
    } else {
      console.log('\n' + text);
      failed = /final_errs=\[\]/.test(text) ? 0 : (/final_errs=/.test(text) ? 1 : 0);
    }
  } catch(e){
    console.log('❌ ' + ((e && e.message) || e));
  } finally {
    if (client) client.close();
    try { child.kill(); } catch(e){}
    await sleep(300);
    try { fs.rmSync(userDir, { recursive: true, force: true }); } catch(e){}
  }
  process.exit(failed);
})();
