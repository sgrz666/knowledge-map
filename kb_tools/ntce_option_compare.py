"""为客观题补 option_compare —— 人工/agent 精标的写入与验收工具。

分工
----
本脚本是**共用底座**：多个 agent 按学段分工，各自只处理自己范围内的文件，
但共用同一套写入与校验逻辑，避免实现分歧。

分工范围（按 `教资KB/questions/<学段>/` 划分，文件互不重叠）：
    agent A → gaozhong   agent B → chuzhong   agent C → youer
    agent D → zhongxue   agent E → xiaoxue

写入原则
--------
`option_compare` 只在**能给出具体判断依据**时写入。以下情形必须留 ``None``：

1. ``content.answer`` 为空或 ``answer_status`` 非 ``letter_only`` —— 无正确选项可分析
2. 选项少于 2 个（材料不完整、跨题混入风险）
3. 题干残缺（``source_stem_incomplete``）
4. agent 无法说明该题的具体干扰点，只能复述选项或套话

**禁止写入的句式**（验收时按此判为不合格并回退）：
    包含「判断标准为准」「请参考该知识点」「待专家核定」「具体干扰项区分依据」
    「常作为干扰项出现」「不能仅凭」「需要进一步」「以上选项」等无信息量表述

合格示例（供 agent 参考的写法）：
    「A『应激』考查的是紧急状态下的生理反应，与B『身心适应』的慢性阶段不同；
      C『防御机制』属于心理防御概念，题干未涉及；D『社会支持』是外部资源，
      不属于应激反应范畴。故选A。」

用法
----
    python -X utf8 kb_tools/ntce_option_compare.py --scope gaozhong --input <json>
    python -X utf8 kb_tools/ntce_option_compare.py --scope all --verify-only
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
SCOPES = ('gaozhong', 'chuzhong', 'youer', 'zhongxue', 'xiaoxue')

# 无信息量句式：命中任一即判定不合格
BANNED = (
    '判断标准为准', '请参考该知识点', '待专家核定', '具体干扰项区分依据',
    '常作为干扰项出现', '不能仅凭', '需要进一步', '以上选项',
    '判断依据以', '参考相关知识点', '需结合知识点',
)

OBJ_TYPES = ('单选', '多选')


def is_banned(text):
    return any(b in text for b in BANNED)


def needs_work(q):
    """该题是否需要补 option_compare。"""
    if q.get('question_type') not in OBJ_TYPES:
        return False
    c = q.get('content') or {}
    oc = (q.get('analysis') or {}).get('option_compare')
    if oc and oc.strip():
        return False
    # 无有效答案不做逐项分析
    if c.get('answer_status') != 'letter_only' or not c.get('answer'):
        return 'no_answer'
    if len(c.get('options') or []) < 2:
        return 'options_incomplete'
    reasons = (q.get('review') or {}).get('pending_reasons') or []
    if 'source_stem_incomplete' in reasons:
        return 'stem_incomplete'
    if 'cross_question_boundary_review_needed' in reasons:
        return 'boundary_risk'
    return True


def iter_files(scope='all', subjects=None):
    """按学段和/或学科筛选文件。

    subjects 为 None 时按学段处理；给定列表时只取这些学科的目录。
    按学科切分用于让多个 agent 并行时文件范围互斥——只要学科集合不相交，
    它们就不会写同一个文件。
    """
    if scope == 'all':
        files = sorted(QUESTIONS.rglob('*.jsonl'))
    else:
        files = sorted((QUESTIONS / scope).rglob('*.jsonl'))
    if subjects:
        keep = set(subjects)
        files = [f for f in files
                 if f.relative_to(QUESTIONS).parts[1] in keep]
    return files


def apply(scope, items, subjects=None, verbose=True):
    """items: {question_id: option_compare 文本}。返回统计。"""
    stats = collections.Counter()
    rejected = {}
    files = iter_files(scope, subjects)
    apply_dir = scope

    for path in files:
        rows = []
        dirty = False
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

                verdict = needs_work(q)
                if verdict is not True:
                    stats[f'skip_{verdict}' if isinstance(verdict, str) else 'skip_ok'] += 1
                    rows.append(q)
                    continue

                qid = q.get('question_id')
                text = (items.get(qid) or '').strip()
                if not text:
                    stats['agent_left_null'] += 1
                    rows.append(q)
                    continue
                if is_banned(text):
                    stats['rejected_banned'] += 1
                    rejected[qid] = text
                    rows.append(q)
                    continue
                if len(text) < 30:
                    stats['rejected_too_short'] += 1
                    rejected[qid] = text
                    rows.append(q)
                    continue

                a = q.setdefault('analysis', {})
                a['option_compare'] = text
                a['option_compare_meta'] = {
                    'method': 'agent_curated_v1',
                    'expert_verified': False,
                    'note': 'agent 精标，待学科专家复核',
                }
                dirty = True
                stats['written'] += 1
                rows.append(q)

        if dirty:
            atomic_write(path, ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))

    stats['files'] = len(files)
    return stats, rejected


def verify(scope='all', subjects=None):
    """验收：统计当前 option_compare 状态、违规句式，以及内容缺陷。

    除黑名单句式外，另检查两项实质缺陷——这两项不拒收（已写入的保留），
    但计入报告供人工抽检：
      missing_answer_letter : 分析未提及正确答案字母，可能漏判正确项
      too_short             : 长度<40 字，信息量可能不足
    """
    files = iter_files(scope, subjects)
    cnt = collections.Counter()
    bad = []
    defect = []
    for path in files:
        with path.open(encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                q = json.loads(line)
                if q.get('question_type') not in OBJ_TYPES:
                    continue
                cnt['objective'] += 1
                oc = (q.get('analysis') or {}).get('option_compare')
                if oc and oc.strip():
                    cnt['filled'] += 1
                    if is_banned(oc):
                        cnt['banned'] += 1
                        bad.append(q.get('question_id'))
                    ans = ((q.get('content') or {}).get('answer') or '').strip()
                    if ans and ans not in oc:
                        cnt['missing_answer_letter'] += 1
                        defect.append((q.get('question_id'), 'no_answer_letter'))
                    if len(oc.strip()) < 40:
                        cnt['too_short'] += 1
                        defect.append((q.get('question_id'), 'too_short'))
                else:
                    cnt['empty'] += 1
    return cnt, bad, defect


def main():
    ap = argparse.ArgumentParser(description='客观题 option_compare 精标写入与验收')
    ap.add_argument('--scope', default='all',
                    choices=list(SCOPES) + ['all'])
    ap.add_argument('--subjects', help='逗号分隔的学科代码，如 yingyu,zhengzhi')
    ap.add_argument('--input', help='agent 产出的 JSON：{question_id: option_compare}')
    ap.add_argument('--verify-only', action='store_true')
    args = ap.parse_args()

    subjects = ([s.strip() for s in args.subjects.split(',') if s.strip()]
                if args.subjects else None)
    label = f'{args.scope}' + (f'/{",".join(subjects)}' if subjects else '')

    if args.verify_only:
        cnt, bad, defect = verify(args.scope, subjects)
        print(f'[{label}] 客观题 {cnt["objective"]} | 已填 {cnt["filled"]} '
              f'| 空 {cnt["empty"]} | 违规句式 {cnt["banned"]}')
        if cnt['banned'] or cnt['missing_answer_letter'] or cnt['too_short']:
            print(f'  缺陷: 未提答案字母 {cnt["missing_answer_letter"]} '
                  f'| 长度<40 {cnt["too_short"]}')
        if bad:
            print('违规样例:', bad[:5])
        if defect:
            print('缺陷样例:', defect[:5])
        return

    if not args.input:
        ap.error('需要 --input 或 --verify-only')

    items = json.loads(pathlib.Path(args.input).read_text(encoding='utf-8'))
    stats, rejected = apply(args.scope, items, subjects)

    print(f'[{label}] 写入 {stats["written"]} | 保留null {stats["agent_left_null"]} '
          f'| 拒收(违规句式) {stats["rejected_banned"]} | 拒收(过短) {stats["rejected_too_short"]}')
    for k in sorted(stats):
        if k.startswith('skip_') and stats[k]:
            print(f'  {k}: {stats[k]}')
    if rejected:
        print('拒收明细(前5):', list(rejected.items())[:5])


if __name__ == '__main__':
    main()
