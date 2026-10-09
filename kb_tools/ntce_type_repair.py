"""按现存题干的唯一原文位置核题型，不把库内序号当原卷题号。"""
import re
from build_kb import TYPE_MAP, SECTION_WORDS, parse_question_text, norm_stem, NUM_CAND_SKIP_AFTER

ALIASES = {**TYPE_MAP, '单选题': '单选', '多选题': '多选', '选择题': '单选', '作文题': '写作'}
TITLE_PATTERN = '|'.join(re.escape(title) for title in sorted(ALIASES, key=len, reverse=True))
HEAD_PATTERN = re.compile('(?P<title>' + TITLE_PATTERN + r')(?=\s*[（(。:：.]|\s*本大题)')
CHOICE_TASK = re.compile(r'[（(]\s*[)）]|下列|以下|选项|哪(?:个|种|项)|正确的是|属于|最恰当|不正确|选择')
COMPLETE_OPTIONS = re.compile(r'A\s*[、.．].*?B\s*[、.．].*?C\s*[、.．].*?D\s*[、.．]', re.S)


def exact_text(text):
    # 来源等价比对只消除宽度和空白；NFKC 会误把数学上下标转为普通数字。
    folded = ''.join(chr(ord(ch) - 0xFEE0) if 0xFF01 <= ord(ch) <= 0xFF5E
                     else ' ' if ch == '\u3000' else ch for ch in text)
    return re.sub(r'\s+', '', folded)


def source_sections(raw):
    heads = []
    for match in HEAD_PATTERN.finditer(raw):
        before = raw[max(0, match.start() - 5):match.start()]
        following = raw[match.end():match.end() + 140]
        declared = bool(re.search(r'本大题|共\s*\d+\s*小?题|每\s*小?题|\d+\s*题|下列各题|根据题目要求', following))
        ordinal = re.search(r'[一二三四五六七八九十]+\s*[、.．:：]\s*$', before)
        positioned = match.start() < 8 or bool(ordinal)
        if declared or positioned:
            heading_start = match.start() - len(before) + ordinal.start() if ordinal else match.start()
            heads.append({'title': match['title'], 'question_type': ALIASES[match['title']],
                          'start': heading_start, 'end': match.end(), 'excerpt': raw[heading_start:match.end() + 100]})
    return heads


def current_source_position(raw, stem):
    needle = stem[:40].strip()
    if len(needle) < 12 or raw.count(needle) != 1:
        return None
    start = raw.index(needle)
    prefix_start = max(0, start - 15)
    prefix = raw[prefix_start:start]
    number = re.search(r'(?<!\d)(\d{1,2})\s*[、.．]?\s*$', prefix)
    if not number:
        return {'start': start, 'number': None}
    number_start = prefix_start + number.start()
    if number_start and raw[number_start - 1] in '第图表式（(':
        return {'start': start, 'number': None}
    return {'start': start, 'number': int(number[1]), 'number_start': number_start}


def choice_evidence(q, raw, sections):
    position = current_source_position(raw, q['content']['stem'])
    if not position:
        return None, {'status': 'current_stem_source_position_unresolved'}
    previous = [head for head in sections if head['start'] < position['start']]
    section = previous[-1] if previous else None
    report = {'status': 'source_position_found_type_pending', 'source_file': q['source']['origin_file'],
              'locator': position, 'section': section, 'expert_verified': False}
    if not section or section['question_type'] not in ('单选', '多选') or position['number'] is None:
        return None, report
    start, number = position['start'], position['number']
    ends = set()
    for head in re.finditer(r'(?<![\d.．])%d\s*[、.．]?(?=[\u4e00-\u9fa5《“（(])' % (number + 1), raw[start + 12:start + 3000]):
        end = start + 12 + head.start()
        if end and raw[end - 1] in '第图表式（(':
            continue
        after = raw[start + 12 + head.end():]
        if NUM_CAND_SKIP_AFTER.match(after) or re.match(r'^(米|倍|度|厘米|毫米|秒)', after):
            continue
        ends.add(end)
    following_sections = [head['start'] for head in sections if start < head['start'] <= start + 3000]
    if following_sections:
        ends.add(min(following_sections))
    candidates = []
    for end in sorted(ends):
        fragment = raw[start:end]
        parsed = parse_question_text(0, fragment)
        if [o['key'] for o in parsed['options']] != list('ABCD') or any(not o['text'].strip() for o in parsed['options']):
            continue
        if len(COMPLETE_OPTIONS.findall(fragment)) != 1 or not CHOICE_TASK.search(parsed['stem']):
            continue
        current = exact_text(q['content']['stem'])
        actual = exact_text(parsed['stem'])
        if not (current == actual or (current.startswith(actual) and COMPLETE_OPTIONS.search(q['content']['stem']))):
            continue
        candidates.append((parsed, end))
    # 多个数字边界不能凭“取最短”猜测。已有完整四项可逐项精确核对，
    # 只保留唯一与当前题干和四个选项完全一致的原文边界。
    current_options = q['content']['options']
    option_exact = False
    if [o['key'] for o in current_options] == list('ABCD') and all(o['text'].strip() for o in current_options):
        exact = [(parsed, end) for parsed, end in candidates
                 if all(exact_text(actual['text']) == exact_text(current['text']) for actual, current in zip(parsed['options'], current_options))]
        if len(exact) == 1:
            candidates = exact
            option_exact = True
    if len(candidates) == 1:
        parsed, end = candidates[0]
        report.update({'status': 'verified_choice_task_and_section', 'source_question_number': number,
                       'end': end, 'raw_option_keys': list('ABCD'), 'current_options_exact_match': option_exact})
        return parsed, report
    if candidates:
        report.update({'status': 'source_choice_boundary_ambiguous', 'candidate_count': len(candidates)})
    return None, report


def repair_type(q, raw, sections, manually_reviewed=False):
    if manually_reviewed:
        return {'question_id': q['question_id'], 'status': 'manual_review_protected'}
    parsed, report = choice_evidence(q, raw, sections)
    report['question_id'] = q['question_id']
    report['current_question_type'] = q['question_type']
    if parsed:
        expected = report['section']['question_type']
        if q['question_type'] != expected:
            q['extra'].setdefault('type_history', []).append({'before': {'question_type': q['question_type'], 'section': q.get('section')},
                'after': {'question_type': expected, 'section': report['section']['title']},
                'method': 'unique_current_stem_full_ABCD_choice_task_and_source_section', 'source_evidence': report.copy(), 'expert_verified': False})
            q['question_type'] = expected
            q['section'] = report['section']['title']
            q['content']['stem'], q['content']['options'] = parsed['stem'], parsed['options']
            if q['review'].get('tagger') == 'llm-v2':
                q['review']['tagger'] = None
                q['extra'].get('llm_tag_result', {})['input_validation_status'] = 'source_type_or_context_changed_pending_rework'
            report['type_repaired'] = True
            if q.get('material_id') == q['question_id'] + '.material.recovered':
                q['material_id'] = None
                q['source']['files'] = [source for source in q['source']['files'] if source['role'] != 'material_raw']
        old_boundary = q['extra'].get('source_boundary_verification')
        if old_boundary and old_boundary.get('status') == 'ambiguous_boundary_candidates':
            history = {'before': old_boundary.copy(), 'method': 'current_full_stem_options_and_source_section',
                       'resolved_locator': report['locator'], 'resolved_end': report['end'], 'expert_verified': False}
            if history not in q['extra'].get('boundary_history', []):
                q['extra'].setdefault('boundary_history', []).append(history)
        q['extra']['source_question_number'] = report['source_question_number']
        q['extra']['source_boundary_verification'] = {'status': 'unique_text_boundary', 'start': report['locator']['start'],
            'end': report['end'], 'source_question_number': report['source_question_number'], 'expert_verified': False}
    elif q['question_type'] not in ('单选', '多选') and q['content']['answer_status'] == 'letter_only':
        candidate = {'answer': q['content']['answer'], 'original_status': 'letter_only',
            'reason': 'nonobjective_letter_without_verified_choice; source_number_or_type_unresolved',
            'source_files': [source for source in q['source']['files'] if source['role'] == 'answer_raw'],
            'type_source_evidence': report.copy(), 'expert_verified': False}
        q['extra']['answer_candidate'] = candidate
        q['extra'].setdefault('source_repairs', []).append({'kind': 'nonobjective_letter_quarantined',
            'before': {'answer': q['content']['answer'], 'answer_status': 'letter_only'}, 'evidence': report.copy(), 'expert_verified': False})
        q['content']['answer'], q['content']['answer_status'] = None, 'source_conflict'
        report['answer_quarantined'] = True
    q['review']['type_source_verification'] = {key: value for key, value in report.items() if key not in ('type_repaired', 'answer_quarantined', 'current_question_type', 'question_id')}
    return report
