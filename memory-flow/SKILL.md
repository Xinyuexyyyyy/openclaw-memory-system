# Memory Flow — 记忆编排层（v2）

## 定位

记忆系统的**编排层**，负责：
1. **捕获阶段**（对接 memory-capture）：接收 pending-extract.md 中的待归档内容
2. **归并阶段**：解析 → 分类 → 冲突检测 → 写入 MEMORY.md + SQLite
3. **归档报告**：生成日报、返回归并结果

**本 skill 是 /memoryre 的唯一执行入口**，不重复。

## 架构位置

```
memory-capture          memory-flow              memory-store
(signal detect)    →    (orchestrate)       →    (SQLite storage)
                        ↓
                    MEMORY.md (主存储)
```

## 存储分工

| 模块 | 职责 | 存储位置 |
|------|------|---------|
| `memory-flow` | 编排逻辑（归并/冲突/日报） | 读写 MEMORY.md |
| `memory-store` | SQLite 持久化（BM25/向量/Garbage Collection） | memory.db |
| `memory-capture` | 信号检测、pending 写入 | pending-extract.md |
| `memory-watch` | 健康检查、冲突预检 | 只读 MEMORY.md |

## 触发词（唯一入口）

- `/memoryre`
- `/archive`
- `归档本轮对话`
- `提取上下文`
- `记住我们这轮对话的内容`

## 操作（Actions）

### `archive` — 执行归档

**前置条件**：`memory/pending-extract.md` 有内容

**流程**：
1. 读取 `pending-extract.md`
2. 按主题块解析（`### 主题：` 分隔）
3. 对每个主题块：
   - 定位 MEMORY.md 对应章节
   - 冲突检测（同一主题新旧内容矛盾？）
   - 无冲突 → 归并写入
   - 有冲突 → 展示冲突，等待用户选择
4. 双写 SQLite（通过 memory-store）
5. 生成/更新当日日报
6. 清空 pending-extract.md
7. 返回归并报告

### `preview` — 预览归并结果（不写入）

扫描 pending，展示归并计划，不执行。

### `status` — 查看归档状态

pending 条数、最后归档时间、SQLite 统计。

## 主题映射

| pending 内容特征 | MEMORY.md 章节 |
|-----------------|---------------|
| 名称/偏好/沟通风格 | Profile |
| 技术选型/工具比较 | Tech Stack |
| 项目启动/进展/完成 | Projects |
| 明确决策/架构选择 | Decisions |
| 教训/错误反思/改进 | Lessons |
| 当日工作记录 | memory/YYYY-MM-DD.md |

## 冲突处理

冲突时展示：
```
⚠️ 冲突：[主题名称]

**现有**：[MEMORY.md 内容摘要]
**新内容**：[pending 内容摘要]

A) 保留现有
B) 更新为新
C) 手动编辑
```
