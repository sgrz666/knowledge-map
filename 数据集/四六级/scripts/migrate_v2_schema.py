# -*- coding: utf-8 -*-
"""v2 schema 迁移：按《应试考证功能设计与技术支撑》§3.3 参考数据格式 + §3.2 层级挂载
- question: question_id/exam/module/question_type/source{}/knowledge_node_ids/ability_ids/difficulty/content{}/analysis{}/tags/extra
- 细粒度挂载: 按题干内容分类(主旨/推断/细节/态度/同义替换), 每题至少 1 个知识点
- 全部资源(文章/范文/翻译/模板/词汇)挂载知识图谱节点
- L5: 产出 mastery_template.json
幂等: 记录含 question_id 字段即视为已迁移。
"""
import json, re, sys
from pathlib import Path
from cet_common import jsonl_dumps

sys.stdout.reconfigure(encoding="utf-8")
KB = Path(__file__).resolve().parents[1]
ROOT = KB.parents[1]
ONT = KB / "ontology"
CN_PAPER = {1: "第一套", 2: "第二套", 3: "第三套"}

KN = {r["id"]: r for r in [json.loads(l) for l in (ONT / "knowledge_nodes.jsonl").read_text(encoding="utf-8").split("\n") if l.strip()]}

def abilities_of(node_ids):
    out = []
    for nid in node_ids:
        for a in KN.get(nid, {}).get("ability_ids", []):
            if a not in out:
                out.append(a)
    return out

MODULE_SLUG = {"听力": "listening", "阅读": "reading", "写作": "writing", "翻译": "translation"}
MODULE_STD = {"听力": "听力理解", "阅读": "阅读理解", "写作": "写作", "翻译": "翻译"}

# ---------- 题干细分类 ----------
RE_GIST = re.compile(r"mainly (about|discuss|talk|focus)|best title|central (idea|topic|point)|purpose of the (text|passage|author)|summarize|主旨", re.I)
RE_INFER = re.compile(r"\binfer|\bimply|\bsuggest|conclude|can (be |we )?(drawn|learned|inferred|concluded)|what do we learn|most probably|likely to", re.I)
RE_ATT = re.compile(r"attitude|tone of|the author('s)? (view|opinion|think|consider|regard)|feasibility", re.I)
RE_SYN = re.compile(r"closest in meaning|underlined (word|phrase|part)|be replaced|paraphras|denote", re.I)
RE_WORD = re.compile(r"what does the (word|phrase|pronoun)|refer(s)? to", re.I)

def classify_careful(stem, lv):
    s = stem or ""
    nodes = []
    if RE_SYN.search(s) or RE_WORD.search(s):
        nodes.append(f"{lv}.read.detail")
    if RE_ATT.search(s):
        nodes.append(f"{lv}.read.attitude")
        if f"{lv}.read.gist" not in nodes:
            nodes.append(f"{lv}.read.gist")
    if RE_GIST.search(s):
        if f"{lv}.read.gist" not in nodes:
            nodes.append(f"{lv}.read.gist")
    if RE_INFER.search(s):
        if f"{lv}.read.infer" not in nodes:
            nodes.append(f"{lv}.read.infer")
    if not nodes:
        nodes = [f"{lv}.read.detail", f"{lv}.read.locate"]
    if f"{lv}.read.locate" not in nodes:
        nodes.insert(1, f"{lv}.read.locate")
    return nodes[:3]

def classify_listen(stem, lv, qtype):
    s = stem or ""
    if RE_GIST.search(s):
        return [f"{lv}.listen.gist"]
    if RE_INFER.search(s):
        return [f"{lv}.listen.infer"]
    return [f"{lv}.listen.detail"]

TYPE_NODES = {
    "选词填空": ["read.cloze", "read.discourse", "lang.vocab"],
    "长篇阅读": ["read.locate", "read.synonym", "read.discourse"],
}

def qnodes(q, lv):
    qt, module = q.get("question_type"), q.get("module")
    stem = q.get("stem") or (q.get("content") or {}).get("stem")
    if module in ("听力", "听力理解"):
        return classify_listen(stem, lv, qt)
    if qt == "仔细阅读":
        return classify_careful(stem, lv)
    base = TYPE_NODES.get(qt, ["read.detail"])
    return [n if n.startswith(("cet4.", "cet6.")) else f"{lv}.{n}" for n in base]

def paper_cn(p):
    return CN_PAPER.get(p, f"第{p}套")

# ---------- 契约字段归位（《应试考证功能设计与技术支撑》§3.2 / 附录 A.1） ----------
# 数据本身不变，只把状态搬到规范规定的字段位置；无法从证据得出的值保持 null，不做推断。
REVIEW_ENUM = ("auto_parsed", "llm_enhanced", "checked", "expert_reviewed", "needs_fix", "quarantined")
COPYRIGHT_BASE = {"authorization_status": "unknown", "holder": None,
                  "use_scope": "research_non_commercial",
                  "expires_at": None, "evidence": [], "review_status": "pending_rights_verification"}

def review_status(record):
    extra = record.get("extra") or {}
    prior = record.get("review") or {}
    nested = extra.get("review") or {}
    reviewer = prior.get("checked_by") or prior.get("reviewed_by") or nested.get("reviewed_by") \
        or nested.get("checked_by") or nested.get("evidence")
    for candidate in (prior.get("status"), nested.get("status"), (record.get("tags") or {}).get("审核")):
        if candidate not in REVIEW_ENUM:
            continue
        # 没有审核人/证据的"已核验"声明不予采信，避免把脚本规整伪装成人工审核。
        if candidate in ("checked", "expert_reviewed") and not reviewer:
            continue
        return candidate
    return "auto_parsed"

def answer_status(record, provenance):
    """content.answer_status 只表达答案可用性；细粒度来源状态保留在 extra.answer_provenance。"""
    answer = (record.get("content") or {}).get("answer")
    if "conflict" in provenance:
        return "source_conflict"
    if answer in (None, "", [], {}):
        return "missing"
    if review_status(record) in ("checked", "expert_reviewed"):
        return "verified"
    return "letter_only" if re.fullmatch(r"[A-O]", str(answer).strip()) else "reference_only"

def fill_copyright(record):
    copyright_info = (record.setdefault("source", {})).setdefault("copyright", {})
    for key, value in COPYRIGHT_BASE.items():
        if copyright_info.get(key) in (None, "", [], {}):
            copyright_info[key] = json.loads(json.dumps(value))
    return record

def bind_review(record):
    """只规范状态，既有审核人/时间/证据字段一律保留。"""
    review = record.setdefault("review", {})
    review["status"] = review_status(record)
    # 附录 A.1 的实体审核署名键统一为 checked_by/checked_at（与共享 schema 及验收器一致）。
    for legacy, canonical in (("reviewed_by", "checked_by"), ("reviewed_at", "checked_at")):
        if legacy in review:
            value = review.pop(legacy)
            if value is not None and review.get(canonical) is None:
                review[canonical] = value
    review.setdefault("checked_by", None)
    review.setdefault("checked_at", None)
    # 来源答案相互冲突的题不可判分，复核态必须是隔离而非自动解析。
    if (record.get("content") or {}).get("answer_status") == "source_conflict":
        review["status"] = "quarantined"
    tags = record.get("tags")
    if isinstance(tags, dict):
        tags["版权"] = "research_non_commercial"
        tags["审核"] = review["status"]
    return record

def normalize_question(record):
    extra = record.setdefault("extra", {})
    content = record.setdefault("content", {})
    provenance = extra.pop("answer_status", None) or extra.get("answer_provenance") or "unspecified"
    extra["answer_provenance"] = provenance
    options = content.get("options")
    answer = content.get("answer")
    if isinstance(options, dict) and options and isinstance(answer, str) \
            and re.fullmatch(r"[A-Z]", answer.strip()) and answer.strip() not in options:
        # 字母不在纸面选项内说明抽取越界，保留原值待核，不能当作有效答案参与诊断。
        extra.setdefault("answer_candidates", []).append({"answer": answer, "reason": "answer_letter_outside_printed_options",
                                                          "review_status": "pending_expert_review"})
        content["answer"] = None
        provenance = "source_conflict"
        extra["answer_provenance"] = provenance
    content["answer_status"] = answer_status(record, provenance)
    record.setdefault("school_level", None)
    record.setdefault("subject", "english")
    record.setdefault("material_id", None)
    record["exam_requirement_ids"] = record.get("exam_requirement_ids") or []
    metadata = extra.get("difficulty_metadata") or {}
    if not record.get("difficulty_meta"):
        record["difficulty_meta"] = {"method": metadata.get("method") or None,
                                     "sample_size": metadata.get("sample_count", 0) or 0,
                                     "calibration_status": metadata.get("status") or metadata.get("planned_method") or "pending_calibration"}
    if record.get("difficulty") is None:
        record["difficulty"] = metadata.get("estimate")
    fill_copyright(record)
    if record["source"]["copyright"].get("source_nature") in (None, "", [], {}):
        record["source"]["copyright"]["source_nature"] = "official_exam"
    return bind_review(record)

def normalize_resource(record):
    fill_copyright(record)
    record["source"]["copyright"].pop("source_nature", None)
    return bind_review(record)

CORPUS_FILES = [KB / "listening" / "transcripts.jsonl", ROOT / "补充资料" / "四六级官方样题" / "questions.jsonl",
                ROOT / "补充资料" / "四六级官方样题" / "passages.jsonl"]

APPROVED_STATES = ("approved", "verified", "expert_reviewed")

def normalize_ontology_edges():
    """脚本自评为 approved 的先修/易混淆边一律降回待核定，审核人字段保持为空。"""
    path = ONT / "edges.jsonl"
    records = [json.loads(l) for l in path.read_text(encoding="utf-8").split("\n") if l.strip()]
    downgraded = 0
    for edge in records:
        claimed = edge.get("declared_status") or edge.get("review_status") or edge.get("status")
        if claimed in APPROVED_STATES and not (edge.get("reviewed_by") or edge.get("reviewer") or edge.get("evidence")):
            edge["declared_status"] = claimed
            edge["review_status"] = "proposed_pending_subject_expert"
            edge["status"] = "proposed_pending_review"
            edge["active"] = False
            edge["reviewed_by"] = None
            if edge.get("rel") in ("prerequisite", "prereq_of", "prerequisite_of"):
                edge["claimed_rel"] = edge["rel"]
                edge["rel"] = "prerequisite_candidate"
                edge["proposed_rel"] = edge["claimed_rel"]
            downgraded += 1
    path.write_text("\n".join(jsonl_dumps(e) for e in records) + "\n", encoding="utf-8")
    print(f"ontology edges: {len(records)} | approvals downgraded to pending: {downgraded}")

def normalize_corpus():
    """听力文字稿与官方样题同样受科研非商业边界约束，需要显式声明而不是留空。"""
    reports = []
    for path in CORPUS_FILES:
        if not path.exists():
            continue
        records = [json.loads(l) for l in path.read_text(encoding="utf-8").split("\n") if l.strip()]
        normalized = [normalize_question(r) if "question_id" in r else normalize_resource(r) for r in records]
        path.write_text("\n".join(jsonl_dumps(r) for r in normalized) + "\n", encoding="utf-8")
        reports.append((path.name, len(normalized)))
    print("corpus:", reports)

def new_qid(old_id):
    m = re.match(r"(cet[46])\.([lr])\.(\d{4}-\d{2})_p(\d)\.q(\d+)", old_id)
    slug = "listening" if m.group(2) == "l" else "reading"
    return f"{m.group(1)}-{m.group(3)}-p{m.group(4)}-{slug}-{m.group(5)}", m.group(3), int(m.group(4))

def conv_passage_id(pp):
    """旧 passage_id（点/下划线两种变体）→ 新 resource_id；听力分组置空。"""
    if not pp:
        return None
    m = (re.match(r"(cet[46])\.r\.(\d{4}-\d{2})-p(\d)\.(ca|cb|c\d)$", pp)
         or re.match(r"(cet[46])\.r\.(\d{4}-\d{2})_p(\d)\.(ca|cb|c\d)$", pp))
    if not m:
        return None
    slug = {"ca": "cloze", "cb": "matching"}.get(m.group(4), m.group(4))
    return f"{m.group(1)}-{m.group(2)}-p{m.group(3)}-reading-{slug}"

def migrate_questions():
    id_map = {}
    n = 0
    for lvdir in ("cet4", "cet6"):
        lv = lvdir
        for f in (KB / "questions" / lvdir).glob("*.jsonl"):
            out = []
            for l in f.read_text(encoding="utf-8").split("\n"):
                if not l.strip():
                    continue
                r = json.loads(l)
                if "question_id" in r:
                    if r.get('module')=='听力理解' and r.get('extra',{}).get('passage_id'):
                        r['extra'].setdefault('_legacy_listening_group_reference',r['extra']['passage_id'])
                        r['extra']['passage_id']=None
                    old_id = (r.get("extra") or {}).get("_old_id")
                    if old_id:
                        id_map[old_id] = r["question_id"]
                    # Repair records created by the faulty v2 migration; do not erase extensions.
                    if not r.get("ability_ids") or any(x.endswith((".read", ".listen")) for x in r.get("knowledge_node_ids", [])):
                        nodes = [x for x in qnodes(r, lv) if x in KN]
                        r["knowledge_node_ids"] = nodes
                        r["ability_ids"] = abilities_of(nodes)
                    out.append(normalize_question(r))
                    continue
                old_id = r["id"]
                qid, ym, paper = new_qid(old_id)
                nodes = qnodes(r, lv)
                nodes = [x for x in nodes if x in KN]
                review = r.get("review", {})
                new = {
                    "question_id": qid,
                    "exam": r["exam"],
                    "module": MODULE_STD[r["module"]],
                    "question_type": r["question_type"],
                    "source": {"type": "真题", "year": ym, "paper": paper_cn(paper), "verified": review.get("status") in ("checked", "expert_reviewed"),
                               "origin_file": r.get("source", {}).get("origin_file"),
                               "analysis_file": r.get("source", {}).get("analysis_file")},
                    "knowledge_node_ids": nodes,
                    "ability_ids": abilities_of(nodes),
                    "difficulty": None,
                    "content": {"stem": r.get("stem"), "options": r.get("options") or {}, "answer": r.get("answer")},
                    "analysis": {"key_info": None, "option_compare": None, "trace_back": None, "raw": r.get('analysis') if isinstance(r.get('analysis'),str) else None,
                                 "status": r.get("analysis_status")},
                    "tags": {"来源": "真题", "审核": review.get("status", "auto_parsed"), "版权": "research_non_commercial", "难度": None},
                    "extra": {"number": r.get("number"), "group": r.get("group"),
                              "passage_id": conv_passage_id(r.get("passage_id")),
                              "text": r.get("text"), "review": review, "_old_id": old_id},
                    "text": r.get("text"),
                }
                id_map[old_id] = qid
                out.append(normalize_question(new))
                n += 1
            f.write_text("\n".join(jsonl_dumps(x) for x in out) + "\n", encoding="utf-8")
    print(f"questions migrated: {n} | id_map: {len(id_map)}")
    return id_map

def migrate_passages(id_map):
    f = KB / "passages" / "reading.jsonl"
    out = []
    for l in f.read_text(encoding="utf-8").split("\n"):
        if not l.strip():
            continue
        r = json.loads(l)
        if "resource_id" in r:
            out.append(normalize_resource(r)); continue
        m = re.match(r"cet[46]\.r\.(\d{4}-\d{2})_p(\d)\.(ca|cb|c\d)", r["id"])
        lv = "cet4" if r["id"].startswith("cet4") else "cet6"
        kind = r["kind"]
        nid = {"cloze": [f"{lv}.read.cloze", f"{lv}.read.discourse", f"{lv}.lang.vocab"],
               "matching": [f"{lv}.read.locate", f"{lv}.read.synonym", f"{lv}.read.discourse"]}.get(kind, [f"{lv}.read", f"{lv}.read.detail"])
        slug = {"ca": "cloze", "cb": "matching"}.get(m.group(3), m.group(3))
        new = {
            "resource_id": f"{lv}-{m.group(1)}-p{m.group(2)}-reading-{slug}",
            "resource_type": "语篇",
            "exam": r["exam"], "year": m.group(1), "paper": paper_cn(int(m.group(2))),
            "kind": kind,
            "knowledge_node_ids": nid,
            "ability_ids": abilities_of(nid),
            "source": {"type": "真题", "origin_file": r.get("source", {}).get("origin_file")},
            "tags": {"来源": "真题", "审核": r.get("review", {}).get("status", "auto_parsed"), "版权": "research_non_commercial"},
            "extra": {"title": r.get("title"), "word_count": r.get("word_count"), "word_bank": r.get("word_bank"),
                      "paragraphs": r.get("paragraphs"), "question_ids": [id_map.get(x, x) for x in r.get("question_ids", [])],
                      "theme": r.get("theme")},
            "text": r.get("text"),
        }
        out.append(normalize_resource(new))
    f.write_text("\n".join(jsonl_dumps(x) for x in out) + "\n", encoding="utf-8")
    print(f"passages migrated: {len(out)}")

def pid(old):
    return re.sub(r"_p(\d)", r"-p\1", old)

def migrate_writing_trans():
    for path, rtype, nodefn in (
        (KB / "writing" / "model_essays.jsonl", "真题写作题目与范文", lambda lv: [f"{lv}.write.structure", f"{lv}.write.argument", f"{lv}.write.coherence"]),
        (KB / "translation" / "items.jsonl", "真题翻译段落与译文", lambda lv: [f"{lv}.trans.topic", f"{lv}.trans.syntax"]),
    ):
        out = []
        for l in path.read_text(encoding="utf-8").split("\n"):
            if not l.strip():
                continue
            r = json.loads(l)
            if "resource_id" in r:
                out.append(normalize_resource(r)); continue
            m = re.match(r"cet[46]\.([wt])\.(\d{4}-\d{2})_p(\d)", r["id"])
            lv = "cet4" if r["id"].startswith("cet4") else "cet6"
            slug = "writing" if m.group(1) == "w" else "translation"
            nodes = [x for x in nodefn(lv) if x in KN]
            new = {
                "resource_id": f"{lv}-{m.group(2)}-p{m.group(3)}-{slug}-1",
                "resource_type": rtype,
                "exam": r["exam"], "year": m.group(2), "paper": paper_cn(int(m.group(3))),
                "knowledge_node_ids": nodes,
                "ability_ids": abilities_of(nodes),
                "source": {"type": rtype, "origin_file": r.get("source", {}).get("origin_file")},
                "tags": {"来源": "真题", "审核": r.get("review", {}).get("status", "auto_parsed"), "版权": "research_non_commercial"},
                "extra": {k: v for k, v in r.items() if k not in ("id", "exam", "year", "paper", "source", "review", "text")},
                "text": r.get("text"),
            }
            out.append(normalize_resource(new))
        path.write_text("\n".join(jsonl_dumps(x) for x in out) + "\n", encoding="utf-8")
        print(f"{path.name}: {len(out)}")

def migrate_templates():
    path = KB / "writing" / "templates.jsonl"
    CAT_NODES = {"opening": "write.structure", "phenomenon": "write.structure", "quote": "write.argument",
                 "argument": "write.argument", "compare": "write.argument", "example": "write.argument",
                 "cause": "write.argument", "solution": "write.argument", "concession": "write.argument",
                 "transition": "write.coherence", "prediction": "write.structure", "ending": "write.structure",
                 "universal": "write.accuracy", "other": "write.accuracy"}
    out = []
    for l in path.read_text(encoding="utf-8").split("\n"):
        if not l.strip():
            continue
        r = json.loads(l)
        if "resource_id" in r:
            out.append(normalize_resource(r)); continue
        nid = f"cet4.{CAT_NODES.get(r.get('category'), 'write.accuracy')}"
        nodes = [nid, "cet6." + CAT_NODES.get(r.get("category"), "write.accuracy")]
        nodes = [x for x in nodes if x in KN]
        out.append(normalize_resource({
            "resource_id": r["id"], "resource_type": "写作模板句",
            "knowledge_node_ids": nodes, "ability_ids": abilities_of(nodes),
            "source": {"type": "模板资源", "origin_file": r.get("source", {}).get("origin_file"), "book": r.get("source", {}).get("book")},
            "tags": {"来源": "辅导资料", "审核": "auto_parsed", "版权": "research_non_commercial"},
            "extra": {k: v for k, v in r.items() if k not in ("id", "source", "text")},
            "text": r.get("text"),
        }))
    path.write_text("\n".join(jsonl_dumps(x) for x in out) + "\n", encoding="utf-8")
    print(f"templates: {len(out)}")

def migrate_vocab():
    reports = []
    for name, nodes in (("words_cet4.jsonl", ["cet4.lang.vocab"]), ("words_cet6.jsonl", ["cet6.lang.vocab"]),
                        ("core_words.jsonl", None), ("phrases_highfreq.jsonl", None),
                        ("translation_topic_words.jsonl", ["cet4.trans.topic", "cet6.trans.topic"])):
        path = KB / "vocabulary" / name
        if not path.exists():
            continue
        out = []
        for l in path.read_text(encoding="utf-8").split("\n"):
            if not l.strip():
                continue
            r = json.loads(l)
            if "resource_id" in r:
                out.append(normalize_resource(r)); continue
            if name == "core_words.jsonl":
                nn = ["cet4.lang.vocab"] if r.get("level") == "CET-4" else ["cet6.lang.vocab"]
            elif name == "phrases_highfreq.jsonl":
                nn = ["cet4.lang.vocab", "cet6.lang.vocab"]
            else:
                nn = nodes
            nn = [x for x in nn if x in KN]
            out.append(normalize_resource({
                "resource_id": r["id"], "resource_type": "词汇语料",
                "knowledge_node_ids": nn, "ability_ids": abilities_of(nn),
                "source": {"type": "词汇表/词组表", "origin_file": r.get("source", {}).get("origin_file")},
                "tags": {"来源": "考试大纲/高频统计", "审核": r.get("review", {}).get("status", "auto_parsed"), "版权": "research_non_commercial"},
                "extra": {k: v for k, v in r.items() if k not in ("id", "source", "review", "text")},
                "text": r.get("text"),
            }))
        path.write_text("\n".join(jsonl_dumps(x) for x in out) + "\n", encoding="utf-8")
        reports.append((name, len(out)))
    print("vocab:", reports)

def migrate_papers(id_map_unused):
    f = KB / "manifest" / "papers.jsonl"
    out = []
    for l in f.read_text(encoding="utf-8").split("\n"):
        if not l.strip():
            continue
        r = json.loads(l)
        if "paper_id" in r:
            out.append(r); continue
        lv = "cet4" if r["exam"] == "CET-4" else "cet6"
        new = dict(r)
        new["paper_id"] = f"{lv}-{r['year']}-p{r['paper']}"
        new.pop("id", None)
        for refk in ("listening_ref", "reading_ref"):
            if r.get(refk):
                mm = re.match(r"(cet[46])\.(\d{4}-\d{2})_p(\d)", r[refk])
                new[refk] = f"{mm.group(1)}-{mm.group(2)}-p{mm.group(3)}" if mm else r[refk]
        out.append(new)
    f.write_text("\n".join(jsonl_dumps(x) for x in out) + "\n", encoding="utf-8")
    print(f"papers: {len(out)}")

def mastery_template():
    tpl = {
        "layer": "L5 用户掌握度",
        "说明": "掌握度为运行时数据(按 用户×知识点 维度持续更新),不入静态知识库;本模板供学习Agent落库使用",
        "record_schema": {
            "user_id": "string",
            "knowledge_node_id": "cet4.read.infer",
            "mastery": "0.0-1.0",
            "status": "未学习|已掌握|待巩固|薄弱",
            "evidence": [{"question_id": "...", "correct": True, "ts": "ISO8601", "duration_ms": 0}],
            "updated_at": "ISO8601",
            "next_review": "FSRS/SM-2 计划时间",
        },
        "update_rule": "每次作答后按 (用户,知识点) 重算; BKT/DKT 可替换简单计数",
    }
    (ONT / "mastery_template.json").write_text(json.dumps(tpl, ensure_ascii=False, indent=1), encoding="utf-8")
    print("mastery_template.json: ok")

def main():
    id_map = migrate_questions()
    migrate_passages(id_map)
    migrate_writing_trans()
    migrate_templates()
    migrate_vocab()
    migrate_papers(id_map)
    normalize_corpus()
    normalize_ontology_edges()
    mastery_template()

if __name__ == "__main__":
    main()
