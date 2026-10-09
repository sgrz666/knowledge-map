# -*- coding: utf-8 -*-
"""本体 v2：按《应试考证功能设计与技术支撑》§3.2/§3.4 层级标准构建
L0 国家标准/考试大纲 → L0.5 素养目标 → L1 能力维度 → L2 知识点(含先修关系) → 题型 → 试题
产出: ontology/standards.json  ability_nodes.jsonl  knowledge_nodes.jsonl  edges.jsonl
幂等可复跑。
"""
import json, sys
from pathlib import Path
from cet_common import merge_jsonl, fill_missing

sys.stdout.reconfigure(encoding="utf-8")
KB = Path(__file__).resolve().parents[1]
ONT = KB / "ontology"

def dump_jsonl(recs, name):
    merge_jsonl(ONT / name,recs)
    print(f"{name}: {len(recs)}")

def dump_json(obj, name):
    old=json.loads((ONT/name).read_text('utf-8')) if (ONT/name).exists() else {}
    (ONT / name).write_text(json.dumps(fill_missing(old,obj), ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{name}: ok")

# ---------- L0 国家标准 / 考试大纲 ----------
standards = {
    "standards": [
        {"id": "std.cet.syllabus", "name": "全国大学英语四、六级考试大纲", "type": "考试大纲",
         "authority": "教育部教育考试院", "约束": ["L1 考试结构", "L2 模块与题型", "分值与时间"]},
        {"id": "std.cse", "name": "中国英语能力等级量表 (CSE)", "type": "国家标准",
         "authority": "教育部、国家语言文字工作委员会", "historical_code": "GF0018-2018", "约束": ["能力等级描述", "CET/CSE 对接须单独核验"]},
        {"id": "std.cet.wordlist", "name": "CET 词汇表", "type": "考试大纲附件",
         "authority": "教育部教育考试院", "约束": ["词汇库 tier=outline 的范围"]},
    ],
    "素养目标": [
        {"id": "comp.languse", "name": "语言运用素养", "anchored_by": ["std.cet.syllabus", "std.cse"],
         "说明": "在一定语境中运用英语获取、理解、表达信息的能力"},
        {"id": "comp.learning", "name": "自主学习与备考素养", "anchored_by": ["std.cse"],
         "说明": "自我诊断、策略调整与持续改进的能力（支撑个性化路径）"},
    ],
}
dump_json(standards, "standards.json")

# ---------- L1 能力维度（§3.4 四六级示例） ----------
# id 约定: ab.{module}.{ability}; abilities 挂知识点; 顶层挂素养
AB = []
def ab(id_, name, module, parent, supports, desc, cse):
    AB.append({"id": id_, "name": name, "module": module, "parent": parent,
               "supports": supports, "knowledge_node_ids": [], "cse_level": None, "description": desc})

for lv in ("cet4", "cet6"):
    e = "CET-4" if lv == "cet4" else "CET-6"
    cse = 4 if lv == "cet4" else 5
    # 听力能力
    ab(f"ab.{lv}.listen.gist", "听力主旨把握", "听力理解", "comp.languse", ["comp.languse"], "把握口头语篇的中心思想与说话意图", cse)
    ab(f"ab.{lv}.listen.detail", "听力细节捕捉", "听力理解", "comp.languse", ["comp.languse"], "捕捉时间、数字、人物行为等具体信息", cse)
    ab(f"ab.{lv}.listen.infer", "听力推理判断", "听力理解", "comp.languse", ["comp.languse"], "依据语音语调与上下文推断态度与隐含意义", cse)
    # 阅读能力（§3.4 示例结构）
    ab(f"ab.{lv}.read.locate", "信息定位能力", "阅读理解", "comp.languse", ["comp.languse"], "根据题干关键词快速定位原文对应信息", cse)
    ab(f"ab.{lv}.read.synonym", "同义替换识别", "阅读理解", f"ab.{lv}.read.locate", [f"ab.{lv}.read.locate"], "识别题干与原文之间的同义/近义改写", cse)
    ab(f"ab.{lv}.read.gist", "主旨概括能力", "阅读理解", "comp.languse", ["comp.languse"], "概括段落/全文主旨，把握作者观点态度", cse)
    ab(f"ab.{lv}.read.infer", "推理判断能力", "阅读理解", "comp.languse", ["comp.languse"], "基于原文信息进行引申推理并排除过度推断", cse)
    ab(f"ab.{lv}.read.discourse", "语篇结构分析能力", "阅读理解", "comp.languse", ["comp.languse"], "分析句间逻辑衔接与段落展开方式", cse)
    # 写作能力
    ab(f"ab.{lv}.write.organize", "篇章组织能力", "写作", "comp.languse", ["comp.languse"], "开头-论证-结尾结构与段落展开", cse)
    ab(f"ab.{lv}.write.coherence", "衔接连贯能力", "写作", "comp.languse", ["comp.languse"], "使用连接词与指代保持语篇连贯", cse)
    ab(f"ab.{lv}.write.langacc", "语言准确性能力", "写作", "comp.languse", ["comp.languse"], "语法、搭配与拼写正确性", cse)
    # 翻译能力
    ab(f"ab.{lv}.trans.lex", "翻译词汇运用", "翻译", "comp.languse", ["comp.languse"], "主题词汇与固定表达的准确选用", cse)
    ab(f"ab.{lv}.trans.syntax", "长难句转换能力", "翻译", "comp.languse", ["comp.languse"], "定语从句、被动、无主句等句法转换", cse)
    # 语言基础
    ab(f"ab.{lv}.lang.vocab", "词汇运用能力", "词汇语法", "comp.languse", ["comp.languse"], "大纲词汇的认知与语境运用", cse)

# ---------- L2 知识点（含细分子节点 + 先修关系） ----------
KN = []
def kn(id_, name, exam, module, parent, prereq, cse, desc, qtypes, abilities):
    KN.append({"id": id_, "name": name, "exam": exam, "module": module, "parent": parent,
               "prereq": [], "candidate_prereq":prereq,"prerequisite_review":{"status":"proposed_pending_subject_expert","active":False,"method":"curriculum_concept_dependency_proposal"}, "cse_level": None, "description": desc, "question_types": qtypes,
               "ability_ids": abilities,
               "text": f"【{exam}{module}知识点】{name}：{desc}"})

for lv in ("cet4", "cet6"):
    e = "CET-4" if lv == "cet4" else "CET-6"
    pre = "cet4" if lv == "cet4" else "cet6"
    cse = 4 if lv == "cet4" else 5
    q = ("短篇新闻", "长对话", "听力篇章", "讲座/讲话") if lv == "cet4" else ("长对话", "听力篇章", "讲座/讲话")
    al = lambda a: [f"ab.{lv}.{a}"]
    # 听力
    kn(f"{lv}.listen", "听力理解", e, "听力理解", "root", [], cse, "理解口头英语材料的主旨、要点与细节", list(q), [])
    kn(f"{lv}.listen.gist", "听力主旨大意", e, "听力理解", f"{lv}.listen", [f"{lv}.listen"], cse, "把握对话/篇章中心思想与说话意图", list(q), al("listen.gist"))
    kn(f"{lv}.listen.detail", "听力细节理解", e, "听力理解", f"{lv}.listen", [f"{lv}.listen"], cse, "捕捉时间、数字、地点、人物行为等具体信息", list(q), al("listen.detail"))
    kn(f"{lv}.listen.infer", "听力推理判断", e, "听力理解", f"{lv}.listen", [f"{lv}.listen.detail"], cse, "推断说话人态度与隐含意义", list(q), al("listen.infer"))
    # 阅读
    kn(f"{lv}.read", "阅读理解", e, "阅读理解", "root", [], cse, "理解书面语篇的主旨、细节与逻辑结构", ["选词填空", "长篇阅读", "仔细阅读"], [])
    kn(f"{lv}.read.locate", "信息定位", e, "阅读理解", f"{lv}.read", [f"{lv}.read"], cse, "根据题干关键词快速定位原文对应句", ["仔细阅读", "长篇阅读"], al("read.locate"))
    kn(f"{lv}.read.synonym", "同义替换识别", e, "阅读理解", f"{lv}.read.locate", [f"{lv}.read.locate"], cse, "识别题干与原文之间的同义/近义改写", ["仔细阅读", "长篇阅读"], al("read.synonym"))
    kn(f"{lv}.read.detail", "细节理解", e, "阅读理解", f"{lv}.read.locate", [f"{lv}.read.locate"], cse, "理解定位句的具体事实与细节信息", ["仔细阅读"], al("read.locate"))
    kn(f"{lv}.read.infer", "推理判断", e, "阅读理解", f"{lv}.read.locate", [f"{lv}.read.locate"], cse, "基于原文信息进行引申推理，排除过度推断", ["仔细阅读"], al("read.infer"))
    kn(f"{lv}.read.gist", "主旨概括", e, "阅读理解", f"{lv}.read", [], cse, "概括段落/全文主旨，把握作者观点态度", ["仔细阅读", "长篇阅读"], al("read.gist"))
    kn(f"{lv}.read.attitude", "观点态度", e, "阅读理解", f"{lv}.read.gist", [f"{lv}.read.gist"], cse, "识别作者或文中人物对某事物的态度倾向", ["仔细阅读"], al("read.gist"))
    kn(f"{lv}.read.cloze", "语境词汇运用", e, "阅读理解", f"{lv}.read", [f"{lv}.read"], cse, "结合语法与语义从备选词中选词填空", ["选词填空"], al("read.discourse"))
    kn(f"{lv}.read.discourse", "语篇结构分析", e, "阅读理解", f"{lv}.read", [f"{lv}.read"], cse, "分析句间逻辑衔接与段落展开方式", ["长篇阅读", "选词填空"], al("read.discourse"))
    # 写作
    kn(f"{lv}.write", "写作", e, "写作", "root", [], cse, "在规定时间内完成指定话题短文写作", ["短文写作"], [])
    kn(f"{lv}.write.structure", "篇章组织", e, "写作", f"{lv}.write", [f"{lv}.write"], cse, "开头-论证-结尾三段式结构与段落展开", ["短文写作"], al("write.organize"))
    kn(f"{lv}.write.argument", "议论说理", e, "写作", f"{lv}.write.structure", [f"{lv}.write.structure"], cse, "观点表达、论据支撑与让步反驳", ["短文写作"], al("write.coherence"))
    kn(f"{lv}.write.coherence", "衔接与连贯", e, "写作", f"{lv}.write.structure", [f"{lv}.write.structure"], cse, "使用连接词与指代保持语篇连贯", ["短文写作"], al("write.coherence"))
    kn(f"{lv}.write.accuracy", "语言准确性", e, "写作", f"{lv}.write", [], cse, "语法、搭配与拼写正确性", ["短文写作"], al("write.langacc"))
    # 翻译
    kn(f"{lv}.trans", "段落汉译英", e, "翻译", "root", [], cse, "将140-200字中文段落译成英文", ["段落汉译英"], [])
    kn(f"{lv}.trans.topic", "话题词汇运用", e, "翻译", f"{lv}.trans", [f"{lv}.trans"], cse, "中国文化、科技、经济等话题核心表达", ["段落汉译英"], al("trans.lex"))
    kn(f"{lv}.trans.syntax", "长难句处理", e, "翻译", f"{lv}.trans", [f"{lv}.trans"], cse, "定语从句、被动语态、无主句、分词结构转换", ["段落汉译英"], al("trans.syntax"))
    # 语言基础
    kn(f"{lv}.lang", "语言基础知识", e, "词汇语法", "root", [], cse, "词汇量、核心语法与固定搭配", [], [])
    kn(f"{lv}.lang.vocab", "核心词汇", e, "词汇语法", f"{lv}.lang", [], cse, "大纲词汇的认知与运用", [], al("lang.vocab"))
    kn(f"{lv}.lang.grammar", "核心语法", e, "词汇语法", f"{lv}.lang", [], cse, "时态语态、三大从句、非谓语、虚拟语气", [], al("lang.vocab"))

dump_jsonl(KN, "knowledge_nodes.jsonl")
dump_jsonl(AB, "ability_nodes.jsonl")

# ---------- 图谱边 ----------
edges = []
for a in AB:
    if a["parent"] in ("comp.languse", "comp.learning"):
        edges.append({"src": a["id"], "dst": a["parent"], "rel": "supports", "说明": "能力支撑素养"})
    elif a["parent"]:
        edges.append({"src": a["id"], "dst": a["parent"], "rel": "sub_ability", "说明": "能力细分"})
for k in KN:
    for abid in k["ability_ids"]:
        edges.append({"src": k["id"], "dst": abid, "rel": "exemplifies", "说明": "知识点体现能力"})
    for pre in k["candidate_prereq"]:
        edges.append({"src": pre, "dst": k["id"], "rel": "prerequisite_candidate", "proposed_rel":"prereq_of","active":False,"review_status":"proposed_pending_subject_expert","说明": "待专家核定的先修候选"})
for c in standards["素养目标"]:
    for sid in c["anchored_by"]:
        edges.append({"src": c["id"], "dst": sid, "rel": "anchored_by", "说明": "素养由标准约束"})
dump_jsonl(edges, "edges.jsonl")

# knowledge_nodes 里回填能力→知识点索引
for a in AB:
    a["knowledge_node_ids"] = [k["id"] for k in KN if a["id"] in k["ability_ids"]]
dump_jsonl(AB, "ability_nodes.jsonl")
print("ontology v2 done")
