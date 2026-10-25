# 架构：默认 OID 微码直印

## 核心决策

- **主路径**：AI/人工生成内容 → TTS → 可读区域布局 → 已知、可复核的 OID 原始码 → 厂商/验证过的编码器输出真实微点阵 → 将透明 PNG 以物理 DPI 嵌入 PDF → 资源包/音频索引安装 → A8S 逐点验证。
- **备用路径**：内容贴 + `DIY BOOK` MP3，只用于验证 A8S 播放链路，非最终教材设计。
- 任何阶段都不得把 `audio_index`（逻辑索引）、`raw_oid`（笔识别的光学码）、`sticker_no`（商品贴纸标号）混同。三者必须经明确绑定。
- 不把 A8S 的 NOD/NOB/NOS、DAB 当作已被逆向公开的打包规范；需要官方工具或可验证的兼容转换工具。

## 数据分层

### 教材

`examples/starter_en.json` 中 `book_id` + `items[].key` 是稳定标识；每个条目有 `word` 与 `sentence` 两个独立的点读区。将来可扩展多语言及 AI 插画。

### 逻辑索引

`output/registry.json` 自动发放稳定的 `audio_index`；在多个教材间保持唯一。该值**不等于**真实 OID 码值；务必备份。重排页面不改变此值。

### 页面与坐标

`output/books/<book_id>/artwork.pdf` 是无微码底图，`regions.json` 以**纸张左上角为坐标原点，单位毫米**，列出 `page`、`x_mm`、`y_mm`、`width_mm`、`height_mm`、`logical_id`，供独立编码器/拼版器使用。默认每张卡上方图像为单词触发区、下方整句为例句触发区，**不是贴纸小方块**。

### 音频

`audio_manifest.json` 是录音清单；`audio/<index>.mp3` 是脚本输出，仍需一个**经过 A8S 验证的映射和资源包构建器**连接 `raw_oid`。这份清单不是 A8S 原生点读包。

### 外部 OID 编码器输入

`compose` 命令需要单独 JSON 映射文件，以逻辑 ID 为键。例如：

```json
{
  "starter_en_01:apple:word": {
    "raw_oid": 12345,
    "pattern_png": "patterns/apple_word.png",
    "tested_on_a8s": false
  }
}
```

**这里的 12345 纯为格式示例，并非 A8S 已知可用码值。** 必须由外部经核验编码器给出正确的点阵图像（透明 RGBA PNG），并在图像空间预先铺满目标物理区域。

`python ant_reader.py compose --book-id starter_en_01 --out output --mapping mappings.json --dpi 600 --experimental` 会检查：区域齐全、`raw_oid` 不重复、路径不越界、PNG 是 RGBA、像素宽高等于物理区域尺寸乘 DPI（容差 1.5px）。仅无 `--experimental` 且每个绑定均明确标记为已实机验证时生成 `print_ready.pdf`。

**不要用随机点、二维码、二维码造型花纹或复制一张贴纸照片填充当作 OID 编码；渲染程序无法验证码制正确性。**

## 音频与微码的两条潜在桥接路径

**路径 A（优先研究）**：传统铺码→书名入口码→DAB/兼容 NOD 包→A8S 点读。已有开放式点读笔教程表明这类流程存在，但 A8S 上具体如何转换、码段与音频索引如何关联必须实测。

**路径 B（快速对照）**：把原装内容贴对应的 OID 直接印进教材→`DIY BOOK/<n>.mp3`。A8S 对编号内容贴的 MP3 播放有资料支持，**印出的原始微码是否等效尚不明确**。

二者不在一轮批量制书里混用，先做独立 A4 码值测试页。

## 当前边界

已实现：版式 PDF、稳定逻辑索引、区域毫米坐标、可选 Edge TTS 或自备 MP3、透明点阵叠加接口、实验模式限制、单元测试。

未实现：A8S 可识别 OID 点阵生成器、原生点读包构建器、A8S 实机识别验证、把 AI 生成器整合到新版 CLI（旧版原型已有）。

备注：直接在页面上印可读微点阵可能影响插图观感，也受打印材料、光谱反射和扫描器阈值影响。叠加透明像素的 PDF 在屏幕上正确，不意味着实体打印会被读到。
