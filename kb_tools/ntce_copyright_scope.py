"""为每题补齐版权使用范围与来源性质标注。

背景
----
`应届考证功能设计与技术支撑：以教资和四六级为例.md` 的设计原则第 1 条要求题目
「必须能追溯至考试大纲、课程标准、权威教材、法律法规或真题来源」。

`教资KB` 已做到逐题可追溯（`source.origin_file` + SHA256 + 行号区间），但
`source.copyright` 只有 `authorization_status: unknown`，没有说明「这是什么
来源、能否使用、是否需要署名」。

本项目已确认定位为**科研用途、非商业化**。依据《中华人民共和国著作权法》
第二十四条第一款第（六）项——为学校课堂教学或者科学研究，翻译、改编、汇编、
播放或者少量复制已经发表的作品，可以不经著作权人许可、不向其支付报酬，但
**不得出版发行**——此类使用在合规范围内。

因此本脚本做两件事，**均不改变 `authorization_status`**（权利状态确实未知，
不应伪造）：

1. 写入 `use_scope: research_non_commercial`
   让库内任何下游使用者都能明确知道授权边界。若将来转商业化，可据此检索出
   所有需重新评估的题目。
2. 标注 `source_nature` 及 `nature_evidence`
   区分真题原件 / 考生回忆版 / 真题精选 / 地方省考。依据是文件名中的发布方
   自我声明（尤其「考生回忆版」），这直接影响成果发表时的引用规范。

同时置 `attribution_required`：提醒使用者成果中需标明来源。

用法
----
    python -X utf8 kb_tools/ntce_copyright_scope.py            # 执行
    python -X utf8 kb_tools/ntce_copyright_scope.py --dry-run  # 只统计
"""

import argparse
import collections
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'kb_tools'))

from ntce_io import atomic_write  # noqa: E402

QUESTIONS = ROOT / '数据集/教资/questions'

USE_SCOPE = 'research_non_commercial'

# (source_nature, 说明, nature_evidence 前缀, 是否需署名)
#   署名要求按「该来源是否由第三方整理」判定：官方试题本身无需署名汇编，
#   但第三方汇编的必须标明汇编出处。
NATURE_RULES = (
    ('exam_recall',
     '第三方依据考生回忆整理，非官方原文，成果引用时须标明汇编出处',
     'filename_marker:回忆版', True),
    ('compiled_selection',
     '第三方汇编整理，可能含二次编辑，成果引用时须标明汇编出处',
     'filename_marker:精选', True),
    ('provincial_exam',
     '省级考试试题，非教育部统一发布',
     'filename_marker:地方/等级考', True),
    ('official_exam',
     '教育主管部门公开发布的考试试题',
     'filename_pattern:官方真题命名', False),
)

# 人工审核过的版权判定不得覆盖。
def is_human_reviewed(copyright):
    return bool(copyright and (copyright.get('checked_by')
                               or copyright.get('attribution_confirmed')))


def classify(filename):
    base = os.path.basename(filename or '')
    if '回忆版' in base:
        return NATURE_RULES[0]
    if '精选' in base:
        return NATURE_RULES[1]
    if any(x in base for x in ('省', '四川', '广东', '浙江')):
        return NATURE_RULES[2]
    return NATURE_RULES[3]


def iter_files():
    return sorted(QUESTIONS.rglob('*.jsonl'))


def run(dry_run=False):
    stats = collections.Counter()
    by_nature = collections.Counter()
    by_level = collections.Counter()
    changes = {}

    for path in iter_files():
        rows = []
        dirty = False
        # 逐行迭代而非 read_text().splitlines()：部分数学题的 JSON 字符串内含
        # 字面换行符（公式换行），splitlines 会把一行 JSON 切断。
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

                src = q.get('source') or {}
                origin = src.get('origin_file') or ''
                nature, note, evidence, need_attr = classify(origin)

                cr = src.setdefault('copyright', {})
                if is_human_reviewed(cr):
                    stats['skipped_human_reviewed'] += 1
                else:
                    # 注意：旧记录里 use_scope 可能是 null 占位，setdefault 不会覆盖
                    # 已有键，必须显式判空赋值，否则声明会在复算后丢失。
                    if cr.get('use_scope') != USE_SCOPE:
                        cr['use_scope'] = USE_SCOPE
                        dirty = True
                    if cr.get('source_nature') != nature:
                        cr['source_nature'] = nature
                        cr['nature_note'] = note
                        cr['nature_evidence'] = evidence
                        cr['attribution_required'] = need_attr
                        dirty = True
                    if dirty:
                        stats['updated'] += 1
                    else:
                        stats['already_set'] += 1

                by_nature[nature] += 1
                by_level[(q.get('level'), nature)] += 1
                rows.append(q)

        if dirty:
            changes[path] = rows

    if not dry_run:
        for path, rows in changes.items():
            atomic_write(path, ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))

    return stats, by_nature, by_level, changes


def main():
    ap = argparse.ArgumentParser(description='补齐版权使用范围与来源性质标注')
    ap.add_argument('--dry-run', action='store_true', help='只统计不写盘')
    args = ap.parse_args()

    stats, by_nature, by_level, changes = run(args.dry_run)

    print('=== 版权使用范围与来源性质标注 ===')
    print('mode:', 'dry-run' if args.dry_run else 'write')
    print('use_scope:', USE_SCOPE)
    print('更新:', stats['updated'], '| 已是目标值:', stats['already_set'])
    if stats['skipped_human_reviewed']:
        print('跳过(人工审核):', stats['skipped_human_reviewed'])
    if stats['json_error']:
        print('JSON 解析失败:', stats['json_error'])
    print('改写文件数:', len(changes))
    print('\n来源性质分布(题量):')
    for k, v in by_nature.most_common():
        print(f'  {k}: {v}')

    print('\n按学段 × 来源性质:')
    levels = sorted({lv for lv, _ in by_level})
    natures = [n[0] for n in NATURE_RULES]
    print('  学段      ' + '  '.join(f'{n[:12]:>12s}' for n in natures))
    for lv in levels:
        cells = '  '.join(f'{by_level.get((lv, n), 0):>12d}' for n in natures)
        print(f'  {lv:<10s}{cells}')


if __name__ == '__main__':
    main()
