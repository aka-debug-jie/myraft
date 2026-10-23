# 前端修订证据

基线2b50228；主要实现aa8dddf；最终运行代码fb6d807。源码摘要、测试计数和逐次延迟汇总见 `summary.json`，正式说明见 [frontend-ux-review.md](../../docs/frontend-ux-review.md)。

- `regression-red.txt` 保存旧行为红测；`ui-first.txt`/`ui-second.txt` 保存中间集成失败；最终 `ui-on-demand.txt` 21项中20通过、1个live-only项跳过。新旧DOM控件测试分别采用实际多选/复选操作。
- `go-tests.jsonl`、`race-tests.jsonl`、`native-go-release.jsonl`：各90顶层、52子测试通过，1可选长测跳过。测试代码不等于测试矩阵全覆盖。
- `native-release-receipt.json` 将36个生产输入绑定到Windows EXE摘要；生产集合与最终源码逐文件核对。
- `real-baseline/`与`real-complete/`是同机相同负载的真实11节点测试；`real-guided/`是新增抽屉的真实3节点流程；`real-100-release/`保存实际100节点状态和独立WAL算术核查。3/100集成运行于aa8dddf，最终fb6d807仅将隐藏回执改为按需展开，最终11节点完整流程另行通过，不混淆各证据版本。
- 所有原始WAL、受控会话和失败输出保留在隔离测试目录；只将复核材料纳入仓库。`provenance.json` 记录原始/交付摘要，文本本机路径缩写、JSON中的进程ID去除，截图不改动。
- 精确最终ZIP验收在包旁 `.acceptance.json`；可见桌面、真人关窗、Windows race及老师电脑未执行。旧正式包和历史证据不覆盖。
