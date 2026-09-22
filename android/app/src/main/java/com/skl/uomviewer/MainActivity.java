package com.skl.uomviewer;

import android.Manifest;
import android.annotation.SuppressLint;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.util.Log;
import android.view.ViewGroup;
import android.webkit.GeolocationPermissions;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;

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
 *
 * 定位：
 *   WebView 里的 navigator.geolocation 有两个前置条件，缺一个都会失败：
 *     ① 宿主 App 拿到系统位置权限（Android 6+ 必须运行时申请，光声明不够）
 *     ② 处理 onGeolocationPermissionsShowPrompt 回调，否则页面发出的
 *        定位请求没人应答 —— 表现为"权限问题"，但系统权限其实是给了的
 *   这两件事之前都漏了，导致移动端定位一直不可用。
 */
public class MainActivity extends AppCompatActivity {

    private static final String TAG = "MainActivity";

    /** 运行时权限请求码。只用于定位，与其它请求码不会冲突。 */
    private static final int REQ_LOCATION = 1001;

    private WebView webView;
    private LocalAssetServer server;

    /**
     * 页面发起的定位请求暂存在这里：Android 的权限对话框是异步的，
     * 用户点完之后才轮到 WebView 的回调，所以必须把"谁在等"记下来。
     */
    private GeolocationPermissions.Callback pendingGeoCallback;
    private String pendingGeoOrigin;

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

        /* 注入原生存储桥，名为 UomNativeStorage。
           为什么需要它：localStorage 按 origin 隔离，而页面是从
           http://127.0.0.1:<port>/ 加载的 —— 端口一变 origin 就变，
           API key / 收藏 / 主题字号全部读不到（用户报的"切后台回来数据没了"）。
           存进 SharedPreferences 就与 origin 无关了。
           必须在 loadUrl 之前注入，否则页面启动时读不到已有数据。 */
        webView.addJavascriptInterface(new StorageBridge(this), "UomNativeStorage");

        webView.setWebViewClient(new WebViewClient());
        /* 关键：WebView 里的 navigator.geolocation 会先问宿主
           "这个源能不能用定位"。默认实现是不应答 = 当作拒绝，
           于是页面拿到的是权限错误 —— 而系统权限可能已经给了，
           所以现象会非常像"你没申请权限"。
           这里接住请求：有系统权限就直接放行，没有就先去要权限。 */
        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onGeolocationPermissionsShowPrompt(
                    String origin, GeolocationPermissions.Callback callback) {
                Log.i(TAG, "页面请求定位: " + origin);
                if (hasLocationPermission()) {
                    callback.invoke(origin, true, false);   // 允许，且不记住
                } else {
                    // 先记下来，等用户点了权限对话框再回调
                    pendingGeoCallback = callback;
                    pendingGeoOrigin = origin;
                    requestLocationPermission();
                }
            }
        });

        /* 启动时先申请一次定位权限。
           为什么不等用户点"定位"再申请：WebView 的定位回调是异步的，
           若首次就在那一刻才弹权限框，用户点完还要再等一轮，
           而页面上没有任何反馈，看起来像"点了没反应"。
           启动时申请掉，用户点定位时通常已经就绪。 */
        if (!hasLocationPermission()) requestLocationPermission();

        // 先起本地服务，再加载页面。端口由系统分配，避免与其它应用冲突。
        server = new LocalAssetServer(this);
        int port = server.start();   // 内部优先用固定端口，被占用才回退
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

    /* ---------------- 定位权限 ---------------- */

    /** 精确或粗略位置有一个就算有权限。 */
    private boolean hasLocationPermission() {
        return ContextCompat.checkSelfPermission(this,
                   Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
            || ContextCompat.checkSelfPermission(this,
                   Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED;
    }

    /**
     * 申请定位权限。
     * 优先同时要"精确+粗略"：Android 12 起用户可以在权限框里只授予"大致位置"，
     * 那时粗略权限会被单独授予，只请求精确会被系统忽略该项。
     */
    private void requestLocationPermission() {
        ActivityCompat.requestPermissions(this, new String[]{
                Manifest.permission.ACCESS_FINE_LOCATION,
                Manifest.permission.ACCESS_COARSE_LOCATION
        }, REQ_LOCATION);
    }

    @Override
    public void onRequestPermissionsResult(int requestCode,
                                           @NonNull String[] permissions,
                                           @NonNull int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != REQ_LOCATION) return;

        boolean granted = grantResults.length > 0
                && grantResults[0] == PackageManager.PERMISSION_GRANTED;
        Log.i(TAG, "定位权限申请结果: " + granted);

        // 把结果回给正在等待的页面请求（如果有）
        if (pendingGeoCallback != null) {
            pendingGeoCallback.invoke(pendingGeoOrigin, granted, false);
            pendingGeoCallback = null;
            pendingGeoOrigin = null;
        }
        if (!granted) {
            Toast.makeText(this,
                    "未授予定位权限，可在系统设置 → 应用 → 权限 里开启；"
                    + "也可以直接在搜索框输入坐标查询",
                    Toast.LENGTH_LONG).show();
        }
    }

    @Override
    protected void onDestroy() {
        if (server != null) { server.stop(); server = null; }
        if (webView != null) { webView.destroy(); webView = null; }
        super.onDestroy();
    }
}
