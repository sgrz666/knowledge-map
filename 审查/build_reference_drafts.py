"""将已编写、有官方理论定位的参考草稿连接完整原题；不修改主题库。"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "补充资料/教资参考解答"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build():
    seed_path = OUT / "reference_seeds.json"
    seeds = json.loads(seed_path.read_text(encoding="utf-8"))
    source_index = json.loads((ROOT / "补充资料/教资官方样题/supplementary_sources.json").read_text(encoding="utf-8"))
    source = next(s for s in source_index["sources"] if s["source_id"] == seeds["source_id"])
    text_path = ROOT / source["text_path"]
    assert sha256(text_path) == source["text_sha256"], "理论原文已变化，请重新核对定位"
    # Word原文含垂直制表和Unicode分隔符，来源定位统一按LF物理行。
    lines = text_path.read_text(encoding="utf-8-sig").split("\n")
    assert seeds.get("line_convention") == "physical_LF", "先转换并核对引用行号"
    rows = []
    for path in sorted((ROOT / "数据集/教资/questions/youer/baojiao").glob("*.jsonl")):
        rows.extend(json.loads(line) for line in path.open(encoding="utf-8-sig") if line.strip())
    records = []
    for seed in seeds["drafts"]:
        for start, end in seed["lines"]:
            assert 1 <= start <= end <= len(lines), (seed["draft_id"], start, end)
        for question in rows:
            if question["content"]["stem"] not in seed["stems"]:
                continue
            if question.get("review", {}).get("cross_question_risk"):
                continue
            if question.get("source", {}).get("raw_file_verification", {}).get("content_alignment") != "stem_excerpt_found":
                continue
            stem = question["content"]["stem"]
            generation = {"provider": "Codex", "model_id": None, "model_id_status": "not_exposed_in_session",
                          "created_at": datetime.now(timezone.utc).isoformat(), "seed_sha256": sha256(seed_path),
                          "input_complete": True}
            evidence = [{"source_id": source["source_id"], "path": source["text_path"], "role": "reference_theory",
                         "sha256": source["text_sha256"], "source_url": source["source_url"],
                         "locator": {"line_start": start, "line_end": end, "line_convention": "physical_LF",
                                     "context_sha256": hashlib.sha256("\n".join(lines[start - 1:end]).encode("utf-8")).hexdigest()}} for start, end in seed["lines"]]
            records.append({"draft_id": seed["draft_id"], "question_id": question["question_id"],
                            "expected_stem_sha256": hashlib.sha256(stem.encode("utf-8")).hexdigest(),
                            "original_stem": stem, "status": "original_reference_draft_pending_expert",
                            "official_exam_answer": False, "answer": seed["answer"], "scoring_points": seed["points"],
                            "score_note": "知识要点用于练习反馈，未取得正式逐点评分分值，不按点数自动换算考试分数。",
                            "source_files": evidence,
                            "analysis": {"method": "ai", "key_info": seed["key_info"],
                                         "option_compare": seed["common_error"],
                                         "trace_back": "依据教育部《3-6岁儿童学习与发展指南》的所列行号归纳，并针对题目编写教育措施与实例；理论支持不等于官方公布该题答案。",
                                         "explanation": seed["answer"], "generation": generation,
                                         "input_evidence_files": evidence, "expert_verified": False,
                                         "status": "original_reference_draft_pending_expert"}})
    with (OUT / "reference_drafts.jsonl").open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    summary = {"source": source["source_id"], "original_draft_topics": len(seeds["drafts"]),
               "matched_question_records": len(records), "official_exam_answers": 0,
               "status": "draft_pending_expert", "source_hash_verified": True}
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    build()
