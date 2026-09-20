# 数据来源与权利归属

本仓库的**代码**与**数据**权利归属不同，请分别对待。

## 数据

| 数据 | 权利归属 | 本仓库的角色 |
|------|---------|-------------|
| `data/uom-shifei.pmtiles` | 中国民用航空局（CAAC）UOM 平台 | 非权利方，仅转载第三方归档 |
| `data/dji_flysafe.geojson` | 深圳市大疆创新科技有限公司 | 非权利方，仅转载第三方归档 |
| `data/custom_zones.geojson` | 本仓库作者自行标注 | 依据公开公告转述生成，**非官方边界** |

上述数据的**版权与解释权归原权利方所有**。本仓库不对数据的准确性、完整性、
时效性作任何担保。

UOM 栅格数据与 DJI 数据的原始归档来自第三方项目
[thezzisu/uomtiles](https://github.com/thezzisu/uomtiles)（MIT License）。
该项目的代码为 MIT 授权，但其打包的数据归上述原权利方所有。

**若你是权利方并认为本仓库的转载不当，请提 Issue，我会立即移除相应数据。**

## 代码

本仓库的代码（`index.html`、`serve.py`、`*.py`、`start.bat`）为原创，
其中 `pmtiles_tool.py` 的 PMTiles v3 目录解析逻辑参照 PMTiles 规范与
[protomaps/PMTiles](https://github.com/protomaps/PMTiles)（BSD-3-Clause）实现。

`lib/` 目录下的第三方库各有其授权：

- Leaflet 1.9.4 — BSD-2-Clause
- PMTiles 3.2.1 — BSD-3-Clause

## 重要声明

本项目是**个人非官方工具**，与民航局、大疆创新均无关联。

数据非实时、非官方、可能过期。**本工具的输出不作为飞行依据。**
实际飞行前请以 [UOM 官方平台](https://uom.caac.gov.cn) 及当地空管部门
发布的最新信息为准。
