# 实测结果与公开范围

本目录原有结果均属于 81723b8，未覆盖或重算。本轮修复和独立测量见 [closure-20261019](closure-20261019/README.md)，当前报告使用新结果。

`18d1e4b` 后的存储独占、WAL 帧上限和 smoke 收尾修复单独记录于 [safety-20261019](safety-20261019/README.md)。它不覆盖原 80 轮、closure 或 ux 的测量；与实际测试源码的对应关系以各目录记录为准。

`publication-checks.json` 单独记录公开副本的复测与审查，不混入原 80 轮规模实验。

这些结果来自已完成的 Windows 11 KVM 虚拟机实验（8 vCPU、约 8 GiB RAM），不是 GitHub CI 或目标统一 Windows 主机的新测量。Go 1.26.3、Python 3.13.12；完整计时口径见 [课程报告](../docs/report.md)。

- `benchmark/results.json` / `results.csv`：80 轮原始数值记录，逐字节保留；16 个“规模 × 场景”组合各 5 轮，80/80 PASS。
- `benchmark/summary.json`：对应统计，逐字节保留；失败轮次不计入成功均值。
- `benchmark/environment.json`：保留 OS 版本、工具版本、CPU 数量、节点参数和测量口径；删除实际输出目录。
- `checks.json`：先前实际检查结果；未执行项仍明确列出。移除只存在于本地交付包的原始归档链接。
- `linux-race.json` / `linux-race.txt`：Linux 竞态检测记录，保留源码 SHA-256；移除内部工具会话编号。
- `source-sha256.json`：实验时保存的源码快照与公开文件的 SHA-256 对照（实测哈希不是交付目录后来修改后的文件哈希）。Go 源码、测试和实验脚本保持一致。公开启动脚本仅移除对仓库外 `Environment.ps1` 的自动加载，使用当前 PATH；报告生成器仅更新公开文档和证据位置。

原始节点日志、诊断归档、Windows 会话转录、节点数据、二进制、工具安装包、虚拟机及课程原压缩包不在公开仓库中。报告中的历史故障讨论来自本地保留记录；公开汇总不能替代完整原始日志审计。

从仓库根目录重新生成报告：

```shell
python scripts/render_report.py --benchmark validation/benchmark --validation validation/checks.json
```

重新测量：

```shell
python scripts/benchmark.py --nodes 10 20 50 100 --entries 2101 --rounds 5 --seed 42 --timeout 120
```

新结果默认保存于忽略的 `.test-output` 目录。脚本会记录本机环境，公开新结果前请再次脱敏。单机多进程和每组五次测量不代表生产、多机或广域网的性能保证。
