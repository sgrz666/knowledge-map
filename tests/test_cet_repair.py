import importlib.util
import json
import tempfile
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / '数据集' / '四六级' / 'scripts'
sys.path.insert(0, str(SCRIPTS))

def module(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    before = sys.argv
    if name in ('fill_answers','build_questions','build_writing_translation'):
        base = ROOT / '数据集/四六级'
        sys.argv = ['test', '--src', str(ROOT), '--stage', str(base/'scripts/_staging/answers'), '--kb', str(base)]
        if name=='build_writing_translation': sys.argv=['test','--src',str(ROOT),'--kb',str(base)]
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = before
    return mod

class MigrationTests(unittest.TestCase):
    def test_listening_section_labels_and_options_are_not_spoken_question_prompts(self):
        m=module('repair_kb')
        for noise in ('Section B','Questions 16 to 18 are on the passage you have just heard','17.','2022','.','A ) It was carefully tested with consumers.'):
            row={'module':'听力理解','content':{'stem':noise},'extra':{}}
            m.clean_listening_prompt(row)
            self.assertIsNone(row['content']['stem'])
            self.assertEqual(row['extra']['prompt_parse_history'][0]['value'],noise)
        actual={'module':'听力理解','content':{'stem':'What did the man do yesterday?'},'extra':{}}
        m.clean_listening_prompt(actual);self.assertEqual(actual['content']['stem'],'What did the man do yesterday?')

    def test_unreviewed_prerequisites_are_excluded_from_paths_without_erasing_approved_edges(self):
        m=module('repair_kb')
        nodes=[{'id':'target','prereq':['source'],'prerequisite_review':{'status':'proposed_pending_subject_expert'}},{'id':'approved','prereq':['source'],'prerequisite_review':{'status':'approved','reviewer':'expert'}}]
        edges=[{'src':'source','dst':'target','rel':'prereq_of','review_status':'proposed_pending_subject_expert'},{'src':'source','dst':'approved','rel':'prereq_of','review_status':'approved'}]
        m.deactivate_unreviewed_prerequisites(nodes,edges)
        self.assertEqual(nodes[0]['prereq'],[]);self.assertEqual(nodes[0]['candidate_prereq'],['source'])
        self.assertEqual(edges[0]['rel'],'prerequisite_candidate');self.assertFalse(edges[0]['active'])
        self.assertEqual(nodes[1]['prereq'],['source']);self.assertEqual(edges[1]['rel'],'prereq_of')

    def test_cet6_listening_content_table_uses_its_own_row_numbers(self):
        m=module('repair_kb')
        self.assertEqual(m.type_requirement('CET-6','长对话'),'cet.content.cet6.r016')
        self.assertEqual(m.type_requirement('CET-6','听力篇章'),'cet.content.cet6.r017')
        self.assertEqual(m.type_requirement('CET-4','长对话'),'cet.content.cet4.r017')

    def test_question_requirement_projection_rejects_other_skill_modules(self):
        m=module('repair_kb')
        requirements={'read':{'module':'阅读','level':['CET-4']},'translate':{'module':'翻译','level':['CET-4']},'listen':{'module':'听力','level':['CET-4']},'six':{'module':'阅读','level':['CET-6']}}
        self.assertEqual(m.question_requirement_ids({'module':'阅读理解','exam':'CET-4'},list(requirements),requirements),['read'])

    def test_relative_dotted_nodes_get_exam_prefix(self):
        m = module('migrate_v2_schema')
        self.assertEqual(m.qnodes({'question_type': '选词填空', 'module': '阅读'}, 'cet4'),
                         ['cet4.read.cloze', 'cet4.read.discourse', 'cet4.lang.vocab'])

    def test_already_migrated_wrong_fallback_is_repaired_without_field_loss(self):
        m = module('migrate_v2_schema')
        old_kb = m.KB
        with tempfile.TemporaryDirectory() as d:
            m.KB = Path(d)
            (m.KB / 'questions/cet4').mkdir(parents=True)
            (m.KB / 'questions/cet6').mkdir(parents=True)
            f = m.KB / 'questions/cet4/2015-06_p1.jsonl'
            r = {'question_id': 'cet4-2015-06-p1-reading-26', 'exam': 'CET-4',
                 'module': '阅读理解', 'question_type': '选词填空',
                 'knowledge_node_ids': ['cet4.read', 'cet4.listen'], 'ability_ids': [],
                 'content': {'answer': 'B'}, 'extra': {'custom': 'preserve', '_old_id': 'cet4.r.2015-06_p1.q26'},
                 'human_note': 'preserve\x85review\u2028note\u2029end'}
            f.write_text(json.dumps(r,ensure_ascii=False), encoding='utf-8')
            try:
                m.migrate_questions()
                fixed = json.loads(f.read_text(encoding='utf-8'))
                self.assertIn('cet4.read.cloze', fixed['knowledge_node_ids'])
                self.assertNotIn('cet4.listen', fixed['knowledge_node_ids'])
                self.assertTrue(fixed['ability_ids'])
                self.assertEqual(fixed['human_note'], r['human_note'])
                self.assertEqual(fixed['extra']['custom'], 'preserve')
                first = f.read_bytes()
                m.migrate_questions()
                self.assertEqual(first, f.read_bytes())
            finally:
                m.KB = old_kb

class AnswerTests(unittest.TestCase):
    def test_original_word_textbox_table_word_bank_is_not_lost(self):
        reader=module('fill_answers');m=module('recover_reading_resources')
        path=ROOT/'数据集/四六级/scripts/_staging/cet4/2015年12月四级真题第1套.docx'
        text,locators=reader.read_source(path)
        span=m.section(text,'cloze');bank=m.explicit_bank(span[2])
        self.assertIsNotNone(bank)
        self.assertEqual(bank['G'],'favorite');self.assertEqual(bank['O'],'theories')
        self.assertTrue(any(loc.get('text_box') for a,b,loc in locators))

    def test_original_reading_prompts_support_full_width_indent_and_sentence_completion(self):
        m=module('restore_original_stems')
        q={'question_type':'仔细阅读'}
        self.assertEqual(m.original_stem(q,'Utility companies have begun to realize that battery technologies ___________.\nA. benefit their business\nB. transmit power faster'), 'Utility companies have begun to realize that battery technologies ___________.')
        reader=module('fill_answers')
        self.assertEqual([n for n,b,a,e in reader.question_blocks('\u300036. Elderly students find it hard to keep up with rapid changes.\n\u300037. Some believe take-home exams affect performance.')],[36,37])
        self.assertIsNone(m.original_stem({'question_type':'长篇阅读'},'D\t37. L\t38. E\t39. N\t40. F\t41. Q\t42. H\t43. C\t44. K\t45. M'))
        blocks=list(reader.question_blocks('40. Participation of ninth graders motivates them to study design.\n41. Design Ventura is welcomed by teachers.\n43. Participants create sustainable products.\nSection C\n'))
        self.assertTrue(blocks[0][1].startswith('Participation'))
        self.assertTrue(blocks[2][1].startswith('Participants'))

    def test_unbound_generated_explanation_is_quarantined_not_left_active(self):
        m=module('fill_answers')
        row={'question_id':'q','question_type':'仔细阅读','content':{'stem':'What does the author say about high-potential women?','options':dict.fromkeys('ABCD','option'),'answer':None},'extra':{'number':52},'analysis':{'raw':'旧题号错误关联的原文解析应完整保存在历史。','status':'source_support_withdrawn_pending_review','method':'published_explanation_text_extraction'}}
        m.fill_records([row],('CET-4','2015-06',1),{})
        self.assertIsNone(row['analysis']['raw'])
        self.assertEqual(row['extra']['analysis_history'][0]['analysis']['raw'],'旧题号错误关联的原文解析应完整保存在历史。')

    def test_reading_resource_recovery_requires_complete_explicit_labels(self):
        m=module('recover_reading_resources')
        bank='\n'.join(letter+') word'+('-form' if letter=='O' else '') for letter in 'ABCDEFGHIJKLMNO')
        self.assertEqual(set(m.explicit_bank(bank)),set('ABCDEFGHIJKLMNO'))
        self.assertIsNone(m.explicit_bank(bank.replace('O) word-form','')))
        alternate=bank.replace('A) word','A. arena').replace('K) word','k) restrictive').replace('D) word','D enabling')
        self.assertEqual(m.explicit_bank(alternate)['D'],'enabling')
        text='\n'.join('['+letter+'] '+'This is an explicitly labelled paragraph containing actual source words. '*4 for letter in 'ABC')+'\n36. This is the separate matching statement.\n'
        paras=m.explicit_paragraphs(text)
        self.assertEqual([p['letter'] for p in paras],list('ABC'))
        self.assertNotIn('matching statement',paras[-1]['text'])

    def test_same_question_number_cannot_bind_unrelated_published_explanation(self):
        m=module('fill_answers')
        q={'content':{'stem':'What does the author say about high-potential women in the not-too-distant future?','options':{'A':'They benefit from fathers staying at home.','B':'They find family-friendly jobs.','C':'They maintain career trajectories.','D':'They choose between career and children.'}}}
        self.assertFalse(m.source_identity_matches(q,{'stem':'C','block':'C\n定位：根据 more fulltime fathers 和 misguided，数量太少了。'}))
        self.assertTrue(m.source_identity_matches(q,{'stem':'D','block':'D\n定位：根据 high-potential women 和 not-too-distant future 对应末段。'}))

    def test_original_word_auto_numbering_recovers_correct_reading_question_identity(self):
        m=module('docx_source')
        path=ROOT/'数据集/四六级/scripts/_staging/cet4/2015年06月四级真题第1套.docx'
        text='\n'.join(t for t,loc in m.read_docx_units(path))
        self.assertIn('51. What gives women a ray of hope',text)
        self.assertIn('55. What does the author say about high-potential women',text)
        self.assertIn('D) They will still face the difficult choice between career and children.',text)

    def test_plain_word_without_numbering_part_remains_readable(self):
        m=module('docx_source')
        path=ROOT/'数据集/四六级/scripts/_staging/cet4/2018年12月四级真题第1套.docx'
        self.assertTrue(m.read_docx_units(path))

    def test_source_listening_groups_support_script_before_and_after_range_header(self):
        m=module('recover_listening')
        for filename in ('2015.06英语四级解析第1套.pdf','2019.06英语四级解析第1套.pdf'):
            path=next((ROOT/'数据集/四六级/scripts/_staging/answers').rglob(filename))
            groups=m.extract_groups(m.read_listening_source(path)[0])
            self.assertTrue(any(g['numbers']==[1,2] and len(g['questions'])==2 for g in groups),filename)

    def test_interleaved_pdf_question_numbers_are_not_one_spoken_prompt(self):
        m=module('recover_listening')
        text='Listening Comprehension\nNews Report One\nQuestions 1 and 2 are based on the report.\n'+'The boy was encouraged by his father to collect a large number of cans. '*8+'\n1. What did the boy\n2. What did the father\ndo according to the report?\n'
        groups=m.extract_groups(text)
        self.assertFalse(any(q['number']==1 and '2.' in q['text'] for g in groups for q in g['questions']))

    def test_word_numbering_restarts_options_but_honors_explicit_never_restart(self):
        from docx import Document
        from docx.oxml import parse_xml
        from docx.oxml.ns import nsdecls
        from docx_source import read_docx_units
        with tempfile.TemporaryDirectory() as d:
            doc=Document();numbering=doc.part.numbering_part.element
            numbering.append(parse_xml('<w:abstractNum '+nsdecls('w')+' w:abstractNumId="97"><w:lvl w:ilvl="0"><w:start w:val="51"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl><w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="upperLetter"/><w:lvlText w:val="%2)"/></w:lvl><w:lvl w:ilvl="2"><w:start w:val="1"/><w:numFmt w:val="lowerLetter"/><w:lvlRestart w:val="0"/><w:lvlText w:val="%3)"/></w:lvl></w:abstractNum>'))
            numbering.append(parse_xml('<w:num '+nsdecls('w')+' w:numId="97"><w:abstractNumId w:val="97"/></w:num>'))
            for level,value in [(0,'question one'),(1,'first'),(1,'second'),(2,'sub one'),(0,'question two'),(1,'first again'),(2,'sub two')]:
                p=doc.add_paragraph(value);p._p.get_or_add_pPr().append(parse_xml('<w:numPr '+nsdecls('w')+'><w:ilvl w:val="'+str(level)+'"/><w:numId w:val="97"/></w:numPr>'))
            path=Path(d)/'numbered.docx';doc.save(path)
            self.assertEqual([t for t,l in read_docx_units(path)],['51. question one','A) first','B) second','a) sub one','52. question two','A) first again','b) sub two'])

    def test_answer_volumes_use_explicit_chinese_volume_labels(self):
        m=module('fill_answers')
        self.assertEqual(m.file_meta(Path('2018年6月英语四级真题答案解析（卷一）.pdf')),('CET-4','2018-06',1))
        self.assertEqual(m.file_meta(Path('2019年12月英语六级真题答案解析（卷二）.pdf')),('CET-6','2019-12',2))

    def test_explicit_independent_source_binding_moves_misprinted_task_candidate(self):
        m=module('build_writing_translation')
        from collections import defaultdict
        data=defaultdict(lambda:defaultdict(list));ref={'path':'volume.pdf','locator':{'text_offset':[20,80],'header':'misprinted second paper'}}
        data[('cet4','2022-12',2)]['model_essay']=[{'value':'The Necessity of Developing Social Skills. Source essay.','source':ref}]
        binding={'from_task':['cet4','2022-12',2],'to_task':['cet4','2022-12',3],'field':'model_essay','source':ref,'text_anchor':'The Necessity of Developing Social Skills','binding_evidence':{'exam_answer_path':'third-paper.pdf','pages':[1],'review_status':'agent_visual_check_pending_subject_expert'}}
        m.apply_task_bindings(data,[binding])
        self.assertFalse(data[('cet4','2022-12',2)]['model_essay'])
        self.assertEqual(len(data[('cet4','2022-12',3)]['model_essay']),1)
        self.assertEqual(data[('cet4','2022-12',3)]['model_essay'][0]['source']['binding_evidence'],binding['binding_evidence'])

    def test_translation_volume_footer_is_not_part_of_complete_prompt(self):
        m=module('build_writing_translation')
        parts=m.split_by_header('2024年6月大学英语四级翻译真题第1套\n四合院是中国传统建筑。\n英语四级翻译真题专项\n2024年6月大学英语四级翻译真题第2套\n农历起源于中国。')
        self.assertEqual(parts[('cet4','2024-06',1)],'四合院是中国传统建筑。')

    def test_legacy_conflict_cannot_remain_active_when_current_source_is_missing(self):
        m=module('fill_answers');meta=('CET-4','2015-12',2)
        row={'question_id':'q','question_type':'长篇阅读','content':{'answer':'J','options':dict.fromkeys('ABCDEFGHIJKLMNO','paragraph')},'extra':{'number':45,'answer_status':'source_conflict'}}
        m.fill_records([row],meta,{})
        self.assertIsNone(row['content']['answer'])
        self.assertEqual(row['extra']['answer_history'][0]['answer'],'J')

    def test_reference_headers_without_daxue_are_complete_boundaries(self):
        m=module('build_writing_translation')
        parts=m.split_by_header('2025 年6 月英语四级写作范文第1 套\nFirst complete essay.\n2025 年6 月英语四级写作范文第2 套\nSecond complete essay.')
        self.assertEqual(parts.get(('cet4','2025-06',1)),'First complete essay.')
        self.assertEqual(parts.get(('cet4','2025-06',2)),'Second complete essay.')
        spaced=m.split_by_header('2023年0 6 月大学英语四级写作范文第1 套\nReal source essay.\n2020年0 7 月大学英语四级写作范文全1 套\nAnother source essay.')
        self.assertEqual(spaced.get(('cet4','2023-06',1)),'Real source essay.')
        self.assertEqual(spaced.get(('cet4','2020-07',1)),'Another source essay.')
        split_year=m.split_by_header('202 2年0 9 月大学英语四级写作范文第1 套\nFirst essay.\n202 2年0 9 月大学英语四级写作范文第2 套\nNext essay.')
        self.assertEqual(split_year.get(('cet4','2022-09',1)),'First essay.')

    def test_first_multiple_choice_option_is_not_an_answer_key(self):
        m=module('fill_answers')
        found,_=m.extract_answers('1. A) First option.\nB) Second option.\nC) Third option.\nD) Fourth option.')
        self.assertNotIn(1,found)

    def test_negative_option_comparison_cannot_supply_a_correct_key(self):
        m=module('fill_answers')
        found,conflicts=m.extract_answers('1. What happened?\n【解析】A项与原文不相符，B项是正确答案。')
        self.assertEqual(found.get(1),'B');self.assertFalse(conflicts)

    def test_answer_search_cannot_cross_next_question(self):
        m = module('fill_answers')
        result, conflicts = m.extract_answers('1. What happened?\nNo key for this question.\n2. Where?\n【答案】 B\n【解析】地点是伦敦。')
        self.assertNotIn(1, result)
        self.assertEqual(result[2], 'B')

    def test_conflicting_answer_candidates_are_not_chosen_by_vote(self):
        m = module('fill_answers')
        result, conflicts = m.extract_answers('26. A\n【解析】甲\n26. B\n【解析】乙')
        self.assertNotIn(26, result)
        self.assertTrue(conflicts)

    def test_source_explanation_segments_are_preserved_as_structured_analysis(self):
        m=module('fill_answers')
        row={'question_id':'cet4-2024-06-p1-listening-1','question_type':'短篇新闻','content':{'stem':'Where did the incident happen?','options':{'A':'a','B':'b','C':'c','D':'d'},'answer':None},'extra':{'number':1},'analysis':{'raw':None}}
        block='Where did the incident happen?\nB\n【做题提示】题目关注新闻中提到的地点信息。\n【解析】新闻开头提到地点是伦敦，因此B项正确。A项把人物姓名当成地点，故排除A。'
        meta=('CET-4','2024-06',1)
        m.fill_records([row],meta,{(meta,1):[{'answer':'B','raw':m.explanation(block),'block':block,'stem':'B','source':{'path':'key.pdf','role':'answer_analysis','locator':{'page':1}}}]})
        self.assertEqual(row['analysis'].get('key_info'),'题目关注新闻中提到的地点信息。')
        self.assertIn('排除A',row['analysis'].get('option_compare') or '')

    def test_existing_answer_is_quarantined_when_sources_conflict(self):
        m=module('fill_answers');meta=('CET-4','2024-06',1)
        row={'question_id':'q','question_type':'短篇新闻','content':{'stem':'Where did the incident happen?','answer':'A','options':dict.fromkeys('ABCD','option')},'extra':{'number':1}}
        items=[{'answer':key,'raw':None,'block':'Where did the incident happen?\n'+key,'stem':key,'source':{'path':key+'.pdf'}} for key in ['B','C']]
        m.fill_records([row],meta,{(meta,1):items})
        self.assertIsNone(row['content']['answer'])
        self.assertEqual(row['extra']['answer_history'][0]['answer'],'A')

    def test_zero_glyph_in_word_bank_is_recovered_from_context(self):
        m=module('build_questions')
        bank=m.extract_bank([],['A) adult       I) emotional\nB) associated   J) implies\nC)chew        K) mammal\nD) contains     L)replace\nE) continue     M) swallow\nF) defense     N) triggered\nG) dental      0) underneath\nH) downward'])
        self.assertEqual(bank.get('O'),'underneath')

    def test_two_column_tail_pairs_attach_to_each_explicit_question(self):
        m=module('build_questions')
        lines=['5. A) brand-new','B) plenty of rooms','6. A) Space. B) Tranquillity.',
               '7. A) Talk to his wife.','B) Pay the rent.',
               '8. A) View of pond. B) Near work.',
               'C) belongs to mother. D) vacant for months.',
               'C) Appliances. D) Location.',
               'C) Check references. D) Consult solicitor.',
               'C) New friends. D) Shoe space.']
        parsed={n:opts for n,stem,opts in m.parse_question_blocks(lines,range(5,9))}
        self.assertEqual(parsed[7].get('D'),'Consult solicitor.')
        self.assertEqual(parsed[8].get('C'),'New friends.')

class IncrementalTests(unittest.TestCase):
    def test_candidate_generator_does_not_deactivate_an_approved_edge(self):
        from cet_common import merge_jsonl,load_jsonl
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'e.jsonl';f.write_text(json.dumps({'src':'a','dst':'b','rel':'prereq_of','review_status':'approved','reviewer':'expert'}),encoding='utf-8')
            merge_jsonl(f,[{'src':'a','dst':'b','rel':'prerequisite_candidate','proposed_rel':'prereq_of','active':False,'review_status':'proposed_pending_subject_expert'}])
            row=load_jsonl(f)[0];self.assertEqual(row['rel'],'prereq_of');self.assertNotEqual(row.get('active'),False)

    def test_recovered_resource_text_can_fill_quarantined_empty_text(self):
        from cet_common import merge_jsonl,load_jsonl
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'r.jsonl';f.write_text(json.dumps({'resource_id':'cet4-2022-12-p3-writing-1','text':None,'extra':{'_legacy_text':'old incorrect mixed text'}}),encoding='utf-8')
            merge_jsonl(f,[{'id':'cet4.w.2022-12_p3','text':'Source-bounded restored essay.'}])
            self.assertEqual(load_jsonl(f)[0]['text'],'Source-bounded restored essay.')
            self.assertEqual(load_jsonl(f)[0]['extra']['_legacy_text'],'old incorrect mixed text')

    def test_listening_group_cannot_refill_reading_passage_reference(self):
        from cet_common import merge_jsonl,load_jsonl
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'q.jsonl'
            f.write_text(json.dumps({'question_id':'cet4-2015-06-p1-listening-1','module':'听力理解','content':{},'extra':{'passage_id':None}}),encoding='utf-8')
            merge_jsonl(f,[{'id':'cet4.l.2015-06_p1.q1','module':'听力','passage_id':'cet4.l.2015-06_p1.g1'}])
            row=load_jsonl(f)[0];self.assertIsNone(row['extra']['passage_id'])
            self.assertEqual(row['extra']['_legacy_listening_group_reference'],'cet4.l.2015-06_p1.g1')

    def test_proven_two_column_options_replace_bad_parse_and_preserve_history(self):
        from cet_common import merge_jsonl,load_jsonl
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'q.jsonl'
            old={'question_id':'cet6-2022-09-p1-listening-7','content':{'options':{'A':'a','B':'b'},'answer':None},'extra':{'reviewer':'专家甲'}}
            f.write_text(json.dumps(old),encoding='utf-8')
            fresh={'id':'cet6.l.2022-09_p1.q7','options':dict.fromkeys('ABCD','correct option'),'option_parse_method':'explicit_two_column_C_D_sequence'}
            merge_jsonl(f,[fresh]);row=load_jsonl(f)[0]
            self.assertEqual(set(row['content']['options']),set('ABCD'))
            self.assertEqual(row['extra']['option_history'][0]['options'],old['content']['options'])
            self.assertEqual(row['extra']['reviewer'],'专家甲')
            first=f.read_bytes();merge_jsonl(f,[fresh]);self.assertEqual(first,f.read_bytes())

    def test_legacy_rebuild_retains_v2_answers_review_and_extensions(self):
        sys.path.insert(0, str(SCRIPTS))
        from cet_common import merge_jsonl
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'q.jsonl'
            old={'question_id':'cet4-2021-06-p2-listening-1','content':{'answer':'B'},'extra':{'reviewer':'专家甲'},'custom_note':'saved'}
            f.write_text(json.dumps(old),encoding='utf-8')
            merge_jsonl(f,[{'id':'cet4.l.2021-06_p2.q1','stem':'new stem','answer':None}])
            r=json.loads(f.read_text('utf-8'))
            self.assertEqual(r['content']['answer'],'B')
            self.assertEqual(r['extra']['reviewer'],'专家甲')
            self.assertEqual(r['custom_note'],'saved')

    def test_printed_listening_rebuild_preserves_source_bound_spoken_prompt(self):
        from cet_common import merge_jsonl,load_jsonl
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'q.jsonl';opts=dict(zip('ABCD',['First complete choice.','Second complete choice.','Third complete choice.','Fourth complete choice.']))
            row={'question_id':'cet4-2021-06-p1-listening-1','content':{'stem':'What did the boy do?','options':opts,'answer':None},'extra':{'spoken_question_source':{'text':'What did the boy do?'},'option_parse_method':'exact_original_word_question_number_and_four_options'},'source':{}}
            f.write_text(json.dumps(row),encoding='utf8')
            merge_jsonl(f,[{'id':'cet4.l.2021-06_p1.q1','module':'听力','stem':'','options':opts,'source':{},'option_parse_method':'exact_original_word_question_number_and_four_options'}])
            result=load_jsonl(f)[0]
            self.assertEqual(result['content']['stem'],row['content']['stem'])
            self.assertFalse(result['extra'].get('question_parse_history'))

    def test_jsonl_unicode_separators_remain_in_one_record(self):
        from cet_common import merge_jsonl,load_jsonl
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'q.jsonl'
            merge_jsonl(f,[{'id':'x','text':'one\x85two\u2028three\u2029four'}])
            self.assertEqual(len(f.read_text('utf-8').splitlines()),1)
            self.assertEqual(load_jsonl(f)[0]['text'],'one\x85two\u2028three\u2029four')

class ArtifactTests(unittest.TestCase):
    def test_subjective_content_matches_all_restored_task_fields(self):
        from cet_common import load_jsonl
        kb=ROOT/'数据集/四六级'
        for path,prompt,reference in [('writing/model_essays.jsonl','topic_prompt','model_essay'),('translation/items.jsonl','source_text','reference')]:
            for row in load_jsonl(kb/path):
                self.assertTrue(row['content'].get('prompt'),row['resource_id'])
                self.assertTrue(row['content'].get('reference_answer'),row['resource_id'])
                self.assertEqual(row['content']['prompt'],row['extra'][prompt],row['resource_id'])
                self.assertEqual(row['content']['reference_answer'],row['extra'][reference],row['resource_id'])

    def test_conflicting_answers_cannot_be_active_and_rights_are_not_inferred(self):
        from cet_common import load_jsonl
        kb=ROOT/'数据集/四六级'
        for path in (kb/'questions').rglob('*.jsonl'):
            for row in load_jsonl(path):
                provenance=row['extra'].get('answer_provenance')
                if provenance=='source_conflict':self.assertFalse(row['content'].get('answer'),row['question_id'])
                self.assertIn(row['content'].get('answer_status'),('verified','letter_only','source_conflict','missing','reference_only'),row['question_id'])
                if row['content']['answer_status']=='verified' or row['review']['status'] in ('checked','expert_reviewed'):
                    self.assertTrue(row['review'].get('checked_by') or row['review'].get('reviewed_by'),row['question_id'])
                rights=row['source']['copyright']
                self.assertEqual(rights['authorization_status'],'unknown')
                self.assertEqual(rights['use_scope'],'research_non_commercial');self.assertIsNone(rights['expires_at'])

    def test_current_prerequisite_proposals_are_inactive_and_not_in_node_paths(self):
        from cet_common import load_jsonl
        kb=ROOT/'数据集/四六级'
        for edge in load_jsonl(kb/'ontology/edges.jsonl'):
            claimed=edge.get('review_status') or edge.get('status')
            if claimed in ('approved','verified','expert_reviewed'):
                self.assertTrue(edge.get('reviewed_by') or edge.get('reviewer') or edge.get('evidence'),edge)
            if edge.get('review_status')=='proposed_pending_subject_expert':
                self.assertFalse(edge.get('active'),edge)
                if edge.get('claimed_rel'):self.assertEqual(edge['rel'],'prerequisite_candidate',edge)
        for node in load_jsonl(kb/'ontology/knowledge_nodes.jsonl'):
            review=node.get('prerequisite_review') or {}
            if review.get('status')=='approved':self.assertTrue(review.get('reviewed_by'),node['id'])
            if review.get('status')!='approved':self.assertFalse(node.get('prereq'))

    def test_reading_passages_use_specific_knowledge_nodes(self):
        from cet_common import load_jsonl
        for r in load_jsonl(ROOT/'数据集/四六级/passages/reading.jsonl'):
            self.assertFalse(any(k.endswith('.read') for k in r['knowledge_node_ids']),r['resource_id'])

    def test_resource_ids_are_unique(self):
        kb = ROOT / '数据集/四六级'
        for name in ('writing/model_essays.jsonl','translation/items.jsonl','vocabulary/phrases_highfreq.jsonl'):
            rows = [json.loads(l) for l in (kb/name).read_text('utf-8').splitlines() if l.strip()]
            ids = [r['resource_id'] for r in rows]
            self.assertEqual(len(ids),len(set(ids)), name)

    def test_sources_have_resolvable_structured_paths(self):
        kb = ROOT / '数据集/四六级'
        for name in ('writing/model_essays.jsonl','translation/items.jsonl','vocabulary/words_cet4.jsonl','writing/templates.jsonl'):
            for r in [json.loads(l) for l in (kb/name).read_text('utf-8').splitlines() if l.strip()]:
                files = r.get('source',{}).get('files',[])
                self.assertTrue(files, r['resource_id'])
                for f in files:
                    self.assertNotIn('...', f['path'])
                    self.assertTrue((ROOT/f['path']).is_file(), f['path'])

    def test_translation_tasks_have_official_requirements_and_computable_rubrics(self):
        kb=ROOT/'数据集/四六级'
        for r in [json.loads(l) for l in (kb/'translation/items.jsonl').read_text('utf-8').splitlines() if l.strip()]:
            self.assertEqual(r.get('task_type'),'paragraph_translation')
            self.assertTrue(r.get('exam_requirement_ids'))
            self.assertTrue(r.get('rubric_id'))
            self.assertEqual(r['extra']['content_review']['expert_review']['status'],'pending')
        rubrics=[json.loads(l) for l in (kb/'ontology/scoring_rubrics.jsonl').read_text('utf-8').splitlines() if l.strip()]
        self.assertEqual(len(rubrics),2)
        for r in rubrics:
            self.assertEqual([(b['raw_score_min'],b['raw_score_max']) for b in r['bands']],[(13,15),(10,12),(7,9),(4,6),(1,3)])

    def test_all_questions_have_specific_semantically_compatible_tags(self):
        kb=ROOT/'数据集/四六级'
        nodes={r['id']:r for r in [json.loads(l) for l in (kb/'ontology/knowledge_nodes.jsonl').read_text('utf-8').splitlines()]}
        requirements={r['requirement_id']:r for r in [json.loads(l) for l in (ROOT/'权威资料/requirements.jsonl').read_text('utf-8').splitlines()]}
        repair=module('repair_kb')
        for f in (kb/'questions').rglob('*.jsonl'):
            for r in [json.loads(l) for l in f.read_text('utf-8').splitlines() if l.strip()]:
                self.assertTrue(r.get('ability_ids'), r['question_id'])
                self.assertTrue(r.get('exam_requirement_ids'),r['question_id'])
                for k in r['knowledge_node_ids']:
                    self.assertIn(nodes[k]['module'],[r['module'],'词汇语法'])
                    self.assertGreaterEqual(k.count('.'),2)
                for i in r['exam_requirement_ids']:
                    self.assertIn(r['exam'],requirements[i]['level'])
                self.assertEqual(r['exam_requirement_ids'],repair.question_requirement_ids(r,r['exam_requirement_ids'],requirements))

if __name__ == '__main__':
    unittest.main()
