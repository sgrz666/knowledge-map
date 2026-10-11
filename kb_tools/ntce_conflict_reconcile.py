"""回原卷核对 answer_status=source_conflict 的题目：只在证据唯一时落回答案，其余一律留在隔离态。

冲突题被隔离不是因为两份答案打架，而是抽取阶段无法确认题号与题型：题干没在原卷里定位到、
选项是 5 个（多选题一个字母不算答完）、或怀疑字母串到了别的题上。所以核对必须逐条把这三件事
问清楚，任何一条问不出唯一答案就拒绝落回，只登记证据。落回也只改答案与题号边界，审核签署
字段一律不动。

落回的题要连带把它自己的规则解析草稿和卡片重渲染：卡片是题记录的镜像，答案变了而卡片还写着
"本题无给定答案"，学习者读到的就是自相矛盾的一张卡。
"""
import argparse
import json
from collections import Counter

from build_kb import OUT, ROOT, load_text, parse_answers, classify_answer
from ntce_analysis_fill import (METHOD as RULE_METHOD, build_explanation, build_key_info,
                                build_option_compare, load_node_index, node_anchor)
from ntce_repair import (mix_risk_evidence, question_pending, read_rows, recorded_numbers,
                         reviewed_content, source_locator_number, sync_cards, unrecorded_neighbors,
                         write_rows)
from ntce_io import atomic_write

RECONCILED = 'source_conflict_answer_reconciled'
# 多选题卷面的选项是 A-E，单选题是 A-D；一个字母只在四选项题上才是完整答案。
SINGLE_CHOICE_OPTION_KEYS = ('A', 'B', 'C', 'D')


def is_reconciled(q):
    return any(change.get('kind') == RECONCILED for change in q['extra'].get('source_repairs', []))


def _refuse(record, reason):
    record['result'] = 'refused'
    record['refusal'] = reason
    return record


def reconcile_one(q, parsed, recorded_numbers=()):
    """返回一条核对证据；result=reconciled 表示可以落回，refused 表示证据不足。"""
    c, ex, rv = q['content'], q['extra'], q['review']
    source = next((f for f in q['source'].get('files', []) if f['role'] == 'answer_raw'), None)
    number = source_locator_number(q)
    candidate = (ex.get('answer_candidate') or {}).get('answer')
    option_keys = [o['key'] for o in (c.get('options') or [])]
    record = {'question_id': q['question_id'], 'level': q['level'], 'subject': q['subject'],
              'session': q['source'].get('session'), 'source_question_number': number,
              'stem_excerpt': (c.get('stem') or '')[:80], 'option_keys': option_keys,
              'preserved_candidate': candidate,
              'quarantine_reason': (ex.get('answer_candidate') or {}).get('reason'),
              'cross_question_risk': rv.get('cross_question_risk') or [],
              'answer_file': source['path'] if source else None,
              'expert_verified': False}
    if rv.get('cross_question_risk'):
        # 串题风险不是"答案可疑"那么轻：题面里吞了整段邻题文本，下一步是剪文本还是补收录，
        # 取决于被吞掉的邻题在本卷有没有独立记录。证据要把这个分岔答清楚，否则隔离只成一串码。
        evidence = mix_risk_evidence(q)
        record['content_boundary'] = {
            **evidence,
            'embedded_numbers_without_record': unrecorded_neighbors(evidence, recorded_numbers)}
    if not source:
        return _refuse(record, 'answer_file_missing')
    path = ROOT / source['path']
    if not path.exists():
        return _refuse(record, 'answer_file_absent')
    if number is None:
        # 题干在原卷里定位不到题号，字母就没有归属；paper_order 不能顶替，它正是当初错位的地方。
        return _refuse(record, 'stem_number_not_located_in_source')
    if tuple(option_keys) != SINGLE_CHOICE_OPTION_KEYS:
        return _refuse(record, 'not_a_four_option_single_choice')
    if rv.get('cross_question_risk'):
        return _refuse(record, 'cross_question_risk_open')
    raw_answer = parsed.get(number)
    status, letters = classify_answer(raw_answer)
    record['answer_key_raw'] = raw_answer
    if status != 'letter':
        return _refuse(record, 'answer_key_not_a_letter_at_located_number')
    if len(letters) != 1:
        # 原卷在这一题号上给了多个字母：这题是多选，一个字母不是完整答案。
        return _refuse(record, 'answer_key_offers_multiple_letters')
    if letters not in option_keys:
        return _refuse(record, 'answer_key_letter_outside_printed_options')
    record['answer_key_letter'] = letters
    if candidate is None:
        return _refuse(record, 'no_preserved_candidate_to_cross_check')
    if candidate != letters:
        # 两份独立抽取不一致：隔离是对的，不能挑一个落回。
        return _refuse(record, 'candidate_disagrees_with_answer_key')
    record['result'] = 'reconciled'
    record['basis'] = ('原卷题干唯一定位到题号 %s，答案键该题号为单字母 %s 且落在印刷选项内，'
                       '与隔离时保全的候选答案一致' % (number, letters))
    return record


def apply_repair(q, record):
    """落回答案并只放开题号边界；审核签署相关字段一律保持原样。"""
    c, rv = q['content'], q['review']
    before = {'answer': c.get('answer'), 'answer_status': c.get('answer_status'),
              'review_status': rv.get('status'),
              'answer_validation_status': rv.get('answer_validation_status'),
              'source_boundary_status': rv.get('source_boundary_status')}
    letters = record['answer_key_letter']
    c['answer'], c['answer_status'] = letters, 'letter_only'
    q['extra']['answer_provenance'] = 'letter'
    # 隔离态必须跟着答案可用性一起解除，否则快照会记成"有答案但仍隔离"的矛盾状态。
    if rv.get('status') == 'quarantined':
        rv['status'] = 'needs_fix'
    rv['answer_validation_status'] = 'not_expert_verified'
    rv['source_boundary_status'] = 'unique_text_boundary'
    rv['pending_reasons'] = question_pending(q)
    q['extra'].setdefault('source_repairs', []).append({
        'kind': RECONCILED, 'before': before,
        'after': {'answer': letters, 'answer_status': 'letter_only', 'review_status': rv['status'],
                  'answer_validation_status': rv['answer_validation_status'],
                  'source_boundary_status': rv['source_boundary_status']},
        'source_question_number': record['source_question_number'],
        'answer_file': record['answer_file'],
        'preserved_candidate': record['preserved_candidate'],
        'basis': record['basis'], 'expert_verified': False,
        'checked_by': rv.get('checked_by')})
    return q


def reconciled_entry(q):
    return next((e for e in q['extra'].get('source_repairs', []) if e.get('kind') == RECONCILED), None)


def refresh_rule_analysis(q, node_index):
    """落回答案后，规则草稿里"本题无给定答案"就成了假话，重算受答案影响的三段。

    解析文案的家在 ntce_analysis_fill，这里只调它自己的生成器，不新写学科判断、
    不覆盖人工审核内容；解析仍缺题眼与选项辨析这一事实由 pending 项继续说清楚。
    """
    analysis = q.get('analysis')
    if not analysis or analysis.get('method') != RULE_METHOD or reviewed_content(q):
        return None
    names, kws = node_anchor(q, node_index)
    answer = q['content'].get('answer')
    after = {'correct_answer': str(answer).strip() if answer else None,
             'key_info': build_key_info(q, names, kws),
             'explanation': build_explanation(q, names, kws),
             'option_compare': build_option_compare(q)}
    before = {field: analysis.get(field) for field in after}
    if before == after:
        return None
    analysis.update(after)
    return {'before': before, 'after': after}


def material_texts(needed):
    texts = {}
    for path in sorted((OUT / 'materials').glob('*/*/*.jsonl')):
        for item in read_rows(path):
            if item.get('material_id') in needed:
                texts[item['material_id']] = item.get('text')
    return texts


def run(scope=None, apply_changes=False):
    records, touched = [], []
    node_index = load_node_index() if apply_changes else {}
    total_cards = 0
    for qfile in sorted((OUT / 'questions').glob('*/*/*.jsonl')):
        level, subject = qfile.parent.parent.name, qfile.parent.name
        if scope and scope != f'{level}/{subject}':
            continue
        rows = read_rows(qfile)
        # 已落回的题也重新核对一遍：证据文件要能整批再生，只记当次新增会让重跑把历史批次抹掉。
        targets = [q for q in rows if q['content']['answer_status'] == 'source_conflict' or is_reconciled(q)]
        if not targets:
            continue
        # 同一张答案卷只解析一次，整批复用，避免逐题重读原卷。
        parsed_by_file = {}
        # 本卷已入库的题号：串题证据要用它判断被吞掉的邻题是有独立记录（剪文本是去重）
        # 还是根本没收录（剪文本会删掉库内唯一一份，必须走补收录）。
        paper_recorded = recorded_numbers(rows)
        restored = []
        changed = 0
        for q in targets:
            source = next((f for f in q['source'].get('files', []) if f['role'] == 'answer_raw'), None)
            path = ROOT / source['path'] if source and source.get('path') else None
            if path is not None and path not in parsed_by_file:
                parsed_by_file[path] = parse_answers(load_text(path)) if path.exists() else {}
            record = reconcile_one(q, parsed_by_file.get(path, {}), paper_recorded)
            record['scope'] = f'{level}/{subject}'
            records.append(record)
            if record['result'] == 'reconciled':
                record['already_applied'] = is_reconciled(q)
                if apply_changes:
                    if not record['already_applied']:
                        apply_repair(q, record)
                    entry = reconciled_entry(q)
                    analysis_diff = refresh_rule_analysis(q, node_index)
                    if analysis_diff:
                        entry['analysis'] = analysis_diff
                    restored.append(q)
                # 只出报告的那次运行也必须说清数据现状，否则摘要会被读成"这批一题都没落回"。
                record['restored_in_dataset'] = is_reconciled(q)
                changed += 1
        if apply_changes and changed:
            write_rows(qfile, rows)
            touched.append(f'{level}/{subject}')
        if restored:
            # 卡片是题记录的镜像：答案、审核状态、待补项任一处变了就得整张重渲染，不能手改头部。
            total_cards += sync_cards(
                restored, material_texts({q['material_id'] for q in restored if q.get('material_id')}))
    summary_scopes = sorted(set(touched))
    review = OUT / 'review'
    write_rows(review / 'answer_conflict_reconciliation.jsonl', records)
    summary = {'scope': scope or 'ALL',
               'applied': bool(apply_changes),
               'inspected': len(records),
               'by_result': dict(Counter(r['result'] for r in records)),
               'by_refusal': dict(Counter(r.get('refusal') for r in records if r['result'] == 'refused')),
               # applied=False 的只出报告运行同样会整批再生证据，这两个字段说明数据实况而不是本次模式。
               'restored_in_dataset': sum(1 for r in records if r.get('restored_in_dataset')),
               'still_quarantined': sum(1 for r in records if r['result'] == 'refused'),
               # 隔离题里有多少题卡的是"题面吞了邻题文本"而不是"答案算不出"，
               # 以及被吞掉的邻题里有多少在本卷压根没有独立记录——后者是收录缺口，不能靠剪文本解决。
               'refused_with_open_question_boundary': sum(
                   1 for r in records if r['result'] == 'refused' and r.get('content_boundary')),
               'boundary_numbers_without_record': sum(
                   len((r.get('content_boundary') or {}).get('embedded_numbers_without_record', ()))
                   for r in records if r['result'] == 'refused'),
               'scopes_touched': summary_scopes,
               'cards_rewritten_this_run': total_cards,
               'note': ('落回只承认"题干在原卷唯一定位到题号 + 答案键该题号是单字母且落在印刷选项内 + '
                        '与隔离时保全的候选一致"三件同时成立；题干定位不到、五选项多选、零选项缺图、'
                        '两份抽取不一致都留在隔离态。审核签署字段不因落回而提升。')}
    atomic_write(review / 'answer_conflict_reconciliation_summary.json',
                 json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', help='只核对一个学段/科目，例如 xiaoxue/jiaoyuxinlixue')
    parser.add_argument('--apply', action='store_true', help='落回已唯一核对的答案；默认只出证据不改数据')
    args = parser.parse_args()
    run(scope=args.scope, apply_changes=args.apply)
