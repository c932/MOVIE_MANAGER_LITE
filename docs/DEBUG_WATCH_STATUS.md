# 观看状态调试说明

## 1. 数据文件

观看状态持久化文件：

- `data/watch_history.json`

## 2. 诊断脚本

可使用：

- `tools/diagnostics/diagnose_watch_status.py`

用于检查观看记录是否写入、路径是否一致。

## 3. 常见异常

1. 切换“已观看”后筛选无结果
   - 检查记录路径与当前 NFO 路径是否一致（大小写、分隔符）。

2. 重启后状态丢失
   - 检查 `data/watch_history.json` 是否可写。

## 4. 建议日志点

- 状态切换时记录目标 NFO 路径
- 加载历史时记录条目数量
- 应用筛选时记录 watched 计数
