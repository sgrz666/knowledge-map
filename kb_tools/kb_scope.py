# -*- coding: utf-8 -*-
"""按 catalog.json 的 exam_scope 判定每条权威标准归属哪套考试库。

两库导出层共用这一份判定：此前教资按 `standard_id.startswith('ntce.')` 硬筛、四六级只取
"被题目引用到的条款"，导致 CSE 3,886 条描述语与 law/teacher/regulation 1,004 条法规条款
从来没进过 L0 图层。归属只认 exam_scope，不再认 id 前缀。
"""
NTCE_MARKS = ("NTCE", "幼儿园", "小学", "中学")
CET_MARKS = ("CET", "英语能力")
# 仅用于纠错留痕、本身不是考试规范的条目（如 GB/T 41671 误编号纠正证据）不参与分层。
NON_NORMATIVE_KINDS = ("correction_evidence",)


def library_of(source):
    """返回 'ntce' / 'cet' / None（None = 非规范留痕条目，两库都不入图）。"""
    if str(source.get("kind")) in NON_NORMATIVE_KINDS:
        return None
    scope = [str(item) for item in (source.get("exam_scope") or [])]
    hits_ntce = any(any(mark in text for mark in NTCE_MARKS) for text in scope)
    hits_cet = any(any(mark in text for mark in CET_MARKS) for text in scope)
    sid = source.get("standard_id")
    if hits_ntce and hits_cet:
        raise ValueError("标准 %s 的 exam_scope 同时命中两库，需先在 catalog.json 拆分为两条标准" % sid)
    if not hits_ntce and not hits_cet:
        raise ValueError("标准 %s 的 exam_scope=%r 无法归类，请补充 exam_scope 或标 kind=correction_evidence" % (sid, scope))
    return "ntce" if hits_ntce else "cet"


def classify(catalog_sources):
    """{library: [standard_id]}，用于测试断言 67 条来源全部有归属。"""
    buckets = {"ntce": [], "cet": [], None: []}
    for source in catalog_sources:
        sid = source.get("standard_id")
        if not sid:
            raise ValueError("catalog.json 存在无 standard_id 的来源条目")
        buckets[library_of(source)].append(sid)
    return buckets


def select(catalog_sources, requirement_rows, library):
    """取该库的全部标准与其条款（L0 全量入图，不按是否被题目引用裁剪）。"""
    standards = {}
    for source in catalog_sources:
        sid = source.get("standard_id")
        if sid and library_of(source) == library:
            standards[sid] = source
    requirements = {}
    for row in requirement_rows:
        rid = row.get("requirement_id")
        if rid and row.get("standard_id") in standards:
            requirements[rid] = row
    return standards, requirements
