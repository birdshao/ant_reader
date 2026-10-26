# 彩色儿童教材背景上的 OID2 微点识别与局部质量分析

2026-10-25。**仅为研究实验，未完成纸张扫描、A8S 真机识读或 NOB/NOD/NOS 兼容验证。**

## 为什么做这项改造

以往 `oid_page_locator.py` 对白底/浅底实验图较敏感；深色插画、渐变填充和文字笔画会使全局黑白阈值漏掉独立的微点。`oid_color_qa.py` 现在以**局部黑帽（black-hat）形态学**作为彩色墨点候选增强通道：对三个 RGB 通道分别做 closing − image，再采用中位通道响应，尽量保留三通道都变暗的黑色小点并抑制宽阔彩色背景。灰阶扫描同样受支持。这不是厂家 OID 微码识别算法。

- `--mode ink`：仅使用局部墨点响应，适合深色渐变或彩色插画。
- `--mode gray`：原始灰度算法，作为历史对照。
- `--mode auto`：先尝试 ink，**当前分块没有识别码值时**再试 gray；避免同时使用两条处理路径对同一个码区给出冲突编号。
- 先在分块里寻找候选，再调用原有 `oid_markerless.decode_markerless()` 进行七定位点、校验位、重复码块投票。跨分块同号去重，重叠异号保守标记为 `AMBIGUOUS_OVERLAPPING_IDS`，不声称通过。
- 报告每个区域的 `mean_luma`、`luma_std`、`dark_microtexture_fraction`、`ink_contrast_p90`、有效码块覆盖率及 `evidence_grade`。这些是**数字图像启发式指标**，不是 A8S 误读率或印刷质量校准。

## 命令行

安装依赖：

```powershell
python -m pip install -r requirements-scan.txt
```

彩色扫描仪输出推荐 8-bit RGB、无压缩 TIFF；1200 DPI A4 图像使用 `tifffile` 的**只读内存映射**按需读图。普通 PNG/JPEG 最多 3000 万像素，超限会在解码前拒绝，避免大文件耗尽内存。

```powershell
python scripts/oid_color_qa.py `
  --image scans/children_a4_1200dpi.tif `
  --mode auto `
  --approx-pitch-px 16 `
  --tile-size 1600 --overlap 720 `
  --out evidence/color_a4.json `
  --preview evidence/color_a4_preview.png
```

注意 `--approx-pitch-px` 表示扫描后图像**定位格点间距**，并非设备的真实 DPI：原始 1200 DPI OID2 图约 16 px，600 DPI 约 8 px。打印缩放后应测量实际图片中的格点距离。

## 测试和重要边界

本轮 10 项新增测试覆盖彩色渐变页面三个独立码值（1331、1345、1347）、纯白页、PNG/TIFF RGB 通道顺序、黑色墨点响应、只读 TIFF、噪声/空白负面样本、CLI 防覆盖和输入参数异常。软件测试合成的黑点由 `sonix_oid2.py` 直接叠印到彩色像素；**不包含喷墨扩散、半色调网点、纸面形变、光源光谱或真实光学扫描噪声**。这意味着后续必须采集真实打印/扫描图校准滤波器和质量阈值。

彩色背景中存在大量尺寸相近的印刷网点时，该检测器仍可能漏检，或出现异号候选。未识别不等于纸张无法被点读笔读取。深色油墨上额外叠印黑色码点，可能本来就缺乏可用的反射率对比；无法仅靠软件恢复丢失的物理信息。

未来实体验证建议配对采集：`原始 OID2 PNG`、`无缩放印刷 PDF`、`打印材料与喷墨/激光驱动参数`、`扫描 TIFF`、`A8S 点读 20 次结果`；分别区分码图算法、印刷/扫描光学质量和固件/资源包兼容问题。
