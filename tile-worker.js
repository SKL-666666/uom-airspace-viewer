/* PMTiles 取数 Worker（批量模式）。
 *
 * 为什么需要 Worker：PMTiles 每次取瓦片都要 varint 解码、目录二分查找、
 * gzip 解压，这些都在 JS 层，堆在主线程上会造成 80~136ms 的长任务。
 *
 * 为什么要批量：一屏需要 40 多张瓦片，逐张取就是 40 多个 HTTP 请求，
 * 而浏览器对同一域名只开 6 条连接。实测发现 PMTiles 的数据是 clustered
 * 存放的（tile_id 顺序 == 文件偏移顺序），同一屏瓦片的 tile_id 跨度通常
 * 只有一两百，因此可以把相邻瓦片合并成少量字节区间，一个 Range 请求取回：
 *
 *   陕西 z13:  45 张瓦片 ->  6 个请求   传输 12.0KB -> 6.4KB
 *   山西 z7 :  40 张瓦片 ->  8 个请求   传输 50.1KB -> 50.1KB
 *   全国 z11:  29 张瓦片 ->  8 个请求   传输 13.2KB -> 12.8KB
 *   新疆 z9 :  42 张瓦片 ->  8 个请求   传输 16.8KB -> 14.5KB
 *
 * 请求数降到约 1/5，字节几乎不膨胀（有时反而更少，因为区间内本就连续）。
 *
 * 协议：
 *   主线程 -> { batch:true, id, tiles:[[z,x,y],...] }
 *   Worker -> { id, results:[{z,x,y,data:ArrayBuffer|null}|{z,x,y,error}] }
 *           已加 stat:true 的消息用于统计上报
 *   单个模式 { id, z, x, y } 仍保留，作为批量失败时的回退。
 */

importScripts('lib/pmtiles.js');

const URL_PMTILES = 'data/uom-shifei.pmtiles';
/* 合并阈值：两个瓦片字节区间之间空隙小于它就并进同一个 Range 请求。
   取 256 字节 —— 空隙的代价远低于多一次请求的往返。 */
const MERGE_GAP = 256;
/* 单个 Range 请求的上限，避免一次拉太多（异常数据时兜底） */
const MAX_RANGE = 4 * 1024 * 1024;

const source = new pmtiles.FetchSource(URL_PMTILES);
/* 库在 Windows+Chromium 上会给每个请求带 cache:"no-store"，导致浏览器
   HTTP 缓存完全失效。它这么做是因为 Chrome 对 206 分片响应的缓存需要
   校验器，缺少时拼接可能出错 —— 服务端已补 Last-Modified/ETag，可安全关闭。 */
source.chromeWindowsNoCache = false;

/* ---------------- varint / 目录解析 ----------------
   移植自 Python 版（pmtiles_tool.py），逻辑一一对应，已在 Node 里做过
   逐字节一致性验证。 */
function readVarint(buf, pos){
  let result = 0, shift = 0, b;
  do {
    b = buf[pos++];
    result |= (b & 0x7f) << shift;
    shift += 7;
  } while (b & 0x80);
  return [result, pos];
}

function deserializeIndex(buf){
  let pos = 0, num;
  [num, pos] = readVarint(buf, pos);
  const entries = new Array(num);
  let lastId = 0;
  for (let i = 0; i < num; i++){
    let v; [v, pos] = readVarint(buf, pos);
    lastId += v;
    entries[i] = { tileId: lastId, offset: 0, length: 0, runLength: 1 };
  }
  for (let i = 0; i < num; i++){ let v; [v, pos] = readVarint(buf, pos); entries[i].runLength = v; }
  for (let i = 0; i < num; i++){ let v; [v, pos] = readVarint(buf, pos); entries[i].length = v; }
  for (let i = 0; i < num; i++){
    let v; [v, pos] = readVarint(buf, pos);
    if (v === 0 && i > 0) entries[i].offset = entries[i-1].offset + entries[i-1].length;
    else entries[i].offset = v - 1;
  }
  return entries;
}

const TZ = [0];
for (let z = 1; z < 27; z++) TZ.push(TZ[z-1] + (1 << (2*(z-1))));

function zxyToTileId(z, x, y){
  let acc = TZ[z], d = 0, n = 1 << z;
  let tx = x, ty = y;
  for (let s = n >> 1; s > 0; s >>= 1){
    const rx = (tx & s) > 0 ? 1 : 0;
    const ry = (ty & s) > 0 ? 1 : 0;
    d += s * s * ((3 * rx) ^ ry);
    // rotate
    if (ry === 0){
      if (rx === 1){ tx = s - 1 - tx; ty = s - 1 - ty; }
      const t = tx; tx = ty; ty = t;
    }
  }
  return acc + d;
}

async function gunzip(buf){
  const ds = new DecompressionStream('gzip');
  const stream = new Blob([buf]).stream().pipeThrough(ds);
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

/* ---------------- 目录与取数 ---------------- */
const DIR = {
  header: null,
  root: null,
  leafCache: new Map(),     // "off/len" -> entries
  ready: false,
  error: ''
};

async function readBytes(offset, length){
  const r = await source.getBytes(offset, length);
  return new Uint8Array(r.data);
}

async function readDirectory(offset, length){
  const key = offset + '/' + length;
  let cached = DIR.leafCache.get(key);
  if (cached) return cached;
  let raw = await readBytes(offset, length);
  if (DIR.header.internalCompression === 2) raw = await gunzip(raw);
  const entries = deserializeIndex(raw);
  if (DIR.leafCache.size > 64) DIR.leafCache.clear();
  DIR.leafCache.set(key, entries);
  return entries;
}

async function initDir(){
  if (DIR.ready) return;
  const h = await readBytes(0, 127);
  const magic = String.fromCharCode(h[0],h[1],h[2],h[3],h[4],h[5],h[6]);
  if (magic !== 'PMTiles') throw new Error('不是 PMTiles 文件');
  const dv = new DataView(h.buffer, h.byteOffset, h.byteLength);
  DIR.header = {
    version: h[7],
    rootOffset: Number(dv.getBigUint64(8, true)),
    rootLength: Number(dv.getBigUint64(16, true)),
    leafOffset: Number(dv.getBigUint64(40, true)),
    dataOffset: Number(dv.getBigUint64(56, true)),
    internalCompression: h[97],
    tileCompression: h[98],
    tileType: h[99],
    minZoom: h[100], maxZoom: h[101],
    minLon: dv.getInt32(102, true)/1e7, minLat: dv.getInt32(106, true)/1e7,
    maxLon: dv.getInt32(110, true)/1e7, maxLat: dv.getInt32(114, true)/1e7
  };
  const rootRaw = await readBytes(DIR.header.rootOffset, DIR.header.rootLength);
  const rootBuf = DIR.header.internalCompression === 2 ? await gunzip(rootRaw) : rootRaw;
  DIR.root = deserializeIndex(rootBuf);
  DIR.ready = true;
}

/* 二分查找最后一个 tileId <= 目标的项 */
function bsearch(entries, tileId){
  let lo = 0, hi = entries.length - 1, m = -1;
  while (lo <= hi){
    const mid = (lo + hi) >> 1;
    if (entries[mid].tileId <= tileId){ m = mid; lo = mid + 1; }
    else hi = mid - 1;
  }
  return m;
}

async function findEntry(tileId){
  let entries = DIR.root, depth = 0;
  while (entries && depth < 4){
    const i = bsearch(entries, tileId);
    if (i < 0) return null;
    const e = entries[i];
    if (e.runLength === 0){
      entries = await readDirectory(DIR.header.leafOffset + e.offset, e.length);
      depth++;
      continue;
    }
    if (e.tileId <= tileId && tileId < e.tileId + e.runLength) return e;
    return null;
  }
  return null;
}

/* 取一批瓦片：合并相邻区间，用尽量少的 Range 请求拉回，再按各瓦片切出来 */
async function fetchBatch(tiles){
  const out = new Array(tiles.length).fill(null);
  const found = [];
  for (let i = 0; i < tiles.length; i++){
    const [z, x, y] = tiles[i];
    if (z < DIR.header.minZoom || z > DIR.header.maxZoom) continue;
    const e = await findEntry(zxyToTileId(z, x, y));
    if (e) found.push({ i, offset: DIR.header.dataOffset + e.offset, length: e.length });
  }
  if (!found.length) return { out: out, ranges: 0 };

  found.sort((a, b) => a.offset - b.offset);
  const ranges = [];
  let s = found[0].offset, e = found[0].offset + found[0].length;
  for (const f of found.slice(1)){
    const end = f.offset + f.length;
    if (f.offset - e <= MERGE_GAP && (end - s) <= MAX_RANGE){
      if (end > e) e = end;
    } else {
      ranges.push([s, e]); s = f.offset; e = end;
    }
  }
  ranges.push([s, e]);

  const buffers = [];
  for (const [a, b] of ranges){
    const raw = await readBytes(a, b - a);
    buffers.push({ a, buf: raw });
  }
  for (const f of found){
    for (const { a, buf } of buffers){
      if (f.offset >= a && f.offset + f.length <= a + buf.length){
        const slice = buf.subarray(f.offset - a, f.offset - a + f.length);
        out[f.i] = slice.buffer.slice(slice.byteOffset, slice.byteOffset + slice.byteLength);
        break;
      }
    }
  }
  return { out: out, ranges: ranges.length };
}

/* ---------------- 统计 ---------------- */
let stat = { batches: 0, tilesReq: 0, ranges: 0, ms: 0, maxMs: 0 };
let statTimer = null;
function flushStat(){
  if (statTimer) return;
  statTimer = setTimeout(() => {
    statTimer = null;
    if (!stat.batches) return;
    self.postMessage({ stat: true, batches: stat.batches, tiles: stat.tilesReq,
                       ranges: stat.ranges,
                       avgMs: +(stat.ms / stat.batches).toFixed(1),
                       maxMs: Math.round(stat.maxMs) });
    stat = { batches: 0, tilesReq: 0, ranges: 0, ms: 0, maxMs: 0 };
  }, 300);
}

/* ---------------- 消息处理 ---------------- */
async function handleBatch(m){
  const t0 = performance.now();
  try {
    await initDir();
    const r = await fetchBatch(m.tiles);
    const results = r.out;
    const payload = m.tiles.map((t, i) => ({ z: t[0], x: t[1], y: t[2], data: results[i] }));
    const transfer = payload.filter(p => p.data).map(p => p.data);
    const ms = performance.now() - t0;
    stat.batches++; stat.ms += ms;
    if (ms > stat.maxMs) stat.maxMs = ms;
    stat.tilesReq += m.tiles.length;
    stat.ranges += r.ranges;
    self.postMessage({ id: m.id, results: payload }, transfer);
  } catch (e){
    self.postMessage({ id: m.id, error: String((e && e.message) || e) });
  }
  flushStat();
}

async function handleSingle(m){
  const t0 = performance.now();
  try {
    await initDir();
    const rb = await fetchBatch([[m.z, m.x, m.y]]);
    const data = rb.out[0];
    const ms = performance.now() - t0;
    stat.batches++; stat.ms += ms; stat.tilesReq++;
    if (ms > stat.maxMs) stat.maxMs = ms;
    if (data) self.postMessage({ id: m.id, data }, [data]);
    else self.postMessage({ id: m.id, data: null });
  } catch (e){
    self.postMessage({ id: m.id, error: String((e && e.message) || e) });
  }
  flushStat();
}

self.onmessage = function (ev){
  const m = ev.data;
  if (!m) return;
  if (m.batch) handleBatch(m);
  else handleSingle(m);
};

/* 启动后先把目录读进来，并回报范围 */
initDir().then(() => {
  const h = DIR.header;
  self.postMessage({ ready: true, header: {
    tileType: h.tileType, minZoom: h.minZoom, maxZoom: h.maxZoom,
    minLon: h.minLon, minLat: h.minLat, maxLon: h.maxLon, maxLat: h.maxLat } });
}).catch(e => {
  self.postMessage({ ready: false, error: String((e && e.message) || e) });
});
