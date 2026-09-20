/* 验证取数缓存语义：这是"不动地图时空白区一直不刷新"的修复点。
 *
 * 三种结果必须区别对待：
 *   拿到数据        -> 缓存
 *   档案里确实没有  -> 缓存（否则每次都白查一遍目录）
 *   取数失败(临时)  -> **绝不缓存**，要能重试
 *
 * 之前把失败也当成"无数据"缓存了，那块瓦片就永远不再请求。
 */

let fail = 0;
const ok = (c, m) => { console.log(`  ${c ? '✓' : '✗'} ${m}`); if (!c) fail++; };

/* ---- 与 index.html 中一致的实现 ---- */
const TILE_STORE_MAX = 600;
const tileStore = new Map();
const tileInflight = new Map();

let fetchImpl = async () => null;          // 各用例替换

async function fetchTileBytes(z, x, y){ return fetchImpl(z, x, y); }

async function getTileEntry(z, x, y){
  const key = z + '/' + x + '/' + y;
  if (tileStore.has(key)){
    const v = tileStore.get(key);
    tileStore.delete(key); tileStore.set(key, v);
    return v;
  }
  if (tileInflight.has(key)) return tileInflight.get(key);
  const p = (async () => {
    let entry, failed = false;
    try {
      const data = await fetchTileBytes(z, x, y);
      entry = (data && data.byteLength) ? { data } : null;
    } catch (e) {
      failed = true; entry = null;
    }
    tileInflight.delete(key);
    if (!failed){
      tileStore.set(key, entry);
      while (tileStore.size > TILE_STORE_MAX) tileStore.delete(tileStore.keys().next().value);
    }
    if (failed) throw new Error('tile fetch failed');
    return entry;
  })();
  tileInflight.set(key, p);
  return p;
}

(async () => {
  console.log('=== 取数缓存语义 ===\n');

  /* 1. 临时失败不缓存 -> 下次会重试并成功 */
  console.log('  用例 1：首次失败，第二次成功');
  let calls = 0;
  fetchImpl = async () => {
    calls++;
    if (calls === 1) throw new Error('模拟网络抖动');
    return new Uint8Array([1, 2, 3]);
  };
  let threw = false;
  await getTileEntry(13, 100, 200).catch(() => { threw = true; });
  ok(threw, '首次失败时向上抛错（不是静默返回 null）');
  const second = await getTileEntry(13, 100, 200);
  ok(second !== null, '再次请求成功拿到数据（说明失败没有被缓存成"无数据"）');
  ok(calls === 2, `真实发起了 ${calls} 次取数（期望 2：失败 1 次 + 重试 1 次）`);

  /* 2. 确定"无数据"要缓存，避免反复查目录 */
  console.log('\n  用例 2：档案里确实没有这块');
  calls = 0;
  fetchImpl = async () => { calls++; return null; };
  const a = await getTileEntry(13, 101, 300);
  const b = await getTileEntry(13, 101, 300);
  ok(a === null && b === null, '两次都返回 null');
  ok(calls === 1, `只查了 ${calls} 次（"无数据"被缓存，第二次直接命中）`);

  /* 3. 成功后缓存，重复请求不再取数 */
  console.log('\n  用例 3：成功结果要缓存');
  calls = 0;
  fetchImpl = async () => { calls++; return new Uint8Array([9, 9]); };
  await getTileEntry(13, 102, 400);
  await getTileEntry(13, 102, 400);
  await getTileEntry(13, 102, 400);
  ok(calls === 1, `3 次请求只取数 ${calls} 次`);

  /* 4. 并发合并：同一瓦片同时请求多次只发一次 */
  console.log('\n  用例 4：并发请求同一瓦片');
  calls = 0;
  fetchImpl = async () => { calls++; await new Promise(r => setTimeout(r, 30)); return new Uint8Array([7]); };
  const ps = [getTileEntry(13, 103, 500), getTileEntry(13, 103, 500), getTileEntry(13, 103, 500)];
  const vs = await Promise.all(ps);
  ok(vs.every(v => v !== null), '三个并发请求都拿到结果');
  ok(calls === 1, `只取数 ${calls} 次（并发合并生效）`);

  /* 5. 失败后不该污染缓存：失败瓦片仍可被后续成功请求填充 */
  console.log('\n  用例 5：先失败多次，最后成功');
  calls = 0;
  fetchImpl = async () => {
    calls++;
    if (calls <= 3) throw new Error('持续失败');
    return new Uint8Array([42]);
  };
  for (let i = 0; i < 3; i++) await getTileEntry(13, 104, 600).catch(() => {});
  const final = await getTileEntry(13, 104, 600);
  ok(final !== null, `第 ${calls} 次成功（多次失败没有把这块永久标记为"无数据"）`);

  console.log(`\n=== ${fail === 0 ? '全部通过' : fail + ' 项失败'} ===`);
  process.exit(fail === 0 ? 0 : 1);
})().catch(e => { console.error('致命错误:', e); process.exit(1); });
