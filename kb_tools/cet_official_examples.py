"""Rebuild the full 2016 CET official samples; never write the main corpus.

The source's CID fonts report every Latin glyph as one em.  Actual glyphs are
centred in those cells: advance = half of each neighbouring glyph width plus
spacing.  Recover spaces from the embedded Latin hmtx metrics and origins,
preserve every page and character, and require a saved visual verification
before accepting a source record for exact matching.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import io
import json
import re
import statistics
import unicodedata
from pathlib import Path

SOURCE_ID = 'cet.syllabus.2016'
PDF_REL = Path('权威资料/originals/cet.syllabus.2016.pdf')
OUTPUT_REL = Path('补充资料/四六级官方样题')
SOURCE_URL = 'https://cet.neea.edu.cn/res/Home/1704/55b02330ac17274664f06d9d3db8249d.pdf'
EXPECTED_SHA256 = '9166d3c03b7bc43abd9d9df91bd2ef8085b4419286f1e5ca100dea68f3cfd1f1'
BOUNDARIES = {
    'cet4_written': (150, 161), 'cet4_listening_script': (162, 167), 'cet4_answer_key': (168, 168),
    'cet4_oral': (169, 171), 'cet6_written': (172, 183),
    'cet6_listening_script': (184, 190), 'cet6_answer_key': (190, 191),
    'cet6_oral': (192, 193), 'cet4_answer_cards': (194, 197), 'cet6_answer_cards': (198, 201),
    'cet4_writing_scoring': (202, 204), 'cet6_writing_scoring': (205, 207),
    'cet4_translation_scoring': (208, 209), 'cet6_translation_scoring': (210, 211),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def glyph_text(char: str) -> str:
    # Verified visually in this PDF's custom English fonts. Fullwidth G is
    # the wrongly mapped hyphen glyph; U+1001B3 is the apostrophe glyph.
    return unicodedata.normalize('NFKC', char.replace('Ｇ', '-').replace(chr(0x1001B3), "'").replace(chr(0x1001B0), '"'))


def normalize_text(text: str) -> str:
    """NFKC and typographic whitespace only; retain English word boundaries."""
    text = unicodedata.normalize('NFKC', str(text or ''))
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'\s+([,.;:!?%)\]，。；：！？])', r'\1', text)
    text = re.sub(r'([(\[“])\s+', r'\1', text)
    text = re.sub(r'(?<=\d)\s*\.\s*(?=\d)', '.', text)
    text = re.sub(r'(?<=\d),\s+(?=\d)', ',', text)
    text = re.sub(r'([.;:!?])(?=[A-Za-z“”"])', r'\1 ', text)
    text = re.sub(r',(?=[A-Za-z“”"])', ', ', text)
    text = re.sub(r'\b([A-Z])\.\s+(?=[A-Z]\.)', r'\1.', text)
    text = re.sub(r'\b([ie])\.\s+(?=[eg]\.)', r'\1.', text)
    return text


def join_source_lines(text):
    text = re.sub(r'-\n(?=[a-z])', '-', text)
    text = re.sub(r'(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])', '', text)
    return normalize_text(text)


def _font_metrics(doc):
    from fontTools.ttLib import TTFont
    result = {}
    seen = set()
    for pno in range(150, 212):
        for xref, *_ in doc[pno - 1].get_fonts(full=True):
            if xref in seen:
                continue
            seen.add(xref)
            name, _, _, data = doc.extract_font(xref)
            if not name.split('+')[-1].startswith('E-'):
                continue
            font = TTFont(io.BytesIO(data))
            order = font.getGlyphOrder()
            units = font['head'].unitsPerEm
            # ASCII's original glyphs remain in the embedded font even though
            # the PDF paints duplicates through the erroneous CID width table.
            result[name.split('+')[-1]] = {
                chr(i): font['hmtx'].metrics[order[i - 31]][0] / units for i in range(32, 127)
            }
    return result


def _reconstruct_line(chars, metrics):
    def width(c):
        ch = glyph_text(c['c'])
        return metrics.get(c['font'], {}).get(ch, 1.0 if ord(ch[0]) > 127 else .5) * c['size']

    chars = sorted(chars, key=lambda c: c['origin'][0])
    output, inserted = [], []
    for i, c in enumerate(chars):
        output.append(glyph_text(c['c']))
        if i + 1 < len(chars):
            n = chars[i + 1]
            advance = n['origin'][0] - c['origin'][0]
            expected = (width(c) + width(n)) / 2
            residual = advance - expected
            if residual > c['size'] * .18 and not output[-1].isspace():
                output.append(' ')
                inserted.append({'after_char': i, 'residual_pt': round(residual, 4)})
    return normalize_text(''.join(output)), inserted


def extract_pages(root: Path, render=False):
    import fitz
    source = root / PDF_REL
    digest = sha256(source)
    if digest != EXPECTED_SHA256:
        raise ValueError('Official PDF hash changed; boundaries/glyph mappings need a new audit.')
    doc = fitz.open(source)
    metrics = _font_metrics(doc)
    pages = {}
    for pno in range(150, 212):
        page = doc[pno - 1]
        physical = []
        for block in page.get_text('rawdict')['blocks']:
            for line in block.get('lines', []):
                if line['dir'] != (1., 0.):
                    continue
                chars = [{**c, 'font': span['font'], 'size': span['size']}
                         for span in line['spans'] for c in span['chars']
                         if 55 < c['origin'][1] < 686 and 58 < c['origin'][0] < 490]
                if not chars or all(c['c'].isspace() for c in chars):
                    continue
                baseline = statistics.median(c['origin'][1] for c in chars)
                physical.append((baseline, chars))
        # MuPDF sometimes breaks one row after a decimal or abbreviation. Merge
        # rows by baseline, then sort x; retain A/C vs B/D source layout in text.
        merged = []
        for baseline, chars in sorted(physical, key=lambda x: x[0]):
            if merged and abs(baseline - merged[-1][0]) < 4:
                merged[-1][1].extend(chars)
            else:
                merged.append([baseline, chars])
        lines = []
        for index, (baseline, chars) in enumerate(merged, 1):
            chars.sort(key=lambda c: c['origin'][0])
            text, spaces = _reconstruct_line(chars, metrics)
            if not text or text.startswith('全国大学英语四、六级考试大纲'):
                continue
            lines.append({'line': index, 'baseline_y': round(baseline, 3),
                          'x_start': round(chars[0]['origin'][0], 3), 'text': text,
                          'raw_glyph_text': ''.join(c['c'] for c in chars),
                          'inserted_spaces': spaces, 'characters': chars})
        pages[pno] = {'pdf_page': pno, 'printed_page': pno - 5,
                      'lines': lines, 'text': '\n'.join(x['text'] for x in lines),
                      'raw_native_text': page.get_text(),
                      'image_path': (OUTPUT_REL / f'page.{pno:03}.png').as_posix(),
                      'text_quality': 'coordinate_reconstructed_pending_visual_check'}
        if render:
            image = root / pages[pno]['image_path']
            image.parent.mkdir(parents=True, exist_ok=True)
            page.get_pixmap(matrix=fitz.Matrix(1.4, 1.4)).save(image)
            pages[pno]['image_sha256'] = sha256(image)
    doc.close()
    return pages


def page_text(pages, start, end):
    return '\n'.join(pages[p]['text'] for p in range(start, end + 1))


def parse_options(text):
    markers = list(re.finditer(r'(?<![A-Za-z])([A-O])\s*\)', text))
    return {m.group(1): normalize_text(text[m.end(): markers[i + 1].start() if i + 1 < len(markers) else len(text)])
            for i, m in enumerate(markers)}


def _source(pages, start, end, role, number=None):
    return {'source_id': SOURCE_ID, 'source_url': SOURCE_URL,
            'pdf_path': PDF_REL.as_posix(), 'pdf_sha256': EXPECTED_SHA256,
            'pdf_pages': list(range(start, end + 1)), 'printed_pages': list(range(start - 5, end - 4)),
            'role': role, 'original_question_number': number,
            'page_text_path': (OUTPUT_REL / 'source_pages.json').as_posix(),
            'locator': {'json_pointer': f'/{start}/lines', 'coordinate_system': 'PDF points; origin at top left'},
            'page_images': [pages[p]['image_path'] for p in range(start, end + 1)]}


def _pages_for_lines(pages, start, end, prefix):
    found = []
    for p in range(start, end + 1):
        for line in pages[p]['lines']:
            if re.match(prefix, line['text']):
                found.append({'pdf_page': p, 'page_line': line['line'], 'baseline_y': line['baseline_y'],
                              'text': line['text']})
    return found


def _cut_structural(text):
    return re.split(r'\n(?:Questions\b|Section [ABC]\b|Directions:|Part [IVX]+\b)', text)[0].strip()


def _numbered(text, first, last, with_options=False):
    pattern = r'(?m)^(\d{1,2})\.\s*' + (r'(?=A\))' if with_options else '')
    markers = [m for m in re.finditer(pattern, text) if first <= int(m.group(1)) <= last]
    rows = {}
    for i, m in enumerate(markers):
        body = _cut_structural(text[m.end():markers[i + 1].start() if i + 1 < len(markers) else len(text)])
        n = int(m.group(1))
        if n in rows:
            raise ValueError(f'Duplicate numbered question {n}')
        rows[n] = body
    if set(rows) != set(range(first, last + 1)):
        raise ValueError(f'Question boundary failure: need {first}..{last}; found {list(rows)}')
    return rows


def _listening_script(text):
    text = text.split('【参考答案】')[0]
    headings = list(re.finditer(r'(?m)^(News Report|Conversation|Passage|Recording) (One|Two|Three)$', text))
    result = {}
    for i, m in enumerate(headings):
        chunk = text[m.end():headings[i + 1].start() if i + 1 < len(headings) else len(text)].strip()
        passage, question_part = chunk.split('\nQuestions ', 1)
        passage = join_source_lines(passage)
        qmarkers = list(re.finditer(r'(?m)^(\d{1,2})\.\s*', question_part))
        for j, q in enumerate(qmarkers):
            stem = _cut_structural(question_part[q.end():qmarkers[j + 1].start() if j + 1 < len(qmarkers) else len(question_part)])
            result[int(q.group(1))] = {'stem': join_source_lines(stem), 'passage': passage,
                                      'group_title': m.group(0), 'raw_script_group': chunk}
    if set(result) != set(range(1, 26)):
        raise ValueError(f'Incomplete listening script: {list(result)}')
    return result


def _answer_key(text):
    text = text.split('【参考答案】')[-1]
    objective, translation = text.split('Part IV Translation', 1)
    key = {int(n): a for n, a in re.findall(r'\b(\d{1,2})\.\s*([A-O])\b', objective)}
    if set(key) != set(range(1, 56)):
        raise ValueError(f'Incomplete answer key: {list(key)}')
    return key, join_source_lines(translation)


def _blank_sentence(passage, number):
    target = re.search(rf'\b{number}\b', passage)
    if not target:
        raise ValueError(f'Blank {number} absent from passage')
    # Locate the complete source sentence; avoid abbreviation/decimal dots.
    bounds = [m.end() for m in re.finditer(r'[.!?](?=\s*[“”"\u2019]?[A-Z])', passage)]
    begin = max([0] + [b for b in bounds if b < target.start()])
    end = min([len(passage)] + [b for b in bounds if b > target.end()])
    sentence = passage[begin:end].strip()
    return re.sub(rf'\b{number}\b', '____', sentence, count=1)


def _written_examples(pages, exam, limits):
    start, end, script_start, script_end, answer_start, answer_end = limits
    written = page_text(pages, start, end)
    script = page_text(pages, script_start, script_end)
    answer_text = page_text(pages, answer_start, answer_end)
    keys, translated = _answer_key(answer_text)
    code = exam.lower().replace('-', '')
    listening = written.split('Part II Listening Comprehension', 1)[1].split('Part III Reading Comprehension', 1)[0]
    printed_options = _numbered(listening, 1, 25, with_options=True)
    scripts = _listening_script(script)
    reading = written.split('Part III Reading Comprehension', 1)[1].split('Part IV Translation', 1)[0]
    cloze, matching_and_detail = reading.split('Section A', 1)[1].split('Section B', 1)
    matching, detail = matching_and_detail.split('Section C', 1)
    cloze_body = re.split(r'in the bank more than once\.', cloze, maxsplit=1)[1].strip()
    bank_at = re.search(r'(?m)^A\)', cloze_body)
    cloze_passage = join_source_lines(cloze_body[:bank_at.start()])
    bank = {k: join_source_lines(v) for k, v in parse_options(cloze_body[bank_at.start():]).items()}
    if set(bank) != set('ABCDEFGHIJKLMNO'):
        raise ValueError('Incomplete cloze word bank')
    title_end = matching.index('Answer Sheet 2.') + len('Answer Sheet 2.')
    first_statement = re.search(r'(?m)^36\.', matching)
    matching_passage = join_source_lines(matching[title_end:first_statement.start()])
    matching_choices = {k: join_source_lines(v) for k, v in parse_options(matching[title_end:first_statement.start()]).items()}
    statements = _numbered(matching[first_statement.start():], 36, 45)
    passages = detail.split('Passage One', 1)[1].split('Passage Two', 1)
    details = {}
    for raw, first, last in zip(passages, [46, 51], [50, 55]):
        raw = re.sub(r'^\s*Questions \d+ to \d+ are based on the following passage\.\s*', '', raw)
        marker = re.search(rf'(?m)^{first}\.', raw)
        passage = join_source_lines(raw[:marker.start()])
        for n, question in _numbered(raw[marker.start():], first, last).items():
            options_start = re.search(r'(?<![A-Za-z])A\)', question)
            details[n] = {'stem': join_source_lines(question[:options_start.start()]),
                          'options': {k: join_source_lines(v) for k, v in parse_options(question[options_start.start():]).items()},
                          'passage': passage, 'raw_question': question, 'raw_passage': raw[:marker.start()]}
    rows = []
    for n in range(1, 56):
        if n <= 25:
            context = scripts[n]
            opts = {k: join_source_lines(v) for k, v in parse_options(printed_options[n]).items()}
            question_type, stem, passage = 'listening', context['stem'], context['passage']
            raw_question, raw_passage = printed_options[n], context['raw_script_group']
        elif n <= 35:
            question_type, stem, passage, opts = 'reading_cloze', _blank_sentence(cloze_passage, n), cloze_passage, bank
            raw_question, raw_passage = cloze_body, cloze_body
        elif n <= 45:
            question_type, stem, passage, opts = 'reading_matching', join_source_lines(statements[n]), matching_passage, matching_choices
            raw_question, raw_passage = statements[n], matching[title_end:first_statement.start()]
        else:
            context = details[n]
            question_type, stem, passage, opts = 'reading_detail', context['stem'], context['passage'], context['options']
            raw_question, raw_passage = context['raw_question'], context['raw_passage']
        if n <= 25 or n >= 46:
            if set(opts) != set('ABCD'):
                raise ValueError(f'{exam} question {n}: incomplete choices {list(opts)}')
        src = _source(pages, start, end, 'official_written_sample', n)
        src['question_line_locators'] = _pages_for_lines(pages, start, end, rf'^{n}\.\s*' + (r'A\)' if n <= 25 else ''))
        if 26 <= n <= 35:
            cloze_pages = (154, 155) if exam == 'CET-4' else (176, 176)
            src['question_line_locators'] = [
                {'pdf_page': p, 'page_line': line['line'], 'baseline_y': line['baseline_y'], 'text': line['text'], 'target_blank_label': n}
                for p in range(cloze_pages[0], cloze_pages[1] + 1) for line in pages[p]['lines']
                if re.search(rf'(?<!\d){n}(?!\d)', line['text'])]
        src['answer_key'] = _source(pages, answer_start, answer_end, 'official_reference_answer_key', n)
        src['answer_key']['answer_line_locators'] = [
            {'pdf_page': p, 'page_line': line['line'], 'baseline_y': line['baseline_y'], 'text': line['text']}
            for p in range(answer_start, answer_end + 1) for line in pages[p]['lines']
            if re.search(rf'(?<!\d){n}\.\s*{keys[n]}\b', line['text'])]
        if n <= 25:
            src['listening_script'] = _source(pages, script_start, script_end, 'official_listening_script', n)
            src['listening_script']['group_title'] = scripts[n]['group_title']
            src['listening_script']['question_line_locators'] = _pages_for_lines(pages, script_start, script_end, rf'^{n}\.\s*')
        rows.append({'example_id': f'{SOURCE_ID}.{code}.written.{n:02}', 'exam': exam,
                     'collection': 'written_sample', 'classification': 'official_syllabus_sample',
                     'question_type': question_type, 'number': n,
                     'stem': stem, 'options': dict(sorted(opts.items())), 'passage': passage,
                     'answer': keys[n], 'answer_kind': 'official_objective_key',
                     'official_analysis': None, 'analysis_status': 'not_provided_in_source',
                     'audio': {'status': 'not_provided_in_source', 'path': None} if n <= 25 else None,
                     'raw_source_question': raw_question, 'raw_source_context': raw_passage,
                     'stem_derivation': 'source sentence; target printed blank label replaced by ____' if 26 <= n <= 35 else 'verbatim reconstructed source text',
                     'text_quality': 'coordinate_reconstructed_pending_visual_check', 'source': src,
                     'visual_context': []})
    writing = written.split('Part I Writing', 1)[1].split('Part II Listening Comprehension', 1)[0]
    writing = writing[writing.index('Directions:'):].strip()
    translation = written.split('Part IV Translation', 1)[1]
    # Directions are kept separately from the Chinese task.
    translation_directions, translation_prompt = translation.split('Answer Sheet 2.', 1)
    translation_directions = translation_directions[translation_directions.index('Directions:'):]
    for kind, prompt, answer in [('writing', writing, None), ('translation', translation_prompt, translated)]:
        task_source = _source(pages, start if kind == 'writing' else end, start if kind == 'writing' else end, 'official_written_sample_task')
        if kind == 'translation':
            task_source['answer_key'] = _source(pages, answer_start, answer_end, 'official_reference_translation')
        rows.append({'example_id': f'{SOURCE_ID}.{code}.written.{kind}', 'exam': exam,
                     'collection': 'written_sample', 'classification': 'official_syllabus_sample',
                     'question_type': kind, 'number': None, 'stem': join_source_lines(prompt),
                     'options': {}, 'passage': '', 'answer': answer,
                     'answer_kind': 'official_reference_translation' if answer else 'no_unique_answer_published',
                     'directions': join_source_lines(translation_directions + 'Answer Sheet 2.') if kind == 'translation' else join_source_lines(prompt),
                     'official_analysis': None, 'analysis_status': 'not_provided_in_source',
                     'raw_source_question': prompt, 'raw_source_context': prompt,
                     'text_quality': 'coordinate_reconstructed_pending_visual_check',
                     'source': task_source,
                     'visual_context': [pages[start]['image_path']] if kind == 'writing' and exam == 'CET-4' else [],
                     'visual_objects': [{'kind': 'task_picture', 'pdf_page': start,
                                         'verbatim_caption': 'Why am I going to school if my phone already knows everything?',
                                         'transcription_method': 'visual transcription of original raster caption'}] if kind == 'writing' and exam == 'CET-4' else []})
    return rows


def _scoring_examples(pages, exam, kind, start, end):
    raw = page_text(pages, start, end)
    markers = list(re.finditer(r'(?m)^(14|11|8|5|2) points$', raw))
    if [int(m.group(1)) for m in markers] != [14, 11, 8, 5, 2]:
        raise ValueError('Scoring response boundary failure')
    preamble = raw[:markers[0].start()]
    if kind == 'translation':
        prompt, reference = preamble.split('【参考译文】', 1)
        prompt = prompt.split('\n', 1)[1]
        answer = join_source_lines(reference)
    else:
        prompt = preamble[preamble.index('Directions:'):]
        answer = None
    responses = [{'score': int(m.group(1)),
                  'response': join_source_lines(raw[m.end():markers[i + 1].start() if i + 1 < len(markers) else len(raw)]),
                  'raw_source_response': raw[m.end():markers[i + 1].start() if i + 1 < len(markers) else len(raw)].strip(),
                  'classification': 'official_scored_response; source language errors preserved',
                  'official_commentary': None}
                 for i, m in enumerate(markers)]
    return {'example_id': f'{SOURCE_ID}.{exam.lower().replace("-", "")}.scoring.{kind}',
            'exam': exam, 'collection': 'scoring_sample', 'classification': 'official_scoring_sample',
            'question_type': kind, 'number': None, 'stem': join_source_lines(prompt), 'options': {}, 'passage': '',
            'answer': answer, 'answer_kind': 'official_reference_translation' if answer else 'no_unique_answer_published',
            'scored_responses': responses, 'official_analysis': None,
            'analysis_status': 'scores_published_without_individual_explanations',
            'raw_source_question': preamble, 'raw_source_context': raw,
            'source': _source(pages, start, end, 'official_scoring_sample'),
            'text_quality': 'coordinate_reconstructed_pending_visual_check',
            'visual_context': [pages[start]['image_path']] if kind == 'writing' and exam == 'CET-4' else [],
            'visual_objects': [{'kind': 'task_picture', 'pdf_page': start,
                                'verbatim_caption': 'Why am I going to school if my phone already knows everything?',
                                'transcription_method': 'visual transcription of original raster caption'}] if kind == 'writing' and exam == 'CET-4' else []}


def extract_official(root: Path, render=False):
    pages = extract_pages(root, render)
    examples = _written_examples(pages, 'CET-4', (150, 161, 162, 167, 168, 168))
    examples.extend(_written_examples(pages, 'CET-6', (172, 183, 184, 190, 190, 191)))
    for exam, kind, start, end in [('CET-4', 'writing', 202, 204), ('CET-6', 'writing', 205, 207),
                                  ('CET-4', 'translation', 208, 209), ('CET-6', 'translation', 210, 211)]:
        examples.append(_scoring_examples(pages, exam, kind, start, end))
    oral = []
    for exam, start, end in [('CET-4', 169, 171), ('CET-6', 192, 193)]:
        oral.append({'example_id': f'{SOURCE_ID}.{exam.lower().replace("-", "")}.oral', 'exam': exam,
                     'classification': 'official_syllabus_oral_sample', 'answer': None,
                     'answer_kind': 'no_response_examples_published', 'raw_source_text': page_text(pages, start, end),
                     'source': _source(pages, start, end, 'official_oral_sample'),
                     'visual_context': [pages[p]['image_path'] for p in range(start, end + 1)],
                     'visual_objects': [{'pdf_page': 192, 'kind': 'presentation_card',
                                        'candidate': candidate, 'prompt': prompt,
                                         'topic': 'Stress',
                                         'verbatim_card_text': 'For Candidate ' + candidate + '\nThe following is a topic concerning stress. Please talk about it.\n' + prompt,
                                         'transcription_method': 'visual transcription of original raster card'}
                                        for candidate, prompt in [('A', "What causes stress in students’ life?"),
                                                                  ('B', 'What are the consequences of a stressful life?')]] if exam == 'CET-6' else
                                       [{'pdf_page': 170, 'kind': 'presentation_picture', 'text_status': 'original image preserved'}],
                     'audio': {'status': 'not_provided_in_source', 'path': None}})
    sections = [{'section_id': key, 'source': _source(pages, a, b, key),
                 'text_extraction_status': 'partial_native_text; complete_original_raster_pages_preserved' if 'answer_cards' in key else 'reconstructed_text_and_original_visual_context',
                 'raw_source_text': page_text(pages, a, b)} for key, (a, b) in BOUNDARIES.items()]
    for section in sections:
        if section['section_id'].endswith('listening_script'):
            section['raw_source_text'] = section['raw_source_text'].split('【参考答案】')[0].rstrip()
        elif section['section_id'].endswith('answer_key'):
            section['raw_source_text'] = section['raw_source_text'][section['raw_source_text'].index('【参考答案】'):]
    bundle = {'pages': pages, 'examples': examples, 'oral_samples': oral, 'source_sections': sections}
    _apply_visual_verification(root, bundle)
    return bundle


def _apply_visual_verification(root, bundle):
    path = root / OUTPUT_REL / 'visual_verification.json'
    if not path.exists():
        return
    audit = json.loads(path.read_text(encoding='utf-8'))
    if audit.get('source_pdf_sha256') != EXPECTED_SHA256:
        return
    verified = set()
    for pno, page in bundle['pages'].items():
        record = audit.get('pages', {}).get(str(pno), {})
        image_path = root / page['image_path']
        text_digest = hashlib.sha256(page['text'].encode('utf-8')).hexdigest()
        if record.get('visual_check') == 'checked' and record.get('reconstructed_text_sha256') == text_digest and image_path.exists() and record.get('image_sha256') == sha256(image_path):
            verified.add(pno)
            page['text_quality'] = 'partial_native_text_original_raster_preserved' if 194 <= pno <= 201 else 'visually_checked_coordinate_reconstruction'
            page['image_sha256'] = record['image_sha256']
    for ex in bundle['examples']:
        relevant = set(ex['source']['pdf_pages'])
        for role in ['answer_key', 'listening_script']:
            relevant.update(ex['source'].get(role, {}).get('pdf_pages', []))
        if relevant <= verified:
            ex['text_quality'] = 'visually_verified'
            ex['text_verification_scope'] = audit['verification_scope']
            ex['content_completeness'] = 'complete_reconstructed_text_and_original_visual_context'


def match_examples(examples, questions):
    source_counts = collections.Counter(_example_signature(ex) for ex in examples
                                        if ex.get('collection') != 'scoring_sample' and ex['question_type'] not in ['writing', 'translation'])
    index = collections.defaultdict(list)
    for q in questions:
        sig = _question_signature(q)
        if sig:
            index[sig].append(q)
    results = []
    for ex in examples:
        if ex.get('collection') == 'scoring_sample' or ex['question_type'] in ['writing', 'translation']:
            continue
        signature = _example_signature(ex)
        hits = index.get(signature, []) if signature else []
        status = 'no_exact_match'
        if signature and source_counts[signature] > 1:
            status = 'ambiguous_source_examples'
        elif hits and ex.get('text_quality') != 'visually_verified':
            status = 'source_text_not_verified'
        elif len(hits) > 1:
            status = 'ambiguous_exact_matches'
        elif len(hits) == 1:
            status = 'exact_unique_match'
        results.append({'example_id': ex['example_id'], 'status': status,
                        'candidate_question_ids': [q['question_id'] for q in hits],
                        'matching_rule': 'NFKC/whitespace-normalized complete stem, ordered choices and complete passage; English word boundaries preserved',
                        'source_answer': ex.get('answer'), 'source': ex['source']})
    return results


def recovery_patches(matches, examples, questions):
    source_counts = collections.Counter(_example_signature(ex) for ex in examples
                                        if ex.get('collection') != 'scoring_sample' and ex['question_type'] not in ['writing', 'translation'])
    examples = {e['example_id']: e for e in examples}
    questions = {q['question_id']: q for q in questions}
    patches = []
    for m in matches:
        if m['status'] != 'exact_unique_match' or len(m['candidate_question_ids']) != 1:
            continue
        ex = examples.get(m['example_id'])
        q = questions.get(m['candidate_question_ids'][0])
        if not ex or not q or ex.get('text_quality') != 'visually_verified' or not ex.get('answer'):
            continue
        if q.get('content', {}).get('answer') not in [None, '']:
            continue
        if _example_signature(ex) != _question_signature(q):
            continue
        # Recheck uniqueness from current question records, not the saved match.
        sig = _example_signature(ex)
        if not sig or source_counts[sig] != 1:
            continue
        if sum(_question_signature(other) == sig for other in questions.values()) != 1:
            continue
        patches.append({'question_id': q['question_id'], 'example_id': ex['example_id'],
                        'field': 'content.answer', 'before': q['content'].get('answer'), 'after': ex['answer'],
                        'before_content_sha256': hashlib.sha256(json.dumps(q['content'], ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest(),
                        'full_context_signature_sha256': hashlib.sha256(json.dumps(sig, ensure_ascii=False).encode('utf-8')).hexdigest(),
                        'source': ex['source'], 'expert_review': {'status': 'pending', 'reviewer': None}})
    return patches


def _signature(exam, stem, options, passage, blank=None):
    if not stem or not passage or not options:
        return None
    return (exam, normalize_text(stem), tuple((k, normalize_text(v)) for k, v in sorted(options.items())),
            normalize_text(passage), blank)


def _example_signature(ex):
    return _signature(ex['exam'], ex['stem'], ex['options'], ex.get('passage'),
                      ex.get('number') if ex['question_type'] == 'reading_cloze' else None)


def _question_signature(q):
    content = q.get('content', {})
    kind = q.get('question_type', '')
    return _signature(q.get('exam'), content.get('stem'), content.get('options'), q.get('_passage_text'),
                      q.get('extra', {}).get('number') if kind == '选词填空' else None)


def read_jsonl(path):
    """Physical file lines: Unicode paragraph separators inside JSON are data."""
    with path.open(encoding='utf-8-sig') as stream:
        for line_number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(f'{path}:{line_number}: incomplete/invalid physical JSONL line') from error


def load_main_questions(root):
    passages = {r['resource_id']: r for r in read_jsonl(root / '数据集/四六级/passages/reading.jsonl')}
    rows = []
    for path in sorted((root / '数据集/四六级/questions').glob('*/*.jsonl')):
        for q in read_jsonl(path):
            passage = passages.get(q.get('extra', {}).get('passage_id'), {})
            q['_passage_text'] = passage.get('text', '')
            q['_physical_source_path'] = path.relative_to(root).as_posix()
            rows.append(q)
    return rows


def _skill_mapping(example):
    code = example['exam'].lower().replace('-', '')
    kind, stem = example['question_type'], example['stem']
    if kind == 'listening':
        gist = bool(re.search(r'mainly about|main point|focus of', stem, flags=re.I))
        skill = 'gist' if gist else 'detail'
        nodes, abilities, requirements = [f'{code}.listen.{skill}'], [f'ab.{code}.listen.{skill}'], ['r079' if gist else 'r005']
    elif kind == 'reading_cloze':
        nodes, abilities, requirements = [f'{code}.read.cloze', f'{code}.read.discourse', f'{code}.lang.vocab'], [f'ab.{code}.read.discourse', f'ab.{code}.lang.vocab'], ['r017', 'r018', 'r019']
    elif kind == 'reading_matching':
        nodes, abilities, requirements = [f'{code}.read.locate', f'{code}.read.synonym', f'{code}.read.discourse'], [f'ab.{code}.read.locate', f'ab.{code}.read.synonym'], ['r083', 'r020']
    elif kind == 'reading_detail':
        gist = bool(re.search(r'main point|mainly about|main idea', stem, flags=re.I))
        nodes, abilities, requirements = ([f'{code}.read.gist'], [f'ab.{code}.read.gist'], ['r082']) if gist else ([f'{code}.read.detail', f'{code}.read.locate'], [f'ab.{code}.read.locate'], ['r083'])
    elif kind == 'writing':
        nodes, abilities, requirements = [f'{code}.write.structure', f'{code}.write.argument', f'{code}.write.coherence'], [f'ab.{code}.write.organize', f'ab.{code}.write.coherence'], ['r025', 'r026', 'r027']
    elif kind == 'translation':
        nodes, abilities, requirements = [f'{code}.trans.topic', f'{code}.trans.syntax'], [f'ab.{code}.trans.lex', f'ab.{code}.trans.syntax'], ['r034', 'r035', 'r037', 'r038']
    else:
        return [], [], []
    return nodes, abilities, [f'{SOURCE_ID}.{r}' for r in requirements]


def standardize(root, bundle):
    """Reuse and validate existing IDs. Mappings are initial labels, not review."""
    nodes = {r['id'] for r in read_jsonl(root / '数据集/四六级/ontology/knowledge_nodes.jsonl')}
    abilities = {r['id'] for r in read_jsonl(root / '数据集/四六级/ontology/ability_nodes.jsonl')}
    requirements = {r['requirement_id'] for r in read_jsonl(root / '权威资料/requirements.jsonl')}
    questions, passages, passage_keys = [], [], {}
    for ex in bundle['examples']:
        if ex['collection'] != 'written_sample':
            continue
        kn, ab, req = _skill_mapping(ex)
        if not set(kn) <= nodes or not set(ab) <= abilities or not set(req) <= requirements:
            raise ValueError(f'Unknown main corpus ontology/requirement IDs for {ex["example_id"]}')
        code = ex['exam'].lower().replace('-', '')
        number, kind = ex['number'], ex['question_type']
        module = '听力理解' if kind == 'listening' else '阅读理解' if kind.startswith('reading') else '写作' if kind == 'writing' else '翻译'
        if kind == 'listening':
            qtype = ('短篇新闻' if number <= 7 else '长对话' if number <= 15 else '听力篇章') if ex['exam'] == 'CET-4' else ('长对话' if number <= 8 else '听力篇章' if number <= 15 else '讲座/讲话')
        else:
            qtype = {'reading_cloze': '选词填空', 'reading_matching': '长篇阅读', 'reading_detail': '仔细阅读', 'writing': '短文写作', 'translation': '段落翻译'}[kind]
        qid = f'{code}-official-syllabus-2016-{kind}-{number if number else 1}'
        source = {'type': '官方大纲样卷', 'standard_id': SOURCE_ID, 'url': SOURCE_URL,
                  'origin_file': PDF_REL.as_posix(), 'sample_status': 'official_syllabus_sample; not labeled as historical live examination',
                  'files': [{'path': PDF_REL.as_posix(), 'role': 'original_content', 'sha256': EXPECTED_SHA256,
                             'locator': {'pdf_pages': ex['source']['pdf_pages'], 'question_number': number,
                                         'question_lines': ex['source'].get('question_line_locators', []),
                                         'example_id': ex['example_id']}}]}
        for role in ['answer_key', 'listening_script']:
            if role in ex['source']:
                source['files'].append({'path': PDF_REL.as_posix(), 'role': role, 'sha256': EXPECTED_SHA256,
                             'locator': {'pdf_pages': ex['source'][role]['pdf_pages'], 'question_number': number,
                                                    'question_lines': ex['source'][role].get('question_line_locators', []),
                                                    'answer_lines': ex['source'][role].get('answer_line_locators', []),
                                                    'group_title': ex['source'][role].get('group_title')}})
        pid = None
        if ex['passage']:
            key = (ex['exam'], kind, ex['passage'])
            if key not in passage_keys:
                pid = f'{code}-official-syllabus-2016-{kind}-passage-{sum(k[0:2] == key[0:2] for k in passage_keys) + 1}'
                passage_keys[key] = pid
                passages.append({'resource_id': pid, 'resource_type': '官方样卷听力文字稿' if kind == 'listening' else '官方样卷阅读语篇',
                                 'exam': ex['exam'], 'kind': kind, 'text': ex['passage'],
                                 'content': {'text': ex['passage'], 'word_bank': ex['options'] if kind == 'reading_cloze' else None,
                                             'paragraph_choices': ex['options'] if kind == 'reading_matching' else None},
                                 'source': source, 'knowledge_node_ids': kn, 'ability_ids': ab, 'exam_requirement_ids': req,
                                 'difficulty': None, 'review': {'status': 'pending_expert_review', 'reviewer': None},
                                 'extra': {'question_ids': [], 'audio': {'status': 'not_provided_in_source', 'files': []} if kind == 'listening' else None,
                                           'mapping_status': 'initial_labels_pending_expert_review', 'text_quality': ex['text_quality']}})
            pid = passage_keys[key]
            next(p for p in passages if p['resource_id'] == pid)['extra']['question_ids'].append(qid)
        questions.append({'question_id': qid, 'exam': ex['exam'], 'module': module, 'question_type': qtype,
                          'year': None, 'paper': '2016 官方大纲样卷',
                          'content': {'stem': ex['stem'], 'options': ex['options'], 'answer': ex['answer']},
                          'knowledge_node_ids': kn, 'ability_ids': ab, 'exam_requirement_ids': req,
                          'source': source, 'difficulty': None,
                          'review': {'status': 'pending_expert_review', 'reviewer': None, 'reviewed_at': None},
                          'analysis': {'raw': None, 'key_info': None, 'option_compare': None, 'trace_back': None, 'status': 'not_provided_in_source'},
                          'extra': {'number': number, 'passage_id': pid, 'official_example_id': ex['example_id'],
                                    'answer_kind': ex['answer_kind'], 'answer_status': 'official_source_available_pending_expert_review' if ex['answer'] else 'no_unique_answer_published',
                                    'audio': {'status': 'not_provided_in_source', 'files': [], 'start_seconds': None, 'end_seconds': None} if kind == 'listening' else None,
                                    'visual_context': ex['visual_context'], 'visual_objects': ex.get('visual_objects', []),
                                    'text_quality': ex['text_quality'],
                                    'content_review': {'initial_label': {'method': 'official_question_format_and_explicit_stem_keywords', 'status': 'pending_validation'},
                                                       'expert_review': {'status': 'pending', 'reviewer': None, 'reviewed_at': None, 'evidence': []}},
                                    'difficulty_metadata': {'status': 'pending_calibration', 'estimate': None},
                                    'mapping_status': 'initial_labels_pending_expert_review',
                                    'stem_derivation': ex.get('stem_derivation', 'verbatim reconstructed task'),
                                    'directions': ex.get('directions'),
                                    'scoring_example_id': f'{SOURCE_ID}.{code}.scoring.{kind}' if kind in ['writing', 'translation'] else None}})
        if kind in ['writing', 'translation']:
            questions[-1]['rubric_id'] = 'cet.writing.holistic.2016' if kind == 'writing' else 'cet.translation.holistic.2016'
    for row in bundle['oral_samples']:
        row.update({'knowledge_node_ids': [], 'ability_ids': [],
                    'exam_requirement_ids': [f'{SOURCE_ID}.r040' if row['exam'] == 'CET-4' else f'{SOURCE_ID}.r041'],
                    'ontology_alignment_status': 'pending_specific_oral_nodes_not_present_in_main_ontology',
                    'review': {'status': 'pending_expert_review'}, 'difficulty': None})
    return questions, passages


def dump_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def dump_jsonl(path, rows):
    with path.open('w', encoding='utf-8', newline='\n') as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n')


def write_layout_sheets(root):
    from PIL import Image, ImageDraw
    out = root / OUTPUT_REL
    for first in range(150, 212, 4):
        numbers = list(range(first, min(first + 4, 212)))
        canvas = Image.new('RGB', (1540, 2168 if len(numbers) > 2 else 1084), '#dddddd')
        draw = ImageDraw.Draw(canvas)
        for index, number in enumerate(numbers):
            image = Image.open(out / f'page.{number:03}.png')
            image.thumbnail((770, 1056))
            x, y = index % 2 * 770, index // 2 * 1084
            canvas.paste(image, (x, y + 28))
            draw.text((x + 10, y + 6), f'PDF PAGE {number}', fill='black')
        canvas.save(out / f'layout.{first:03}-{numbers[-1]:03}.jpg', quality=90)


def write_viewer(out, bundle):
    # Embedded data allows opening the viewer directly as a file, without a web
    # server or fetch permissions. Text is inserted through textContent only.
    payload = json.dumps({'examples': bundle['examples'], 'oral': bundle['oral_samples'],
                          'sections': bundle['source_sections']}, ensure_ascii=False).replace('<', '\\u003c')
    html = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>CET 2016 官方样卷</title>
<style>body{margin:0;font:16px/1.7 system-ui;color:#20242b;background:#f5f6f7}header{background:#16344b;color:white;padding:24px max(5vw,24px)}h1{font-size:26px;margin:0}header p{max-width:900px;margin:8px 0}main{max-width:1120px;margin:auto;padding:24px}select,input,button{font:inherit;padding:6px}nav{position:sticky;top:0;background:#f5f6f7;padding:10px 0;display:flex;flex-wrap:wrap;gap:12px}article{background:white;border:1px solid #d5dae0;margin:20px 0;padding:24px}article h2{font-size:20px;margin:0 0 10px}.muted{color:#596776;font-size:14px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;background:#f8f9fa;padding:14px}summary{cursor:pointer;font-weight:600}details{margin:10px 0}.answer{border-left:4px solid #245879;padding:12px}img{max-width:100%;height:auto}a{color:#19587d}ol{padding-left:24px}footer{padding:24px;color:#596776}</style>
<header><h1>CET 2016 官方大纲样卷</h1><p>两套完整笔试、听力文字稿、官方参考答案、口试资料和写译评分样卷。这里的内容来自官方大纲样卷。题型与能力是初标，内容仍待专家审核，难度待校准。</p><p>听力源音频未提供；客观题与译文有官方参考答案。写作没有唯一答案。评分样卷保留低分作答与原文错误。</p></header>
<main><nav><select id="exam" aria-label="考试"><option value="">四级与六级</option><option>CET-4</option><option>CET-6</option></select><select id="kind" aria-label="资料类型"><option value="">全部题型</option><option value="listening">听力</option><option value="reading_cloze">选词填空</option><option value="reading_matching">长篇阅读</option><option value="reading_detail">仔细阅读</option><option value="writing">写作</option><option value="translation">翻译</option><option value="oral">口试</option><option value="archive">完整原文档案</option></select><input id="search" placeholder="搜索完整题目/语篇" aria-label="搜索"><span id="count"></span></nav><div id="results"></div></main>
<footer>原 PDF 与哈希、页码、文字恢复坐标见 source_pages.json。页图是原 PDF 渲染，图画任务与口试卡片可直接查看。文本恢复状态和专家审核状态分开保存。</footer>
<script id="data" type="application/json">__DATA__</script><script>
const data=JSON.parse(document.getElementById('data').textContent), el=id=>document.getElementById(id);
const titles={listening:'听力',reading_cloze:'选词填空',reading_matching:'长篇阅读',reading_detail:'仔细阅读',writing:'写作',translation:'翻译'};
function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n}
function disclosure(parent,label,text){const d=node('details');d.append(node('summary',label),node('pre',text));parent.append(d);return d}
function source(a,s){const d=node('details');d.append(node('summary','查看原 PDF 页图与出处'));const p=node('p','PDF 页码：'+s.pdf_pages.join(', ')+'；印刷页码：'+s.printed_pages.join(', '));d.append(p);const pdf=node('a','原官方 PDF');pdf.href='../../'+s.pdf_path+'#page='+s.pdf_pages[0];pdf.target='_blank';d.append(pdf,node('p',s.source_url,'muted'));for(const im of s.page_images||[]){const link=node('a','查看 '+im.split('/').pop());link.href=im.split('/').pop();link.target='_blank';const holder=node('p');holder.append(link);d.append(holder)}a.append(d)}
function draw(){const exam=el('exam').value,kind=el('kind').value,query=el('search').value.toLowerCase();let rows=kind==='oral'?data.oral:kind==='archive'?data.sections:data.examples.filter(x=>!kind||x.question_type===kind);rows=rows.filter(x=>(!exam||x.exam===exam||!x.exam)&&( !query||JSON.stringify(x).toLowerCase().includes(query)));el('count').textContent=rows.length+' 条资料';el('results').replaceChildren();for(const x of rows){const a=node('article');a.append(node('h2',x.exam?x.exam+' '+(titles[x.question_type]||'口试')+(x.number?' · 第 '+x.number+' 题':'')+(x.collection==='scoring_sample'?' · 官方评分样卷':''):x.section_id));a.append(node('p',x.example_id||x.section_id,'muted'));if(x.stem)a.append(node('pre',x.stem));if(x.passage)disclosure(a,'完整语篇 / 听力文字稿',x.passage);if(x.options){const o=node('ol');for(const[k,v]of Object.entries(x.options)){o.append(node('li',k+') '+v))}a.append(o)}if(x.answer)disclosure(a,'官方参考答案',x.answer);else if(x.answer_kind)a.append(node('p','官方来源未给出唯一答案','muted'));if(x.scored_responses)for(const r of x.scored_responses)disclosure(a,r.score+' 分官方评分作答（原文错误保留）',r.response);if(x.raw_source_text)disclosure(a,'完整官方原文',x.raw_source_text);for(const im of x.visual_context||[]){const img=node('img');img.src=im.split('/').pop();img.alt='官方图画任务 / 口试资料原页';img.loading='lazy';a.append(img)}source(a,x.source);a.append(node('p','文本状态：'+(x.text_quality||'原页图与原文保留')+'；专家审核：待审','muted'));el('results').append(a)}}
for(const id of['exam','kind','search'])el(id).addEventListener(id==='search'?'input':'change',draw);draw();
</script></html>'''
    (out / 'index.html').write_text(html.replace('__DATA__', payload), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--render', action='store_true', help='Render all original sample pages to PNG.')
    args = parser.parse_args()
    bundle = extract_official(args.root, render=args.render)
    out = args.root / OUTPUT_REL
    out.mkdir(parents=True, exist_ok=True)
    if args.render:
        write_layout_sheets(args.root)
    dump_json(out / 'source_pages.json', bundle['pages'])
    (out / 'reconstructed_source.txt').write_text('\n\n'.join(f'[[PDF_PAGE {p} / PRINTED_PAGE {p-5}]]\n{v["text"]}'
                                                           for p, v in bundle['pages'].items()), encoding='utf-8')
    for page in bundle['pages'].values():
        image = args.root / page['image_path']
        if image.exists():
            page['image_sha256'] = sha256(image)
    standard_questions, passages = standardize(args.root, bundle)
    main_questions = load_main_questions(args.root)
    matches = match_examples(bundle['examples'], main_questions)
    patches = recovery_patches(matches, bundle['examples'], main_questions)
    dump_json(out / 'source_pages.json', bundle['pages'])
    dump_jsonl(out / 'official_examples.jsonl', bundle['examples'])
    dump_jsonl(out / 'questions.jsonl', standard_questions)
    dump_jsonl(out / 'passages.jsonl', passages)
    dump_jsonl(out / 'oral_samples.jsonl', bundle['oral_samples'])
    dump_jsonl(out / 'source_sections.jsonl', bundle['source_sections'])
    dump_jsonl(out / 'exact_matches.jsonl', matches)
    dump_jsonl(out / 'recovery_patches.jsonl', patches)
    summary = {'source_id': SOURCE_ID, 'source_url': SOURCE_URL, 'pdf_path': PDF_REL.as_posix(),
               'source_pdf_sha256': EXPECTED_SHA256, 'source_boundaries': BOUNDARIES,
               'source_sample_pages': len(bundle['pages']), 'standard_questions': len(standard_questions),
               'official_objective_answers': 110, 'written_tasks': 4,
               'official_reference_translations': 2, 'unique_writing_answers': 0,
               'passages': len(passages), 'oral_sample_sets': len(bundle['oral_samples']),
               'scoring_sample_tasks': 4, 'official_scored_responses': 20,
               'main_questions_checked': len(main_questions),
               'match_status_counts': dict(collections.Counter(m['status'] for m in matches)),
               'exact_content_candidates': sum(bool(m['candidate_question_ids']) for m in matches),
               'true_answer_recoveries': len(patches), 'main_corpus_modified': False,
               'text_quality_counts': dict(collections.Counter(x['text_quality'] for x in bundle['examples'])),
               'visual_verification_path': (OUTPUT_REL / 'visual_verification.json').as_posix(),
               'missing_fields': ['source listening audio and timestamps', 'official individual answer explanations',
                                  'unique writing answer', 'expert review and difficulty calibration',
                                  'specific oral ontology/ability alignment', 'word-by-word text proofreading beyond saved visual checks'],
               'text_method': 'embedded original Latin font glyph metrics + neighboring character origin spacing; raw glyph stream, coordinates and all source page images preserved',
               'copyright_scope': 'official publicly released syllabus samples; no commercial third-party analyses copied'}
    dump_json(out / 'summary.json', summary)
    write_viewer(out, bundle)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
