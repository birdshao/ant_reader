# OID PDF 无中间位图重采样（实验路径）

**状态：2026-10-25；软件制版已验证，A8S 实机兼容性未知。**

## 为什么保留矢量 PDF？

之前的 `oid_pdf_bridge.py` 会先将 OidProducer 的 PDF 渲染成 PNG，再用灰度阈值提取黑点。这可能改变微点大小、轮廓、密度、抗锯齿；不同生成器/打印设备的容差也不同。

`vector_oid_assembly.py` 直接通过 PyMuPDF `show_pdf_page(clip=...)` 在页内复用来源 PDF 的原始矢量元素，不做额外阈值或 PNG 重编码。**它不能防止最终打印驱动光栅化，也不能把其他品牌的 OID 转成 A8S 的 OID**。真正的 Sonix2/A8S 原始码仍应由可信、授权工具输出。

## 输入

1. `ant_reader.py prepare` 得到一本教材的 `artwork.pdf`, `regions.json`, `audio_manifest.json`。
2. 可信工具生成的**仅含光学码** PDF；不能用带白色背景的整页设计稿冒充透明叠印码图。码值与 PDF 页、裁剪区域必须有外部证据支持。
3. `vector_bindings.json`：书名入口 + 与 `regions.json` 完全相同的逻辑区域集合。见 `examples/vector_oid_binding.example.json`。

每个码图绑定字段：`raw_oid`（从可信工具确认，不可通过文件名推断）、`source`（工具及版本）、`pdf`（绑定 JSON 所在目录内的相对路径）、`page`（源 PDF 页号，从 1 开始）、`rect_mm`（`[x,y,width,height]`，**PDF 页面左上角起算，单位毫米**）。

## 执行

```powershell
python ant_reader.py prepare --book examples/oid_3code_smoke.json --out output --tts edge

# 将外部 OID-only codes.pdf 放在 binding JSON 所在目录，
# 手工核实三码的原始值和裁剪坐标，再填写 vector_bindings.json。
python scripts/vector_oid_assembly.py `
  --book-dir output/books/albi_oid2_smoke `
  --binding output/vector_bindings.json `
  --out output/vector_experiment
```

用 `--allow-missing-audio` 只能生成明确标注的残缺实验文件；**默认缺音频将拒绝生成**。如果源 PDF 含有任何栅格图像，默认拒绝；研究时可手动加 `--allow-raster-source`，但此时不能宣称“全矢量码”。输入必须有绘图对象或显式允许的栅格图像，且裁剪内不能包含文字标签；大块背景填充会被拦截。

输出：

- `EXPERIMENTAL_vector_book.pdf`：单独的入口页 + 图文区域铺码 PDF；只能作印码实验。
- `vendor_handoff.csv` 与 `mp3_by_raw_oid/`：供**授权制包工具**录入的码值-音频清单；**不是 A8S 可安装资源包**。
- `audit.json`：源 PDF SHA-256、裁剪毫米坐标、矢量绘图对象数量、是否含位图、铺码重复数，以及明确的 `UNVERIFIED_A8S` 状态。

## 如何确认没有中间位图重采样？

生成文件后，可用 PyMuPDF 查看：

```python
import fitz
with fitz.open('output/vector_experiment/EXPERIMENTAL_vector_book.pdf') as pdf:
    page = pdf[1]
    print('vector paths:', len(page.get_drawings()))
    print('embedded bitmap image resources:', len(page.get_images(full=True)))
```

测试夹具使用人工合成的**几何圆点**，这些点并非有效 OID；单元测试检查新 PDF 含大量原始矢量路径而未新增位图。正式打印前，必须测试来源码图的尺寸、压印顺序及打印驱动；无法从 PDF 结构直接判断实机识别率。

## 实际兼容性阻塞不变

- 小蝌蚪 A8S 是否接受这些码值：**未知**。
- 小蝌蚪 NOB/NOD/NOS 打包 API：**尚未获得可验证的开源实现**。
- 没有 A8S 实机或对应的授权工具，不得把生成的 PDF/MP3 交付物称为“可点读教材”。
- 文档中的码值示例仅供结构说明，不证明码段分配或冲突情况。

## 外部技术依据

- [tttool 项目：GME/OID 制作](https://github.com/entropia/tip-toi-reveng)
- [tttool 打印经验](https://github-wiki-see.page/m/entropia/tip-toi-reveng/wiki/Printing)
- [2026 年打印码点直径及网格间距问题](https://github.com/entropia/tip-toi-reveng/issues/309)