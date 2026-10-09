# -*- coding: utf-8 -*-
"""为无解析题目生成规则版四段解析草稿（不调用任何付费 LLM）。

方法：规则 + 知识库已有节点（outline/*.json）+ 题目已有标签证据（extra.tagging_evidence）。
优先级：主观题（材料分析/简答/教学设计/论述/辨析/写作/活动设计/解答/诊断）优先，其次客观题。

诚实性原则（项目最高准则）：
- 只填能可靠生成的字段；无法可靠生成（如主观题的逐项错误思路、客观题“为什么某选项错”的学科理由）
  一律置 None，绝不编造占位文案。
- 不覆盖任何已有分析（含人工审核数据）；不触碰 difficulty / rubric 字段。
- 幂等：同输入两次运行逐字节一致（无随机、无时间戳、无哈希）。
- status/方法名明确标识为规则生成，而非模型生成；expert_verified 恒为 False。

用法：
  python kb_tools/ntce_analysis_fill.py            # 全量补缺
  python kb_tools/ntce_analysis_fill.py --dry-run  # 只统计不落盘
"""
import ast
import json
import sys
from pathlib import Path

from build_kb import OUT
from ntce_repair import read_rows, write_rows, manually_reviewed, reviewed_content
from ntce_io import atomic_write

METHOD = 'rule_kb_draft'
STATUS = 'rule_draft_pending_expert'

SUBJECTIVE_TYPES = {'简答', '材料分析', '教学设计', '论述', '辨析', '写作',
                    '活动设计', '解答', '诊断'}


def load_node_index():
    """构建 node_id -> {name, keywords(list)} 索引，关键词用于 trace_back / key_info。"""
    index = {}
    for path in sorted((OUT / 'outline').glob('*.json')):
        doc = json.loads(path.read_text(encoding='utf-8'))
        for node in doc.get('nodes', []):
            nid = node.get('node_id')
            if not nid:
                continue
            kw = node.get('keywords')
            if isinstance(kw, str):
                try:
                    kw = ast.literal_eval(kw)
                except (ValueError, SyntaxError):
                    kw = []
            if not isinstance(kw, list):
                kw = []
            index[nid] = {'name': node.get('name') or nid, 'keywords': [str(k) for k in kw if k]}
    return index


def parse_keywords(raw):
    if isinstance(raw, list):
        return [str(k) for k in raw if k]
    if isinstance(raw, str):
        try:
            val = json.loads(raw)
        except ValueError:
            try:
                val = ast.literal_eval(raw)
            except (ValueError, SyntaxError):
                return []
        return [str(k) for k in val if k] if isinstance(val, list) else []
    return []


def node_anchor(q, node_index):
    """返回 (节点名列表, 关键词集合)。优先 knowledge_node_ids，其次 tagging_evidence 的 stem_terms。"""
    names, kws = [], set()
    for nid in q.get('knowledge_node_ids') or []:
        node = node_index.get(nid)
        if node:
            names.append(node['name'])
            kws.update(node['keywords'])
    if not names:
        # 退路：标签证据里的 stem_terms 也可作为知识点线索（不为空）。
        for ev in q.get('extra', {}).get('tagging_evidence') or []:
            terms = ev.get('stem_terms') or []
            if terms:
                kws.update(terms)
    return names, kws


def option_summary(options):
    return '；'.join('%s%s' % (o.get('key', ''), (o.get('text') or '').strip()) for o in options)


def is_objective(q):
    """依据题型与是否存在选项判定客观题。"""
    if q['question_type'] in ('单选', '多选'):
        return True
    if q['question_type'] == '未标注':
        return bool(q['content'].get('options'))
    return False


def build_key_info(q, names, kws):
    c = q['content']
    stem = (c.get('stem') or '').strip()
    if is_objective(q):
        opts = option_summary(c.get('options') or [])
        ans = c.get('answer')
        ans_text = ('给定答案：' + str(ans)) if ans and str(ans).strip() and str(ans).strip() != '暂缺' else '本题无给定答案。'
        return '题干考查：%s。选项：%s。%s' % (stem, opts, ans_text)
    # 主观题
    anchor = ('（关联知识点：' + '、'.join(names) + '）') if names else ''
    return '题干要求：%s。%s' % (stem, anchor)


def build_trace_back(q, names, kws):
    if names:
        base = '关联知识点：' + '、'.join(names)
        if kws:
            base += '；关键词：' + '、'.join(sorted(kws)[:8])
        return base
    if kws:
        return '关联线索词：' + '、'.join(sorted(kws)[:8]) + '（未匹配到知识库节点，待专家补对齐）。'
    return None  # 无可靠依据，诚实留空


def build_explanation(q, names, kws):
    c = q['content']
    if is_objective(q):
        ans = c.get('answer')
        anchor = ('知识点【' + '、'.join(names) + '】') if names else '关联知识点'
        if ans and str(ans).strip() and str(ans).strip() != '暂缺':
            return ('本题给定答案为 %s；解析依据题干与%s（给定答案未经独立学科核实，待专家核定）。'
                    % (str(ans).strip(), anchor))
        return ('本题无给定答案，无法提供确定性解析；建议结合%s判断，答案待来源补全与专家核定。'
                % anchor)
    # 主观题：锚定节点+关键词，明确非官方答案
    anchor = ('知识点【' + '、'.join(names) + '】') if names else '相关学科/教育理论'
    kwhint = ('，要点可围绕：' + '、'.join(sorted(kws)[:8])) if kws else ''
    rubric = q.get('rubric') or {}
    npts = len(rubric.get('question_specific_points') or [])
    rubric_hint = ('；本题已生成 %d 条框架评分要点（框架推导，非官方答案）' % npts) if npts else ''
    return ('本题为主观题，需结合%s与题干情境展开作答。以下为作答要点方向（框架推导，'
            '非官方标准答案，待专家核定）%s%s。' % (anchor, kwhint, rubric_hint))


# 客观题规则能做到的、诚实的干扰项信号：绝对化表述识别。
# 这是纯文本语言学标记，不构成“某选项为何错”的学科判断；因此只作为提示，
# 并明确声明须结合知识点判定正误。无此信号的题 option_compare 诚实留 None。
ABSOLUTE_MARKERS = ['都', '全', '全部', '全都', '所有', '皆', '均', '必须', '一定',
                   '必然', '绝对', '唯一', '无不', '没有任何', '任何', '总是', '完全',
                   '无一', '统统', '尽数', '一概']


def build_option_compare(q):
    """主观题无选项 → None。

    客观题：规则无法可靠做“逐项学科干扰分析”，因此只输出可诚实断言的文本信号——
    识别含绝对化表述的选项（教资命题中这类表述常作干扰项，但正误仍须结合知识点判定）。
    无任何绝对化信号的题 → 返回 None（诚实留空，让缺失可见，待专家/模型补）。
    绝不输出“以……判断标准为准”这类假装完整的模板。
    """
    if not is_objective(q):
        return None
    c = q['content']
    opts = c.get('options') or []
    if not opts:
        return None
    ans = c.get('answer')
    ans_letters = set(str(ans).strip()) if (ans and str(ans).strip() and str(ans).strip() != '暂缺') else set()
    flagged = []
    for o in opts:
        key = o.get('key', '')
        text = (o.get('text') or '').strip()
        hits = sorted({m for m in ABSOLUTE_MARKERS if m in text})
        if hits:
            flagged.append('%s（含“%s”）' % (key, '、'.join(hits)))
    if not flagged:
        return None
    ans_text = ('给定答案为 %s。' % str(ans).strip()) if ans_letters else ''
    return (ans_text + '下列选项含绝对化表述：' + '；'.join(flagged) +
            '。教资命题中绝对化表述常作为干扰项出现，但正误须结合关联知识点判定，不能仅凭表述判断。')


def build_analysis(q):
    """返回四段解析 dict，或 None（无可生成内容时）。"""
    if q.get('analysis'):  # 已有结构化解析，跳过（含人工审核数据保护）
        return None
    if reviewed_content(q):  # 人工介入过的题目不动
        return None
    c = q['content']
    ans = c.get('answer')
    has_answer = bool(ans and str(ans).strip() and str(ans).strip() != '暂缺')
    names, kws = node_anchor(q, NODE_INDEX)

    # 主观题完全无锚点且无答案时，只给 key_info（题干本身），其余诚实留空也可；
    # 但至少 key_info 总可靠（题干存在），因此仍生成。
    key_info = build_key_info(q, names, kws)
    trace_back = build_trace_back(q, names, kws)
    explanation = build_explanation(q, names, kws)
    option_compare = build_option_compare(q)

    # 没有任何可生成字段（极端情况）则不落盘
    if not key_info and not trace_back and not explanation:
        return None

    return {
        'method': METHOD,
        'correct_answer': (str(ans).strip() if has_answer else None),
        'key_info': key_info or None,
        'option_compare': option_compare,
        'trace_back': trace_back,
        'explanation': explanation or None,
        'knowledge_node_ids': q.get('knowledge_node_ids') or [],
        'ability_ids': q.get('ability_ids') or [],
        'exam_requirement_ids': q.get('exam_requirement_ids') or [],
        'status': STATUS,
        'expert_verified': False,
        'source_note': '规则+知识库节点生成，未调用模型；非官方答案，待专家核定。',
    }


def refresh_option_compare(dry_run):
    """修复模式：对已有的 rule_kb_draft 客观题，用诚实版本重算 option_compare。

    - 含“判断标准为准”等模板文案的 → 改回诚实结果（可能变为 None）。
    - 原本为 None 但存在绝对化信号的 → 补上诚实提示。
    - 只动 method=='rule_kb_draft' 的题；不碰 originals、不碰 difficulty/rubric。
    返回统计。
    """
    NODE_INDEX_LOCAL = load_node_index()
    global NODE_INDEX
    NODE_INDEX = NODE_INDEX_LOCAL
    files = sorted((OUT / 'questions').glob('*/*/*.jsonl'))
    total = touched = set_null = set_honest = kept = 0
    obj_nonnull_after = 0
    for path in files:
        rows = read_rows(path)
        changed = False
        for q in rows:
            a = q.get('analysis')
            if not a or a.get('method') != METHOD:
                continue
            if not is_objective(q):
                continue
            total += 1
            new_oc = build_option_compare(q)
            old_oc = a.get('option_compare')
            if new_oc == old_oc:
                kept += 1
                if new_oc:
                    obj_nonnull_after += 1
                continue
            # 记录修复动作
            if old_oc and '判断标准为准' in str(old_oc):
                set_null += 1 if new_oc is None else 0
                set_honest += 1 if new_oc is not None else 0
            a['option_compare'] = new_oc
            changed = True
            touched += 1
            if new_oc:
                obj_nonnull_after += 1
        if changed and not dry_run:
            write_rows(path, rows)
    report = {
        'mode': 'refresh_option_compare',
        'dry_run': dry_run,
        'rule_objective_scanned': total,
        'touched': touched,
        'kept_unchanged': kept,
        'template_nulled': set_null,
        'template_replaced_with_honest': set_honest,
        'obj_option_compare_nonnull_after': obj_nonnull_after,
        'expert_verified': False,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main():
    global NODE_INDEX
    dry_run = '--dry-run' in sys.argv
    if '--refresh' in sys.argv:
        return refresh_option_compare(dry_run)
    NODE_INDEX = load_node_index()
    files = sorted((OUT / 'questions').glob('*/*/*.jsonl'))

    total = generated = skipped_existing = 0
    by_type = {}
    four_complete = 0  # key_info+option_compare+trace_back+explanation 全非空
    partial = 0        # 至少填了部分，但 option_compare 为空或其他空

    for path in files:
        rows = read_rows(path)
        changed = False
        for q in rows:
            total += 1
            t = q['question_type']
            if q.get('analysis') or reviewed_content(q):
                skipped_existing += 1
                continue
            ana = build_analysis(q)
            if ana is None:
                continue
            # 幂等保护：仅当确实无 analysis 时写入
            q['analysis'] = ana
            changed = True
            generated += 1
            stat = by_type.setdefault(t, {'gen': 0, 'complete': 0, 'partial': 0})
            stat['gen'] += 1
            if all(ana.get(f) for f in ('key_info', 'option_compare', 'trace_back', 'explanation')):
                stat['complete'] += 1
                four_complete += 1
            else:
                stat['partial'] += 1
                partial += 1
        if changed and not dry_run:
            write_rows(path, rows)

    report = {
        'method': METHOD,
        'dry_run': dry_run,
        'questions_total': total,
        'skipped_existing_or_expert': skipped_existing,
        'generated': generated,
        'four_segment_complete': four_complete,
        'partial_fill': partial,
        'by_type': by_type,
        'expert_verified': False,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == '__main__':
    main()
