# 前端操作与视觉修订

本轮基线为 `2b50228`，主要实现提交为 `aa8dddf`，随后将原始任务载荷改为展开时才序列化，避免折叠任务栏重复处理大型实验结果。保留深石墨色的独立节点舞台、六个工作区、Go embed 静态页面和本机控制边界；没有引入 Node.js 构建链或前端框架。14个 config/raft/rpc 生产文件与基线逐文件相同。旧ZIP、原课程报告和历次实验不回写。

## 操作问题与修复

|问题|复现及修复|验证位置|
|---|---|---|
|创建请求正在发送，按钮仍显示可用|延迟合成POST复现；现在立即同步busy与禁用状态，双击仍只发送一次|`dashboard_ui_test.py` delayed create|
|输入时后台状态已变，主区按钮未同步|聚焦输入期间推送撤销控制帧后失焦复现；表单DOM持续保留，独立live区域更新，草稿/光标不丢失|revoked control、focus/navigation|
|会话代次改变后旧确认框仍可发送|旧确认框基线携带旧代次；现立即失效关闭，发送前再核对scope|generation confirmation|
|乱序bootstrap覆盖新状态|控制GET返回顺序复现；请求序号保护会话列表与权限，CSRF从当前bootstrap显式传递|older bootstrap|
|控制器重启与迟到回包边界|新测试覆盖旧控制器回执丢弃、身份读取首次失败后的受控重试、错误节点身份不能标成准备完成|controller reply/retry、workflow identity|
|结果仅有短暂通知，课堂步骤不清楚|增加按需演示抽屉与持续回执；受理、提交、应用、校验和恢复分开显示。结果未知时同一确认框禁止重发|真实11节点浏览器流程、unknown POST|
|100节点小屏初次截断、连线密集|首次和未手动操作后的视口改变自动fit；默认按选中节点显示关系，节点拖动超过6px才转为平移，键盘焦点自动移入|Stage独立回归、真实100节点截图|
|导航、提示和排版不一致|静态/运行导航统一六页；hash前进后退；停止影响按自有进程和可达性分别说明；日志结构化比较、实验复选参数与高级折叠|六页截图与浏览器回归|

原停止请求的后端身份/代次保护一直存在，本轮旧确认框探针不是“已经误停其他会话”的证据；原内部防重复发送也有效，按钮外观问题不等于已经重复写入。

保留原生dialog并修正其外层aria-hidden；危险确认聚焦取消，关闭回到操作入口。展示节点的进程所有权与节点可达性分别判断，节点失联不妨碍控制器停止自有进程。写入不确定时不会自动重发；接口请求有10秒浏览器等待上限，超时不代表后端操作未执行。

## 视觉与资料取舍

首页继续以真实节点和逻辑关系为主体。11节点位置固定；Leader通过低饱和青绿和轮廓区分，换届不重排。超过15节点采用独立网格，全部关系需要显式展开。演示流程、节点详情与任务回执覆盖画布而不挤压布局。其他页面以日志矩阵、事件时间线、实验图和验证结果为主体；大段原始JSON与高级参数按需展开。

本轮参考了六个GitHub项目及官方交互资料，只使用设计方法，没有复制模拟状态或引入其运行依赖：

- [RaftScope](https://github.com/ongardie/raftscope)、[The Secret Lives of Data](https://github.com/benbjohnson/thesecretlivesofdata)：课堂实验的操作与结果对应。
- [XYFlow](https://github.com/xyflow/xyflow)及其[可访问性说明](https://reactflow.dev/learn/advanced-use/accessibility)：键盘聚焦与视口可见性。
- [D3 Zoom](https://github.com/d3/d3-zoom)和[交互说明](https://d3js.org/d3-zoom)、[Cytoscape.js](https://github.com/cytoscape/cytoscape.js)：画布平移缩放、点击与拖动区分、关系展示密度。
- [Carbon](https://github.com/carbon-design-system/carbon)的[空状态](https://www.carbondesignsystem.com/building-blocks/core/patterns/empty-states)与[就地加载反馈](https://www.carbondesignsystem.com/building-blocks/core/components/inline-loading/guidelines)：明确下一步和任务进度。
- [W3C对话框](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/)及[状态消息](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html)：焦点、错误、取消与辅助技术反馈。

## 实际验证与来源

完整本轮记录见 [validation/frontend-ux-20261021](../validation/frontend-ux-20261021/README.md)。浏览器合成测试只证明交互行为，不作为Raft共识证据；真实集群、Win11原生程序与最终ZIP分别记录。

|检查|实际结果|证据|
|---|---|---|
|Linux fmt / vet / build|PASS|fmt/vet、构建后的真实浏览器运行|
|Linux Go / race|各90顶层、52子测试通过，1个可选长测跳过|go-tests.jsonl、race-tests.jsonl|
|Windows原生 Go|90顶层、52子测试通过，1长测跳过；vet/build通过|native-go-release.jsonl、native-build-release.log|
|Python标准库回归|Linux44通过；Windows43通过、1个Linux专用跳过|python-tests.txt、native-build-release.log|
|浏览器合成回归|21项：20通过、1个未提供live URL的只读检查跳过|ui-on-demand.txt|
|3/11节点smoke|故障、恢复、少数派检查通过|smoke.txt|
|真实11节点六页流程|2101条、停止取消、故障重选、原盘恢复、固定前缀、实验运行/取消/导出通过；页面错误0|real-complete/results.json及九张真实截图|
|真实3节点演示主线|从演示抽屉提交2101条；故障后额外3条；恢复及原检查点一致|real-guided/results.json、workflow-real.png|
|真实100节点页面|2101条提交、完整状态及独立算术核查；桌面/手机首次全部可见|real-100-release/|
|共享采集|1/5/10浏览器各5轮，monitor RPC均55|real-complete/results.json|
|Windows最终绿色包|精确ZIP的新目录实操由包旁 `.acceptance.json` 绑定；未取得该回执时不视为已验收|交付目录同名回执|
|Windows可见桌面、真人关窗、race、老师电脑|NOT RUN|不以后台API或Linux浏览器替代|

Stage独立检查同时验证了点击/拖动区分、双指缩放下限、键盘平移、聚焦可见和destroy清理。合成测试没有发送真实节点操作。

初轮集成检查保留在 `ui-first.txt` / `ui-second.txt`：发现确认框外层 `aria-hidden`，以及旧测试对多选下拉/折叠参数的定位不适用。修复可访问性，并按真实复选/展开操作更新测试；没有放宽请求次数、数据一致性或协议断言。

真实11节点截图拍摄于故障和监控实验之后，日志已超过初始2101条，不把这些截图称为“恰好2101条”的瞬间。

### 提交延迟观察

同一Linux主机/Go1.27.2，11节点，每请求256条命令；每组6个样本。计时包含HTTP、任务轮询和调度，轮询间隔100ms；两组均开启共享采集。系统负载没有完全隔离，不计算稳定加速或可靠P95/P99。

|版本|浏览器|样本数|中位数(s)|最小(s)|最大(s)|
|---|---:|---:|---:|---:|---:|
|baseline-2b50228|0|6|0.2272|0.2092|0.2645|
|baseline-2b50228|10|6|0.2304|0.2052|0.2462|
|new-fb6d807|0|6|0.2260|0.2158|0.2293|
|new-fb6d807|10|6|0.2320|0.2171|0.2495|

数字由本轮逐次记录计算，原始值见 `latency-observations.csv` 和两个 results.json。0浏览器下中位数略低、10浏览器下略高，不能据此宣布普遍加速。任务栏的原始大载荷只在展开时序列化，未新增节点轮询。

### 真实界面

[六页截图](../validation/frontend-ux-20261021/real-complete/) · [真实演示流程](../validation/frontend-ux-20261021/real-guided/workflow-real.png) · [100节点桌面](../validation/frontend-ux-20261021/real-100-release/desktop.png) · [100节点手机](../validation/frontend-ux-20261021/real-100-release/mobile.png)


## 复现

先按README构建 `raft-node` 和 `raft-console`；普通Windows绿色包不需要Go/Python/Node.js。开发浏览器回归另需Python Playwright和Chromium。

```sh
python scripts/dashboard_ui_test.py --url http://127.0.0.1:8080 --output 新证据目录
python scripts/stage_ui_test.py --output 新画布证据目录
python scripts/dashboard_e2e.py --node ./raft-node --dashboard ./raft-console --output 新真实实验目录
```

第一条对目标服务只读取；合成状态会拦截API。第三条是POSIX开发验收，会创建独立控制器与节点并负责清理；Windows使用绿色包启动入口和原生验收步骤，不能用后台测试冒充可见桌面或真人关窗。

## 限制

没有新增真实网络分区注入器，页面继续禁用分区按钮。原课程能力保留，本轮不重复完整四规模五场景矩阵或长时压力；旧版本结果不自动升级成新版本验收。Windows race、真人关窗与老师统一电脑实测继续单列NOT RUN。局部UI耗时与少量提交观察不代表生产性能保证。
