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

sys.stdout.reconfigure(encoding="utf-8")
KB = Path(r"D:\codeplus\knowledge_map\数据集\四六级")
ONT = KB / "ontology"
CN_PAPER = {1: "第一套", 2: "第二套", 3: "第三套"}

KN = {r["id"]: r for r in [json.loads(l) for l in (ONT / "knowledge_nodes.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]}

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
    if module == "听力":
        return classify_listen(q.get("stem"), lv, qt)
    if qt == "仔细阅读":
        return classify_careful(q.get("stem"), lv)
    base = TYPE_NODES.get(qt, ["read.detail"])
    return [f"{lv}.{n}" if "." not in n else n for n in base]

def paper_cn(p):
    return CN_PAPER.get(p, f"第{p}套")

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
            for l in f.read_text(encoding="utf-8").splitlines():
                if not l.strip():
                    continue
                r = json.loads(l)
                if "question_id" in r:
                    id_map[r["extra"]["_old_id"]] = r["question_id"] if r.get("extra") else r["question_id"]
                    out.append(r)
                    continue
                old_id = r["id"]
                qid, ym, paper = new_qid(old_id)
                nodes = qnodes(r, lv)
                nodes = [x for x in nodes if x in KN] or [f"{lv}.read", f"{lv}.listen"]
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
                    "analysis": {"key_info": None, "option_compare": None, "trace_back": None, "raw": None,
                                 "status": r.get("analysis_status")},
                    "tags": {"来源": "真题", "审核": review.get("status", "auto_parsed"), "版权": "internal-personal-use", "难度": None},
                    "extra": {"number": r.get("number"), "group": r.get("group"),
                              "passage_id": conv_passage_id(r.get("passage_id")),
                              "text": r.get("text"), "review": review, "_old_id": old_id},
                    "text": r.get("text"),
                }
                id_map[old_id] = qid
                out.append(new)
                n += 1
            f.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in out) + "\n", encoding="utf-8")
    print(f"questions migrated: {n} | id_map: {len(id_map)}")
    return id_map

def migrate_passages(id_map):
    f = KB / "passages" / "reading.jsonl"
    out = []
    for l in f.read_text(encoding="utf-8").splitlines():
        if not l.strip():
            continue
        r = json.loads(l)
        if "resource_id" in r:
            out.append(r); continue
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
            "tags": {"来源": "真题", "审核": r.get("review", {}).get("status", "auto_parsed"), "版权": "internal-personal-use"},
            "extra": {"title": r.get("title"), "word_count": r.get("word_count"), "word_bank": r.get("word_bank"),
                      "paragraphs": r.get("paragraphs"), "question_ids": [id_map.get(x, x) for x in r.get("question_ids", [])],
                      "theme": r.get("theme")},
            "text": r.get("text"),
        }
        out.append(new)
    f.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in out) + "\n", encoding="utf-8")
    print(f"passages migrated: {len(out)}")

def pid(old):
    return re.sub(r"_p(\d)", r"-p\1", old)

def migrate_writing_trans():
    for path, rtype, nodefn in (
        (KB / "writing" / "model_essays.jsonl", "真题写作题目与范文", lambda lv: [f"{lv}.write.structure", f"{lv}.write.argument", f"{lv}.write.coherence"]),
        (KB / "translation" / "items.jsonl", "真题翻译段落与译文", lambda lv: [f"{lv}.trans.topic", f"{lv}.trans.syntax"]),
    ):
        out = []
        for l in path.read_text(encoding="utf-8").splitlines():
            if not l.strip():
                continue
            r = json.loads(l)
            if "resource_id" in r:
                out.append(r); continue
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
                "tags": {"来源": "真题", "审核": r.get("review", {}).get("status", "auto_parsed"), "版权": "internal-personal-use"},
                "extra": {k: v for k, v in r.items() if k not in ("id", "exam", "year", "paper", "source", "review", "text")},
                "text": r.get("text"),
            }
            out.append(new)
        path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in out) + "\n", encoding="utf-8")
        print(f"{path.name}: {len(out)}")

def migrate_templates():
    path = KB / "writing" / "templates.jsonl"
    CAT_NODES = {"opening": "write.structure", "phenomenon": "write.structure", "quote": "write.argument",
                 "argument": "write.argument", "compare": "write.argument", "example": "write.argument",
                 "cause": "write.argument", "solution": "write.argument", "concession": "write.argument",
                 "transition": "write.coherence", "prediction": "write.structure", "ending": "write.structure",
                 "universal": "write.accuracy", "other": "write.accuracy"}
    out = []
    for l in path.read_text(encoding="utf-8").splitlines():
        if not l.strip():
            continue
        r = json.loads(l)
        if "resource_id" in r:
            out.append(r); continue
        nid = f"cet4.{CAT_NODES.get(r.get('category'), 'write.accuracy')}"
        nodes = [nid, "cet6." + CAT_NODES.get(r.get("category"), "write.accuracy")]
        nodes = [x for x in nodes if x in KN]
        out.append({
            "resource_id": r["id"], "resource_type": "写作模板句",
            "knowledge_node_ids": nodes, "ability_ids": abilities_of(nodes),
            "source": {"type": "模板资源", "origin_file": r.get("source", {}).get("origin_file"), "book": r.get("source", {}).get("book")},
            "tags": {"来源": "辅导资料", "审核": "auto_parsed", "版权": "internal-personal-use"},
            "extra": {k: v for k, v in r.items() if k not in ("id", "source", "text")},
            "text": r.get("text"),
        })
    path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in out) + "\n", encoding="utf-8")
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
        for l in path.read_text(encoding="utf-8").splitlines():
            if not l.strip():
                continue
            r = json.loads(l)
            if "resource_id" in r:
                out.append(r); continue
            if name == "core_words.jsonl":
                nn = ["cet4.lang.vocab"] if r.get("level") == "CET-4" else ["cet6.lang.vocab"]
            elif name == "phrases_highfreq.jsonl":
                nn = ["cet4.lang.vocab", "cet6.lang.vocab"]
            else:
                nn = nodes
            nn = [x for x in nn if x in KN]
            out.append({
                "resource_id": r["id"], "resource_type": "词汇语料",
                "knowledge_node_ids": nn, "ability_ids": abilities_of(nn),
                "source": {"type": "词汇表/词组表", "origin_file": r.get("source", {}).get("origin_file")},
                "tags": {"来源": "考试大纲/高频统计", "审核": r.get("review", {}).get("status", "auto_parsed"), "版权": "internal-personal-use"},
                "extra": {k: v for k, v in r.items() if k not in ("id", "source", "review", "text")},
                "text": r.get("text"),
            })
        path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in out) + "\n", encoding="utf-8")
        reports.append((name, len(out)))
    print("vocab:", reports)

def migrate_papers(id_map_unused):
    f = KB / "manifest" / "papers.jsonl"
    out = []
    for l in f.read_text(encoding="utf-8").splitlines():
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
    f.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in out) + "\n", encoding="utf-8")
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
    mastery_template()

if __name__ == "__main__":
    main()
