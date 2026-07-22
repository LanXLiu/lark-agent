# Operations

`ops/` 保存运维命令入口和项目资源。

命令模块负责解析 CLI 参数，并调用 `app`、`knowledge` 或 `infrastructure` 中的可复用实现。

## 模块

| 模块 | 职责 |
| --- | --- |
| [`scripts/`](scripts/README.md) | 文件上传、chunk 写入、召回检查、collection 初始化和文档删除 |
| [`docs/`](docs/README.md) | README 和项目文档使用的截图与资源 |

所有命令建议从项目根目录执行。
