"""在全量教资库上修复语义挂接、来源、答案结构与同步产物。

python kb_tools/ntce_repair.py [--skip-outline]
保留所有题目和历史答案；不生成虚构的标准答案或专家审核。
"""
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from build_kb import ROOT, OUT, load_text, norm_stem, parse_question_text, render_card, parse_answers, classify_answer, ANSWER_CONTRACT, NUM_CAND_SKIP_AFTER
from ntce_ontology import ABILITY_NAMES, select_nodes, matches
from ntce_io import atomic_write


def read_rows(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.open(encoding='utf-8') if line.strip()]


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows)
    if '\u2028' in text or '\u2029' in text:
        text = text.replace('\u2028', '\\n').replace('\u2029', '\\n')
    atomic_write(path, text)


def load_official():
    catalog_path = ROOT / '权威资料/catalog.json'
    catalog = json.loads(catalog_path.read_text(encoding='utf-8')) if catalog_path.exists() else {}
    sources = {r['standard_id']: r for r in catalog.get('sources', []) if 'standard_id' in r}
    requirements = read_rows(ROOT / '权威资料/requirements.jsonl')
    return sources, requirements


def manually_reviewed(component):
    """人工身份/证据存在时，自动化只补缺省字段，不重写审核决定。"""
    return bool(component and (component.get('checked_by') or component.get('expert_verified')))


# 难度标定方法标识：由 ntce_difficulty.py 写入，refresh_tags 必须兜底保留。
# 缺了这些键，下游无法区分 heuristic_* 估算与真实 IRT 校准。
DIFFICULTY_TRACE_KEYS = ('method', 'calibration', 'version', 'features')


def reviewed_content(q):
    return manually_reviewed(q.get('review')) or q.get('review', {}).get('tagger') == 'expert'


SUBJECT_CN = {'yuwen': '语文', 'shuxue': '数学', 'yingyu': '英语', 'zhengzhi': '政治',
              'lishi': '历史', 'dili': '地理', 'wuli': '物理', 'huaxue': '化学', 'shengwu': '生物',
              'meishu': '美术', 'yinyue': '音乐', 'tiyu': '体育', 'xinxi': '信息',
              'zonghe': '综合素质', 'baojiao': '保教', 'jiaoxue': '教育教学', 'jiaoyuzhishi': '教育知识', 'mianshi': '面试'}
LEVEL_CN = {'youer': '幼儿', 'xiaoxue': '小学', 'zhongxue': '中学', 'chuzhong': '初', 'gaozhong': '高', 'zhongxiaoxue': '中小学'}


def same_scope(requirement, level, subject):
    if not requirement.get('standard_id', '').startswith('ntce.'):
        return False
    sj, lv = str(requirement.get('subject', '')), str(requirement.get('level', ''))
    subject_ok = sj == subject or SUBJECT_CN.get(subject, '#') in sj or (subject == 'zhengzhi' and any(alias in sj for alias in ('思想品德', '道德与法治')))
    level_ok = lv == level or LEVEL_CN.get(level, '#') in lv
    if subject == 'mianshi':
        subject_ok = 'interview' in requirement.get('standard_id', '') or subject_ok
        if level == 'zhongxiaoxue':
            level_ok = level_ok or any(x in lv for x in ('小学', '中学', 'xiaoxue', 'zhongxue'))
    return subject_ok and level_ok


def align_outline(doc, requirements, sources):
    scoped = [r for r in requirements if same_scope(r, doc['level'], doc['subject']) and len(r.get('content', '')) >= 12]
    by_id = {r['requirement_id']: r for r in scoped}
    for node in doc['nodes']:
        if manually_reviewed(node):
            # 人工对齐仅在官方条目仍有效时保留；失效引用留证据供人工迁移。
            previous = node.get('exam_requirement_ids', [])
            retired = [rid for rid in previous if rid not in by_id]
            if retired:
                node.setdefault('retired_alignment_evidence', []).extend(rid for rid in retired if rid not in node.get('retired_alignment_evidence', []))
                node['exam_requirement_ids'] = [rid for rid in previous if rid in by_id]
                node['mapping_status'] = 'manual_mapping_requires_source_migration'
            continue
        if not node.get('assessable'):
            node['mapping_status'] = 'grouping_only'
            continue
        scored = []
        for requirement in scoped:
            text = requirement.get('content', '') + ' ' + requirement.get('title', '')
            terms = matches(text, node.get('keywords', []))
            score = sum(min(len(term), 10) for term in terms)
            # 不把“课程”“教学”等宽泛词独立视作原文中的细概念证据。
            if any(len(term) >= 3 or re.search('[a-zA-Z]', term) for term in terms):
                scored.append((score, requirement['requirement_id'], terms))
        scored.sort(key=lambda x: (-x[0], x[1]))
        # 大纲对地理/英语等只列专业知识范围，细点是条款的可评估拆解。
        # 题仍挂大气分层/语音等细点，派生关系保存原文与解释。
        derived = False
        if doc['subject'] == 'mianshi':
            suffix = node['parent'].rsplit('.', 1)[-1] if node.get('parent') else node['node_id'].rsplit('.', 1)[-1]
            dimensions = {'m1': ['思维品质', '言语表达'], 'm2': ['心理素质', '思维品质'],
                          'm3': ['交流沟通'], 'm4': ['交流沟通', '思维品质'], 'm5': ['职业认知'],
                          'm6': ['教学设计', '教学实施', '教学评价', '活动设计']}[suffix]
            direct = [(5, r['requirement_id'], []) for r in scoped
                      if any(dimension in r.get('module', '') for dimension in dimensions)]
            if direct:
                scored = direct
                derived = True
        if not scored and '.s1.' in node['node_id']:
            anchors = [r for r in scoped if not re.search(r'教学|课程|设计|评价|目标|实施|要求|题型|结构', r.get('module', ''))
                       and re.search(r'基本概念|基础知识|专业知识|知识体系|学科知识|基本知识|语言知识', r.get('content', ''))]
            if anchors:
                scored = [(1, anchors[0]['requirement_id'], [])]
                derived = True
        node['exam_requirement_ids'] = [rid for _, rid, _ in scored[:3]]
        node['alignment_evidence'] = [{'requirement_id': rid, 'matched_terms': terms,
                                       'method': 'domain_requirement_operationalization' if derived else 'official_text_terms',
                                       'rationale': ('将官方能力/知识范围拆解为可评估任务：' + node['name']) if derived else None,
                                       'expert_verified': False}
                                      for _, rid, terms in scored[:3]]
        node['mapping_status'] = ('derived_from_official_scope_pending_review' if derived else 'automatic_alignment_pending_review') if scored else 'pending_official_alignment'
        node['sources'] = [{'standard_id': by_id[rid]['standard_id'],
                           'path': sources.get(by_id[rid]['standard_id'], {}).get('local_path'),
                           'source_url': sources.get(by_id[rid]['standard_id'], {}).get('source_url'),
                           'locator': by_id[rid].get('locator')} for _, rid, _ in scored[:3]]
    doc['official_standard_ids'] = sorted({r['standard_id'] for r in scoped})
    doc['source_verified'] = bool(scoped)
    if not manually_reviewed(doc):
        doc['verified'] = False
    doc['note'] = '官方原文自动词项对齐与学科细点拆解；所有映射待教研审核。分组节点assessable=false不参与题级打标。'


def question_metrics(questions):
    return {'questions': len(questions), 'knowledge_mapped': sum(bool(q.get('knowledge_node_ids')) for q in questions),
            'ability_mapped': sum(bool(q.get('ability_ids')) for q in questions),
            'requirement_mapped': sum(bool(q.get('exam_requirement_ids')) for q in questions),
            'answers_nonempty': sum(bool(q['content'].get('answer')) for q in questions),
            'analysis_nonempty': sum(bool(q['content'].get('analysis')) for q in questions),
            'structured_analysis_nonempty': sum(bool((q.get('analysis') or {}).get('explanation')) for q in questions),
            'answer_status': dict(Counter(q['content']['answer_status'] for q in questions)),
            'answer_not_in_options': sum(len(q['content']['options']) >= 2 and q['content']['answer_status'] == 'letter_only'
                 and len(q['content']['answer'] or '') == 1 and q['content']['answer'] not in [o['key'] for o in q['content']['options']] for q in questions),
            'choice_options_under_four': sum(q['question_type'] in ('单选', '多选') and len(q['content']['options']) < 4 for q in questions)}


def evidence_source(q, file_cache):
    source = q['source']
    path = ROOT / source['origin_file']
    if path not in file_cache:
        file_cache[path] = (load_text(path), hashlib.sha256(path.read_bytes()).hexdigest()) if path.exists() else ('', None)
    text, checksum = file_cache[path]
    apath = path.parent.with_name(path.parent.name.replace('真题', '真题答案')) / (path.stem + '（答案）.csv')
    if not apath.exists():
        apath = apath.with_name(path.stem + ' （答案）.csv')
    files = [{'path': source['origin_file'], 'role': 'question_raw',
              'locator': {'paper_order': q['extra']['paper_order'], 'alignment_status': 'pending'}, 'sha256': checksum}]
    if apath.exists():
        files.append({'path': apath.relative_to(ROOT).as_posix(), 'role': 'answer_raw',
                      'locator': {'alignment_status': 'pending_question_number_check'}})
    needle = norm_stem(q['content']['stem'])[:40]
    literal_aligned = len(needle) >= 12 and needle in norm_stem(text)
    for f in source.get('files', []):
        if isinstance(f.get('path'), str) and f['path'].startswith('教资KB/'):
            f['path'] = '数据集/教资/' + f['path'][len('教资KB/'):]
    if q.get('analysis') and isinstance(q['analysis'].get('source_files'), list):
        for f in q['analysis']['source_files']:
            if isinstance(f.get('path'), str) and f['path'].startswith('教资KB/'):
                f['path'] = '数据集/教资/' + f['path'][len('教资KB/'):]
    generated_keys = {(f['path'], f['role']) for f in files}
    prior_files = {(f.get('path'), f.get('role')): f for f in source.get('files', [])}
    for f in files:
        old = prior_files.get((f['path'], f['role']), {})
        f.update({k: v for k, v in old.items() if k not in ('path', 'role', 'sha256')})
    files.extend(f for f in source.get('files', []) if (f.get('path'), f.get('role')) not in generated_keys)
    source['files'] = files
    source['verified'] = bool(source.get('content_verification', {}).get('verified') and source.get('content_verification', {}).get('checked_by'))
    source['raw_file_verification'] = {'status': 'file_exists' if checksum else 'missing',
                                      'sha256': checksum,
                                      'content_alignment': 'stem_excerpt_found' if literal_aligned else 'pending'}
    source.setdefault('content_verification', {'status': 'not_expert_reviewed', 'verified': False, 'checked_by': None})
    copyright = source.setdefault('copyright', {})
    for key, value in {'authorization_status': 'unknown', 'holder': None, 'use_scope': None, 'expires_at': None}.items():
        copyright.setdefault(key, value)
    # use_scope 已由 ntce_copyright_scope.py 按项目实际用途写入（科研用途非商业化）。
    # 旧记录里存在 use_scope: null 的占位，setdefault 不会覆盖它，会让已声明的
    # 使用范围在复算后丢失。此处仅补缺，不覆盖已确定的值。
    if copyright.get('use_scope') is None:
        copyright['use_scope'] = 'research_non_commercial'
    source['source_classification'] = '考生回忆版' if '回忆' in path.name else '题库声称真题'
    return text


def recover_options(q, raw_text='', section_heads=None):
    c = q['content']
    if reviewed_content(q):
        return False
    if q['question_type'] not in ('单选', '多选'):
        return False
    proof = q.get('review', {}).get('type_source_verification', {})
    if raw_text and proof.get('status') == 'verified_choice_task_and_section' and proof.get('current_options_exact_match'):
        from ntce_type_repair import exact_text
        current_source = parse_question_text(0, raw_text[proof['locator']['start']:proof['end']])
        if ([o['key'] for o in current_source['options']] == [o['key'] for o in c['options']] == list('ABCD')
                and exact_text(current_source['stem']) == exact_text(c['stem'])
                and all(exact_text(actual['text']) == exact_text(current['text']) for actual, current in zip(current_source['options'], c['options']))):
            return False  # 已逐项证实当前完整正文；历史 before 不能覆盖更强的唯一边界。
    original = next((change['before'] for change in q['extra'].get('source_repairs', []) if change['kind'] == 'option_marker_recovery'), c)
    body = original['stem'] + '\n' + '\n'.join(o['key'] + '、' + o['text'] for o in original['options'])
    recovered = parse_question_text(0, body)
    method = 'complete_ABCD_sequence_in_existing_raw_text'
    # 只在题干长片段唯一出现，且可恢复真实题号边界时扩展原文。
    needle = original['stem'][:32].strip()
    if raw_text and len(needle) >= 15 and raw_text.count(needle) == 1:
        start = raw_text.index(needle)
        number = re.search(r'(?<!\d)(\d{1,2})\s*[、.．]?\s*$', raw_text[max(0, start - 10):start])
        if number:
            source_number = int(number.group(1))
            search_start = start + len(needle)
            tail = raw_text[search_start:start + 2500]
            viable_by_end = {}
            for head in re.finditer(r'(?<![\d.．])%d\s*[、.．]?(?=[\u4e00-\u9fa5《“（])' % (source_number + 1), tail):
                after = tail[head.end():]
                if NUM_CAND_SKIP_AFTER.match(after) or re.match(r'^(米|倍|度|厘米|毫米|秒)', after):
                    continue
                end = search_start + head.start()
                following_sections = [section['start'] for section in (section_heads or []) if start < section['start'] < end]
                if following_sections:
                    end = min(following_sections)
                expanded = parse_question_text(0, raw_text[start:end])
                if len(expanded['options']) == 4 and all(o['text'].strip() for o in expanded['options']):
                    viable_by_end[end] = (expanded, end)
            viable = list(viable_by_end.values())
            if len(viable) == 1:
                recovered, end = viable[0]
                method = 'unique_stem_and_next_source_question_number'
                q['extra']['source_question_number'] = source_number
                q['extra']['source_boundary_verification'] = {'status': 'unique_text_boundary', 'start': start, 'end': end, 'source_question_number': source_number, 'expert_verified': False}
            elif len(viable) > 1:
                q['extra']['source_boundary_verification'] = {'status': 'ambiguous_boundary_candidates', 'candidate_count': len(viable), 'expert_verified': False}
    options = recovered['options']
    if len(options) != 4 or any(not o['text'].strip() for o in options):
        return False
    if options == c['options'] and recovered['stem'] == c['stem']:
        return False
    # 未改动的完整选项无需重新切割，防止题干中的字母提及造成移动。
    if method == 'complete_ABCD_sequence_in_existing_raw_text' and len(c['options']) == 4 and all(o['text'].strip() for o in c['options']) and not any(re.search(r'[A-D]\s*[、．.]', o['text']) for o in c['options']):
        return False
    q['extra'].setdefault('source_repairs', []).append({'kind': 'option_marker_recovery',
        'method': method,
        'before': {'stem': c['stem'], 'options': c['options']}, 'expert_verified': False})
    c['stem'], c['options'] = recovered['stem'], options
    if q['review'].get('tagger') == 'llm-v2':
        q['review']['tagger'] = None
        q['extra'].pop('llm_tag_signature', None)
    return True


def structured_source_analysis(q):
    text = q['content'].get('analysis')
    if q.get('analysis'):
        if not manually_reviewed(q['analysis']):
            q['analysis'].update({'correct_answer': q['content'].get('answer'), 'knowledge_node_ids': q['knowledge_node_ids'], 'ability_ids': q['ability_ids']})
        return
    if not text:
        return
    q['analysis'] = {'correct_answer': q['content'].get('answer'),
                     'key_info': None, 'option_compare': None, 'trace_back': q['source']['origin_file'],
                     'explanation': text,
                     'knowledge_node_ids': q['knowledge_node_ids'], 'ability_ids': q['ability_ids'],
                     'status': 'source_answer_points_pending_review', 'expert_verified': False,
                     'source_files': [f for f in q['source']['files'] if f['role'] == 'answer_raw']}


def recover_source_answer(q, answer_cache):
    if reviewed_content(q):
        return
    number = q['extra'].get('source_question_number')
    if number is None or q['extra'].get('source_boundary_verification', {}).get('status') != 'unique_text_boundary':
        return
    source = next((f for f in q['source']['files'] if f['role'] == 'answer_raw'), None)
    if not source:
        return
    path = ROOT / source['path']
    if path not in answer_cache:
        answer_cache[path] = parse_answers(load_text(path))
    raw = answer_cache[path].get(number)
    status, answer = classify_answer(raw)
    source['locator'] = {'source_question_number': number, 'alignment_status': 'unique_stem_source_number', 'expert_verified': False}
    if q['content']['answer_status'] == 'source_conflict' and q['extra'].get('answer_candidate', {}).get('answer') == answer:
        return  # 已隔离的同一来源答案不能在复跑时恢复有效判分。
    if answer and answer != q['content'].get('answer'):
        if status == 'letter' and any(a not in {o['key'] for o in q['content']['options']} for a in answer):
            return
        q['extra'].setdefault('source_repairs', []).append({'kind': 'source_answer_number_recovery',
              'before': {'answer': q['content'].get('answer'), 'answer_status': q['content']['answer_status']},
              'source_question_number': number, 'source_file': source['path'], 'expert_verified': False})
        q['content']['answer'], q['content']['answer_status'] = answer, ANSWER_CONTRACT[status][0]
        q['extra']['answer_provenance'] = ANSWER_CONTRACT[status][1]
        if status == 'brief':
            q['content']['analysis'] = answer


def normalize_source_answers(q):
    """清除缺/略/字母答案/连续答案号伪装成逐题解析的情况，保留原始证据。"""
    if reviewed_content(q):
        return
    c = q['content']
    if q['extra'].get('answer_provenance') != 'brief':
        return
    old = c.get('answer')
    status, answer = classify_answer(old)
    if len(re.findall(r'\d{2}[、.．]', old or '')) >= 3:
        status, answer = 'source_conflict', None
    if status == 'brief':
        return
    q['extra'].setdefault('source_answer_quality_findings', []).append({'raw_answer': old,
        'raw_analysis': c.get('analysis'), 'reason': 'source_placeholder_or_letters_or_merged_answer_sequence', 'expert_verified': False})
    if status == 'source_conflict':
        q['extra']['answer_candidate'] = {'answer': old, 'original_status': c['answer_status'], 'reason': 'source_explicit_conflict_or_merged_answer_sequence', 'expert_verified': False}
    c['answer'], c['answer_status'] = answer, status
    if c.get('analysis') == old:
        c['analysis'] = None
    if (q.get('analysis') or {}).get('explanation') == old and not manually_reviewed(q['analysis']):
        q['extra']['source_answer_quality_findings'][-1]['raw_structured_analysis'] = q.pop('analysis')


def sanitize_source_analysis(q):
    if reviewed_content(q):
        return
    text = q['content'].get('analysis')
    if not text:
        return
    status, _ = classify_answer(text)
    if status not in ('missing', 'letter', 'source_conflict') and len(re.findall(r'\d{2}[、.．]', text)) < 3:
        return
    finding = {'raw_analysis': text, 'reason': 'placeholder_letters_or_merged_answer_sequence', 'expert_verified': False}
    if (q.get('analysis') or {}).get('explanation') == text and not manually_reviewed(q['analysis']):
        finding['raw_structured_analysis'] = q.pop('analysis')
    q['extra'].setdefault('source_analysis_quality_findings', []).append(finding)
    q['content']['analysis'] = None


def quarantine_unsafe_answer(q):
    c = q['content']
    keys = {o['key'] for o in c['options']}
    answer = c.get('answer')
    if not reviewed_content(q) and len(keys) >= 2 and c['answer_status'] == 'letter_only' and answer and any(a not in keys for a in answer):
        q['extra']['answer_candidate'] = {'answer': answer, 'original_status': c['answer_status'],
             'reason': 'not_in_current_options; source_options_or_alignment_unresolved',
             'source_files': [f for f in q['source']['files'] if f['role'] == 'answer_raw'], 'expert_verified': False}
        c['answer'] = None
        c['answer_status'] = 'source_conflict'
    if not manually_reviewed(q['review']):
        q['review']['answer_validation_status'] = 'blocked_source_conflict' if c['answer_status'] == 'source_conflict' else 'not_expert_verified'


def source_mix_risks(q):
    """扫描所有题的跨题混入风险；风险是候选诊断，不能自动宣称源题正确。"""
    c = q['content']
    texts = [c['stem']] + [o['text'] for o in c['options']]
    risks = []
    sequence = re.compile(r'A\s*[、.．].*?B\s*[、.．].*?C\s*[、.．].*?D\s*[、.．]', re.S)
    if sequence.search(c['stem']):
        risks.append('complete_choice_sequence_in_stem')
    if any(sequence.search(o['text']) for o in c['options']):
        risks.append('complete_choice_sequence_in_option')
    combined = c['stem'] + '\n' + '\n'.join(o['key'] + '、' + o['text'] for o in c['options'])
    if len(sequence.findall(combined)) >= 2:
        risks.append('multiple_complete_choice_sequences')
    if any(re.search(r'(?<!\d)\d{1,2}\s*(?=下列|教师|某学校|某幼儿园|某小学|某中学|学生|根据|依据|为了|中国|在我国)', text) for text in texts):
        risks.append('embedded_numbered_question_candidate')
    risks.extend(q['review'].get('case_material_risks', []))
    q['review']['source_boundary_status'] = q['extra'].get('source_boundary_verification', {}).get('status', 'not_located')
    q['review']['cross_question_risk'] = risks
    return risks


def practice_rubric(q):
    rubric = q.setdefault('rubric', {})
    if q.get('question_id'):
        q.setdefault('rubric_id', 'rubric.' + q['question_id'])
        rubric.setdefault('rubric_id', 'rubric.' + q['question_id'])
    defaults = {'status': 'practice_framework_pending_subject_expert', 'official_scoring': False,
                'dimensions': [{'name': name, 'max_level': 3, 'levels': ['未呈现', '部分呈现', '基本准确', '准确且有证据']}
                               for name in ('要点覆盖', '理论运用', '逻辑结构', '语言表达', '规范性')],
                'question_specific_points': [], 'exam_requirement_ids': q['exam_requirement_ids'], 'expert_verified': False}
    for key, value in defaults.items():
        rubric.setdefault(key, value)
    if not manually_reviewed(rubric):
        rubric['exam_requirement_ids'] = q['exam_requirement_ids']
    return rubric


def refresh_mapping(q, node_index):
    review = q['review']
    ids = q['knowledge_node_ids']
    if not reviewed_content(q):
        q['ability_ids'] = sorted({('shengkao' if q['exam'] == '省考' else 'ntce') + '.' + q['level'] + '.ability.' + aid
                                  for nid in ids for aid in node_index.get(nid, {}).get('ability_codes', [])})
        q['exam_requirement_ids'] = sorted({rid for nid in ids for rid in node_index.get(nid, {}).get('exam_requirement_ids', [])})
        review['alignment_status'] = 'automatic_pending_review'
        review['requirement_mapping_status'] = 'pending_expert_review' if q['exam_requirement_ids'] else 'unmapped'
        review['requirement_mapping_evidence_statuses'] = sorted({node_index[nid].get('mapping_status') for nid in ids if nid in node_index})
    review['content_verified'] = bool(review.get('checked_by') and review.get('content_verified'))


def refresh_tags(q):
    tags = q.setdefault('tags', {})
    derived = {'exam': q['exam'], 'subject': q['subject'], 'question_type': q['question_type'],
               'knowledge': q['knowledge_node_ids'], 'ability': q['ability_ids'],
               'difficulty': {'value': q.get('difficulty'), 'status': 'uncalibrated' if q.get('difficulty') is None else 'provided'},
               'source': {'type': q['source']['source_classification'], 'session': q['source']['session'], 'files': q['source']['files']},
               'review': {'status': q['review']['status'], 'tagger': q['review']['tagger'], 'content_verified': q['review']['content_verified']},
               'copyright': q['source']['copyright']}
    for key, value in derived.items():
        if isinstance(value, dict) and isinstance(tags.get(key), dict):
            # 保留 difficulty 的标定方法标识（method/calibration/version/features）。
            # 这些键由 ntce_difficulty.py 写入，标识启发式估算 vs 真实校准，丢失会让下游
            # 无法区分二者。若将来把 derived['difficulty'] 改为整体赋值，此处仍能兜底。
            preserved = {k: tags[key][k] for k in DIFFICULTY_TRACE_KEYS if k in tags[key]} if key == 'difficulty' else {}
            tags[key].update(value)
            if preserved:
                tags[key].update(preserved)
        else:
            tags[key] = value
    return tags


def question_pending(q):
    reasons = []
    c = q['content']
    if len(c['stem'].strip()) < 10 or '暂缺' in c['stem']:
        reasons.append('source_stem_incomplete')
    if not q['knowledge_node_ids']:
        reasons.append('knowledge_alignment_needed')
    if not q['ability_ids']:
        reasons.append('ability_alignment_needed')
    if not q['exam_requirement_ids']:
        reasons.append('official_requirement_alignment_needed')
    if not c.get('answer'):
        reasons.append('reference_answer_needed')
    if c['answer_status'] == 'source_conflict':
        reasons.append('source_answer_conflict_review_needed')
    if q['review'].get('cross_question_risk'):
        reasons.append('cross_question_boundary_review_needed')
    if (q['review'].get('source_boundary_status') == 'ambiguous_boundary_candidates'
            or q.get('extra', {}).get('source_boundary_verification', {}).get('status') == 'ambiguous_boundary_candidates'
            or q['review'].get('type_source_verification', {}).get('status') == 'source_choice_boundary_ambiguous'):
        reasons.append('source_boundary_alignment_needed')
    if not c.get('analysis'):
        reasons.append('question_specific_explanation_needed')
    if q['question_type'] in ('单选', '多选'):
        if len(c['options']) < 4 or any(not o['text'] for o in c['options']):
            reasons.append('source_options_or_diagram_needed')
        answer = c.get('answer') or ''
        if c['answer_status'] == 'letter_only' and any(a not in {o['key'] for o in c['options']} for a in answer):
            reasons.append('answer_option_alignment_needed')
    else:
        if not (q.get('rubric') or {}).get('question_specific_points'):
            reasons.append('question_specific_scoring_points_needed')
    if q.get('difficulty') is None:
        reasons.append('difficulty_calibration_needed')
    if not q['review']['content_verified']:
        reasons.append('expert_content_review_needed')
    return reasons


def sync_materials(questions):
    reverse = defaultdict(list)
    for q in questions:
        if q.get('material_id'):
            reverse[q['material_id']].append(q)
    for path in sorted((OUT / 'materials').glob('*/*/*.jsonl')):
        records = read_rows(path)
        for rec in records:
            linked = reverse[rec['material_id']]
            rec['question_ids'] = [q['question_id'] for q in linked]
            rec['used_by_questions'] = rec['question_ids']
            rec['word_count'] = len(rec.get('text', ''))
            rec['level'] = linked[0]['level'] if linked else path.parent.parent.name
            rec['subject'] = linked[0]['subject'] if linked else path.parent.name
            q_types = {q.get('question_type') for q in linked}
            if any(t in ('教学设计', '活动设计') for t in q_types):
                rec['kind'] = 'lesson_plan_material'
            elif any('面试' in str(t) for t in q_types):
                rec['kind'] = 'interview_material'
            else:
                rec['kind'] = 'case_material'
            rec['knowledge_node_ids'] = sorted({nid for q in linked for nid in q['knowledge_node_ids']})
            rec['ability_ids'] = sorted({nid for q in linked for nid in q['ability_ids']})
            rec['exam_requirement_ids'] = sorted({nid for q in linked for nid in q['exam_requirement_ids']})
            rec.setdefault('source_files', [])
            for q in linked:
                for f in q['source']['files']:
                    if f['role'] in ('question_raw', 'material_raw') and f not in rec['source_files']:
                        rec['source_files'].append(f)
            rec['source'] = {
                'origin_file': linked[0]['source']['origin_file'] if linked else (rec['source_files'][0]['path'] if rec['source_files'] else 'unknown'),
                'files': rec['source_files'],
                'type': '真题',
                'copyright': linked[0]['source'].get('copyright', {'use_scope': 'research_non_commercial'}) if linked else {'use_scope': 'research_non_commercial'}
            }
            rec.setdefault('review', {})
            rec['review'].setdefault('content_verified', False)
            rec['review'].setdefault('status', 'auto_parsed')
            rec['review'].setdefault('extraction_status', 'source_parsed_pending_review')
        write_rows(path, records)


def sync_cards(questions, materials):
    count = 0
    for q in questions:
        if q['extra'].get('duplicate_of'):
            continue
        path = OUT / 'cards' / q['level'] / q['subject'] / q['source']['session'] / ('q%02d.md' % q['extra']['paper_order'])
        path.parent.mkdir(parents=True, exist_ok=True)
        text = render_card(q, materials.get(q.get('material_id')))
        text += '\n**核验与使用:** 原料关联核验不等于专家核定。版权授权状态 ' + q['source']['copyright'].get('authorization_status', 'unknown') + '。\n'
        text += '\n待补项: ' + '；'.join(q['review']['pending_reasons']) + '\n'
        if q.get('rubric'):
            text += '\n**主观题练习评价量规（建议稿）:**\n' + json.dumps(q['rubric'], ensure_ascii=False, indent=2) + '\n'
        atomic_write(path, text)
        count += 1
    return count


def repair(skip_outline=False):
    files = sorted((OUT / 'questions').glob('*/*/*.jsonl'))
    batches = [(path, read_rows(path)) for path in files]
    questions = [q for _, records in batches for q in records]
    review_dir = OUT / 'review'
    review_dir.mkdir(exist_ok=True)
    baseline_path = review_dir / 'baseline_metrics.json'
    if not baseline_path.exists():
        baseline_path.write_text(json.dumps(question_metrics(questions), ensure_ascii=False, indent=2), encoding='utf-8')
    if not skip_outline:
        from m5_tag import gen_outline
        gen_outline()
    sources, requirements = load_official()
    official_rubric_path = ROOT / '权威资料/official_interview_rubrics.json'
    interview_criteria = json.loads(official_rubric_path.read_text(encoding='utf-8')).get('criteria', []) if official_rubric_path.exists() else []
    rubric_out = OUT / 'rubrics/official_interview.json'
    rubric_out.parent.mkdir(exist_ok=True)
    atomic_write(rubric_out, json.dumps({'source': official_rubric_path.relative_to(ROOT).as_posix(),
       'scope': 'official_exam_rubric_reference; question_task_mapping_pending_review',
       'criteria': interview_criteria}, ensure_ascii=False, indent=2))
    outlines = {}
    node_index = {}
    for path in sorted((OUT / 'outline').glob('*.json')):
        doc = json.loads(path.read_text(encoding='utf-8'))
        align_outline(doc, requirements, sources)
        atomic_write(path, json.dumps(doc, ensure_ascii=False, indent=1))
        outlines[(doc['level'], doc['subject'])] = doc['nodes']
        node_index.update({n['node_id']: n for n in doc['nodes']})
    file_cache, answer_cache = {}, {}
    from ntce_material_repair import recover_case_materials, case_risks
    material_batches = {path: read_rows(path) for path in (OUT / 'materials').glob('*/*/*.jsonl')}
    material_recovery = recover_case_materials(questions, material_batches, file_cache)
    for path, records in material_batches.items():
        write_rows(path, records)
    materials = {m['material_id']: m['text'] for records in material_batches.values() for m in records}
    recovered = 0
    from ntce_type_repair import repair_type, source_sections
    type_sections, type_audit = {}, []
    for q in questions:
        raw_text = evidence_source(q, file_cache)
        source_key = q['source']['origin_file']
        if source_key not in type_sections:
            type_sections[source_key] = source_sections(raw_text)
        type_audit.append(repair_type(q, raw_text, type_sections[source_key], reviewed_content(q)))
        sanitize_source_analysis(q)
        normalize_source_answers(q)
        recovered += recover_options(q, raw_text, type_sections[source_key])
        recover_source_answer(q, answer_cache)
        quarantine_unsafe_answer(q)
        q['review']['case_material_risks'] = case_risks(q, materials.get(q.get('material_id'), ''))
        mix_risks = source_mix_risks(q)
        if not reviewed_content(q) and any(risk in mix_risks for risk in ('complete_choice_sequence_in_stem', 'complete_choice_sequence_in_option', 'multiple_complete_choice_sequences')):
            if q['content'].get('answer'):
                q['extra']['answer_candidate'] = {'answer': q['content']['answer'], 'original_status': q['content']['answer_status'],
                   'reason': 'possible_cross_question_mix; preserve_original_answer_pending_boundary_review', 'expert_verified': False}
                q['content']['answer'] = None
                q['content']['answer_status'] = 'source_conflict'
            q['review']['answer_validation_status'] = 'blocked_possible_cross_question_mix'
        nodes = outlines.get((q['level'], q['subject']), [])
        if not reviewed_content(q) and q['review'].get('tagger') == 'llm-v2':
            from llm_batch import input_status
            context = input_status(q, materials.get(q.get('material_id')))
            result = q['extra'].get('llm_tag_result', {})
            if context['status'] != 'complete' or result.get('input_truncated'):
                result['input_validation_status'] = 'insufficient_context_pending_rework'
                result['current_input_context'] = context
                q['extra']['llm_tag_result'] = result
                q['review']['tagger'] = None
                q['knowledge_node_ids'] = []
        if not reviewed_content(q):
            if not (q['review'].get('tagger') == 'llm-v2' and all(nid in node_index and node_index[nid]['assessable'] for nid in q['knowledge_node_ids'])):
                ids, evidence = select_nodes(q['content']['stem'], q['content']['options'], nodes,
                                             q['question_type'], materials.get(q.get('material_id'), ''))
                q['knowledge_node_ids'] = ids
                q['review']['tagger'] = 'content-rule-v2' if ids else None
                q['extra']['tagging_evidence'] = evidence
        # 面试题的卷名是明确的任务分类证据，绑定细任务节点。
        if not reviewed_content(q) and q['subject'] == 'mianshi' and not q['knowledge_node_ids']:
            from m5_tag import CHAPTER_NODE
            for term, suffix in CHAPTER_NODE.items():
                if term in (q['source'].get('paper') or ''):
                    candidates = [n for n in nodes if n.get('assessable') and ('.' + suffix + '.') in n['node_id']]
                    if candidates and len(q['content']['stem'].strip()) >= 10:
                        q['knowledge_node_ids'] = [candidates[0]['node_id']]
                        q['review']['tagger'] = 'chapter-task-rule-v2'
                        q['extra']['tagging_evidence'] = [{'method': 'source_chapter_task', 'matched_terms': [term], 'expert_verified': False}]
                    break
        refresh_mapping(q, node_index)
        structured_source_analysis(q)
        if q['question_type'] not in ('单选', '多选'):
            practice_rubric(q)
            q.setdefault('rubric_id', 'rubric.' + q['question_id'])
            if q['subject'] == 'mianshi':
                scope_ids = {r['standard_id'] for r in requirements if r['requirement_id'] in q['exam_requirement_ids']}
                if not manually_reviewed(q['rubric']):
                    q['rubric']['official_exam_criteria_reference'] = [criterion for criterion in interview_criteria
                        if criterion['standard_id'] in scope_ids and criterion['requirement_id'] in q['exam_requirement_ids']]
                q['rubric'].setdefault('official_rubric_file', 'rubrics/official_interview.json')
                q['rubric'].setdefault('scope_note', '官方分值属于整场面试评价，不等于本题满分；具体任务评分点仍需教研制定。')
        q.setdefault('school_level', q.get('level'))
        q.setdefault('module', SUBJECT_CN.get(q.get('subject'), q.get('subject')))
        if q.get('difficulty') is not None and not q.get('difficulty_meta'):
            diff_method = q.get('tags', {}).get('difficulty', {}).get('method', 'heuristic')
            q['difficulty_meta'] = {'method': diff_method, 'description': '分层启发式冷启动估算，未经真实作答IRT参数校准'}
        q['review']['pending_reasons'] = question_pending(q)
        if not q['review']['content_verified'] and any(reason in q['review']['pending_reasons'] for reason in ('source_stem_incomplete', 'answer_option_alignment_needed', 'source_options_or_diagram_needed')):
            q['review']['status'] = 'needs_fix'
            q['review']['review_priority'] = 'low_confidence'
        elif not q['review']['content_verified'] and q['review']['status'] == 'auto_parsed':
            q['review']['status'] = 'needs_fix'
            q['review']['review_priority'] = 'flagged_general'
        refresh_tags(q)
    for path, records in batches:
        write_rows(path, records)
    sync_materials(questions)
    card_count = sync_cards(questions, materials)
    pending = [{'question_id': q['question_id'], 'reasons': q['review']['pending_reasons'],
                'origin_file': q['source']['origin_file'], 'subject': q['subject'], 'level': q['level']} for q in questions if q['review']['pending_reasons']]
    write_rows(review_dir / 'pending.jsonl', pending)
    write_rows(review_dir / 'question_type_source_audit.jsonl', type_audit)
    stats = question_metrics(questions)
    stats.update({'knowledge_nodes': len(node_index), 'assessable_knowledge_nodes': sum(n.get('assessable', False) for n in node_index.values()),
                  'cards': card_count, 'materials': len(materials), 'pending_questions': len(pending),
                  'pending_by_reason': dict(Counter(reason for p in pending for reason in p['reasons'])),
                  'source_option_repairs_total': sum(any(change['kind'] == 'option_marker_recovery' for change in q['extra'].get('source_repairs', [])) for q in questions),
                  'source_answer_repairs_total': sum(any(change['kind'] == 'source_answer_number_recovery' and change['before']['answer_status'] != 'source_conflict' for change in q['extra'].get('source_repairs', [])) for q in questions),
                  'cross_question_risk_records': sum(bool(q['review'].get('cross_question_risk')) for q in questions),
                  'cross_question_risk_by_type': dict(Counter(risk for q in questions for risk in q['review'].get('cross_question_risk', []))),
                  'expert_verified_questions': sum(q['review']['content_verified'] for q in questions),
                  'source_type_repairs_total': sum(bool(q['extra'].get('type_history')) for q in questions),
                  'nonobjective_letter_quarantined_total': sum(any(change['kind'] == 'nonobjective_letter_quarantined' for change in q['extra'].get('source_repairs', [])) for q in questions),
                  'material_links_recovered_total': sum(bool(q.get('material_id') and q['material_id'].endswith('.material.recovered')) for q in questions),
                  'trailing_cases_detached_total': sum(any(change['kind'] == 'trailing_case_detached' and change['before']['stem'] != q['content']['stem'] for change in q['extra'].get('source_repairs', [])) for q in questions),
                  'by_subject': {key: question_metrics([q for q in questions if q['level'] + '/' + q['subject'] == key]) for key in sorted({q['level'] + '/' + q['subject'] for q in questions})}})
    atomic_write(OUT / 'stats.json', json.dumps(stats, ensure_ascii=False, indent=2))
    write_rows(review_dir / 'source_boundaries.jsonl', [{'question_id': q['question_id'], 'origin_file': q['source']['origin_file'],
                 'boundary': q['extra'].get('source_boundary_verification'), 'risk': q['review']['cross_question_risk'],
                 'answer_candidate': q['extra'].get('answer_candidate')} for q in questions if q['review']['cross_question_risk']
                 or q['extra'].get('source_boundary_verification', {}).get('status') == 'ambiguous_boundary_candidates'])
    write_rows(review_dir / 'llm_tag_queue.jsonl', [{'question_id': q['question_id'], 'input_status': q['extra'].get('llm_tag_input_status'),
               'result': q['extra'].get('llm_tag_result')} for q in questions if q['extra'].get('llm_tag_input_status', {}).get('status') == 'skipped'
               or q['extra'].get('llm_tag_result', {}).get('status') in ('unmatched', 'invalid_response', 'provider_error')])
    write_rows(review_dir / 'llm_analysis_failures.jsonl', [{'question_id': q['question_id'], 'result': q['extra']['llm_analysis_result']}
               for q in questions if q['extra'].get('llm_analysis_result', {}).get('status') not in (None, 'draft')])
    manifest_path = OUT / 'MANIFEST.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest.setdefault('source_materials_original', manifest.get('materials', 0))
    manifest.update({'name': '教资真题知识库 v2', 'schema_version': '2.0', 'questions': len(questions),
                     'materials': len(materials), 'cards': card_count, 'stats_file': 'stats.json',
                     'pending_queue': 'review/pending.jsonl', 'tagging': {'tagger': 'content-rule-v2/llm-v2', 'status': '待专家复核',
                     'knowledge_mapped': stats['knowledge_mapped'], 'ability_mapped': stats['ability_mapped'],
                     'requirement_mapped': stats['requirement_mapped']},
                     'known_limitations': ['全量保留原始题；缺答案/图形/学科审核/难度校准逐题见pending.jsonl。',
                                            'source.verified=false；raw_file_verification只说明文件关联，不能证明答案正确。',
                                            '量规为练习建议稿，缺具体评分点的题不能自动评分。']})
    atomic_write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=1))
    from build_graph import build
    build()
    print(json.dumps({k: v for k, v in stats.items() if k != 'by_subject'}, ensure_ascii=False, indent=2))
    return stats


if __name__ == '__main__':
    import sys
    repair('--skip-outline' in sys.argv)
