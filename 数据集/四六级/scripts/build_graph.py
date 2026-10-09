# -*- coding: utf-8 -*-
"""四六级图谱导出：按《应试考证功能设计与技术支撑》§3.2 八层分级与 §3.4 边契约生成
graph/nodes.jsonl、graph/edges.jsonl。

未经教研核定的先修/易混淆关系一律保持候选状态（active_for_learning_path=False），
自动映射一律 verified=False，不以任何脚本自评冒充专家审核。
"""
import json
import sys
from collections import Counter
from pathlib import Path

KB = Path(__file__).resolve().parents[1]
ROOT = KB.parents[1]
OUT = KB / "graph"
SCRIPTS = KB / "scripts"
sys.path.insert(0, str(ROOT / "kb_tools"))
from kb_scope import select as scope_select  # noqa: E402  与教资共用同一套 exam_scope 归属判定

EDGE_ASSESSMENT = "assesses"
EDGE_ABILITY = "supports_ability"
EDGE_REQUIREMENT = "aligned_to_requirement"
EDGE_PREREQ = "prerequisite_of"
EDGE_MATERIAL = "refers_to_material"
EDGE_RUBRIC = "has_rubric"
PREREQ_VERIFIED = "verified"
PREREQ_PENDING = "proposed_pending_review"

EXAM_SLUG = {"CET-4": "cet4", "CET-6": "cet6"}
MODULE_SLUG = {"听力理解": "listening", "阅读理解": "reading", "写作": "writing", "翻译": "translation"}
REVIEWED_KEYS = ("reviewed_by", "reviewer")


def rows(path):
    records = []
    for target in (path if isinstance(path, list) else [path]):
        if not Path(target).exists():
            continue
        for line in Path(target).read_text(encoding="utf-8").split("\n"):
            if line.strip():
                records.append(json.loads(line))
    return records


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(path)


def human_reviewer(row):
    for key in REVIEWED_KEYS:
        if row.get(key):
            return row[key]
    return None


def main():
    nodes, edges, edge_keys = {}, [], set()

    def node(nid, layer, kind, name, **values):
        if nid not in nodes:
            nodes[nid] = {"id": nid, "layer": layer, "type": kind, "name": name, **values}

    def edge(src, dst, kind, **values):
        key = (src, dst, kind, values.get("status"))
        if key in edge_keys or src not in nodes or dst not in nodes:
            return
        edge_keys.add(key)
        edges.append({"src": src, "dst": dst, "type": kind, **values})

    questions = []
    for level in ("cet4", "cet6"):
        questions.extend(rows(sorted((KB / "questions" / level).glob("*.jsonl"))))
    abilities = rows(KB / "ontology" / "ability_nodes.jsonl")
    knowledge = rows(KB / "ontology" / "knowledge_nodes.jsonl")
    rubrics = rows(KB / "ontology" / "scoring_rubrics.jsonl")
    passages = rows([p for p in (KB / "passages").glob("*.jsonl") if not p.name.startswith("_")])
    resources = rows([p for folder in ("writing", "translation", "vocabulary", "listening")
                      for p in sorted((KB / folder).glob("*.jsonl")) if not p.name.startswith("_")])

    # L0 全量入图：CSE 量表描述语与四六级大纲条款都是 §3.1 声明的挂载标尺，
    # 此前只导出"已被题目引用"的条款，导致 3,886 条 CSE 描述语在图上不存在。
    catalog_path = ROOT / "权威资料" / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8")) if catalog_path.exists() else {}
    standard_rows, requirement_rows = scope_select(
        catalog.get("sources", []), rows(ROOT / "权威资料" / "requirements.jsonl"), "cet")

    for standard_id, source in sorted(standard_rows.items()):
        node(standard_id, "L0", "standard", source.get("title") or source.get("name") or standard_id,
             source_url=source.get("source_url"), local_path=source.get("local_path"),
             exam_scope=source.get("exam_scope", []),
             verified=bool(source.get("verified")), verification_scope="official_source_acquisition")
    for requirement_id, requirement in sorted(requirement_rows.items()):
        node(requirement_id, "L0", "exam_requirement", requirement.get("title") or requirement.get("content"),
             standard_id=requirement.get("standard_id"), locator=requirement.get("locator"),
             content=requirement.get("content"), exam_scope=requirement.get("exam_scope", []),
             verified=False,
             verification_scope="extracted_clause_pending_review")
        edge(requirement.get("standard_id"), requirement_id, "specifies")

    counts = Counter((q["exam"], q["module"]) for q in questions)
    for exam, slug in sorted(EXAM_SLUG.items(), key=lambda kv: kv[1]):
        eid = "cet." + slug
        node(eid, "L1", "exam", exam)
        literacy = eid + ".literacy.communicative_competence"
        node(literacy, "L3", "literacy", "语言运用与交际能力", exam=eid, verified=False,
             verification_scope="curricular_construct_pending_review")
        edge(eid, literacy, "targets")
        for module, module_slug in sorted(MODULE_SLUG.items()):
            mid = f"{eid}.{module_slug}"
            node(mid, "L2", "module", module, exam=eid, question_count=counts.get((exam, module), 0))
            edge(eid, mid, "contains")

    for ability in abilities:
        aid = ability["id"]
        exam_slug = next((slug for slug in EXAM_SLUG.values() if f".{slug}." in aid), "cet4")
        node(aid, "L3", "ability", ability.get("name") or aid, exam="cet." + exam_slug, verified=False,
             inheritance="none; explicit supports_ability edges and question ability_ids only")
        edge(f"cet.{exam_slug}.literacy.communicative_competence", aid, "comprises")
        for nid in ability.get("knowledge_node_ids") or []:
            if nid in {k["id"] for k in knowledge}:
                edge(aid, nid, EDGE_ABILITY, verified=False, mapping_status="automatic_pending_review")

    knowledge_ids = {k["id"] for k in knowledge}
    for item in knowledge:
        nid = item["id"]
        exam_slug = nid.split(".", 1)[0]
        module_node = f"cet.{exam_slug}.{MODULE_SLUG.get(item.get('module'), 'reading')}"
        node(nid, "L4", "knowledge_node", item.get("name") or nid, module=module_node,
             assessable=bool(item.get("question_types")), description=item.get("description"),
             exam_requirement_ids=item.get("exam_requirement_ids") or [],
             mapping_status=item.get("mapping_status"), verified=False)
        parent = item.get("parent")
        if parent and parent in knowledge_ids:
            edge(parent, nid, "has_child")
        elif parent == "root":
            edge(module_node, nid, "contains")
        else:
            edge(module_node, nid, "contains")
        for requirement_id in item.get("exam_requirement_ids") or []:
            edge(requirement_id, nid, EDGE_REQUIREMENT, verified=False, mapping_status="automatic_pending_review")

    for passage in passages:
        pid = passage.get("resource_id")
        node(pid, "L5", "material", passage.get("extra", {}).get("title") or pid,
             word_count=passage.get("extra", {}).get("word_count") or len(passage.get("text") or ""),
             exam="cet." + pid.split("-", 1)[0], material_kind=passage.get("kind"))

    for record in rubrics:
        rid = record["rubric_id"]
        node(rid, "L6", "rubric", record.get("task_type") or rid, task_type=record.get("task_type"),
             method=record.get("method"), bands=record.get("bands"),
             review_status=record.get("review_status"), verified=False)

    for question in questions:
        qid = question["question_id"]
        slug = qid.split("-", 1)[0]
        eid = "cet." + slug
        mid = f"{eid}.{MODULE_SLUG[question['module']]}"
        node(qid, "L6", "question", None, module=mid, question_type=question.get("question_type"),
             answer_status=(question.get("content") or {}).get("answer_status"),
             review=(question.get("review") or {}).get("status"), difficulty=question.get("difficulty"),
             difficulty_meta=question.get("difficulty_meta"))
        edge(mid, qid, "contains")
        for nid in question.get("knowledge_node_ids") or []:
            edge(nid, qid, EDGE_ASSESSMENT, verified=False, mapping_status="automatic_pending_review")
        for aid in question.get("ability_ids") or []:
            edge(aid, qid, EDGE_ABILITY, verified=False, mapping_status="automatic_pending_review")
        for requirement_id in question.get("exam_requirement_ids") or []:
            edge(requirement_id, qid, EDGE_REQUIREMENT, verified=False, mapping_status="automatic_pending_review")
        material_id = (question.get("extra") or {}).get("passage_id") or question.get("material_id")
        if material_id and material_id in nodes:
            edge(qid, material_id, EDGE_MATERIAL)
        if question.get("rubric_id") and question["rubric_id"] in nodes:
            edge(qid, question["rubric_id"], EDGE_RUBRIC)

    for item in resources:
        rid = item.get("resource_id")
        if not rid:
            continue
        # 范文/译文资源与其题目同号，入图时加 res. 命名空间，避免覆盖 L6 题目节点后被误标成能力→题目
        gid = rid if rid not in nodes else "res." + rid
        extra = {"for_question": rid} if gid != rid else {}
        node(gid, "L7", "resource", item.get("resource_type") or rid, res_type=item.get("resource_type"),
             exam="cet." + slug if (slug := rid.split("-", 1)[0]) in EXAM_SLUG.values() else None, **extra)
        for nid in item.get("knowledge_node_ids") or []:
            if nid in nodes:
                edge(nid, gid, "supplements_resource")
        for aid in item.get("ability_ids") or []:
            if aid in nodes:
                edge(aid, gid, "supports_resource")

    for relation in rows(KB / "ontology" / "edges.jsonl"):
        src, dst, kind = relation.get("src"), relation.get("dst"), relation.get("rel")
        if not (src and dst):
            continue
        reviewer = human_reviewer(relation)
        claimed = relation.get("review_status") or relation.get("status")
        if kind in ("prerequisite", "prereq_of", "prerequisite_of", "prerequisite_candidate"):
            approved = claimed in ("approved", "verified") and bool(reviewer)
            edge(src, dst, EDGE_PREREQ,
                 status=PREREQ_VERIFIED if approved else PREREQ_PENDING,
                 rationale=relation.get("说明") or relation.get("description"),
                 reviewed_by=reviewer, active_for_learning_path=approved,
                 declared_review_status=relation.get("review_status"))
        elif kind in ("confused_with", "misconception_lead_to"):
            if src in nodes and dst in nodes:
                edge(src, dst, kind, status=PREREQ_PENDING if not reviewer else PREREQ_VERIFIED,
                     rationale=relation.get("说明") or relation.get("cognitive_trap") or relation.get("error_pattern"),
                     reviewed_by=reviewer, active_for_learning_path=False)

    dangling = [e for e in edges if e["src"] not in nodes or e["dst"] not in nodes]
    if dangling:
        raise ValueError("Dangling graph endpoints: " + str(dangling[:3]))

    atomic_write(OUT / "nodes.jsonl", "".join(json.dumps(n, ensure_ascii=False) + "\n"
                                              for n in sorted(nodes.values(), key=lambda n: n["id"])))
    atomic_write(OUT / "edges.jsonl", "".join(json.dumps(e, ensure_ascii=False) + "\n"
                                             for e in sorted(edges, key=lambda e: (e["src"], e["dst"], e["type"]))))
    layers = Counter(n["layer"] for n in nodes.values())
    stats = {
        "nodes": len(nodes),
        "edges": len(edges),
        "by_layer": {layer: layers.get(layer, 0) for layer in ("L0", "L1", "L2", "L3", "L4", "L5", "L6", "L7")},
        "by_type": dict(Counter(n["type"] for n in nodes.values())),
        "by_edge_type": dict(Counter(e["type"] for e in edges)),
        "prerequisite_verified": sum(1 for e in edges if e["type"] == EDGE_PREREQ and e.get("status") == PREREQ_VERIFIED),
        "prerequisite_pending": sum(1 for e in edges if e["type"] == EDGE_PREREQ and e.get("status") == PREREQ_PENDING),
        "files": ["graph/nodes.jsonl", "graph/edges.jsonl"],
        "note": "八层分级与 §3.4 边命名对齐；自动映射与条款引用一律 verified=False 待教研核定；无审核人的先修自评已降为候选。",
    }
    atomic_write(OUT / "graph_stats.json", json.dumps(stats, ensure_ascii=False, indent=1))
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
