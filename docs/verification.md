# 验证与维护记录

## 2026-09-16：从本机原型整理为独立仓库

范围：只复制应用、翻译适配器和回归测试源码。未复制私人课堂录音、转写、偏好、运行日志、Python 环境或本机快捷方式到源码包。原安装未修改。模型和运行时由安装器独立部署，不进入 Git 或分享 ZIP。

实际安装入口：Python 3.11.16 执行 `scripts/setup.py --backend both --from-existing <原安装>`，创建新 venv，pip 实际下载安装依赖；模型和 Windows 引擎使用之前已下载的固定资产，经哈希验证后复制。该过程验证了从本地缓存安装，不等同于验证朋友网络上的全新模型下载。安装后的 `scripts/doctor.py --verify` 对两种模型及原生资源全量哈希检查通过。

Windows：8 项切句/时间线/积压逻辑测试、2 项分发边界测试通过；真实 ASR worker 在 0/0.1/0.5 秒停止均正常退出，耗时 0.297/0.078/0.031 秒。实际 `start.cmd` 启动独立 venv 的 GUI，点击示例，走本地 WAV → 原生 ASR → Hy-MT2 worker → 两段中英字幕 → 自动保存；回读 TXT 两段完整且没有“未完成”标记。原型已知的 JFK 否定误译仍出现，集成成功不代表翻译准确。独立环境中 `test_stream_translation.py --unknown` 在 4.66 秒完成，验证 NLLB 异常保留英文后继续翻译下一句；该测试模拟 ASR 输入边界，不代表硬件采音验收。新仓库本轮没有重跑真实系统声音硬件测试，旧原型的两分钟数据仅作背景。

macOS 初始静态检查：从 GitHub b11005 / v0.1.0 下载 arm64 归档，SHA-256 与 release digest 一致，检查了真实归档布局和文件摘要。NeMo 包有 `nemo-speech/` 顶层，llama 包有 `llama-b11005/` 顶层，必须保留对应路径及动态库布局。随后已在一台 Apple M4 Mac 上完成联网安装、资源校验和真实 Tk 示例流程验证，详见 [macOS 记录](macos.md)。真实麦克风和长期使用仍待验收；系统声音后端未实现。

## 可复用经验

- 保存修复推送后做识别/降噪消融：固定同段 PCM 分别比较流式上下文、离线、响度、高通及 FFT 降噪。所测 FFT 参数在模糊讲话上使输出明显缩短，单独降噪也复现，暂不默认开启；词更多不等于更准。`ffprobe` 容器时长与截取后实际采样长度曾不一致，实验按采样数记录音频时长，不直接将播放器请求时长或截取参数用于实时率计算。详见 [首轮增强实验](asr-enhancement-experiment.md)，仅本地实验，未随保存修复发布。

- 2026-09-16 用户要求分阶段处理：当前只修字幕保存并增加可选 WAV 留存，增强算法和识别质量保持待验证。Windows AudioArchive 在采集回调把原始设备 float32 字节送入独立有界磁盘队列，落盘 PCM16，位于增强和 downmix 前；不能放到耗时 ASR 消费之后才写，避免识别变慢时只保存已识别部分。正常停止更新 WAV 头并重命名，写入中保留 partial.wav，不覆盖同名既有文件。`test_audio_archive.py` 已验证声道、帧数、采样率、样值和拒绝覆盖，并加入 CI。
- 音频保存真实验收：通过新启动的 Windows GUI 菜单关闭增强、开启保存原始音频，系统声音采集真实播放器输出的用户指定清晰录音一分钟片段，再通过 UI 停止。实际接收 57.0 秒，WAV 48 kHz 双声道 PCM16 共 2,736,000 帧，与 captured_seconds 一致；不将播放器的请求时长直接称为实际采集长度，也未验证静音间隔的墙钟对齐。partial 文件正常改名，TXT 中保存最终 WAV 路径。实时英文 160 词 / 12 条字幕，停止前稳定前缀保留；将软件保存的 WAV 直接交给实际 NeMo CLI 离线转写成功（161 词，首尾内容均在）。证据和源代码摘要保存在本机忽略目录 `diagnostics/audio-save-check/result.json`。仅验证 Windows 系统声音短测；麦克风录音保存、强制断电、磁盘耗尽和 80 分钟课堂仍未做硬件级验收。
- 多行结果补充：C ABI 的单个 partial/final 可能含换行，GUI 正则必须用 DOTALL 接收完整结果，不能只取第一行；已加入真实 Tk 队列＋自动保存回归，并在原安装 / 新仓库重跑通过。系统声音首轮 3 分钟真实回放测试在历史累计修复后、DOTALL 补丁加载前完成（301 词 / 23 条字幕，过程快照稳定前缀保留）；最终完整补丁的真实回放由上述清晰录音验收覆盖。两个阶段不混记为同一构建。

- 2026-09-16 字幕历史覆盖修复：固定版本 NeMo-Speech.cpp v0.1.0 的 [transcribe.cpp](https://github.com/NVIDIA/NeMo-Speech.cpp/blob/v0.1.0/app/transcribe.cpp) 将每个 final 通过 append_result 累积，stderr 的 live partial/final 是当前段，退出时 stdout 才是整稿。原 GUI 对所有结果执行 self.text = updated，真实 Tk 队列＋自动保存回归已复现“First lesson complete.”在第二段到来时被覆盖（修复前第 2、3 步失败）。新 TranscriptHistory 保留已完成段，只修订当前段；CLI 分离 stderr 状态与 stdout 整稿，整稿按完整文档传递，避免分行覆盖与重复追加。原安装和独立仓库均已更新源码；启动中的旧进程需重开。历史会话未保存原始事件，不能据此精确还原每次历史丢失过程。
- 回归入口：`python -m unittest discover -s tests -p test_transcript_history.py`（6 项）、`python tests/test_transcript_persistence.py`（真实 Tk 事件队列/自动保存/回读，ASR 与已有译文采用受控输入）。后者在新仓库 Python 3.11 和原安装 Python 3.14 均通过，覆盖跨段、段内修订、已完成中文保留、多行退出整稿及非字幕日志忽略；8 项切句回归和 2 项分发测试也通过。CI 已加入两项新入口。受控事件测试不等同于模型或长课堂验收。
- 真实桌面初步验证：新启动修复版，原生 UI 点击“示例”，实际 WAV → NeMo CLI → Hy-MT2 → 自动保存并回读 TXT，英文两句均保留，中文两条；示例本身的已知否定误译仍在，不将其计为翻译质量通过。长时间课程完整性仍需长测。

- 时间线核对补充：字幕自动保存采用临时文件 replace，实测 TXT 的 Windows CreationTime 随替换更新，不能用它代替录制开始时间。应结合 start() 生成的会话文件名、JSONL 创建时间、最后保存时间及实际 captured_seconds；最后保存还可能晚于停止采集。不同最终文本范围不代表两个会话没有重叠。选离线参考音频时同时核对媒体时长、时间与内容，不能只取最新文件。

- 2026-09-16 长时双实例观察：增强麦克风会话实际触发 120 个音频块 / 12 秒上限并以退出码 1 停止。随后已接收音频计数追平、翻译队列清空，不代表停止后的讲话被保存。异常分析必须区分音频积压、待译年龄和单次推理耗时；不能仅凭缓冲区满判定内存耗尽。该会话没有同步资源采样，根因尚未验证。最终保存的两份字幕主题和范围不同，不能作为同段增强 A/B 准确率证据。后续应先保存完整输入流 / 快照并对齐音频区间，再比较；同一录音的自动参考稿也需要抽查原音。私有诊断证据保存在本机被忽略的 diagnostics 目录。

- 快速停止需区分 ASR 加载中和已开始 listening；加载中终止，已开始则先发中断让引擎 flush。Windows worker 使用专属隐藏控制台；不能广播给 GUI 或其他终端。
- Windows venv 常有启动器及真实 Python 两级进程；关闭 stdin 让真实 worker 自行退出，超时清理专属进程树。macOS 翻译 worker 建独立进程组，超时时按组清理。
- 旧窗口卡死曾由 `Text.see` 引发；当前合并渲染、用比例滚动、限制可见字符数，完整字幕单独保留。不要只因模型进程还在就判断 UI 正常。
- Windows 系统声音 worker 的 stdin 停止检查用 PeekNamedPipe；此前阻塞读线程与 NumPy 导入在原机器上出现过死锁。该经验只在 Windows 路径得到复现和验证。
- 同一快照同时改词和新增文字时，新增词必须使用新时间；否则最早待译年龄虚高。相关逻辑回归见 `test_translation_flow.py`。
- 模型 `<unk>`、循环生成和正常排队是不同问题；保留英文降级可以让队列清空，但不能计为中文翻译成功。
- 分享用 `scripts/package_source.py` 的白名单，不要直接压缩整个工作目录。源码包不带 venv；朋友安装后再运行。

## 后续验收

2026-09-16 性能补充：对正在运行的原型 GUI / 麦克风 / Hy-MT2 进程树做约 121 秒只读观察，未停止会话；额外基准在采样前取消，其不完整结果不使用。每秒读取 RSS、私有提交、CPU 时间增量，并只解析 llama-server 新增 timing 行；GUI 临时观察器读取已有队列计数，不更改业务流程，约 125 秒后自行结束。对齐同一时间窗后有 20 次推理完成，统计与解释见 [性能记录](performance.md)。新工具 `scripts/observe_resources.py` 的真实 CLI 入口已完成该次观测；其中无 GUI 探针，后者仅为原型 CPython 3.14 临时诊断，不作为跨平台功能发布。资源统计要区分工作集与私有提交，并标注系统内存压力；不要把内存受压时的 RSS 当作最低配置。

另一台 Windows 完整联网安装、连续 30–60 分钟播放、设备切换和断开；Apple Silicon 麦克风权限/采集/立即停止/退出、更多机器上的安装验证；macOS 系统声音后端。首轮 overlapping 固定样本 A/B 见 [实验记录](overlap-experiment.md)：前文泄漏没有触发输出保护，默认仍关闭；需进一步验证源范围回写与有界重译方案。

发布候选复核（保存功能单独发布）：独立 worktree 移除未发布增强/对比入口后，18 项单元测试及 Tk 自动保存回归通过；实际候选 loopback_worker 经真实播放器→系统声音→WAV 路径完成采集，退出码 0、12 秒 PCM 录音成功收尾。测试依赖的本机引擎/模型通过被忽略的目录链接复用，不进入提交。


## Temporary Windows GTCRN menu trial (2026-09-16)

Added direct menu choices for raw / 25% / 50% GTCRN, effective on next start. No dynamic gain. `app/gtcrn_mix.py` keeps online model state, a matching raw FIFO, and stateful 48-to-16 kHz FIR decimation; supports current 16/48 kHz devices and explicitly rejects unsupported rates. Stop flushes the frontend before ASR. Windows workers use the existing isolated diagnostics enhancement environment; main translation dependencies are unchanged. This is a local experimental installation, not a packaged cross-platform release.

`tests/test_gtcrn_menu_live.py` drives actual Tk menu and start/stop controls, real WASAPI playback/capture and native ASR, with translation disabled and isolated test preferences/output. All three direct-menu choices transcribed the JFK sample, saved full text and raw audio, reported correct active modes, and finished with zero ASR backlog and zero GTCRN buffered samples. Mid-stream menu changes did not change the active mode. Results: `diagnostics/gtcrn-menu-e2e/result.json`. Initial cascade-menu tests were repeated after switching to direct menu entries; these repeated audible samples were noticed by the user. Tests and audio playback have ended. Avoid repeating audible workflow checks without a clear user-facing heads-up; prefer non-audio checks for presentation-only follow-ups.

Additional checks: immediate startup cancellation for both neural modes; zero-input flush; 48,001-sample input processed whole vs arbitrary 777-sample chunks, same 16,001-sample output within 1e-5. Native screenshot inspection observed the intermediate settings menu; final direct-menu behavior was verified through actual Tk controls, not a mocked handler. Title/hint-only follow-ups do not change the audio path. Long-run simultaneous ASR/Hy-MT2 queue behavior remains for the user's trial.

New untranscribed holdout: `diagnostics/classroom-new-35m-45m.wav`, source classroom recording at container 35:00, requested 600 seconds, decoded 599.9695625 seconds at 48 kHz mono. Metadata/SHA-256 in adjacent JSON. `diagnostics/classroom-live-trial.html` provides a non-autoplay player and switching instructions. Application title includes 降噪试用 to distinguish this build; recordings and exports identify active processing mode.


### 2026-09-17：实验性 GTCRN 可选安装与反馈入口

菜单保留原版／25%／50%，实验模式明确标注，默认原版；缺少可选资源时禁用实验模式，旧的实验偏好本次回退原版。安装入口 `setup.cmd --experimental-denoise` 将固定版 sherpa-onnx 1.13.8、SciPy 1.17.1 安装到项目主虚拟环境；模型由 assets.json 下载并校验到 models/enhancement，不再引用 diagnostics 内开发机环境。源码打包白名单包含可选依赖清单及反馈模板。没有自动反馈上传。

本机 Windows / Python 3.11.16 已从 `translation/.venv/Scripts/python.exe scripts/setup.py --experimental-denoise` 完成可选依赖安装和真实网络模型下载、SHA-256 检查。doctor --verify 显示 experimental denoising ready。setup --help、修改 Python 文件编译及源码 ZIP 内容检查通过；ZIP 不含模型、录音和会话文件。

实际 Tk 菜单驱动三个模式启动系统音频 worker，再正常停止，新 UI 实例重新读取菜单保存的 50% 偏好，通过；入口 diagnostics/check_experimental_delivery.py，结果 diagnostics/experimental-delivery/result.json。测试使用隔离偏好及保存目录，未重启用户窗口、未修改用户设置、未播放声音。该短测试验证新版环境路由、设备启动、停止和偏好，不能声称新版又完成十分钟字幕质量验收。另在主虚拟环境对本地 JFK 文件进行两比例真实 GTCRN 分块处理（没有播放），两路均返回 176000 个有效样本、尾部缓冲为零。此前用户十分钟三路试用为算法及真实内容对照的既有证据。

受控覆盖：将可用性探测替换为不可用，真实 Tk 菜单回退原版并禁用两个实验选项，通过；这是条件分支测试，不是 macOS 真机验证。macOS 安装选项明确拒绝，原有路径不安装可选依赖。全新 Windows 机器安装及 macOS 真机仍待朋友验证。

维护经验：把实验交付给他人前要清除 GUI/worker 对 diagnostics 环境及模型路径的依赖，更新安装器和源码打包白名单；“开发机可运行”不足以证明源码分享后可安装。音频 E2E 会发声的测试必须事先明确，本轮复核使用无播放入口，未重跑 test_gtcrn_menu_live.py。
PR #1 合并复核：在保存修复 3906063 上整合 macOS 安装补丁 9b580b4，仅验证记录发生文字冲突，保留双方验收范围。Windows Python 3.11 下 18 项单元测试及真实 Tk 受控事件自动保存回归通过；修改后的 EnvBuilder 参数实际创建了带空格路径的临时 venv，pip 和 Tk 导入成功，解释器仍采用复制方式。安装器 --help、shell 语法检查通过。这些检查不等同于重新完成联网安装或 macOS 硬件验收；Mac 安装与示例链路依据贡献者在 docs/macos.md 中的 M4 实测记录，真实麦克风及长时运行仍待测。


### 2026-09-17 上午采集队列溢出诊断及 CI 加固

本地证据：11-06-36 与 11-31-22 会话均为原版、麦克风输入，无降噪；分别采集 1456.5 秒与 88.5 秒后队列到 120 块并触发保护。停止后约 19–20 秒才排空 12 秒输入，存在实际处理吞吐低于实时的时段。GUI 指标接收间隔未出现相应的长时间冻结，最大观测约 1.39／1.63 秒，但既有日志没有识别调用计时和资源记录，因此不能确定是 native ASR、CPU 争用／降频、内存分页还是短时输出阻塞。它们与此前“结果游标尚为零导致待识别显示很大”是不同现象。11-33-24 会话检查时仍在运行，未强制重启或叠加真实 ASR 模型压力测试。

保留 120 块溢出保护，未宣称修复根因。增加实际队列样本数／最高值／最老块等待、拒收帧、送模完成秒数及结果游标、callback 时间和状态、native 阶段耗时、输出阶段停留、进程 CPU/RSS/private/page faults 和系统 CPU/可用 RAM；GUI 保存 worker 消息传递耗时及待处理事件数。独立线程每秒写同会话 capture.jsonl，不经过 stdout/Tk，每会话轮换一份、约 40 MiB 上限，不记录语音文本。源码摘要和 PID 用于核对下次运行版本，诊断写盘失败仅提示，不停止采集。资源探针需要 psutil，旧环境缺少时其他探针仍工作。

区分方法：queue 增长且 asr_push/results 长时间活动，进一步用进程 CPU 与系统 CPU/内存判断计算或资源压力；stdout 长时间活动而独立心跳持续提示消费者背压；queue 为零但 result_lag 很大是结果发出滞后，不能误判采集堵塞。若连心跳也中断，仍需调查进程调度、GIL/native 持锁或磁盘阻塞，不能凭缺日志指定根因。

验证入口：run_ci.py unit/gui/frontend。新增队列溢出及无结果时空队列测试、独立心跳与轮换测试；test_capture_worker_contract.py 通过真实 worker 参数入口、callback、队列、JSONL 及 WAV 文件路径验证正常收尾及溢出退出，音频设备和 ASR 为受控替身，不冒充硬件或真实识别复现。真实 GTCRN 16/48 kHz 空输入／任意分块／flush 用小型 ONNX 模型验证，不播放音频。Tk 5000 次字幕事件响应回归接入 CI；纯逻辑双系统运行；测试清单漏项立即失败。旧 CI 只覆盖 22 项单测和保存回归，未覆盖渲染压力、真实降噪或队列溢出。


GitHub PR #3 首次云端验收：Windows/Linux 逻辑、Windows Tk 与受控 worker、真实 GTCRN 前端及 Required CI 汇总均通过（run 35242858607）。本地新增未分类测试的反向探针被 run_ci.py 正确拒绝，随后移除。main 已启用分支保护：要求 PR、分支跟上 main、GitHub Actions 的 Required CI 成功；管理员同样受约束，不额外要求第二位审批人。禁止把未运行的硬件测试归为 CI 通过。此配置由 GitHub API 读取确认，不依靠 README 宣称。


### 2026-09-17 晚间输入设备溢出（与 12 秒队列溢出区分）

18:22 与 18:23 两次会话的新 capture 探针均记录 callback_status=2（本机 PyAudioWPatch 常量 paInputOverflow），应用 queue overflow_count=0，queue_high_seconds=1.2；实际采集分别为 10.3 / 62.1 秒。此处为上游输入流已丢弃数据的报告，不能套用上午 120 块应用队列满的结论。[PortAudio 状态定义](https://portaudio.com/docs/v19-doxydocs/portaudio_8h.html)。当前实现收到非零设备状态即停止，因此这些会话没有继续采集，但 WAV 正常收尾不表示上游丢失的声音被恢复。

两次采集期间可用 RAM 最低 107.62 / 7.77 MiB；这是严重资源压力证据，但不是因果对照。stdout 最大调用耗时均约 0.016 秒，不支持长时间输出背压为此次直接原因。page_faults 是累计页错误，包含软缺页，不能当硬盘换页次数。停止后的资源快照不能替代故障当时进程归因；尤其 private commit 不能当常驻物理内存。下一步优先同输入、同模式的内存充足对照，仍需排查驱动／回调调度。未自动关闭其他进程、修改缓冲上限或忽略设备丢帧。

脱敏数值摘要在 diagnostics/input-overflow-20260917-evening.json；原始探针保留在本地 transcripts。本次仅诊断与记录，没有部署行为变更。


### 2026-09-17 旧版稳定性的回归排查：保存录音会切换采集后端

用户补充旧版可能是增加原始音频保存之前。对比 960cae0 / 3906063 与当前 GUI：旧麦克风走 nemo-speech --live；原始音频保存或增强启用后走 Python loopback_worker。故不能把“同一麦克风／同一负载”当作同一采集实现，也不能只归因于内存。新增 18:31 会话在可用 RAM 最低约 916 MiB 时仍报 input overflow，未证明内存是充分或必要条件。

本机只读枚举证实 get_default_input_device_info 默认是 MME，44.1 kHz／2 声道；Windows WASAPI 同一麦克风端点为 48 kHz／4 声道。候选修正通过 WASAPI host 的 defaultInputDevice 明确选麦克风，缺少 WASAPI 时才回退并记录 route；系统声音回环入口保持一致。probe 新增 host API、device route/index、默认输入延迟，便于核对。Windows 默认 PyAudio 输入不等于 WASAPI 默认输入，是本次确认的配置差异；它是否解释实际溢出仍待同条件实测。

新增设备选择两项测试及真实 worker 控制边界回归通过；只读本机枚举验证候选实际选中 WASAPI 48 kHz。检查时旧 native --live 会话正在运行，没有打断它或叠加另一 ASR 模型；因此未宣称声卡连续采集或稳定性已经验证。诊断分支保留候选，不立即合并 main。当前可用的旧路径对照是原版＋关闭原始音频保存；不能在保持保存开启时声称已经回到旧路径。新增探针锁竞争仍是待排除因素，此次只改设备选择以避免混淆对照。

保存原始音频现改为每次启动显式选择，不从旧偏好恢复开启状态；手动勾选仍可用于当前应用会话。已将旧偏好为 true 的启动、真实菜单手动开启以及持久化关闭状态接入现有 Tk 保存回归（CI gui 组）。此调整不改变字幕自动保存。用户授权先推送当前候选，WASAPI 长时硬件稳定性仍待实测。
