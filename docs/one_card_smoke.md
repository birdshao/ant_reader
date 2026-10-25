# A8S 无贴纸点读：三码实验（可立即生成，但**兼容性未知**）

## 本轮得到的技术结果

`book_assembly.py` 补上原先缺失的 **书名入口码 + 全区域 OID 重复铺码 + 原始码映射 MP3**。
它不会发明 OID 算法或伪造 A8S 包。外部 PNG 必须注明原始 raw OID、实际 source_dpi、来源。
它只重复 **整个码图 tile**，不进行任意缩放、部分裁剪；剩余边界留白。
已在独立 PDF 检查微码图案的实物宽高与原始 PNG 像素/DPI 一致。

## 跑通一个使用 Albi OID2 的非 A8S 实机验证实验

前提：Python 3.10+；`pip install -r requirements.txt`；仓库的已成功 GitHub Actions 工件包含 `albi_candidates.json` 和三个 PNG。如果已将工件下载解压到 `output/albi_oid2/`，可直接：

```powershell
python ant_reader.py prepare --book examples/oid_3code_smoke.json --out output --tts edge
python scripts/make_albi_smoke_binding.py --manifest output/albi_oid2/albi_candidates.json --book-dir output/books/albi_oid2_smoke --out output/oid_bindings
python book_assembly.py --book-dir output/books/albi_oid2_smoke --binding output/oid_bindings/bindings.json --out output/albi_oid2_smoke_handoff
```

输出：
- `EXPERIMENTAL_print_book.pdf`：独立入口页 + Apple 图卡，真实的 Albi OID2 tile 重复叠印；**是否能够被 A8S 识别未知**。
- `vendor_handoff.csv`：书名入口码、每块区域的 raw_oid、MP3、原始码图 SHA-256 和每区域贴入 tile 数。
- `handoff_mp3_by_raw_oid/<raw_oid>.mp3`：给授权的点读包制作工具手工导入的 **候选** 音频。它们无法凭文件名自动触发 A8S。
- `vendor_handoff_NOT_PLAYABLE.zip`：可追溯的音频/映射资料，不是 NOD、NOB、NOS、DAB，也不可直接安装到点读笔。
- `audit.json`：状态明确为 `EXPERIMENTAL_NOT_A8S_VERIFIED`，记录真实铺码尺寸和 hash。

使用纯离线 `--tts none` 时，组装默认拒绝缺音频；若只想先验证 PDF 几何，可加 `--allow-missing-audio` 输出明确标记的残缺草案。

**不要向点读笔导入未知第三方码值的音频包，不要覆盖已装书包。**

## 关键差异和风险

1. **第三方 OID2 编码器存在** != **A8S 兼容**。Albi 候选 `raw_oid` 1331/1345/1347 只说明按 Albi 自有查表获得码图。
2. **打印有码** != **点读有声**。A8S 需要正确的封面/书名入口，匹配的本地或云端音频资源包。A8S 用户指南同时提到 DAB 和 NOD/NOB/NOS 的资源导入用途；兼容性因模式/固件/云端授权流程而异。
3. 社区展示的小蝌蚪点读包**专用合成工具可能需要商家/授权资格**，不能将它当成已开放的 Python SDK，也不能照搬其他型号的临时文件结构。
4. `source_dpi` 必须为该图案实际导出 DPI。不能只改元数据来缩小点图；由生成器重新生成相应物理尺寸。
5. 复用同一码值会发生跨书冲突。正式生产前应引入书名码的全局分配与碰撞检测，并登记机器固件、已有点读包。

## 实机实验的判定

先用原装贴校准 A8S 的 `DIY BOOK` 音频链路，再测试合法来源的传统点阵实验页。
按以下路径逐项推进：光学码有无反应 → 是否读到**预期的原始码值** → 是否需要书名入口 → 是否有**匹配的资源包** → 打印 600/1200 DPI 长期识别率。
**如果缺少配套点读包，静音/报错无法区分“码不兼容”与“资源包缺失”。**

## 外部证据

- 小蝌蚪 A8S 入门：[内容贴、点读包、同码书、NOD/NOB/NOS](https://www.10100.com/article/106571954)
- 小蝌蚪授权合成工具展示：[抖音教程（需确认设备型号和权限）](https://www.douyin.com/shipin/7380947731973539859)
- OidProducer 并非万能资源包工具：[既有操作说明](https://zymin.cn/arcticle/diandubao-puma)
- 真实第三方编码器：[Albi_tuzka](https://github.com/JanValiVales/Albi_tuzka)
