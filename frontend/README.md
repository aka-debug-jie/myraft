# React 拓扑原型

这是一套共用数据和操作层的 React 应用，提供两个拓扑渲染器；不是两个各自轮询、各自写入的控制台。其他五个工作区仍链接到原版真实页面，选型后再迁移。

## 构建与运行

开发构建需要 Node 24 LTS 和 npm，依赖由 `package-lock.json` 锁定。页面运行不需要 Node、Vite 服务或外网 CDN。

```bash
cd frontend
npm ci
npm run typecheck
npm test
npm run build
cd ..
go build -o raft-node .
go build -o raft-console ./cmd/dashboard
./raft-console -node-bin ./raft-node -source-dir . -allow-control
```

- SVG：`http://127.0.0.1:8080/prototype/?renderer=svg`
- React Flow：`http://127.0.0.1:8080/prototype/?renderer=flow`
- 并排：`http://127.0.0.1:8080/prototype/?renderer=compare`
- 原六页：`http://127.0.0.1:8080/`

Windows 可执行文件扩展名为 `.exe`。`-allow-control` 只开放本机明确启用控制的可能性，仍需在页面中确认。右上角会话菜单可启用控制、创建 11/100 节点、恢复和停止自有进程；只读预览禁止这些动作。关闭浏览器不会关闭集群。

Vite 只输出到 `cmd/dashboard/static/prototype/`，不会清空原页面。构建产物随源码保存，已有 `go build ./cmd/dashboard` 仍可直接使用已构建页面。修改 TypeScript 后需要先运行 `npm run build`，再重建 Go 程序。`npm run dev` 是构建监视，不启动绕过同源约束的开发代理，也不替代 Go 的嵌入重建。

## 操作

点击节点查看检查器及报告关系；点击空白或 Escape 取消选择。关闭检查器保留选择，再按 Escape 清除。搜索接受 `100` 或 `#100`，会聚焦节点及有效 Leader 关系。普通滚轮不直接缩放；Ctrl/Cmd+滚轮、双指或工具按钮可缩放。方向键/Home/End 遍历节点，只有一个节点 Tab 入口。

100 节点默认全体可见，手机缩略时隐藏过小编号，搜索和聚焦显示身份与关系。状态筛选弱化其他节点，不改变固定成员。小地图按需展开。图中没有虚拟中继或组主干；Follower 报告不等于网络链路、复制 ACK 或多数派确认。

顶栏“校验当前”和侧栏“一致性证据”分别提供完整校验、固定检查点、历史校验和导出；提交受理、提交确认、全体应用和完整校验分别展示。未知写入不自动重发。

## 验证

```bash
python scripts/prototype_ui_test.py --url http://127.0.0.1:8080 --output new-evidence/prototype-ui
python scripts/prototype_acceptance.py --dashboard ./raft-console --node ./raft-node --output new-evidence/prototype-real
python scripts/prototype_lifecycle.py --url http://127.0.0.1:8080 --output new-evidence/lifecycle
python scripts/prototype_interaction_benchmark.py --url http://127.0.0.1:8080 --output new-evidence/interaction-performance
```

第一条在 Playwright 中拦截合成数据，不发送真实写入；第二条在独立目录运行真实 11/100 节点并控制自己创建的进程。两者都需要测试用 Python 与 Playwright Chromium。真实脚本会保留配置、WAL、日志与证据，结束时关闭自己的进程。

生产目录没有离线 demo 开关。断线只显示未知，不切换到演示数据。SSE、Host/Origin、CSRF 和权限沿用现有 Go 接口，React Flow 不能修改节点成员或创建协议关系。
