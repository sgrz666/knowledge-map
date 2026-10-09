"""教资全库修复的语义回归；始终检查全库，不通过发布筛选缩小分母。"""
import json
from pathlib import Path
import unittest
import sys

ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / '数据集' / '教资'
sys.path.insert(0, str(ROOT / 'kb_tools'))


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').split('\n') if line.strip()]


class NtceRepairRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.questions = [q for path in sorted((KB / 'questions').glob('*/*/*.jsonl')) for q in rows(path)]
        cls.nodes = {n['id']: n for n in rows(KB / 'graph/nodes.jsonl')}
        cls.edges = rows(KB / 'graph/edges.jsonl')

    def test_full_corpus_retained(self):
        self.assertEqual(14500, len(self.questions))
        self.assertEqual(len(self.questions), len({q['question_id'] for q in self.questions}))

    def test_manifest_current_material_count_matches_corpus(self):
        manifest = json.loads((KB / 'MANIFEST.json').read_text(encoding='utf-8'))
        actual = sum(len(rows(path)) for path in (KB / 'materials').glob('*/*/*.jsonl'))
        self.assertEqual(actual, manifest['materials'])

    def test_module_to_knowledge_path_exists(self):
        modules = {n['id'] for n in self.nodes.values() if n.get('layer') == 'L2'}
        linked = {e['src'] for e in self.edges if e['src'] in modules and self.nodes[e['dst']].get('layer') == 'L4'}
        self.assertEqual(modules, linked)

    def test_geography_atmosphere_is_assessable(self):
        q = next(q for q in self.questions if q['subject'] == 'dili' and '反射无线电波' in q['content']['stem'])
        names = [self.nodes[nid]['name'] for nid in q['knowledge_node_ids']]
        self.assertTrue(any('大气' in name for name in names), names)
        self.assertNotIn('学科专业知识', names)

    def test_source_verification_is_not_expert_review(self):
        q = self.questions[0]
        self.assertIn('raw_file_verification', q['source'])
        self.assertFalse(q['source']['verified'])
        self.assertFalse(q['review'].get('content_verified'))

    def test_subject_and_interview_ability_mapping(self):
        for subject in ('dili', 'shuxue', 'yingyu', 'mianshi'):
            candidates = [q for q in self.questions if q['subject'] == subject and len(q['content']['stem']) > 50]
            self.assertTrue(any(q.get('ability_ids') for q in candidates), subject)

    def test_prerequisites_are_documented_dependencies(self):
        for edge in self.edges:
            if edge['type'] == 'prerequisite':
                self.assertTrue(edge.get('rationale'), edge)
                self.assertTrue(edge.get('review_status'), edge)
                self.assertNotIn('按大纲顺序', edge.get('note', ''))

    def test_nine_semantic_tag_groups_and_pending_queue(self):
        expected = {'exam', 'subject', 'question_type', 'knowledge', 'ability', 'difficulty', 'source', 'review', 'copyright'}
        for q in self.questions:
            self.assertTrue(expected.issubset(q.get('tags', {})), q['question_id'])
        self.assertTrue((KB / 'review/pending.jsonl').exists())

    def test_option_parser_ignores_letters_inside_question_and_repeated_markers(self):
        from build_kb import parse_question_text
        body = '1气体在A、B、C三个状态变化，正确的是（）。A、A、等温B、B、等压C、C、等容D、D、绝热'
        q = parse_question_text(1, body)
        self.assertEqual(['A', 'B', 'C', 'D'], [o['key'] for o in q['options']])
        self.assertEqual('等温', q['options'][0]['text'])
        self.assertIn('C三个状态', q['stem'])

    def test_numeric_candidate_uses_absolute_offset(self):
        from build_kb import find_k
        text = '题干 3年后继续学习。下一题3正确题干。'
        hit = find_k(text, 3, len(text), 3)
        self.assertEqual(text.index('3正确'), hit[0])

    def test_option_parser_does_not_promote_later_merged_question(self):
        from build_kb import parse_question_text
        body = '1甲问题。A、甲一B、甲二C、甲三D、甲四2乙问题。A、乙一B、乙二C、乙三D、乙四'
        q = parse_question_text(1, body)
        self.assertEqual('甲问题。', q['stem'])
        self.assertEqual('甲一', q['options'][0]['text'])

    def test_manual_rubric_and_tag_extensions_survive_refresh(self):
        import ntce_repair
        self.assertTrue(callable(getattr(ntce_repair, 'practice_rubric', None)), 'manual-preserving rubric refresh missing')
        practice_rubric, refresh_tags = ntce_repair.practice_rubric, ntce_repair.refresh_tags
        q = {'exam': 'NTCE', 'subject': 'dili', 'question_type': '教学设计', 'knowledge_node_ids': ['manual.node'],
             'ability_ids': ['manual.ability'], 'exam_requirement_ids': ['official.r001'], 'difficulty': None,
             'source': {'session': '2023a', 'files': [], 'source_classification': '真题', 'copyright': {'authorization_status': 'authorized'}},
             'review': {'status': 'expert_reviewed', 'tagger': 'expert', 'content_verified': True, 'checked_by': 'teacher-1'},
             'rubric': {'status': 'expert_approved', 'checked_by': 'teacher-1', 'evidence': ['review-42'],
                        'question_specific_points': ['正确解释大气分层'], 'dimensions': [{'name': '内容准确', 'weight': 10}]},
             'tags': {'source': {'manual_evidence': 'archive-42'}, 'custom': 'keep'}}
        original = json.loads(json.dumps(q['rubric'], ensure_ascii=False))
        for _ in range(2):
            practice_rubric(q)
            refresh_tags(q)
        for key, value in original.items():
            self.assertEqual(value, q['rubric'][key])
        self.assertEqual('archive-42', q['tags']['source']['manual_evidence'])
        self.assertEqual('keep', q['tags']['custom'])
        self.assertEqual('teacher-1', q['review']['checked_by'])

    def test_manual_content_and_mapping_survive_automatic_repair(self):
        from ntce_repair import refresh_mapping, recover_options, recover_source_answer, quarantine_unsafe_answer
        q = {'exam': 'NTCE', 'level': 'xiaoxue', 'question_type': '单选',
             'knowledge_node_ids': ['manual.node'], 'ability_ids': ['manual.ability'], 'exam_requirement_ids': ['manual.requirement'],
             'content': {'stem': '教师已核对的特殊试题', 'options': [{'key': 'A', 'text': '甲'}, {'key': 'B', 'text': '乙'}],
                         'answer': 'C', 'answer_status': 'letter_only'}, 'extra': {}, 'source': {'files': []},
             'review': {'status': '专家审核', 'tagger': 'expert', 'content_verified': True, 'checked_by': 'teacher-1',
                        'evidence': ['review-42'], 'requirement_mapping_status': 'expert_approved', 'answer_validation_status': 'expert_approved'}}
        expected = json.loads(json.dumps(q))
        for _ in range(2):
            self.assertFalse(recover_options(q))
            recover_source_answer(q, {})
            quarantine_unsafe_answer(q)
            refresh_mapping(q, {'manual.node': {'ability_codes': ['different'], 'exam_requirement_ids': ['different']}})
        self.assertEqual(expected, q)

    def test_retired_official_ids_are_absent_everywhere(self):
        path = ROOT / '权威资料/retired_requirement_ids.json'
        retired_record = json.loads(path.read_text(encoding='utf-8'))
        retired = set(retired_record if isinstance(retired_record, list) else retired_record['retired'])
        self.assertFalse(retired.intersection(self.nodes))
        for q in self.questions:
            self.assertFalse(retired.intersection(q['exam_requirement_ids']), q['question_id'])
            self.assertFalse(retired.intersection(q.get('rubric', {}).get('exam_requirement_ids', [])), q['question_id'])

    def test_quarantined_answer_is_not_reintroduced_on_rerun(self):
        from ntce_repair import recover_source_answer, ROOT as SOURCE_ROOT
        q = {'content': {'answer': None, 'answer_status': 'source_conflict', 'options': [{'key': key, 'text': key} for key in 'ABCD']},
             'source': {'files': [{'role': 'answer_raw', 'path': 'fixture.csv', 'locator': {}}]}, 'review': {},
             'extra': {'source_question_number': 1, 'source_boundary_verification': {'status': 'unique_text_boundary'},
                       'answer_candidate': {'answer': 'A', 'reason': 'possible_cross_question_mix'}}}
        expected = json.loads(json.dumps(q['content']))
        recover_source_answer(q, {SOURCE_ROOT / 'fixture.csv': {1: 'A'}})
        self.assertEqual(expected, q['content'])
        self.assertNotIn('source_repairs', q['extra'])

    def test_llm_receives_complete_context_or_skips(self):
        from llm_batch import input_status, question_brief
        q = {'question_id': 'q1', 'question_type': '材料分析', 'material_id': 'm1', 'extra': {},
             'review': {}, 'source': {'raw_file_verification': {'content_alignment': 'stem_excerpt_found'}},
             'content': {'stem': '请依据完整材料分析该教师的课堂行为。', 'options': [{'key': 'A', 'text': '甲' * 100}], 'answer': None}}
        material = '材料正文' * 200
        self.assertIn(material, question_brief(q, material))
        self.assertIn('甲' * 100, question_brief(q, material))
        self.assertEqual('complete', input_status(q, material)['status'])
        self.assertIn('linked_material_missing', input_status(q)['reasons'])
        q['review']['cross_question_risk'] = ['multiple_complete_choice_sequences']
        self.assertIn('cross_question_risk', input_status(q, material)['reasons'])
        self.assertFalse(input_status(q, material)['input_truncated'])

    def test_source_placeholders_and_five_letter_answers_are_not_explanations(self):
        from build_kb import classify_answer
        self.assertEqual(('missing', None), classify_answer('缺。'))
        self.assertEqual(('missing', None), classify_answer('略'))
        self.assertEqual(('letter', 'ABCDE'), classify_answer('ABCDE'))
        self.assertEqual(('source_conflict', None), classify_answer('此题问题与答案不符。建议去掉此题。'))

    def test_llm_missing_visual_context_checks_material_and_options(self):
        from llm_batch import input_status
        q = {'question_id': 'q1', 'question_type': '材料分析', 'extra': {}, 'review': {},
             'source': {'raw_file_verification': {'content_alignment': 'stem_excerpt_found'}},
             'content': {'stem': '请依据所给资料回答本题。', 'options': [], 'answer': None}}
        self.assertIn('visual_context_not_verified', input_status(q, '教师出示如下图，要求观察图中现象。')['reasons'])
        q['content']['options'] = [{'key': 'A', 'text': '参照下表中的结果'}]
        self.assertIn('visual_context_not_verified', input_status(q)['reasons'])
        q['content']['stem'] = '句中划线词语含贬义色彩的一项是（ ）。'
        self.assertIn('formatted_context_not_verified', input_status(q)['reasons'])

    def test_analysis_budget_exhaustion_stops_all_files(self):
        import llm_batch
        from unittest.mock import patch
        from tempfile import TemporaryDirectory
        q = {'question_id': 'q1', 'question_type': '单选', 'extra': {}, 'review': {'type_source_verification': {'status': 'verified_choice_task_and_section'}},
             'knowledge_node_ids': [], 'source': {'raw_file_verification': {'content_alignment': 'stem_excerpt_found'}},
             'content': {'stem': '这个完整试题有四个非空选项。', 'options': [{'key': k, 'text': k} for k in 'ABCD'],
                         'answer': 'A', 'answer_status': 'letter_only', 'analysis': None}}
        with TemporaryDirectory() as tmp:
            paths = [Path(tmp) / name for name in ('one.jsonl', 'two.jsonl')]
            for path in paths:
                path.write_text(json.dumps(q) + '\n', encoding='utf-8')
            with patch.object(llm_batch, 'iter_subject_files', return_value=iter([('xiaoxue', 'zonghe', p) for p in paths])), \
                 patch.object(llm_batch, 'OUT', Path(tmp)), \
                 patch.object(llm_batch, 'load_materials', return_value={}), \
                 patch.object(llm_batch, 'chat', side_effect=llm_batch.BudgetLimit('stop')) as chat, \
                 patch('ntce_repair.repair', return_value={}):
                llm_batch.gen_analysis({'LLM_MODEL': 'deepseek-flash'}, 8)
                self.assertEqual(1, chat.call_count)

    def test_atomic_writer_never_exposes_partial_file(self):
        import ntce_io
        from unittest.mock import patch
        from tempfile import TemporaryDirectory
        import os
        with TemporaryDirectory() as tmp:
            destination = Path(tmp) / 'questions.jsonl'
            destination.write_text('old-complete\n', encoding='utf-8')
            replace = os.replace
            def checked_replace(source, target):
                self.assertEqual(destination.parent, Path(source).parent)
                self.assertEqual('old-complete\n', destination.read_text(encoding='utf-8'))
                self.assertEqual('new-complete\n' * 100, Path(source).read_text(encoding='utf-8'))
                return replace(source, target)
            with patch.object(ntce_io.os, 'replace', side_effect=checked_replace):
                ntce_io.atomic_write(destination, 'new-complete\n' * 100)
            self.assertEqual('new-complete\n' * 100, destination.read_text(encoding='utf-8'))
            self.assertEqual([destination], list(destination.parent.iterdir()))

    def test_subjective_case_material_boundaries_recovered_from_source(self):
        materials = {m['material_id']: m for path in (KB / 'materials').glob('*/*/*.jsonl') for m in rows(path)}
        q = next(q for q in self.questions if q['question_id'] == 'ntce.youer.baojiao.2011b.q23')
        self.assertTrue(q['material_id'], '洋洋任务缺少本题材料')
        self.assertNotIn('成成', q['content']['stem'])
        self.assertIn('洋洋', materials[q['material_id']]['text'])
        following = next(q for q in self.questions if q['question_id'] == 'ntce.youer.baojiao.2011b.q24')
        self.assertIn('成成', materials[following['material_id']]['text'])
        self.assertIn('case_entity_mismatch_in_source', following['review']['cross_question_risk'])

    def test_missing_case_material_blocks_model_input(self):
        from llm_batch import input_status
        q = {'question_id': 'q1', 'question_type': '材料分析', 'extra': {}, 'review': {},
             'source': {'raw_file_verification': {'content_alignment': 'stem_excerpt_found'}},
             'content': {'stem': '请结合这个案例分析教师采用的活动策略。', 'options': [], 'answer': None}}
        self.assertIn('case_material_boundary_unresolved', input_status(q)['reasons'])

    def test_case_age_is_narrative_but_numbered_task_is_not(self):
        from ntce_material_repair import narrative_section
        self.assertTrue(narrative_section('4岁的成成与其他幼儿在沙池里进行游戏。'))
        self.assertFalse(narrative_section('2请分析幼儿活动中教师的教育行为。'))

    def test_inline_case_does_not_require_separate_material_record(self):
        from ntce_material_repair import case_risks, needs_preceding_material
        stem = '一次活动后，夏老师看到一个孩子钻到了桌子底下，趴在地上。于是夏老师将他叫起，问他地上这么脏，为什么趴在地上？他听后委屈地掉下了眼泪，小声说：“老师，地上有纸屑，我想把它扫干净。”夏老师点了点头。该案例表明师幼关系具有（ ）。'
        q = {'question_type': '单选', 'content': {'stem': stem}}
        self.assertNotIn('case_reference_without_attached_material', case_risks(q))
        self.assertFalse(needs_preceding_material(q))
        q['content']['stem'] = '在这个案例中，教师应如何引导幼儿进行活动？请分别说明原因和具体措施。'
        self.assertIn('case_reference_without_attached_material', case_risks(q))
        self.assertTrue(needs_preceding_material(q))

    def test_reference_locator_checks_actual_context_not_just_range(self):
        from ntce_reference_import import validate_references, refresh_imported_references
        import copy
        draft = rows(ROOT / '补充资料/教资参考解答/reference_drafts.jsonl')[0]
        self.assertIsNone(validate_references(draft))
        shifted = copy.deepcopy(draft)
        shifted['source_files'][0]['locator']['line_start'] += 1
        shifted['source_files'][0]['locator']['line_end'] += 1
        self.assertEqual('reference_context_hash_mismatch', validate_references(shifted))
        q = {'source': {'files': [{'path': 'original.csv', 'role': 'question_raw'}]},
             'analysis': {'draft_id': draft['draft_id'], 'explanation': '保留原稿', 'generation': {'seed_sha256': 'original'}},
             'rubric': {'question_specific_points': [{'point_id': draft['draft_id'] + '.p1', 'expected': '保留具体评分点'}]}}
        refresh_imported_references(q, draft)
        refresh_imported_references(q, draft)
        self.assertEqual('保留原稿', q['analysis']['explanation'])
        self.assertEqual('original', q['analysis']['generation']['seed_sha256'])
        self.assertEqual('保留具体评分点', q['rubric']['question_specific_points'][0]['expected'])
        self.assertEqual(len(draft['source_files']) + 1, len(q['source']['files']))

    def test_raw_choice_type_and_subjective_offset_letter_are_distinguished(self):
        choice = next(q for q in self.questions if q['question_id'] == 'ntce.chuzhong.dili.2014a-jx.q01')
        self.assertEqual('单选', choice['question_type'])
        subjective = next(q for q in self.questions if q['question_id'] == 'ntce.chuzhong.dili.2016b.q03')
        self.assertEqual('材料分析', subjective['question_type'])
        self.assertIsNone(subjective['content']['answer'])
        self.assertEqual('source_conflict', subjective['content']['answer_status'])

    def test_next_section_header_is_not_appended_to_last_option(self):
        from ntce_repair import recover_options
        from ntce_type_repair import source_sections
        stem = '关于教师教学组织，下列处理方式最恰当的是（ ）。'
        q = {'question_type': '单选', 'content': {'stem': stem, 'options': [{'key': key, 'text': key+'项'} for key in 'ABCD']}, 'review': {}, 'extra': {}}
        raw = '一、单项选择题（本大题共1小题）1' + stem + 'A、A项B、B项C、C项D、D项二、简答题（本大题共1小题）2简述教师教学方法的选择要求。'
        recover_options(q, raw, source_sections(raw))
        self.assertEqual('D项', q['content']['options'][-1]['text'])

    def test_verified_current_choice_preserves_resolution_of_old_ambiguity(self):
        from ntce_type_repair import repair_type, source_sections
        from ntce_repair import recover_options
        stem = '关于教师教学组织，下列处理方式最恰当的是（ ）。'
        q = {'question_id': 'q1', 'question_type': '单选', 'section': '单项选择题',
             'content': {'stem': stem, 'options': [{'key': key, 'text': key+'项'} for key in 'ABCD'], 'answer': 'A', 'answer_status': 'letter_only'},
             'source': {'origin_file': 'fixture.csv', 'files': []}, 'review': {},
             'extra': {'source_boundary_verification': {'status': 'ambiguous_boundary_candidates', 'candidate_count': 2}}}
        raw = '一、单项选择题（本大题共2小题）1' + stem + 'A、A项B、B项C、C项D、D项2下列教学方法正确的是（）。A、甲B、乙C、丙D、丁'
        sections = source_sections(raw)
        proof = repair_type(q, raw, sections)
        self.assertTrue(proof['current_options_exact_match'])
        self.assertEqual('unique_text_boundary', q['extra']['source_boundary_verification']['status'])
        self.assertEqual(2, q['extra']['boundary_history'][0]['before']['candidate_count'])
        recover_options(q, raw, sections)
        self.assertEqual('unique_text_boundary', q['extra']['source_boundary_verification']['status'])

    def test_source_text_comparison_preserves_mathematical_symbols(self):
        from ntce_type_repair import exact_text
        self.assertNotEqual(exact_text('x²'), exact_text('x2'))
        self.assertNotEqual(exact_text('x₂'), exact_text('x2'))
        self.assertNotEqual(exact_text('①'), exact_text('1'))
        self.assertEqual(exact_text('教师Ａ：ｘ＋２　'), exact_text('教师 A:x+2'))

    def test_boundary_ambiguity_is_pending_without_abcd_mix_risk(self):
        import copy
        from ntce_repair import question_pending
        q = copy.deepcopy(self.questions[0])
        q['review']['cross_question_risk'] = []
        q['review']['source_boundary_status'] = 'ambiguous_boundary_candidates'
        q['extra']['source_boundary_verification'] = {'status': 'ambiguous_boundary_candidates', 'candidate_count': 2}
        self.assertIn('source_boundary_alignment_needed', question_pending(q))


if __name__ == '__main__':
    unittest.main()
