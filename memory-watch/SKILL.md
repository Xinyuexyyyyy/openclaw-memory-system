# Memory Watch — 记忆守护与健康监控

## 定位

`memory-guardian` + `memory-health` 的合并版本：
- **Guardian**（回路②）：操作前检查 MEMORY.md，检测冲突 → 暂停操作，强制确认
- **Health**（回路③）：定期扫描 MEMORY.md 健康度 → 生成报告

## Guardian — 守护回路（回路②）

### 触发时机

以下操作前必须调用：
- 删除文件：`rm` / `trash`
- 强制回退：`git reset --hard` / `git clean -f`
- 修改核心配置：`SOUL.md` / `MEMORY.md` / `USER.md` / `IDENTITY.md`
- 覆盖重要配置文件
- 部署/服务管理：`systemctl start/stop/restart` / `apt install`
- 修改 API 密钥或 provider 配置

### 操作

| action | 说明 |
|--------|------|
| `check` | 执行前检查，检测冲突 |
| `confirm` | 确认操作继续 |
| `deny` | 拒绝操作 |

### 输出

无冲突：放行 ✅
有冲突：展示冲突详情 + 暂停，等待用户选择 A/B/C

---

## Health — 健康检查（回路③）

### 触发方式

- **Cron**：每 4 小时自动运行
- **手动**：用户说"记忆体检"、"检查记忆"

### 检查维度

| 维度 | 规则 | 阈值 |
|------|------|------|
| 孤立条目 | 条目所在主题从未被其他条目引用 | 无引用次数 |
| 过时条目 | 超过 N 天未更新的条目 | 默认 60 天 |
| 冲突条目 | 同一主题有正反两条矛盾记录 | — |

### 操作

| action | 说明 |
|--------|------|
| `check` | 执行健康检查，输出完整报告 |
| `report` | 生成简短摘要（适合飞书展示） |

---

## 边界原则

- **Guardian 只读**：不修改 MEMORY.md
- **Health 只读**：不修改 MEMORY.md
- **冲突必须确认**：guardian 检测到冲突时，操作必须暂停
