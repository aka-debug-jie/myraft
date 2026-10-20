# 新版本验收与交付边界

最终实现提交为 `ef130d9`。规模/延迟矩阵对应 `88bd633`；最终仅撤除重复的实验进度复制并收紧打包字节绑定，Raft、界面和只读采集路径相同。最终 Go、race、原生构建及六页操作另行回归。原 `2de62ea` 课程验收记录与正式 ZIP 不回写、不覆盖。

原正式 ZIP 已重新核验，SHA-256 为 `596bddfbd01177d45aafa30661367d73a18e64ac9915ef52fa7eb92cfa88ee10`。用户提供了后续自动桌面验收记录及 r2 摘要 `7B93621374B9E76AA098FAF63D10E426861A71AE7769F8D794E374B54F27D41D`；本工作区没有取得 r2 文件，因此本轮没有独立复核该归档。用户提供记录中的自动关窗与真人关窗继续区分。

所有下列证据均在 [validation/perf-next-20261020](../validation/perf-next-20261020/README.md)。合成 UI 状态测试不能替代真实 Raft；Linux 浏览器截图也不能替代 Windows 桌面操作。

|项目|状态|实际操作与证据|
|---|---|---|
|Go 格式、vet、构建|PASS|最终源码检查；`final-vet.txt`，构建回执|
|Linux Go / race|PASS|各 82 个顶层测试、46 个子用例；长测在常规套件中跳过，另行执行；`release-go-tests.jsonl`、`release-race-tests.jsonl`|
|Python 回归|PASS|44 项；`release-python.txt`|
|Win11 原生 Go/Python|PASS|Go 同为 82 顶层、46 子用例；Python 44 项，其中 1 个 Linux 专用项跳过；`delivery-go-tests.jsonl`、`windows-delivery-build.log`|
|3/11 节点选举、故障、恢复、少数派|PASS|Linux `final-smoke.txt`；Windows `windows-native.log`|
|原课程四规模五场景|PASS|10/20/50/100 节点，election/failover/catchup/divergence/replication 各三轮，60/60；逐轮独立 WAL 算术核查；`final-course-regression/`|
|2101 命令与当前/历史一致性|PASS|真实 11 节点六页浏览器操作；真实 100 节点截图同时保存完整状态及独立核查；`real-console-4173d24/`、`real-100/`|
|旧正式包数据升级|PASS|原正式包节点 EXE 先提交，全部停止后以新 EXE 使用原 ID/配置/数据恢复；历史 index=2102/hash/x 保持；`windows-evidence/old-package-upgrade/`|
|复制批次|PASS|11 节点 64/128/256/512 三场景各三轮；50/100 节点 128 与 512 对比，失败不隐藏；相应 batches 目录|
|共享采集与延迟样本|PASS（功能与记录）|Linux 三规模 × 0/1/5/10 浏览器，每组 200 请求、三轮；Windows 11/100 节点分别记录；不表示所有 P95 均改善|
|换届与长时间资源检查|PASS（列明范围）|11 节点 30 次停止恢复；100 节点在 30 分钟运行内完成 20 次停止恢复，基线和候选均通过；三个存活节点真实投票轮换 30 次；相应 soak 日志和 Go 回归|
|前端状态、布局、输入与动效|PASS|9 个合成测试通过，1 个未提供 live URL 的用例跳过；100 节点更新耗时单列；`ui-acceptance/`|
|六页真实操作|PASS|创建、2101 条提交、双击抑制、停止确认、重选、恢复、历史校验、实验运行/取消、导出、主题与投影；`real-console-4173d24/`|
|新绿色 ZIP 精确归档复验|NOT RUN|待对最终归档在新 Win11 中文/空格目录复验，不能由源码测试替代|
|新版本可见终端与真人关窗|NOT RUN|虚拟机没有已登录桌面；原用户提供记录不自动覆盖新版本|
|Windows race / 老师统一电脑|NOT RUN|未配置 C 工具链；没有目标电脑访问|
|无开发工具环境的规模实验|NOT RUN|规模实验仍需 Go/Python，页面明确报告缺失；普通演示另按绿色包验证|

## 性能结论

哈希编码与完整诊断的分配、计算和锁占用有可重复局部改善；整机请求 P95 存在波动，不能宣称普遍加速。初测中的退化点已进行交替运行顺序复测，Windows 和 Linux 分开呈现。成功请求分位数、失败轮次、测量边界及原始数据都保留，详见 [性能说明](performance-next.md)。

## 已发现并处理的问题

曾对实验结果输入 map 的修改增加防护；复核确认原发布路径已有深拷贝，故撤除重复复制和不必要测试，不再将该探针称为生产 SSE 缺陷。打包器新增回归，确保校验与归档使用同一份 EXE 字节；无旧包损坏证据。界面接入中修复了页面标记被误当导航按钮、快捷操作后导航遮挡、投影模式不能退出、窄屏适配裁切与后台事件补播。测试脚本中的 PowerShell PATH、压缩通配符和动画 Promise 等问题也保留记录，未通过放宽协议断言或延长任意睡眠掩盖。

## 剩余限制

无快照压缩、动态成员、请求去重或业务线性一致读。多数派及必要 Sync 保持原规则；Sync 仍在节点锁内。日志会增长，长期多 Leader 轮换的 worker 上限未消除。对永久阻塞展示 sink 的一个消费者仍有既有边界。当前测试没有给出“所有故障均无 bug”或生产环境延迟保证。
