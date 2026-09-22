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

print('\n' + ('=== 全部通过：%d 项 ===' % total if fail == 0
             else '=== %d/%d 项未通过 ===' % (fail, total)))
sys.exit(0 if fail == 0 else 1)
