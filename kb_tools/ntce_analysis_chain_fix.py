# -*- coding: utf-8 -*-
"""修正 upgrade-analysis 误升级链路:恢复首轮 LLM 解析草稿的诚实 method 标记

2026-10-05 首次运行 upgrade-analysis 时,analysis_upgrade_eligible 缺少
"排除已有完整结构化解析"条件,把 gen-analysis 刚生成的 296 题当成了
"待结构化的来源解析"再次加工,method 被改成 llm_structured_from_source,
但其输入凭据实际是另一份模型草稿,不是已出版来源。

本工具把这类题恢复为首轮草稿(method=llm,generation=首轮调用),
被弃用的升级稿与原因保留在 extra.llm_analysis_attempts 历史;
真正以来源解析正文为输入凭据的升级题(attempts 首项无 method)不受影响。
幂等:修复后 analysis.method 为 llm,再次运行不会触发。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '数据集' / '教资'
sys.stdout.reconfigure(encoding='utf-8')

from ntce_repair import read_rows
from ntce_io import atomic_write


def fix_question(r):
    a = r.get('analysis')
    attempts = r['extra'].get('llm_analysis_attempts') or []
    if not (isinstance(a, dict) and a.get('method') == 'llm_structured_from_source'
            and attempts and isinstance(attempts[0], dict) and attempts[0].get('method') == 'llm'):
        return False
    upgrade_attempt = dict(a)
    upgrade_attempt['discarded_reason'] = 'upgrade_input_was_itself_an_llm_draft; restored_initial_draft_chain'
    r['extra']['llm_analysis_attempts'] = [upgrade_attempt] + list(attempts[1:])
    r['analysis'] = attempts[0]
    r['content']['analysis'] = attempts[0].get('explanation')
    r['extra'].setdefault('analysis_chain_repairs', []).append({
        'kind': 'restore_initial_llm_draft_after_mis_upgrade',
        'discarded_method': 'llm_structured_from_source',
        'expert_verified': False})
    r['extra']['analysis_status'] = 'draft(llm-v2)'
    return True


def main():
    fixed = 0
    for qf in sorted(OUT.glob('questions/*/*/*.jsonl')):
        recs = read_rows(qf)
        touched = [r for r in recs if fix_question(r)]
        if touched:
            atomic_write(qf, '\n'.join(json.dumps(r, ensure_ascii=False) for r in recs) + '\n')
            fixed += len(touched)
            print('  %s/%s/%s 修复 %d 题' % (qf.parent.parent.name, qf.parent.name, qf.stem, len(touched)))
    print('chain-fix 完成:恢复 %d 题的首轮 LLM 解析草稿' % fixed)
    from ntce_repair import repair
    repair(skip_outline=True)


if __name__ == '__main__':
    main()
