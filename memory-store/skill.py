"""Memory Store — 记忆存储引擎

底层实现全在 ../memory-facade/（store.py / bm25_store.py / vector_store.py / hybrid_search.py / forgetting.py）。
本 skill 是对外的统一存储入口。

存储分工：
  memory-flow  → write（insert / soft_delete）
  memory-watch → read（search / stats）
  agent        → skill 接口（search / stats / hybrid / purge）
"""

import sys
from pathlib import Path

_FACADE_DIR = Path(__file__).parent.parent / "memory-facade"


def _lazy_load():
    """延迟加载 facade 各模块"""
    mods = {}
    for name, file in [
        ("store", "store.py"),
        ("bm25", "bm25_store.py"),
        ("vector", "vector_store.py"),
        ("hybrid", "hybrid_search.py"),
        ("forgetting", "forgetting.py"),
    ]:
        p = _FACADE_DIR / file
        if p.exists():
            import importlib.util
            spec = importlib.util.spec_from_file_location(f"mf_{name}", str(p))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mods[name] = mod
    return mods


def handle(action: str, params: dict) -> dict:
    """Skill 入口 — 存储相关操作"""
    m = _lazy_load()
    store = m.get("store")

    if not store:
        return {"reply": "❌ memory-facade store.py 未找到", "available": False}

    # ── 初始化 ───────────────────────────────────────────────
    if action == "init":
        try:
            store.init_db()
            return {"reply": "✅ 数据库初始化完成"}
        except Exception as e:
            return {"reply": f"❌ 初始化失败：{e}"}

    # ── 写入 ────────────────────────────────────────────────
    if action == "insert":
        content = params.get("content", "")
        topic = params.get("topic", "general")
        project_id = params.get("project_id", "default")
        if not content:
            return {"reply": "❌ content 不能为空"}
        try:
            mem_id = store.insert(content=content, topic=topic, project_id=project_id)
            return {"reply": f"✅ 写入成功", "id": mem_id, "topic": topic}
        except Exception as e:
            return {"reply": f"❌ 写入失败：{e}"}

    if action == "soft_delete":
        mem_id = params.get("mem_id")
        if not mem_id:
            return {"reply": "❌ 缺少 mem_id"}
        ok = store.soft_delete(mem_id)
        return {"reply": f"{'✅' if ok else '⚠️'} 软删除 {'成功' if ok else '失败（可能已删除）'}"}

    if action == "purge":
        days = params.get("days", 60)
        dry = not params.get("execute", False)
        result = store.purge_old(days=days, dry_run=dry)
        if dry:
            return {"reply": f"[DRY-RUN] 将清理 {len(result)} 条", "to_delete": result}
        return {"reply": f"[EXEC] ✅ 已清理 {len(result)} 条", "deleted": len(result)}

    # ── 读取 ────────────────────────────────────────────────
    if action == "search":
        topic = params.get("topic")
        query = params.get("query")
        project_id = params.get("project_id")
        include_tombstoned = params.get("include_tombstoned", False)
        results = store.search(
            topic=topic, query=query, project_id=project_id,
            include_tombstoned=include_tombstoned
        )
        if not results:
            return {"reply": "✅ 无结果", "count": 0}
        lines = [f"✅ {len(results)} 条：\n"]
        for r in results:
            lines.append(f"[{r['topic']}] {r['content'][:60]}... | id={r['id'][:12]}")
        return {"reply": "\n".join(lines), "count": len(results), "results": results}

    if action == "stats":
        conn = store._get_conn()
        rows = conn.execute(
            "SELECT topic, COUNT(*) as cnt FROM memories "
            "WHERE tombstoned_at IS NULL GROUP BY topic ORDER BY cnt DESC"
        ).fetchall()
        conn.close()
        topics = dict(rows)
        total = sum(topics.values())
        lines = [f"📊 共 {total} 条记忆\n"]
        for t, c in sorted(topics.items(), key=lambda x: -x[1]):
            lines.append(f"  {t}: {c} 条")
        return {"reply": "\n".join(lines), "total": total, "by_topic": topics}

    # ── 混合搜索 ────────────────────────────────────────────
    if action == "hybrid":
        hybrid = m.get("hybrid")
        bm25 = m.get("bm25")
        vector = m.get("vector")

        if not all([hybrid, bm25, vector]):
            return {"reply": "❌ 混合搜索组件未就绪"}

        query = params.get("query", "")
        topic = params.get("topic")
        top_k = params.get("top_k", 5)
        alpha = params.get("alpha", 0.5)

        bm25_store = bm25.MemoryBM25Store()
        vector_store = vector.MemoryVectorStore()

        results = hybrid.hybrid_search(
            query=query, top_k=top_k, alpha=alpha, topic=topic,
            bm25_store=bm25_store, vector_store=vector_store, store=store,
        )

        if not results:
            return {"reply": f"✅ 无相关记忆（{query}）", "count": 0}

        enriched = []
        for r in results:
            mem = store.get_by_id(r["id"])
            if mem:
                r["content"] = mem["content"][:100]
                enriched.append(r)

        lines = [f"🔍 混合搜索「{query}」（BM25 α={alpha}）：\n"]
        for r in enriched:
            lines.append(f"  [{r['topic']}] {r['content'][:60]}... | score={r['combined_score']:.3f}")

        return {"reply": "\n".join(lines), "count": len(enriched), "results": enriched}

    # ── 索引重建 ────────────────────────────────────────────
    if action == "rebuild_bm25":
        bm25_mod = m.get("bm25")
        if not bm25_mod:
            return {"reply": "❌ bm25_store 未找到"}
        memories = store.search(include_tombstoned=False)
        idx = bm25_mod.MemoryBM25Store()
        idx.build(memories)
        return {"reply": f"✅ BM25 索引重建完成（{len(idx.doc_ids)} 条）", "count": len(idx.doc_ids)}

    if action == "vector_upsert":
        vector_mod = m.get("vector")
        if not vector_mod:
            return {"reply": "❌ vector_store 未找到"}
        memories = store.search(include_tombstoned=False)
        vs = vector_mod.MemoryVectorStore()
        vs.upsert(memories)
        return {"reply": f"✅ 向量索引重建完成（{vs.count()} 条）", "count": vs.count()}

    return {"reply": f"未知操作：{action}，支持：init / insert / search / stats / soft_delete / purge / hybrid / rebuild_bm25 / vector_upsert"}
