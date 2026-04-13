"""Memory Capture — 记忆自动捕获"""
import re
import sys
from datetime import datetime
from pathlib import Path

# 延迟引入 hybrid search（避免启动慢）
_facade_loaded = False
_hybrid_mod = None

def _get_hybrid():
    global _facade_loaded, _hybrid_mod
    if _facade_loaded:
        return _hybrid_mod
    _facade_loaded = True
    facade_dir = Path(__file__).parent.parent / "memory-facade"
    try:
        import importlib.util
        # 加载 store
        spec = importlib.util.spec_from_file_location(
            "mf_store", str(facade_dir / "store.py"))
        store_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(store_mod)
        # 加载 bm25
        spec = importlib.util.spec_from_file_location(
            "mf_bm25", str(facade_dir / "bm25_store.py"))
        bm25_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bm25_mod)
        # 加载 vector
        spec = importlib.util.spec_from_file_location(
            "mf_vector", str(facade_dir / "vector_store.py"))
        vector_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(vector_mod)
        # 加载 hybrid
        spec = importlib.util.spec_from_file_location(
            "mf_hybrid", str(facade_dir / "hybrid_search.py"))
        _hybrid_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_hybrid_mod)
        _hybrid_mod._store = store_mod
        _hybrid_mod._bm25 = bm25_mod
        _hybrid_mod._vector = vector_mod
        return _hybrid_mod
    except Exception:
        return None

WORKSPACE = Path.home() / ".openclaw" / "workspace"
PENDING_FILE = WORKSPACE / "memory" / "pending-extract.md"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


# ─────────────────────────────────────────────────────────────
# 记忆信号检测
# ─────────────────────────────────────────────────────────────

MEMORY_SIGNALS = {
    "preference": [
        r"我喜欢", r"我一般", r"通常我", r"偏好", r"prefer",
        r"我不喜欢", r"讨厌", r"hate",
        r"喜欢用", r"习惯用", r"一直用",
    ],
    "decision": [
        r"决定了", r"选定了", r"就这样", r"最终方案",
        r"我们决定", r"确定用", r"最终选择",
        r"拍板", r"定了",
    ],
    "lesson": [
        r"下次要注意", r"之前", r"这次", r"曾经",
        r"教训是", r"反思", r"错在",
        r"要注意", r"别再", r"不能再",
    ],
    "status_change": [
        r"完成了", r"结束了", r"完成了",
        r"失败了", r"放弃了", r"停止",
        r"上线了", r"发布了",
    ],
    "tool_change": [
        r"换成", r"改用", r"迁移到", r"切换到",
        r"换了", r"改成了",
    ],
    "context_update": [
        r"其实", r"准确说", r"更正", r"补充",
        r"更准确地说", r"严格来说",
    ],
}

TOPIC_MAP = {
    "preference": "Profile → 沟通偏好",
    "decision": "Decisions → 架构决策",
    "lesson": "Lessons → 技术教训",
    "status_change": "Projects → 项目状态",
    "tool_change": "Tech Stack → 工具选型",
    "context_update": "Profile → 上下文更新",
}


def detect_signal_type(text: str) -> list[str]:
    """检测文本中包含的记忆信号类型"""
    found = []
    for sig_type, patterns in MEMORY_SIGNALS.items():
        for pat in patterns:
            if re.search(pat, text):
                found.append(sig_type)
                break
    return found


def extract_memory_snippets(text: str, sig_types: list[str]) -> list[dict]:
    """从文本中提取记忆片段，按类型分组"""
    if not sig_types:
        # 没有匹配到显式信号，但文本长度适中，可能是隐式记忆
        if len(text) >= 20 and len(text) <= 500:
            return [{"type": "context_update", "topic": "Profile → 上下文更新", "content": text.strip()}]
        return []

    snippets = []
    for sig_type in sig_types:
        topic = TOPIC_MAP.get(sig_type, "未分类")
        # 简单截取：保留信号词前后各 100 字符
        for pat in MEMORY_SIGNALS.get(sig_type, []):
            m = re.search(pat, text)
            if m:
                start = max(0, m.start() - 50)
                end = min(len(text), m.end() + 100)
                snippet = text[start:end].strip()
                snippets.append({
                    "type": sig_type,
                    "topic": topic,
                    "content": snippet,
                })
                break
    return snippets


# ─────────────────────────────────────────────────────────────
# 写入 pending-extract.md
# ─────────────────────────────────────────────────────────────

def _ensure_pending():
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not PENDING_FILE.exists():
        PENDING_FILE.write_text("# 待归档内容\n\n", encoding="utf-8")


def _write_to_pending(snippets: list[dict]) -> int:
    """追加记忆片段到 pending 文件，返回写入条数"""
    if not snippets:
        return 0

    _ensure_pending()

    existing = PENDING_FILE.read_text(encoding="utf-8")

    lines = []
    for s in snippets:
        lines.append(f"\n### 主题：{s['topic']}")
        lines.append(f"**检测时间**：{_now()}")
        lines.append(f"**类型**：{s['type']}")
        lines.append(f"**内容**：")
        lines.append(f"{s['content']}")
        lines.append("")

    existing += "\n".join(lines)
    PENDING_FILE.write_text(existing, encoding="utf-8")
    return len(snippets)


# ─────────────────────────────────────────────────────────────
# Skill 操作路由
# ─────────────────────────────────────────────────────────────

def handle(action: str, params: dict) -> dict:
    if action == "capture":
        content = params.get("content", "")
        if not content:
            return {"silent": True, "captured": 0}

        sig_types = detect_signal_type(content)
        if not sig_types:
            return {"silent": True, "captured": 0}

        snippets = extract_memory_snippets(content, sig_types)
        n = _write_to_pending(snippets)

        # 同时触发 active inject：搜索相关记忆并写入 inject 文件
        inject_result = None
        try:
            inject_result = handle("inject", {"content": content})
        except Exception:
            pass  # inject 失败不影响 capture 主流程

        return {
            "silent": True,
            "captured": n,
            "snippets": snippets,
            "inject": inject_result,
        }

    elif action == "status":
        if not PENDING_FILE.exists():
            return {"reply": "✅ pending 文件为空", "count": 0}

        text = PENDING_FILE.read_text(encoding="utf-8")
        count = text.count("### 主题：")
        if count == 0:
            return {"reply": "✅ pending 文件为空", "count": 0}
        return {"reply": f"📋 待归档记忆：{count} 条", "count": count}

    elif action == "remind":
        if not PENDING_FILE.exists():
            return {"reply": None}  # 无内容，不提醒

        text = PENDING_FILE.read_text(encoding="utf-8")
        count = text.count("### 主题：")
        if count == 0:
            return {"reply": None}

        return {
            "reply": (
                f"🔔 发现 {count} 条待归档记忆。"
                f" 运行 `/memoryre` 归档，或继续对话。"
            ),
            "count": count,
        }

    elif action == "inject":
        """主动注入：检测相关记忆并写入 inject 文件"""
        content = params.get("content", "")
        if not content:
            return {"reply": "⚠️ inject 需要 content 参数"}

        hybrid = _get_hybrid()
        if not hybrid:
            return {"reply": "⚠️ hybrid search 未就绪"}

        # hybrid 搜索 top-3
        try:
            bm25_store = hybrid._bm25.MemoryBM25Store()
            vector_store = hybrid._vector.MemoryVectorStore() if hasattr(hybrid, '_vector') else None
        except Exception:
            return {"reply": "⚠️ store 初始化失败"}

        results = hybrid.hybrid_search(
            query=content,
            top_k=3,
            alpha=0.5,
            bm25_store=bm25_store,
            vector_store=vector_store,
        )

        if not results:
            return {"reply": "✅ 无相关记忆需要注入", "count": 0}

        # 写入 inject 文件
        INJECT_FILE = Path.home() / ".openclaw/workspace/ai_system/runtime/session_current/memory_inject.md"
        INJECT_FILE.parent.mkdir(parents=True, exist_ok=True)

        lines = [f"# 主动注入的记忆（{_now()}）"]
        for r in results:
            mem = hybrid._store.get_by_id(r['id'])
            if mem:
                lines.append(f"\n## [{mem['topic']}] {mem['content'][:100]}...")
                lines.append(f"id={mem['id']} | score={r.get('combined_score', r.get('score', 0)):.3f}")

        INJECT_FILE.write_text("\n".join(lines), encoding="utf-8")
        return {
            "reply": f"✅ 写入 {len(results)} 条相关记忆到注入文件",
            "count": len(results),
            "results": results,
        }

    else:
        return {"reply": f"未知操作：{action}，支持的：capture / status / remind / inject"}
