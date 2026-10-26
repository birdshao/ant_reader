# A8S 原生码值 / 厂商点读包实验桥接（证据驱动）

**状态：未得到可验证的 A8S 原生 NOB/NOD/NOS 格式规范、合法制包 SDK 或真实 A8S 测码样本。本文不声称已完成原生制包。**

## 先分清三种值

| 字段 | 含义 | 可信来源 |
|---|---|---|
| `raw_oid` | 纸面 OID2 16 位点阵编码 | 我们的数字编码器 `sonix_oid2.py`，不等于 A8S 必然可读 |
| `vendor_code` | 小蝌蚪客户端“测码”或制作软件要求输入的编号 | **必须从 A8S/厂商客户端的实际观测取得**，不能假设为 raw 或 Albi 内部索引；脚本允许 uint32，但**实际码宽还未确定** |
| `audio_index` | `ant_reader` 内部稳定的教材逻辑音频编号 | `audio_manifest.json`，不等于前面两个 |

另有 `book_id` 书籍上下文：A8S 有同码书籍选择逻辑，不能强行使用全局一张码→MP3 表。

## 实际找到的资料

- [小蝌蚪客户端自制教程：找音频→测码→按码值命名→合成→安装](https://jingxuan.douyin.com/m/video/7382631383451094324)。公开视频**不能证明**我们已经有当前授权客户端与无人值守 CLI。
- [A8S 百度网盘安装原生点读包，DAB 不能直接作为 NOB](https://www.douyin.com/video/7522358097243884810)。
- [A8S 同码书管理](https://www.10100.com/article/106571954)。同一纸面入口码需要书籍上下文/选择机制。
- [新版客户端 DAB→NOD 的 T6 演示](https://jingxuan.douyin.com/m/video/7494335942515510587)。仅 T6 证据，**不能直接推断 A8S 可接受 NOD 或同种包格式**。

**新增关键原始线索**：[小蝌蚪授权合成工具视频与文字记录](https://www.douyin.com/shipin/7380947731973539859) 描述的流程为：登录**已授权**的 Windows 合成工具 → 新增书籍并填写封面选书码 → 选取 XLS 配置、音频文件夹 → 合成出 `nob.tmp`（视频自动转写有误，应以实际文件为准）→ 上传 → 申请在线点读。这个线索证明存在软件合成路径，**但不代表其可公开下载，也不能确认 A8S 固件接受这个中间文件而不经服务端签发**。尤其不能擅自构造所谓 XLS 配置列。请索要授权客户端版本、空白 XLS 示例与最小原创输出。

暂未查到可信可用的开源 A8S NOB/NOD/NOS 生成器。Sonix/Albi OID2 的点阵/表并非 A8S 原生资源包格式。

## 1. 测码数据与比对

复制示例 JSON 到私有目录，使用 A8S 测码、官方客户端显示值填入真实观测。示例全为**未验证**的 Albi 编号，不可标记为 `confirmed:true`：

```powershell
python scripts/a8s_native_bridge.py mapping `
  --observations examples/a8s_native_observations.example.json `
  --out evidence/native_mapping_hypotheses.json
```

得到 `identity_raw_to_vendor` 假设的匹配计数。若已经合法取得 `OidProducer10.20` 开源提取的 65536 项 `int2raw.json`：

```powershell
python scripts/a8s_native_bridge.py mapping `
  --observations private_samples/real_a8s_observations.json `
  --oidproducer-table private_samples/int2raw.json `
  --out evidence/native_mapping_comparison.json
```

即使两个 OID 关系吻合，也只形成假设，**不等于识别出固件实际编号规则**。数据冲突（同一本 raw 对应不同客户端号，或相反）直接列出；不同书籍允许独立上下文。

## 2. 生成厂商客户端输入（不是 NOB）

在 `ant_reader prepare` 和 `make_sonix_oid2_binding.py` 完成后，必须首先通过**真实的小蝌蚪客户端测码实验**确认该书封面与每个内容码的 `vendor_code`，并记录来源；没有有效记录不能复制生成客户端输入。用户需手工核实/授权后，将原创 MP3 作为客户端输入。

```powershell
python scripts/a8s_native_bridge.py stage `
  --book-dir output/books/albi_oid2_smoke `
  --binding output/sonix_bindings/bindings.json `
  --observations private_samples/real_a8s_observations.json `
  --out output/a8s_vendor_input
```

输出 `vendor_client_input/{vendor_code}.mp3`、`vendor_import_manifest.csv`、`manifest.json` 和 README。**不会创建 `.nob/.nod/.nos`，不会往点读笔写入文件**。是否可以直接导入、是否需要额外书名入口或索引文件仍由官方客户端实测决定。

> 安全说明：证据对象中的 `source_note` 不要写真实设备序列号、云端 token 或儿童语音内容；GitHub 不要提交 `private_samples/`、`evidence/`、原生包或音频。

## 3. 原生制包逆向的最小控制变量实验

先借厂商授权客户端制作 4 个**完全原创且有权研究**的输出：

A. 基线：入口码 E，内容码 C，音频 A；B. 内容码 C→D，音频不变；C. 音频 A→B，码值不变；D. 只改入口码 E→F。

记录每一份：官方客户端版本、资源包扩展名、文件长度、SHA-256、安装行为、是否需要云端授权、真实的 `vendor_code`、A8S 固件版本。随后用仓库已有 `native_pack_lab.py inspect/compare`、`controlled_delta_lab.py` 比较差异。若包依赖动态时间戳或压缩数据，不能根据一个偏移就推断字段。

在真实样本和客户端可用前，**实现一个“猜测版 NOB 生成器”毫无可验证性，可能损坏设备书库，因此本阶段明确不这么做。**
