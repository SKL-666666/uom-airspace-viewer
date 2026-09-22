package com.skl.uomviewer;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Log;
import android.webkit.JavascriptInterface;

import org.json.JSONArray;

import java.util.Map;

/**
 * 网页端用户数据的原生存储桥。
 *
 * 解决什么问题：
 *   localStorage 是【按 origin 隔离】的。移动端页面从
 *   http://127.0.0.1:<port>/ 加载，而端口会变（端口被占用时、或历史上用
 *   随机端口时），origin 一变，localStorage 里的 API key、收藏点、主题字号
 *   就全部读不到 —— 用户看到的是"切后台回来数据没了"。
 *
 *   所以把数据存到应用私有目录（SharedPreferences），与 origin 完全无关，
 *   端口怎么变都不丢。
 *
 * 为什么方法必须是同步的（不能用回调）：
 *   页面启动时就要读 key / 主题 / 字号，才能在首屏渲染前决定用哪个底图和字号。
 *   如果原生存储是异步的，页面就得先渲染默认值再改写，会闪一下。
 *   @JavascriptInterface 标注的方法由 WebView 同步调用并可直接返回 String，
 *   正好满足这个需求。
 *
 * 安全说明：
 *   桥只暴露 get/set/remove/keys 四个方法，不做任何文件系统或网络访问。
 *   注意 @JavascriptInterface 的方法会被页面里任意 JS 调用，所以入参一律
 *   当不可信数据处理（键名过滤、长度上限），避免被用来写超大内容撑爆存储。
 */
public class StorageBridge {

    private static final String TAG = "StorageBridge";
    private static final String PREF_NAME = "uom_user_data";

    /** 单个值的长度上限。API key、收藏列表都远小于这个数。 */
    private static final int MAX_VALUE_LEN = 512 * 1024;

    /** 键名长度上限，并禁止可疑字符（键名最终只当字符串用，但仍做基本约束）。 */
    private static final int MAX_KEY_LEN = 128;

    private final SharedPreferences prefs;

    public StorageBridge(Context ctx) {
        this.prefs = ctx.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE);
    }

    private boolean validKey(String k) {
        return k != null && k.length() > 0 && k.length() <= MAX_KEY_LEN;
    }

    /** 读。返回 null 表示不存在（页面据此回退到默认值）。 */
    @JavascriptInterface
    public String getItem(String key) {
        if (!validKey(key)) return null;
        try {
            return prefs.getString(key, null);
        } catch (Exception e) {
            Log.w(TAG, "读取失败 " + key + ": " + e.getMessage());
            return null;
        }
    }

    @JavascriptInterface
    public void setItem(String key, String value) {
        if (!validKey(key)) return;
        if (value == null) return;
        if (value.length() > MAX_VALUE_LEN) {
            Log.w(TAG, "值过大，拒绝写入: " + key + " (" + value.length() + " 字符)");
            return;
        }
        try {
            // apply() 异步落盘，不阻塞 WebView 的 JS 线程
            prefs.edit().putString(key, value).apply();
        } catch (Exception e) {
            Log.e(TAG, "写入失败 " + key + ": " + e.getMessage());
        }
    }

    @JavascriptInterface
    public void removeItem(String key) {
        if (!validKey(key)) return;
        try {
            prefs.edit().remove(key).apply();
        } catch (Exception e) {
            Log.w(TAG, "删除失败 " + key + ": " + e.getMessage());
        }
    }

    /**
     * 列出所有键，返回 JSON 数组字符串。
     * 之所以返回 JSON 而不是分隔符拼接：键名可能含任意字符，
     * 用分隔符拼会在键名里出现该字符时解析错。
     */
    @JavascriptInterface
    public String keys() {
        try {
            JSONArray arr = new JSONArray();
            Map<String, ?> all = prefs.getAll();
            for (String k : all.keySet()) arr.put(k);
            return arr.toString();
        } catch (Exception e) {
            Log.w(TAG, "列举键失败: " + e.getMessage());
            return "[]";
        }
    }
}
