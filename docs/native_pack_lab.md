# A8S 原生点读包结构取证：只读分析，不是假装制包

2026-10-25。**目标**：等真实 A8S 或厂商授权工具导出文件可用时，把 `.nob` / `.nod` / `.nos` / `.dab` 的结构证据转化为可审计数据，为将来开发合规适配器提供依据。扩展名并不保证内容格式。我们没有已确认 A8S 可用的开源原生制包器。

## 为什么要做

社区小蝌蚪自制演示包含：封面选书码、内容码、MP3、合成以及通过云端申请在线点读。演示里的工具需授权，且并未证明 A8S 版本一定与其一致。A8S 使用说明同时出现 NOD/NOB/NOS、DAB 的描述，具体型号如何接受文件需要通过**实际安装**和厂商答复验证。

**优先实验对象**：通过官方途径获得、且你有权研究的两个最小自制点读资源包。理想样本除了某个内容码音频的变化外，其他配置相同。如果只有一份安装好的原生资源包，也可以先 `inspect`。

## 命令

使用 Python 3.10+，无需第三方 Python 依赖。假设自有授权样本位于本机 `private_samples/`：

```powershell
python scripts/native_pack_lab.py inspect `
  --file private_samples\book_v1.nob `
  --out evidence\book_v1_inspection.json

python scripts/native_pack_lab.py inspect `
  --file private_samples\book_v2.nob `
  --out evidence\book_v2_inspection.json

python scripts/native_pack_lab.py compare `
  --a private_samples\book_v1.nob `
  --b private_samples\book_v2.nob `
  --out evidence\book_v1_vs_v2.json
```

对比之前先通过 `a8s_device_audit.py snapshot/diff` 确认哪些文件是**安装过程中实际新增**的；如设备资源分区不暴露，就使用授权工具的合法输出。

输出中包含：

- 文件大小、SHA-256、魔数识别（只检测常见容器，`unknown` 很正常）；
- 最多 32 个 4 KiB 块的采样熵和零字节比例；
- 两个包的最长相同前缀、互不重叠的相同后缀；
- 按偏移对齐的 64 KiB 块差异（最多输出 128 个变化块的**位置**，不会导出音频内容）。

报告默认记录样本**文件名**（可能含私有信息），不包含绝对路径；不要直接上传到公开 GitHub。工具拒绝符号链接、空文件、超过 1 GiB 的文件，不会修改原始输入，已有报告不会覆盖。项目的 `.gitignore` 应当排除 `evidence/` 和 `private_samples/`。

## 能证明 / 不能证明

能证明：某个样本前 32 字节、实际 SHA-256、包内容是否与另一份样本在特定偏移发生变化；可能能发现 ZIP、RIFF 等公认容器的魔数。

**不能证明**：
- 高熵内容就是加密（压缩数据也会高熵）；
- 出现 ZIP 等魔数就一定是 A8S 可安装资源包；
- 两个文件的差异就是 OID 码表；
- 没有文件变化就说明没有安装（可能存于隐藏分区或云端）；
- 本脚本能合成 `.nob/.nod/.nos`，或能恢复第三方商业教材内容。

## 我们真正需要的最小材料

- A8S 固件版本、USB 实际可见目录清单（不需要序列号）；
- 一份**真实可在该 A8S 播放**的自有授权包，或厂商软件按自己的音频合成的最小包；
- 若能制作两份：只改变一个 OID→MP3 映射，尽量控制其他输入不变；
- 打印码图必须包含来源、物理点阵间距、输出分辨率及原始编号；测试音频由自己录制。

## 已有开源工具复用边界

`tttool`/`ttbox` 提供其他生态下的端到端 OID 制书参考；`Albi_tuzka` 有真实 Albi OID2 码图生成能力，但不能认定兼容 A8S。已有 `oid_pdf_bridge.py`、`vector_oid_assembly.py` 负责打印层；新的 `native_pack_lab.py` 专门针对**真实小蝌蚪资源包样本**开展结构取证。绝不把 Albi OID2 资源包当作 A8S 安装包。

### 来源

- [A8S 新手指南：资源管理与 DIY BOOK](https://www.10100.com/article/106571954)
- [小蝌蚪合成工具公开演示（需授权）](https://www.douyin.com/shipin/7380947731973539859)
- [厂商方案资料：不同代 OID 硬件/笔头](https://www.ztrontech.com/blog1/409.html)
- [OID 印刷厂 FAQ：印版分辨率要求可能达 2400dpi](https://website.very-color.com/OIDs/OID_FAQ.html) ——该数字属于特定厂商工艺主张，**不是 A8S 官方规格**，家用打印机是否可读仍需实测。