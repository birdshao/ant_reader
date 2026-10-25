# 开源项目调查：小蝌蚪 A8S 无贴纸点读（2026-10-25）

**结论：找到能完成 OID 图案、整页铺码和音频资源包的开源项目，但未找到经验证可直接为 A8S 生成原生 NOD/NOB/NOS 包的完整开源链。** GitHub 上公开下载 EXE/RAR 不等于公开源代码。

| 项目 | 实际覆盖 | 可否直接用于 A8S |
|---|---|---|
| [entropia/tip-toi-reveng / tttool](https://github.com/entropia/tip-toi-reveng) | 生成 Tiptoi 的 OID 图片、GME 音频包和逻辑脚本 | **不能认定**：GME 不是 NOD/NOB/NOS |
| [cleracruza/ttbox](https://github.com/cleracruza/ttbox) | SVG 标注区域自动插入 OID；批处理出版流程 | 复用架构/数据流，不复用专属码值 |
| [thawn/ttmp32gme](https://github.com/thawn/ttmp32gme) | MP3→GME 和打印控制页 | 完整流程的设计参考，非 A8S 适配 |
| [buddly27/tiptoi-tools](https://github.com/buddly27/tiptoi-tools) | Python 读写 Tiptoi GME | 参考格式解析，不是小蝌蚪原生格式 |
| [JanValiVales/Albi_tuzka](https://github.com/JanValiVales/Albi_tuzka) | Albi OID2 图案生成，本项目已做打印实验 | **未验证** A8S 是否识别 |
| [umaribn681/oidproducer-sonix2](https://github.com/umaribn681/oidproducer-sonix2) | 仅包含 RAR 文件，并非源码项目 | 不自动运行来源未验证的 EXE/RAR |
| [shenya0203/ReadPenServer](https://github.com/shenya0203/ReadPenServer) | 通用点读相关设备/服务代码 | 未发现 A8S 制包功能 |

## A8S 的真实问题不只是印码

- [A8S 入门指南](https://www.10100.com/article/106571954) 介绍选书入口、云端点读包、DIY BOOK 和 NOD/NOB/NOS 文件，但**没有原生制包 API**。
- [社区合成工具演示](https://www.douyin.com/shipin/7380947731973539859) 出现入口码、内容码、MP3、合成以及申请在线点读；作者称部分功能需要授权代理商资格。
- [OidProducer 教程](https://www.3h3.com/soft/130979.html) 显示它能产生类似 Code_Sonix2/600dpi/CMY_K_PDF 的外部印码 PDF；这 **不证明** A8S 能识别它输出的码值。不要下载破解版。
- [Sonix OID3 资料](https://www.sonix.com.tw/files/1/5041DEAF72776B4AE050007F010076C4) 表示有些 OID3 芯片能识别 OID2；尚无证据证明 A8S 使用对应芯片/码池。
- [tttool 2026 点距问题](https://github.com/entropia/tip-toi-reveng/issues/309)：物理点尺寸和网格距离可能决定打印可读性；名义 DPI 一样仍可能不兼容。

## 对 ant_reader 的采用决定

1. 继续用 ant_reader.py 生成 AI/音频/逻辑区域；逻辑索引与 raw_oid 分离。
2. 学习 ttbox 的 SVG/批量铺码，把外部码资产导入本工程。
3. 新增 scripts/oid_pdf_bridge.py：外部 OID-only PDF → 明确毫米坐标和 DPI 的 RGBA PNG + 来源/哈希。
4. 新增 scripts/make_oid_binding.py：严格一一绑定封面入口码和所有内容区，再交给 book_assembly.py 做完整码块重复铺设。
5. **明确边界**：PDF 重新栅格化/黑白阈值可能改变微点几何，这只是打印候选；非 A8S 原生编码、非 NOD/NOB 打包、未经实机扫描。
6. 优先向厂家获取获授权的微码图、码值范围与独立的资源包制作工具。若仅提供 GUI，计划后续自动化导入文件/操作；在此之前不声称无 GUI 全自动闭环。

仅当 A8S 实测通过入口→两内容区→自己的音频，并能在离线重启后重复工作，才升级为真正兼容方案。
