"""Memory Watch — 记忆守护与健康监控（合并版）

- Guardian 回路②：操作前冲突检测
- Health 回路③：定期健康扫描

原 memory-guardian + memory-health，现已合并到本 skill。
"""

# 直接内联两个模块的逻辑，避免跨目录 import 的复杂性

import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path

WORKSPACE = Path.home() / ".openclaw" / "workspace"
MEMORY_FILE = WORKSPACE / "MEMORY.md"
GUARDIAN_LOG = WORKSPACE / "memory" / "guardian-log.json"


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _today():
    return datetime.now().strftime("%Y-%m-%d")


# ══════════════════════════════════════════════════════════════
# PART 1: GUARDIAN（回路②）
# ══════════════════════════════════════════════════════════════

def _extract_keywords(operation: str) -> list[str]:
    files = re.findall(r"[\w\-\.]+\.(yaml|yml|json|md|py|sh|conf|cfg|toml)", operation)
    projects = re.findall(r"(?:blueprints|skills)/([\w\-]+)", operation)
    sensitive = ["SOUL", "MEMORY", "USER", "IDENTITY", "AGENTS", "TOOLS",
                 "config", "api_key", "credential", "secret", "password"]
    found = [w for w in sensitive if w.lower() in operation.lower()]
    return list(set(files + projects + found))


def _search_memory(keywords: list[str]) -> list[dict]:
    if not MEMORY_FILE.exists() or not keywords:
        return []
    text = MEMORY_FILE.read_text(encoding="utf-8")
    results = []
    for kw in keywords:
        pattern = re.compile(r"(.{0,100}" + re.escape(kw) + r".{0,100})", re.IGNORECASE)
        for m in pattern.finditer(text):
            section_match = re.search(r"(## [^#\n]+)$", text[:m.start()])
            section = section_match.group(1).strip() if section_match else "未知章节"
            results.append({"keyword": kw, "context": m.group(0).strip(), "section": section})
    return results


def _detect_guardian_conflicts(entries: list[dict]) -> list[dict]:
    if len(entries) < 2:
        return []
    by_section = {}
    for e in entries:
        sec = e.get("section", "未知")
        by_section.setdefault(sec, []).append(e)
    conflicts = []
    positive = ["必须", "重要", "不要删", "不能删", "保留", "备份", "一直用", "喜欢", "偏好"]
    negative = ["废弃", "已放弃", "停止使用", "换成", "改用", "不再用"]
    for sec, items in by_section.items():
        if len(items) < 2:
            continue
        pos_hits = [it for it in items if any(p in it["context"] for p in positive)]
        neg_hits = [it for it in items if any(n in it["context"] for n in negative)]
        if pos_hits and neg_hits:
            conflicts.append({"section": sec, "positive": pos_hits, "negative": neg_hits})
    return conflicts


PENDING_OPS_FILE = WORKSPACE / "memory" / "guardian-pending-ops.json"

PENDING_OPS = {}  # in-memory cache


def _load_pending_ops():
    """从文件恢复 pending ops（跨进程持久化）"""
    global PENDING_OPS
    if PENDING_OPS_FILE.exists():
        try:
            import json
            PENDING_OPS = json.loads(PENDING_OPS_FILE.read_text(encoding="utf-8"))
        except Exception:
            PENDING_OPS = {}


def _save_pending_ops():
    """持久化 pending ops 到文件"""
    try:
        import json
        PENDING_OPS_FILE.parent.mkdir(parents=True, exist_ok=True)
        PENDING_OPS_FILE.write_text(json.dumps(PENDING_OPS, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _save_guardian_log(op_id: str, entry: dict):
    import json
    GUARDIAN_LOG.parent.mkdir(parents=True, exist_ok=True)
    logs = []
    if GUARDIAN_LOG.exists():
        try:
            logs = json.loads(GUARDIAN_LOG.read_text(encoding="utf-8"))
        except Exception:
            logs = []
    entry["op_id"] = op_id
    entry["timestamp"] = _now()
    logs.append(entry)
    GUARDIAN_LOG.write_text(json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8")


# ══════════════════════════════════════════════════════════════
# PART 2: HEALTH（回路③）
# ══════════════════════════════════════════════════════════════

def _parse_memory() -> dict:
    if not MEMORY_FILE.exists():
        return {"sections": [], "entries": []}
    text = MEMORY_FILE.read_text(encoding="utf-8")
    parts = re.split(r"(?=^##\s+)", text, flags=re.MULTILINE)
    sections = []
    for part in parts:
        if not part.strip():
            continue
        title_match = re.match(r"^## (.+)", part.strip())
        if not title_match:
            continue
        title = title_match.group(1).strip()
        subsections = re.split(r"(?=^###\s+)", part, flags=re.MULTILINE)
        entries = []
        for sub in subsections:
            if not sub.strip() or sub == part.strip():
                continue
            sub_title_match = re.match(r"^###\s+(.+)", sub.strip())
            if sub_title_match:
                sub_title = sub_title_match.group(1).strip()
                ts_match = re.search(r"(\d{4}-\d{2}-\d{2})", sub)
                updated = ts_match.group(1) if ts_match else None
                entries.append({
                    "title": sub_title,
                    "section": title,
                    "updated": updated,
                    "content": sub.strip()[:300],
                })
        sections.append({"title": title, "entries": entries})
    return {"sections": sections, "raw": text}


def _detect_stale(entries: list[dict], days: int = 60) -> list[dict]:
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return [e for e in entries if e.get("updated") and e["updated"] < cutoff]


def _detect_orphaned(entries: list[dict]) -> list[dict]:
    """
    检测孤立条目：条目标题在 MEMORY.md 中只出现一次（仅作为自身标题），
    说明没有被正文引用，可能是废弃或遗漏的内容。

    跳过以下合法结构条目：
    - 带 " → " 链接符的条目（如 "Profile → 沟通偏好"）
      这类条目是嵌入在父章节中的元组，本身就由父章节索引，不依赖额外引用
    - 日期格式开头的条目（如 "2026-04-01 - ..."）
      这类条目是时间线/日志条目，不与正文交叉引用是正常现象
    """
    if not entries or not MEMORY_FILE.exists():
        return []
    text = MEMORY_FILE.read_text(encoding="utf-8")
    orphaned = []
    for e in entries:
        title = e.get("title", "")
        if not title:
            continue
        # 跳过带 → 的条目（subsection 内的嵌入元组）
        if " → " in title:
            continue
        # 跳过日期格式条目（时间线/日志条目）
        if re.match(r"^\d{4}-\d{2}-\d{2}", title):
            continue
        plain = re.sub(r"^[#]+\s+", "", title).strip()
        if re.match(r"^\d+\.\d+", plain) or len(plain) < 5:
            continue
        if text.count(plain) <= 1:
            orphaned.append(e)
    return orphaned


def _detect_health_conflicts(entries: list[dict]) -> list[dict]:
    by_section = {}
    for e in entries:
        by_section.setdefault(e.get("section", "未知"), []).append(e)
    conflicts = []
    positive = ["必须", "重要", "不要删", "不能删", "保留", "备份", "一直用", "喜欢", "偏好", "确认", "决定"]
    negative = ["废弃", "已放弃", "停止使用", "换成", "改用", "不再用", "撤销", "取消"]
    for sec, items in by_section.items():
        if len(items) < 2:
            continue
        clean = lambda t: re.sub(r"`[^`]+`", "", t)
        pos_hits = [it for it in items if any(p in clean(it.get("content", "")) for p in positive)]
        neg_hits = [it for it in items if any(n in clean(it.get("content", "")) for n in negative)]
        pos_ids = {id(p) for p in pos_hits}
        neg_filtered = [n for n in neg_hits if id(n) not in pos_ids]
        if pos_hits and neg_filtered:
            conflicts.append({"section": sec, "positive": pos_hits, "negative": neg_filtered})
    return conflicts


def _generate_health_report(stale, orphaned, conflicts) -> str:
    total = len(stale) + len(orphaned) + len(conflicts)
    lines = [f"# 记忆健康报告 — {_today()}", f"**生成时间**：{_now()}", "", "## 📊 总体评分", "",
             "| 维度 | 结果 |", "|------|------|",
             f"| 孤立条目 | {len(orphaned)} |", f"| 过时条目 | {len(stale)} |",
             f"| 冲突条目 | {len(conflicts)} |", ""]
    if orphaned:
        lines.append("## ⚠️ 孤立条目")
        for o in orphaned[:10]:
            lines.append(f"- **{o['section']}** → {o['title']}")
        lines.append("")
    if stale:
        lines.append("## 📅 过时条目（>60天）")
        for s in stale[:10]:
            lines.append(f"- **{s['section']}** → {s['title']}（{s.get('updated','?')}）")
        lines.append("")
    if conflicts:
        lines.append("## ❌ 冲突条目")
        for c in conflicts[:5]:
            lines.append(f"**{c['section']}**：")
            for p in c["positive"][:2]:
                lines.append(f"  ✅ {p['title']}")
            for n in c["negative"][:2]:
                lines.append(f"  ❌ {n['title']}")
        lines.append("")
    elif total == 0:
        lines = [f"# 记忆健康报告 — {_today()}", f"**{_now()}**", "", "✅ MEMORY.md 健康，无异常。", ""]
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# 路由
# ══════════════════════════════════════════════════════════════

def handle(action: str, params: dict) -> dict:
    # ── GUARDIAN ────────────────────────────────────────────
    if action == "check" and "operation" in params:
        # Guardian 模式：操作前检查
        operation = params.get("operation", "")
        topic = params.get("topic", "")
        keywords = _extract_keywords(operation)
        if topic:
            keywords.append(topic)
        entries = _search_memory(keywords)
        conflicts = _detect_guardian_conflicts(entries)
        op_id = str(uuid.uuid4())[:8]

        if conflicts:
            PENDING_OPS[op_id] = {"operation": operation, "conflicts": conflicts}
            _save_pending_ops()
            conflict_lines = []
            for i, c in enumerate(conflicts):
                conflict_lines.append(f"\n**冲突 {i+1}**（{c['section']}）：")
                conflict_lines.append(f"  ✅ 正面：{c['positive'][0]['context'][:80]}")
                conflict_lines.append(f"  ❌ 负面：{c['negative'][0]['context'][:80]}")
            reply = (
                f"⚠️ 检测到 {len(conflicts)} 个记忆冲突，操作已暂停。\n\n"
                f"**操作**：`{operation}`\n" + "\n".join(conflict_lines)
                + f"\n\n**操作ID**：`{op_id}`\n"
                f"说 `watch confirm {op_id}` 继续，或 `watch deny {op_id}` 取消。"
            )
            return {"reply": reply, "proceed": False, "conflicts": conflicts, "op_id": op_id}
        return {"reply": "✅ 无冲突，操作可以继续。", "proceed": True, "entries": entries}

    if action == "confirm":
        _load_pending_ops()
        op_id = params.get("operation_id", "")
        if op_id not in PENDING_OPS:
            return {"reply": f"❌ 操作ID不存在或已过期：{op_id}"}
        op = PENDING_OPS[op_id]
        _save_guardian_log(op_id, {"action": "confirmed", "operation": op["operation"]})
        return {"reply": f"✅ 已确认，继续执行：`{op['operation']}`。", "confirmed": True}

    if action == "deny":
        _load_pending_ops()
        op_id = params.get("operation_id", "")
        if op_id not in PENDING_OPS:
            return {"reply": f"❌ 操作ID不存在或已过期：{op_id}"}
        op = PENDING_OPS[op_id]
        _save_guardian_log(op_id, {"action": "denied", "operation": op["operation"]})
        return {"reply": f"❌ 已取消操作：`{op['operation']}`。", "denied": True}

    # ── HEALTH ─────────────────────────────────────────────
    if action == "check":
        # Health 模式：健康扫描
        days = params.get("days", 60)
        data = _parse_memory()
        all_entries = [e for sec in data.get("sections", []) for e in sec.get("entries", [])]
        stale = _detect_stale(all_entries, days)
        orphaned = _detect_orphaned(all_entries)
        conflicts = _detect_health_conflicts(all_entries)
        report = _generate_health_report(stale, orphaned, conflicts)
        return {
            "reply": report,
            "stale_count": len(stale),
            "orphaned_count": len(orphaned),
            "conflict_count": len(conflicts),
        }

    if action == "report":
        days = params.get("days", 60)
        data = _parse_memory()
        all_entries = [e for sec in data.get("sections", []) for e in sec.get("entries", [])]
        stale = _detect_stale(all_entries, days)
        orphaned = _detect_orphaned(all_entries)
        conflicts = _detect_health_conflicts(all_entries)
        total = len(stale) + len(orphaned) + len(conflicts)
        if total == 0:
            reply = "✅ 记忆健康，无异常。"
        else:
            parts = []
            if orphaned: parts.append(f"⚠️ 孤立 {len(orphaned)}")
            if stale: parts.append(f"📅 过时 {len(stale)}")
            if conflicts: parts.append(f"❌ 冲突 {len(conflicts)}")
            reply = "记忆体检：" + "，".join(parts) + "。详情用 `watch check`。"
        return {"reply": reply, "stale_count": len(stale), "orphaned_count": len(orphaned), "conflict_count": len(conflicts)}

    return {"reply": f"未知操作：{action}，支持：check(含operation=时为Guardian) / confirm / deny / report"}
