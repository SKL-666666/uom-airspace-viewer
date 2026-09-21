# UOM 适飞空域查询

一个查中国无人机适飞空域的离线工具。点地图任意位置，判定该点是否在适飞空域内，
同时叠加显示大疆禁飞/限飞区与首都禁飞区标注。

**在线版（打开即用）**：<https://skl-666666.github.io/uom-airspace-viewer/>

---

## 它解决什么问题

飞无人机前需要确认一块地方能不能飞。官方渠道是 UOM 平台，但要登录、
交互也不方便随时查。这个工具把数据取到本地，点一下就出结果：

- **该点是否在适飞空域内** —— 直接读官方栅格数据的像素判定
- **是否命中大疆禁飞/限飞区** —— 叠加 1499 个空域多边形（含限高、区域类型）
- **是否在首都禁飞区（ZB(SR)801）范围内** —— 用户自行标注的 300km 圆

---

## 界面与功能

布局按"地图是主体、控件为辅"来做：顶部搜索栏 + 右侧竖工具条 + 底部状态条，
设置项收进浮层面板。

| 功能 | 说明 |
|------|------|
| **地点搜索** | 一个输入框搞定三件事：坐标（`39.90,116.41`）、行政区名、在线地点搜索。前两者离线可用 |
| **点击查询** | 点地图任意位置出结论；结果走底部抽屉，可拖拽收起 |
| **手动刷新** | 工具条 ⟳：点一下刷新当前视野，**长按清空全部缓存**（用于某片区域一直刷不出来） |
| **测距 / 测面** | 点地图加顶点，实时显示总长与面积（球面公式）；双击结束，Esc 清除 |
| **收藏夹** | 收藏常用点位，双击名称改名，可导出 |
| **批量查询** | 粘贴多行坐标一次判定，结果表 + 汇总，可导出 CSV 式表格 / GeoJSON |
| **导入导出** | GeoJSON / KML 双向；导出的坐标一律标注 WGS84 |
| **深浅主题 / 字号** | 主题跟随系统或手动指定；字号默认跟随系统，也可手动放大 |
| **诊断自检** | 浏览器里就能枚举视野瓦片、统计有/无数据、试加载底图 —— **线上也可用** |

### 坐标系（重要）

UOM 栅格、大疆、ZB(SR)801 都是 **WGS84/CGCS2000**；高德、腾讯底图是
**GCJ-02**，百度是 **BD-09**，同一地点相差 300~600 米。

- **点击查询会自动换算**：在高德/腾讯底图上点一个点，判定用的是换算后的
  WGS84 坐标，结论是对的（界面上的经纬度读数也统一显示 WGS84）。
- **但蓝色适飞层是 WGS84 栅格**，铺在 GCJ-02 底图上仍会与底图自己的道路、
  注记错位。**不要拿它去核对边界** —— 要核对请换天地图 / Esri / OSM。

---

## 三种使用方式

| 方式 | 适用 | 需要什么 |
|------|------|---------|
| **在线版** | 随手查 | 只要能上网 |
| **Windows exe** | 常用、要离线 | 双击即可，无需 Python |
| **本地服务** | 要完整诊断能力 | Python 3.x |

### 在线版

<https://skl-666666.github.io/uom-airspace-viewer/>

之所以能纯静态部署，是因为 **GitHub Pages 支持 HTTP Range 请求** ——
而 PMTiles 正是靠 Range 按需读取字节。已实测确认：

```
HTTP/1.1 206 Partial Content
Accept-Ranges: bytes
Content-Range: bytes 0-126/89540467
```

### Windows exe

到 [Releases](../../releases) 下载 `UOM-Viewer-Windows-x64.exe`，双击运行。

单文件 45MB，已内置全部数据与本地服务，**不需要安装 Python**。
首次启动会解压到临时目录，约 1~3 秒。

### 本地服务

```bash
python serve.py 8080
# 打开 http://127.0.0.1:8080/index.html
```

或用项目根目录的 `启动查看器.bat` / 桌面的 `UOM适飞空域查询.bat`。

> **必须用 HTTP 服务打开**，不能双击 `index.html`。
> PMTiles 依赖 HTTP Range 请求，`file://` 下浏览器不发 Range，数据读不出来。

---

## 数据来源与时效

| 图层 | 来源 | 数据日期 | 说明 |
|------|------|---------|------|
| UOM 适飞空域 | 第三方归档 [thezzisu/uomtiles](https://github.com/thezzisu/uomtiles) | **2026-05-23** | 抓取自 UOM 平台 WMS |
| 大疆禁飞/限飞 | 同上，整理自 fly-safe.dji.com | 2026-06-03 | 非大疆官方发布文件 |
| ZB(SR)801 | 用户依据 NOTAM C0903/26 转述自行标注 | 2026-09-20 生效 | **非官方边界** |

**UOM 数据的实际日期是 2026-05-23**，取自 PMTiles 元数据的 `version` 字段，
比 Release 发布日（6 月 3 日）更早。页面上对这个日期有醒目标注。

> 数据不是实时的。2026-09-20 起 ZB(SR)801 首都禁飞区生效，UOM 平台已同步
> 调整，但本工具的栅格数据停留在 5 月，**不反映该变动** —— 这正是需要
> 叠加自定义管制区图层的原因。

---

## 判定逻辑

### UOM 适飞空域（栅格法）

UOM 原始数据是 PNG8 二值栅格，颜色固定、alpha 严格为 0 或 255：

```
适飞像素 = RGBA(41, 128, 185, 255)
alpha = 0    → 非适飞
瓦片缺失     → 该区域无适飞空域
```

点击时把经纬度换算到 z13 瓦片坐标与瓦片内像素，直接读该像素 alpha。
z13 分辨率约 20 米/像素。

**这个判定的一个重要性质**：适飞空域只覆盖约 30% 的国土面积（随机撒点实测
27% 为适飞、71% 无数据）。**城市里看到空白是正常的**，不是加载失败。
界面上的「适飞层 有数据 N 块 / 空 M 块」就是用来区分这两种情况的。

**已知限制**：边界是像素台阶（原始数据即如此），不适合当作精确边界线使用。

### 大疆禁飞/限飞区

射线法点在多边形内判定，支持 Polygon / MultiPolygon 与内洞。
结论优先级：`restricted`（禁飞）> `authorization` > `warning` > `recommended`。

### ZB(SR)801

独立的圆形多边形（天安门圆心，半径 300 km），与官方数据物理隔离存放在
`data/custom_zones.geojson`，图层默认虚线红边、低填充，标注明确写「非官方」。

---

## 底图与坐标系

| 底图 | 坐标系 | 与数据偏移 | 需要 Key |
|------|--------|-----------|---------|
| 天地图 · 矢量/影像/地形 | CGCS2000 ≈ WGS84 | **无偏移** | 是（免费） |
| Esri · 卫星/街道/地形 | WGS84 | **无偏移** | 否 |
| OSM · 德国/法国镜像 | WGS84 | **无偏移** | 否 |
| 高德 · 矢量/卫星/注记 | GCJ-02 | **300–600 米** | 否 |
| 腾讯 · 矢量/卫星 | GCJ-02 | **300–600 米** | 否 |
| 百度 · 矢量/卫星 | BD-09 | 偏移更大 | 是 |

UOM 与国家 2000 坐标系一致，**天地图和 Esri 系是唯一无偏移的底图，推荐使用**。

> 在高德/腾讯底图上**点击查询会自动做坐标换算**，判定结论是对的；但蓝色适飞层
> 是 WGS84 栅格，铺在 GCJ-02 底图上仍会与底图自身的道路/注记错位。要核对边界
> 请换天地图或 Esri。

天地图 Key 申请：<https://console.tianditu.gov.cn/api/key>（免费）。
在页面「设置 → API Key」填入后保存在本机 localStorage。

### 地名搜索需要额外的 key

搜索分三路，**前两路完全离线可用**，只有第三路要联网：

| 输入 | 需要 key | 说明 |
|------|---------|------|
| 坐标 `39.90,116.41` | 否 | 直接定位并查询 |
| 行政区名（北京/广东…） | 否 | 内置省市清单 |
| 具体地点（首都机场…） | **是** | 见下 |

在线通道有两条，**任意配一条即可**（设置 →「图源与 Key」）：

1. **天地图 tk** —— 该 key 必须**额外开通「地名搜索」服务**。
   实测：瓦片能出图的 key 不一定能搜索，两者是不同的服务；
   key 不合法时接口返回 `非法key / 请到API控制台重新申请Key`。
2. **高德 Web服务 key** —— <https://console.amap.com/dev/key/app>（免费）。
   实测 `restapi.amap.com` 返回 `Access-Control-Allow-Origin: *`，浏览器可直连。
   高德返回的是 **GCJ-02** 坐标，程序内部已自动换算成 WGS84 再用于判定。

> 搜不出来时，点 **设置 →「诊断」→「测试地名搜索」**：它会逐个通道实测并把
> 接口的原话打出来（key 只报存在性与长度，不打印内容），一眼能看出是没配 key、
> key 非法、还是没开通服务。

> 百度 Web 服务接口**不含 CORS 响应头**，浏览器无法直连（只能 JSONP）；
> OSM 的 Nominatim 在国内实测连接超时。这两条都未采用。

**Key 按「页面源」隔离** —— 在 `127.0.0.1:8080` 存的 key 在
`github.io` 上读不到，两个源需要各存一次。天地图的 key 申请时还可以
限定 referrer，为某个域名申请的换域名使用会被拒。

---

## 性能设计

这个工具做过几轮针对性优化，记录在这里供参考。

### 瓦片批量取数（主要优化）

PMTiles 的数据是 clustered 存放的（tile_id 顺序 == 文件偏移顺序），
同一屏瓦片的 tile_id 跨度通常只有一两百。因此可以把相邻瓦片合并成少量
字节区间，用几个 Range 请求一次取回，而不是逐张请求：

| 视图 | 瓦片数 | 逐张请求 | 合并后 |
|------|--------|---------|--------|
| 陕西 z13 | 45 | 45 | **6** |
| 山西 z7 | 40 | 40 | **8** |
| 一屏实测 | 48 | 48 | **3** |

**请求数降到约 1/16，传输字节几乎不膨胀**（有时反而更少，因为区间内本就连续）。

实现放在 Web Worker 里（`tile-worker.js`），自己解析 PMTiles 目录、合并区间、
切片，主线程只做「拿数据 → 建 blob → 塞给 img」。

### 其他

- **PMTiles 目录二分查找 + 叶子目录缓存** —— 叶子目录有 4096 项，
  线性扫描会累积成上百毫秒
- **大疆图层按缩放分级** —— 全国视图下 94% 的多边形不到 3 像素，
  画它们是纯浪费；低缩放只用 567 个（屏幕尺寸 ≥3px 的）
- **相邻层级空闲预取** —— 停手 350ms 后预取上下层瓦片，缩放时直接命中
- **关闭 `chromeWindowsNoCache`** —— pmtiles 库在 Windows+Chromium 上
  会给每个请求带 `cache:"no-store"` 导致 HTTP 缓存完全失效；
  服务端补上 ETag/Last-Modified 后可安全关闭

详细的性能分析见 [性能分析.md](性能分析.md)。

---

## 项目结构

```
UOM/
├── index.html                 查看器（单文件，含全部前端逻辑）
├── serve.py                   本地 HTTP 服务（自己实现 Range 支持）
├── tile-worker.js             Web Worker：批量取数 + PMTiles 解析
├── desktop_app.py             桌面版入口（pywebview 外壳）
├── 启动查看器.bat              本地启动脚本
│
├── data/
│   ├── uom-shifei.pmtiles     UOM 适飞空域栅格，z0–z13，85 MB
│   ├── dji_cn_full.geojson    大疆禁飞/限飞（中国境内，1499 个）
│   ├── dji_cn_low.geojson     同上，低缩放概览版（567 个）
│   └── custom_zones.geojson   ZB(SR)801 标注（非官方）
│
├── harmony/                   HarmonyOS 工程（ArkTS + Web 组件）
├── android/                   Android 工程（Java + WebView）
├── .github/workflows/         CI：云端构建 APK
│
├── test_*.js / test_*.py      测试（缓存语义、批量取数、坐标链、坐标换算、判定优先级…）
├── run_all_tests.js           一条命令跑全部检查与测试
├── audit.js                   静态排查脚本
├── check_ids.js               标记与脚本的接口一致性（id / class）
├── check_refs.js              函数引用与调用参数个数
├── check_order.js             声明顺序检查
├── make_probe.py              生成带自检探针的页面副本（供浏览器自检）
├── cdp_ui_test.js             用无头 Chrome 在真实时间里跑页面自检
└── 性能分析.md                 性能实测与分析
```

---

## 打包与分发

三平台产物都在 [Releases](../../releases)。

| 平台 | 产物 | 大小 | 构建方式 |
|------|------|------|---------|
| Windows | `UOM-Viewer-Windows-x64.exe` | 45 MB | `python -m PyInstaller build_exe.spec` |
| Android | `UOM-Viewer-Android.apk` | 2.4 MB | 推 tag 触发 CI（本机无 Android SDK） |
| HarmonyOS | `UOM-Viewer-HarmonyOS-unsigned.hap` | 104 KB | `bash harmony/scripts/build_hap.sh` |

### Android

本机没有 Android SDK，因此走 GitHub Actions 云端构建：推一个 `v*` tag 即
自动构建、签名并附加到同名 Release。

```bash
git tag v1.0.2 && git push origin v1.0.2
```

> 构建踩过的坑：`androidx.webkit` 会传递依赖老版 `kotlin-stdlib-jdk8`，
> 与新版 `kotlin-stdlib` 产生重复类
> （`kotlin.collections.jdk8.CollectionsJDK8Kt`）导致
> `checkReleaseDuplicateClasses` 失败。该项目其实用不到 `androidx.webkit`
> （WebView API 全在 `android.webkit` 里），已移除，并加了
> `resolutionStrategy.force` 统一 Kotlin 标准库版本作为兜底。

签名用的是一次性密钥（`keytool` 现场生成），只为让 APK 可安装，
不适合上架。

### Windows

```bash
pip install pywebview pythonnet pyinstaller
python -m PyInstaller build_exe.spec --noconfirm
```

> 打包体积对排除列表很敏感。本机 site-packages 里装了 torch / sklearn 等
> 大库，不排除的话单文件会到 286MB；`build_exe.spec` 里已排除，产物约 45MB。

### HarmonyOS

需要 DevEco Studio 自带工具链（node / hvigor / jbr / SDK）：

```bash
bash harmony/scripts/build_hap.sh
```

> `hvigor` 在打包阶段会 `spawn java`，必须让 `JAVA_HOME` 和 `PATH` 都指向
> DevEco 自带的 `jbr`，否则报 `spawn java ENOENT`。

产物是**未签名** HAP。要装到真机需在 DevEco 里配置签名（生成证书 +
Profile），或在 AppGallery Connect 申请调试证书。

### Android

本机没有 Android SDK，因此走 CI：推一个 tag 即触发云端构建，
产物上传为 artifact。

```bash
git tag v1.0.0 && git push origin v1.0.0
```

---

## 免责声明

本项目是**个人非官方工具**，与民航局、大疆创新均无关联。

数据来自第三方归档且非实时，**不作为飞行依据**。
实际飞行前请以 [UOM 官方平台](https://uom.caac.gov.cn) 及当地空管部门
发布的最新信息为准。

数据版权归原权利方所有，详见 [NOTICE.md](NOTICE.md)。
