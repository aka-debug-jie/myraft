# 发布前最终二进制复验

2026-10-23 使用最终部署的 `raft-console-deploy` 重新执行真实11节点六页流程与100节点2101条命令测试，均PASS。100份WAL独立算术校验全部通过。控制台摘要与前一轮 `frontend-enterprise-20261022/build.json` 完全一致，见本目录 receipt.json。

前一轮 `real-100-release` 的控制台是较早候选，二进制摘要不同；它保持原样，仅作为该候选的历史结果。最终部署程序以本轮复验记录为依据。源码静态文件摘要绑定见 receipt.json；测试在原工作区进行，发布副本只另行脱敏历史路径，不修改生产代码。

原始数据保留在工作区 `.tools/publish-enterprise-20261023/`。交付文本只简写机器目录，不改变数值与结果。Windows桌面/原生、Windows race、老师电脑、完整规模矩阵与长时压力均未重跑。没有生成新Windows ZIP或Release。
