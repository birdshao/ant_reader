# OID2 打印 → 扫描 → 原始码解码（实验性）

> 2026-10-25。`scripts/oid_scan_qa.py` 与 `scripts/sonix_oid2.py` 配合，面向**已知位置的研究用测试卡**。它不是通用相机识码库，不是小蝌蚪 A8S 固件，也不能证明 A8S 兼容性。

## 能做什么

1. 直接通过 Python 输出 **70 × 70 mm 标定卡**（嵌入在 A4 PDF 中）：中央约 20 × 20 mm 的 Sonix/Albi 风格 OID2 原始码图，四角为 OpenCV ArUco 位置标记（独立于 OID）。
2. 使用扫描仪扫描，或用分辨率足够的相机拍摄；从图像中的四个 ArUco ID 估计单应性变换，透视校正到名义 600/1200 DPI。
3. 从中央编码区域的重复 32×32 基本块读取定位点、位移编码符号、校验位，并用多数投票报告恢复的 16 位原始码、无效块数量和置信情况。
4. 输出只包含码值、计数、SHA-256 和变换矩阵的 JSON。不会采集笔端数据，也不生成点读包。

## 首次生成测试卡

安装 Python 3.10+：

```powershell
python -m pip install -r requirements-scan.txt
python scripts/oid_scan_qa.py make-target --raw-oid 1345 --dpi 1200 `
  --png output/qa1345.png --pdf output/qa1345_A4.pdf
```

**A4 PDF 要以 100% / 实际尺寸打印**，不要使用“适合纸张”、打印驱动智能缩放、自动锐化。四个大号方形标记只是帮助我们的 Python 对齐纸张，不是小蝌蚪需要扫描的 OID。打印样张边长应为 70 mm。

建议优先用支持 1200 DPI 的扫描仪和黑色碳粉。手机拍摄必须确保微点在实际图像中有足够像素：**即使 ArUco 标记检测成功，微点被相机模糊后仍可能无法恢复。**

## 扫描与质量报告

```powershell
python scripts/oid_scan_qa.py scan --image scans/qa1345.png --dpi 1200 `
  --expected-raw-oid 1345 --out evidence/qa1345_report.json `
  --rectified evidence/qa1345_rectified.png
```

- `raw_oid`: 满足门槛时恢复的码值，失败则为 `null`。
- `leading_candidate`: 投票领先候选码；**低置信度时不得当作真实结果**。
- `tiles_total`: 理论完整 32×32 原始块数量；本 20mm 图案通常是 196。
- `tiles_checksum_valid`: 单块定位、数据点、校验通过数量。
- `tiles_majority`: 支持领先码值的有效块数量。
- `majority_fraction`: 支持领先码值的有效块比例。
- `coverage_fraction`: 支持领先码值的全部原始块比例。
- `status=DECODED_RESEARCH_ONLY`: 满足至少 6 块、80% 有效块多数、12% 总块覆盖，**不代表实际 A8S 可读**。

本工具依赖测试卡上额外的 ArUco 标记；普通儿童点读教材没有这些标记，也不能直接拿任意照片使用本脚本。最终仍需开发自然纸面的无标记识读测试或依赖 A8S 原生解码功能。

## 已完成的软件测试

测试使用**数字渲染及合成的透视、90 度旋转、模糊、少量噪声**，包括 600/1200 DPI 与多个原始码、黑/白空白区及缺少标记的失败案例。无纸张、印刷机、扫描仪或 A8S 的实验结果。测试结果只是确保软件基本可靠，不应作为打印质量保证。

## 失败如何定位

- `No ArUco calibration markers`: 镜头取景不全、四角缺失、黑白反转或标记被模糊。
- `INSUFFICIENT_EVIDENCE`：OID 微点没有足够有效块，可能是打印缩放、微点丢失、墨点扩散、低 DPI 或输入不是真实 OID2。
- `matches_expected=false`：恢复的值与目标不一致；不能据此认为小蝌蚪支持/不支持。
- 1200 DPI 数字打印页能解码不代表打印驱动一定将 1200 DPI 物理输出。PDF 生成后要用打印扫描去确认。

## 下一阶段

取得实际的打印扫描图片后，按设备固件、打印机型号、纸张、DPI、实际比例、码值、识别率分组；代码通过这些真实扫描样本优化阈值/非线性畸变。**A8S 到货后还需验证 Sonix OID2 光学兼容与其 `.nob/.nod` 音频索引机制。**
