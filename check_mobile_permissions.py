# 校验 Android Java 源文件的结构完整性（不做完整编译，只做静态核对）。
#
# 为什么需要：本机没有 Android SDK，无法编译 APK。而定位这类改动涉及
# 权限声明 + 运行时申请 + WebView 回调三处，漏任何一处都表现为"权限问题"，
# 现象一样、原因不同。所以在推 CI 之前先用静态检查把遗漏挡下来。
#
# 检查三件事：
#   1) 括号配平（跳过注释与字符串，避免误判）
#   2) 定位相关的关键 API 是否都出现
#   3) AndroidManifest 是否声明了位置权限
#
# 用法: python check_mobile_permissions.py
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
fail = 0
total = 0


def ok(cond, label, extra=''):
    global fail, total
    total += 1
    if cond:
        print('  ✓ ' + label)
    else:
        fail += 1
        print('  ✗ ' + label + ('  ' + extra if extra else ''))


def strip_code(src):
    """去掉注释与字符串字面量，只留下结构性字符。"""
    out = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        two = src[i:i + 2]
        if two == '//':
            while i < n and src[i] != '\n':
                i += 1
        elif two == '/*':
            i += 2
            while i + 1 < n and src[i:i + 2] != '*/':
                i += 1
            i += 2
        elif c in ('"', "'"):
            q = c
            i += 1
            while i < n and src[i] != q:
                if src[i] == chr(92):
                    i += 1
                i += 1
            i += 1
        else:
            out.append(c)
            i += 1
    return ''.join(out)


print('=== 移动端定位配置检查 ===\n')

# ---------- Android ----------
print('— Android —')
mani_path = os.path.join(ROOT, 'android', 'app', 'src', 'main', 'AndroidManifest.xml')
java_path = os.path.join(ROOT, 'android', 'app', 'src', 'main', 'java',
                         'com', 'skl', 'uomviewer', 'MainActivity.java')

mani = io.open(mani_path, encoding='utf-8').read()
ok('ACCESS_FINE_LOCATION' in mani, 'Manifest 声明了精确位置权限')
ok('ACCESS_COARSE_LOCATION' in mani, 'Manifest 声明了粗略位置权限')
# 只声明精确会被部分系统拒绝粗略请求；只声明粗略拿不到 GPS。两个都要。
ok('uses-feature' in mani and 'android.hardware.location' in mani,
   '位置硬件声明为可选（避免无 GPS 设备无法安装）')

java = io.open(java_path, encoding='utf-8').read()
ok('ActivityCompat.requestPermissions' in java,
   '运行时动态申请权限（Android 6+ 必须，光声明不够）')
ok('onRequestPermissionsResult' in java, '实现了权限申请结果回调')
ok('onGeolocationPermissionsShowPrompt' in java,
   '处理了 WebView 定位请求回调（漏了则系统权限给了也没人应答）')
ok('callback.invoke' in java, '回调里放行了定位请求')
ok('ACCESS_FINE_LOCATION' in java and 'ACCESS_COARSE_LOCATION' in java,
   '两种权限一起申请（Android 12+ 用户可只给"大致位置"）')
ok('hasLocationPermission' in java, '有权限判断方法')

code = strip_code(java)
for o, c, name in [('{', '}', '花括号'), ('(', ')', '圆括号')]:
    a, b = code.count(o), code.count(c)
    ok(a == b, '%s 配平 (%d/%d)' % (name, a, b), '不配平!' if a != b else '')

# ---------- HarmonyOS ----------
print('\n— HarmonyOS —')
mod_path = os.path.join(ROOT, 'harmony', 'entry', 'src', 'main', 'module.json5')
mod = io.open(mod_path, encoding='utf-8').read()
ok('ohos.permission.LOCATION' in mod, '声明了 ohos.permission.LOCATION')
ok('ohos.permission.APPROXIMATELY_LOCATION' in mod,
   '声明了 ohos.permission.APPROXIMATELY_LOCATION（粗略位置，两者需成对）')

idx_path = os.path.join(ROOT, 'harmony', 'entry', 'src', 'main', 'ets',
                        'pages', 'Index.ets')
idx = io.open(idx_path, encoding='utf-8').read()
ok('onGeolocationShow' in idx,
   '处理了 ArkWeb 定位请求回调（onGeolocationShow）')
ok('event.geolocation.invoke' in idx, '回调里放行了定位请求')

# 权限申请写在 EntryAbility 里（需要 UIAbilityContext，页面拿到的 context 类型不同），
# 所以要在那个文件里找，不能在 Index.ets 里找。
ab_path = os.path.join(ROOT, 'harmony', 'entry', 'src', 'main', 'ets',
                       'entryability', 'EntryAbility.ets')
ab = io.open(ab_path, encoding='utf-8').read()
ok('requestPermissionsFromUser' in ab, '运行时动态申请权限（在 EntryAbility 中）')
ok('APPROXIMATELY_LOCATION' in ab, '两个位置权限成对申请（只申请 LOCATION 会被拒）')

# module.json5 里的 reason 字段：位置权限在 HarmonyOS 上要求填申请理由
ok('reason' in mod, '权限声明含 reason（HarmonyOS 对位置权限有此要求）')

# ---------- 用户数据持久化 ----------
# 背景：localStorage 按 origin 隔离，而页面从 http://127.0.0.1:<port>/ 加载。
# 端口一变 origin 就变，用户数据全部读不到（"切后台回来数据没了"）。
# 所以两端都要注入原生存储桥，页面统一走 UomStore 这一层。
print('\n— 用户数据持久化 —')
index_html = io.open(os.path.join(ROOT, 'index.html'), encoding='utf-8').read()
ok('const UomStore' in index_html, '网页端有 UomStore 存储抽象')

# 除 UomStore 内部，不应再有直接的 localStorage 调用 —— 漏一处就少一份数据
_i = index_html.index('const UomStore = (function(){')
_j = index_html.index('})();', _i)
outside = (index_html[:_i] + index_html[_j:]).count('localStorage.')
ok(outside == 0, 'UomStore 之外没有直接操作 localStorage',
   '还有 %d 处' % outside if outside else '')
ok('UomNativeStorage' in index_html, '网页端引用了原生桥 UomNativeStorage')
ok("PREFIX = 'uom_'" in index_html,
   'UomStore 前缀为 uom_（与旧数据键名兼容，老用户数据不丢）')

_ab = os.path.join(ROOT, 'android', 'app', 'src', 'main', 'java',
                   'com', 'skl', 'uomviewer', 'StorageBridge.java')
and_java = io.open(_ab, encoding='utf-8').read() if os.path.isfile(_ab) else ''
ok('@JavascriptInterface' in and_java, 'Android 桥用 @JavascriptInterface（必须同步）')
ok('SharedPreferences' in and_java, 'Android 存进 SharedPreferences')
ok(all(m in and_java for m in ['getItem', 'setItem', 'removeItem', 'keys']),
   'Android 桥暴露 get/set/remove/keys 四个方法')

_hb = os.path.join(ROOT, 'harmony', 'entry', 'src', 'main', 'ets',
                   'common', 'StorageBridge.ets')
har_ets = io.open(_hb, encoding='utf-8').read() if os.path.isfile(_hb) else ''
ok(len(har_ets) > 0, 'HarmonyOS 有 StorageBridge')
ok('preferences' in har_ets, 'HarmonyOS 存进 Preferences')
ok(all(m in har_ets for m in ['getItem', 'setItem', 'removeItem', 'keys']),
   'HarmonyOS 桥暴露同样的四个方法')
ok('javaScriptProxy' in idx, 'HarmonyOS 用 javaScriptProxy 注入桥')
# 必须检查【代码】里没有 asyncMethodList，而不是整份文件 ——
# 注释里提到它是正常的（我在注释里写明了"不要列进去"），
# 按整份文件搜会把正确代码判成错。先把注释去掉再查。
_idx_code = re.sub(r'/\*[\s\S]*?\*/', '', idx)
_idx_code = re.sub(r'//[^\n]*', '', _idx_code)
ok('asyncMethodList' not in _idx_code,
   '桥方法未列进 asyncMethodList（列了会变异步，而页面按同步读取）')

# ---------- 底部安全区（手机小白条） ----------
print('\n— 底部安全区 —')
ok('safe-area-inset-bottom' in index_html, '使用了 safe-area-inset-bottom')
ok('--safe-b' in index_html and '--safe-r' in index_html, '定义了安全区变量')
for _sel in ['#result{', '#coordBar{', '#toast{']:
    _seg = index_html[index_html.index(_sel):index_html.index(_sel) + 320]
    ok('var(--safe-b)' in _seg,
       '%s 使用安全区变量（写死会在有小白条的设备上被遮住）' % _sel.rstrip('{'))

# ---------- 提示都要能手动关闭 ----------
print('\n— 提示的手动关闭入口 —')
ok('tst-x' in index_html, 'toast 有手动关闭按钮')
ok('sempty-x' in index_html, '搜索结果提示有手动关闭按钮')
ok('diagHide' in index_html, '诊断输出有收起按钮')
ok("id=\"errX\"" in index_html or 'errX' in index_html, '错误横幅有手动关闭按钮')
# 报错/警告类提示不该自动消失（要用户看完再处理）
ok('needsAttention' in index_html,
   '错误/警告类 toast 默认不自动消失（避免用户来不及看）')

print('\n' + ('=== 全部通过：%d 项 ===' % total if fail == 0
             else '=== %d/%d 项未通过 ===' % (fail, total)))
sys.exit(0 if fail == 0 else 1)
