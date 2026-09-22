package com.skl.uomviewer;

import android.content.Context;
import android.content.res.AssetManager;
import android.util.Log;

import java.io.BufferedInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.PushbackInputStream;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * 应用内本地 HTTP 服务：把 APK 里的 assets 当成一个支持 Range 的静态站点。
 *
 * 为什么必须要它（这是整个内置方案的关键）：
 *   PMTiles 的读取方式是"先取头部 127 字节，再按目录跳着取指定字节区间"，
 *   全程依赖 HTTP Range（206）。而 WebView 的 assets:// / file:// 协议
 *   都是"只能整体读取"的，Range 请求拿不到 206，PMTiles 直接读不了。
 *   所以必须自己起一个支持 Range 的本地 HTTP 服务，让页面走
 *   http://127.0.0.1:port/ 访问 —— 和本地开发时用 python serve.py 是同一个道理。
 *
 * 实现要点：
 *   · 只读 assets，不写文件；85MB 数据不必解包到磁盘
 *   · 只监听 127.0.0.1，不对外暴露
 *   · 端口由系统分配（0），避免与其它应用冲突
 *   · Range 支持三种形式：bytes=a-b、bytes=a-、bytes=-n；越界返回 416
 *   · assets 的 InputStream 不能 seek，用 skip() 定位；已用循环跳过保证跨过
 *     skip 单次跳不远的限制（InputStream.skip 允许返回比请求更小的值）
 */
public class LocalAssetServer {

    private static final String TAG = "LocalAssetServer";

    private final AssetManager assets;
    private final ExecutorService pool = Executors.newFixedThreadPool(8);
    private ServerSocket server;
    private int port = -1;
    private volatile boolean running = false;

    public LocalAssetServer(Context ctx) {
        this.assets = ctx.getAssets();
    }

    /** 启动服务并返回端口。失败返回 -1。 */
    public int start() {
        try {
            // 绑定 127.0.0.1 而不是 0.0.0.0：这个服务只给本应用自己的 WebView 用，
            // 不能暴露到局域网。
            server = new ServerSocket(0, 64, InetAddress.getByName("127.0.0.1"));
            port = server.getLocalPort();
            running = true;
            Thread t = new Thread(this::acceptLoop, "asset-http");
            t.setDaemon(true);
            t.start();
            Log.i(TAG, "本地服务已启动 http://127.0.0.1:" + port);
            return port;
        } catch (IOException e) {
            Log.e(TAG, "启动失败: " + e.getMessage());
            return -1;
        }
    }

    public int getPort() { return port; }

    public void stop() {
        running = false;
        try { if (server != null) server.close(); } catch (IOException ignored) {}
        pool.shutdownNow();
    }

    private void acceptLoop() {
        while (running) {
            try {
                final Socket s = server.accept();
                pool.execute(() -> handle(s));
            } catch (IOException e) {
                if (running) Log.w(TAG, "accept 异常: " + e.getMessage());
            }
        }
    }

    private static final Map<String, String> MIME = new HashMap<>();
    static {
        MIME.put("html", "text/html; charset=utf-8");
        MIME.put("js", "text/javascript; charset=utf-8");
        MIME.put("css", "text/css; charset=utf-8");
        MIME.put("json", "application/json; charset=utf-8");
        MIME.put("geojson", "application/geo+json; charset=utf-8");
        MIME.put("pmtiles", "application/octet-stream");
        MIME.put("png", "image/png");
        MIME.put("jpg", "image/jpeg");
        MIME.put("svg", "image/svg+xml");
        MIME.put("ico", "image/x-icon");
        MIME.put("txt", "text/plain; charset=utf-8");
        MIME.put("md", "text/plain; charset=utf-8");
        MIME.put("webp", "image/webp");
    }

    private static String mimeOf(String path) {
        int i = path.lastIndexOf('.');
        if (i < 0) return "application/octet-stream";
        String ext = path.substring(i + 1).toLowerCase(Locale.US);
        String m = MIME.get(ext);
        return m != null ? m : "application/octet-stream";
    }

    private void handle(Socket sock) {
        try {
            sock.setSoTimeout(15000);
            PushbackInputStream in = new PushbackInputStream(
                    new BufferedInputStream(sock.getInputStream(), 8192), 4096);
            String requestLine = readLine(in);
            if (requestLine == null) { sock.close(); return; }

            // 读掉请求头，找出 Range
            String range = null;
            String line;
            int headerCount = 0;
            while ((line = readLine(in)) != null && !line.isEmpty() && headerCount++ < 100) {
                int c = line.indexOf(':');
                if (c > 0) {
                    String k = line.substring(0, c).trim().toLowerCase(Locale.US);
                    if (k.equals("range")) range = line.substring(c + 1).trim();
                }
            }

            String[] parts = requestLine.split(" ");
            if (parts.length < 2) { sock.close(); return; }
            String method = parts[0];
            String rawPath = parts[1];
            boolean headOnly = "HEAD".equalsIgnoreCase(method);

            // 去掉查询串与 fragment，并做一次最简的路径规范化
            String path = rawPath;
            int q = path.indexOf('?');
            if (q >= 0) path = path.substring(0, q);
            int h = path.indexOf('#');
            if (h >= 0) path = path.substring(0, h);
            try { path = java.net.URLDecoder.decode(path, "UTF-8"); } catch (Exception ignored) {}
            if (path.startsWith("/")) path = path.substring(1);
            if (path.isEmpty()) path = "index.html";
            // 目录式访问（如 /data/）补 index.html
            if (path.endsWith("/")) path += "index.html";
            // 拒绝上跳，避免越出 assets
            if (path.contains("..")) { sendError(sock, 403, "Forbidden"); return; }

            long size;
            try {
                size = assetSize(path);
            } catch (IOException e) {
                sendError(sock, 404, "Not Found: " + path);
                return;
            }

            long start = 0, end = size - 1;
            boolean partial = false;
            if (range != null && range.startsWith("bytes=")) {
                String spec = range.substring(6).trim();
                int dash = spec.indexOf('-');
                if (dash >= 0) {
                    String a = spec.substring(0, dash).trim();
                    String b = spec.substring(dash + 1).trim();
                    try {
                        if (a.isEmpty() && !b.isEmpty()) {
                            // bytes=-N：最后 N 字节
                            long n = Long.parseLong(b);
                            if (n <= 0) { sendRangeNotSatisfiable(sock, size); return; }
                            start = Math.max(0, size - n);
                            end = size - 1;
                        } else if (!a.isEmpty()) {
                            start = Long.parseLong(a);
                            end = b.isEmpty() ? size - 1 : Math.min(Long.parseLong(b), size - 1);
                        }
                    } catch (NumberFormatException e) {
                        sendRangeNotSatisfiable(sock, size);
                        return;
                    }
                    if (start < 0 || start >= size || end < start) {
                        // 越界必须回 416 并带 Content-Range: bytes */size，
                        // PMTiles 靠这个判断"读到头了"。
                        sendRangeNotSatisfiable(sock, size);
                        return;
                    }
                    partial = true;
                }
            }

            long len = end - start + 1;
            StringBuilder hd = new StringBuilder();
            hd.append(partial ? "HTTP/1.1 206 Partial Content\r\n"
                              : "HTTP/1.1 200 OK\r\n");
            hd.append("Content-Type: ").append(mimeOf(path)).append("\r\n");
            hd.append("Content-Length: ").append(len).append("\r\n");
            hd.append("Accept-Ranges: bytes\r\n");
            if (partial) {
                hd.append("Content-Range: bytes ").append(start).append('-')
                  .append(end).append('/').append(size).append("\r\n");
            }
            // 本地资源随 APK 版本变化，用 no-cache 避免 WebView 拿到旧文件
            hd.append("Cache-Control: no-cache\r\n");
            hd.append("Connection: close\r\n\r\n");

            OutputStream out = sock.getOutputStream();
            out.write(hd.toString().getBytes("UTF-8"));
            if (!headOnly) {
                try (InputStream is = assets.open(path)) {
                    skipFully(is, start);
                    copyN(is, out, len);
                }
            }
            out.flush();
        } catch (Exception e) {
            Log.w(TAG, "处理请求异常: " + e.getMessage());
        } finally {
            try { sock.close(); } catch (IOException ignored) {}
        }
    }

    /**
     * 取 assets 里某个文件的大小。
     * AssetManager.open 返回的流不支持 available() 拿全长，
     * 这里用 openFd 的 length（未压缩条目才有效），失败再退回读流计数。
     * 注意：assets 里的文件若被 aapt 压缩，openFd 会抛异常。
     * 所以构建时必须对 .pmtiles 声明 noCompress，否则这里会退化成整文件读一遍，
     * 85MB 每次请求都读一遍会非常慢。
     */
    private long assetSize(String path) throws IOException {
        try {
            android.content.res.AssetFileDescriptor fd = assets.openFd(path);
            long n = fd.getLength();
            fd.close();
            if (n > 0) return n;
        } catch (IOException ignored) {
            // 被压缩或不支持，走下面的计数方式
        }
        long n = 0;
        try (InputStream is = assets.open(path)) {
            byte[] buf = new byte[65536];
            int r;
            while ((r = is.read(buf)) > 0) n += r;
        }
        return n;
    }

    /** InputStream.skip 允许少跳，必须循环直到跳够。 */
    private static void skipFully(InputStream is, long n) throws IOException {
        long left = n;
        while (left > 0) {
            long s = is.skip(left);
            if (s <= 0) {
                // skip 返回 0 时改用读丢弃，避免死循环
                if (is.read() < 0) break;
                left--;
            } else {
                left -= s;
            }
        }
    }

    private static void copyN(InputStream is, OutputStream out, long n) throws IOException {
        byte[] buf = new byte[65536];
        long left = n;
        while (left > 0) {
            int want = (int) Math.min(buf.length, left);
            int r = is.read(buf, 0, want);
            if (r < 0) break;
            out.write(buf, 0, r);
            left -= r;
        }
    }

    private static String readLine(InputStream in) throws IOException {
        StringBuilder sb = new StringBuilder(128);
        int c;
        while ((c = in.read()) >= 0) {
            if (c == '\n') break;
            if (c != '\r') sb.append((char) c);
            if (sb.length() > 8192) break;
        }
        return sb.length() == 0 && c < 0 ? null : sb.toString();
    }

    private static void sendError(Socket sock, int code, String msg) {
        try {
            byte[] body = msg.getBytes("UTF-8");
            String hd = "HTTP/1.1 " + code + " " + msg + "\r\n"
                    + "Content-Type: text/plain; charset=utf-8\r\n"
                    + "Content-Length: " + body.length + "\r\n"
                    + "Connection: close\r\n\r\n";
            OutputStream out = sock.getOutputStream();
            out.write(hd.getBytes("UTF-8"));
            out.write(body);
            out.flush();
        } catch (IOException ignored) {}
    }

    private static void sendRangeNotSatisfiable(Socket sock, long size) {
        try {
            String hd = "HTTP/1.1 416 Range Not Satisfiable\r\n"
                    + "Content-Range: bytes */" + size + "\r\n"
                    + "Content-Length: 0\r\n"
                    + "Accept-Ranges: bytes\r\n"
                    + "Connection: close\r\n\r\n";
            OutputStream out = sock.getOutputStream();
            out.write(hd.getBytes("UTF-8"));
            out.flush();
        } catch (IOException ignored) {}
    }
}
