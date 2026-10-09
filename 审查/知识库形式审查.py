"""只读检查两套知识库；仅在审查目录保存结果及含原始检查代码的 notebook。"""
import json
import re
from pathlib import Path
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent
ERRORS = []


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def rows(paths):
    result = []
    for path in sorted(paths):
        # JSON 字符串可含 U+2028 等 Unicode 分隔符；JSONL 只按物理换行切记录。
        for number, line in enumerate(path.open(encoding="utf-8-sig"), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                result.append((record, str(path.relative_to(ROOT)), number))
            except (ValueError, TypeError) as exc:
                ERRORS.append({"file": str(path.relative_to(ROOT)), "line": number, "error": str(exc)})
    return result


def present(value):
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None and value != "" and value != [] and value != {}


def analysis_text_present(analysis, content):
    values = [content.get("analysis")]
    if isinstance(analysis, dict):
        values.extend(analysis.get(key) for key in ("raw", "raw_text", "published_explanation", "explanation", "key_info", "option_compare"))
    else:
        values.append(analysis)
    for value in values:
        if not isinstance(value, str):
            continue
        text = re.sub(r"[\s。．.!！,，;；:：]+", "", value)
        if text and text not in {"缺", "略", "无", "暂无", "暂缺", "参见解析", "见解析", "答案略", "解析略", "待补", "待补充"} and not re.fullmatch(r"[A-O]+", text, re.I):
            return True
    return False


def pct(n, total):
    return round(100 * n / total, 2) if total else None


def source_exists(value, bases):
    if isinstance(value, dict):
        paths = [entry.get("path") for entry in value.get("files") or [] if isinstance(entry, dict)]
        paths.append(value.get("origin_file"))
        return any(source_exists(path, bases) for path in paths if path)
    if not value:
        return False
    relative = Path(value.replace("\\", "/"))
    return any((base / relative).is_file() for base in bases)


def dag_check(edges):
    adjacency = defaultdict(set)
    indegrees = Counter()
    for a, b in edges:
        if b not in adjacency[a]:
            adjacency[a].add(b)
            indegrees[b] += 1
        indegrees.setdefault(a, 0)
    queue = deque(n for n, degree in indegrees.items() if degree == 0)
    visited = 0
    while queue:
        node = queue.popleft()
        visited += 1
        for child in adjacency[node]:
            indegrees[child] -= 1
            if indegrees[child] == 0:
                queue.append(child)
    return {"nodes": len(indegrees), "acyclic": visited == len(indegrees)}


def question_profile(data, kn_ids, ab_ids, source_bases, qid_set=None, material_ids=None):
    counts = Counter()
    segments = defaultdict(Counter)
    samples = defaultdict(list)
    id_counts = Counter()
    for r, file, line in data:
        counts["total"] += 1
        qid = r.get("question_id")
        id_counts[qid] += 1
        content = r.get("content") or {}
        nodes = r.get("knowledge_node_ids") or []
        abilities = r.get("ability_ids") or []
        source = r.get("source") or {}
        review = r.get("review") or r.get("extra", {}).get("review") or {}
        analysis = r.get("analysis") or content.get("analysis")
        flags = {
            "with_knowledge": bool(nodes),
            "with_ability_field": bool(abilities),
            "with_answer": present(content.get("answer")),
            "with_difficulty": present(r.get("difficulty")),
            "with_analysis_content": analysis_text_present(analysis, content),
            "with_structured_analysis": isinstance(analysis, dict) and all(present(analysis.get(k)) for k in ("key_info", "option_compare", "trace_back")),
            "source_verified_true": source.get("verified") is True,
            "source_file_exists": source_exists(source, source_bases),
            "with_tags": bool(r.get("tags")),
            "marked_duplicate": bool(r.get("extra", {}).get("duplicate_of")),
            "with_material": bool(r.get("material_id")),
            "blank_stem": not present(content.get("stem")),
            "with_audio_field": any(present(r.get("extra", {}).get(k)) for k in ("audio", "audio_url", "audio_id", "audio_path")),
            "with_exam_requirement_id": present(r.get("exam_requirement_ids")),
            "coarse_read_listen_fallback": set(nodes) in ({"cet4.read", "cet4.listen"}, {"cet6.read", "cet6.listen"}),
        }
        for name, ok in flags.items():
            counts[name] += int(ok)
        key = r.get("exam", "") if "level" not in r else f"{r['level']}/{r['subject']}"
        segments[key]["total"] += 1
        for name in ("with_knowledge", "with_answer", "with_analysis_content", "marked_duplicate"):
            segments[key][name] += int(flags[name])
        counts["review:" + str(review.get("status"))] += 1
        counts["tagger:" + str(review.get("tagger"))] += 1
        counts["type:" + str(r.get("question_type"))] += 1
        counts["answer_status:" + str(content.get("answer_status"))] += 1
        counts["exam:" + str(r.get("exam"))] += 1
        problems = []
        if not nodes:
            problems.append("untagged")
        if any(n not in kn_ids for n in nodes):
            problems.append("dangling_knowledge")
        if any(a not in ab_ids for a in abilities):
            problems.append("dangling_ability")
        if material_ids is not None and r.get("material_id") and r["material_id"] not in material_ids:
            problems.append("dangling_material")
        duplicate = r.get("extra", {}).get("duplicate_of")
        if qid_set is not None and duplicate and duplicate not in qid_set:
            problems.append("dangling_duplicate_of")
        if flags["source_verified_true"] and review.get("status") in ("低置信", "待复核", "needs_fix", "auto_parsed"):
            problems.append("source_verified_but_question_unreviewed")
        if not flags["source_file_exists"]:
            problems.append("source_path_unresolved")
        options = content.get("options")
        keys = set(options) if isinstance(options, dict) else {o.get("key") for o in options or [] if isinstance(o, dict)}
        answer = content.get("answer")
        if isinstance(answer, str) and re.fullmatch(r"[A-Z]", answer.strip()) and keys and answer.strip() not in keys:
            problems.append("answer_not_in_options")
        for problem in problems:
            counts[problem] += 1
            if len(samples[problem]) < 5:
                samples[problem].append({"id": qid, "file": file, "line": line, "knowledge": nodes, "answer": answer, "stem": str(content.get("stem", ""))[:160]})
    counts["duplicate_id_rows"] = sum(n - 1 for n in id_counts.values() if n > 1)
    return {"counts": dict(counts), "rates": {k: pct(v, counts["total"]) for k, v in counts.items() if k.startswith("with_")}, "segments": {k: dict(v) for k, v in sorted(segments.items())}, "samples": dict(samples)}


def audit_cet():
    base = ROOT / "数据集" / "四六级"
    raw = ROOT / "英语四六级资料合集（2026年最新）(1)"
    kn = rows([base / "ontology" / "knowledge_nodes.jsonl"])
    ab = rows([base / "ontology" / "ability_nodes.jsonl"])
    edges = rows([base / "ontology" / "edges.jsonl"])
    standards = read_json(base / "ontology" / "standards.json")
    kn_ids = {r["id"] for r, _, _ in kn}
    ab_ids = {r["id"] for r, _, _ in ab}
    graph_ids = kn_ids | ab_ids | {r["id"] for r in standards["standards"] + standards["素养目标"]}
    questions = rows(base.glob("questions/*/*.jsonl"))
    qids = {r["question_id"] for r, _, _ in questions}
    profile = question_profile(questions, kn_ids, ab_ids, [raw, base, base / "scripts", ROOT])
    resources = {}
    resource_ids = set()
    passage_ids = set()
    resource_data = {}
    for folder in ("passages", "writing", "translation", "vocabulary", "listening"):
        for path in sorted((base / folder).glob("*.jsonl")):
            if path.name.startswith("_"):
                continue
            data = rows([path])
            resource_data[path.name] = data
            ids = [r.get("resource_id") for r, _, _ in data]
            resource_ids.update(ids)
            if folder == "passages":
                passage_ids.update(ids)
            c = Counter(total=len(data))
            for r, _, _ in data:
                extra = r.get("extra") or {}
                c["with_knowledge"] += bool(r.get("knowledge_node_ids"))
                c["with_ability"] += bool(r.get("ability_ids"))
                c["dangling_knowledge"] += any(n not in kn_ids for n in r.get("knowledge_node_ids", []))
                c["dangling_ability"] += any(n not in ab_ids for n in r.get("ability_ids", []))
                c["with_model_essay"] += present(extra.get("model_essay"))
                c["with_reference_translation"] += present(extra.get("reference_translation")) or present(extra.get("reference"))
                c["source_file_exists"] += source_exists(r.get("source") or {}, [raw, base, base / "scripts", ROOT])
                c["with_exam"] += present(r.get("exam"))
                c["with_exam_requirement_id"] += present(r.get("exam_requirement_ids"))
            c["duplicate_ids"] = sum(n - 1 for n in Counter(ids).values() if n > 1)
            resources[str(path.relative_to(base))] = dict(c)
    passage_links = Counter()
    passage_link_samples = []
    for r, file, line in questions:
        pid = r.get("extra", {}).get("passage_id")
        if pid:
            passage_links["question_with_passage_id"] += 1
            if pid not in passage_ids:
                passage_links["dangling_question_passage_id"] += 1
                if len(passage_link_samples) < 4:
                    passage_link_samples.append({"id": r["question_id"], "passage_id": pid, "file": file, "line": line})
    for r, _, _ in resource_data.get("reading.jsonl", []):
        for qid in r.get("extra", {}).get("question_ids", []):
            passage_links["passage_question_links"] += 1
            passage_links["dangling_passage_question_id"] += qid not in qids
    edge_types = Counter(r.get("rel") for r, _, _ in edges)
    bad_edges = [r for r, _, _ in edges if r["src"] not in graph_ids or r["dst"] not in graph_ids]
    prerequisites = [(r["src"], r["dst"]) for r, _, _ in edges if (r.get("type") or r.get("rel")) in ("prerequisite_of", "prerequisite", "prereq_of")]
    ref_fields = ("source", "source_url", "origin_file", "version", "effective_date", "clause", "outline_item_id", "standard_ids")
    return {"questions": profile, "resources": resources, "passage_links": dict(passage_links), "passage_link_samples": passage_link_samples,
            "ontology": {"knowledge_nodes": len(kn), "ability_nodes": len(ab), "edges": len(edges), "edge_types": dict(edge_types), "dangling_edges": bad_edges[:8], "dangling_edges_count": len(bad_edges), "prerequisite_dag": dag_check(prerequisites), "standards": standards["standards"], "knowledge_with_authority_fields": sum(any(present(r.get(k)) for k in ref_fields) for r, _, _ in kn), "knowledge_without_ability": sum(not r.get("ability_ids") for r, _, _ in kn)},
            "manifest_stats": read_json(base / "manifest" / "stats.json")}


def audit_ntce():
    base = ROOT / "数据集/教资"
    nodes = rows([base / "graph" / "nodes.jsonl"])
    edges = rows([base / "graph" / "edges.jsonl"])
    by_id = {r["id"]: r for r, _, _ in nodes}
    kn_ids = {nid for nid, r in by_id.items() if r.get("type") == "knowledge_node"}
    ab_ids = {nid for nid, r in by_id.items() if r.get("type") == "ability"}
    materials = rows(base.glob("materials/*/*/*.jsonl"))
    mids = {r.get("material_id") for r, _, _ in materials}
    questions = rows(base.glob("questions/*/*/*.jsonl"))
    qids = {r["question_id"] for r, _, _ in questions}
    profile = question_profile(questions, kn_ids, ab_ids, [ROOT], qids, mids)
    direct = defaultdict(set)
    descendants = defaultdict(set)
    edge_types = Counter()
    bad_edges = []
    module_knowledge_edges = []
    prereq = []
    for e, _, _ in edges:
        a, b, kind = e["src"], e["dst"], e.get("type")
        edge_types[kind] += 1
        if a not in by_id or b not in by_id:
            bad_edges.append(e)
            continue
        if kind == "supports_ability" and a in ab_ids and b in kn_ids:
            direct[b].add(a)
        if kind == "has_child":
            descendants[a].add(b)
        if by_id[a].get("layer") == "L2" and b in kn_ids:
            module_knowledge_edges.append(e)
        if kind == "prerequisite_of" and e.get("status") == "verified":
            prereq.append((a, b))
    inherited = {k: set(v) for k, v in direct.items()}
    for parent, abilities in direct.items():
        todo, visited = list(descendants[parent]), set()
        while todo:
            child = todo.pop()
            if child in visited:
                continue
            visited.add(child)
            inherited.setdefault(child, set()).update(abilities)
            todo.extend(descendants[child])
    coverage = Counter()
    samples = []
    for r, file, line in questions:
        tagged = r.get("knowledge_node_ids", [])
        coverage["questions_with_direct_ability_path"] += any(direct.get(k) for k in tagged)
        coverage["questions_with_inherited_ability_path"] += any(inherited.get(k) for k in tagged)
        if not r.get("extra", {}).get("duplicate_of"):
            coverage["unique_questions"] += 1
            coverage["unique_with_knowledge"] += bool(tagged)
        if r.get("exam") == "NTCE":
            coverage["national_exam_questions"] += 1
            coverage["national_exam_with_knowledge"] += bool(tagged)
        if tagged and not any(inherited.get(k) for k in tagged) and len(samples) < 4:
            samples.append({"id": r["question_id"], "knowledge_ids": tagged, "file": file, "line": line})
    standard_nodes = [r for r, _, _ in nodes if r.get("type") == "standard"]
    outline = [read_json(path) for path in sorted((base / "outline").glob("*.json"))]
    return {"questions": profile, "ability_path_coverage": dict(coverage), "no_ability_path_samples": samples,
            "graph": {"nodes": len(nodes), "edges": len(edges), "layers": dict(Counter(r.get("layer") for r, _, _ in nodes)), "types": dict(Counter(r.get("type") for r, _, _ in nodes)), "edge_types": dict(edge_types), "dangling_edges_count": len(bad_edges), "dangling_edges": bad_edges[:8], "knowledge_nodes_with_direct_ability": len(direct), "knowledge_nodes_with_inherited_ability": len(inherited), "module_to_knowledge_edge_count": len(module_knowledge_edges), "prerequisite_dag": dag_check(prereq), "standard_nodes_verified": sum(r.get("verified") is True for r in standard_nodes), "standard_nodes_with_source_file_or_url": sum(any(present(r.get(k)) for k in ("source", "source_url", "origin_file", "url")) for r in standard_nodes)},
            "outline": {"files": len(outline), "verified": sum(r.get("verified") is True for r in outline), "knowledge_nodes": sum(len(r.get("nodes", [])) for r in outline)},
            "materials": len(materials), "manifest": read_json(base / "MANIFEST.json")}


def main():
    result = {"captured_at": datetime.now(timezone(timedelta(hours=8))).isoformat(), "scope": "四六级和教资主 JSONL、静态本体和图谱全量；不核定每题答案正确性，不运行产品功能", "cet": audit_cet(), "ntce": audit_ntce(), "json_errors": ERRORS}
    OUT.mkdir(exist_ok=True)
    (OUT / "知识库形式审查结果.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    code = Path(__file__).read_text(encoding="utf-8")
    code = code.replace("ROOT = Path(__file__).resolve().parents[1]", "ROOT = Path.cwd().parent if Path.cwd().name == '审查' else Path.cwd()")
    code = code.replace("OUT = Path(__file__).resolve().parent", "OUT = ROOT / '审查'")
    code = code[:code.index("def main():")]
    code += "result = {'cet': audit_cet(), 'ntce': audit_ntce(), 'json_errors': ERRORS}\nprint(json.dumps(result, ensure_ascii=False, indent=2))\n"
    notebook = {"nbformat": 4, "nbformat_minor": 5, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}, "language_info": {"name": "python", "version": "3"}}, "cells": [
        {"cell_type": "markdown", "metadata": {}, "id": "scope", "source": ["# 知识库形式审查\n", "全量只读检查。工作目录设为仓库根或审查目录。静态库无需预置用户掌握度，但应能支撑后续作答归因。答案存在不代表答案正确；source.verified 不等于专家审核。"]},
        {"cell_type": "code", "metadata": {}, "id": "audit", "execution_count": 1, "source": code.splitlines(keepends=True), "outputs": [{"output_type": "stream", "name": "stdout", "text": json.dumps({k: result[k] for k in ("cet", "ntce", "json_errors")}, ensure_ascii=False, indent=2).splitlines(keepends=True)}]}
    ]}
    (OUT / "知识库形式审查.ipynb").write_text(json.dumps(notebook, ensure_ascii=False, indent=1), encoding="utf-8")
    for library in ("cet", "ntce"):
        view = dict(result[library])
        view.pop("manifest", None)
        view.pop("manifest_stats", None)
        view["questions"] = {k: v for k, v in view["questions"].items() if k != "samples"}
        print(library, json.dumps(view, ensure_ascii=False, indent=2))
    print("JSON_ERRORS", json.dumps(ERRORS, ensure_ascii=False))


if __name__ == "__main__":
    main()
