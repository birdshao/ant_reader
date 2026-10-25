# OID2 印刷失真敏感性实验（设备到货前）

这是已知码块位置的**数字图像实验**，不是打印机、扫描头或小蝌蚪 A8S 实机识别仿真。输出不代表 A8S 成功率。

运行：
```powershell
python scripts/oid_print_stress.py --raw-oid 1345 --dpi 600 --out output/stress_600.json
python scripts/oid_print_stress.py --raw-oid 1345 --dpi 1200 --out output/stress_1200.json
```

程序复用 `sonix_oid2.py` 的 Sonix 风格 OID2 编码器，在理想像素图上施加：baseline、blur_0_4、blur_0_8、blur_1_2、dot_gain_1、dot_loss_1、low_contrast、jpeg_70 八种实验档。

- 对每个完整的 32×32（600 DPI）或 64×64（1200 DPI）点阵**预先知道其准确原点**，按 7 个定位点及 9 个数据点采样，输出 `correct/wrong_oid/unreadable`。
- 模糊半径与墨点大小的单位为数字像素，**不同 DPI 下物理尺度不一致**；不能凭这些数值决定打印机选型。
- 没有模拟纸张吸墨、实际碳粉颗粒、红外反射、自动网格定位、旋转/透视校正或设备侧信号处理。
- 未生成 A8S 原生 NOB/NOD/NOS，也未确认 A8S 可以识别这些 OID2 原始码。

到货前建议：向品牌方获取一组有效的 A8S 书名码、两个内容码、对应原始微码图与最小点读包；用 OID 打印标尺提前检查设备是否按实际尺寸输出。到货后先用原装内容贴与 DIY BOOK 验证音频链，再对完整入口→内容→对应资源包进行真机测试。

所有实验报告状态均为 `SYNTHETIC_DIGITAL_ONLY_A8S_UNVERIFIED`。
