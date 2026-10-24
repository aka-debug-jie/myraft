# 空采样时间修复与只读创建请求核验

日期：2026-10-24。基线：`ad3193e498a5a4ee2b4d1ad3f15cb890ec320638`。

## 修复范围

新建控制器尚无会话时，Go 的 `completed_at` 为 `0001-01-01T00:00:00Z`。
原界面直接用当前时间减去它，在 Hero 和底栏显示约 639 亿秒。原操作新鲜度检查已经排除这个零时间，因此本次发现是显示错误，不是错误开放写操作。

`frontend/src/actions.ts` 新增小型共用 `sampleAge`，缺失、无效和 Go 零时间返回无样本；`App.tsx` 与 `fresh` 共用该计算。Hero 和底栏显示“等待首次采样”。有效旧样本仍显示实际年龄，仍判定为过期。未改变 Go 生产代码、API、SSE、Raft、WAL、权限顺序或未知写入不自动重试规则。

`frontend/tests/api.test.ts` 覆盖零时间、缺失、非法值、有效历史时间和过期状态。`scripts/sample_age_ui_test.py` 对真实空控制器等待实际 SSE 后检查两处文案，并将非法时间及旧样本回放单独标为合成测试。SVG、Flow、compare 均覆盖桌面及手机。

## 只读 create 为什么可能返回 409

现有检查顺序是 Host / Origin / CSRF → 请求格式 → controller / session / generation → 只读控制权限 → busy / 参数 → 创建任务。

| 请求条件 | 实际返回 | 副作用 |
| --- | --- | --- |
| 会话信息匹配，控制未开启 | 403，`console is read-only` | 无创建任务、会话或节点 |
| controller / generation / session 错误或必要字段缺失 | 409，`session generation changed` | 无创建任务、会话或节点 |

`cmd/dashboard/operations_scope_test.go` 用真实 HTTP 测试服务器验证空会话和已附着会话共 10 种请求，包括服务器允许控制、但使用者尚未显式启用的情况。每例同时核对响应正文和状态未改变。

这是已有保护顺序的回归覆盖，不是权限漏洞修复。用户提供的 Windows 验收摘要没有原始请求字段与响应正文，因此不能将那一次 409 的具体原因宣布为已证实。进一步归因时应保存三个会话字段、响应状态/正文及请求当时的会话信息；不要导出 CSRF token。仅凭 HTTP 状态码不能判断命中了哪项保护。

## 验证与证据

Linux 本轮：前端类型检查、36 项单元测试和生产构建通过；Go fmt/vet/build、普通及 race 回归各 156 个测试项通过、1 个可选长时测试跳过；Python 46 项通过。

浏览器专项 9 项通过：6 项真实空控制器检查，3 项合成非法/过期时间检查。原 Phase 1 交互 12 项、恢复与回执 6 项通过。证据保存于 `validation/sample-time-hotfix-20261024/`，包含原版失败结果、修复后结果和同场景截图。原版浏览器使用保留的 `354d029` 可执行文件，其前端源码/资源与 `ad3193e` 无差异。

Windows 新包另名 `myraft-react-win11-20261024-r2.zip`，使用本轮源码独立原生构建。原生测试、包内文件摘要、干净目录验证与未执行项，以随 Release 提供的本轮 acceptance JSON 和 native build receipt 为准。用户此前对原包完成的 45 项实机通过记录保留为原包证据，不自动挪作 r2 成绩。

本补丁不包含新的长期性能结论，不重跑正式规模矩阵；真人关窗、Windows race 和目标老师电脑等未执行项不转为 PASS。
