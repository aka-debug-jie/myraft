# 视觉重构 2.0 · Phase 0 评审

按使用者提供的 2.0 说明，本轮只完成“视觉地基、顶栏、左侧导航与背景”，在视觉方向评审处停止。**尚未进入 Hero/KPI、暖金 Leader、节点卡片或 Inspector 重做。**SVG 继续作为主版本，Flow/compare 保留技术对比。

## 修改

- `frontend/src/theme.css`：增加深蓝黑、薄荷、暖金及浅色/投影的 shell 设计令牌。旧节点和面板令牌保留原值；暖金令牌尚未应用到 Leader。
- `frontend/src/app.css`：顶栏增至72px、品牌22px、搜索与操作控件更清楚；导航44px目标、选中指示和悬停文字；背景采用低对比网格及静态柔光。玻璃效果仅用于顶栏，并有纯色降级。
- 手机顶栏使用明确的两行布局，保留全部现有操作及无障碍标签。没有新增或重复操作入口。
- 构建产物全部来自正常 Vite 构建；没有手改产物、增加依赖、外部字体或 CDN。

节点、边、几何、交互、API/SSE/session/action 和 Go 源码均未修改。实际浏览器对照确认了节点背景、文字、边框及连线颜色保持不变。用户已有的未提交需求文件保持原样，SHA-256 为 `a1b1d4c2fad2be20e859fedae8624f83cab591628781c3fa3c300b871ffe51f6`。

## 查看

| 修改前 | Phase 0 暗色 | 浅色 | 手机 |
|---|---|---|---|
| [1440×900](../validation/frontend-redesign-phase0-20261023/before-real-11-1440.png) | [1440×900](../validation/frontend-redesign-phase0-20261023/final-11-1440-dark.png) | [1440×900](../validation/frontend-redesign-phase0-20261023/final-11-1440-light.png) | [390×844](../validation/frontend-redesign-phase0-20261023/final-11-390-dark.png) |

这些截图来自真实11节点的只读观测，非合成演示。

当前 Tailscale 评审入口：[11节点 SVG](http://100.108.139.80:8081/prototype/?renderer=svg&review=phase0)。页面内可切换 Flow 和 compare。[100节点入口](http://100.108.139.80:8082/prototype/?renderer=svg&review=phase0) 也使用同一视觉地基。

仅更新了只读控制台程序。11/100节点进程实例未改变，代理的来源与方法限制保留，POST/PUT/DELETE仍为403。原始二进制和所有旧证据仍保留，没有推送远端。

## 检查

- TypeScript、Vite生产构建通过；17项前端单元测试通过。
- 现有合成浏览器回归：30个规模/视口/渲染器组合、7组交互全部通过，测试脚本未修改。
- 真实11节点页面错误为0；手机无横向溢出；节点和边的原有颜色保持不变。
- 证据及输入摘要见 [checks.json](../validation/frontend-redesign-phase0-20261023/checks.json)。

本轮没有重跑 Windows 原生、长时性能或课程写入/故障实验，不继承旧记录为本轮PASS。Phase 0 不代表说明中的全部最终目标完成；请先评审底色、顶栏和导航方向，确认后再进入 Phase 1。
