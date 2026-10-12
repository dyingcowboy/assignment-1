# Part 3：观察接口对非法走法的影响

目前完成 DeepSeek 的两组实验。GPT-OSS 接口尚未配置，因此该模型的两组轨迹和结果缺失，本报告不能视为作业要求的完整四组实验。

## 实验条件

两组均使用 DeepSeek 官方接口的 `deepseek-flash`、`reasoning_effort=low`、行动输出上限 4,096 token、200 次行动请求上限、1,800 秒沙箱期限。对局由 Part 1 生成的 `fix.patch` 修复服务器，模型执白，确定性服务器 bot 执黑。两组均启用 6,000-token 阈值的上下文压缩，保留最近一个完整步骤；摘要关闭 thinking，输出上限为 1,200 token。

对照条件包括棋盘、FEN、轮次、check 状态和近期历史。board-only 条件省略 `legal_moves`，让模型推断合法动作；另一条件额外提供合法走法列表，并提示模型从该列表选取。两组不启用 `simulate_move`、`run_python` 或 chess skill。这比较的是两种完整观察接口，包括相应提示语。

## 结果

| 模型 | 观察条件 | `play_move` 调用 | 非法走法拒绝 | 非法走法比例 | `game_over` | 结果 |
|---|---|---:|---:|---:|---|---|
| DeepSeek | 棋盘，不列合法走法 | 51 | 3 | 5.88% | true | White wins |
| DeepSeek | 棋盘与合法走法 | 23 | 0 | 0.00% | true | Black wins |
| GPT-OSS | 棋盘，不列合法走法 | — | — | — | 未运行 | 缺少接口 |
| GPT-OSS | 棋盘与合法走法 | — | — | — | 未运行 | 缺少接口 |

证据：board-only 的 [轨迹](part3-no-legal-moves-deepseek.json) 与 [结果](part3-no-legal-moves-deepseek-result.json)；提供合法走法的 [轨迹](part3-legal-moves-deepseek.json) 与 [结果](part3-legal-moves-deepseek-result.json)。不把此前中断或 provider 错误的诊断轨迹合并到正式实验中。

| 辅助指标 | 不列合法走法 | 提供合法走法 |
|---|---:|---:|
| 行动请求 | 55 | 29 |
| `finish_reason=length` 回合 | 4 | 6 |
| 压缩事件 | 21 | 12 |
| 实际棋局 ply 数 | 95 | 46 |

计数方法：每个响应中的 `play_move` 调用计一次；只将工具返回的 `not legal` / `illegal move` 拒绝计为非法走法。非法走法比例为非法拒绝数除以全部 `play_move` 调用数。无工具调用的 reasoning 截断回合不计为非法走法。工具观察按所属 assistant action 匹配，允许不同回合重复使用同一 `tool_call_id`，避免将下一回合或压缩前的重复历史误计入。

提供的 logger 不保存最终工具观察，所以最后一步通过 result 中的 `human_move`、终局状态和棋谱交叉核对。`scripts/prepare_submission.py --replay-chess` 可以在临时目录中从 pinned source 应用真实补丁，重新执行直接走法，核对完整最终状态与非法走法数；不修改 `chess_app/`。

## 可以与不可以推出什么

这一次样本中，给出合法走法的条件没有产生非法调用；board-only 条件产生了 3 次非法调用。这符合“显式合法动作集合能减少模型自行推导规则的负担”的解释，但每个条件只有一次运行，不能据此估计稳定的失误率，也不能断言任何棋力差异。没有合法走法列表的一组获胜，也不能说明省略列表会提高棋力。

两个对局长度不同，模型选择的局面与行动不同，压缩次数和截断回合也不同。因此总调用数不能作为两种接口效率的严格因果比较。`length` 代表输出预算截断，和走法是否合法是两个不同指标；恢复请求关闭 thinking 并强制工具调用，之后再恢复普通行动的 `low` 设置。

## 后续配置调整

由于 4,096-token 上限下出现仅有 reasoning、未输出工具调用的回合，后续普通行动的默认上限已提高为 8,192，thinking 仍为 `low`；摘要仍关闭 thinking 并保留 1,200-token 上限。强制工具恢复保留 harness 传入的 4,096-token 上限。通过 `DEEPSEEK_REASONING_EFFORT` 和 `DEEPSEEK_MAX_TOKENS` 可显式覆盖普通行动设置。

这是一项依据本项目失败样本制定的工程配置，不是官方推荐的最优数值，也没有用同局面重复实验验证其性能收益。以上正式两组实验均在旧的 4,096 上限下完成，未因后续配置变更而改写。官方 API 说明见 [Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/) 与 [Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/)；thinking 工具交互需要回传各回合的 reasoning，强制工具选择则需要关闭 thinking。

## Recap

DeepSeek 两组均到达终局，非法走法分别为 3/51 与 0/23；单次样本支持观察接口有影响，不能证明棋力或稳定失误率差异。GPT-OSS 两组尚未执行，四组实验仍不完整。
