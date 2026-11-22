# 002 接续运行与分组进度

## 变更

- `runs` 增加 `baseline_run_id`：本次运行接续的上次已完成运行，用于按组增量重算。
- `runs` 增加 `progress`：JSON，保存 `{done: {组指纹: 组解}, total: 组数}`，供中断后恢复。
- 删除 `schedules`、`deliveries` 的模型引用（该业务流程不再使用定时分发）。

## 升级语句（MySQL 8）

```sql
ALTER TABLE runs
  ADD COLUMN baseline_run_id INT NULL,
  ADD CONSTRAINT fk_runs_baseline FOREIGN KEY (baseline_run_id) REFERENCES runs (id),
  ADD COLUMN progress JSON NULL;
```

已有历史运行的两个新字段保持 `NULL`，按「不接续、无进度」处理，可直接复用。
