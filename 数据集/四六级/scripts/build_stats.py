# -*- coding: utf-8 -*-
"""P7 统计与质检：listening_ref 补全 + stats.json。
用法: python build_stats.py --kb <知识库根目录>
"""
import argparse, json, sys
from pathlib import Path
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
ap = argparse.ArgumentParser()
ap.add_argument("--kb", required=True)
A = ap.parse_args()
KB = Path(A.kb).resolve()
if "knowledge_map" not in KB.parts:
    raise ValueError(f"path outside allowed root: {KB}")

def load(path):
    p = KB / path
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]

def count(path):
    return len(load(path))

# listening_ref 补全（PDF 管线产出的 p3 卷）
papers = load("manifest/papers.jsonl")
by_session = {}
for p in papers:
    by_session.setdefault((p["exam"], p["year"]), []).append(p)
# papers 计数按实际文件重算（清单计数早于去重/修复）
qfile_counts = {}
for lv0 in ("cet4", "cet6"):
    for f0 in (KB / "questions" / lv0).glob("*.jsonl"):
        qfile_counts[f"{lv0}.{f0.stem}"] = len([x for x in f0.read_text(encoding="utf-8").splitlines() if x.strip()])
for pp in papers:
    n0 = qfile_counts.get(pp["id"])
    if n0 is not None:
        cur = pp.get("listening_qs", 0) + pp.get("reading_qs", 0)
        if cur != n0:
            delta = n0 - cur
            if pp.get("listening_qs", 0) > 0:
                pp["reading_qs"] = max(0, pp.get("reading_qs", 0) + delta)
            else:
                pp["listening_qs"] = max(0, pp.get("listening_qs", 0) + delta)
# 节选卷 / 缺听力卷 → ref 指向同场次最完整的卷
for (exam, ym), ps in by_session.items():
    full = max(ps, key=lambda x: x.get("listening_qs", 0) + x.get("reading_qs", 0))
    for p in ps:
        if p is full:
            continue
        if p.get("listening_qs", 0) < 25 and not p.get("listening_ref") and full.get("listening_qs", 0) >= 25:
            p["listening_ref"] = full["id"]
        if p.get("reading_qs", 0) < 30 and not p.get("reading_ref") and full.get("reading_qs", 0) >= 30:
            p["reading_ref"] = full["id"]
for (exam, ym), ps in by_session.items():
    src = next((x for x in ps if x.get("listening_qs") == 25), None)
    if src:
        for p in ps:
            if p.get("listening_qs") == 0 and not p.get("listening_ref"):
                p["listening_ref"] = src["id"]
                p.setdefault("warnings", []).append(f"listening shared from {src['id']}")
(KB / "manifest" / "papers.jsonl").write_text(
    "\n".join(json.dumps(x, ensure_ascii=False) for x in papers) + "\n", encoding="utf-8")

# 题目统计
q_total = q_ans = 0
by_level = {}
for lv in ("cet4", "cet6"):
    recs = []
    qd = KB / "questions" / lv
    for f in sorted(qd.glob("*.jsonl")):
        for l in f.read_text(encoding="utf-8").splitlines():
            if l.strip():
                recs.append(json.loads(l))
    # 去重：同 id 保留信息最全的一条（有题干和选项者优先）
    def quality(r):
        return (bool(r.get("stem")), len(r.get("options") or {}), bool(r.get("answer")))
    best = {}
    for r in recs:
        k = r["id"]
        if k not in best or quality(r) > quality(best[k]):
            best[k] = r
    # 质量标记：客观题选项数异常 → needs_fix（保留数据，可过滤）
    n_needs_fix = 0
    for r in best.values():
        if r.get("question_type") in ("选词填空", "长篇阅读"):
            continue
        if len(r.get("options") or {}) not in (0, 4):
            r["review"] = {"status": "needs_fix"}
            n_needs_fix += 1
    # 按文件写回去重结果（写本文件自己的首条记录，避免跨文件重复）
    for f in sorted(qd.glob("*.jsonl")):
        rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
        seen, out = set(), []
        for r in rows:
            k = r["id"]
            if k in seen:
                continue
            seen.add(k)
            out.append(best.get(k, r))
        f.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in out) + "\n", encoding="utf-8")
    recs = list(best.values())
    ids = [r["id"] for r in recs]
    dup = len(ids) - len(set(ids))
    by_level[lv] = {
        "records": len(recs),
        "with_answer": sum(1 for r in recs if r.get("answer")),
        "duplicate_ids": dup,
        "by_type": dict(Counter(r["question_type"] for r in recs)),
        "by_module": dict(Counter(r["module"] for r in recs)),
    }
    q_total += len(recs)
    q_ans += sum(1 for r in recs if r.get("answer"))

full_papers = sum(1 for p in papers if p.get("listening_qs") == 25 and p.get("reading_qs") == 30)
no_listen = [p["id"] for p in papers if p.get("listening_qs", 0) < 25 and not p.get("listening_ref")]
scan_sessions = sorted({p["year"] for p in papers}) and ["2026-06"]

stats = {
    "generated": "2026-10-02",
    "source": "英语四六级资料合集（2026年最新）(1)",
    "vocabulary": {
        "words_cet4": count("vocabulary/words_cet4.jsonl"),
        "words_cet6": count("vocabulary/words_cet6.jsonl"),
        "core_words": count("vocabulary/core_words.jsonl"),
        "phrases_highfreq": count("vocabulary/phrases_highfreq.jsonl"),
        "translation_topic_words": count("vocabulary/translation_topic_words.jsonl"),
    },
    "questions": {
        "total": q_total,
        "with_answer": q_ans,
        "answer_fill_rate": round(q_ans / q_total, 3) if q_total else 0,
        "papers_total": len(papers),
        "papers_full_25L_30R": full_papers,
        "papers_missing_listening_without_ref": len(no_listen),
        "detail": by_level,
    },
    "passages": {
        "reading": count("passages/reading.jsonl"),
        "listening_transcripts": count("passages/listening_transcripts.jsonl"),
    },
    "writing": {
        "model_essays": count("writing/model_essays.jsonl"),
        "with_model_essay": sum(1 for x in load("writing/model_essays.jsonl") if x.get("model_essay")),
        "templates": count("writing/templates.jsonl"),
    },
    "translation": {
        "items": count("translation/items.jsonl"),
        "with_reference": sum(1 for x in load("translation/items.jsonl") if x.get("reference")),
    },
    "ontology": {"knowledge_nodes": count("ontology/knowledge_nodes.jsonl")},
    "not_ingested": {
        "listening_audio": "120 个 MP3 仅在 manifest/ingest_log.md 登记路径，不入向量库",
        "listening_transcripts": "四级/六级《听力原文合集》PDF 均为扫描件（无文本层），待 OCR 补录",
        "sessions_2026_06": "2026年6月真题册/解析册为扫描件，仅登记原件路径，待 OCR",
        "answer_books_corrupt_font": "2016.06-2017.06 部分解析册 PDF 字体映射损坏（文本为乱码），答案待 OCR/人工补录",
    },
    "answer_fill_report": "manifest/answers_fill_report.json",
    "parse_report": "manifest/parse_report.json",
}
(KB / "manifest" / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps({k: v for k, v in stats.items() if k in ("vocabulary", "questions", "passages", "writing", "translation")}, ensure_ascii=False, indent=1))
