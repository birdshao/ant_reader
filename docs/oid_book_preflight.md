# ant_reader：整本教材 OID2 印前 QA（自动闭环）

状态（2026-10-25）：**数字制版与软件 QA 已实现，A8S 原生 OID 码池、NOB/NOD/NOS 制包、真实打印识读均未验证。** `READY_FOR_EXPERIMENT_PRINT` 只是“软件输入和布局可制作实验打印件”，不是硬件认证或打印良率。

## 解决的实际问题

上一阶段 `oid_print_geometry.py` 只核对一个已经裁剪、基本对齐的 OID 区域；现在 `oid_book_preflight.py` 对整个 `prepare` 工作目录执行：

1. **绑定唯一性**：使用 `book_assembly.validate_binding()`，检查书名入口与全部教材区域必须各绑定一个独立 OID 编号，逻辑 ID 和音频索引完整对应。
2. **数字码值复核**：`Sonix OID2` 来源的 PNG 不只看声明码值或 SHA；重新通过独立编码器生成原始 16-bit OID 的 alpha 点阵，**逐像素比较码图**，并检查可见墨点是否为黑色。码图与声明编号不一致时 `BLOCKED`，在生成 PDF 前拒绝继续。
3. **物理坐标与铺码完整性**：读取 `regions.json`、`artwork.pdf`，验证每一块区域页面编号、毫米范围、完整 OID tile 数量以及封面入口区域；调用与 `book_assembly.compose` 相同的 `tile_positions()`，禁止拉伸、切割半个码块。
4. **音频证据**：核对 `audio_manifest.json` 的文件是否真实存在、最小文件大小和 SHA-256。音频未就绪时标记 `INCOMPLETE`，一键流程默认拒绝组装；`--allow-missing-audio` 仅适用于明确允许的实验草稿。
5. **组装文件完整性**：对生成的 `EXPERIMENTAL_print_book.pdf` 校验 SHA-256，并与 `audit.json` 中的封面/每个区域码值、PNG 指纹和重复铺码个数逐项对照；被改动或与绑定不符时 `BLOCKED`。
6. **可选的扫描图比较**：按 `scan_manifest.json` 为各区域提供真实打印扫描裁剪图，调用 `oid_print_geometry.analyze()` 测量点径/漏点/网格间距及逐码块解码。只支持**已按参考尺寸对齐、近似同向、同尺寸**的单码区 PNG；不支持直接上传任意整页手机照片做精密测量。

对于不是 `Sonix OID2` 的外部提供图案，工具默认给出 `EXTERNAL_CODEC_NOT_CHECKED`，不将其冒充已做码值复核。若来源本身已确认为 Sonix OID2、但文件标注不规范，可明确指定 `--force-sonix-oid2`；该选项只能表示实验所用的解码假设，**不会改变 A8S 实机状态**。

## 最省事：一次完成制书与两次核对

首先准备好已有流程的 `book_dir` 和 `bindings.json`，例如：

```powershell
python ant_reader.py prepare --book examples/oid_3code_smoke.json --out output --tts edge
python scripts/make_sonix_oid2_binding.py `
  --book-dir output/books/albi_oid2_smoke `
  --assignment examples/sonix_oid2_smoke_assignment.json `
  --out output/sonix_bindings

python scripts/oid_book_pipeline.py `
  --book-dir output/books/albi_oid2_smoke `
  --binding output/sonix_bindings/bindings.json `
  --out output/sonix_checked_book
```

一键流程先做印前 QA（若数字码值不符则**不生成 PDF**），然后调用现有 `book_assembly.compose()` 生成实验 PDF，再重新检查组装审计：

- `output/sonix_checked_book/EXPERIMENTAL_print_book.pdf`
- `output/sonix_checked_book/preflight.json`
- `output/sonix_checked_book/preflight.csv`
- `output/sonix_checked_book/audit.json`
- `output/sonix_checked_book/vendor_handoff_NOT_PLAYABLE.zip`

这个 ZIP **不是 A8S 可安装的 NOB/NOD/NOS 点读包**。`edge` 是在线 TTS，需安装额外软件和联网；没有可用音频可加 `--allow-missing-audio` 制作明确不完整的实验版。

## 只生成独立印前报告

如果书已准备好，或由外部工具完成组装，直接运行：

```powershell
python scripts/oid_book_preflight.py `
  --book-dir output/books/albi_oid2_smoke `
  --binding output/sonix_bindings/bindings.json `
  --out evidence/book_preflight.json `
  --csv evidence/book_preflight.csv `
  --fail-on-issues
```

已通过 `book_assembly.py` 生成实验 PDF 时再传 `--assembly-audit output/sonix_checked_book/audit.json`。报告存在时拒绝覆盖，避免丢失 QA 历史。

**状态解释**：

- `READY_FOR_EXPERIMENT_PRINT`：全部受支持的数字图案与绑定一致、几何条件成立、音频文件存在；如果提供了扫描清单，必须全部覆盖且不能存在失败区域。仍然不是 A8S 认证。
- `INCOMPLETE`：尚未验证的外部码图、音频缺失或扫描清单不完整；需要补充材料。
- `BLOCKED`：数字码图与 raw_oid 不一致，已提供的扫描不匹配，或已组装 PDF/审计指纹冲突。由 CLI `--fail-on-issues` 控制自动化退出码。

## 有真实打印图后如何配对测量

创建 `private_scans/scan_manifest.json`：

```json
{
  "format": "ant-reader-oid2-scan-manifest/1",
  "book_id": "albi_oid2_smoke",
  "capture_kind": "physical_scan",
  "regions": {
    "__cover__": {"image": "cover_crop.png", "scan_dpi": 1200},
    "albi_oid2_smoke:apple:word": {"image": "word_crop.png", "scan_dpi": 1200},
    "albi_oid2_smoke:apple:sentence": {"image": "sentence_crop.png", "scan_dpi": 1200}
  }
}
```

以上 PNG 应放在该清单所在文件夹，均为**单个同码 OID 源 tile 的独立裁剪区域**，必须先校正方向与大小，像素尺寸与原始候选 PNG 一样，不能包含不同码值区域。`scan_dpi` 必须是已知的、可复核的扫描 DPI。传入 `--scans private_scans/scan_manifest.json` 即可。具体几何误差阈值仍是软件实验参数，需要真正的纸张扫描校准；工具不会记录“通过 A8S 实验”。

所有扫描文件与报告建议存放在 `.gitignore` 已排除的 `evidence/` 或用户私有目录，避免公开第三方版权资源或设备标识。

## 回归测试

新增测试覆盖：正确三码书、改错一位 raw_oid、PNG 单点篡改、外部编码不冒充验证、音频缺失、区域不足以容纳完整码块、越界扫描路径、合成扫描几何 QA、PDF 被改动的 SHA 检验、JSON/CSV 防覆盖以及一键组装硬阻断。软件验证不是实机兼容性证明。
