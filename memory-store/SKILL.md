# Memory Store — 记忆存储引擎

## 定位

SQLite + BM25 + ChromaDB 向量的三层存储引擎。
供 `memory-flow` 等上层模块调用，不单独面向 agent。

## 底层实现

实际代码在 `../memory-facade/`（store.py / bm25_store.py / vector_store.py）。
本 skill 是存储能力的统一出口。

## 存储结构

```
SQLite    → 主存储（结构化记忆：id/topic/project/content/时间戳）
BM25      → 关键词检索（中文 jieba 分词）
Vector    → 语义检索（ChromaDB + Ollama nomic-embed-text）
RRF 融合  → BM25 + Vector 混合排序
遗忘曲线  → 长时间未访问的记忆降权
```

## 表结构

```sql
memories(
  id TEXT PK,
  content TEXT,
  topic TEXT DEFAULT 'general',
  project_id TEXT DEFAULT 'default',
  created_at TEXT,
  updated_at TEXT,
  tombstoned_at TEXT,
  access_count INTEGER DEFAULT 0
)
```

## 操作（Actions）

### `insert`

写入一条记忆。返回 id。

### `search`

Faceted 检索：按 topic / project_id / keyword 过滤。

### `hybrid`

BM25 + Vector RRF 融合搜索。

### `soft_delete`

软删除（标记 tombstoned_at）。

### `purge`

清理超过 N 天的 tombstoned 条目。

### `stats`

各 topic 条目数量统计。

## 调用方式

```python
# 内部调用（memory-flow 等）
import sys
sys.path.insert(0, '~/.openclaw/workspace/skills/memory-facade')
import store as _s
_s.insert(content="...", topic="lessons", project_id="default")
results = _s.search(topic="lessons")
```
