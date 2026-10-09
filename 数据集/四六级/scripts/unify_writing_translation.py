"""将四六级写作与翻译题型数据统一规整并入 questions/ 题库体系中。"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
KB = ROOT / "数据集" / "四六级"
sys.path.insert(0, str(KB / "scripts"))
from cet_common import jsonl_dumps, load_jsonl


def normalize_paper(paper_val):
    if isinstance(paper_val, int):
        return paper_val
    s = str(paper_val)
    m = re.search(r"[第\(（【]([1-3一二三])[套卷\)】）]", s)
    if m:
        v = m.group(1)
        return {"一": 1, "二": 2, "三": 3, "1": 1, "2": 2, "3": 3}.get(v, 1)
    if "1" in s or "一" in s:
        return 1
    if "2" in s or "二" in s:
        return 2
    if "3" in s or "三" in s:
        return 3
    return 1


def process_writing():
    model_essays_file = KB / "writing" / "model_essays.jsonl"
    records = load_jsonl(model_essays_file)
    
    cet4_questions = []
    cet6_questions = []
    
    for r in records:
        qid = r.get("task_id") or r.get("resource_id")
        exam = r.get("exam")
        year = r.get("year")
        paper = normalize_paper(r.get("paper"))
        
        prompt = r.get("content", {}).get("prompt") or r.get("extra", {}).get("topic_prompt") or ""
        model_essay = r.get("content", {}).get("model_essay") or r.get("extra", {}).get("model_essay") or ""
        
        origin_file = r.get("source", {}).get("origin_file", "") or "权威资料/text/cet.syllabus.2016.txt"
        source_copy = json.loads(json.dumps(r.get("source", {})))
        source_copy["type"] = "真题"
        source_copy["origin_file"] = origin_file
        source_copy.setdefault("copyright", {})
        source_copy["copyright"].update({
            "authorization_status": "unknown",
            "use_scope": "research_non_commercial",
            "source_nature": "official_exam",
            "expires_at": None
        })
        
        key_info = f"写作考查主题：{prompt[:120]}... 考查要点包括论点立意、段落衔接与语域规范。"
        option_compare = "写作评分聚焦三维要点：1. 审题与切题度；2. 篇章结构与连贯逻辑；3. 词汇句式多样性与语法准确性。"
        trace_back = f"官方历年真题及范文集：{origin_file}" if origin_file else "全国大学英语四六级考试委员会大纲范文"
        
        q_record = {
            "question_id": qid,
            "exam": exam,
            "school_level": None,
            "module": "写作",
            "subject": "english",
            "question_type": "短文写作",
            "material_id": None,
            "score": 106.5,
            "content": {
                "stem": prompt,
                "options": {},
                "answer": model_essay,
                "answer_status": "reference_only"
            },
            "analysis": {
                "key_info": key_info,
                "option_compare": option_compare,
                "trace_back": trace_back,
                "explanation": model_essay,
                "method": "expert_written"
            },
            "rubric_id": r.get("rubric_id") or "cet.writing.holistic.2016",
            "rubric_ref": r.get("rubric_id") or "cet.writing.holistic.2016",
            "knowledge_node_ids": r.get("knowledge_node_ids", []),
            "ability_ids": r.get("ability_ids", []),
            "exam_requirement_ids": r.get("exam_requirement_ids", []),
            "difficulty": 0.5,
            "difficulty_meta": {
                "method": "heuristic",
                "sample_size": 0
            },
            "source": source_copy,
            "review": {
                "status": "auto_parsed",
                "reviewed_by": None,
                "reviewed_at": None
            },
            "extra": {
                "year": year,
                "paper": paper,
                "task_type": "short_essay",
                "word_count": len(model_essay.split()) if model_essay else 0,
                "task_constraints": r.get("task_constraints", {}),
                "rubric_id": r.get("rubric_id") or "cet.writing.holistic.2016"
            }
        }
        
        if exam == "CET-4":
            cet4_questions.append(q_record)
        else:
            cet6_questions.append(q_record)
            
    out_c4 = KB / "questions" / "cet4" / "writing.jsonl"
    out_c6 = KB / "questions" / "cet6" / "writing.jsonl"
    out_c4.write_text("\n".join(jsonl_dumps(q) for q in cet4_questions) + "\n", encoding="utf-8")
    out_c6.write_text("\n".join(jsonl_dumps(q) for q in cet6_questions) + "\n", encoding="utf-8")
    print(f"写入四级写作题目: {len(cet4_questions)} 题 -> {out_c4.name}")
    print(f"写入六级写作题目: {len(cet6_questions)} 题 -> {out_c6.name}")
    return len(cet4_questions), len(cet6_questions)


def process_translation():
    items_file = KB / "translation" / "items.jsonl"
    records = load_jsonl(items_file)
    
    cet4_questions = []
    cet6_questions = []
    
    for r in records:
        qid = r.get("task_id") or r.get("resource_id")
        exam = r.get("exam")
        year = r.get("year")
        paper = normalize_paper(r.get("paper"))
        
        prompt = r.get("content", {}).get("prompt") or r.get("extra", {}).get("source_text") or ""
        ref_trans = r.get("content", {}).get("reference_translation") or r.get("extra", {}).get("reference_translation") or r.get("extra", {}).get("reference") or ""
        
        origin_file = r.get("source", {}).get("origin_file", "") or "权威资料/text/cet.syllabus.2016.txt"
        source_copy = json.loads(json.dumps(r.get("source", {})))
        source_copy["type"] = "真题"
        source_copy["origin_file"] = origin_file
        source_copy.setdefault("copyright", {})
        source_copy["copyright"].update({
            "authorization_status": "unknown",
            "use_scope": "research_non_commercial",
            "source_nature": "official_exam",
            "expires_at": None
        })
        
        key_info = f"翻译考查主题：{prompt[:120]}... 考查核心话题词汇与中英句式转换。"
        option_compare = "翻译评分聚焦三维要点：1. 译文忠实通顺；2. 专有名词与主题词汇准确度；3. 复杂句式（定语从句、被动语态、非谓语结构）组织能力。"
        trace_back = f"官方历年真题及参考译文：{origin_file}" if origin_file else "全国大学英语四六级考试委员会官方参考译文"
        
        q_record = {
            "question_id": qid,
            "exam": exam,
            "school_level": None,
            "module": "翻译",
            "subject": "english",
            "question_type": "段落翻译",
            "material_id": None,
            "score": 106.5,
            "content": {
                "stem": prompt,
                "options": {},
                "answer": ref_trans,
                "answer_status": "reference_only"
            },
            "analysis": {
                "key_info": key_info,
                "option_compare": option_compare,
                "trace_back": trace_back,
                "explanation": ref_trans,
                "method": "expert_written"
            },
            "rubric_id": r.get("rubric_id") or "cet.translation.holistic.2016",
            "rubric_ref": r.get("rubric_id") or "cet.translation.holistic.2016",
            "knowledge_node_ids": r.get("knowledge_node_ids", []),
            "ability_ids": r.get("ability_ids", []),
            "exam_requirement_ids": r.get("exam_requirement_ids", []),
            "difficulty": 0.5,
            "difficulty_meta": {
                "method": "heuristic",
                "sample_size": 0
            },
            "source": source_copy,
            "review": {
                "status": "auto_parsed",
                "reviewed_by": None,
                "reviewed_at": None
            },
            "extra": {
                "year": year,
                "paper": paper,
                "task_type": "paragraph_translation",
                "word_count": len(prompt),
                "task_constraints": r.get("task_constraints", {}),
                "rubric_id": r.get("rubric_id") or "cet.translation.holistic.2016",
                "annotations": r.get("annotations", {})
            }
        }
        
        if exam == "CET-4":
            cet4_questions.append(q_record)
        else:
            cet6_questions.append(q_record)
            
    out_c4 = KB / "questions" / "cet4" / "translation.jsonl"
    out_c6 = KB / "questions" / "cet6" / "translation.jsonl"
    out_c4.write_text("\n".join(jsonl_dumps(q) for q in cet4_questions) + "\n", encoding="utf-8")
    out_c6.write_text("\n".join(jsonl_dumps(q) for q in cet6_questions) + "\n", encoding="utf-8")
    print(f"写入四级翻译题目: {len(cet4_questions)} 题 -> {out_c4.name}")
    print(f"写入六级翻译题目: {len(cet6_questions)} 题 -> {out_c6.name}")
    return len(cet4_questions), len(cet6_questions)


if __name__ == "__main__":
    process_writing()
    process_translation()
