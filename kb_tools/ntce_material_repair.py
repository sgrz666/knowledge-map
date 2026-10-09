"""从唯一CSV原文区间恢复案例材料；不推断题目与案例之间未给出的语义。"""
import hashlib
import re
from build_kb import ROOT, OUT, load_text

CASE_HEAD = re.compile(r'[（(][一二三四五六七八九十]+[）)]\s*')
CASE_REFERENCE = re.compile(r'上述(?:材料|案例)|这个案例|该案例|案例中|材料中|结合材料|根据材料|诗中|文中')


def has_inline_material(stem):
    """已有实际材料正文时不强求另建 material_id；纯任务指令不算材料。"""
    references = list(CASE_REFERENCE.finditer(stem))
    if not references:
        return False
    prefix = stem[:references[-1].start()].strip()
    # 去掉阅读提示，保留后面的实际段落；空白后直接进入任务仍会被拒绝。
    prefix = re.sub(r'^(?:请)?(?:认真)?阅读[^\n。]*[。\n]\s*', '', prefix).strip()
    if len(prefix) < 60 or re.match(r'^(?:问题|任务|(?:请)?(?:根据|结合)|在(?:这个|上述|该)案例)', prefix):
        return False
    explicit_body = bool(re.match(r'^材料(?:[一二三四五六七八九十\d]+)?\s*[：:.．\n]', prefix))
    narrative = bool(re.search(r'老师|教师|学生|幼儿|儿童|小朋友|班主任|小\w{1,2}|文文|洋洋|成成', prefix)
                     and re.search(r'说|认为|活动|组织|发生|发现|提问|玩|观察|批评|学习|教学|要求|展示', prefix))
    return explicit_body or narrative


def narrative_section(tail):
    head = tail.strip()[:100]
    if re.match(r'请|简述|说明|分析|设计|要求|问题|试|\d(?!\d?岁)|[（(][123一二三]', head):
        return False
    return bool(re.search(r'老师|教师|学生|幼儿|儿童|岁的|某|妈妈|爸爸|文文|洋洋|成成|李老师|材料', head))


def needs_preceding_material(q):
    stem = q['content']['stem']
    if has_inline_material(stem):
        return False
    return bool(CASE_REFERENCE.search(stem) or
                (q['question_type'] in ('材料分析', '教学设计', '活动设计', '诊断') and len(stem) < 500
                 and re.search(r'请|问题|要求|[（(]1[）)]|判断|分析|怎样|如何|什么|老师对', stem)))


def source_position(raw, stem):
    needle = stem[:40].strip()
    if len(needle) < 12 or raw.count(needle) != 1:
        return None
    start = raw.index(needle)
    prefix = raw[max(0, start - 20):start]
    match = re.search(r'(?<!\d)(\d{1,2})\s*[、.．]?\s*$', prefix)
    if not match:
        return None
    return start, max(0, start - 20) + match.start(), int(match.group(1))


def case_risks(q, material_text=''):
    stem = q['content']['stem']
    risks = []
    for heading in CASE_HEAD.finditer(stem):
        if heading.start() >= 20 and len(stem[heading.end():].strip()) >= 50 and narrative_section(stem[heading.end():]) and re.search(r'分析|判断|说明|回答|怎样|什么|如何|谈谈|要求|请|问题', stem[:heading.start()]):
            risks.append('next_case_section_after_current_task')
            break
    if CASE_REFERENCE.search(stem) and not material_text and not has_inline_material(stem):
        risks.append('case_reference_without_attached_material')
    if material_text and any(name in stem and name not in material_text for name in ('小明', '洋洋', '成成', '文文')):
        risks.append('case_entity_mismatch_in_source')
    return risks


def recover_case_materials(questions, material_batches, file_cache):
    index = {m['material_id']: m for records in material_batches.values() for m in records}
    attached = detached = 0
    following_by_source = {}
    groups = {}
    for q in questions:
        groups.setdefault(q['source']['origin_file'], []).append(q)
    for group in groups.values():
        ordered = sorted(group, key=lambda q: (q['source']['session'], q['extra']['paper_order']))
        for current, following in zip(ordered, ordered[1:]):
            if current['source']['session'] == following['source']['session'] and following['extra']['paper_order'] == current['extra']['paper_order'] + 1:
                following_by_source[current['question_id']] = following
    for q in questions:
        if q['question_type'] in ('单选', '多选') or q['review'].get('checked_by') or q['review'].get('tagger') == 'expert':
            continue
        path = ROOT / q['source']['origin_file']
        if path not in file_cache:
            file_cache[path] = (load_text(path), hashlib.sha256(path.read_bytes()).hexdigest()) if path.exists() else ('', None)
        raw, checksum = file_cache[path]
        # 复查早期较宽规则的自动切分；人工稿保持。历史不删除。
        prior_detach = next((change for change in reversed(q['extra'].get('source_repairs', [])) if change['kind'] == 'trailing_case_detached'), None)
        if prior_detach and q['content']['stem'] != prior_detach['before']['stem'] and q['content']['stem'] in prior_detach['before']['stem']:
            q['content']['stem'] = prior_detach['before']['stem']
        position = source_position(raw, q['content']['stem'])
        if not position:
            continue
        start, number_start, number = position
        stem = q['content']['stem']
        following = following_by_source.get(q['question_id'])
        next_position = source_position(raw, following['content']['stem']) if following else None
        # 完整题干与原文唯一一致时才截出其后的下一案例，原文本保留历史。
        if raw.count(stem) == 1:
            for heading in CASE_HEAD.finditer(stem):
                if next_position and next_position[0] > start + len(stem) - 3 and heading.start() >= 20 and len(stem[heading.end():].strip()) >= 50 and narrative_section(stem[heading.end():]) and 'next_case_section_after_current_task' in case_risks(q):
                    change = {'kind': 'trailing_case_detached', 'before': {'stem': stem},
                        'source_file': q['source']['origin_file'], 'locator': {'start': start + heading.start(), 'end': start + len(stem)},
                        'expert_verified': False}
                    if not any(old['kind'] == change['kind'] and old['before'] == change['before'] for old in q['extra'].get('source_repairs', [])):
                        q['extra'].setdefault('source_repairs', []).append(change)
                    q['content']['stem'] = stem[:heading.start()].strip()
                    q['review']['tagger'] = None
                    detached += 1
                    break
        automatic_mid = q['question_id'] + '.material.recovered'
        # 每次重新核对自动关联的原文区间，旧规则的结果不能绕过较严的新边界规则。
        # 人工已审核材料和原始材料继续保持。
        previous_material = index.get(automatic_mid)
        if q.get('material_id') == automatic_mid and not (previous_material or {}).get('review', {}).get('checked_by'):
            q['material_id'] = None
            q['source']['files'] = [f for f in q['source']['files'] if f['role'] != 'material_raw']
            q['review']['material_boundary_status'] = 'automatic_association_requires_source_revalidation'
        if q.get('material_id') or not needs_preceding_material(q):
            continue
        headings = list(CASE_HEAD.finditer(raw[:number_start]))
        if not headings:
            continue
        heading = headings[-1]
        material = raw[heading.end():number_start].strip()
        if not 50 <= len(material) <= 15000:
            continue
        # 禁止把此前独立题的任务也吸进案例。只能接受紧邻任务号的独立段落。
        if re.search(r'(?<!\d)\d{1,2}\s*[、.．]?\s*(?=请|根据|结合|试|简述|问题|分析|谈谈|老师对|回答|求|设|计算|阅读|判断|说明|下列|以下)', material):
            continue
        mid = q['question_id'] + '.material.recovered'
        record = {'material_id': mid, 'text': material,
                  'source_files': [{'path': q['source']['origin_file'], 'role': 'material_raw', 'sha256': checksum,
                                    'locator': {'decoded_csv_character_start': heading.end(), 'decoded_csv_character_end': number_start,
                                                'next_source_question_number': number, 'alignment_status': 'unique_task_excerpt_with_preceding_case_section'}}],
                  'review': {'content_verified': False, 'status': 'auto_parsed',
                             'extraction_status': 'source_interval_recovered_pending_expert'}}
        target = OUT / 'materials' / q['level'] / q['subject'] / (q['source']['session'] + '.jsonl')
        if mid not in index:
            material_batches.setdefault(target, []).append(record)
            index[mid] = record
        else:
            previous = index[mid]
            previous['text'] = record['text']
            previous['source_files'] = record['source_files']
            for field, value in record['review'].items():
                previous.setdefault('review', {}).setdefault(field, value)
        if not any(change['kind'] == 'case_material_link' and change['material_id'] == mid for change in q['extra'].get('source_repairs', [])):
            q['extra'].setdefault('source_repairs', []).append({'kind': 'case_material_link', 'before': {'material_id': q.get('material_id')},
                'material_id': mid, 'source_question_number': number, 'expert_verified': False})
        q['material_id'] = mid
        q['review']['material_boundary_status'] = 'unique_source_interval_pending_expert'
        q['source'].setdefault('files', []).extend(record['source_files'])
        attached += 1
    active = {q.get('material_id') for q in questions}
    for records in material_batches.values():
        records[:] = [record for record in records if not record['material_id'].endswith('.material.recovered') or record['material_id'] in active or record.get('review', {}).get('checked_by')]
    return {'new_material_links': attached, 'trailing_cases_detached': detached}
