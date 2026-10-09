"""Source identity regressions for the 2026-10-04 CET passage repair."""
import importlib.util
import sys
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / '数据集/四六级'
sys.path.insert(0, str(KB / 'scripts'))
from cet_common import load_jsonl, merge_jsonl


class SourceIdentityTests(unittest.TestCase):
    def repair_module(self):
        path = KB / 'scripts/repair_passage_references.py'
        self.assertTrue(path.is_file(), 'The source identity reconciler must exist')
        spec = importlib.util.spec_from_file_location('repair_passage_references', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def fixture(self):
        text = ('Reading Comprehension\nSection C\nPassage One\n'
                'Questions 56 to 60 are based on the following passage.\n'
                'The researchers studied how clocks affect creativity at work.\n'
                '46. What did the researchers study?\nA) Clocks.\nB) Plants.\nC) Rivers.\nD) Cities.\n'
                '47. What was affected at work?\nA) Sleep.\nB) Creativity.\nC) Travel.\nD) Food.\nPart IV Translation')
        q = {'question_id': 'retained-reading-51', 'question_type': '仔细阅读',
             'content': {'stem': 'What did the researchers study?', 'options': dict(zip('ABCD', ['Clocks.', 'Plants.', 'Rivers.', 'Cities.']))}}
        p = {'resource_id': 'retained-c1', 'kind': 'reading', 'text': 'The researchers studied how clocks affect creativity at work.'}
        return text, q, p

    def test_full_identity_proves_actual_source_number_despite_conflicting_printed_range(self):
        mod = self.repair_module()
        text, q, p = self.fixture()
        matches = mod.source_matches(q, p, text, [], ROOT / 'source.docx', ROOT)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['source_question_number'], 46)
        self.assertTrue(matches[0]['source_boundary_warnings'])

    def test_same_file_number_or_partial_options_cannot_prove_identity(self):
        mod = self.repair_module()
        text, q, p = self.fixture()
        q['content']['options']['D'] = 'A choice from the next question.'
        self.assertEqual(mod.source_matches(q, p, text, [], ROOT / 'source.docx', ROOT), [])

    def test_legacy_rebuild_cannot_reactivate_a_quarantined_passage_link(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'questions.jsonl'
            old = {'question_id': 'cet4-2015-12-p2-reading-53', 'module': '阅读理解',
                   'content': {}, 'extra': {'passage_id': None,
                                           'passage_binding': {'status': 'quarantined_no_unique_source_identity'}}}
            path.write_text(json.dumps(old), encoding='utf-8')
            merge_jsonl(path, [{'id': 'cet4.r.2015-12_p2.q53', 'module': '阅读',
                                'passage_id': 'cet4.r.2015-12_p2.c1'}])
            self.assertIsNone(load_jsonl(path)[0]['extra']['passage_id'])

    def test_complete_original_inline_options_can_prove_identity(self):
        mod = self.repair_module()
        text, q, p = self.fixture()
        text = text.replace('A) Clocks.\nB) Plants.\nC) Rivers.\nD) Cities.',
                            'A) Clocks.\tB) Plants.   C) Rivers.\tD) Cities.')
        matches = mod.source_matches(q, p, text, [], ROOT / 'source.docx', ROOT)
        self.assertEqual(len(matches), 1)
        q['content']['options'] = dict(zip('ABCD', ['Clocks.', 'Plants.', 'Rivers.', 'Cities.']))
        p['text'] = 'A different article about a criminal record and justice.'
        self.assertEqual(mod.source_matches(q, p, text, [], ROOT / 'source.docx', ROOT), [])

    def test_same_article_prefix_with_different_tail_cannot_prove_identity(self):
        mod = self.repair_module()
        text, q, p = self.fixture()
        common = 'A complete description of the researchers and their study. ' * 5
        text = text.replace(p['text'], common + 'The final finding supports clocks.')
        p['text'] = common + 'The final finding rejects clocks.'
        self.assertEqual(mod.source_matches(q, p, text, [], ROOT / 'source.docx', ROOT), [])

    def test_english_word_boundaries_are_part_of_source_identity(self):
        mod = self.repair_module()
        text, q, p = self.fixture()
        text = text.replace('A) Clocks.', 'A) They are now here.')
        q['content']['options']['A'] = 'They are nowhere.'
        self.assertEqual(mod.source_matches(q, p, text, [], ROOT / 'source.docx', ROOT), [])

    def test_decimal_point_is_part_of_source_identity(self):
        mod = self.repair_module()
        text, q, p = self.fixture()
        text = text.replace('A) Clocks.', 'A) The result was 0.5.')
        q['content']['options']['A'] = 'The result was 05.'
        self.assertEqual(mod.source_matches(q, p, text, [], ROOT / 'source.docx', ROOT), [])

    def test_matching_paragraph_labels_are_part_of_complete_source_identity(self):
        mod = self.repair_module()
        a = 'The scientist observed insects and their life cycles in a tropical forest.'
        b = 'The drawings helped other scientists understand species and their habitats.'
        stem = 'The scientist travelled to a tropical forest to study insects.'
        text = f'Reading Comprehension\nSection B\n[A] {a}\n[B] {b}\n36. {stem}\nSection C\n'
        q = {'question_id': 'retained-reading-36', 'question_type': '长篇阅读', 'content': {'stem': stem}}
        p = {'resource_id': 'retained-matching', 'kind': 'matching', 'text': a + ' ' + b,
             'extra': {'paragraphs': [{'letter': 'A', 'text': a}, {'letter': 'B', 'text': b}]}}
        self.assertEqual(len(mod.source_matches(q, p, text, [], ROOT / 'source.docx', ROOT)), 1)
        p['extra']['paragraphs'][1]['letter'] = 'C'
        self.assertEqual(mod.source_matches(q, p, text, [], ROOT / 'source.docx', ROOT), [])

    def test_superscript_is_part_of_source_identity(self):
        mod = self.repair_module()
        text, q, p = self.fixture()
        text = text.replace('A) Clocks.', 'A) The area is 2 m².')
        q['content']['options']['A'] = 'The area is 2 m2.'
        self.assertEqual(mod.source_matches(q, p, text, [], ROOT / 'source.docx', ROOT), [])

    def test_full_width_ascii_is_an_equivalent_layout(self):
        mod = self.repair_module()
        text, q, p = self.fixture()
        q['content']['options']['A'] = 'Ｃｌｏｃｋｓ．'
        self.assertEqual(len(mod.source_matches(q, p, text, [], ROOT / 'source.docx', ROOT)), 1)


class PassageArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.passages = {r['resource_id']: r for r in load_jsonl(KB / 'passages/reading.jsonl')}
        cls.questions = {r['question_id']: r for p in (KB / 'questions').rglob('*.jsonl') for r in load_jsonl(p)}

    def test_restored_source_questions_have_both_passage_references(self):
        groups = [('cet4-2015-06-p1', [54, 55]), ('cet4-2017-06-p2', [47, 48]),
                  ('cet4-2020-12-p1', [46, 47, 48, 52, 53, 54, 55]),
                  ('cet6-2018-12-p2', [36, 37, 40, 41, 42, 43, 44, 45])]
        for prefix, numbers in groups:
            for number in numbers:
                qid = f'{prefix}-reading-{number}'
                q = self.questions[qid]
                passage = self.passages[q['extra']['passage_id']]
                self.assertIn(qid, passage['extra']['question_ids'], qid)
                self.assertEqual(q['extra']['passage_binding']['status'], 'source_identity_verified_pending_expert_review')

    def test_inactive_parser_artifacts_keep_history_without_active_passage_reference(self):
        for number in range(56, 60):
            q = self.questions[f'cet4-2015-12-p2-reading-{number}']
            self.assertIsNone(q['extra'].get('passage_id'), q['question_id'])
            self.assertTrue(q['extra'].get('passage_reference_history'))
            self.assertFalse(q['extra']['active'])

    def test_source_number_is_not_inferred_from_preserved_id(self):
        q = self.questions['cet4-2015-12-p2-reading-51']
        self.assertEqual(q['extra'].get('source_question_number'), 46)
        self.assertEqual(q['extra']['number'], 51)
        self.assertEqual(q['extra']['passage_id'], 'cet4-2015-12-p2-reading-c1')
        self.assertTrue(q['extra']['passage_binding']['source_boundary_warnings'])

    def test_mixed_baseline_options_cannot_prove_passage_binding(self):
        for number in list(range(46, 51)) + list(range(52, 56)):
            q = self.questions[f'cet4-2015-12-p2-reading-{number}']
            self.assertIsNone(q['extra'].get('passage_id'), q['question_id'])
            self.assertEqual(q['extra']['passage_binding']['status'], 'quarantined_no_unique_source_identity')
            self.assertTrue(q['extra']['passage_reference_history'])
            self.assertFalse(q['extra'].get('scoring_eligible', True))
            self.assertEqual(q['extra'].get('source_identity_review', {}).get('status'), 'pending')

    def test_all_existing_forward_links_have_the_same_back_reference(self):
        for qid, q in self.questions.items():
            pid = q['extra'].get('passage_id')
            if pid:
                self.assertIn(qid, self.passages[pid]['extra']['question_ids'], qid)

    def test_source_article_recovery_removes_question_contamination_and_retains_complete_old_text(self):
        polluted = {
            'cet4-2015-06-p1-reading-c2': 'What gives women a ray of hope',
            'cet4-2017-06-p2-reading-c1': 'The market sales of toilet paper have decreased',
            'cet4-2020-12-p1-reading-c1': 'What are teachers complaining about?',
            'cet4-2020-12-p1-reading-c2': 'Why does the author ask us to imagine buying food',
            'cet6-2018-12-p2-reading-matching': 'Merian was the first scientist to study a type of American ant.',
        }
        for pid, contamination in polluted.items():
            passage = self.passages[pid]
            self.assertNotIn(contamination, passage['text'], pid)
            self.assertTrue(any(contamination in h['text'] for h in passage['extra'].get('text_history', [])), pid)

    def test_source_article_recovery_completes_a_proven_truncated_article(self):
        passage = self.passages['cet4-2015-12-p2-reading-c2']
        self.assertIn('second chances are crucial', passage['text'])
        self.assertTrue(passage['extra'].get('text_history'))

    def test_stats_expose_new_source_identity_gaps(self):
        stats = json.loads((KB / 'manifest/stats.json').read_text('utf-8'))
        self.assertEqual(stats['remaining_gaps'].get('reading_unlinked_active_passage'), 9)
        self.assertEqual(stats['passages'].get('reference_repair', {}).get('original_structure_errors'), 23)


if __name__ == '__main__':
    unittest.main()
