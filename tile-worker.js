/* PMTiles 取数 Worker。
 *
 * 为什么需要它：PMTiles 每次取瓦片都要做 varint 解码、目录二分查找、
 * gzip 解压（叶子目录解出来是几百 KB 的 varint 数据），这些都在 JS 层。
 * 一屏几百块瓦片同时加载时，这些计算全部堆在主线程上，实测造成
 * 80~136ms 的连续长任务。
 *
 * 协议：
 *   主线程 -> { id, z, x, y }
 *   Worker -> { id, data: ArrayBuffer | null }       成功
 *           | { id, error: string }                  失败
 *   data 用 Transferable 转移所有权，避免拷贝。
 *
 * 另外上报统计（stat 消息），用于定位"到底慢在哪"：
 *   n        取数次数
 *   totalMs  累计耗时
 *   maxMs    单次最长
 *   missMs   目录未命中（需要读盘+解压叶子目录）的累计耗时与次数
 */

importScripts('lib/pmtiles.js');

let pm = null;
let pmError = '';

try {
  /* 库在 Windows + Chromium 上会给每个请求带 cache:"no-store"，
     导致浏览器 HTTP 缓存完全失效，每次缩放都要重新拉字节。
     它这么做是因为 Chrome 对 206 分片响应的缓存需要校验器，
     缺少校验器时分片拼接可能出错 —— 服务端已补上 Last-Modified/ETag，
     所以这里可以安全关闭。 */
  const src = new pmtiles.FetchSource('data/uom-shifei.pmtiles');
  src.chromeWindowsNoCache = false;
  pm = new pmtiles.PMTiles(src, new pmtiles.SharedPromiseCache(2000));
} catch (e) {
  pmError = String((e && e.message) || e);
}

/* ---------------- 统计 ---------------- */
const STAT = { n: 0, totalMs: 0, maxMs: 0, slow: 0 };
let statTimer = null;

function bump(dtMs) {
  STAT.n++;
  STAT.totalMs += dtMs;
  if (dtMs > STAT.maxMs) STAT.maxMs = dtMs;
  if (dtMs > 50) STAT.slow++;          // 超过 50ms 记一次"慢取数"
  if (statTimer) return;
  statTimer = setTimeout(() => {
    statTimer = null;
    self.postMessage({
      stat: true,
      n: STAT.n,
      avgMs: STAT.n ? +(STAT.totalMs / STAT.n).toFixed(1) : 0,
      maxMs: Math.round(STAT.maxMs),
      slow: STAT.slow,
      noStore: false
    });
    STAT.n = 0; STAT.totalMs = 0; STAT.maxMs = 0; STAT.slow = 0;
  }, 250);
}

/* 启动时就把 header 拿好，顺便向主线程报告 bounds 供设置图层范围 */
if (pm) {
  pm.getHeader().then(function (h) {
    self.postMessage({
      ready: true,
      header: {
        tileType: h.tileType, minZoom: h.minZoom, maxZoom: h.maxZoom,
        minLon: h.minLon, minLat: h.minLat, maxLon: h.maxLon, maxLat: h.maxLat
      }
    });
  }).catch(function (e) {
    self.postMessage({ ready: false, error: String((e && e.message) || e) });
  });
} else {
  self.postMessage({ ready: false, error: pmError || 'PMTiles 初始化失败' });
}

self.onmessage = function (ev) {
  const m = ev.data;
  if (!m || !pm) {
    if (m && m.id) self.postMessage({ id: m.id, error: pmError || 'PMTiles 不可用' });
    return;
  }
  const t0 = performance.now();
  pm.getZxy(m.z, m.x, m.y).then(function (res) {
    const dt = performance.now() - t0;
    bump(dt);
    if (res && res.data && res.data.byteLength) {
      const buf = res.data;
      /* 转移所有权，零拷贝 */
      self.postMessage({ id: m.id, data: buf }, [buf]);
    } else {
      self.postMessage({ id: m.id, data: null });
    }
  }).catch(function (e) {
    bump(performance.now() - t0);
    self.postMessage({ id: m.id, error: String((e && e.message) || e) });
  });
};
