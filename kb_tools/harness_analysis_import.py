# -*- coding: utf-8 -*-
"""导入会话模型生成的解析草稿到教资KB(不经过外部API,费用计入ZCode配额)

输入: 审查/harness_batches/results/batch_*_results.jsonl
  每行 {"question_id","status":"draft|answer_disputed|unanswerable",
        "analysis":{"key_info","option_compare","trace_back","explanation"},"note"?}

规则:
- draft 必须四段非空才写 analysis;否则降级记录 result 不写解析。
- provenance 诚实: method='harness_llm', model 记录会话模型名,
  generation.channel='zcode_session_subagent'; 不写 token 计费假数据。
- 已有 analysis(含 method)或 content.analysis 的题跳过,幂等可重跑。
- 只改题目记录,不触发 repair;复算由调用方另行执行。
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '数据集' / '教资'
BATCH_DIR = ROOT / '审查/harness_batches'
MODEL_LABEL = 'GLM-5.3-Flash(session)'
sys.stdout.reconfigure(encoding='utf-8')

from ntce_repair import read_rows
from ntce_io import atomic_write


def load_index():
    index = {}
    for qf in sorted(OUT.glob('questions/*/*/*.jsonl')):
        recs = read_rows(qf)
        for i, r in enumerate(recs):
            index[r['question_id']] = (qf, recs, i)
    return index


def main():
    index = load_index()
    imported = disputed = unanswerable = skipped = invalid = 0
    touched_files = set()
    for rf in sorted(BATCH_DIR.glob('results/batch_*_results.jsonl')):
        for line in rf.read_text(encoding='utf-8').split('\n'):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                invalid += 1
                continue
            qid = item.get('question_id')
            entry = index.get(qid)
            if not entry:
                invalid += 1
                continue
            qf, recs, i = entry
            r = recs[i]
            if r.get('analysis') or r['content'].get('analysis'):
                skipped += 1
                continue
            prev = r['extra'].get('llm_analysis_result')
            if isinstance(prev, dict) and isinstance(prev.get('generation'), dict) \
                    and prev['generation'].get('channel') == 'zcode_session_subagent':
                skipped += 1
                continue
            status = item.get('status')
            a = item.get('analysis') if isinstance(item.get('analysis'), dict) else {}
            valid_draft = (status == 'draft'
                           and all(isinstance(a.get(f), str) and a[f].strip()
                                   for f in ('key_info', 'option_compare', 'trace_back', 'explanation')))
            r['extra']['llm_analysis_result'] = {'status': status if status in ('draft', 'answer_disputed', 'unanswerable') else 'invalid_response',
                                                 'result': item, 'input_context': {'status': 'complete'},
                                                 'generation': {'channel': 'zcode_session_subagent', 'model': MODEL_LABEL,
                                                                'batch': rf.stem, 'generated_at': datetime.now(timezone.utc).isoformat()}}
            if status == 'draft' and not valid_draft:
                r['extra']['llm_analysis_result']['status'] = 'invalid_four_section_response'
                invalid += 1
                touched_files.add(qf)
                continue
            if valid_draft:
                r['content']['analysis'] = a['explanation']
                r['analysis'] = {**a, 'status': 'llm_draft_pending_expert', 'expert_verified': False,
                                 'correct_answer': r['content']['answer'], 'method': 'harness_llm', 'model': MODEL_LABEL,
                                 'generation': r['extra']['llm_analysis_result']['generation'],
                                 'input_evidence_files': r['source'].get('files', []),
                                 'input_context': {'status': 'complete'},
                                 'source_note': '原始答案与题干是输入凭据；会话模型解析没有已出版来源，考试范围条款不能证明具体答案。',
                                 'knowledge_node_ids': r['knowledge_node_ids'], 'ability_ids': r.get('ability_ids', [])}
                r['analysis']['exam_requirement_ids'] = r.get('exam_requirement_ids', [])
                r['extra']['analysis_status'] = 'draft(harness-v1)'
                imported += 1
            elif status == 'answer_disputed':
                disputed += 1
            elif status == 'unanswerable':
                unanswerable += 1
            else:
                invalid += 1
            touched_files.add(qf)
    for qf in sorted(touched_files):
        _, recs, _ = next((v for v in index.values() if v[0] == qf))
        atomic_write(qf, '\n'.join(json.dumps(r, ensure_ascii=False) for r in recs) + '\n')
    print('导入 %d, 答案存疑 %d, 无法作答 %d, 跳过 %d, 无效 %d, 文件 %d 个'
          % (imported, disputed, unanswerable, skipped, invalid, len(touched_files)))


if __name__ == '__main__':
    main()
