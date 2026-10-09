"""Reconcile stale passage links using bounded original content identity.

Preserved IDs and parser numbers never establish an original question number.
Only a full stem and all four choices, or a full matching statement, can do so.
"""
import copy
import json
import re
from datetime import datetime
from pathlib import Path

from cet_common import load_jsonl, jsonl_dumps
from fill_answers import read_source, question_blocks, ref_for
from restore_original_stems import original_blocks, source_regions

KB = Path(__file__).resolve().parents[1]
ROOT = KB.parents[1]


def layout_normalized(text):
    """Fold layout only; preserve word boundaries, decimals and other symbols."""
    value = ''.join(chr(ord(char) - 0xFEE0) if 0xFF01 <= ord(char) <= 0xFF5E else ' ' if char == '\u3000' else char
                    for char in (text or ''))
    value = value.translate(str.maketrans({'‘': "'", '’': "'", '“': '"', '”': '"'}))
    return re.sub(r'\s+', ' ', value).strip()


def reading_spans(text):
    start = re.search(r'Reading\s+Comprehension', text, re.I)
    if not start:
        return []
    stop = re.search(r'(?im)^\s*Part\s*(?:IV|Ⅳ)\b', text[start.end():])
    end = start.end() + stop.start() if stop else len(text)
    sections = list(re.finditer(r'(?im)^\s*Section\s+([ABC])\b', text[start.end():end]))
    result = []
    for i, section in enumerate(sections):
        a = start.end() + section.end()
        b = start.end() + sections[i + 1].start() if i + 1 < len(sections) else end
        if section[1].upper() == 'B':
            result.append(('matching', a, b))
        elif section[1].upper() == 'C':
            headings = list(re.finditer(r'(?im)^\s*Passage\s+(?:One|Two)\b', text[a:b]))
            for j, heading in enumerate(headings):
                lo = a + heading.end()
                hi = a + headings[j + 1].start() if j + 1 < len(headings) else b
                result.append(('reading', lo, hi))
    return result


def span_article(raw, kind):
    blocks = list(question_blocks(raw)) if kind == 'matching' else original_blocks(raw, '仔细阅读')
    if kind == 'matching':
        blocks = [block for block in blocks if 36 <= block[0] <= 45]
    if not blocks:
        return None
    article_end = blocks[0][2]
    article = raw[:article_end]
    # Remove only the printed range prompt, not any article sentences.
    article = re.sub(r'(?im)^\s*Questions?[^\n]*following\s+passage[^\n]*\n?', '', article)
    if kind == 'matching':
        # The resource text stores paragraph bodies; source labels remain in
        # the original locator and the separately restored paragraphs field.
        article = re.sub(r'(?m)^\s*(?:\[[A-Z]\]|[A-Z][)）])\s*', '', article)
    return re.sub(r'\s+', ' ', article).strip(), article_end, blocks


def matching_paragraphs(raw):
    marks = list(re.finditer(r'(?m)^\s*(?:\[([A-Z])\]|([A-Z])[)）])\s*', raw))
    letters = [m[1] or m[2] for m in marks]
    if not letters or letters != [chr(65 + i) for i in range(len(letters))]:
        return []
    return [{'letter': letters[i], 'text': layout_normalized(raw[m.end():marks[i + 1].start() if i + 1 < len(marks) else len(raw)])}
            for i, m in enumerate(marks)]


def source_matches(question, passage, text, offsets, path, root=ROOT):
    """Return only full identities inside the source span containing this article."""
    kind = 'matching' if question.get('question_type') == '长篇阅读' else 'reading'
    if passage.get('kind') not in ({'matching'} if kind == 'matching' else {'reading', 'careful'}):
        return []
    target = layout_normalized(re.sub(r'^\s*\d{1,2}\s*[.、．]\s*', '', question.get('content', {}).get('stem') or ''))
    article_target = layout_normalized(passage.get('text'))
    if len(target) < 12 or len(article_target) < 25:
        return []
    options = question.get('content', {}).get('options') or {}
    if kind == 'reading' and (set(options) != set('ABCD') or any(not layout_normalized(v) for v in options.values())):
        return []
    matches = []
    for region_a, region_b in source_regions(question, text):
        region = text[region_a:region_b]
        for span_kind, span_a, span_b in reading_spans(region):
            if kind != span_kind:
                continue
            a, b = region_a + span_a, region_a + span_b
            raw = text[a:b]
            extracted = span_article(raw, kind)
            if not extracted:
                continue
            article, article_end, blocks = extracted
            if article_target != layout_normalized(article):
                continue
            paragraph_labels = []
            if kind == 'matching':
                source_paragraphs = matching_paragraphs(raw[:article_end])
                saved = passage.get('extra', {}).get('paragraphs') or []
                if not isinstance(saved, list):
                    continue
                saved_paragraphs = [{'letter': item.get('letter'), 'text': layout_normalized(item.get('text'))} for item in saved]
                if not source_paragraphs or source_paragraphs != saved_paragraphs:
                    continue
                paragraph_labels = [p['letter'] for p in source_paragraphs]
            printed = re.search(r'Questions?\s+(\d+)\s+(?:to|and)\s+(\d+)\s+are\s+based', raw, re.I)
            actual = [block[0] for block in blocks]
            warnings = []
            if printed and actual and any(not int(printed[1]) <= n <= int(printed[2]) for n in actual):
                warnings.append({'status': 'printed_range_conflicts_with_explicit_numbered_blocks',
                                 'printed_range': [int(printed[1]), int(printed[2])], 'actual_numbered_blocks': actual,
                                 'printed_excerpt': printed[0], 'authentication_status': 'pending_original_official_paper_verification'})
            for number, block, block_a, block_b in blocks:
                if kind == 'matching':
                    stem = block
                    parsed = {}
                else:
                    marks = list(re.finditer(r'(?<!\S)([A-D])[)）.．]\s*', block))
                    if [m[1] for m in marks] != list('ABCD'):
                        continue
                    stem = block[:marks[0].start()]
                    parsed = {m[1]: block[m.end():marks[i + 1].start() if i + 1 < len(marks) else len(block)].strip()
                              for i, m in enumerate(marks)}
                    if any(layout_normalized(options[letter]) != layout_normalized(parsed[letter]) for letter in 'ABCD'):
                        continue
                if target != layout_normalized(stem):
                    continue
                question_ref = ref_for(path, root, offsets, a + block_a, a + block_b, number)
                question_ref['role'] = 'original_question_identity'
                passage_ref = ref_for(path, root, offsets, a, a + article_end, None)
                passage_ref['role'] = 'original_passage_boundary'
                matches.append({'passage_id': passage['resource_id'], 'source_question_number': number,
                                'question_source': question_ref, 'passage_source': passage_ref,
                                'normalization': 'fullwidth_ASCII_equivalent_quotes_and_whitespace_only_words_numbers_superscripts_symbols_preserved',
                                'complete_article_identity': 'equal_to_source_article_outside_question_boundaries',
                                'verified_paragraph_labels': paragraph_labels,
                                'source_boundary_warnings': warnings,
                                'method': 'same_original_file_bounded_reading_section_exact_full_stem_and_all_choices' if kind == 'reading'
                                          else 'same_original_file_bounded_Section_B_exact_full_statement',
                                'review_status': 'source_extracted_pending_subject_expert'})
    return matches


def restore_bounded_articles(passages, root, cache):
    for passage in passages:
        kind = 'matching' if passage.get('kind') == 'matching' else 'reading'
        question = {'exam': passage.get('exam'), 'source': {'year': passage.get('year'), 'paper': passage.get('paper')}}
        current = layout_normalized(passage.get('text'))
        candidates = []
        for name in sorted(original_paths(passage)):
            if name not in cache:
                try:
                    cache[name] = read_source(root / name)
                except Exception:
                    cache[name] = ('', [])
            text, offsets = cache[name]
            for region_a, region_b in source_regions(question, text):
                for span_kind, span_a, span_b in reading_spans(text[region_a:region_b]):
                    if span_kind != kind:
                        continue
                    a, b = region_a + span_a, region_a + span_b
                    extracted = span_article(text[a:b], kind)
                    if not extracted:
                        continue
                    article, article_end, _ = extracted
                    complete = layout_normalized(article)
                    # A shared opening is insufficient: the complete shorter
                    # text must agree up to the explicit source boundary.
                    if min(len(current), len(complete)) < 300 or not (current.startswith(complete) or complete.startswith(current)):
                        continue
                    ref = ref_for(root / name, root, offsets, a, a + article_end, None)
                    ref['role'] = 'original_complete_article'
                    candidates.append({'text': article, 'source': ref,
                                       'method': 'explicit_reading_section_and_passage_heading_to_first_original_question_block',
                                       'normalization': 'fullwidth_ASCII_equivalent_quotes_and_whitespace_only_words_numbers_superscripts_symbols_preserved',
                                       'evidence': 'complete_source_article_prefix_of_old_resource_with_question_contamination' if current.startswith(complete)
                                                   else 'complete_old_resource_prefix_of_unique_source_article_truncated_at_source_boundary',
                                       'review_status': 'source_extracted_pending_subject_expert'})
        identities = {layout_normalized(item['text']) for item in candidates}
        if len(identities) != 1:
            continue
        candidate = candidates[0]
        if current == layout_normalized(candidate['text']) and passage.get('extra', {}).get('complete_article_recovery'):
            passage['extra']['complete_article_recovery']['normalization'] = candidate['normalization']
        if current != layout_normalized(candidate['text']):
            ex = passage.setdefault('extra', {})
            history = ex.setdefault('text_history', [])
            entry = {'text': passage['text'], 'reason': candidate['evidence'], 'source': candidate['source'],
                     'status': 'retained_for_audit_not_active'}
            if entry not in history:
                history.append(entry)
            passage['text'] = candidate['text']
            ex['complete_article_recovery'] = candidate


def original_paths(row):
    return {f['path'] for f in row.get('source', {}).get('files', []) if f.get('role') == 'original_content' and f.get('path')}


def paper_key(row):
    source = row.get('source', {})
    return row.get('exam'), source.get('year') or row.get('year'), source.get('paper') or row.get('paper')


def retain_reference(row, passage_id, reason):
    if not passage_id:
        return
    entry = {'passage_id': passage_id, 'reason': reason, 'status': 'retained_for_audit_not_active'}
    history = row.setdefault('extra', {}).setdefault('passage_reference_history', [])
    if entry not in history:
        history.append(entry)


def reconcile(kb=KB, root=ROOT):
    passage_path = kb / 'passages/reading.jsonl'
    passages = load_jsonl(passage_path)
    pmap = {p['resource_id']: p for p in passages}
    question_files = {path: load_jsonl(path) for path in sorted((kb / 'questions').rglob('*.jsonl'))}
    questions = [q for rows in question_files.values() for q in rows]
    original_mismatches = []
    targets = {p['resource_id'] for p in passages if p.get('extra', {}).get('passage_reference_review')}
    for q in questions:
        ex = q.get('extra', {})
        pid = ex.get('passage_id')
        p = pmap.get(pid)
        if p and (ex.get('active') is False or q['question_id'] not in p.get('extra', {}).get('question_ids', [])):
            targets.add(pid)
            if q['question_id'] not in p.get('extra', {}).get('question_ids', []):
                original_mismatches.append(q['question_id'])
        if ex.get('passage_binding'):
            targets.update(h['passage_id'] for h in ex.get('passage_reference_history', []) if h.get('passage_id') in pmap)
    # A source warning on this affected c1 led to the paired c2 audit; keep the
    # check scoped to the same existing source paper rather than all old papers.
    if 'cet4-2015-12-p2-reading-c1' in targets:
        targets.add('cet4-2015-12-p2-reading-c2')
    target_rows = [p for p in passages if p['resource_id'] in targets]
    by_paper = {}
    for p in target_rows:
        by_paper.setdefault(paper_key(p), []).append(p)
    cache = {}
    restore_bounded_articles(target_rows, root, cache)
    checked = []
    for q in questions:
        ex = q.setdefault('extra', {})
        old_pid = ex.get('passage_id')
        candidates = by_paper.get(paper_key(q), [])
        if not candidates or q.get('question_type') not in ('长篇阅读', '仔细阅读'):
            continue
        if old_pid not in targets and not ex.get('passage_binding'):
            continue
        if ex.get('active') is False:
            retain_reference(q, old_pid, 'inactive_parser_artifact_cannot_reference_an_active_reading_passage')
            ex['passage_id'] = None
            ex['passage_binding'] = {'status': 'quarantined_inactive_parser_artifact'}
        else:
            matches = []
            for p in candidates:
                for name in sorted(original_paths(q) & original_paths(p)):
                    if name not in cache:
                        try:
                            cache[name] = read_source(root / name)
                        except Exception:
                            cache[name] = ('', [])
                    text, offsets = cache[name]
                    matches += source_matches(q, p, text, offsets, root / name, root)
            identities = {(m['passage_id'], m['source_question_number']) for m in matches}
            if len(identities) == 1:
                evidence = matches[0]
                if old_pid and old_pid != evidence['passage_id']:
                    retain_reference(q, old_pid, 'replaced_by_unique_original_content_identity')
                ex['passage_id'] = evidence['passage_id']
                ex['source_question_number'] = evidence['source_question_number']
                ex['passage_binding'] = dict(evidence, status='source_identity_verified_pending_expert_review')
            else:
                retain_reference(q, old_pid, 'full_stem_and_all_options_do_not_prove_unique_original_question_identity')
                ex['passage_id'] = None
                ex['scoring_eligible'] = False
                ex['source_identity_review'] = {'status': 'pending',
                                                 'reason': 'mixed_stem_or_options_no_unique_original_question_identity',
                                                 'automatic_scoring': 'ineligible_until_full_source_identity_is_proven_and_expert_reviewed'}
                ex['passage_binding'] = {'status': 'quarantined_no_unique_source_identity',
                                         'candidate_identity_count': len(identities),
                                         'review_status': 'pending_original_source_boundary_and_subject_expert'}
        checked.append({'question_id': q['question_id'], **copy.deepcopy(ex['passage_binding'])})
    for p in target_rows:
        ex = p.setdefault('extra', {})
        fresh = [q['question_id'] for q in questions if q['extra'].get('passage_id') == p['resource_id'] and q['extra'].get('active') is not False]
        old = ex.get('question_ids', [])
        if old != fresh:
            history = ex.setdefault('question_reference_history', [])
            entry = {'question_ids': copy.deepcopy(old), 'reason': 'reconciled_from_unique_original_content_identity', 'status': 'retained_for_audit_not_active'}
            if entry not in history:
                history.append(entry)
            ex['question_ids'] = fresh
        ex['passage_reference_review'] = {'method': 'full_original_question_identity_and_article_boundary',
                                          'status': 'source_extracted_pending_subject_expert',
                                          'active_question_ids': fresh}
    for path, rows in question_files.items():
        path.write_text('\n'.join(jsonl_dumps(q) for q in rows) + '\n', encoding='utf-8')
    passage_path.write_text('\n'.join(jsonl_dumps(p) for p in passages) + '\n', encoding='utf-8')
    report_path = kb / 'manifest/passage_reference_repair_report.json'
    prior = json.loads(report_path.read_text('utf-8')) if report_path.exists() else {}
    result = {'frozen_at': prior.get('frozen_at') or datetime.now().astimezone().isoformat(),
              'original_structure_error_ids': prior.get('original_structure_error_ids', original_mismatches),
              'checked_passage_ids': sorted(targets), 'questions': checked,
              'complete_article_recoveries': [{'resource_id': p['resource_id'], **p['extra']['complete_article_recovery']}
                                              for p in target_rows if p.get('extra', {}).get('complete_article_recovery')],
              'summary': {'original_structure_errors': len(prior.get('original_structure_error_ids', original_mismatches)),
                          'source_identity_verified': sum(q['status'] == 'source_identity_verified_pending_expert_review' for q in checked),
                          'restored_original_error_backlinks_verified': sum(q['question_id'] in prior.get('original_structure_error_ids', original_mismatches) and q['status'] == 'source_identity_verified_pending_expert_review' for q in checked),
                          'complete_articles_restored_with_history': sum(bool(p.get('extra', {}).get('complete_article_recovery')) for p in target_rows),
                          'inactive_parser_artifact_links_cleared': sum(q['status'] == 'quarantined_inactive_parser_artifact' for q in checked),
                          'unproven_active_links_quarantined': sum(q['status'] == 'quarantined_no_unique_source_identity' for q in checked)},
              'limits': 'Existing five source papers only; no ID renumbering, answer synthesis, expert approval, or wider paper reparse.'}
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    print(json.dumps(reconcile()['summary'], ensure_ascii=False))
