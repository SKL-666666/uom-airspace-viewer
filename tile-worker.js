/* PMTiles 取数 Worker。
 *
 * 为什么需要它：PMTiles 每次取瓦片都要做 varint 解码、目录二分查找、
 * gzip 解压（叶子目录解出来是 528KB / 4096 项），这些都在 JS 层。
 * 一屏几百块瓦片同时加载时，这些计算全部堆在主线程上，实测造成
 * 80~136ms 的连续长任务，帧率掉到 50fps 以下、最差帧 200ms。
 *
 * 移到 Worker 后主线程只剩「拿到 ArrayBuffer → 建 blob URL → 塞给 img」，
 * 计算全部在 Worker 线程完成。
 *
 * 协议：
 *   主线程 -> { id, z, x, y }
 *   Worker -> { id, data: ArrayBuffer | null }       成功
 *           | { id, error: string }                  失败
 * data 用 Transferable 转移所有权，避免拷贝。
 */

importScripts('lib/pmtiles.js');

let pm = null;
try {
  pm = new pmtiles.PMTiles(
    'data/uom-shifei.pmtiles',
    new pmtiles.SharedPromiseCache(1000)   // 默认只有 100 条，一屏就挤爆
  );
} catch (e) {
  pm = null;
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
  self.postMessage({ ready: false, error: 'PMTiles 初始化失败' });
}

self.onmessage = function (ev) {
  const m = ev.data;
  if (!m || !pm) {
    if (m && m.id) self.postMessage({ id: m.id, error: 'PMTiles 不可用' });
    return;
  }
  pm.getZxy(m.z, m.x, m.y).then(function (res) {
    if (res && res.data && res.data.byteLength) {
      const buf = res.data;
      /* 转移所有权，零拷贝 */
      self.postMessage({ id: m.id, data: buf }, [buf]);
    } else {
      self.postMessage({ id: m.id, data: null });
    }
  }).catch(function (e) {
    self.postMessage({ id: m.id, error: String((e && e.message) || e) });
  });
};
