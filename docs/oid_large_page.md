# 高分辨率整页 OID2 分块定位（无 A8S 真机验证）

此工具使用 `scripts/oid_large_page.py` 将 `oid_page_locator.py` 的整页像素上限改为**按分块分别检测**。它不会新发明 OID 编码；光学识别复用已有无标记 OID2 定位器。每个候选 OID 区域需包含多个完整的重复码块；仅适合相互分开的浅底微点区，未验证复杂彩色插画、扫描仪伪色、纸张反光或小蝌蚪 A8S。

## 关键输入规则

- **大于 3000 万像素的输入必须是 8-bit、未压缩、像素数据连续的单页 TIFF**（灰度或 RGB）。程序通过 `tifffile.memmap(..., mode='r')` 只读映射磁盘文件，实际读取/处理以 tile 为单位，避免一次生成整页 OpenCV 标签矩阵。
- PNG / JPEG 仅允许 `<= 3000 万像素`；其文件头尺寸首先通过 Pillow 检查，再由 OpenCV 解码全图。**PNG/JPEG 即使逐块调用处理器，也不能据此保证低内存**；不支持用本程序直接处理 1200 DPI A4 PNG。
- 不支持压缩 TIFF、分离式 TIFF 多个 plane、16-bit TIFF、反色 MINISWHITE TIFF；遇到不符合条件的文件直接给错误，不会偷偷读入全图。文件超过 4 亿像素会拒绝。拍摄 JPEG 也可能改变小黑点，不建议用低质量 JPEG 作为微码 QA 的唯一证据。
- `--approx-pitch-px` 是**当前扫描图像**中的大网格间距：原始 1200 DPI 约 16 像素、600 DPI 约 8 像素，已缩放或扫描仪不同分辨率时须测量调整。
- 同一分块区域不能混合两个不同 OID。源码检测到重叠的不同码值不会静默合并，将其计入 `merge_diagnostics.conflicting_overlaps`。没有识读证据的候选不会变成正式解码结果。

## 命令

```powershell
python -m pip install -r requirements-scan.txt

# 用扫描软件保存单页未压缩 TIFF，例如 1200 DPI A4 约 9921x14031 像素
python scripts/oid_large_page.py `
  --image scans/a4_1200dpi_uncompressed.tif `
  --approx-pitch-px 16 `
  --tile-size 1600 --overlap 720 `
  --out evidence/a4_scan.json `
  --preview evidence/a4_preview.png
```

输出 JSON 包含每个识读区域的全页像素坐标 `bbox_px`、`raw_oid`、独立分块发现次数 `observations`、来源 tile 索引及解码多数票统计。`--preview` 是最长边不超过 1800 像素的**诊断缩略图**，不用于识读，框的位置映射自原始像素坐标。`source_sha256` 支持复核源文件是否改变。

算法使用 1600px 重叠窗口，默认重叠 720px；靠近拼缝的较大码区可能被两个窗口分别识别，最后按“**同一 raw_oid，重叠面积占较小矩形 >= 20%**”归并。不同 OID 即使区域重叠也不会强行归并。同一物理码区因强烈变形/遮挡而被拆成不重叠的小区域时，仍可能出现两个框；不要把 `decoded_count` 当成准确的书页内容区个数。当前没有真正语义级别的“区域分割”。

## 软件验证与限制

自动测试使用 3 个数字生成 OID2 区域、一处普通英文文字、多窗口拼缝、无效 PNG/压缩 TIFF、RGB TIFF、不同码值重叠合并策略和防止覆盖输出。另有实际 A4 1200 DPI 尺寸 `14031 x 9921` 的**稀疏无压缩 TIFF**，验证只读内存映射、局部裁剪和缩略图生成，不将全页 1.39 亿像素解码到内存；**没有声称整张实体纸张被扫描识别**。全尺寸跑所有窗口时的耗时仍取决于硬件、候选区域数量和图像噪声。

目前保留的核心阻塞项：A8S 能否识别此 OID2 光学码、A8S 书名/内容码池、合法原生 NOB/NOD/NOS 资源包生成及真实播放验证。**本工具只证明 Python 对已知类型的重复微点进行图像分析，不是 A8S 固件模拟器。**
