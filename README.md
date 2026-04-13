# OpenClaw Memory System

**版本**: v2.0  
**框架**: OpenClaw AgentSkill  
**许可证**: MIT

---

四模块协作的长期记忆管理系统。覆盖记忆的**捕获 → 存储 → 编排 → 监控**全链路，支持 SQLite 本地存储、BM25 全文检索、ChromaDB 向量检索，以及操作前的冲突守护和定期健康扫描。

---

## 🎯 核心价值

- **三层存储**: SQLite（结构化）+ BM25（全文）+ ChromaDB（向量），各司其职
- **自动捕获**: 对话中自动检测记忆信号，无需手动标注
- **智能归并**: 按主题分类、自动去重、冲突确认，归档过程可审计
- **Guardian 回路**: 高风险操作前自动检查 MEMORY.md，检测正反记忆冲突
- **Health 回路**: 定期扫描孤立/过时/冲突条目，保持记忆健康

---

## 🗂️ 模块架构

```
                    ┌─────────────────┐
  对话/外部信号 ────▶│  memory-capture │───▶ pending-extract.md
                    └────────┬────────┘
                             │ 触发 /memoryre
                             ▼
┌──────────────────────────────────────────────────────┐
│                    memory-flow                        │
│  解析 → 分类 → 冲突检测 → 归并写入                    │
└──────────┬───────────────────┬───────────────────────┘
           │                   │
           ▼                   ▼
   ┌───────────────┐   ┌─────────────────┐
   │ memory-store   │   │   MEMORY.md      │
   │ (三层存储引擎) │   │ (结构化 Markdown) │
   └───────┬───────┘   └─────────────────┘
           │
           ├──▶ SQLite（结构化数据）
           ├──▶ BM25（全文检索）
           └──▶ ChromaDB（向量检索）
           
                    ┌─────────────────┐
   高风险操作 ──────▶│  memory-watch    │───▶ Guardian 冲突检测
                    └────────┬────────┘
                             │ cron / 手动
                             ▼
                    ┌─────────────────┐
                    │   Health 扫描    │───▶ 健康报告
                    └─────────────────┘
```

| 模块 | 职责 | 触发方式 |
|------|------|---------|
| `memory-capture` | 对话中自动检测记忆信号，写入待归档队列 | 自动注入 |
| `memory-flow` | 解析 → 分类 → 冲突检测 → 写入存储 | 手动 `/memoryre` |
| `memory-store` | SQLite + BM25 + ChromaDB 三层存储引擎 | 被 memory-flow 调用 |
| `memory-watch` | Guardian（冲突）+ Health（健康扫描） | 操作前 / cron |

---

## 🚀 快速开始

### 前置依赖

- OpenClaw Agent（≥ v0.9）
- Python ≥ 3.10
- `chromadb`（向量存储，可选，不安装则仅 BM25）
- `rank-bm25`（全文检索，可选）

### 安装

将整个目录放入 OpenClaw workspace 的 `skills/` 目录：

```bash
cp -r openclaw-memory-system/* ~/.openclaw/workspace/skills/
```

各模块独立也可运行，完整功能需要四模块协同。

---

## 📂 目录结构

```
openclaw-memory-system/
├── memory-capture/     # 记忆自动捕获
│   ├── SKILL.md
│   └── skill.py
├── memory-flow/        # 记忆编排层（核心调度）
│   ├── SKILL.md
│   └── skill.py
├── memory-store/       # 三层存储引擎
│   ├── SKILL.md
│   └── skill.py
├── memory-watch/       # 守护 + 健康监控
│   ├── SKILL.md
│   └── skill.py
├── LICENSE
└── README.md
```

---

## 💡 使用方式

### 自动捕获（memory-capture）

对话过程中自动检测记忆信号（偏好表达、明确决策、教训反思等），静默写入 `memory/pending-extract.md`，不打断对话。

### 手动归档（memory-flow）

```
/memoryre
```

触发后：
1. 读取 `memory/pending-extract.md`
2. 解析主题、分类（Profile / Tech Stack / Decisions / Lessons 等）
3. 检测与现有记忆的冲突
4. 写入 MEMORY.md + SQLite
5. 生成归并报告

### 高风险操作前（memory-watch Guardian）

```
watch check rm -rf /important/path
```

- 检测 MEMORY.md 中是否有相反记忆
- 有冲突 → 暂停操作，要求确认
- 无冲突 → 继续执行

### 定期体检（memory-watch Health）

```
watch check
```

- 检测孤立条目（在 MEMORY 中只有标题，没有正文引用）
- 检测过时条目（超过 60 天未更新）
- 检测冲突条目（同一主题正反记忆并存）

---

## 🧠 存储结构

### MEMORY.md（结构化 Markdown）

```markdown
# MEMORY

## 1. 个人画像 (Profile)
...

## 2. 技术栈 (Tech Stack)
...

## 3. 项目全景 (Projects)
...

## 4. 关键决策 (Decisions)
...

## 5. 教训与原则 (Lessons)
...

## 6. 重要教训详情
...
```

### SQLite Schema

```sql
CREATE TABLE memory (
    id          TEXT PRIMARY KEY,
    topic       TEXT NOT NULL,
    sub_topic   TEXT,
    content      TEXT NOT NULL,
    source       TEXT,          -- 来源文件/模块
    memory_type  TEXT,          -- preference / decision / lesson / fact
    created_at   TIMESTAMP,
    updated_at   TIMESTAMP,
    deleted_at   TIMESTAMP      -- 软删除
);

CREATE VIRTUAL TABLE memory_fts USING bm25(memory_fts, ...);
```

---

## ⚙️ 自定义分类主题

编辑 `memory-flow/skill.py` 中的 `SECTION_MARKERS`：

```python
SECTION_MARKERS = {
    "Profile": "个人画像",
    "Tech Stack": "技术栈",
    "Decisions": "关键决策",
    "Lessons": "教训与原则",
    "Projects": "项目全景",
    ...
}
```

---

## 🔗 协同工作流

### 与 Project SOP 集成

项目关键决策自动触发 capture：

```python
# project-sop 在每个节点调用
from memory_capture import handle as capture_handle
capture_handle("capture", {
    "signal": "decision",
    "content": "我们决定用 ChromaDB 做向量库"
})
```

### 与 Guardian 集成

所有高危操作通过 `memory-watch` 的 Guardian 回路：

```
操作 → memory-watch.check(operation=...) → 有冲突? 
  → YES: 暂停 + 确认
  → NO:  继续执行
```

---

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE)
