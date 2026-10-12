# AI 使用记录

本文件记录当前仓库轨迹与本轮工作中可以核实的 AI 使用，不代表对其他未记录操作的完整追溯。

## 使用的 AI 技术与工具

- **OpenAI Codex**：用于检查作业要求、阅读代码、诊断工具调用与上下文压缩的边界问题、修改实现、运行验证、分析真实轨迹、整理实验报告及准备提交归档。本轮还通过官方 DeepSeek 文档核对 thinking、输出预算和工具调用约束。
- **DeepSeek 官方 API，`deepseek-flash`**：作为作业 harness 中的语言模型。`CodeAgent` 使用终端工具与 `invoke_skill` 生成 chess-app 和 Django 补丁；`ChessAgent` 使用 `play_move` 完成基础对局与两种观察条件实验，并在 skill 演示中生成 Python 搜索代码。Part 2 的工作记忆摘要也由模型生成。
- **Codex 的写作风格技能**：辅助保持报告的直接、克制表达；实验结论来自仓库中的轨迹、结果及验证日志。

Codex 通过终端、Python、pytest 和 Modal 沙箱检查上述输出；这些执行与验证工具本身不替代模型。没有用脚本伪造 LLM 响应、实验轨迹、补丁生成过程或缺失模型的结果。模型生成的棋步选择 Python 仅在远程沙箱执行。

## 使用范围与证据

- Part 1：模型通过 coding harness 生成 `artifacts/fix.patch`；行动与工具交互见 `artifacts/part1-trajectory.json`。
- Part 2：压缩版与完整上下文 baseline 的真实模型交互见两份 `django__django-15368` 轨迹；token 用量与实验限制见 `artifacts/token-usage-analysis.md`。
- Part 3：基础对局、DeepSeek 的两组观察实验和程序化搜索见对应轨迹；计数和观察条件见 `artifacts/observation-experiment.md`。
- 当前没有配置 GPT-OSS 接口，因此尚未执行该模型的两组实验。提交归档会明确标记为 partial，不会将 DeepSeek 的结果替代为 GPT-OSS 结果。

模型输出经过检查与验证，但不能将通过测试等同于全面正确，也不能将一次对局推广为稳定的棋力结论。首次程序化演示曾暴露模型对评分规则的翻译错误，因此补充了结构化字段说明并重跑；保留了原始尝试作为本地诊断资料。

## Recap

AI 用于 harness 实现、补丁与棋步生成、模型摘要以及实验整理；结果以真实轨迹和执行验证为依据。目前缺少 GPT-OSS 两组实验，不能声称完成全部作业。
