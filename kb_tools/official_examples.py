"""Archive official NTCE examples separately and propose only exact, unique recoveries.

No function writes the question corpus or general requirements. Public interfaces:
extract_catalog(root), match_examples(examples, questions), recovery_patches(...).
JSONL is always read by physical lines; U+2028 is valid content within one record.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / '补充资料' / '教资官方样题'
TYPES = ('单项选择题', '选择题', '简答题', '辨析题', '解答题', '论述题',
         '材料分析题', '案例分析题', '教学案例分析题', '教学情境分析题',
         '教学情景分析题', '教学设计题', '活动设计题', '写作题', '诊断题',
         '课例点评题', '技术设计题', '音乐编创题', '音乐作品分析题')
SIMPLE_TYPES = {'单项选择题', '选择题', '简答题', '辨析题', '解答题', '论述题', '写作题'}


def read_jsonl(path):
    with Path(path).open(encoding='utf-8-sig') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_jsonl(path, records):
    with Path(path).open('w', encoding='utf-8', newline='\n') as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')


def normalize_full_text(text):
    """Only NFKC and whitespace removal; no punctuation/word/number substitutions."""
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text or ''))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def heading_type(line):
    text = normalize_full_text(line)
    if not re.match(r'^(?:\d+|[一二三四五六七八九十]+)[.、]', text):
        return None
    return next((kind for kind in TYPES if kind in text), None)


def sample_bounds(lines):
    starts = [i for i, line in enumerate(lines)
              if re.match(r'^[四六][.、](?:题型示例|试题样本|试题示例)', normalize_full_text(line))]
    if len(starts) != 1:
        raise ValueError(f'Expected one official sample section; found {starts}')
    return starts[0], len(lines) - 1


def raw_slice(lines, start, end):
    return '\n'.join(lines[start:end + 1])


def trim_bounds(lines, start, end):
    while start <= end and not lines[start].strip():
        start += 1
    while end >= start and not lines[end].strip():
        end -= 1
    return start, end


def split_options(question_text):
    marks = list(re.finditer(r'(?:^|[\s\n])([A-D])[．.、]\s*', question_text))
    if [m.group(1) for m in marks] != ['A', 'B', 'C', 'D']:
        return question_text.strip(), []
    options = []
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(question_text)
        options.append({'key': mark.group(1), 'text': question_text[mark.end():end].strip()})
    return question_text[:marks[0].start()].strip(), options


def completeness_issues(question_text):
    issues = []
    if re.search(r'[\x01\x15]', question_text):
        issues.append('unextracted_word_object_or_symbol')
    if re.search(r'题图|如图|下图|谱例|下列两幅图|图文资料|如下图|下面是一道作业题', question_text):
        issues.append('visual_context_requires_original_word_verification')
    if re.search(r'内容略|原文（略）|目录（略）|材料三：（具体', question_text):
        issues.append('source_explicitly_omits_context')
    return issues


def base_record(source, lines, start, end, example_id, kind, question_text,
                record_kind='question', source_question_number=None):
    stem, options = split_options(question_text) if kind in {'选择题', '单项选择题'} else (question_text.strip(), [])
    issues = completeness_issues(question_text)
    return {'schema_version': '1.0', 'example_id': example_id,
            'record_kind': record_kind, 'classification': 'official_outline_sample',
            'source_id': source['standard_id'], 'source_name': source['name'],
            'authority': source['authority'], 'source_url': source['source_url'],
            'source_path': source['local_path'], 'source_sha256': source['sha256'],
            'source_text_sha256': source['text_sha256'],
            'locator': {'text_path': source['text_path'], 'line_start': start + 1,
                        'line_end': end + 1, 'section': '官方样题'},
            'question_type': kind, 'source_question_number': source_question_number,
            'raw_question_text': raw_slice(lines, start, end), 'stem': stem, 'options': options,
            'answer_present': False, 'answer_kind': 'not_provided', 'answer': None,
            'raw_answer_text': None, 'answer_locator': None, 'scoring_points': None,
            'general_scoring_locator': None, 'content_completeness': 'unverified_text_only',
            'content_issues': issues, 'recovery_eligible': False, 'expert_verified': False,
            'copyright': {'holder': source['authority'], 'authorization_status': 'official_public_download',
                          'publication_reuse_license_verified': False},
            'note': '官方大纲样题，不据此声称题库题目是官方发布真题；图片及公式以归档Word原件为准。'}


def extract_science(source, lines):
    """317 is the only archived outline explicitly publishing its answer section."""
    sample_start, _ = sample_bounds(lines)
    answer_heading = next(i for i, line in enumerate(lines) if line.strip() == '样本试题标准答案与评分标准')
    marks = [(i, int(m.group(1))) for i, line in enumerate(lines[sample_start + 1:answer_heading], sample_start + 1)
             if (m := re.match(r'^\s*([1-7])[．.]', line))]
    answers = {int(m.group(1)): (i, m.group(2))
               for i, line in enumerate(lines[answer_heading + 1:], answer_heading + 1)
               for m in re.finditer(r'([1-4])[．.]\s*([A-D])', line)}
    answer_marks = [(i, int(m.group(1))) for i, line in enumerate(lines[answer_heading + 1:], answer_heading + 1)
                    if (m := re.match(r'^\s*([5-7])[．.]', line))]
    examples = []
    for index, (start, number) in enumerate(marks):
        end = marks[index + 1][0] - 1 if index + 1 < len(marks) else answer_heading - 1
        while end > start and (not lines[end].strip() or heading_type(lines[end])):
            end -= 1
        text = re.sub(r'^\s*\d+[．.]\s*', '', raw_slice(lines, start, end), count=1)
        kind = '选择题' if number < 5 else '简答题' if number == 5 else '案例分析题' if number == 6 else '教学设计题'
        item = base_record(source, lines, start, end, f"{source['standard_id']}.sample.{number:02d}",
                           kind, text, source_question_number=number)
        if number <= 4:
            at, answer = answers[number]
            answer_start = answer_end = at
            raw_answer = lines[at]
            answer_kind = 'letter'
        else:
            ai = next(i for i, (_, n) in enumerate(answer_marks) if n == number)
            answer_start = answer_marks[ai][0]
            answer_end = answer_marks[ai + 1][0] - 1 if ai + 1 < len(answer_marks) else len(lines) - 1
            while answer_end > answer_start and (not lines[answer_end].strip() or heading_type(lines[answer_end])):
                answer_end -= 1
            raw_answer = raw_slice(lines, answer_start, answer_end)
            answer = re.sub(r'^\s*\d+[．.]\s*', '', raw_answer, count=1)
            answer_kind = 'reference_with_official_scoring'
        if number == 7:
            item['content_issues'].append('material_one_image_not_extracted')
        # 2's figure is semantically necessary even though its options are complete.
        item.update(answer_present=True, answer_kind=answer_kind, answer=answer,
                    raw_answer_text=raw_answer,
                    answer_locator={'text_path': source['text_path'], 'line_start': answer_start + 1,
                                    'line_end': answer_end + 1, 'section': '样本试题标准答案与评分标准',
                                    'source_question_number': number},
                    scoring_points=answer if number >= 5 else None,
                    content_completeness='complete_text' if number in {3, 5} else 'incomplete_text_extraction',
                    recovery_eligible=number in {3, 5})
        examples.append(item)
    if [e['source_question_number'] for e in examples] != list(range(1, 8)):
        raise ValueError('Science example boundaries changed; manual source check required')
    return examples


def extract_interview(source, lines):
    start, end = sample_bounds(lines)
    marks = [i for i, line in enumerate(lines[start + 1:], start + 1) if re.match(r'^例[一二三四五六七八九十]+[：:]', line.strip())]
    scoring_start = next(i for i, line in enumerate(lines) if line.strip() == '五、评分标准')
    examples = []
    for index, at in enumerate(marks):
        last = marks[index + 1] - 1 if index + 1 < len(marks) else end
        at, last = trim_bounds(lines, at, last)
        text = re.sub(r'^例[一二三四五六七八九十]+[：:]\s*', '', raw_slice(lines, at, last), count=1)
        item = base_record(source, lines, at, last, f"{source['standard_id']}.sample.{index + 1:02d}", '面试试讲或展示', text)
        item['general_scoring_locator'] = {'text_path': source['text_path'], 'line_start': scoring_start + 1,
                                          'line_end': start, 'scope': 'general_interview_rubric_not_sample_answer'}
        examples.append(item)
    return examples


def extract_unanswered(source, lines):
    start, end = sample_bounds(lines)
    headings = [(i, heading_type(line)) for i, line in enumerate(lines[start + 1:], start + 1) if heading_type(line)]
    # English outline uses Roman section headings as additional context boundaries.
    roman = [i for i, line in enumerate(lines[start + 1:], start + 1)
             if re.match(r'^[IV]+[．.]', line.strip())]
    for at in roman:
        if lines[at].strip().startswith('III'):
            headings.append((at, '教学设计题'))
        elif lines[at].strip().startswith('IV'):
            headings.append((at, '教学情景分析题'))
    headings.sort()
    boundaries = sorted({i for i, _ in headings} | set(roman) | {end + 1})
    examples = []
    for at, kind in headings:
        last = next(bound for bound in boundaries if bound > at) - 1
        first, last = trim_bounds(lines, at + 1, last)
        if first > last:
            continue
        numbered = [i for i, line in enumerate(lines[first:last + 1], first)
                    if re.match(r'^\s*[（(]\d+[）)]', line)]
        if kind in SIMPLE_TYPES and numbered and numbered[0] == first:
            spans = [(mark, numbered[j + 1] - 1 if j + 1 < len(numbered) else last)
                     for j, mark in enumerate(numbered)]
            record_kind = 'question'
        else:
            spans = [(first, last)]
            record_kind = 'question_group' if len(numbered) > 1 else 'question'
        for first, last in spans:
            first, last = trim_bounds(lines, first, last)
            text = re.sub(r'^\s*[（(]\d+[）)]\s*', '', raw_slice(lines, first, last), count=1) if record_kind == 'question' else raw_slice(lines, first, last)
            examples.append(base_record(source, lines, first, last,
                                        f"{source['standard_id']}.sample.{len(examples) + 1:02d}", kind, text, record_kind))
    return examples


def selected_sources(root):
    catalog = json.loads((Path(root) / '权威资料' / 'catalog.json').read_text(encoding='utf-8-sig'))
    return [s for s in catalog['sources'] if s['standard_id'].startswith(('ntce.outline.', 'ntce.interview.'))]


def extract_catalog(root=ROOT):
    examples = []
    for source in selected_sources(root):
        text_path = Path(root) / source['text_path']
        if digest(text_path) != source['text_sha256'] or digest(Path(root) / source['local_path']) != source['sha256']:
            raise ValueError(f"Source bytes changed: {source['standard_id']}")
        lines = text_path.read_text(encoding='utf-8-sig').split('\n')
        if source['standard_id'] == 'ntce.outline.317':
            records = extract_science(source, lines)
        elif source['standard_id'].startswith('ntce.interview.'):
            records = extract_interview(source, lines)
        else:
            records = extract_unanswered(source, lines)
        if not records:
            raise ValueError(f"No samples extracted: {source['standard_id']}")
        if source['standard_id'] == 'ntce.outline.317':
            add_verified_visual_context(Path(root), records)
        examples.extend(records)
    return examples


def add_verified_visual_context(root, examples):
    archive = root / '补充资料' / '教资官方样题'
    path = archive / 'visual_verification.json'
    if not path.exists():
        return
    visual = json.loads(path.read_text(encoding='utf-8'))
    if digest(root / visual['original_path']) != visual['original_sha256']:
        raise ValueError('Original Word changed after visual verification')
    if digest(root / visual['exported_pdf_path']) != visual['exported_pdf_sha256']:
        raise ValueError('Exported PDF changed after visual verification')
    pages = {p['page']: p for p in visual['pages']}
    for page in pages.values():
        if digest(root / page['image_path']) != page['image_sha256']:
            raise ValueError('Inspected PDF page changed after verification')
    transcriptions = {
        1: '原件第4页公式转录：氢氧化物相对分子质量m，氯化物相对分子质量n；选项A：+(m−n)/18.5；B：+(n−m)/18.5；C：+18.5/(m−n)；D：+18.5/(n−m)。',
        2: '碳循环示意图完整保留在PDF第4页及对应页图中；不能仅凭含图字样的文本判断材料等价。',
        4: '原件第4页向量转录：Δr=(4i−5j+6k)m；F=(−3i−5j+9k)N；i、j、k均为单位基向量。',
        6: '原件第4页作业框转录：重30N的容器，容积5×10^−2m³；装满水后容器对水平桌面压强6000Pa；水深20cm；g=10N/kg。学生先得水压强2000Pa，错误使用S容=V容/h=0.25m²，错误结论F容=500N。原件第6页正确计算：水压强2000Pa；S容=F/P=(G容+ρ水gV水)/P=(30+1000×10×5×10^−2)/6000≈8.8×10^−2m²；F容=2000×8.8×10^−2=176N。原件保留该舍入结果。',
        7: '原件第5页教材截图完整保留：父亲无耳垂ee，母亲有耳垂Ee，配子e与E/e，子女可能有耳垂Ee或无耳垂ee。截图原文及遗传图见对应页图。'
    }
    for example in examples:
        number = example['source_question_number']
        qp, ap = visual['question_pages'][str(number)], visual['answer_pages'][str(number)]
        example['original_context_status'] = 'complete_original_visual_context'
        example['visual_context'] = {'pdf_path': visual['exported_pdf_path'],
                                     'pdf_sha256': visual['exported_pdf_sha256'],
                                     'question_page': qp, 'answer_page': ap,
                                     'question_page_image': pages[qp], 'answer_page_image': pages[ap],
                                     'status': visual['verification_status'], 'expert_verified': False}
        example['object_transcription'] = transcriptions.get(number)
        example['note'] += ' 原Word对象已确认存在，PDF第4–7页及页图保留完整视觉上下文；文本缺项是抽取遗漏。对象转录只用于辅助读者，图题自动匹配仍关闭。'


def signature(stem, options):
    return (normalize_full_text(stem), tuple((o['key'], normalize_full_text(o['text'])) for o in (options or [])))


def match_examples(examples, questions):
    indexes = defaultdict(list)
    source_keys = defaultdict(list)
    for question in questions:
        indexes[signature(question['content']['stem'], question['content'].get('options'))].append(question)
    for example in examples:
        if example['recovery_eligible']:
            source_keys[signature(example['stem'], example['options'])].append(example)
    matches = []
    for example in examples:
        candidates = indexes.get(signature(example['stem'], example['options']), [])
        status = 'no_exact_match'
        if example['content_completeness'].startswith('incomplete'):
            status = 'text_context_incomplete_for_matching'
        elif candidates:
            if not example['answer_present']:
                status = 'exact_match_no_source_answer'
            elif len(candidates) != 1 or len(source_keys[signature(example['stem'], example['options'])]) != 1:
                status = 'ambiguous_kb_match' if len(candidates) != 1 else 'ambiguous_source_match'
            elif candidates[0].get('material_id') or candidates[0].get('review', {}).get('cross_question_risk'):
                status = 'context_not_equivalent'
            elif not example['recovery_eligible']:
                status = 'source_content_unverified'
            elif candidates[0]['content'].get('answer') is not None:
                status = 'exact_unique_existing_answer'
            elif candidates[0]['content'].get('answer_status') not in {'reference_only', 'missing', 'source_conflict', None}:
                status = 'kb_answer_status_not_recoverable'
            else:
                status = 'exact_unique_recoverable'
        matches.append({'example_id': example['example_id'], 'source_id': example['source_id'],
                        'status': status, 'kb_question_ids': [q['question_id'] for q in candidates],
                        'match_method': 'complete_stem_and_all_options_nfkc_whitespace_exact',
                        'candidate_count': len(candidates), 'expert_verified': False})
    return matches


def recovery_patches(matches, examples, questions):
    """Return reviewable patches; caller must recheck before-state hash before use."""
    by_example = {e['example_id']: e for e in examples}
    by_question = {q['question_id']: q for q in questions}
    current_matches = {m['example_id']: m for m in match_examples(examples, questions)}
    patches = []
    for match in matches:
        if match['status'] != 'exact_unique_recoverable':
            continue
        current = current_matches.get(match['example_id'])
        if not current or current['status'] != 'exact_unique_recoverable' or current['kb_question_ids'] != match['kb_question_ids']:
            continue
        example = by_example[match['example_id']]
        question = by_question[match['kb_question_ids'][0]]
        original = json.dumps(question['content'], ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        patches.append({'question_id': question['question_id'], 'example_id': example['example_id'],
                        'before_content_sha256': hashlib.sha256(original.encode()).hexdigest(),
                        'answer': example['answer'], 'answer_kind': example['answer_kind'],
                        'source_id': example['source_id'], 'source_url': example['source_url'],
                        'answer_locator': example['answer_locator'], 'match_method': match['match_method'],
                        'classification': 'official_outline_sample_reference', 'expert_verified': False})
    return patches


def build(root=ROOT, output=DEFAULT_OUTPUT):
    root, output = Path(root), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    examples = extract_catalog(root)
    questions = [q for path in sorted((root / '数据集' / '教资' / 'questions').rglob('*.jsonl')) for q in read_jsonl(path)]
    matches = match_examples(examples, questions)
    patches = recovery_patches(matches, examples, questions)
    source_sections = []
    for source in selected_sources(root):
        lines = (root / source['text_path']).read_text(encoding='utf-8-sig').split('\n')
        start, end = sample_bounds(lines)
        source_sections.append({'source_id': source['standard_id'], 'source_url': source['source_url'],
                                'source_path': source['local_path'], 'source_sha256': source['sha256'],
                                'text_sha256': source['text_sha256'],
                                'locator': {'text_path': source['text_path'], 'line_start': start + 1, 'line_end': end + 1},
                                'raw_text': raw_slice(lines, start, end),
                                'includes_embedded_objects': False,
                                'original_word_required_for_objects': True})
    write_jsonl(output / 'official_examples.jsonl', examples)
    write_jsonl(output / 'source_sample_sections.jsonl', source_sections)
    write_jsonl(output / 'exact_matches.jsonl', matches)
    write_jsonl(output / 'recovery_patches.jsonl', patches)
    summary = {'generated_at': datetime.now(timezone.utc).isoformat(), 'sources': len(source_sections),
               'written_outline_sources': 35, 'interview_sources': 3, 'corpus_questions_scanned': len(questions),
               'example_records': len(examples), 'record_kind_counts': dict(Counter(e['record_kind'] for e in examples)),
               'explicit_answer_records': sum(e['answer_present'] for e in examples),
               'complete_text_answer_examples': sum(e['recovery_eligible'] for e in examples),
               'answers_with_complete_original_visual_context': sum(e.get('original_context_status') == 'complete_original_visual_context' for e in examples),
               'recoverable_kb_questions': len(patches), 'match_status_counts': dict(Counter(m['status'] for m in matches)),
               'source_example_counts': dict(Counter(e['source_id'] for e in examples)),
               'note': '只提供审阅补丁，未写主库。question_group完整保留多问及共享材料，不能冒充单个已唯一对齐题。7份显式答案均来自317，原Word对象均存在且PDF与页图完整保留；5题仅文本提取不完整，禁止仅文本自动匹配。常规面试评分不是样题答案。'}
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(build(args.root, args.output), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
