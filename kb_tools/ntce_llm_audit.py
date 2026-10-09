"""只读复算教资初标资格、保留/待补结果及累计实际模型费用。"""
import json
from collections import Counter, defaultdict
from build_kb import OUT
from ntce_repair import read_rows
from llm_batch import input_status
from ntce_io import atomic_write


def audit():
    questions = [q for path in sorted((OUT / 'questions').glob('*/*/*.jsonl')) for q in read_rows(path)]
    materials = {m['material_id']: m['text'] for path in (OUT / 'materials').glob('*/*/*.jsonl') for m in read_rows(path)}
    outcomes = []
    for q in questions:
        context = input_status(q, materials.get(q.get('material_id')))
        result = q['extra'].get('llm_tag_result', {})
        outcomes.append({'question_id': q['question_id'], 'input_status': context,
            'currently_mapped': bool(q['knowledge_node_ids']), 'tagger': q['review'].get('tagger'),
            'saved_llm_result_status': result.get('status'),
            'saved_llm_node_count': len(result.get('nodes') or []),
            'input_validation_status': result.get('input_validation_status'),
            'response_model': result.get('generation', {}).get('response_model')})
    usage = read_rows(OUT / 'review/llm_usage.jsonl') if (OUT / 'review/llm_usage.jsonl').exists() else []
    sample_path = OUT / 'review/llm_analysis_sample.jsonl'
    samples = read_rows(sample_path) if sample_path.exists() else []
    question_index = {q['question_id']: q for q in questions}
    sample_errors = []
    sample_markdown = ['# 20题逐题解析草稿样本', '', '以下均为模型草稿，尚无专家审核。原题与原答案是输入凭据；没有取得已出版的逐题解析依据。', '']
    for sample in samples:
        qid = sample['question_id']
        current = question_index.get(qid)
        a = sample.get('analysis') or {}
        if not current or current['content']['stem'] != sample['stem'] or current['content']['options'] != sample['options'] or current['content']['answer'] != sample['source_answer']:
            sample_errors.append({'question_id': qid, 'reason': 'current_content_changed_since_model_input'})
        elif input_status(current, materials.get(current.get('material_id')))['status'] != 'complete':
            sample_errors.append({'question_id': qid, 'reason': 'current_context_is_not_complete'})
        elif current['review'].get('type_source_verification', {}).get('status') != 'verified_choice_task_and_section':
            sample_errors.append({'question_id': qid, 'reason': 'current_source_type_not_verified'})
        if not all(a.get(field) for field in ('key_info', 'option_compare', 'trace_back')):
            sample_errors.append({'question_id': qid, 'reason': 'three_segment_body_missing'})
        sample_markdown.extend(['## ' + qid, '', sample['stem'], ''])
        sample_markdown.extend(option['key'] + '. ' + option['text'] for option in sample['options'])
        sample_markdown.extend(['', '原答案：' + str(sample['source_answer']) + '；响应状态：' + str(sample['result']['status']), '',
            '**关键信息：** ' + (a.get('key_info') or '无'), '', '**逐项比较：** ' + (a.get('option_compare') or '无'), '',
            '**判断步骤：** ' + (a.get('trace_back') or '无'), '', '**逐题解释：** ' + (a.get('explanation') or '无'), '',
            '实际模型：' + str(sample['result']['generation'].get('response_model')) + '；方法：llm；专家审核：未完成。', '', '原料来源：', ''])
        for source in sample['source_files']:
            sample_markdown.append('- ' + source['role'] + '：' + source['path'] + '；定位 ' + json.dumps(source.get('locator'), ensure_ascii=False))
        sample_markdown.append('')
    models = defaultdict(list)
    for call in usage:
        models[call.get('response_model') or 'no_response_model'].append(call)
    model_summary = {}
    for name, calls in sorted(models.items()):
        model_summary[name] = {'calls': len(calls), 'status': dict(Counter(call['status'] for call in calls)),
            'prompt_tokens': sum(call.get('usage', {}).get('prompt_tokens', 0) for call in calls),
            'completion_tokens': sum(call.get('usage', {}).get('completion_tokens', 0) for call in calls),
            'conservative_cost_cny': round(sum(call.get('conservative_cost_cny', 0) for call in calls), 8)}
    report = {'questions': len(questions),
        'eligible_complete_context': sum(o['input_status']['status'] == 'complete' for o in outcomes),
        'skipped_context': sum(o['input_status']['status'] != 'complete' for o in outcomes),
        'skip_reasons': dict(Counter(reason for o in outcomes for reason in o['input_status']['reasons'])),
        'mapped_without_current_llm_tagger': sum(o['currently_mapped'] and o['tagger'] != 'llm-v2' for o in outcomes),
        'current_llm_mapped': sum(o['currently_mapped'] and o['tagger'] == 'llm-v2' for o in outcomes),
        'saved_llm_results': sum(o['saved_llm_result_status'] is not None for o in outcomes),
        'saved_llm_successful_drafts': sum(o['saved_llm_result_status'] == 'draft_pending_expert' for o in outcomes),
        'saved_llm_unmatched': sum(o['saved_llm_result_status'] == 'unmatched' for o in outcomes),
        'invalidated_context_results': sum(o['input_validation_status'] == 'insufficient_context_pending_rework' for o in outcomes),
        'still_unmapped': sum(not o['currently_mapped'] for o in outcomes),
        'eligible_still_unmapped': sum(not o['currently_mapped'] and o['input_status']['status'] == 'complete' for o in outcomes),
        'usage_by_actual_model': model_summary,
        'conservative_total_cny': round(sum(call.get('conservative_cost_cny', 0) for call in usage), 8),
        'hard_budget_cny': 5,
        'analysis_sample': {'questions': len(samples), 'status': dict(Counter(sample['result']['status'] for sample in samples)),
            'current_input_validation_errors': sample_errors, 'expert_verified': False},
        'legacy_48_question_pilot': {'calls': 18, 'prompt_tokens': 11871, 'completion_tokens': 2791,
            'actual_model': None, 'model_status': 'not_recorded_in_legacy_pipeline', 'cost_cny': None},
        'note': '资格按当前完整上下文重算；保留的历史模型草稿不等于仍在使用。旧48题未保存实际模型，不能追溯套用价格。'}
    atomic_write(OUT / 'review/llm_audit.json', json.dumps(report, ensure_ascii=False, indent=2))
    atomic_write(OUT / 'review/llm_context_audit.jsonl', ''.join(json.dumps(o, ensure_ascii=False) + '\n' for o in outcomes))
    atomic_write(OUT / 'review/llm_analysis_sample.md', '\n'.join(sample_markdown) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == '__main__':
    audit()
