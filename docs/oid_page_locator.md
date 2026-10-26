# 整页 OID2 微码区域自动检测（研究工具，非 A8S 认证）

新增 `scripts/oid_page_locator.py`：处理一幅灰度/彩色扫描 PNG/JPG，无需四角 ArUco，也无需预先传入 OID 值。程序检测小墨点连通域、计算局部墨点密度并形成候选区域，再逐一使用 `oid_markerless.py` 的傅里叶网格估计、不对称定位点和 16 位 OID2 校验/多数投票完成解码。不会仅凭高密度纹理就报告有效 OID。

## 使用

```powershell
pip install -r requirements-scan.txt
python scripts/oid_page_locator.py --image scans/full_page.png --approx-pitch-px 16 --out evidence/page_report.json --annotated evidence/page_boxes.png
```

`--approx-pitch-px` 是扫描图上的 OID2 网格步长，不是基本码块尺寸。1200 DPI 原生码图约 16 px，600 DPI 原生图约 8 px；图片缩放后须根据实际间距修改。`--max-regions` 默认为 12，最多 12。文件存在时拒绝覆盖。

报告字段：区域 `bbox_px=[x,y,width,height]`，候选码 `raw_oid`（不确定则 `null`），`status`、有效票数、覆盖率、候选总数、是否截断、源文件 SHA-256。`--annotated` 只输出另外一幅带框的图，不修改原图。`a8s_compatible` 永远为 `UNTESTED`。

## 2026-10-25 软件验证

- 同一页分开的三个微码区域分别自动解出 1345、1347、1331；使用 600/1200 DPI 数字源样本。
- 加入英文普通文字、轻度模糊和 1200 DPI 样本中的少量随机黑点，仍能找到对应 OID。纯文字、空白、随机纹理、混合两种 OID 的同一区域不会通过验证。
- 600 DPI 随机噪声示例可能漏掉候选区域；这是已知局限，不应宣称真实印刷成功率。

## 重要边界

1. 目前是基于微小连通域的保守启发式定位器，适合白色或浅色背景、多个相互分隔的重复微码区域。复杂彩色插画遮挡、背景细纹和微码区域相互接触时可能漏检。
2. 目前最多读取约 3000 万像素的扫描图；单一区域超过 1600 px 或 2 MP 会保守跳过，应先裁图分批检测。真实 A4 600 DPI 全页一般超过该限制，因此需要先分区或分块扫描；暂不应称可处理任意完整 A4 高 DPI 扫描。
3. 不支持明显透视、光学畸变、反光和低像素远景照片。`truncated=true` 表示有候选未检查。
4. OpenCV 在普通扫描图上成功读出 Sonix 风格 OID2，并不表示小蝌蚪 A8S 能用该纸面码值，也不表示生成了原生 NOB/NOD/NOS 资源包；必须实机验证。

要继续提高真实性，应使用实际打印/扫描样本校准点径与连通域阈值，将失败的彩色背景、漏点、透视样本追加到测试。
