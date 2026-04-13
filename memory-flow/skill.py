"""Memory Flow — 记忆编排层 v2

合并了 memory-orchestrator 和 memory-re-operator 的职责。
唯一入口：/memoryre → archive → MEMORY.md + SQLite
"""

import re
import sys
from datetime import datetime
from pathlib import Path

# ── 依赖邻居模块 ────────────────────────────────────────────

def _load_store():
    """延迟加载 memory-facade store"""
    facade_dir = Path(__file__).parent.parent / "memory-facade"
    sys.path.insert(0, str(facade_dir))
    import store as _s
    return _s

# ── 路径常量 ────────────────────────────────────────────────

WORKSPACE = Path.home() / ".openclaw" / "workspace"
MEMORY_FILE = WORKSPACE / "MEMORY.md"
PENDING_FILE = WORKSPACE / "memory" / "pending-extract.md"
DAILY_DIR = WORKSPACE / "memory"
INJECT_DIR = WORKSPACE / "ai_system" / "runtime" / "session_current"


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _today():
    return datetime.now().strftime("%Y-%m-%d")


# ── 解析 pending-extract.md ────────────────────────────────

def _parse_pending(path: Path) -> list[dict]:
    """解析 pending 文件，返回 topic blocks"""
    if not path.exists():
        return []

    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return []

    # 按 ### 主题： 分隔
    raw_blocks = re.split(r"\n### 主题：", text)
    results = []

    for i, block in enumerate(raw_blocks):
        block = block.strip()
        if not block:
            continue

        if i == 0:
            # 第一个块：文件头
            time_match = re.search(r"## 提取时间[：:]\s*(.+)", block)
            results.append({
                "time": time_match.group(1).strip() if time_match else "",
                "raw": block,
                "topic": None,
                "content": None,
            })
        else:
            header_match = re.match(r"(.+?)\n([\s\S]+)", block, re.DOTALL)
            if header_match:
                topic_path = header_match.group(1).strip()
                content = header_match.group(2).strip()
                results.append({
                    "time": "",
                    "topic": topic_path,
                    "content": content,
                })

    return results


# ── 主题匹配 ────────────────────────────────────────────────

TOPIC_MAP = {
    "project":  "PROJECTS",
    "项目":     "PROJECTS",
    "decision": "DECISIONS",
    "决策":     "DECISIONS",
    "lesson":   "LESSONS",
    "教训":     "LESSONS",
    "principle": "LESSONS",
    "tech":     "TECHSTACK",
    "技术栈":   "TECHSTACK",
    "profile":  "PROFILE",
    "画像":     "PROFILE",
    "偏好":     "PROFILE",
}


def _match_section(topic_str: str) -> str:
    t = topic_str.lower()
    for key, section in TOPIC_MAP.items():
        if key in t:
            return section
    return "UNKNOWN"


# ── 冲突检测 ────────────────────────────────────────────────

def _detect_conflict(existing: str, new: str) -> bool:
    """检测新旧内容的矛盾状态对"""
    contradictions = [
        # 状态矛盾
        (r'进行中|活跃|active', r'完成|done|上线|结束|✅'),
        (r'失败|放弃|停止|🔴|未完成|未激活', r'完成|done|上线|结束|✅|进行中|活跃'),
        # 偏好矛盾
        (r'喜欢|prefer|一直用|偏好', r'讨厌|hate|不喜欢|废弃|换成|改用|不再用'),
        # 决策矛盾
        (r'确认|决定|确定', r'撤销|取消|废弃|不再'),
    ]
    for pos_pat, neg_pat in contradictions:
        pos_in_old = bool(re.search(pos_pat, existing))
        neg_in_old = bool(re.search(neg_pat, existing))
        pos_in_new = bool(re.search(pos_pat, new))
        neg_in_new = bool(re.search(neg_pat, new))
        if (pos_in_old and neg_in_new) or (neg_in_old and pos_in_new):
            return True
    return False


# ── 归并写入 MEMORY.md ────────────────────────────────────

SECTION_MARKERS = {
    "PROFILE":   "## 1. 个人画像 (Profile)",
    "TECHSTACK": "## 2. 技术栈 (Tech Stack)",
    "PROJECTS":  "## 3. 项目全景 (Projects)",
    "DECISIONS": "## 4. 关键决策 (Decisions)",
    "LESSONS":   "## 5. 教训与原则 (Lessons)",
}


def _merge_block(block: dict, memory_text: str) -> tuple[str, str, dict | None]:
    """归并单个 block 到 MEMORY.md，返回 (新文本, 状态, 冲突信息)"""
    topic = block.get("topic", "")
    content = block.get("content", "")
    if not topic or not content:
        return memory_text, "skip", None

    section = _match_section(topic)
    marker = SECTION_MARKERS.get(section, "## 更新日志")

    if marker not in memory_text:
        return memory_text, "skip", None

    idx = memory_text.index(marker)
    insert_pos = idx

    # 检测插入位置前 300 字符窗口，做冲突检测
    window = memory_text[max(0, insert_pos - 300):insert_pos]
    conflict = None
    if len(window) > 50 and _detect_conflict(window, content[:300]):
        conflict = {"topic": topic, "existing": window[-200:], "new": content[:200]}

    ts = block.get("time") or _now()
    entry_lines = [
        f"### {topic}  ",
        f"**归档时间**：{ts}  ",
        f"{content}",
        "",
    ]
    entry = "\n" + "\n".join(entry_lines) + "\n"

    new_text = memory_text[:insert_pos] + entry + "\n" + memory_text[insert_pos:]
    return new_text, "merged" if not conflict else "conflict", conflict


# ── SQLite 双写 ────────────────────────────────────────────

def _write_sqlite(entry: str, topic: str, section: str):
    """写入 SQLite（通过 memory-facade store）"""
    try:
        store = _load_store()
        # 确保数据库已初始化
        try:
            store.init_db()
        except Exception:
            pass
        # 截断 300 字符写入
        store.insert(
            content=entry.strip()[:300],
            topic=section.lower(),
            project_id="default",
        )
    except Exception:
        pass  # SQLite 失败不影响主流程


# ── 日报更新 ────────────────────────────────────────────────

def _update_daily(blocks: list[dict]):
    """生成/更新当日日报"""
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    daily_path = DAILY_DIR / f"daily_report_{_today()}.md"

    lines = [f"# 日报 {_today()}\n", f"**归档时间**：{_now()}\n", "\n## 归档内容\n"]

    for b in blocks:
        t = b.get("topic", "未分类")[:50]
        c = b.get("content", "")[:100]
        lines.append(f"### {t}\n{c}...\n")

    text = "".join(lines)
    if daily_path.exists():
        existing = daily_path.read_text(encoding="utf-8")
        text = existing + "\n" + text

    daily_path.write_text(text, encoding="utf-8")
    return str(daily_path)


# ── 主归档流程 ─────────────────────────────────────────────

def _do_archive(blocks: list[dict], dry_run: bool = False) -> dict:
    """执行归档，返回结果"""
    if not blocks:
        return {"merged": [], "conflicts": [], "skipped": [], "reply": "✅ pending 为空，无归档"}

    if not MEMORY_FILE.exists():
        return {"merged": [], "conflicts": [], "errors": ["MEMORY.md 不存在"]}

    memory_text = MEMORY_FILE.read_text(encoding="utf-8")
    merged, conflicts, skipped = [], [], []

    for block in blocks:
        topic = block.get("topic")
        if not topic:
            skipped.append("(无主题块)")
            continue

        section = _match_section(topic)
        marker = SECTION_MARKERS.get(section, "## 更新日志")
        if marker not in memory_text:
            skipped.append(f"{topic}（章节不存在）")
            continue

        new_text, status, conflict = _merge_block(block, memory_text)

        if status == "merged":
            memory_text = new_text
            merged.append(topic)
            entry_start = new_text.index(f"### {topic}")
            entry_end = new_text.index("\n\n", entry_start) + 2
            entry = new_text[entry_start:entry_end]
            _write_sqlite(entry, topic, section)

        elif status == "conflict":
            conflicts.append({**conflict, "topic": topic})

        else:
            skipped.append(topic)

    if not dry_run:
        MEMORY_FILE.write_text(memory_text, encoding="utf-8")
        _update_daily(blocks)

    return {"merged": merged, "conflicts": conflicts, "skipped": skipped}


# ── 路由 ────────────────────────────────────────────────────

def handle(action: str, params: dict) -> dict:
    blocks = _parse_pending(PENDING_FILE)

    if action == "archive":
        if not blocks:
            return {"reply": "✅ pending 为空，无需归档", "merged": 0}

        result = _do_archive(blocks, dry_run=False)
        _clear_pending()

        lines = [f"✅ 归档完成  |  {_now()}\n"]
        lines.append(f"**归并**：{len(result['merged'])} 条")
        for m in result["merged"]:
            lines.append(f"  ✅ {m}")

        if result.get("skipped"):
            lines.append(f"**跳过**：{len(result['skipped'])} 条（章节不匹配）")
            for s in result["skipped"][:3]:
                lines.append(f"  ⊙ {s}")

        if result.get("conflicts"):
            lines.append(f"\n⚠️ **冲突**（需人工确认）：{len(result['conflicts'])} 条")
            for c in result["conflicts"]:
                lines.append(f"  ⚠️ {c['topic']}")

        return {"reply": "\n".join(lines), **result}

    elif action == "preview":
        # 不写入，只展示归并计划
        if not blocks:
            return {"reply": "✅ pending 为空", "merged": 0}

        result = _do_archive(blocks, dry_run=True)
        lines = [f"📋 归并预览（共 {len(blocks)} 个主题块）\n"]
        lines.append(f"**将归并**：{len(result['merged'])} 条")
        for m in result["merged"]:
            lines.append(f"  ✅ {m}")
        if result.get("skipped"):
            lines.append(f"**将跳过**：{len(result['skipped'])} 条")
        if result.get("conflicts"):
            lines.append(f"\n⚠️ **冲突**：{len(result['conflicts'])} 条")
            for c in result["conflicts"]:
                lines.append(f"  ⚠️ {c['topic']}")

        lines.append("\n_预览模式，未写入。如需执行请说 `执行归档`。_")
        return {"reply": "\n".join(lines), **result}

    elif action == "status":
        if not PENDING_FILE.exists():
            return {"reply": "✅ pending 为空", "pending_count": 0}

        text = PENDING_FILE.read_text(encoding="utf-8")
        count = text.count("### 主题：")
        if count == 0:
            return {"reply": "✅ pending 为空", "pending_count": 0}

        # SQLite 统计
        sqlite_count = 0
        try:
            store = _load_store()
            try:
                store.init_db()
            except Exception:
                pass
            all_mem = store.search(include_tombstoned=False)
            sqlite_count = len(all_mem)
        except Exception:
            pass

        return {
            "reply": f"📋 待归档：{count} 条 | SQLite：{sqlite_count} 条",
            "pending_count": count,
            "sqlite_count": sqlite_count,
        }

    else:
        return {"reply": f"未知操作：{action}，支持：archive / preview / status"}


def _clear_pending():
    if PENDING_FILE.exists():
        PENDING_FILE.write_text("# 待归档内容\n\n", encoding="utf-8")
