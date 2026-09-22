package com.skl.uomviewer;

import android.annotation.SuppressLint;
import android.os.Bundle;
import android.util.Log;
import android.view.ViewGroup;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.Toast;

import androidx.appcompat.app.AppCompatActivity;

/**
 * UOM 适飞空域查询 —— Android 客户端。
 *
 * 数据全部内置在 APK 里（85MB PMTiles + 大疆 GeoJSON），完全离线可用。
 * 不再依赖 GitHub Pages —— 实测在中国大陆首次建连要 10~15 秒，
 * 而无人机使用场景常在野外没有稳定网络，所以必须内置。
 *
 * 关键点：内置数据也必须走 HTTP 才能用。
 *   PMTiles 靠 HTTP Range（206）按需读字节，而 WebView 的 assets:// 与
 *   file:// 都不支持 Range，直接读会失败。所以应用启动时在 127.0.0.1
 *   起一个只读 assets 的本地 HTTP 服务（见 LocalAssetServer），
 *   页面通过 http://127.0.0.1:<port>/ 访问 —— 与本地开发时用
 *   python serve.py 完全同构，因此页面代码不需要为移动端做任何特化。
 */
public class MainActivity extends AppCompatActivity {

    private WebView webView;
    private LocalAssetServer server;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        FrameLayout root = new FrameLayout(this);
        root.setLayoutParams(new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        webView = new WebView(this);
        root.addView(webView, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(root);

        WebSettings s = webView.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);          // 页面用 localStorage 存设置与收藏
        s.setAllowFileAccess(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setSupportZoom(true);
        s.setBuiltInZoomControls(true);
        s.setDisplayZoomControls(false);
        // 底图是第三方瓦片，部分图源走 http，需要允许混合内容
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);

        webView.setWebViewClient(new WebViewClient());
        webView.setWebChromeClient(new WebChromeClient());

        // 先起本地服务，再加载页面。端口由系统分配，避免与其它应用冲突。
        server = new LocalAssetServer(this);
        int port = server.start();
        if (port > 0) {
            webView.loadUrl("http://127.0.0.1:" + port + "/index.html");
        } else {
            // 服务起不来就没有可用的数据通道，如实告诉用户而不是白屏
            Log.e("MainActivity", "本地数据服务启动失败");
            Toast.makeText(this,
                    "本地数据服务启动失败，无法读取内置数据", Toast.LENGTH_LONG).show();
            webView.loadData(
                    "<html><body style='font-family:sans-serif;padding:24px;color:#333'>"
                    + "<h3>本地数据服务启动失败</h3>"
                    + "<p>内置数据需要本地 HTTP 服务才能读取（PMTiles 依赖 Range 请求）。</p>"
                    + "<p>请重启应用；若仍失败请反馈。</p></body></html>",
                    "text/html; charset=utf-8", "UTF-8");
        }
    }

    /** 返回键优先让页面内的历史回退，其次才退出应用。 */
    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onDestroy() {
        if (server != null) { server.stop(); server = null; }
        if (webView != null) { webView.destroy(); webView = null; }
        super.onDestroy();
    }
}
