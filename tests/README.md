# Tests

跨模块测试放在本目录。与具体实现强相关的单元测试可以放在实现文件旁边，但 Agent 工具和运行时 Skill 测试放在这里，避免生产包目录混入测试文件。

## 覆盖范围

- Agent 工具调用循环和最终回答组装。
- 运行时 Skill 加载和单轮上下文激活。
- 业务数据库工具权限过滤。
- 业务查询 guard：日期窗口、限流和 Redis 兜底行为。
- MCP 服务协议行为。
- 对话记忆。
- 文档转换、清洗、切片、检索和架构边界。

## 运行

```powershell
python -m pytest -q
```

如果 Windows 默认 pytest 临时目录权限异常：

```powershell
python -m pytest -q --basetemp .pytest_tmp
```

测试数据应使用示例或临时文件。真实业务问题、评估输出、凭据和连接值不应提交到仓库。
