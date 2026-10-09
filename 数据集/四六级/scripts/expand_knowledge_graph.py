"""扩展知识图谱：挂载万级考纲词汇实体与真题例句关联，补充四六级与教资认知诊断关系边。"""
import json
import re
import sys
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[3]
CET_KB = ROOT / "数据集" / "四六级"
NTCE_KB = ROOT / "数据集" / "教资"
sys.path.insert(0, str(CET_KB / "scripts"))
from cet_common import jsonl_dumps, load_jsonl


def build_vocabulary_entities():
    # 1. 加载真题阅读文章作为例句语料
    passages = load_jsonl(CET_KB / "passages" / "reading.jsonl")
    sentence_corpus = []
    for p in passages:
        pid = p.get("resource_id")
        text = p.get("text", "")
        # 按句号、感叹号、问号切分英文句子
        sents = re.split(r"(?<=[.!?])\s+", text)
        for s in sents:
            s_clean = s.strip()
            if 15 <= len(s_clean) <= 250:
                sentence_corpus.append({"passage_id": pid, "sentence": s_clean})
                
    # 2. 读取 4,424 四级词汇与 5,518 六级词汇
    c4_words = load_jsonl(CET_KB / "vocabulary" / "words_cet4.jsonl")
    c6_words = load_jsonl(CET_KB / "vocabulary" / "words_cet6.jsonl")
    
    entities = []
    # 预先构建常见词倒排索引加速查找例句
    word_to_sentences = defaultdict(list)
    for item in sentence_corpus[:2000]:  # 采样真实句子索引
        tokens = set(re.findall(r"\b[a-zA-Z]+\b", item["sentence"].lower()))
        for token in tokens:
            if len(word_to_sentences[token]) < 3:
                word_to_sentences[token].append({
                    "passage_id": item["passage_id"],
                    "sentence": item["sentence"]
                })
                
    total_words = c4_words + c6_words
    for w in total_words:
        ex = w.get("extra", {})
        word_text = ex.get("word") or ""
        token = word_text.lower().strip()
        
        matched_sentences = word_to_sentences.get(token, [])
        
        entity = {
            "entity_id": w.get("resource_id"),
            "word": word_text,
            "phonetic": ex.get("phonetic"),
            "level": ex.get("level"),
            "tier": ex.get("tier"),
            "pos_meaning": ex.get("pos_meaning"),
            "knowledge_node_ids": w.get("knowledge_node_ids", ["cet4.lang.vocab"]),
            "ability_ids": w.get("ability_ids", ["ab.cet4.lang.vocab"]),
            "exam_requirement_ids": w.get("exam_requirement_ids", []),
            "real_exam_examples": matched_sentences,
            "source": w.get("source")
        }
        entities.append(entity)
        
    out_file = CET_KB / "ontology" / "vocabulary_entities.jsonl"
    out_file.write_text("\n".join(jsonl_dumps(e) for e in entities) + "\n", encoding="utf-8")
    print(f"考纲词汇实体库生成完成：共挂载 {len(entities)} 词汇实体（四级 {len(c4_words)} + 六级 {len(c6_words)}）-> {out_file.name}")
    return len(entities)


def expand_cet_edges():
    edges_file = CET_KB / "ontology" / "edges.jsonl"
    existing_edges = load_jsonl(edges_file)
    existing_keys = {(e.get("src"), e.get("rel"), e.get("dst")) for e in existing_edges}
    
    standards = json.loads((CET_KB / "ontology" / "standards.json").read_text(encoding="utf-8"))
    kn = load_jsonl(CET_KB / "ontology" / "knowledge_nodes.jsonl")
    ab = load_jsonl(CET_KB / "ontology" / "ability_nodes.jsonl")
    valid_ids = {r["id"] for r in kn} | {r["id"] for r in ab} | {r["id"] for r in standards["standards"] + standards["素养目标"]}
    
    # 认知诊断先修关系边 (形成严格DAG)
    prereq_pairs = [
        ("cet4.lang.vocab", "cet4.read.locate"),
        ("cet4.read.locate", "cet4.read.synonym"),
        ("cet4.read.synonym", "cet4.read.detail"),
        ("cet4.read.detail", "cet4.read.infer"),
        ("cet4.read.detail", "cet4.read.gist"),
        ("cet4.read.gist", "cet4.read.attitude"),
        ("cet4.lang.grammar", "cet4.read.discourse"),
        ("cet4.lang.vocab", "cet4.listen.detail"),
        ("cet4.listen.detail", "cet4.listen.infer"),
        ("cet4.listen.detail", "cet4.listen.gist"),
        ("cet4.lang.grammar", "cet4.write.accuracy"),
        ("cet4.write.structure", "cet4.write.coherence"),
        ("cet4.write.coherence", "cet4.write.argument"),
        ("cet4.lang.vocab", "cet4.trans.topic"),
        ("cet4.lang.grammar", "cet4.trans.syntax"),
        # 四级到六级递进
        ("cet4.read.detail", "cet6.read.detail"),
        ("cet4.listen.detail", "cet6.listen.detail"),
        ("cet4.write.structure", "cet6.write.structure"),
        ("cet4.trans.syntax", "cet6.trans.syntax"),
        # 六级内部
        ("cet6.lang.vocab", "cet6.read.locate"),
        ("cet6.read.locate", "cet6.read.synonym"),
        ("cet6.read.synonym", "cet6.read.detail"),
        ("cet6.read.detail", "cet6.read.infer"),
        ("cet6.read.detail", "cet6.read.gist"),
        ("cet6.read.gist", "cet6.read.attitude"),
        ("cet6.lang.grammar", "cet6.read.discourse"),
        ("cet6.lang.vocab", "cet6.listen.detail"),
        ("cet6.listen.detail", "cet6.listen.infer"),
        ("cet6.listen.detail", "cet6.listen.gist"),
        ("cet6.lang.grammar", "cet6.write.accuracy"),
        ("cet6.write.structure", "cet6.write.coherence"),
        ("cet6.write.coherence", "cet6.write.argument"),
        ("cet6.lang.vocab", "cet6.trans.topic"),
        ("cet6.lang.grammar", "cet6.trans.syntax"),
    ]
    
    # 高频混淆关系边
    confused_pairs = [
        ("cet4.read.detail", "cet4.read.infer", "事实细节定位与过度推理主观臆断混淆"),
        ("cet4.read.locate", "cet4.read.synonym", "机械字面原词匹配与同义改写替换混淆"),
        ("cet4.read.gist", "cet4.read.detail", "主旨大意判断误选局部细节事实"),
        ("cet4.listen.detail", "cet4.listen.infer", "听力原词发音重合干扰与深层含义推断混淆"),
        ("cet4.listen.gist", "cet4.listen.detail", "首句局部细节误当全篇核心主旨"),
        ("cet6.read.detail", "cet6.read.infer", "六级复杂细节定位与隐含主旨推断混淆"),
        ("cet6.read.locate", "cet6.read.synonym", "字面匹配与深度近义转述混淆"),
        ("cet6.read.gist", "cet6.read.detail", "篇章宏观立意误选次要论据"),
        ("cet6.listen.detail", "cet6.listen.infer", "讲座细节信息与演讲者真实观点混淆"),
        ("cet6.listen.gist", "cet6.listen.detail", "引入案例细节误选为讲座主旨"),
    ]
    
    # 易错概念诱发关系边
    misconception_pairs = [
        ("cet4.read.locate", "cet4.read.infer", "字面匹配思维定势诱发推断题断章取义"),
        ("cet4.listen.detail", "cet4.listen.gist", "瞬时关键词捕捉定势导致主旨概括以偏概全"),
        ("cet6.read.locate", "cet6.read.infer", "机械定位定势诱发同义改写识别失败"),
        ("cet6.listen.detail", "cet6.listen.gist", "细节注意过载导致篇章宏观逻辑断层"),
    ]
    
    new_edges = list(existing_edges)
    added_count = 0
    
    for src, dst in prereq_pairs:
        if src in valid_ids and dst in valid_ids:
            key = (src, "prerequisite", dst)
            if key not in existing_keys:
                new_edges.append({
                    "src": src,
                    "rel": "prerequisite",
                    "dst": dst,
                    "review_status": "proposed_pending_subject_expert",
                    "active": False,
                    "reviewed_by": None,
                    "description": f"{src} 是 {dst} 的必要先修前置技能"
                })
                existing_keys.add(key)
                added_count += 1
                
    for src, dst, note in confused_pairs:
        if src in valid_ids and dst in valid_ids:
            key = (src, "confused_with", dst)
            if key not in existing_keys:
                new_edges.append({
                    "src": src,
                    "rel": "confused_with",
                    "dst": dst,
                    "review_status": "proposed_pending_subject_expert",
                    "active": False,
                    "reviewed_by": None,
                    "cognitive_trap": note
                })
                existing_keys.add(key)
                added_count += 1
                
    for src, dst, desc in misconception_pairs:
        if src in valid_ids and dst in valid_ids:
            key = (src, "misconception_lead_to", dst)
            if key not in existing_keys:
                new_edges.append({
                    "src": src,
                    "rel": "misconception_lead_to",
                    "dst": dst,
                    "review_status": "proposed_pending_subject_expert",
                    "active": False,
                    "reviewed_by": None,
                    "error_pattern": desc
                })
                existing_keys.add(key)
                added_count += 1
                
    edges_file.write_text("\n".join(jsonl_dumps(e) for e in new_edges) + "\n", encoding="utf-8")
    print(f"四六级图谱扩展完成：新增 {added_count} 条认知诊断关系边，总边数 {len(new_edges)}")
    return added_count


def expand_ntce_edges():
    edges_file = NTCE_KB / "graph" / "edges.jsonl"
    nodes_file = NTCE_KB / "graph" / "nodes.jsonl"
    existing_edges = [json.loads(l) for l in edges_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    existing_keys = {(e.get("src"), e.get("type"), e.get("dst")) for e in existing_edges}
    
    nodes = [json.loads(l) for l in nodes_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    valid_ids = {n["id"] for n in nodes}
    
    prereq_pairs = [
        ("ntce.xiaoxue.jiaoxue.m1.k01", "ntce.xiaoxue.jiaoxue.m1.k02"),
        ("ntce.xiaoxue.jiaoxue.m2.k1", "ntce.xiaoxue.jiaoxue.m2.k2"),
        ("ntce.xiaoxue.jiaoxue.m2.k2", "ntce.xiaoxue.jiaoxue.m5.k01"),
        ("ntce.xiaoxue.jiaoxue.m5.k01", "ntce.xiaoxue.jiaoxue.m5.k02"),
        ("ntce.xiaoxue.jiaoxue.m5.k02", "ntce.xiaoxue.jiaoxue.m6.k01"),
        ("ntce.xiaoxue.jiaoxue.m6.k01", "ntce.xiaoxue.jiaoxue.m7.k01"),
        ("ntce.xiaoxue.jiaoxue.m2.k3", "ntce.xiaoxue.jiaoxue.m3.k01"),
        ("ntce.zhongxue.jiaoyuzhishi.m1.k01", "ntce.zhongxue.jiaoyuzhishi.m2.k01"),
        ("ntce.zhongxue.jiaoyuzhishi.m2.k01", "ntce.zhongxue.jiaoyuzhishi.m3.k01"),
        ("ntce.zhongxue.jiaoyuzhishi.m3.k01", "ntce.zhongxue.jiaoyuzhishi.m4.k01"),
        ("ntce.zhongxue.jiaoyuzhishi.m4.k01", "ntce.zhongxue.jiaoyuzhishi.m5.k01"),
        ("ntce.youer.baojiao.m1.k01", "ntce.youer.baojiao.m2.k1"),
        ("ntce.youer.baojiao.m2.k1", "ntce.youer.baojiao.m3.k01"),
    ]
    
    confused_pairs = [
        ("ntce.xiaoxue.jiaoxue.m2.k1", "ntce.xiaoxue.jiaoxue.m2.k2", "身心发展规律特征与学习心理理论混淆"),
        ("ntce.xiaoxue.jiaoxue.m2.k3", "ntce.xiaoxue.jiaoxue.m2.k4", "德育品德形成阶段与心理健康辅导原则混淆"),
        ("ntce.xiaoxue.jiaoxue.m5.k01", "ntce.xiaoxue.jiaoxue.m5.k02", "三维教学目标设定与教学活动环节混淆"),
        ("ntce.xiaoxue.jiaoxue.m6.k01", "ntce.xiaoxue.jiaoxue.m7.k01", "课堂教学实施过程与学习评价反思维度混淆"),
        ("ntce.zhongxue.jiaoyuzhishi.m3.k01", "ntce.zhongxue.jiaoyuzhishi.m4.k01", "中学生感知记忆注意规律与思维问题解决过程混淆"),
        ("ntce.zhongxue.jiaoyuzhishi.m5.k01", "ntce.zhongxue.jiaoyuzhishi.m6.k01", "中学德育原则途径与心理辅导方法混淆"),
        ("ntce.youer.baojiao.m2.k1", "ntce.youer.baojiao.m3.k01", "幼儿心理发展特征与幼儿园一日保育活动常规混淆"),
    ]
    
    misconception_pairs = [
        ("ntce.xiaoxue.jiaoxue.m2.k2", "ntce.xiaoxue.jiaoxue.m5.k01", "将行为主义负强化错误归因导致教学评价设计偏差"),
        ("ntce.xiaoxue.jiaoxue.m2.k3", "ntce.xiaoxue.jiaoxue.m3.k01", "忽视道德认知发展阶段导致班级纪律管理简单粗暴"),
        ("ntce.zhongxue.jiaoyuzhishi.m4.k01", "ntce.zhongxue.jiaoyuzhishi.m5.k01", "混淆品德心理结构中的道德意志与道德情感"),
    ]
    
    new_edges = list(existing_edges)
    added_count = 0
    
    for src, dst in prereq_pairs:
        if src in valid_ids and dst in valid_ids:
            key = (src, "prerequisite", dst)
            if key not in existing_keys:
                new_edges.append({
                    "src": src,
                    "dst": dst,
                    "type": "prerequisite",
                    "rel": "prerequisite_of",
                    "rationale": f"{src} 构成 {dst} 的必要学科先修知识支撑",
                    "review_status": "proposed_pending_subject_expert",
                    "status": "proposed_pending_review",
                    "active": False,
                    "reviewed_by": None
                })
                existing_keys.add(key)
                added_count += 1
                
    for src, dst, note in confused_pairs:
        if src in valid_ids and dst in valid_ids:
            key = (src, "confused_with", dst)
            if key not in existing_keys:
                new_edges.append({
                    "src": src,
                    "dst": dst,
                    "type": "confused_with",
                    "note": note,
                    "active": False,
                    "review_status": "proposed_pending_subject_expert",
                    "reviewed_by": None
                })
                existing_keys.add(key)
                added_count += 1
                
    for src, dst, pattern in misconception_pairs:
        if src in valid_ids and dst in valid_ids:
            key = (src, "misconception_lead_to", dst)
            if key not in existing_keys:
                new_edges.append({
                    "src": src,
                    "dst": dst,
                    "type": "misconception_lead_to",
                    "pattern": pattern,
                    "active": False,
                    "review_status": "proposed_pending_subject_expert",
                    "reviewed_by": None
                })
                existing_keys.add(key)
                added_count += 1
                
    edges_file.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in new_edges) + "\n", encoding="utf-8")
    print(f"教资图谱扩展完成：新增 {added_count} 条认知诊断关系边，总边数 {len(new_edges)}")
    return added_count


if __name__ == "__main__":
    build_vocabulary_entities()
    expand_cet_edges()
    expand_ntce_edges()
