import { socket } from '@kit.NetworkKit';
import { fileIo } from '@kit.CoreFileKit';
import { common } from '@kit.AbilityKit';
/* resourceManager 在 LocalizationKit 里，不在 AbilityKit ——
   编译器直接报了 'not exported from Kit AbilityKit'，已改正。 */
import { resourceManager } from '@kit.LocalizationKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { util } from '@kit.ArkTS';

const DOMAIN = 0x0000;

/**
 * 应用内本地 HTTP 服务（HarmonyOS）：把 rawfile 里的静态资源以支持 Range 的形式提供。
 *
 * 为什么要自己起服务：
 *   PMTiles 靠 HTTP Range（206）跳着读字节。ArkWeb 直接用 rawfile:// 或 file://
 *   加载时不走 HTTP，拿不到 206，PMTiles 第一步"读 127 字节头部"就会失败，
 *   表现为地图一片空白。所以必须有一个 http://127.0.0.1:port/ 的入口。
 *
 * 为什么是【裸 TCP + 手写 HTTP】：
 *   查过 SDK 才确认：@ohos.net.http 只有客户端（createHttpRequest），
 *   没有 createHttpServer（我最初按印象写过，那是错的）。
 *   服务端能力在 @ohos.net.socket 的 TCPSocketServer，它只给字节流，
 *   HTTP 协议层要自己写。本项目只需 GET/HEAD + Range，手写是可控的。
 *
 * 关键：不做解包。
 *   getRawFd() 返回 {fd, offset, length}，而 fileIo.readSync 支持在 fd 上按
 *   offset 随机读 —— 也就是说 rawfile【本身就能随机访问】，不必把 85MB
 *   拷到私有目录。省掉一次 85MB 落盘，启动更快，也不额外占存储。
 *   读取时真实偏移 = descriptor.offset + Range 起点 + 已发送量。
 *
 * 前提：rawfile 资源不能被 HAP 压缩，否则 getRawFd 失败。
 *      构建配置需对 .pmtiles/.geojson 关闭压缩（见 entry/build-profile.json5）。
 */
export class RangeHttpServer {

  private server: socket.TCPSocketServer | null = null;
  private port: number = -1;
  private ctx: common.UIAbilityContext | null = null;

  /** 网页资源在 rawfile 里的前缀目录 */
  private static readonly RAW_PREFIX: string = 'web/';

  async init(ctx: common.UIAbilityContext): Promise<void> {
    this.ctx = ctx;
  }

  /**
   * 解析 Range 头。与 Android 侧 parseRange 逻辑一致，
   * 并由 test_range_server.py 覆盖同一套用例（越界 416、三种形式、边界值）。
   * 返回：[0]=0 整体 / 1 部分 / 2 越界；部分时 [1]=start [2]=end；越界时 [2]=size
   */
  static parseRange(spec: string, size: number): number[] {
    if (!spec || spec.indexOf('bytes=') !== 0) return [0, 0, size - 1];
    const s: string = spec.substring(6).trim();
    const dash: number = s.indexOf('-');
    if (dash < 0) return [0, 0, size - 1];
    const a: string = s.substring(0, dash).trim();
    const b: string = s.substring(dash + 1).trim();
    let start: number = 0;
    let end: number = size - 1;
    if (a.length === 0 && b.length > 0) {
      const n: number = parseInt(b, 10);
      if (!isFinite(n) || n <= 0) return [2, 0, size];
      start = Math.max(0, size - n);
      end = size - 1;
    } else if (a.length > 0) {
      start = parseInt(a, 10);
      end = b.length === 0 ? size - 1 : Math.min(parseInt(b, 10), size - 1);
      if (!isFinite(start) || !isFinite(end)) return [2, 0, size];
    } else {
      return [2, 0, size];
    }
    if (start < 0 || start >= size || end < start) return [2, 0, size];
    return [1, start, end];
  }

  private static mimeOf(path: string): string {
    const i: number = path.lastIndexOf('.');
    const ext: string = i < 0 ? '' : path.substring(i + 1).toLowerCase();
    if (ext === 'html') return 'text/html; charset=utf-8';
    if (ext === 'js') return 'text/javascript; charset=utf-8';
    if (ext === 'css') return 'text/css; charset=utf-8';
    if (ext === 'json') return 'application/json; charset=utf-8';
    if (ext === 'geojson') return 'application/geo+json; charset=utf-8';
    if (ext === 'pmtiles') return 'application/octet-stream';
    if (ext === 'png') return 'image/png';
    if (ext === 'jpg' || ext === 'jpeg') return 'image/jpeg';
    return 'application/octet-stream';
  }

  /** 启动监听回环地址，端口从 18080 起找空位。 */
  async start(): Promise<number> {
    for (let p = 18080; p < 18100; p++) {
      const srv = socket.constructTCPSocketServerInstance();
      try {
        await srv.listen({ address: '127.0.0.1', port: p });
      } catch (e) {
        try { await srv.close(); } catch (e2) { /* ignore */ }
        continue;                              // 端口被占，换下一个
      }
      srv.on('connect', (conn: socket.TCPSocketConnection) => this.onConnect(conn));
      srv.on('error', (err: BusinessError) => {
        hilog.error(DOMAIN, 'UOMViewer', '服务错误 %{public}s', JSON.stringify(err));
      });
      this.server = srv;
      this.port = p;
      hilog.info(DOMAIN, 'UOMViewer', '本地服务 http://127.0.0.1:%{public}d', p);
      return p;
    }
    hilog.error(DOMAIN, 'UOMViewer', '18080~18099 均被占用');
    return -1;
  }

  /**
   * 一条连接的处理。
   * 请求头可能跨多个 TCP 包，必须累积到出现 \r\n\r\n 才解析 ——
   * 假设"一个 message 就是一个完整请求"在真实网络下会偶发解析失败。
   */
  private onConnect(conn: socket.TCPSocketConnection): void {
    const chunks: Uint8Array[] = [];
    let parsed: boolean = false;

    conn.on('message', (info: socket.SocketMessageInfo) => {
      if (parsed) return;
      chunks.push(new Uint8Array(info.message));
      let total: number = 0;
      for (const c of chunks) total += c.byteLength;
      const all: Uint8Array = new Uint8Array(total);
      let off: number = 0;
      for (const c of chunks) { all.set(c, off); off += c.byteLength; }
      const text: string = new util.TextDecoder('utf-8').decodeToString(all);
      const end: number = text.indexOf('\r\n\r\n');
      if (end < 0) {
        if (total > 65536) this.reply(conn, 400, 'text/plain', 'Bad Request');
        return;                                // 还没收全，继续等
      }
      parsed = true;
      this.handleRequest(conn, text.substring(0, end));
    });

    conn.on('error', () => {
      try { conn.close(); } catch (e) { /* ignore */ }
    });
  }

  private handleRequest(conn: socket.TCPSocketConnection, head: string): void {
    const lines: string[] = head.split('\r\n');
    if (lines.length === 0) { this.reply(conn, 400, 'text/plain', 'Bad Request'); return; }
    const parts: string[] = lines[0].split(' ');
    if (parts.length < 2) { this.reply(conn, 400, 'text/plain', 'Bad Request'); return; }
    const method: string = parts[0].toUpperCase();
    const headOnly: boolean = method === 'HEAD';
    if (method !== 'GET' && !headOnly) {
      this.reply(conn, 405, 'text/plain', 'Method Not Allowed');
      return;
    }

    let rangeSpec: string = '';
    for (let i = 1; i < lines.length; i++) {
      const c: number = lines[i].indexOf(':');
      if (c <= 0) continue;
      if (lines[i].substring(0, c).trim().toLowerCase() === 'range') {
        rangeSpec = lines[i].substring(c + 1).trim();
      }
    }

    let path: string = parts[1];
    const q: number = path.indexOf('?');
    if (q >= 0) path = path.substring(0, q);
    if (path.startsWith('/')) path = path.substring(1);
    if (path.length === 0) path = 'index.html';
    if (path.indexOf('..') >= 0) { this.reply(conn, 403, 'text/plain', 'Forbidden'); return; }

    const ctx: common.UIAbilityContext | null = this.ctx;
    if (!ctx) { this.reply(conn, 500, 'text/plain', 'Not Initialized'); return; }
    const rawPath: string = RangeHttpServer.RAW_PREFIX + path;

    ctx.resourceManager.getRawFd(rawPath).then((fd: resourceManager.RawFileDescriptor) => {
      const size: number = fd.length;
      const base: number = fd.offset;

      const release = () => {
        ctx.resourceManager.closeRawFd(rawPath).catch(() => { /* ignore */ });
      };

      const r: number[] = RangeHttpServer.parseRange(rangeSpec, size);
      if (r[0] === 2) {
        // 越界必须 416 + Content-Range: bytes */size —— PMTiles 靠它判断读到末尾
        const h416: string = 'HTTP/1.1 416 Range Not Satisfiable\r\n'
          + 'Content-Range: bytes */' + size + '\r\n'
          + 'Accept-Ranges: bytes\r\nContent-Length: 0\r\nConnection: close\r\n\r\n';
        this.sendThenClose(conn, h416, release);
        return;
      }

      const partial: boolean = r[0] === 1;
      const start: number = partial ? r[1] : 0;
      const end: number = partial ? r[2] : size - 1;
      const len: number = end - start + 1;

      let h: string = 'HTTP/1.1 ' + (partial ? '206 Partial Content' : '200 OK') + '\r\n'
        + 'Content-Type: ' + RangeHttpServer.mimeOf(path) + '\r\n'
        + 'Content-Length: ' + len + '\r\n'
        + 'Accept-Ranges: bytes\r\n'
        + 'Cache-Control: no-cache\r\n';
      if (partial) {
        h += 'Content-Range: bytes ' + start + '-' + end + '/' + size + '\r\n';
      }
      h += 'Connection: close\r\n\r\n';

      if (headOnly) { this.sendThenClose(conn, h, release); return; }

      conn.send({ data: h }).then(() => {
        const CHUNK: number = 256 * 1024;
        let sent: number = 0;
        while (sent < len) {
          const n: number = Math.min(CHUNK, len - sent);
          const buf: ArrayBuffer = new ArrayBuffer(n);
          // 真实偏移 = rawfile 内偏移(base) + Range 起点 + 已发送量
          const read: number = fileIo.readSync(fd.fd, buf,
            { offset: base + start + sent, length: n });
          if (read <= 0) break;
          const slice: ArrayBuffer = read === n ? buf : buf.slice(0, read);
          conn.send({ data: slice });
          sent += read;
        }
      }).catch((err: BusinessError) => {
        hilog.error(DOMAIN, 'UOMViewer', '发送失败 %{public}s', JSON.stringify(err));
      }).finally(() => {
        release();
        setTimeout(() => { try { conn.close(); } catch (e) { /* ignore */ } }, 50);
      });
    }).catch((err: BusinessError) => {
      hilog.warn(DOMAIN, 'UOMViewer', '404 %{public}s (%{public}s)',
                 path, JSON.stringify(err));
      this.reply(conn, 404, 'text/plain; charset=utf-8', 'Not Found: ' + path);
    });
  }

  private sendThenClose(conn: socket.TCPSocketConnection, data: string,
                        after?: () => void): void {
    conn.send({ data: data }).then(() => {
      /* 关闭前留一点时间让数据发出去 */
    }).catch(() => {
      /* 对端已断开 */
    }).finally(() => {
      if (after) after();
      setTimeout(() => { try { conn.close(); } catch (e) { /* ignore */ } }, 50);
    });
  }

  private reply(conn: socket.TCPSocketConnection, code: number,
                mime: string, body: string): void {
    const enc: Uint8Array = new util.TextEncoder().encodeInto(body);
    const h: string = 'HTTP/1.1 ' + code + ' Error\r\n'
      + 'Content-Type: ' + mime + '\r\n'
      + 'Content-Length: ' + enc.byteLength + '\r\n'
      + 'Connection: close\r\n\r\n';
    conn.send({ data: h })
      .then(() => conn.send({ data: enc.buffer as ArrayBuffer }))
      .catch(() => { /* 对端已断开 */ })
      .finally(() => {
        setTimeout(() => { try { conn.close(); } catch (e) { /* ignore */ } }, 50);
      });
  }

  async stop(): Promise<void> {
    if (this.server) {
      try { await this.server.close(); } catch (e) { /* 已关闭 */ }
      this.server = null;
    }
  }

  getPort(): number { return this.port; }
}
