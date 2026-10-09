"""官方样题抽取和严格恢复的实际来源回归；不修改主库。"""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'kb_tools' / 'official_examples.py'
if MODULE.exists():
    spec = importlib.util.spec_from_file_location('official_examples', MODULE)
    official = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(official)
else:
    official = None


class OfficialExamplesRegression(unittest.TestCase):
    def test_implementation_available(self):
        self.assertIsNotNone(official, '严格官方样题抽取与匹配接口尚未实现')

    @classmethod
    def setUpClass(cls):
        cls.examples = official.extract_catalog(ROOT) if official else []

    def require_implementation(self):
        if official is None:
            self.skipTest('等待实现后再运行来源回归')

    def example(self, number):
        return next(e for e in self.examples if e['example_id'] == f'ntce.outline.317.sample.{number:02d}')

    def question(self, sample, question_id='test.q1'):
        return {'question_id': question_id, 'exam': 'NTCE', 'level': 'chuzhong', 'subject': 'kexue',
                'material_id': None, 'content': {'stem': sample['stem'], 'options': sample['options'],
                                               'answer': None, 'answer_status': 'reference_only'},
                'review': {'cross_question_risk': []}}

    def test_all_38_sources_have_retained_sample_text(self):
        self.require_implementation()
        self.assertEqual(38, len({e['source_id'] for e in self.examples}))
        for e in self.examples:
            p = ROOT / e['locator']['text_path']
            lines = p.read_text(encoding='utf-8-sig').split('\n')
            loc = e['locator']
            self.assertEqual('\n'.join(lines[loc['line_start'] - 1:loc['line_end']]), e['raw_question_text'])
            self.assertTrue(e['source_url'].startswith('https://ntce.neea.edu.cn/'))

    def test_science_has_seven_explicit_answers_but_two_complete_text_examples(self):
        self.require_implementation()
        science = [e for e in self.examples if e['source_id'] == 'ntce.outline.317']
        self.assertEqual(7, len(science))
        self.assertEqual(7, sum(e['answer_present'] for e in science))
        self.assertEqual([3, 5], [e['source_question_number'] for e in science if e['recovery_eligible']])
        self.assertIn('科学家案例', self.example(5)['answer'])
        self.assertIn('【评分说明】', self.example(6)['raw_answer_text'])
        self.assertIn('①教学目标', self.example(7)['raw_answer_text'])

    def test_quoted_wrong_answer_is_not_an_official_answer(self):
        self.require_implementation()
        wrong_context = [e for e in self.examples if e['source_id'] == 'ntce.outline.407' and '故答案为B' in e['raw_question_text']]
        self.assertEqual(1, len(wrong_context))
        self.assertFalse(wrong_context[0]['answer_present'])
        self.assertIsNone(wrong_context[0]['answer'])

    def test_english_design_and_classroom_dialogue_are_retained(self):
        self.require_implementation()
        for source_id in ('ntce.outline.305', 'ntce.outline.405'):
            records = [e for e in self.examples if e['source_id'] == source_id]
            self.assertTrue(any('教学设计需包括' in e['raw_question_text'] for e in records))
            self.assertTrue(any('My mum buyed' in e['raw_question_text'] for e in records))

    def test_interview_global_rubric_is_not_a_sample_answer(self):
        self.require_implementation()
        interview = [e for e in self.examples if e['source_id'].startswith('ntce.interview.')]
        self.assertEqual(6, len(interview))
        self.assertFalse(any(e['answer_present'] for e in interview))
        self.assertTrue(all(e['general_scoring_locator'] for e in interview))

    def test_complete_stem_nfkc_whitespace_unique_match(self):
        self.require_implementation()
        sample = self.example(5)
        q = self.question(sample)
        q['content']['stem'] = q['content']['stem'].replace('“', '“\u3000').replace('”', '\n”')
        matches = official.match_examples([sample], [q])
        self.assertEqual('exact_unique_recoverable', matches[0]['status'])
        patch = official.recovery_patches(matches, [sample], [q])
        self.assertEqual(1, len(patch))
        self.assertFalse(patch[0]['expert_verified'])
        self.assertEqual(sample['answer'], patch[0]['answer'])

    def test_duplicate_complete_stems_are_ambiguous(self):
        self.require_implementation()
        sample = self.example(5)
        matches = official.match_examples([sample], [self.question(sample, 'a'), self.question(sample, 'b')])
        self.assertEqual('ambiguous_kb_match', matches[0]['status'])
        self.assertEqual([], official.recovery_patches(matches, [sample], []))

    def test_short_excerpt_and_matching_number_cannot_recover(self):
        self.require_implementation()
        sample = self.example(5)
        q = self.question(sample)
        q['content']['stem'] = '简述科学史在科学教学中的功能。'
        q['extra'] = {'source_question_number': 5}
        self.assertEqual('no_exact_match', official.match_examples([sample], [q])[0]['status'])

    def test_changed_material_and_options_cannot_recover(self):
        self.require_implementation()
        sample = self.example(3)
        q = self.question(sample)
        q['content']['options'] = [dict(o) for o in q['content']['options']]
        q['content']['options'][0]['text'] = '替换的选项'
        self.assertEqual('no_exact_match', official.match_examples([sample], [q])[0]['status'])
        q = self.question(self.example(5))
        q['material_id'] = 'unverified-context'
        self.assertEqual('context_not_equivalent', official.match_examples([self.example(5)], [q])[0]['status'])

    def test_missing_word_objects_are_never_recoverable(self):
        self.require_implementation()
        sample = self.example(6)
        q = self.question(sample)
        matches = official.match_examples([sample], [q])
        self.assertEqual('text_context_incomplete_for_matching', matches[0]['status'])
        self.assertEqual([], official.recovery_patches(matches, [sample], [q]))

    def test_original_objects_are_preserved_as_visual_context(self):
        self.require_implementation()
        for number in range(1, 8):
            sample = self.example(number)
            self.assertEqual('complete_original_visual_context', sample.get('original_context_status'))
            self.assertIn(sample['visual_context']['question_page'], [4, 5])
            self.assertIn(sample['visual_context']['answer_page'], [6, 7])
            self.assertTrue((ROOT / sample['visual_context']['pdf_path']).is_file())
        self.assertIn('6000Pa', self.example(6)['object_transcription'])
        self.assertIn('176N', self.example(6)['object_transcription'])

    def test_jsonl_uses_physical_lines_with_unicode_separator(self):
        self.require_implementation()
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'rows.jsonl'
            p.write_text(json.dumps({'text': 'a\u2028b'}, ensure_ascii=False) + '\n', encoding='utf-8')
            self.assertEqual([{'text': 'a\u2028b'}], official.read_jsonl(p))

    def test_stale_match_is_rechecked_before_patch_generation(self):
        self.require_implementation()
        sample = self.example(5)
        q = self.question(sample)
        matches = official.match_examples([sample], [q])
        q['content']['stem'] += '附加了另一题的要求。'
        self.assertEqual([], official.recovery_patches(matches, [sample], [q]))

    def test_supplementary_catalog_keeps_publisher_metadata_out_of_answers(self):
        self.require_implementation()
        index = json.loads((ROOT / '补充资料/教资官方样题/supplementary_sources.json').read_text(encoding='utf-8'))
        self.assertEqual(9, len(index['sources']))
        self.assertEqual(9, len({s['source_id'] for s in index['sources']}))
        for source in index['sources']:
            self.assertFalse(source['exact_kb_answers_acquired'])
            if source['authority'].endswith('出版社'):
                self.assertFalse(source['body_acquired'])
        guide = next(s for s in index['sources'] if s['source_id'] == 'moe.preschool_guideline.2012')
        self.assertEqual(guide['sha256'], official.digest(ROOT / guide['local_path']))
        self.assertIn(guide['short_quote'], (ROOT / guide['text_path']).read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
