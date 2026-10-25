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
