# UOM 适飞空域查询

本地运行的无人机空域查询网页。点击地图任意位置，判定该点是否在适飞空域内，
并叠加显示大疆禁飞/限飞区。

---

## 在线版（GitHub Pages）

**https://skl-666666.github.io/uom-airspace-viewer/**

不需要装 Python、不需要跑本地服务，打开就能用。

之所以能纯静态部署，是因为 **GitHub Pages 支持 HTTP Range 请求**——这是
PMTiles 按需读取字节的前提。已实测确认：

```
HTTP/1.1 206 Partial Content
Accept-Ranges: bytes
Content-Range: bytes 0-126/89540467
```

并按真实访问序列端到端验证过（头部 → 根目录 → 叶目录 → 单张瓦片，
每步内容与本地文件逐字节一致）。

**在线版的限制**

- 诊断上报（`POST /__diag` → `diag.log`）只在本地服务器上存在。
  线上出错不会写进日志，排查性能问题需要在本地跑。
- 数据仍是仓库里的静态快照，不会自动更新。

## 快速开始

双击 `start.bat`，浏览器会自动打开 <http://127.0.0.1:8080/index.html>。

或手动运行：

```bash
python serve.py 8080
```

> **必须用 HTTP 服务打开**，不能双击 `index.html`。PMTiles 依赖 HTTP Range
> 请求按需读取字节，`file://` 协议下浏览器不会发 Range，数据读不出来。

---

## 文件结构

```
UOM/
├── index.html                 查看器页面（单文件，含全部前端逻辑）
├── serve.py                   本地 HTTP 服务（自己实现了 Range 支持）
├── start.bat                  Windows 启动脚本
├── data/
│   ├── uom-shifei.pmtiles     UOM 适飞空域栅格，z0–z13，85 MB
│   ├── dji_flysafe.geojson    大疆禁飞/限飞区，4112 个多边形
│   └── custom_zones.geojson   自定义管制区（ZB(SR)801，非官方）
├── lib/                       Leaflet 1.9.4 + PMTiles 3.2.1（本地，免 CDN）
│
├── download_uom.py            下载/续传数据
├── build_custom_zones.py      生成自定义管制区
├── pmtiles_tool.py            PMTiles 读取器 + PNG 像素解析
├── verify_logic.py            判定逻辑校验（跑已知点）
├── make_preview.py            导出指定层级预览图
└── 复刻指南.md                 原始开发笔记
```

---

## 数据来源与时效

| 图层 | 来源 | 数据日期 | 说明 |
|------|------|---------|------|
| UOM 适飞空域 | 第三方归档 [thezzisu/uomtiles](https://github.com/thezzisu/uomtiles) | **2026-05-23** | 抓取自 UOM 平台 WMS |
| 大疆禁飞/限飞 | 同上，整理自 fly-safe.dji.com | 2026-06-03 | 非大疆官方发布文件 |
| ZB(SR)801 | 用户依据 NOTAM C0903/26 转述自行标注 | 2026-09-20 生效 | **非官方边界** |

**UOM 数据的实际日期是 2026-05-23**，取自 PMTiles 元数据的 `version` 字段，
比 Release 发布日（6 月 3 日）更早。页面上有这个日期的醒目标注。

> 数据不是实时的。2026-09-20 起 ZB(SR)801 首都禁飞区生效，UOM 平台已同步调整，
> 但本文件的栅格数据停留在 5 月，**不反映该变动**——这正是需要叠加自定义管制区图层的原因。

### 更新数据

```bash
python download_uom.py uom-shifei.pmtiles dji_flysafe.geojson
python build_custom_zones.py     # 改圆心/半径请编辑该脚本
```

下载脚本走 `api.github.com` 取签名 CDN 直链（`github.com` 主站在国内不稳定），
支持断点续传，失败会自动换新签名重试。

---

## 判定逻辑

### UOM 适飞空域（栅格法，无需矢量化）

UOM 原始数据是 PNG8 二值栅格，颜色固定、alpha 严格为 0 或 255：

```
适飞像素 = RGBA(41, 128, 185, 255)
alpha = 0    → 非适飞
瓦片缺失     → 该区域无适飞空域
```

点击时把经纬度换算到 z13 瓦片坐标与瓦片内像素，直接读该像素 alpha。
z13 分辨率约 20 米/像素，对无人机用途足够。

**已知限制**：边界是像素台阶（原始数据即如此），不适合当作精确边界线使用。

### 大疆禁飞/限飞区

射线法点在多边形内判定，支持 Polygon / MultiPolygon 与内洞。
按以下优先级给结论：`restricted`（禁飞）> `authorization` > `warning` > `recommended`。

### ZB(SR)801

独立的圆形多边形（天安门圆心，半径 300 km），与官方数据物理隔离存放在
`custom_zones.geojson`，图层默认虚线红边、低填充，标注明确写「非官方」。

---

## 底图与坐标系

| 底图 | 坐标系 | 与 UOM 数据偏移 | 需要 Key |
|------|--------|----------------|---------|
| 天地图 · 矢量/影像 | CGCS2000 ≈ WGS84 | **无偏移** ✅ | 是（免费） |
| 高德 · 矢量/卫星 | GCJ-02 | **300–600 米** ⚠️ | 否 |
| 无底图 | — | — | 否 |

UOM 与国家 2000 坐标系一致，**天地图是唯一无偏移的底图，推荐使用**。

天地图 Key 申请：<https://console.tianditu.gov.cn/api/key>（免费）。
申请后在页面左上角「底图」区域粘贴保存，存在 localStorage。

高德底图会错位，这一点在页面上有明确警告。

---

## 免责声明

本工具是**个人非官方项目**，数据来自第三方归档且非实时，**不作为飞行依据**。
实际飞行前请以 UOM 官方平台（<https://uom.caac.gov.cn>）及当地空管部门
发布的最新信息为准。
