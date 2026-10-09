"""复核空参考答案是否本来只有“参见解析”，保存逐题定位与各学段原文样例。"""
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from build_kb import OUT, ROOT, load_text, parse_answers, classify_answer
from ntce_repair import read_rows, write_rows
from ntce_io import atomic_write


def audit():
    cache, records, samples = {}, [], defaultdict(list)
    for qfile in sorted((OUT / 'questions').glob('*/*/*.jsonl')):
        for q in read_rows(qfile):
            if q['content']['answer_status'] != 'reference_only' and not any(
                    change.get('before', {}).get('answer_status') in ('reference', 'reference_only', 'derived_reference',
                                                                      'original_reference_draft_pending_expert')
                    for change in q['extra'].get('source_repairs', [])):
                continue
            source = next((f for f in q['source'].get('files', []) if f['role'] == 'answer_raw'), None)
            if not source:
                record = {'question_id': q['question_id'], 'level': q['level'], 'result': 'answer_file_missing'}
            else:
                path = ROOT / source['path']
                if path not in cache:
                    raw_text = load_text(path)
                    cache[path] = raw_text, parse_answers(raw_text)
                raw_text, parsed = cache[path]
                num = q['extra'].get('source_question_number', q['extra']['paper_order'])
                raw_answer = parsed.get(num)
                status, answer = classify_answer(raw_answer)
                result = 'source_only_refers_to_missing_analysis' if status == 'reference' else 'source_explicit_answer_conflict' if status == 'source_conflict' else 'source_contains_answer_candidate' if answer else 'source_placeholder_missing_answer' if raw_answer else 'source_number_missing'
                record = {'question_id': q['question_id'], 'level': q['level'], 'result': result,
                          'answer_file': source['path'], 'source_question_number_candidate': num,
                          'number_alignment': q['extra'].get('source_boundary_verification', {}).get('status', 'paper_order_unverified'),
                          'raw_answer': raw_answer, 'parsed_status': status,
                          'stem_excerpt': q['content']['stem'][:160], 'expert_verified': False}
                exact = re.search(r'(?<!\d)' + str(num) + r'\s*[、.．:：]\s*' + re.escape(raw_answer.strip() if raw_answer else '#NO_ANSWER#'), raw_text)
                if exact:
                    record['locator'] = {'decoded_csv_character_start': exact.start(), 'decoded_csv_character_end': exact.end()}
                    record['raw_context'] = raw_text[max(0, exact.start() - 45):exact.end() + 70]
                if len(samples[q['level']]) < 2 and status == 'reference' and len(q['content']['stem']) >= 10:
                    samples[q['level']].append(record)
            records.append(record)
    review = OUT / 'review'
    write_rows(review / 'reference_answer_source_audit.jsonl', records)
    summary = {'records': len(records), 'by_result': dict(Counter(r['result'] for r in records)),
               'samples_by_level': dict(samples),
               'note': '题号候选未全部唯一对齐；存在正文的候选仍须确认来源边界，不能直接替换答案。参见解析本身不能恢复不存在的正文。'}
    atomic_write(review / 'reference_answer_source_audit_summary.json', json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k != 'samples_by_level'}, ensure_ascii=False, indent=2))
    return summary


if __name__ == '__main__':
    audit()
