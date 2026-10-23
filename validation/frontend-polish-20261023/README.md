# 本轮证据 · 2026-10-23

基线 `62d78ea`，生产文件与实际执行程序绑定见 `build.json`；源码改动后的本轮结果单独保存，不替代旧课程/Windows验收。

| 文件/目录 | 类型与用途 |
|---|---|
| `real-matrix/results.json` | REAL，3/11/20/50/100，各2101+3条、重选、原盘恢复、固定前缀及三视口 |
| `real-matrix/n*/` | REAL，全景/聚焦/重选/恢复截图、节点结果、独立WAL算术参考 |
| `real-classroom/results.json` | REAL，完整11节点页面操作、实验执行与取消、导出、共享采集 |
| `real-classroom/*.png` | REAL，六页、主题、投影、手机截图 |
| `comparison/before/`、`comparison/after/` | SYNTHETIC，同输入视觉对比，各5规模×3视口 |
| `release/geometry/geometry.json` | SYNTHETIC，SVG几何采样，不代表Raft安全性证明 |
| `accepted-topology.txt`、`accepted-stage.txt` | SYNTHETIC，13,330路径、观察防抖、槽位、范围、缩放和生命周期 |
| `accepted-polish.txt`、`accepted/polish/picking.json` | SYNTHETIC，7项新增交互回归；297点实际鼠标拾取与处理时间 |
| `accepted-browser.txt` | SYNTHETIC，原24项前端回归通过、1项GET-only live跳过；真实流程另有执行 |
| `baseline/render/render.json`、`picked/render/render.json` | SYNTHETIC，同机各3轮Stage渲染，不能当作节点提交性能 |
| `final/go-*`、`final/python.txt`、`final/charts.txt` | 本轮Go/race、44项Python、14项图表断言 |
| `baseline/`、`workflow-red.txt`、`chart_ui_baseline.txt` | 基线及开发失败证据，不计作最终通过 |
| `cleanup.json` | 本轮进程和端口清理记录，其他既有服务不在清理范围 |

`provenance.json` 保留复制前后 SHA-256；少数文本里的工作区及用户目录替换为 `<workspace>`、`<home>`，原始证据仍在工作区 `.tools/frontend-polish-20261023`。截图没有修改。`SHA256SUMS` 覆盖本目录所有交付文件（不包含清单自身）。浏览器导出的原始 ZIP、过程日志、配置及 WAL 留在原始证据目录，未复制开发路径或 CSRF 凭据到此目录。

本轮 Windows、真人关窗、Safari/Firefox、长时 soak、完整课程规模统计矩阵均 NOT RUN。请结合 [修订报告](../../docs/frontend-polish.md) 阅读测试范围。
