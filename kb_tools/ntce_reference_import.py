"""精确题干哈希、真实来源区间和引用哈希校验后采纳独立参考草稿。"""
import copy
import hashlib
import json
from collections import Counter
from build_kb import ROOT, OUT, load_text
from ntce_repair import read_rows, write_rows, reviewed_content, practice_rubric
from ntce_io import atomic_write

THEORY_TERMS = {
    'preschool.individual-differences': ('个体差异', '尺子'),
    'preschool.whole-development': ('整体', '领域'),
    'preschool.active-learning': ('探究', '操作'),
    'preschool.concrete-mathematics': ('数', '操作'),
    'preschool.avoid-premature-primary-training': ('超前教育', '强化训练'),
    'preschool.game-development': ('游戏', '学习'),
    'preschool.social-learning': ('交往', '规则'),
    'preschool.supportive-climate': ('关心', '温暖'),
    'preschool.direct-experience': ('直接感知', '亲身体验'),
    'preschool.life-relevance': ('生活', '经验'),
    'preschool.block-play': ('积木', '建构'),
    'preschool-planting': ('观察', '探究'),
}


def validate_references(draft):
    contexts = []
    for source in draft['source_files']:
        path = ROOT / source['path']
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != source['sha256']:
            return 'reference_source_hash_mismatch'
        lines = path.read_text(encoding='utf-8').split('\n')
        locator = source['locator']
        if not 1 <= locator['line_start'] <= locator['line_end'] <= len(lines):
            return 'reference_source_locator_invalid'
        context = '\n'.join(lines[locator['line_start'] - 1:locator['line_end']])
        if locator.get('line_convention') != 'physical_LF' or hashlib.sha256(context.encode('utf-8')).hexdigest() != locator.get('context_sha256'):
            return 'reference_context_hash_mismatch'
        contexts.append(context)
    combined = '\n'.join(contexts)
    if any(term not in combined for term in THEORY_TERMS.get(draft['draft_id'], ())):
        return 'reference_principle_terms_missing'
    return None


def refresh_imported_references(q, draft):
    """只迁移本次独立草稿的引用，正文与生成当时记录保持。"""
    prior_files = copy.deepcopy(q['analysis'].get('source_files', []))
    q['source']['files'] = [source for source in q['source']['files'] if source not in prior_files]
    for source in draft['source_files']:
        if source not in q['source']['files']:
            q['source']['files'].append(copy.deepcopy(source))
    q['analysis']['source_files'] = copy.deepcopy(draft['source_files'])
    q['analysis']['input_evidence_files'] = copy.deepcopy(draft['source_files'])
    q['analysis']['source_locator_validation'] = {'file_hashes_and_context_hashes_match': True,
        'line_convention': 'physical_LF', 'principle_terms_present': list(THEORY_TERMS.get(draft['draft_id'], ())),
        'expert_content_verified': False}
    for point in q.get('rubric', {}).get('question_specific_points', []):
        if isinstance(point, dict) and point.get('point_id', '').startswith(draft['draft_id'] + '.'):
            point['source_files'] = copy.deepcopy(draft['source_files'])


def import_drafts(refresh_locators=False):
    drafts = read_rows(ROOT / '补充资料/教资参考解答/reference_drafts.jsonl')
    batches = {path: read_rows(path) for path in sorted((OUT / 'questions').glob('*/*/*.jsonl'))}
    index = {q['question_id']: q for records in batches.values() for q in records}
    outcomes, source_cache = [], {}
    for draft in drafts:
        q = index.get(draft['question_id'])
        reason = None
        if not q:
            reason = 'question_missing'
        elif reviewed_content(q):
            reason = 'manual_review_protected'
        elif refresh_locators and q.get('analysis', {}).get('draft_id') == draft['draft_id'] \
                and q['content']['answer_status'] == 'reference_only' \
                and q['extra'].get('answer_provenance') == 'original_reference_draft_pending_expert':
            reason = validate_references(draft)
            if reason is None:
                refresh_imported_references(q, draft)
                outcomes.append({'question_id': q['question_id'], 'status': 'references_refreshed', 'draft_id': draft['draft_id'], 'expert_verified': False})
                continue
        elif q['content'].get('answer') or q['content'].get('analysis') or q.get('analysis'):
            reason = 'existing_content_preserved'
        elif hashlib.sha256(q['content']['stem'].encode('utf-8')).hexdigest() != draft['expected_stem_sha256']:
            reason = 'stem_hash_changed'
        elif q['review'].get('cross_question_risk'):
            reason = 'source_boundary_risk'
        else:
            origin = ROOT / q['source']['origin_file']
            if origin not in source_cache:
                source_cache[origin] = load_text(origin) if origin.exists() else ''
            stem = q['content']['stem']
            raw = source_cache[origin]
            if raw.count(stem) != 1:
                reason = 'full_stem_source_interval_not_unique'
            else:
                reason = validate_references(draft)
        if reason:
            outcomes.append({'question_id': draft['question_id'], 'status': 'skipped', 'reason': reason})
            continue
        before = copy.deepcopy(q['content'])
        q['content']['answer'] = draft['answer']
        q['content']['answer_status'] = 'reference_only'
        q['extra']['answer_provenance'] = 'original_reference_draft_pending_expert'
        q['content']['analysis'] = draft['analysis']['explanation']
        q['analysis'] = copy.deepcopy(draft['analysis'])
        q['analysis'].update({'correct_answer': draft['answer'], 'official_answer': False,
                             'source_files': copy.deepcopy(draft['source_files']), 'draft_id': draft['draft_id']})
        rubric = practice_rubric(q)
        if not rubric.get('checked_by') and not rubric.get('question_specific_points'):
            rubric['question_specific_points'] = [{'point_id': draft['draft_id'] + '.p%d' % (i + 1), 'expected': point,
                    'source_files': copy.deepcopy(draft['source_files']), 'official_score': None} for i, point in enumerate(draft['scoring_points'])]
            rubric['score_note'] = draft['score_note']
        q['source']['files'].extend(copy.deepcopy(draft['source_files']))
        q['extra'].setdefault('source_repairs', []).append({'kind': 'original_reference_draft_import', 'before': before,
                'draft_id': draft['draft_id'], 'draft_file': '补充资料/教资参考解答/reference_drafts.jsonl',
                'expert_verified': False, 'source_stem_locator': {'decoded_csv_character_start': raw.index(stem), 'decoded_csv_character_end': raw.index(stem) + len(stem)}})
        outcomes.append({'question_id': q['question_id'], 'status': 'accepted_draft', 'draft_id': draft['draft_id'], 'expert_verified': False})
    for path, records in batches.items():
        write_rows(path, records)
    write_rows(OUT / 'review/reference_draft_import.jsonl', outcomes)
    result = {'candidates': len(drafts), 'by_status': dict(Counter(record['status'] for record in outcomes)),
              'skip_reasons': dict(Counter(record.get('reason') for record in outcomes if record['status'] == 'skipped')),
              'expert_verified': False}
    atomic_write(OUT / 'review/reference_draft_import_summary.json', json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == '__main__':
    import sys
    import_drafts('--refresh-locators' in sys.argv)
