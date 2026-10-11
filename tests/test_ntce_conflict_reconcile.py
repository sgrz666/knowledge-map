"""答案冲突回原卷核对的契约：落回的答案必须能从原始卷面独立复算出来，且审核状态不被带走。

这批题原先整体隔离，是因为抽取阶段确认不了题号与题型。核对工具只在"题干在原卷唯一定位到题号 +
答案键该题号是单字母且落在印刷选项内 + 与隔离时保全的候选一致"三件同时成立时才落回答案。
下面的用例不信工具自己的结论：它直接重读原卷答案 CSV，逐条复算落回的那个字母。
"""
import json
import sys
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kb_tools'))

from build_kb import OUT, ROOT as KB_ROOT, load_text, parse_answers  # noqa: E402
from ntce_conflict_reconcile import RECONCILED, run  # noqa: E402
from ntce_repair import mix_risk_evidence  # noqa: E402

BATCH = 'xiaoxue/jiaoyuxinlixue'
STILL_QUARANTINED = 'source_conflict'


def question_rows():
    for qfile in sorted((OUT / 'questions').glob('*/*/*.jsonl')):
        for line in qfile.read_text(encoding='utf-8').splitlines():
            if line.strip():
                yield qfile, json.loads(line)


def reconciled_rows():
    return [(f, q) for f, q in question_rows()
            if any(c.get('kind') == RECONCILED for c in q['extra'].get('source_repairs', []))]


class TestConflictReconciliation(unittest.TestCase):
    def test_every_restored_answer_recomputes_from_the_original_answer_key(self):
        rows = reconciled_rows()
        self.assertTrue(rows, '核对工具一行都没落回，说明它在这批上失效了')
        for _, q in rows:
            change = next(c for c in q['extra']['source_repairs'] if c['kind'] == RECONCILED)
            number = change['source_question_number']
            answer_key = KB_ROOT / change['answer_file']
            self.assertTrue(answer_key.exists(),
                            f"{q['question_id']} 的依据指向不存在的原卷：{change['answer_file']}")
            letters = parse_answers(load_text(answer_key)).get(number)
            self.assertEqual(q['content']['answer'], letters,
                             f"{q['question_id']} 落回的答案与原卷答案键第 {number} 题不一致")
            option_keys = [o['key'] for o in q['content']['options']]
            self.assertIn(letters, option_keys,
                          f"{q['question_id']} 的答案字母 {letters} 不在印刷选项 {option_keys} 内")
            self.assertEqual(len(option_keys), 4,
                             f"{q['question_id']} 不是四选项单选题却被落回了单字母")
            self.assertEqual(change['preserved_candidate'], letters,
                             f"{q['question_id']} 落回时没有与隔离保全的候选交叉核对")

    def test_restoring_an_answer_never_promotes_the_review_status(self):
        for _, q in reconciled_rows():
            review = q['review']
            self.assertIsNone(review['checked_by'], f"{q['question_id']} 被自动署上审核人")
            self.assertFalse(review['content_verified'], f"{q['question_id']} 被自动标成内容已核定")
            self.assertNotIn(review['status'], ('checked', 'expert_reviewed'),
                             f"{q['question_id']} 的审核状态被自动提升到 {review['status']}")
            self.assertEqual(review['answer_validation_status'], 'not_expert_verified')
            self.assertIn('expert_content_review_needed', review['pending_reasons'],
                          f"{q['question_id']} 的人工复核待办被落回动作一起抹掉了")
            self.assertEqual(q['content']['answer_status'], 'letter_only')

    def test_refused_records_stay_quarantined_with_their_conflict_marker(self):
        # 核对不出来就一行都不许动：答案仍为空、状态仍是冲突、仍留在隔离态。
        for _, q in question_rows():
            if q['content']['answer_status'] != STILL_QUARANTINED:
                continue
            self.assertIsNone(q['content']['answer'],
                              f"{q['question_id']} 仍标着来源冲突却已有答案，落回与状态脱节了")
            self.assertEqual(q['review']['status'], 'quarantined',
                              f"{q['question_id']} 的冲突题离开了隔离态，会被当成可判分题目")

    def test_batch_scope_agrees_with_the_committed_snapshot(self):
        snapshot = json.loads((ROOT / '审查' / '教资完整性核对.json').read_text(encoding='utf-8'))
        row = next(s for s in snapshot['scopes']
                   if (s['school_level'], s['subject']) == tuple(BATCH.split('/')))
        actual = sum(1 for _, q in question_rows()
                     if (q['level'], q['subject']) == tuple(BATCH.split('/'))
                     and q['content']['answer_status'] == STILL_QUARANTINED)
        self.assertEqual(row['answer_conflict'], actual,
                         '完整性快照与题库实况不一致：改完数据没有重跑生成脚本')

    def test_multi_select_and_optionless_questions_are_held_out_by_name(self):
        summary = run(scope=BATCH, apply_changes=False)
        refused = summary['by_refusal']
        self.assertGreater(refused.get('not_a_four_option_single_choice', 0), 0,
                           '这批里已无多选/缺选项题，该拒绝分支需要用别的批次钉住')
        self.assertGreater(refused.get('stem_number_not_located_in_source', 0), 0,
                           '题干定位不到的题在这一批里已经消失，拒绝分支失去覆盖')
        self.assertEqual(summary['by_result'].get('refused'), sum(refused.values()))

    def test_restored_card_mirrors_the_record_and_stops_denying_the_answer(self):
        # 卡片是题记录的镜像：上一批就是只改了数据没重渲染，卡片头部还写着隔离、正文写着"本题无给定答案"。
        for _, q in reconciled_rows():
            path = (OUT / 'cards' / q['level'] / q['subject'] / q['source']['session']
                    / ('q%02d.md' % q['extra']['paper_order']))
            self.assertTrue(path.exists(), f"{q['question_id']} 没有对应卡片：{path}")
            lines = path.read_text(encoding='utf-8').splitlines()
            fields = dict(l.split(':', 1) for l in lines[1:lines.index('---', 1)] if ':' in l)
            want = (q['review']['status'], q['content']['answer_status'])
            self.assertEqual(want, (fields['review_status'].strip(), fields['answer_status'].strip()),
                             f"{path} 的头部状态与题记录不一致，卡片没有随数据重渲染")
            body = '\n'.join(lines[lines.index('---', 1) + 1:])
            self.assertIn(q['content']['answer'], body,
                          f"{path} 的正文没有落回的答案")
            self.assertNotIn('本题无给定答案', body,
                             f'{path} 已经有答案了，正文却还断言本题无给定答案')
            self.assertIn('expert_content_review_needed', body,
                          f'{path} 的人工复核待办在卡片上看不见了')

    def test_restored_rule_analysis_follows_the_answer_without_claiming_verification(self):
        for _, q in reconciled_rows():
            analysis = q['analysis']
            self.assertEqual(analysis['correct_answer'], q['content']['answer'],
                             f"{q['question_id']} 的解析草稿还记着落回之前的空答案")
            self.assertFalse(analysis['expert_verified'])
            self.assertEqual(analysis['status'], 'rule_draft_pending_expert')
            self.assertIn('待专家核定', analysis['explanation'],
                          f"{q['question_id']} 的解析去掉了'无答案'的说法，却没留下未经核实的声明")

    def test_report_only_rerun_regenerates_the_whole_batch_without_touching_data(self):
        before = {f: f.read_text(encoding='utf-8') for f in
                  sorted((OUT / 'questions' / BATCH.split('/')[0] / BATCH.split('/')[1]).glob('*.jsonl'))}
        summary = run(scope=BATCH, apply_changes=False)
        after = {f: f.read_text(encoding='utf-8') for f in
                 sorted((OUT / 'questions' / BATCH.split('/')[0] / BATCH.split('/')[1]).glob('*.jsonl'))}
        self.assertEqual(before, after, '只出报告的核对改动了题库数据')
        records = [json.loads(l) for l in
                   (OUT / 'review' / 'answer_conflict_reconciliation.jsonl').read_text(encoding='utf-8').splitlines()
                   if l.strip()]
        counts = Counter((r['result'], r.get('already_applied')) for r in records)
        self.assertEqual(counts[('reconciled', True)], summary['by_result']['reconciled'],
                         '重跑把已落回的批次从证据文件里丢了，证据必须整批再生')
        self.assertEqual(summary['scopes_touched'], [])
        # 摘要必须自述数据实况：只出报告的那次运行若只记 applied=False，读起来就像这批一题都没落回。
        self.assertEqual(summary['restored_in_dataset'], summary['by_result']['reconciled'],
                         '摘要没记下这批已有答案落回题记录')
        self.assertEqual(summary['still_quarantined'], summary['by_result']['refused'],
                         '摘要没记下核对不出来、仍留在隔离态的题数')
        self.assertFalse(summary['applied'])

    def test_a_refused_question_names_the_field_that_swallows_the_next_questions(self):
        """隔离码只写"跨题风险"不足以指导下一步：剪文本还是补收录，取决于串进了哪个字段、
        被吞掉的邻题在本卷有没有独立记录。证据要自己把这两件事答出来。"""
        summary = run(scope=BATCH, apply_changes=False)
        records = [json.loads(l) for l in
                   (OUT / 'review' / 'answer_conflict_reconciliation.jsonl').read_text(encoding='utf-8').splitlines()
                   if l.strip()]
        boundary = [r for r in records if r['result'] == 'refused' and r.get('content_boundary')]
        self.assertEqual(summary['refused_with_open_question_boundary'], len(boundary))
        self.assertTrue(boundary, '这批明明有题面串题的拒绝题，证据却没把字段定位出来')
        for record in boundary:
            evidence = record['content_boundary']
            self.assertTrue(evidence['sequence_fields'],
                            f"{record['question_id']} 说有风险，却没指出完整选项序列落在哪个字段")
            self.assertGreaterEqual(evidence['combined_sequences'], 2)
        worst = max(boundary, key=lambda r: max(r['content_boundary']['sequence_counts'].values()))
        self.assertGreaterEqual(max(worst['content_boundary']['sequence_counts'].values()), 5,
                                '一个选项里串进十几道邻题是这批最重的题面缺陷，只留一条风险码等于埋没它')
        # 邻题编号按"数字 + 邻题常见开头词"识别，是下限；认得出的那些若本卷没有独立记录，
        # 剪文本就会删掉库内唯一一份，必须走补收录。摘要按同一口径合计。
        self.assertEqual(summary['boundary_numbers_without_record'],
                         sum(len(r['content_boundary']['embedded_numbers_without_record']) for r in boundary))

    def test_the_reconcile_tool_reads_the_same_boundary_rules_as_the_repair_pass(self):
        """串题检测只许有一份口径：核对工具不得另写正则，否则两处会各自漂移出两套隔离结论。"""
        level, subject = BATCH.split('/')
        for qfile in sorted((OUT / 'questions' / level / subject).glob('*.jsonl')):
            for line in qfile.read_text(encoding='utf-8').splitlines():
                if not line.strip():
                    continue
                q = json.loads(line)
                evidence = mix_risk_evidence(q)
                codes = set(q['review'].get('cross_question_risk') or [])
                self.assertEqual(bool(evidence['sequence_counts'].get('stem')),
                                 'complete_choice_sequence_in_stem' in codes, q['question_id'])
                self.assertEqual(any(f != 'stem' for f in evidence['sequence_fields']),
                                 'complete_choice_sequence_in_option' in codes, q['question_id'])
                self.assertEqual(evidence['combined_sequences'] >= 2,
                                 'multiple_complete_choice_sequences' in codes, q['question_id'])


if __name__ == '__main__':
    unittest.main()
