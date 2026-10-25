# ant_reader — AI + Python 自动生成可打印微码点读教材

面向 **小蝌蚪 A8S** 的儿童点读内容制作工程。**主路线是把 OID 光学微点阵直接印在教材的图片和文字交互区**，不依赖购买和粘贴内容贴。

> 项目状态（2026-10-25）：已确认 A8S 支持 DIY BOOK 编号 MP3 内容贴玩法及部分传统铺码书/点读包生态；但尚无可核验的 A8S 原生 OID 编码公开规范或完整命令行打包 API。未经实机识别验证的图案绝不标记为可用。

## 目标产线

```text
AI 文案 / 插画 / TTS
          ↓
     book.json（中间标准）
          ↓
  页面排版 + 区域坐标 + 音频
          ↓
  OID 码值绑定 / 码图编码器
          ↓
  微点阵精确叠加 → 可打印 PDF
          ↓
  点读资源包生成 / 导入笔内
          ↓
  A8S 实测：准确率、重启、码值冲突
```

### 技术策略

1. **P0：微码直印**。单词、插画、句子使用独立可点读区域。支持外部已验证 OID PNG 精确贴合毫米坐标，绝不把 QR、随机圆点或小达人 `25001` 码段冒充 A8S 可识别微码。
2. **P1：验证真实编码-资源包联动**。传统 OidProducer 可以为部分开放式点读笔铺码，但码段与 A8S 的 NOD/NOB/NOS/DAB 或 DIY BOOK 绑定关系必须通过实机确认。
3. **P2：无 GUI 批处理**。如厂商仅提供 Windows 图形界面，先用人工导出阶段通关，再评估稳定的 GUI 自动化或合法开源替代。
4. **备用路径**：原装“内容贴”编号 + `DIY BOOK/<number>.mp3` 用于硬件验收/回归，不作为教材的默认制版方式。

## 仓库文件

- [架构与接口](docs/architecture.md)
- [微码编码/资源包调研及证据分级](docs/oid_research.md)
- [A8S 到货后实测清单](docs/device_validation.md)
- [任务路线图](docs/roadmap.md)
- `examples/starter_en.json`：最小英语教材数据。

## 可验证现状

| 环节 | 状态 |
|---|---|
| AI / Python 生成书页内容、音频及区域元数据 | 已有本地原型，需要纳入仓库并加强 |
| 纸张坐标、物理尺寸、PDF 底图 | 原型已实现 |
| 实测 A8S 微码的生成、绑定与打印 | **未通过，等待设备与码图工具** |
| A8S 直接打印 OID 的成功识别 | **未实测** |
| DAB / NOD 等专有点读包自动生产 | **未实现** |

请勿用未验证的码图批量印刷，先制作 1 页小型测试版。

## 相关资料

- [小蝌蚪 A8S 用户教程：DIY BOOK、DAB 与点读书入口](https://www.10100.com/article/106571954)
- [OidProducer 铺码及内容码区间（小达人生态，不等于 A8S 码值映射）](https://www.i-bei.com/baby/thread-51323-1-1.html)
- [开放式点读笔的铺码教学（包含小蝌蚪）](https://www.bilibili.com/video/BV1oT411L7Ep/)
- [小达人传统点读包制作流程](https://www.bilibili.com/video/BV1RG4y1Y7wx/)

**原则：用脚本生成内容和页面，保留编码器适配层；把“页面编号、光学原始码、内容贴编号、资源包音频索引”分开存储。**

## 本仓库现在可运行的部分

环境：Python 3.10+；安装 `requirements.txt`，系统需支持中文字体（Windows 微软雅黑或 Linux Noto Sans CJK）。

```bash
pip install -r requirements.txt
# 不生成音频，只生成底图和完整微码区域信息（完全离线）
python ant_reader.py prepare --book examples/starter_en.json --out output --tts none
# 可选，调用在线英文 TTS 生成真正 MP3
pip install edge-tts
python ant_reader.py prepare --book examples/starter_en.json --out output --tts edge
python -m unittest discover -s tests -v
```

结果位于 `output/books/starter_en_01/`：`artwork.pdf` 是完整教材底图（但还没有 OID 码），`regions.json` 是整片图文区域的毫米坐标，`mapping_template.csv` 供外部 OID 工具填入码值、图案路径，`audio_manifest.json` 是音频索引。

获取经 A8S 测试的透明 OID PNG 后，使用下述命令组合成实验打印版：

```bash
python ant_reader.py compose --out output --book-id starter_en_01 \
  --mapping mappings.json --dpi 600 --experimental
```

`mappings.json` 的格式见 [架构与接口](docs/architecture.md)。**没有真实有效的图案输入就不能生成真正可点读的 PDF。** `compose` 只负责物理尺寸不失真的叠层，不会凭空生成 OID 码。


### AI 生成原创教材初稿

此功能已纳入 CLI，但需要自己的 API 密钥与模型；**尚未在真实在线 API 上测试**。输出必须人工审核后才能给儿童使用：

```bash
# 在系统环境变量中设置 OPENAI_API_KEY，勿提交 .env / 令牌
python ant_reader.py generate-ai --topic "动物英语单词" --book-id animals_01 \
  --age 4-6 --count 6 --model YOUR_MODEL --output examples/animals_01.json
python ant_reader.py prepare --book examples/animals_01.json --out output --tts edge
```


## OID 物理打印验证工具（新增，2026-10-25）

新增 [oid_lab.py](oid_lab.py) / [打印实验说明](docs/print_lab.md)，进一步推进无贴纸直印主路线。**这不是 A8S 原生码生成器**：拿到 OidProducer 或其它可信编码器产生的真实 PNG 后，工具按源 DPI 以真实物理尺寸嵌入打印页，不对点阵进行拉伸缩放，并留存 SHA-256 审计证据。

```bash
# 没有 OID 素材也能生成不含微码的 100mm 打印标定页
python oid_lab.py blank-sheet --out output/a8s_blank_calibration.pdf
# 准备真实候选码 PNG 后（编辑 JSON 路径和 source_dpi）
python oid_lab.py candidate-sheet --manifest examples/oid_candidates.example.json --out output/a8s_candidate.pdf
# A8S 到货后，录入真实点读结果并统计，严禁填写预想结果
python oid_lab.py record --log output/scan.csv --id entry-56001 --raw-oid 56001 --expected '进入测试书' --observed '无反应' --attempts 20 --correct 0
python oid_lab.py report --log output/scan.csv
```

[候选输入示例](examples/oid_candidates.example.json) 的 PNG 路径是占位符，需替换真实候选光学码文件；无此文件时程序会拒绝生成候选测试页。正式的 A8S OID 编码与其 NOD/NOB/NOS 资源包映射仍需实机验证。当前本地 11 项测试通过（几何/日志/异常校验，**不包含识别测试**）。


### 真实第三方 OID2 候选生成（仅做兼容性研究）

GitHub Actions 新增 [Albi OID2 候选码工作流](.github/workflows/oid2-candidates.yml)，使用固定版本的 [Albi_tuzka](https://github.com/JanValiVales/Albi_tuzka) 开源编码器输出 1200 DPI 图案、码值审计及实验 PDF；点击 [成功构建记录](https://github.com/birdshao/ant_reader/actions/runs/40192874945) 下载 artifact。该编码器的内部 ID 100/101/102 分别映射到 raw OID 1331/1345/1347；这是 **Albi 码制**，不是已经确认的 A8S 码制，也尚未完成任何 A8S 实机扫描。详见 [实验说明](docs/print_lab.md)。


## 实验书：三码入口 + 全页微码铺设 + 音频交付（2026-10-25）

新增 `book_assembly.py`：在 `ant_reader.py prepare` 生成的 PDF 上按**真实物理 DPI**重复铺入外部光学码图案，不缩放、不切半码，支持独立封面入口码，生成 CSV/MP3 和非可安装的厂商交付 ZIP。**它不是 A8S 原生 OID 编码器和点读包生成器**。参阅 [三码实验指南](docs/one_card_smoke.md)。

```bash
# 先准备一张图卡（或按指南从已成功的 GitHub Actions 下载 3 个 Albi OID2 图）
python ant_reader.py prepare --book examples/oid_3code_smoke.json --out output --tts edge
# 将已验证来源的候选 PNG 和代码清单放入工作区，再运行：
python scripts/make_albi_smoke_binding.py --manifest output/albi_oid2/albi_candidates.json --book-dir output/books/albi_oid2_smoke --out output/oid_bindings
python book_assembly.py --book-dir output/books/albi_oid2_smoke --binding output/oid_bindings/bindings.json --out output/albi_oid2_smoke_handoff
```

当前所有候选码值与音频映射均 **UNVERIFIED ON A8S**。不要将实验 ZIP 当点读包安装。

## A8S 设备和官方资源包安装差异探测（只读）

新增 `a8s_device_audit.py`，提供以下独立于无贴纸铺码主线的**证据采集**步骤；不构成点读包解码器：

```powershell
# A8S USB 暴露为 E: 时（请替换实际盘符）
python a8s_device_audit.py snapshot --root E:\ --out evidence\before.json
# 在官方客户端合法安装一本自己持有的书，并确认点读后：
python a8s_device_audit.py snapshot --root E:\ --out evidence\after.json
python a8s_device_audit.py diff --before evidence\before.json --after evidence\after.json --out evidence\delta.json
# 如有本地包可研究，可生成受限的文件头审计：
python a8s_device_audit.py header --file "E:\BOOK\sample.nob" --out evidence\header.json
```

**代码不会写入设备；默认只记录疑似点读文件相对路径、大小和有上限的 SHA-256。** 这一步帮助确认 A8S 的真实资源包存储行为，不能推断 OID 光学码或绕过授权。详见 [A8S USB 只读证据链](docs/a8s_usb_evidence.md)。


## OidProducer/Sonix2 PDF 光学码桥接与开源调研（2026-10-25）

已确认 [tttool](https://github.com/entropia/tip-toi-reveng)、[ttbox](https://github.com/cleracruza/ttbox) 和 [ttmp32gme](https://github.com/thawn/ttmp32gme) 提供其他品牌的整套制书链，但**暂未发现可生成 A8S 原生 NOD/NOB/NOS 点读包的可信开源工具**。详见 [开源工具兼容性调查](docs/open_source_landscape.md)。

新增 [OID-only PDF 导入](scripts/oid_pdf_bridge.py)、[入口码/区域码绑定](scripts/make_oid_binding.py) 与 [操作指南](docs/oidproducer_bridge.md)：通过厂商可信工具输出纯微码 PDF，按物理毫米坐标/DPI 裁取成 PNG，再结合 `book_assembly.py` 制作实验打印 PDF。

```powershell
python ant_reader.py prepare --book examples/oid_3code_smoke.json --out output --tts edge
# 先将已授权源 PDF 和真实码值写入自己的 my_oid_pdf_import.json
python scripts/oid_pdf_bridge.py --spec examples/my_oid_pdf_import.json --out output/oid_import
python scripts/make_oid_binding.py --manifest output/oid_import/oid_candidates.json --assignment examples/oid_book_assignment.example.json --book-dir output/books/albi_oid2_smoke --out output/oid_binding
python book_assembly.py --book-dir output/books/albi_oid2_smoke --binding output/oid_binding/bindings.json --out output/oid_experiment
```

**注意**：示例码值是占位符；PDF 栅格化/阈值化可能改变微点几何；A8S 真机兼容性、音频制包/安装仍未解决，不要把该 PDF 当作已可点读的量产书。


## 矢量 OID PDF 实验制版（不经过 PNG 二值化）

新增 [`scripts/vector_oid_assembly.py`](scripts/vector_oid_assembly.py)：将外部工具生成的 **OID-only 矢量 PDF** 按毫米尺寸直接平铺入书名入口与教材图文区域，保留矢量图形路径，不经过原先 PDF→PNG 的灰度阈值环节。来源、码值、裁剪尺寸、是否含位图都记录在 `audit.json`。新流程默认阻止缺音频、重复码、背景覆盖及无效来源；它**不能编码 A8S 原生码，也不能生成 NOD/NOB/NOS**，只能作为候选实验。详见 [矢量 PDF 制版指南](docs/vector_pdf_workflow.md)。


## A8S 原生资源包只读分析

新增 [`scripts/native_pack_lab.py`](scripts/native_pack_lab.py)，支持合法持有的 `.nob/.nod/.nos` 样本**只读结构检查**与双文件差异对比：格式魔数、SHA-256、分块熵、公共前后缀及变化区域。报告不含音频主体，不上传用户文件，不覆盖现有取证结果。该工具**不是** A8S 原生制包器，无法解出码表；[操作和解释边界](docs/native_pack_lab.md)。本地共 56 项软件测试通过（未接触 A8S）。


## A8S 原生包控制变量实验（2026-10-25）

新增 [controlled_delta_lab.py](scripts/controlled_delta_lab.py) 和 [控制变量实验指导](docs/controlled_delta_experiments.md)，在自己合法获得的多份最小资源包中，比较**只改内容 OID**或**只改音频**造成的变化。同尺寸情况下记录精确变动字节范围，并搜索同偏移的 16/32 位大小端或 ASCII 数字替换候选；跨两个 OID 变体进一步交叉检查。实验值和猜测位置不等于 A8S 真实格式规范。

```powershell
# 编辑示例中的假设码值和文件名，不要公开上传原生包
python scripts/controlled_delta_lab.py --spec controlled_delta.json --out evidence/controlled_delta_report.json
```

示例配置：[controlled_delta.example.json](examples/controlled_delta.example.json)。本轮本地 69 项软件测试通过，含独立 CLI 测试；**仍没有完成 A8S 真实 NOB 解码/制包或实机扫描**。


## Sonix-style OID2 raw code encoder (2026-10-25)

**Key advance:** `scripts/sonix_oid2.py` now generates actual 16-bit Sonix-style OID2 printed dot tiles directly in Python, without the OidProducer Windows GUI. The independent upstream comparison is **pixel-exact for three codes** (1331 / 1345 / 1347) at 1200 DPI. The source formula was documented in the MPL-2.0 Albi project and traces a specific `OidProducer10.20.exe` index↔raw conversion table. There is a separate safe parser for the *open-source* literal table; do not assume a numeric offset mapping. `scripts/make_sonix_oid2_binding.py` integrates a candidate book with existing `book_assembly.py`.

**Not yet solved:** A8S native optical compatibility, A8S-specific code pool, `NOB/NOD/NOS` resource pack creation and physical pen recognition. Generated files are experiments, not proven playable books.

- [Detailed coding rules and reproducible commands](docs/sonix_oid2_encoding.md)
- [Sample two-region OID2 assignment](examples/sonix_oid2_smoke_assignment.json)

```bash
python scripts/sonix_oid2.py render --raw-oid 1345 --dpi 1200 --width-mm 20 --height-mm 20 --out output/oid_raw_1345.png
python scripts/sonix_oid2.py verify --png output/oid_raw_1345.png --dpi 1200 --expected-raw-oid 1345
python -m unittest discover -s tests -v
```

## OID2 数字印刷敏感性仿真（设备到货前）

新增 [oid_print_stress.py](scripts/oid_print_stress.py)：对开源 Sonix 风格 OID2 图像做模糊、墨点扩散/漏点、对比度/JPEG 压缩实验，并用已知原点的数字解码器记录正确、错码和无效码块。**不是 A8S 实机识别率**；详见 [实验指南](docs/oid_print_stress.md)。

```powershell
python scripts/oid_print_stress.py --raw-oid 1345 --dpi 1200 --out output/stress_1200.json
```

## OID2 实验打印→扫描→解码（2026-10-25）

新增 [OpenCV 标定卡/识别器](scripts/oid_scan_qa.py) 与 [验收指南](docs/oid_scan_qa.md)。支持输出 A4 70mm 标定卡，四角 ArUco 标记用于相机/扫描仪透视对齐，解码中央 20mm OID2 区域，统计 32x32 重复码块多数值/错误数。安装扫描专用依赖 `pip install -r requirements-scan.txt`。此项目实验只能证明软件数字 OID2 解码；**A8S 识别和原生资源包仍未验证**。


## 无 ArUco 的 OID2 局部扫描识别（实验）

新增 [`scripts/oid_markerless.py`](scripts/oid_markerless.py)：给定一张只含**一个重复 OID2 码值**的局部扫描图，自动估算网格、校正转角、识别不对称定位点并恢复原始 raw OID，**不需要 ArUco 标记，也不需要预先输入正确码值**。独立的 [操作说明及技术限制](docs/oid_markerless.md)。

```bash
pip install -r requirements-scan.txt
python scripts/oid_markerless.py --image scans/crop.png --approx-pitch-px 16 --out evidence/local_decode.json
```

该工具尚不支持任意整页自动寻找微码位置，且只经过合成图像测试，**不代表小蝌蚪 A8S 能正确点读**。
