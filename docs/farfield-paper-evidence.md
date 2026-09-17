# 远场弱语音增强：论文证据与适用边界

2026-09-16。只读文献研究，供后续实验选择；未安装或测试这些新模型，未改变应用默认设置。部署与许可核查见文末。本文针对 Windows CPU、固定 Nemotron Speech Streaming EN 0.6B Q8 后端，以及单路课堂录音；不包含私人音频或转写内容。既有实验见 [识别与降噪实验](asr-enhancement-experiment.md)。

## 1. 优先试“保留原音的增强”，有直接 ASR 证据

Ochiai 等的研究将增强误差分解，发现人工处理伪影可能比残余噪声更损害识别。其 OA（observation adding）在推理时混合增强与原音，无需重训后端。CHiME-3 真实录音 et05 的表 VI：原音 WER 28.7%，SNR 损失训练的增强器 31.7%，再混入 40% 原音为 22.5%。实验后端是 Kaldi DNN-HMM，并非 Nemotron；数据还包含 WSJ/CHiME 与 CSJ/DEMAND 模拟组合，不能直接移植改善幅度。[论文、数据与表 VI](https://arxiv.org/html/2404.14860v1)

**工程推论：** 把 `输出 = α × 对齐后的原音 + (1−α) × 增强音` 作为低成本首选消融。测试 α=0、0.25、0.5、0.75、1，先校正模型延迟、样本长度和输出增益。论文的 SAR 改善结论不等于所有 α 都降低 WER；参数应在开发片段选定，再验证其他片段，不能只挑最好结果。原音基线必须保留。

此前本项目 RNNoise 的半强度混合仍有漏词，说明回混不是必然有效。那次结果也不能否定其他前端；更换模型后需重新配对评估。论文 40% 原音只是其条件下的一项结果，不是通用最优参数。

## 2. GTCRN 很适合 CPU 预算，但轻量不等于更准

官方 ICASSP 2024 实现目前报告 48.2K 参数、33.0 MMAC/s；README 解释这些数字与论文原始统计差异来自 ERB 模块计数和映射优化。提供 DNS3 与 VCTK-DEMAND 权重及 streaming 实现，报告 i5-12400 2.50 GHz 的 RTF 0.07。[作者项目](https://github.com/Xiaobin-Rong/gtcrn)

该证据支持把 GTCRN 纳入低开销候选，不能证明在当前电脑和 NeMo＋翻译同时运行时不会积压。README 展示的 DNSMOS 等是增强质量指标，不是当前 ASR 的 WER。需要分别测增强耗时、算法等待、ASR/翻译队列及连续运行内存，而非仅计算一个短文件总耗时。

## 3. DeepFilterNet3 可调衰减；弱语音要特别检查静音门限

DeepFilterNet 2023 论文的模型以 48 kHz、20 ms 窗、10 ms hop 和两帧 look-ahead 工作，报告总算法延迟 40 ms；Rust/tract 在单线程 i5-8250U 上 RTF 0.19。训练使用 DNS4，主要评估 VoiceBank/VCTK-DEMAND 的 PESQ、STOI 等，未提供本任务 ASR 成绩。论文还描述 local SNR 低于 −10 dB 时返回静音谱的条件分支，并允许调整衰减和阶段门限。[原论文](https://arxiv.org/pdf/2305.08227)

**工程推论：** 它值得作为可控衰减候选，但不能使用“越安静越好”的调参目标。先核对所选发行版是否启用相同静音策略，再测限制衰减、禁用过强门控和 OA 回混。论文门限不是对当前录音漏词原因的证明；也不能仅凭论文描述推定最新二进制行为。48 kHz 前端到 16 kHz ASR 的重采样与延迟须纳入公平比较。[官方项目](https://github.com/Rikorose/DeepFilterNet)

## 4. DPDFNet 更明确针对过度衰减，但仍缺本任务识别证据

2025 年 DPDFNet 预印本加入 dual-path RNN、过度衰减损失和面向长时间持续运行的微调；评估包含 12 种语言、低信噪比长录音。这与弱声被抑制的风险相关。论文主要报告 PESQ/STOI/SI-SDR、DNSMOS/NISQA 和组合指标 PRISM，没有给出 Nemotron 或其他 ASR 的 WER 实验。其 DPDFNet-4 的 RTF 0.97 来自 Ceva NPN32 **NPU**，不能作为普通 CPU 的性能依据。[论文](https://arxiv.org/html/2512.16420v1)

**工程推论：** 适合排在 GTCRN 后进行质量对照，优先较小模型及原音回混，不应直接替换默认前端。虽然文中称 causal，DF 模块仍写有两帧 look-ahead，不能解释成零等待。运行与授权须按具体权重核对。[作者项目](https://github.com/ceva-ip/DPDFNet)

## 5. 去混响是另一条路线，先确认问题和真实声道

WPE 利用延迟的线性预测减少晚期混响，处理的不是固定背景噪声。Caroselli 等报告在线自适应多通道 WPE 能改善远场 ASR，包括多条件训练的声学模型；但该研究是麦克风阵列场景，不能把收益照搬到单声道课堂音频。论文解释多麦不同房间响应可补充单麦频谱缺失。[Interspeech 2017 原论文](https://www.isca-archive.org/interspeech_2017/caroselli17_interspeech.pdf)

NARA-WPE 提供 NumPy 的离线、块在线与逐帧在线实现，可用作不依赖 GPU 的研究基线；其 README 列出的已测试 Python 版本为 3.7–3.10，当前 Python 3.11 环境仍需验证。[官方实现](https://github.com/fgnt/nara_wpe)

**工程推论：** 先听辨是否有明显尾音拖曳，再做小规模单通道 WPE 消融。立体声文件不自动等于独立同步阵列通道，更不能把复制的双声道当阵列。单麦收益和 CPU 实时性均未证实，优先级低于轻量增强加 OA。

同轮对目标源录音的 ffprobe 核查结果为 48 kHz、单声道，单声道不是后续降采样才造成的。现有文件无法直接提供多麦波束形成所需的独立空间观测。

## 下一轮实验约束

固定同一批含连续弱语音的 PCM，原音、GTCRN、一个更强前端及各自 OA 混合进行配对比较；保留模型状态与足够前导音频，避免每短片段重新初始化造成不公平。开发片段与保留验证片段分开。选少量能人工听清的片段建立逐词参考，报告 WER 的替换、删除、插入；听不清处明确标注，不靠另一识别器的稿子充当真值。

同 RMS 试听只用于听辨比较；送入 ASR 的实际处理信号、削波情况、采样数、延迟补偿与参数另行保存。检查被去除的声音是否包含辅音或词尾。最后再通过真实采集入口测持续队列和字幕延迟。论文 CPU RTF、感知指标和短音频词数，都不能替代本机端到端识别验证。

## 部署核查简注

以下由同轮主研究核对官方仓库/API，属于安装可行性证据，尚非本机运行测试。

- GTCRN 官方代码核对版本 `502ebfab64da7c4a9af78dcb9c6ceef1ebb01c73`，MIT。[版本与许可](https://github.com/Xiaobin-Rong/gtcrn/tree/502ebfab64da7c4a9af78dcb9c6ceef1ebb01c73)
- DPDFNet 官方代码核对版本 `9bd9844a227bb6aa57e55588d8d0e961fcff1c46`；官方权重卡声明 Apache-2.0。[代码](https://github.com/ceva-ip/DPDFNet/tree/9bd9844a227bb6aa57e55588d8d0e961fcff1c46)、[权重卡](https://huggingface.co/Ceva-IP/DPDFNet)
- sherpa-onnx v1.13.8 有 Windows x64 与 macOS arm64 发行资产。可以优先评估 GTCRN 和 16 kHz DPDFNet2，避免直接扩充现有主应用依赖。[发行版](https://github.com/k2-fsa/sherpa-onnx/releases/tag/v1.13.8)
- DPDFNet 的 sherpa `attenuation_limit` 文档限定仅离线生效；正值越大允许越强衰减，0 关闭限制，即完整增强。不能把 0 当旁路，也不能用该离线参数声称在线强度控制已可用。[官方说明](https://k2-fsa.github.io/sherpa/onnx/speech-enhancement/dpdfnet.html)
- DeepFilterNet v0.5.6 提供 Windows x64 与 macOS arm64 独立程序。Python 包的 NumPy `<2.0` 约束与当前项目 2.4.6 不兼容，若实验优先用独立程序或隔离环境。[发行版](https://github.com/Rikorose/DeepFilterNet/releases/tag/v0.5.6)、[包配置](https://github.com/Rikorose/DeepFilterNet/blob/v0.5.6/DeepFilterNet/pyproject.toml)
- DeepFilterNet 代码许可不能自动代替每个权重的许可判断；当轮查看的权重许可讨论未得到维护者澄清，打包公开发行前仍需核清。[相关 issue 709](https://github.com/Rikorose/DeepFilterNet/issues/709)

建议顺序是 GTCRN＋DPDFNet2 的原音/全增强/对齐回混对照，DeepFilterNet3 为第三候选，WPE 为确认混响后的独立探索。
