package com.skl.uomviewer;

import android.annotation.SuppressLint;
import android.os.Bundle;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.Toast;

import androidx.appcompat.app.AppCompatActivity;

/**
 * UOM 适飞空域查询 —— Android 客户端（WebView 外壳）。
 *
 * 页面用 WebView 直接加载线上站点：GitHub Pages 支持 HTTP Range 请求，
 * 而 PMTiles 正是靠 Range 按需读取字节，所以纯静态环境即可工作，
 * 不需要在客户端内置 85MB 数据。
 *
 * 长按标题栏可切换为本地服务地址（配合同一局域网内的 python serve.py），
 * 本地服务额外提供 /diag/* 诊断端点。
 */
public class MainActivity extends AppCompatActivity {

    private static final String REMOTE_URL =
            "https://skl-666666.github.io/uom-airspace-viewer/index.html";
    private static final String LOCAL_URL =
            "http://127.0.0.1:8080/index.html";

    private WebView webView;
    private boolean useLocal = false;

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
        s.setDomStorageEnabled(true);        // 页面用 localStorage 存底图 key
        s.setAllowFileAccess(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setSupportZoom(true);
        s.setBuiltInZoomControls(true);
        s.setDisplayZoomControls(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);

        webView.setWebViewClient(new WebViewClient());
        webView.setWebChromeClient(new WebChromeClient());

        // 长按任意位置切换线上/本地数据源
        webView.setOnLongClickListener(v -> {
            useLocal = !useLocal;
            String url = useLocal ? LOCAL_URL : REMOTE_URL;
            Toast.makeText(this, "切换到" + (useLocal ? "本地" : "线上") + "数据源",
                    Toast.LENGTH_SHORT).show();
            webView.loadUrl(url);
            return true;
        });

        webView.loadUrl(REMOTE_URL);
    }

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
        if (webView != null) {
            webView.destroy();
            webView = null;
        }
        super.onDestroy();
    }
}
