# OidProducer → Python OID 微码直印桥接（实验态）

目标：把获授权来源的 **仅包含黑色码点/白色背景** OidProducer PDF 接入自动铺码程序，避免人工一页页制版。

## 操作流程

1. 使用可信的 OidProducer/供应商工具输出纯微码 PDF（例如传统的 `Code_Sonix2/600dpi/CMY_K_PDF` 目录）；先不要合成彩图。记录每块图案的 **原始码值**、PDF 页号和实际矩形，不能靠码图猜码值。
2. 将 PDF 放在 JSON 配置同一目录下，按 [示例](../examples/oid_pdf_import.example.json) 提供 `source_pdf`、`dpi`、`rect_mm`（左上角 x/y/宽/高，单位 mm）、`raw_oid`。
3. 执行：

```powershell
python scripts/oid_pdf_bridge.py --spec examples/my_oid_pdf_import.json --out output/oid_import
python oid_lab.py candidate-sheet --manifest output/oid_import/oid_candidates.json --out output/oid_import/candidates.pdf
```

4. 用 `python ant_reader.py prepare --book examples/starter_en.json --out output --tts edge` 准备教材。在完整分配表中给出入口候选码、每个逻辑区域的候选 id（见 [分配格式示例](../examples/oid_book_assignment.example.json)，需覆盖书中所有区域）。
5. 继续：

```powershell
python scripts/make_oid_binding.py --manifest output/oid_import/oid_candidates.json --assignment examples/my_oid_book_assignment.json --book-dir output/books/starter_en_01 --out output/oid_binding
python book_assembly.py --book-dir output/books/starter_en_01 --binding output/oid_binding/bindings.json --out output/print_experiment
```

输出包含 `oid_candidates.json`、`source_audit.json`、`tiles/*.png`、`bindings.json`、实验打印 PDF 和非可安装的音频交付清单。

## 核心安全/质量限制

- 外部 PDF 白底→PNG 的渲染/阈值化 **可能改变微点大小、抗锯齿和网格间距**；它不是无损转换。工具记录 DPI/源 PDF SHA256，拒绝空白或过黑图块，但仍需与源 PDF 及原版印码对照。
- 如果 PDF 含彩色图案、文字或装饰，二值化无法分辨码点与背景；应从厂商输出纯码点 PDF，不能直接裁切彩色点读成品。
- 名义上“OID2”并不意味着品牌互通；所有候选图案 `UNVERIFIED_A8S`。
- 两个脚本均**不会生成 NOB/NOD/NOS/DAB**。缺少设备匹配的点读包，即使有码也未必播放。
- 不运行未经确认的第三方破解安装包，不覆写点读笔系统文件。

## 到货后的最小验收

A8S 型号/固件与已安装资源记录 → 单码打印物理尺寸 → 入口码 → 两个内容码 → 自己的 MP3 → 离线重启/重复点读。

静音不足以判断是“图案无法解码”：也可能是没有同码值的资源包，需要分类记录。
