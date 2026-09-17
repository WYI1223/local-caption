# 概率统计课堂术语表（准备稿）

[可编辑 JSON](probability-glossary.json) 用于英语课堂字幕翻译，当前仅准备词表，尚未接入应用。不会影响已运行的会话；未做真实模型的术语遵循率或延迟测试。

Hy-MT2 官方模型卡提供术语干预提示示例，方式是在翻译请求前附上源词与目标译法，不需要训练或修改模型权重。来源：[官方模型卡 Translation Task Instruction Examples / Terminology](https://huggingface.co/tencent/Hy-MT2-1.8B#hy-mt2-translation-task-instruction-examples-chinese-english-comparison)，查阅于 2026-09-16。

## 接入规则

- 只从 `terms` 中选取当前待译句实际出现的词，优先最长短语，避免把全部词表塞入每次请求。初始建议最多 8 项；这是待测试的工程起点，不是已验证最优值。
- 匹配需要词边界、大小写兼容及常见空白归一化，不能用子串把 `PDF` 匹配进其他单词。缩略词只在选定概率统计课堂词表时使用；例如其他场景的 PDF 可能是文件格式。
- `context_required` 是人工审核备注，不能无条件注入或执行替换。例如 `I mean` 不能翻译成“我均值”。
- `do_not_autocorrect` 是禁止机械纠错的例子，不是翻译禁词。没有音频或可靠上下文时，不把 EMF/ETF 强制改成 PMF/MGF，也不替换课堂举例中的 Coke、code、star。
- 没有命中时保留原普通翻译提示。术语约束不保证模型完全遵循，也不能恢复 ASR 丢掉的内容。

## 请求示例

下面是对官方提示结构的本项目示例，不是实际运行结果：

```text
参考下面的翻译：
PMF 翻译成 概率质量函数（PMF）
geometric distribution 翻译成 几何分布
将以下文本翻译为简体中文，只输出译文，不要额外解释：

What is the PMF of the geometric distribution?
```

## 后续验证

录音结束后，用相同的已确认英文短句分别执行普通提示和命中术语提示，保持模型、采样配置一致，记录术语译法、整句含义、额外输出以及延迟。包含无命中、`I mean`、PMF/MGF、错误 ASR 输入等对照。短句实验通过后，再通过实际应用的字幕保存入口验证。当前正在录音期间不启动额外模型、不占用现有翻译队列。
