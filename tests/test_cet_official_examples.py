import copy
import unittest
from pathlib import Path

from kb_tools.cet_official_examples import (
    extract_official, match_examples, normalize_text, parse_options, recovery_patches, standardize, read_jsonl,
)

ROOT = Path(__file__).resolve().parents[1]


class TextAndMatchTests(unittest.TestCase):
    def test_normalization_preserves_word_boundaries(self):
        self.assertEqual(normalize_text(' Ａ　good\n choice . '), 'A good choice.')
        self.assertNotEqual(normalize_text('the man'), normalize_text('theman'))

    def test_punctuation_spaces_and_abbreviations_are_readable(self):
        self.assertEqual(normalize_text('below.You should write.U.S.Department;Mr.Palmer'),
                         'below. You should write. U.S. Department; Mr. Palmer')
        self.assertEqual(normalize_text('7.5 million and 1,167 people'), '7.5 million and 1,167 people')

    def test_two_column_options_and_cross_line_decimal(self):
        self.assertEqual(parse_options('A) On Christmas Eve. C) During a security check.\nB) Just before midnight. D) In the morning.'),
                         {'A': 'On Christmas Eve.', 'B': 'Just before midnight.', 'C': 'During a security check.', 'D': 'In the morning.'})

    def example(self):
        return {'example_id': 'source.1', 'exam': 'CET-4', 'question_type': 'reading_detail',
                'stem': 'What does the writer mean?', 'options': {'A': 'First.', 'B': 'Second.'},
                'passage': 'The complete original passage.', 'answer': 'B',
                'text_quality': 'visually_verified', 'source': {'source_id': 'official', 'pdf_pages': [1]}}

    def question(self):
        return {'question_id': 'old.1', 'exam': 'CET-4', 'content': {'stem': 'What does the writer mean?',
                'options': {'A': 'First.', 'B': 'Second.'}, 'answer': None},
                '_passage_text': 'The complete original passage.'}

    def test_full_context_unique_match(self):
        matches = match_examples([self.example()], [self.question()])
        self.assertEqual(matches[0]['status'], 'exact_unique_match')
        self.assertEqual(len(recovery_patches(matches, [self.example()], [self.question()])), 1)

    def test_same_number_or_options_without_passage_cannot_match(self):
        q = self.question(); q['_passage_text'] = ''
        self.assertNotEqual(match_examples([self.example()], [q])[0]['status'], 'exact_unique_match')

    def test_ambiguous_matches_and_unverified_text_rejected(self):
        q = self.question(); other = copy.deepcopy(q); other['question_id'] = 'old.2'
        self.assertEqual(match_examples([self.example()], [q, other])[0]['status'], 'ambiguous_exact_matches')
        ex = self.example(); ex['text_quality'] = 'coordinate_reconstructed_pending_visual_check'
        self.assertEqual(match_examples([ex], [q])[0]['status'], 'source_text_not_verified')

    def test_patch_rechecks_changed_content_and_existing_answer(self):
        ex, q = self.example(), self.question(); matches = match_examples([ex], [q])
        q['content']['stem'] += ' Changed.'
        self.assertEqual(recovery_patches(matches, [ex], [q]), [])
        q = self.question(); q['content']['answer'] = 'A'
        self.assertEqual(recovery_patches(matches, [ex], [q]), [])

    def test_saved_unique_match_rejects_new_ambiguity(self):
        ex, q = self.example(), self.question(); matches = match_examples([ex], [q])
        other = copy.deepcopy(q); other['question_id'] = 'old.new'
        self.assertEqual(recovery_patches(matches, [ex], [q, other]), [])

    def test_conflicting_source_examples_cannot_generate_patch(self):
        ex, q = self.example(), self.question()
        other = copy.deepcopy(ex); other['example_id'] = 'source.conflict'; other['answer'] = 'A'
        matches = match_examples([ex, other], [q])
        self.assertTrue(all(m['status'] == 'ambiguous_source_examples' for m in matches))
        self.assertEqual(recovery_patches(matches, [ex, other], [q]), [])

    def test_read_jsonl_preserves_embedded_unicode_paragraph_separator(self):
        import tempfile, json
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'records.jsonl'
            path.write_text(json.dumps({'text': 'first\u2028second'}, ensure_ascii=False) + '\n', encoding='utf-8')
            self.assertEqual(list(read_jsonl(path)), [{'text': 'first\u2028second'}])


class ActualOfficialSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = extract_official(ROOT, render=False)

    def test_full_written_papers_and_answer_keys(self):
        for exam in ['CET-4', 'CET-6']:
            rows = [x for x in self.bundle['examples'] if x['exam'] == exam and x['collection'] == 'written_sample']
            self.assertEqual(len(rows), 57)
            objective = [x for x in rows if x['answer_kind'] == 'official_objective_key']
            self.assertEqual({x['number'] for x in objective}, set(range(1, 56)))
            self.assertTrue(all(x['answer'] for x in objective))

    def test_listening_stems_scripts_all_options_and_missing_audio(self):
        rows = [x for x in self.bundle['examples'] if x['question_type'] == 'listening']
        self.assertEqual(len(rows), 50)
        for x in rows:
            self.assertEqual(set(x['options']), set('ABCD'))
            self.assertTrue(x['stem'])
            self.assertTrue(x['passage'])
            self.assertEqual(x['audio']['status'], 'not_provided_in_source')
        q = next(x for x in rows if x['exam'] == 'CET-4' and x['number'] == 2)
        self.assertEqual(q['options']['C'], 'During a security check.')

    def test_cross_page_questions_and_full_reading_context(self):
        q = next(x for x in self.bundle['examples'] if x['exam'] == 'CET-4' and x.get('number') == 23)
        self.assertIn('7.5 million dollars', q['options']['C'])
        for x in self.bundle['examples']:
            if x['question_type'].startswith('reading'):
                self.assertTrue(x['passage'])
                self.assertTrue(x['options'])
        for exam, labels in [('CET-4', 'ABCDEFGHIJK'), ('CET-6', 'ABCDEFGHIJKLMNO')]:
            matching = [x for x in self.bundle['examples'] if x['exam'] == exam and x['question_type'] == 'reading_matching']
            self.assertEqual(len(matching), 10)
            self.assertTrue(all(set(x['options']) == set(labels) for x in matching))

    def test_writing_picture_and_scored_samples_not_model_answer(self):
        rows = [x for x in self.bundle['examples'] if x['collection'] == 'scoring_sample']
        self.assertEqual(len(rows), 4)
        for x in rows:
            self.assertEqual([s['score'] for s in x['scored_responses']], [14, 11, 8, 5, 2])
            self.assertTrue(all(s['response'] for s in x['scored_responses']))
        writing = next(x for x in rows if x['exam'] == 'CET-4' and x['question_type'] == 'writing')
        self.assertIsNone(writing['answer'])
        self.assertTrue(writing['visual_context'])

    def test_spelling_and_glyphs_restored_without_correcting_source_errors(self):
        q = next(x for x in self.bundle['examples'] if x['exam'] == 'CET-4' and x.get('number') == 1)
        self.assertIn('Christmas-time attacks', q['options']['A'])
        self.assertNotIn('ChristmasGtime', q['options']['A'])
        self.assertNotIn('So mali', q['options']['D'])
        self.assertTrue(self.bundle['oral_samples'])

    def test_standard_question_schema_and_all_passage_references(self):
        questions, passages = standardize(ROOT, self.bundle)
        self.assertEqual(len(questions), 114)
        self.assertEqual(len(passages), 23)
        pids = {p['resource_id'] for p in passages}
        for q in questions:
            self.assertIsNone(q['difficulty'])
            self.assertEqual(q['review']['status'], 'pending_expert_review')
            self.assertTrue(q['knowledge_node_ids'])
            self.assertTrue(q['ability_ids'])
            self.assertTrue(q['exam_requirement_ids'])
            self.assertTrue(all(len(k.split('.')) >= 3 for k in q['knowledge_node_ids']))
            self.assertTrue(all(f['sha256'] and f['locator']['pdf_pages'] for f in q['source']['files']))
            if q['extra']['passage_id']:
                self.assertIn(q['extra']['passage_id'], pids)
        for o in self.bundle['oral_samples']:
            self.assertEqual(o['knowledge_node_ids'], [])
            self.assertEqual(o['ability_ids'], [])
            self.assertIn('pending', o['ontology_alignment_status'])

    def test_complete_archive_boundaries_and_genuine_missing_fields(self):
        self.assertEqual(set(self.bundle['pages']), set(range(150, 212)))
        self.assertEqual(len(self.bundle['source_sections']), 14)
        sections = {r['section_id']: r for r in self.bundle['source_sections']}
        self.assertNotIn('【参考答案】', sections['cet6_listening_script']['raw_source_text'])
        self.assertTrue(sections['cet6_answer_key']['raw_source_text'].startswith('【参考答案】'))
        for row in self.bundle['examples']:
            self.assertIsNone(row['official_analysis'])
        writing = [x for x in self.bundle['examples'] if x['collection'] == 'written_sample' and x['question_type'] == 'writing']
        self.assertEqual(len(writing), 2)
        self.assertTrue(all(x['answer'] is None for x in writing))


if __name__ == '__main__':
    unittest.main()
