# A8S OID 无贴纸直印实验室：可重复的打印、识别与映射验证

**优先级 P0**。本工具不会从数字原生编码 A8S OID，也不包含厂商专有算法。它解决的是：有一个候选图案之后，如何**不经图像缩放**精确地印出来、记录来源与实机识别结果。

## 1. 无设备也能做的准备

```bash
python oid_lab.py blank-sheet --out blank_a8s_calibration.pdf
```

该 A4 页**没有微码**，可用来确认打印机按 100% 实际尺寸输出：用尺量测最下方 100 mm 标尺，误差超出你的工艺容差时先调整打印机驱动。无需提前购买/粘贴内容贴。

## 2. 拿到真实的候选 OID PNG 以后

输入示例：`examples/oid_candidates.example.json`。将 `YOUR_REAL_OID_IMAGE.png` 改成经过 OidProducer 或其它可信编码器**实际生成**的 PNG，图片必须放在 manifest 所在目录或其子目录。配置中的 `source_dpi` 是**源码图像的生成 DPI**，不是 Windows 打印机选项；二者不要混淆。

```bash
python oid_lab.py candidate-sheet --manifest /path/candidates.json --out test_oids.pdf
```

输出 `test_oids.pdf` 和 `test_oids.audit.json`。每个候选有：OID 数值、来源、SHA-256、源像素、物理尺寸。原始 PNG 像素不会被重采样/拉伸。超出测试格的图像会拒绝，而不是强行缩小。默认每页六个码，自动分页，打印尺寸为 A4。

**重要：** 印出光学候选码不等于能在 A8S 上播放声音。常见资源包需要先用封面入口码选择相应书包；若没装包，可能识别到码也不能播放。`56001/25001` 是传统点读笔教程出现的**候选码值**，绝非 A8S 官方保证码段。A8S 部分型号用 NOD/NOB/NOS 等格式，DAB 不能直接假定可装。

## 3. 实物到货后记录每种码的结果

先验证“笔读取官方点读书”“A8S 内容贴 + DIY BOOK MP3”作为音频校准，再做微码直印试验：

```bash
python oid_lab.py record --log scan_results.csv \
    --id entry-56001 --raw-oid 56001 \
    --expected "进入测试书" --observed "无反应" \
    --attempts 20 --correct 0 --wrong-audio 0 \
    --printer "laser-printer" --dpi 1200 --paper "普通复印纸" --mode "离线"
python oid_lab.py report --log scan_results.csv --out scan_report.json
```

记录真实观察，不猜测结果。报告按 `(candidate id, raw_oid)` 累计测试次数、正确次数、错播次数、正确率。实验室暂定阈值：**同一码至少 100 次、正确率 >= 99%、错播 0 次**；它不是厂商保证值，更不是一个无需上机的合格证。真正的端到端验收还要求：码和音频绑定正确、重启/离线正常、多本书无冲突。

## 4. 编码器候选与避坑

- 传统 OidProducer：小达人/部分小蝌蚪开放式点读笔教程中实际使用过的铺码工具，应优先获取可信、可授权的 Windows 版本以及示例点读包。它可能没有脚本接口，**应先完成一个书名码 + 两个内容码的人工导出闭环**。
- [Albi_tuzka 的 `oid_png_generator.py`](https://github.com/JanValiVales/Albi_tuzka) 开源支持 Albi 兼容 OID2 PNG，命令行可指定 600/1200 DPI，但**不能据此认定适配 A8S**。其授权采用 MPL 2.0；本项目不直接复制其源码。用于第三方码制对照实验时保留原始来源。
- [tttool](https://github.com/entropia/tip-toi-reveng) 是 Tiptoi 生态工具，其输出码制与尺寸不自动适配 A8S。普通二维码、Anoto 位置点阵、随机点并不是 A8S 的 OID 替代品。
- 严禁把 `raw_oid`、编号 MP3、内容贴编号视为同一个数字；它们是三个独立标识，只有**配套资源包 + 实机**才能建立映射。

## 5. 优先验收矩阵

1. 1200 DPI 黑色碳粉/白纸；印小块，扫 20 次；若成功，扩大至 100 次。
2. 600 DPI 黑色碳粉/白纸；码点尺寸、驱动策略保持记录。
3. 同一有效码印在浅色插画/文字下，测正确率与错播。
4. 关 Wi-Fi、重启 A8S，测试点读包是否离线可用。
5. 两本不同书，使用各自入口/内容码，检查误播放及碰撞。

任何一种失败都不要把源图案写成 `tested_on_a8s=true`，直到完整链路符合验收条件。

## 外部资料

- [A8S 官方使用短视频：NOB 包、DAB 不可直接装的注意事项](https://www.douyin.com/video/7522358097243884810)
- [传统开放式点读笔铺码/点读包教程](https://www.bilibili.com/video/BV1RG4y1Y7wx/)
- [Albi/Tiptoi OID 物理码尺寸不同的分析](https://tatageek.blog/2021/01/28/jak-funguje-albi-tuzka/)
- [工业 OID 打印精度建议：1200 DPI、碳黑、尺寸检查](https://www.talkpens.com/info/oid-printing-requirements2-20025970.html)


## 6. 可复现的 Albi OID2 对照码生成（实验，不代表 A8S 兼容）

GitHub Actions 工作流 [oid2-candidates.yml](../.github/workflows/oid2-candidates.yml) 自动固定第三方 Albi_tuzka 提交 `04dbe89903534bc2b0b661684ad514f269217775`，分别用其 **内部编号** 100、101、102 生成 1200 DPI、20×20mm 的 OID2 PNG，同时读取其 `bnl_utils.oid_table` 取得**实际 raw OID**（两者不相等时绝不混为一谈）。然后调用我们的 `candidate-sheet` 生成实验打印 PDF 和 SHA-256 审计报告，上传为 GitHub Actions artifact。MPL 上游源码不复制入本仓库。

请不要将这组 OID2 候选标注为“小蝌蚪有效码”；若 A8S 无法识别，只能说明当前码制/固件/书包/打印条件下没有打通，不能推断整机不支持铺码。优先使用厂家或 OidProducer 可确认的码图与配套书包进行真正闭环验证。