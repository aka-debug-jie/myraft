# 存储独占、帧上限及 smoke 收尾验证

基线 `18d1e4b`，测试时为有本轮修改的工作区。`benchmark/environment.json` 保留真实 Git 基线、dirty=true、实际工具版本、源文件及二进制 SHA-256；未把基线提交冒充修复后的提交。所有记录的源码摘要与本次交付源码逐一核对一致。`source-under-test-sha256.json` 还记录 Windows 导出时的代码/测试/脚本摘要。文档后来更新，不影响构建输入。

- Linux Go 1.27.2 / Python 3.12.7：格式、vet、构建、单元、race、20 项 Python 回归、3/11 节点真实 smoke 通过。数据独占相关测试在 race 下重复 3 次。
- Win11 Go 1.26.3 / Python 3.13.12：vet、单元、存储相关 3 轮重复、20 项 Python 回归通过；原启动/11 节点演示验收通过，含中文空格路径、2101 命令、故障重选、恢复、历史前缀及进程身份检查，结束时本轮节点进程为 0。
- Windows、macOS、DragonFly/FreeBSD/NetBSD/OpenBSD 的 amd64 测试包交叉构建通过。macOS/BSD 未运行；Windows race 未执行。
- `benchmark/` 是本轮新源码的 16 轮 Linux 实验：10/20/50/100 节点 × 四场景 × 一轮，2101 条命令，seed107，16/16 PASS。单机且部分时间与其他检查重叠，只作功能回归，不宣称性能提升。原 80 轮和 closure/ux 数据未修改。

`storage-red.txt` 是新增两个回归在未修复代码上的预期失败：重复打开获准、超大帧获成功应答。`smoke-red.txt` 用同一完整 scenario 回归调用基线脚本，预期失败为实际 PASS 与所需 FAIL 不一致。它们是复现证据，不计入修复后通过数量。对应修复后输出及 `checks.json` 单独保存。

第一次 Windows 全套 Python 检查有 3 个原报告测试报错：便携解释器的隔离 `_pth` 不加载脚本目录，子进程无法导入相邻的 benchmark 模块。随后仅在本轮测试目录复制解释器、补充当前 scripts 路径，20/20 通过；没有改原解释器或报告代码，也没有跳过断言。该环境问题保留在 checks.json 中。

公开文件移除了主机绝对路径、guest PID 和本地结果目录；节点 WAL、锁文件、虚拟机、工具和原始进程日志未公开。用法及保证边界见 [修复说明](../../docs/storage-safety.md)。
