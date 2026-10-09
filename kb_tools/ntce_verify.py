"""教资全库结构检查与真实双次复跑文件哈希幂等验证。质量待补项另列，不缩减分母。"""
import argparse
import hashlib
import json
from collections import Counter
from build_kb import ROOT, OUT
from ntce_repair import read_rows, load_official
from ntce_io import atomic_write


def snapshot():
    files = []
    for folder, pattern in [('questions', '*/*/*.jsonl'), ('materials', '*/*/*.jsonl'), ('outline', '*.json'),
                            ('cards', '*/*/*/*.md'), ('graph', '*.jsonl'), ('rubrics', '*.json'),
                            ('resources', '*.jsonl'), ('schemas', '*.json')]:
        files.extend((OUT / folder).glob(pattern))
    files.extend(OUT / name for name in ('MANIFEST.json', 'stats.json', 'graph/MANIFEST.json',
                                       'review/pending.jsonl', 'review/source_boundaries.jsonl',
                                       'review/question_type_source_audit.jsonl',
                                       'review/llm_tag_queue.jsonl', 'review/llm_analysis_failures.jsonl'))
    return {p.relative_to(OUT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(files)) if p.is_file()}


def verify(idempotence=False):
    stability = None
    if idempotence:
        from ntce_repair import repair
        repair()
        first = snapshot()
        repair()
        second = snapshot()
        changed = sorted(k for k in set(first) | set(second) if first.get(k) != second.get(k))
        stability = {'files_checked': len(first), 'changed_files': changed, 'passed': not changed,
                     'snapshot_sha256': hashlib.sha256(json.dumps(second, sort_keys=True).encode()).hexdigest()}
    questions = [q for p in sorted((OUT / 'questions').glob('*/*/*.jsonl')) for q in read_rows(p)]
    nodes = {n['id']: n for n in read_rows(OUT / 'graph/nodes.jsonl')}
    edges = read_rows(OUT / 'graph/edges.jsonl')
    _, requirements = load_official()
    official_ids = {r['requirement_id'] for r in requirements}
    retired = set(json.loads((ROOT / '权威资料/retired_requirement_ids.json').read_text(encoding='utf-8'))['retired'])
    errors = []
    if len(questions) != 14500 or len({q['question_id'] for q in questions}) != len(questions):
        errors.append('全库14500分母或题目ID唯一性失败')
    for q in questions:
        for field in ('knowledge_node_ids', 'ability_ids', 'exam_requirement_ids'):
            for nid in q[field]:
                if nid not in nodes:
                    errors.append({'question_id': q['question_id'], 'field': field, 'dangling': nid})
        for rid in q['exam_requirement_ids'] + q.get('rubric', {}).get('exam_requirement_ids', []):
            if rid not in official_ids or rid in retired:
                errors.append({'question_id': q['question_id'], 'invalid_requirement': rid})
        for f in q['source']['files']:
            if not (ROOT / f['path']).is_file():
                errors.append({'question_id': q['question_id'], 'missing_source_file': f['path']})
        if q['source']['verified'] and not q['source']['content_verification'].get('checked_by'):
            errors.append({'question_id': q['question_id'], 'unsupported_source_verification': True})
        if q['content']['answer_status'] == 'source_conflict' and q['content']['answer'] is not None:
            errors.append({'question_id': q['question_id'], 'conflicting_answer_still_active': True})
        if q['question_type'] not in ('单选', '多选') and q['content']['answer_status'] == 'letter_only':
            errors.append({'question_id': q['question_id'], 'nonobjective_letter_still_active': True})
        if q['content'].get('analysis') in ('缺', '略', 'ABCDE'):
            errors.append({'question_id': q['question_id'], 'placeholder_counted_as_analysis': True})
    for edge in edges:
        if edge['src'] not in nodes or edge['dst'] not in nodes:
            errors.append({'dangling_edge': edge})
        if edge['type'] == 'prerequisite_of' and edge.get('status') != 'verified' and edge.get('active_for_learning_path'):
            errors.append({'unreviewed_prerequisite_active': edge})
        if edge['type'] == 'prerequisite_of' and edge.get('status') == 'verified' and not edge.get('reviewed_by'):
            errors.append({'prerequisite_verified_without_reviewer': edge})
    if retired.intersection(nodes):
        errors.append({'retired_graph_nodes': sorted(retired.intersection(nodes))})
    l2 = {nid for nid, node in nodes.items() if node['layer'] == 'L2'}
    linked = {e['src'] for e in edges if e['src'] in l2 and nodes.get(e['dst'], {}).get('layer') == 'L4'}
    if l2 != linked:
        errors.append({'module_without_knowledge_path': sorted(l2 - linked)})
    pending = read_rows(OUT / 'review/pending.jsonl')
    result = {'questions': len(questions), 'structural_errors': len(errors), 'errors': errors,
              'module_paths': len(linked), 'pending_questions': len(pending),
              'pending_by_reason': dict(Counter(reason for p in pending for reason in p['reasons'])),
              'note': '结构完整不等于语义或内容专家验收通过；全库待补队列保留。'}
    if stability is not None:
        result['idempotence'] = stability
    atomic_write(OUT / 'review/verification.json', json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k not in ('errors', 'pending_by_reason')}, ensure_ascii=False, indent=2))
    if errors or (idempotence and not result['idempotence']['passed']):
        raise SystemExit(1)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check-idempotence', action='store_true')
    verify(parser.parse_args().check_idempotence)
