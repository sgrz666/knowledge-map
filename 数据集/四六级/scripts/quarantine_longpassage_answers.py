# -*- coding: utf-8 -*-
"""隔离长篇阅读中违反「一一对应」约束的答案。

依据（题型硬约束）：
  长篇阅读是段落匹配题（kind=matching），每题对应一个段落，**答案字母必须互异**。
  同一题型下49 卷答案全唯一、38 卷有重复——若段落匹配允许重复，则不该有此分化，
  故重复卷的答案存在错位（按文本位置顺序写回，而题号顺序与文本出现顺序不一致）。

范围严格限定：
  - 只处理「长篇阅读」。**明确排除「选词填空」**——它是 15 选 10 填 10 空，
    同一字母可重复使用（实测 75% 的卷都有重复，属正常现象）。
  - 只处理答案有重复的卷；答案全唯一的卷不动（49 卷）。

动作：清空 content.answer 回到 null，原值存入 extra.answer_quarantine，
**保留 difficulty**（难度模型只用文本特征，与答案无关，无需清除）。
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
KB = ROOT / '数据集/四六级'
TARGET_TYPE = '长篇阅读'
MIN_QUESTIONS = 5          # 题目太少不做统计判断


def read_rows(p):
    rows = []
    for line in Path(p).open(encoding='utf-8'):
        if line.strip():
            x = json.loads(line)
            rows.extend(x if isinstance(x, list) else [x])
    return rows


def write_rows(p, rows):
    p.write_text(''.join(json.dumps(r, ensure_ascii=False).replace('\x85', '\\u0085').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029') + '\n' for r in rows),
                 encoding='utf-8')


def main():
    dry = '--dry-run' in sys.argv
    report = {
        'generated': '2026-10-08',
        'action': 'quarantine answers violating one-to-one constraint (long-passage matching)',
        'scope': {'question_type': TARGET_TYPE, 'min_questions': MIN_QUESTIONS,
                  'excluded': '选词填空 (15选10填10空，字母可重复，属正常)',
                  },
        'baseline': {}, 'papers': [],
        'quarantined_questions': 0, 'papers_affected': 0,
    }

    cache = {}
    healthy = affected = 0
    for p in sorted((KB / 'questions').glob('cet*/*.jsonl')):
        key = f'{p.parent.name}/{p.name}'
        rows = read_rows(p)
        cache[key] = rows
        qs = [r for r in rows
              if r.get('question_type') == TARGET_TYPE and (r.get('content') or {}).get('answer')]
        if len(qs) < MIN_QUESTIONS:
            continue
        answers = [r['content']['answer'] for r in qs]
        if len(set(answers)) == len(answers):
            healthy += 1
            continue
        affected += 1
        # 隔离：整卷该题型的答案全部清空。
        # 理由：错位是系统性的，逐题猜哪些对哪些错不可靠；整卷隔离更保守。
        cleared = 0
        dups = sorted(a for a, c in Counter(answers).items() if c > 1)
        for r in qs:
            old = r['content']['answer']
            r['content']['answer'] = None
            r.setdefault('extra', {})['answer_quarantine'] = {
                'status': 'quarantined_one_to_one_violation',
                'original_answer': old,
                'paper_duplicates': dups,
                'paper_answer_sequence': answers,
                'reason': 'long-passage matching requires distinct paragraph letters; '
                          'duplicates indicate systematic misalignment, '
                          'no verified answer key available for correction',
                'quarantined_at': '2026-10-08',
                'needs': 'human review or acquisition of an authorized answer key',
            }
            cleared += 1
        report['papers'].append({
            'paper': key, 'questions': len(qs), 'duplicates': dups,
            'quarantined': cleared, 'answer_sequence': answers,
        })
        report['quarantined_questions'] += cleared
        if not dry:
            write_rows(p, rows)

    report['baseline'] = {
        'papers_with_unique_answers_untouched': healthy,
        'papers_violating_constraint': affected,
    }
    report['papers_affected'] = affected

    print('=== 长篇阅读答案隔离 ===')
    print(f'答案全唯一（不动）: {healthy} 卷')
    print(f'违反一一对应（隔离）: {affected} 卷 / {report["quarantined_questions"]} 题')
    print()
    for r in report['papers'][:15]:
        print(f"  {r['paper']:26s} {r['questions']:3d}题 重复{r['duplicates']}  {r['answer_sequence']}")
    if len(report['papers']) > 15:
        print(f'  ... 共 {len(report["papers"])} 卷')
    print()
    print(f'排除的题型: 选词填空（15选10填10空，字母可重复，实测 75% 卷有重复属正常）')

    if not dry:
        (KB / 'manifest' / 'longpassage_answer_quarantine.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
        print('\n已写 manifest/longpassage_answer_quarantine.json')
    else:
        print('\n(dry-run，未写盘)')


if __name__ == '__main__':
    main()
