"""准备20题有完整原料的解析样本ID；本脚本不调用API、不写主库。"""
import hashlib
import json
import re
from pathlib import Path
from build_kb import ROOT, OUT, load_text, parse_answers
from ntce_repair import read_rows, write_rows
from llm_batch import analysis_eligible, question_brief
from ntce_io import atomic_write


def prepare():
    qs = [q for path in sorted((OUT / 'questions').glob('*/*/*.jsonl')) for q in read_rows(path)]
    materials = {m['material_id']: m['text'] for path in (OUT / 'materials').glob('*/*/*.jsonl') for m in read_rows(path)}
    cfg = {'LLM_MODEL': 'deepseek-flash'}
    cache, chosen, seen = {}, [], set()
    for level, subject in [('xiaoxue', 'zonghe'), ('youer', 'zonghe'), ('zhongxue', 'zonghe'), ('zhongxue', 'jiaoyuzhishi')]:
        group = []
        candidates = sorted([q for q in qs if (q['level'], q['subject']) == (level, subject)],
                            key=lambda q: hashlib.sha256(q['question_id'].encode()).hexdigest())
        for q in candidates:
            material = materials.get(q.get('material_id'))
            if not analysis_eligible(q, material, cfg):
                continue
            stem = q['content']['stem']
            if subject == 'zonghe' and not re.search(r'老师|教师|教学|学习|教育|学生|幼儿', stem):
                continue
            normalized = re.sub(r'\s|[，。,.？?()（）]', '', stem)
            if normalized in seen:
                continue
            origin = q['source']['origin_file']
            answer_file = next((source['path'] for source in q['source']['files'] if source['role'] == 'answer_raw'), None)
            if not answer_file:
                continue
            if origin not in cache:
                cache[origin] = load_text(ROOT / origin)
            if answer_file not in cache:
                cache[answer_file] = parse_answers(load_text(ROOT / answer_file))
            number = q['extra'].get('source_question_number')
            if cache[origin].count(stem) != 1 or cache[answer_file].get(number) != q['content']['answer']:
                continue
            seen.add(normalized)
            group.append({'question_id': q['question_id'], 'stem': stem, 'options': q['content']['options'],
                'source_answer': q['content']['answer'], 'source_files': q['source']['files'],
                'source_type_verification': q['review']['type_source_verification'],
                'stem_sha256': hashlib.sha256(stem.encode('utf-8')).hexdigest(),
                'full_input_bytes': len(question_brief(q, material).encode('utf-8')),
                'official_answer_verified': False})
            if len(group) == 5:
                break
        chosen.extend(group)
    if len(chosen) != 20:
        raise RuntimeError('完整安全候选不足20条，保留队列而不降低上下文要求：%d' % len(chosen))
    write_rows(OUT / 'review/llm_analysis_plan.jsonl', chosen)
    atomic_write(OUT / 'review/llm_analysis_question_ids.json', json.dumps([q['question_id'] for q in chosen], ensure_ascii=False, indent=2))
    print(json.dumps({'questions': len(chosen), 'question_ids': [q['question_id'] for q in chosen],
        'input_payload_bytes': sum(q['full_input_bytes'] for q in chosen), 'api_called': False}, ensure_ascii=False, indent=2))
    return chosen


if __name__ == '__main__':
    prepare()
