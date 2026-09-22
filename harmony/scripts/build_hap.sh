#!/usr/bin/env bash
# 构建 HarmonyOS HAP（未签名）。
#
# 需要 DevEco Studio 自带的工具链：node、hvigor、jbr(Java 21)、SDK。
# 关键点：hvigor 在打包阶段会 spawn java，所以 JAVA_HOME 和 PATH 都必须
# 指向 jbr，否则报 "spawn java ENOENT"（这个坑我踩过）。
set -e

DEVECO="${DEVECO_HOME:-/c/Program Files/Huawei/DevEco Studio}"
NODE="$DEVECO/tools/node/node.exe"
HVIGOR="$DEVECO/tools/hvigor/bin/hvigorw.js"

if [ ! -f "$NODE" ]; then
  echo "未找到 DevEco 工具链: $DEVECO" >&2
  echo "请设置 DEVECO_HOME 指向 DevEco Studio 安装目录" >&2
  exit 1
fi

export DEVECO_SDK_HOME="$DEVECO/sdk"
# Git Bash 下 PATH 必须用 POSIX 写法，用 Windows 反斜杠路径 java 不生效
export PATH="$(cygpath -u "$DEVECO/jbr/bin" 2>/dev/null || echo "$DEVECO/jbr/bin"):$PATH"

# 仓库根目录。
# 路径坑：脚本以相对路径被调用时，$0 只到 harmony/scripts/build_hap.sh，
# 之前用 "$(dirname "$0")/../.." 拼出来落到了 harmony/ 下面（少了一层）。
# 先用 cd + pwd 求出绝对路径，后面一律基于它。
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# 先把网页资源与 85MB 数据同步进 rawfile（这些文件不入版本库）
echo "同步内置资源…"
python "$REPO_ROOT/sync_rawfile.py"

cd "$REPO_ROOT/harmony"
"$NODE" "$HVIGOR" assembleHap \
  --mode module -p product=default -p buildMode=release --no-daemon

OUT="entry/build/default/outputs/default"
echo
echo "产物："
ls -la "$OUT" 2>/dev/null || true
