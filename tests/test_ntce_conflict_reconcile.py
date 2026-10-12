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
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kb_tools'))

from build_kb import OUT, ROOT as KB_ROOT, load_text, parse_answers  # noqa: E402
from ntce_analysis_fill import METHOD as RULE_METHOD  # noqa: E402
from ntce_conflict_reconcile import (RECONCILED, batch_summary, evidence_paths,  # noqa: E402
                                     refresh_rule_analysis, run)
from ntce_repair import card_path, dedup_audit, dedup_evidence, mix_risk_evidence  # noqa: E402

BATCH = 'xiaoxue/jiaoyuxinlixue'
STILL_QUARANTINED = 'source_conflict'


def evidence_lines(batch=BATCH):
    """按批次读逐题证据；文件名口径归核对工具自己管，测试不另拼一份。"""
    path, _ = evidence_paths(OUT / 'review', batch)
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def batch_with_conflicts(exclude=BATCH):
    """从完整性快照里取另一个仍带答案冲突的批次，用来验证跨批次互不覆盖。"""
    snapshot = json.loads((ROOT / '审查' / '教资完整性核对.json').read_text(encoding='utf-8'))
    for row in snapshot['scopes']:
        key = '%s/%s' % (row['school_level'], row['subject'])
        if key != exclude and row['answer_conflict']:
            return key
    raise AssertionError('全库除这批以外再没有带答案冲突的科目，跨批次保留的用例失去正例')


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

    def check_mirror(self, record, path):
        """卡片是题记录的镜像：上一批就是只改了数据没重渲染，卡片头部还写着隔离、正文写着"本题无给定答案"。"""
        self.assertTrue(path.exists(), f"{record['question_id']} 没有对应卡片：{path}")
        lines = path.read_text(encoding='utf-8').splitlines()
        fields = dict(l.split(':', 1) for l in lines[1:lines.index('---', 1)] if ':' in l)
        want = (record['review']['status'], record['content']['answer_status'])
        self.assertEqual(want, (fields['review_status'].strip(), fields['answer_status'].strip()),
                         f"{path} 的头部状态与题记录不一致，卡片没有随数据重渲染")
        body = '\n'.join(lines[lines.index('---', 1) + 1:])
        self.assertIn(record['content']['answer'], body,
                      f"{path} 的正文没有落回的答案")
        self.assertNotIn('本题无给定答案', body,
                         f'{path} 已经有答案了，正文却还断言本题无给定答案')
        self.assertIn('expert_content_review_needed', body,
                      f'{path} 的人工复核待办在卡片上看不见了')

    def check_denies_an_answer(self, record, path):
        """规范题自己就没有答案时，卡必须如实标"未提供"（或主观题的 null），而不是替它编一个。"""
        self.assertTrue(path.exists(), f"{record['question_id']} 没有对应卡片：{path}")
        lines = path.read_text(encoding='utf-8').splitlines()
        fields = dict(l.split(':', 1) for l in lines[1:lines.index('---', 1)] if ':' in l)
        self.assertIn(fields['answer'].strip(), ('未提供', 'null'),
                      f"{path} 的规范题没有答案，卡片头部却印出了答案")
        self.assertEqual(fields['answer_status'].strip(), record['content']['answer_status'],
                         f'{path} 的头部答案态与题记录不一致，卡片没有随数据重渲染')

    def test_restored_card_mirrors_the_record_and_stops_denying_the_answer(self):
        for _, q in reconciled_rows():
            # 被判重的那道题按设计不出自己的卡（卡只给被指向的规范题），镜像检查归下面那个用例。
            if q['extra'].get('duplicate_of'):
                continue
            self.check_mirror(q, card_path(q))

    def test_a_deduped_restored_question_is_carried_by_the_canonical_card(self):
        """落回的答案在卡集里必须有人替它说话：要么是自己的卡，要么是规范题那张卡。
        规范题的卡讲的是规范题（选项排列不同会让答案字母不同），所以核对的是"它是规范题的镜像"。
        规范题自己也没有答案时，卡集里就没有任何一份答案替这条落回说话——那是另一个维度的缺口，
        归属仍然对得上，缺的是答案，必须单独出现在复核队列 §3.3 的现算里，不能混进"归属核不出来"。
        归属今天已核不出来的那几条也不许算作已覆盖。"""
        by_id = {q['question_id']: q for _, q in question_rows()}
        dups = [q for _, q in reconciled_rows() if q['extra'].get('duplicate_of')]
        self.assertTrue(dups, '全库没有落回过一道判重题，卡集覆盖的检查失去正例')
        unverifiable, carrier_missing = [], []
        for q in dups:
            self.assertFalse(card_path(q).exists(),
                             f"{q['question_id']} 是判重题却有自己的卡：出卡与判重两套口径开始各说各话")
            canonical = by_id[q['extra']['duplicate_of']]
            if canonical['content'].get('answer'):
                self.check_mirror(canonical, card_path(canonical))
            else:
                self.check_denies_an_answer(canonical, card_path(canonical))
                carrier_missing.append(q['question_id'])
            if dedup_evidence(q, by_id)['codes']:
                unverifiable.append(q['question_id'])
        audit = dedup_audit(list(by_id.values()))
        self.assertEqual(audit['card_written'], 0,
                         '有判重题拿到了自己的卡，"重复题不出卡"这条设计已经不再成立')
        section = (ROOT / '审查' / '待复核清单.md').read_text(encoding='utf-8').split('### 3.3', 1)
        self.assertEqual(len(section), 2,
                         '落回的判重题里有归属核不出来的，但复核队列没有 §3.3 来登记这个缺口')
        if unverifiable:
            self.assertIn('{:,}'.format(audit['uncheckable']), section[1],
                          '§3.3 报的不可核对条数与题库现算不一致：缺口被手抄过')
        if carrier_missing:
            self.assertIn('{:,}'.format(audit['answer_carrier_missing']), section[1],
                          '这批有 %d 道题落回的答案在卡集里无人代答（规范题自己没答案），'
                          '但 §3.3 没有把这个维度算出来：%s' % (len(carrier_missing), carrier_missing))

    def test_restored_rule_analysis_follows_the_answer_without_claiming_verification(self):
        for _, q in reconciled_rows():
            analysis = q['analysis']
            self.assertEqual(analysis['correct_answer'], q['content']['answer'],
                             f"{q['question_id']} 的解析草稿还记着落回之前的空答案")
            self.assertFalse(analysis['expert_verified'])
            if analysis['method'] != RULE_METHOD:
                # 正文家在别处的草稿（学科大模型推演候选）不由本工具改写，只对齐答案字段。
                continue
            self.assertEqual(analysis['status'], 'rule_draft_pending_expert')
            self.assertIn('待专家核定', analysis['explanation'],
                          f"{q['question_id']} 的解析去掉了'无答案'的说法，却没留下未经核实的声明")

    def test_a_draft_owned_by_another_generator_only_gets_its_answer_aligned(self):
        """落回不能替别人的草稿重写正文：文案家在别处，改了就是本工具替它做了学科判断。

        这里只认答案字段跟着落回走，方法、状态与三段原文必须原样留下。
        """
        q = {'question_id': 'ntce.test.draft.q01', 'content': {'answer': 'C'},
             'analysis': {'method': 'qwen-plus_deduced_candidate_v1',
                          'status': 'candidate_draft_pending_expert',
                          'expert_verified': False, 'correct_answer': None,
                          'key_info': '模型原文', 'explanation': '模型原文',
                          'option_compare': '模型原文'},
             'review': {'status': 'needs_fix', 'checked_by': None, 'content_verified': False,
                        'tagger': 'model', 'pending_reasons': [], 'cross_question_risk': []},
             'extra': {}}
        diff = refresh_rule_analysis(q, {})
        self.assertEqual(diff, {'before': {'correct_answer': None},
                                'after': {'correct_answer': 'C'}},
                         '非规则草稿的改动超出了答案字段')
        self.assertEqual(q['analysis']['correct_answer'], 'C')
        self.assertEqual(q['analysis']['key_info'], '模型原文', '落回把别人家的正文换成了规则文案')
        self.assertEqual(q['analysis']['explanation'], '模型原文')
        self.assertEqual(q['analysis']['option_compare'], '模型原文')
        self.assertEqual(q['analysis']['method'], 'qwen-plus_deduced_candidate_v1')
        self.assertEqual(q['analysis']['status'], 'candidate_draft_pending_expert')
        self.assertIsNone(refresh_rule_analysis(q, {}), '已对齐的字段被重复记成一次改动')

    def test_a_manually_reviewed_draft_is_left_alone_even_when_the_answer_landed(self):
        q = {'question_id': 'ntce.test.reviewed.q01', 'content': {'answer': 'C'},
             'analysis': {'method': RULE_METHOD, 'correct_answer': None, 'key_info': '人工原文',
                          'explanation': '人工原文', 'option_compare': '人工原文'},
             'review': {'status': 'checked', 'checked_by': '教研·具名', 'content_verified': True,
                        'tagger': 'expert', 'pending_reasons': [], 'cross_question_risk': []},
             'extra': {}}
        self.assertIsNone(refresh_rule_analysis(q, {}), '落回覆盖了人工审核过的解析')
        self.assertEqual(q['analysis']['correct_answer'], None)

    def test_report_only_rerun_regenerates_the_whole_batch_without_touching_data(self):
        before = {f: f.read_text(encoding='utf-8') for f in
                  sorted((OUT / 'questions' / BATCH.split('/')[0] / BATCH.split('/')[1]).glob('*.jsonl'))}
        summary = run(scope=BATCH, apply_changes=False)
        after = {f: f.read_text(encoding='utf-8') for f in
                 sorted((OUT / 'questions' / BATCH.split('/')[0] / BATCH.split('/')[1]).glob('*.jsonl'))}
        self.assertEqual(before, after, '只出报告的核对改动了题库数据')
        records = evidence_lines()
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
        records = evidence_lines()
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
        # 剪文本就会删掉库内唯一一份，必须走补收录。摘要按同一口径合计：条按（卷·编号）去重。
        pairs = {(r['scope'], r['session'], n) for r in boundary
                 for n in r['content_boundary']['embedded_numbers_without_record']}
        self.assertEqual(summary['boundary_numbers_without_record'], len(pairs))
        self.assertEqual(summary['boundary_questions_without_record'],
                         sum(1 for r in boundary if r['content_boundary']['embedded_numbers_without_record']))

    def test_a_recording_gap_counts_once_per_paper_not_once_per_mention(self):
        """补收录的缺口数与全库现算清单 §3.2 必须同口径：同一卷里两道题都露出编号 29，
        要补的是同一条记录；把题面露出的处数当条数，两处会各自漂出一个"该批还缺几条"。
        卷的身份带批次前缀，不同科目下的同名卷面（2017b 在许多科目都存在）不能并进同一条。"""
        def row(scope, session, nums):
            return {'result': 'refused', 'scope': scope, 'session': session,
                    'content_boundary': {'embedded_numbers_without_record': nums}}
        rows = [row('a/b', '2017b', [29]), row('a/b', '2017b', [29]), row('a/b', '2019b', [28]),
                row('a/b', '2021c', []), row('c/d', '2017b', [29])]
        summary = batch_summary('a/b', rows, 'a/b', False, ['a/b'], 0)
        self.assertEqual(summary['boundary_numbers_without_record'], 3,
                         '补收录条数没有按（卷·编号）去重，或把别科目的同名卷面并成了一条')
        self.assertEqual(summary['boundary_questions_without_record'], 4,
                         '露出无记录编号的题数把没有编号的题也算进去了')

    def test_reconciling_another_batch_keeps_this_batchs_evidence_whole(self):
        """分批修补一轮只核对一个科目，逐题对照就得一批存一份。原先全库共用一个文件，
        跑第二科的同一行 write_rows 会把第一科的题号、依据与结论整批覆盖掉。
        没被安排核对的那一批只在临时目录里跑：测试跑一次不该在库里凭空多出“这科已核对”的证据。"""
        review = OUT / 'review'
        path, digest = evidence_paths(review, BATCH)
        before = {p.name: p.read_text(encoding='utf-8') for p in review.glob('answer_conflict_reconciliation.*')}
        other = batch_with_conflicts()
        with TemporaryDirectory() as tmp:
            summary = run(scope=other, apply_changes=False, review_dir=Path(tmp))
            self.assertEqual(summary['batch'], other, '摘要没自述它核对的是哪一批')
            other_rows = [json.loads(l) for l in
                          evidence_paths(Path(tmp), other)[0].read_text(encoding='utf-8').splitlines() if l.strip()]
            self.assertTrue(other_rows, '未核对过的那一批一题都没读出来，跨批次的用例失去正例')
            self.assertEqual({r['scope'] for r in other_rows}, {other},
                             '一批的证据文件里混进了别批的题，按批读就再也数不清')
        self.assertEqual({p.name: p.read_text(encoding='utf-8') for p in review.glob('answer_conflict_reconciliation.*')},
                         before, '核对别的科目动了库里的逐题证据')
        self.assertTrue(digest.exists(), '这一批的汇总没和证据文件一起留在库里')
        self.assertEqual({r['scope'] for r in evidence_lines()}, {BATCH},
                         '库里的这批证据混进了别批的题')

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
