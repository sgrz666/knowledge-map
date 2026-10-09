"""清理 analysis.option_compare 中的模板化占位文案。

背景
----
`kb_tools/ntce_analysis_fill.py` 曾为无解析题目生成四段解析，其中客观题的
`option_compare` 使用了如下模板文案：

    「各选项内容：Axxx（给定答案）；Byyy。**正误判定需以知识点【X】的判断标准
      为准；具体干扰项区分依据请参考该知识点，待专家核定。**」

这段话没有任何分析价值——它复述选项后把判断责任推回知识点。而
`kb_tools/ntce_llm_audit.py` 判定「四段齐全」的条件是字段**非空**：

    if not all(a.get(field) for field in ('key_info','option_compare',
                                          'trace_back','explanation')):

因此模板文案会被计为「解析完整」，让 `review/llm_audit.json` 虚高，并把真正
的缺失变成不可见。诚实的 `null` 至少能告诉下游「这段需要人来做」。

本脚本把这些 `option_compare` 置回 `null`，只动这一个字段，保留同条题目中
确实有信息量的 `key_info` / `trace_back` / `explanation`。

用法
----
    python -X utf8 kb_tools/ntce_analysis_cleanup.py            # 执行
    python -X utf8 kb_tools/ntce_analysis_cleanup.py --dry-run  # 只统计
"""

import argparse
import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'kb_tools'))

from ntce_io import atomic_write  # noqa: E402

QUESTIONS = ROOT / '数据集/教资/questions'

# 模板文案特征串。任一命中即判定为占位文案。
TEMPLATE_MARKERS = (
    '判断标准为准',
    '请参考该知识点',
    '待专家核定',
    '具体干扰项区分依据',
)

# 这些字段属于真实提取，保留不动。
KEEP_FIELDS = ('key_info', 'trace_back', 'explanation')

# 人工审核过的解析不得改动。
def is_human_reviewed(a):
    return bool(a.get('expert_verified'))


def is_template(text):
    if not isinstance(text, str) or not text.strip():
        return False
    return any(marker in text for marker in TEMPLATE_MARKERS)


def iter_files():
    return sorted(QUESTIONS.rglob('*.jsonl'))


def scan(dry_run=False):
    stats = collections.Counter()
    by_type = collections.Counter()
    changes = {}

    for path in iter_files():
        rows = []
        dirty = False
        # 逐行迭代而非 splitlines()：部分数学题的 JSON 字符串内含字面换行符
        # （如公式换行），splitlines() 会把它切断导致 JSONDecodeError。
        with path.open(encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    q = json.loads(line)
                except json.JSONDecodeError:
                    stats['json_error'] += 1
                    continue

                a = q.get('analysis')
                if isinstance(a, dict) and is_template(a.get('option_compare')):
                    if is_human_reviewed(a):
                        stats['skipped_human_reviewed'] += 1
                    else:
                        stats['cleared'] += 1
                        by_type[q.get('question_type')] += 1
                        a['option_compare'] = None
                        dirty = True
                elif isinstance(a, dict) and a.get('explanation'):
                    stats['kept_non_template'] += 1
                rows.append(q)

        if dirty:
            changes[path] = rows

    if not dry_run:
        for path, rows in changes.items():
            atomic_write(path, ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))

    return stats, by_type, changes


def main():
    ap = argparse.ArgumentParser(description='清理 option_compare 模板化占位文案')
    ap.add_argument('--dry-run', action='store_true', help='只统计不写盘')
    args = ap.parse_args()

    stats, by_type, changes = scan(args.dry_run)

    print('=== option_compare 模板文案清理 ===')
    print('mode:', 'dry-run' if args.dry_run else 'write')
    print('置为 null:', stats['cleared'])
    print('保留(非模板):', stats['kept_non_template'])
    if stats['skipped_human_reviewed']:
        print('跳过(人工审核):', stats['skipped_human_reviewed'])
    if stats['json_error']:
        print('JSON 解析失败:', stats['json_error'])
    print('改写文件数:', len(changes))
    print('按题型:')
    for k, v in by_type.most_common():
        print(f'  {k}: {v}')


if __name__ == '__main__':
    main()
