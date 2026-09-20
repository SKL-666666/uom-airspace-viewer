/* 验证客户端攒批逻辑：一轮内的多次请求要合成一个消息，
 * 且返回结果必须按顺序对上各自的 Promise（错了就会张冠李戴）。
 *
 * 这里把 index.html 里的攒批代码原样抽出来跑，不依赖 DOM。
 */
let fail = 0;
const ok = (c, m) => { console.log(`  ${c ? '✓' : '✗'} ${m}`); if (!c) fail++; };

/* ---- 与 index.html 中一致的攒批实现 ---- */
let workerSeq = 0;
const batchPending = new Map();
const inflightBatches = new Map();
let batchTimer = null;
const sent = [];               // 记录发出去的消息

function batchFlush(){
  batchTimer = null;
  if (!batchPending.size) return;
  const items = [], resolvers = [];
  for (const rec of batchPending.values()){
    items.push([rec.z, rec.x, rec.y]);
    resolvers.push(rec.resolvers);
  }
  batchPending.clear();
  const id = ++workerSeq;
  inflightBatches.set(id, resolvers);
  sent.push({ batch: true, id, tiles: items });
}

function workerGetTile(z, x, y){
  return new Promise((resolve, reject) => {
    const key = z + '/' + x + '/' + y;
    let rec = batchPending.get(key);
    if (!rec){ rec = { z: z, x: x, y: y, resolvers: [] }; batchPending.set(key, rec); }
    rec.resolvers.push({ resolve: resolve, reject: reject });
    if (!batchTimer) batchTimer = setTimeout(batchFlush, 0);
  });
}

/* 模拟 Worker 回包 */
function deliver(m){
  /* 批量整体失败：{id, error}，没有 results —— 必须立刻拒绝 */
  if (m.error && inflightBatches.has(m.id)){
    const rs = inflightBatches.get(m.id);
    inflightBatches.delete(m.id);
    for (const list of rs) for (const r of list) r.reject(new Error(m.error));
    return;
  }
  if (m.results){
    const rs = inflightBatches.get(m.id);
    if (!rs) return;
    inflightBatches.delete(m.id);
    m.results.forEach((r, i) => {
      const list = rs[i];
      if (!list) return;
      for (const res of list){
        if (r && r.error) res.reject(new Error(r.error));
        else res.resolve(r ? r.data : null);
      }
    });
  }
}

(async () => {
  console.log('=== 验证客户端攒批 ===\n');

  /* 1. 一轮内 40 次请求应合成 1 个消息 */
  const tiles = [];
  for (let x = 6720; x < 6728; x++)
    for (let y = 3140; y < 3145; y++) tiles.push([13, x, y]);
  console.log(`  同一轮内发起 ${tiles.length} 次请求`);
  const promises = tiles.map(([z, x, y]) => workerGetTile(z, x, y));
  ok(sent.length === 0, '此时尚未发出消息（等本轮结束）');
  await new Promise(r => setTimeout(r, 20));
  ok(sent.length === 1, `攒批后只发出 ${sent.length} 个消息（期望 1）`);
  ok(sent[0].tiles.length === tiles.length, `消息内包含 ${sent[0].tiles.length} 张瓦片`);

  /* 2. 顺序对齐：给每张瓦片返回可区分的标记，检查是否对号入座 */
  const results = sent[0].tiles.map((t, i) => {
    const buf = new Uint8Array([i & 255, (i >> 8) & 255, t[0], t[1] & 255]);
    return { z: t[0], x: t[1], y: t[2], data: buf.buffer };
  });
  deliver({ id: sent[0].id, results });

  const vals = await Promise.all(promises);
  let mismatch = 0;
  vals.forEach((v, i) => {
    if (!v) { mismatch++; return; }
    const b = new Uint8Array(v);
    if ((b[0] | (b[1] << 8)) !== i) mismatch++;
  });
  ok(mismatch === 0, `${vals.length} 个 Promise 都拿到了属于自己那张瓦片的结果`);

  /* 3. 有空数据时也要对号入座 */
  sent.length = 0;
  batchPending.clear(); inflightBatches.clear();
  const p2 = [workerGetTile(13, 6800, 3100), workerGetTile(13, 6801, 3100), workerGetTile(13, 6802, 3100)];
  await new Promise(r => setTimeout(r, 20));
  ok(sent.length === 1, '第二轮同样合为 1 个消息');
  deliver({ id: sent[0].id, results: [
    { z: 13, x: 6800, y: 3100, data: null },
    { z: 13, x: 6801, y: 3100, data: new Uint8Array([9]).buffer },
    { z: 13, x: 6802, y: 3100, data: null },
  ]});
  const v2 = await Promise.all(p2);
  ok(v2[0] === null && v2[1] !== null && v2[2] === null,
     '含空数据时顺序仍正确（null / 有数据 / null）');

  /* 4. 错误项单独 reject，不影响同批其它项 */
  sent.length = 0;
  batchPending.clear(); inflightBatches.clear();
  const p3 = [workerGetTile(13, 6810, 3100), workerGetTile(13, 6811, 3100)];
  await new Promise(r => setTimeout(r, 20));
  deliver({ id: sent[0].id, results: [
    { z: 13, x: 6810, y: 3100, error: '模拟失败' },
    { z: 13, x: 6811, y: 3100, data: new Uint8Array([7]).buffer },
  ]});
  let rejected = false, okData = false;
  await p3[0].catch(() => { rejected = true; });
  await p3[1].then(v => { okData = !!v; });
  ok(rejected && okData, '同批中一项失败不影响另一项成功');

  /* 5. 请求数与去重：同一瓦片重复请求只发一次 */
  sent.length = 0;
  batchPending.clear(); inflightBatches.clear();
  const p4 = [workerGetTile(13, 6820, 3100), workerGetTile(13, 6820, 3100)];
  await new Promise(r => setTimeout(r, 20));
  ok(sent[0].tiles.length === 1, `重复请求同一瓦片 -> 消息内只含 1 张（Map 键去重）`);
  deliver({ id: sent[0].id, results: [{ z: 13, x: 6820, y: 3100, data: new Uint8Array([1]).buffer }] });
  const v4 = await Promise.all(p4);
  ok(v4[0] !== null && v4[1] !== null,
     '重复请求的两个 Promise 都完成（resolver 不覆盖，否则会丢一块瓦片）');

  /* 6. 批量整体失败要立刻拒绝，不能等 15 秒超时 */
  console.log('  用例 6：Worker 返回批量错误（无 results）');
  sent.length = 0; batchPending.clear(); inflightBatches.clear();
  const t0 = Date.now();
  const p6 = [workerGetTile(13, 6900, 3100), workerGetTile(13, 6901, 3100)];
  await new Promise(r => setTimeout(r, 20));
  deliver({ id: sent[0].id, error: '模拟批量失败' });
  let rejCount = 0;
  await Promise.all(p6.map(x => x.catch(() => { rejCount++; })));
  const dt = Date.now() - t0;
  ok(rejCount === 2, `两个 Promise 都被拒绝（${rejCount}/2）`);
  ok(dt < 2000, `立即拒绝，耗时 ${dt}ms（而不是等 15 秒超时）`);

  /* 7. 单项错误只拒绝那一项 */
  console.log('  用例 7：单项错误');
  sent.length = 0; batchPending.clear(); inflightBatches.clear();
  const p7 = [workerGetTile(13, 6910, 3100)];
  await new Promise(r => setTimeout(r, 20));
  deliver({ id: sent[0].id, results: [{ z: 13, x: 6910, y: 3100, error: 'worker unavailable' }] });
  let rej7 = false;
  await p7[0].catch(() => { rej7 = true; });
  ok(rej7, '单项错误被正确拒绝');

  console.log(`\n=== ${fail === 0 ? '全部通过' : fail + ' 项失败'} ===`);
  process.exit(fail === 0 ? 0 : 1);
})().catch(e => { console.error('致命错误:', e); process.exit(1); });
