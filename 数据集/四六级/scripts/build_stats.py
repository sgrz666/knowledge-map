"""Recompute statistics from v2 fields, retaining every record and every gap."""
import argparse, json, sys
from collections import Counter
from datetime import date
from pathlib import Path
from cet_common import load_jsonl, jsonl_dumps

sys.stdout.reconfigure(encoding='utf-8')

def main(argv=None):
    ap=argparse.ArgumentParser();ap.add_argument('--kb',required=True);args=ap.parse_args(argv)
    kb=Path(args.kb).resolve()
    passages=load_jsonl(kb/'passages/reading.jsonl');pmap={r['resource_id']:r for r in passages}
    allq,detail,paper_counts=[],{},{}
    for lv in ('cet4','cet6'):
        rows=[]
        for f in sorted((kb/'questions'/lv).glob('*.jsonl')):
            rr=load_jsonl(f);rows+=rr
            paper_counts[f'{lv}-{f.stem.replace("_p","-p")}']=Counter(r['module'] for r in rr)
        detail[lv]={'records':len(rows),'with_answer':sum(bool(r['content'].get('answer')) for r in rows),
                    'with_analysis':sum(bool(r.get('analysis',{}).get('raw')) for r in rows),
                    'duplicate_ids':len(rows)-len({r['question_id'] for r in rows}),
                    'by_type':dict(Counter(r['question_type'] for r in rows)),
                    'by_module':dict(Counter(r['module'] for r in rows))}
        allq+=rows
    quality=Counter()
    for q in allq:
        c=q['content'];ex=q['extra'];opts=c.get('options') or {};a=c.get('answer');qt=q['question_type']
        passage=pmap.get(ex.get('passage_id'),{})
        if qt in ('长篇阅读','仔细阅读','选词填空') and not passage and ex.get('active') is not False:
            quality['reading_unlinked_active_passage']+=1
        if passage and q['question_id'] not in passage.get('extra',{}).get('question_ids',[]):
            quality['reading_passage_reference_mismatch']+=1
        if qt=='选词填空':
            opts=opts or passage.get('extra',{}).get('word_bank') or {}
            if not opts: quality['missing_cloze_word_bank']+=1
            if opts and (set(opts)!=set('ABCDEFGHIJKLMNO') or any(not str(v or '').strip() for v in opts.values())): quality['cloze_incomplete_word_bank']+=1
        elif qt=='长篇阅读':
            paragraphs=passage.get('extra',{}).get('paragraphs') or {}
            if not paragraphs: quality['missing_matching_paragraph_labels']+=1
            if isinstance(paragraphs,dict): opts=opts or paragraphs
        elif set(opts)!=set('ABCD') or any(not str(v or '').strip() for v in opts.values()): quality['objective_incomplete_options']+=1
        if qt in ('长篇阅读','仔细阅读') and not c.get('stem'):quality['reading_missing_task_prompt']+=1;quality['missing_'+('matching_statement' if qt=='长篇阅读' else 'careful_reading_question')]+=1
        if a and opts and a not in opts: quality['answer_outside_available_options']+=1
        if not a: quality['missing_answer']+=1
        if not q.get('analysis',{}).get('raw'): quality['missing_analysis']+=1
        if not all(q.get('analysis',{}).get(k) for k in ('key_info','option_compare','trace_back')): quality['missing_full_structured_analysis']+=1
        if q.get('difficulty') is None: quality['difficulty_pending_calibration']+=1
        if not q.get('knowledge_node_ids'): quality['missing_knowledge_nodes']+=1
        if not q.get('ability_ids'): quality['missing_abilities']+=1
        if not q.get('exam_requirement_ids'): quality['missing_exam_requirements']+=1
        if q['module']=='听力理解' and not ex.get('audio',{}).get('files'): quality['missing_exact_paper_audio']+=1
        if ex.get('content_review',{}).get('expert_review',{}).get('status')!='approved': quality['pending_expert_review']+=1
        if ex.get('answer_status')=='source_conflict': quality['answer_source_conflicts']+=1
        if ex.get('answer_history'): quality['records_with_quarantined_answer_history']+=1
        if ex.get('analysis_history'):quality['records_with_quarantined_analysis_history']+=1
        if ex.get('source_discovery',{}).get('status')=='parser_artifact_outside_CET_number_range':quality['inactive_parser_artifacts']+=1
        if q.get('source',{}).get('copyright',{}).get('authorization_status')=='unknown': quality['questions_rights_unknown']+=1
        if not q.get('source',{}).get('copyright',{}).get('use_scope'): quality['questions_missing_confirmed_use_scope']+=1
        if q['module']=='听力理解':
            audio=ex.get('audio',{})
            if audio.get('start_seconds') is None or audio.get('end_seconds') is None: quality['listening_pending_segment_alignment']+=1
            if not c.get('stem'): quality['listening_missing_printed_or_transcribed_question_prompt']+=1
            if ex.get('question_prompt_availability',{}).get('status')=='spoken_prompt_unavailable_missing_audio_and_transcript': quality['listening_prompt_unavailable']+=1
        if ex.get('exam_design_applicability',{}).get('status','').startswith('historical_'): quality['historical_exam_design_pending_authentication']+=1
    papers=load_jsonl(kb/'manifest/papers.jsonl')
    for p in papers:
        cnt=paper_counts.get(p['paper_id'],Counter())
        p['listening_qs']=cnt.get('听力理解',0);p['reading_qs']=cnt.get('阅读理解',0)
    (kb/'manifest/papers.jsonl').write_text('\n'.join(jsonl_dumps(p) for p in papers)+'\n',encoding='utf-8')
    resources={}
    for folder in ('vocabulary','passages','writing','translation','listening'):
        for f in sorted((kb/folder).rglob('*.jsonl')):
            if f.name.startswith('_'): continue
            rr=load_jsonl(f);ids=[r.get('resource_id') for r in rr]
            resources[str(f.relative_to(kb)).replace('\\','/')]={'records':len(rr),'unique_ids':len(set(ids)),
                'with_original_text':sum(bool(r.get('text')) for r in rr),
                'copyright_unknown_records':sum(r.get('source',{}).get('copyright',{}).get('authorization_status')=='unknown' for r in rr),
                'unresolved_source_records':sum(r.get('source',{}).get('local_file_status')!='resolved' for r in rr)}
    writing=load_jsonl(kb/'writing/model_essays.jsonl');trans=load_jsonl(kb/'translation/items.jsonl')
    ans=sum(bool(r['content'].get('answer')) for r in allq);analysis=sum(bool(r.get('analysis',{}).get('raw')) for r in allq)
    baseline=json.loads((kb/'manifest/review_baseline.json').read_text('utf-8'))
    old_answers=baseline['question_answers']
    added=sum(bool(q['content'].get('answer')) and not old_answers.get(q['question_id']) for q in allq)
    withdrawn=sum(bool(old_answers.get(q['question_id'])) and not q['content'].get('answer') for q in allq)
    changed=sum(bool(old_answers.get(q['question_id'])) and bool(q['content'].get('answer')) and old_answers[q['question_id']]!=q['content']['answer'] for q in allq)
    supported=sum(bool(q['content'].get('answer')) and q['extra'].get('answer_status')=='source_extracted_pending_expert_review' for q in allq)
    added_records=[q for q in allq if q['question_id'] not in old_answers]
    discovery=Counter(q['extra'].get('source_discovery',{}).get('status','new_source_boundary_pending_verification') for q in added_records)
    transcripts=load_jsonl(kb/'listening/transcripts.jsonl')
    analysis_history=[entry for q in allq for entry in q['extra'].get('analysis_history',[]) if entry.get('analysis',{}).get('raw')]
    for r in writing+trans:
        if not r.get('content',{}).get('prompt'): quality['subjective_task_missing_prompt']+=1
        if not r.get('content',{}).get('reference_answer'): quality['subjective_task_missing_reference']+=1
    quality['resources_rights_unknown']=sum(v['copyright_unknown_records'] for v in resources.values())
    passage_report_path=kb/'manifest/passage_reference_repair_report.json'
    passage_report=json.loads(passage_report_path.read_text('utf-8')) if passage_report_path.exists() else {}
    stats={'generated':date.today().isoformat(),'source':'英语四六级资料合集（2026年最新）(1)',
      'counting_rules':'One questions JSONL row is one objective question; tasks/resources counted separately, no whitelist exclusion.',
      'questions':{'total':len(allq),'with_answer':ans,'with_analysis':analysis,'answer_fill_rate':round(ans/len(allq),4),
                   'active_source_question_records':sum(q['extra'].get('active') is not False for q in allq),
                   'inactive_parser_artifact_records':quality['inactive_parser_artifacts'],
                   'new_records_pending_expert_confirmation':len(added_records)-quality['inactive_parser_artifacts'],
                   'new_records_confirmed_by_expert':sum(q['extra'].get('source_discovery',{}).get('expert_confirmation_status')=='approved' for q in added_records),
                   'with_quarantined_analysis_history':sum(bool(q['extra'].get('analysis_history')) for q in allq),
                   'quarantined_original_explanation_entries':len(analysis_history),
                   'by_analysis_status':dict(Counter(q.get('analysis',{}).get('status','unknown') for q in allq if q.get('analysis',{}).get('raw'))),
                   'with_explicit_source_supported_answer_pending_review':supported,'legacy_answer_without_current_explicit_key':ans-supported,
                   'with_full_structured_analysis':sum(all(q.get('analysis',{}).get(k) for k in ('key_info','option_compare','trace_back')) for q in allq),
                   'papers_total':len(papers),'papers_full_25L_30R':sum(p['listening_qs']==25 and p['reading_qs']==30 for p in papers),
                   'with_knowledge_nodes':sum(bool(q['knowledge_node_ids']) for q in allq),
                   'with_abilities':sum(bool(q['ability_ids']) for q in allq),
                   'with_exam_requirements':sum(bool(q.get('exam_requirement_ids')) for q in allq),
                   'with_audio':sum(bool(q.get('extra',{}).get('audio',{}).get('files')) for q in allq),'detail':detail},
      'change_from_review_baseline':{'question_count_baseline':5294,'answers_baseline':835,'answers_net_change':ans-835,
                                     'retained_new_records':len(added_records),'new_records_by_discovery_status':dict(discovery),
                                     'previously_blank_answers_filled':added,'baseline_answers_quarantined':withdrawn,'baseline_answers_changed':changed,
                                     'baseline_question_ids_missing':len(set(old_answers)-{q['question_id'] for q in allq}),
                                     'analyses_baseline':0,'analyses_added':analysis},
      'resources':resources,
      'vocabulary':{f.stem:resources['vocabulary/'+f.name]['records'] for f in (kb/'vocabulary').glob('*.jsonl') if not f.name.startswith('_')},
      'passages':{'reading':len(passages),'reference_repair':passage_report.get('summary',{}),
                  'reference_repair_report':'manifest/passage_reference_repair_report.json'},
      'listening':{'transcript_resources':len(transcripts),
                   'current_transcript_resources':sum(r['extra'].get('extraction_status')=='current_source_extraction_pending_expert_review' for r in transcripts),
                   'superseded_transcripts_retained_for_audit':sum(r['extra'].get('extraction_status')=='superseded_text_order_retained_for_audit' for r in transcripts),
                   'with_bound_spoken_question':sum(bool(q.get('extra',{}).get('spoken_question_source')) for q in allq),
                   'with_bound_group_transcript':sum(bool(q.get('extra',{}).get('listening_transcript_ids')) for q in allq),
                   'audit_report':'manifest/source_transcript_audit.jsonl','recovery_report':'manifest/listening_recovery_report.json'},
      'writing':{'model_essays':len(writing),'with_model_essay':sum(bool(r['extra'].get('model_essay')) for r in writing),
                  'with_prompt':sum(bool(r['extra'].get('topic_prompt')) for r in writing),'templates':len(load_jsonl(kb/'writing/templates.jsonl'))},
      'translation':{'items':len(trans),'with_reference':sum(bool(r['extra'].get('reference')) for r in trans),
                     'with_source_text':sum(bool(r['extra'].get('source_text')) for r in trans)},
      'ontology':{'knowledge_nodes':len(load_jsonl(kb/'ontology/knowledge_nodes.jsonl')),'ability_nodes':len(load_jsonl(kb/'ontology/ability_nodes.jsonl')),
                  'active_prerequisite_edges':sum(r.get('rel')=='prereq_of' and r.get('active') is not False for r in load_jsonl(kb/'ontology/edges.jsonl')),
                  'pending_prerequisite_candidates':sum(r.get('rel')=='prerequisite_candidate' for r in load_jsonl(kb/'ontology/edges.jsonl')),
                  'scoring_rubrics':len(load_jsonl(kb/'ontology/scoring_rubrics.jsonl'))},
      'remaining_gaps':dict(quality),
      'quality':{'by_review_status':dict(Counter(r.get('tags',{}).get('审核','unknown') for r in allq)),
                 'resources_unique_ids':sum(r['unique_ids'] for r in resources.values()),
                 'resource_duplicate_ids':sum(r['records']-r['unique_ids'] for r in resources.values())},
      'not_ingested':{'2026_06':'原始试卷/解析册扫描件需OCR；目录年份不代表题库已收录。',
                      'cet4_2024_06_objective':'原题PDF有文本层，但旧生成器遗漏该场次；列排版、题号与选项边界尚未完整校正，未把不完整抽取伪装为完整题组。写译任务已独立抽取并引用原题。',
                      'listening_transcripts':'全源PDF/DOCX审计已执行；已恢复的稿和问题见listening/transcripts及题目绑定，扫描件/损坏字体是extraction_failure，不能视为来源不存在；原MP3题组时间区间待校对。',
                      'difficulty':'未取得作答样本和专家校准，不生成虚假difficulty。',
                      'cse_alignment':'CET与CSE官方等级对接待核验，保留CSE历史/现行原文而不使用考试数字代替等级。'},
      'answer_fill_report':'manifest/answers_fill_report.json','repair_report':'manifest/repair_report.json'}
    previous=kb/'manifest/stats.json'
    previous.write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:stats[k] for k in ('questions','change_from_review_baseline','remaining_gaps','writing','translation')},ensure_ascii=False,indent=2))
    readme=f'''# 四六级知识库

已修复 v2 迁移、重复资源与来源指针，并接入官方 CET 2016 大纲和题型表。全库仍是待教研审核的学习资料，未宣称已完成专家审核、难度校准或 CET/CSE 等级对接。

统计日期：{stats['generated']}；实际口径见 `manifest/stats.json`，所有缺陷记录计入总数。

| 数据 | 当前数量 | 内容覆盖 |
| --- | ---: | --- |
| 客观题 | {len(allq)} | 答案 {ans}，原始逐题解析 {analysis} |
| 阅读语篇 | {len(passages)} | 独立资源 ID |
| 听力文字稿 | {len(transcripts)} | 当前源提取 {stats['listening']['current_transcript_resources']}，唯一绑定题目 {stats['listening']['with_bound_spoken_question']} |
| 写作任务 | {len(writing)} | 范文 {stats['writing']['with_model_essay']}，题目 {stats['writing']['with_prompt']} |
| 翻译任务 | {len(trans)} | 译文 {stats['translation']['with_reference']}，中文原文 {stats['translation']['with_source_text']} |
| 写作模板 | {stats['writing']['templates']} | 功能标签与原始文件引用 |
| 知识点 / 能力 | {stats['ontology']['knowledge_nodes']} / {stats['ontology']['ability_nodes']} | 官方要求 ID、原文定位与初标方法 |
| 主观题量规 | {stats['ontology']['scoring_rubrics']} | 官方整体印象五档评分，原始分 1–15 |

基线 5294 个题目 ID 全部保留（缺失 {stats['change_from_review_baseline']['baseline_question_ids_missing']}）。新增保留记录 {len(added_records)}，其中 {quality['inactive_parser_artifacts']} 条是原解析器的伪题，已停用且不可判分；其余 {stats['questions']['new_records_pending_expert_confirmation']} 条源编号恢复记录仍待专家确认，不能将新增行数称为已核定真题数量。全量 {len(allq)} 条，活动源题记录 {stats['questions']['active_source_question_records']} 条。

较审查基线 835 个答案、0 条解析，原来空白的题目新增答案 {added}，原有答案隔离 {withdrawn}，答案净变化 {ans-835}，活动原始解析新增 {analysis}。现有答案中 {supported} 条有本次明确源答案支持、{ans-supported} 条仍为历史来源待核；全部保留待专家审核状态。此前过宽规则生成的字母与错误题号关联的解析已撤回；旧解析完整保存在 {stats['questions']['with_quarantined_analysis_history']} 条题目的 `extra.analysis_history`，不计为可用解析。重复资源 ID 为 {stats['quality']['resource_duplicate_ids']}；不丢文本，重复内容合并，释义不同的词条保留稳定 variant ID。

题目读取 `question_id/exam/module/question_type/content/analysis/knowledge_node_ids/ability_ids/exam_requirement_ids`。答案在 `content.answer`；原始解析在 `analysis.raw`，提取方法、定位、状态同时保留。未从来源得到的三段解析仍为空，不把知识点标签或占位文案计为解析。

资源读取 `resource_id/text/extra`。范文在 `extra.model_essay`，译文在 `extra.reference`。写译任务另有 `task_id/task_type/content.prompt/content.reference_answer/rubric_id/task_constraints`；量规见 `ontology/scoring_rubrics.jsonl`。评分先选择官方档次，再在该档分值范围内提出练习建议；维度反馈不冒充官方加权分数，正式评分仍需当次样卷与训练过的阅卷员。

语篇引用通过原卷内完整题干、全部选项（匹配题为完整陈述）及明确语篇边界核对。此次修复原有 23 个双向引用错误：19 条恢复题补齐经原文证明的反向关联，4 条停用伪题的活动关联撤回。另将同卷核验发现的 {quality['reading_unlinked_active_passage']} 条混合题干/选项记录撤回活动语篇关联，并标为 `source_identity_review.status=pending/scoring_eligible=false`；原 ID、全文及旧关联完整保留。详见 `manifest/passage_reference_repair_report.json`。保留 ID 与 `extra.number` 是历史解析身份，不能据此推断原题号；经内容唯一证明的原题号在 `extra.source_question_number`。2015-12 第 2 套 reading-51 实际对应源题号 46，源卷提示 56–60 与实际编号 46–50 冲突已显式留存，历年原卷认证仍待核。

同次全文核验在这 5 份既有源卷内恢复了 {passage_report.get('summary',{}).get('complete_articles_restored_with_history',0)} 份完整语篇：5 份移除正文尾部混入的题干/选项，1 份补齐截短的文章后半段。旧正文完整保存在 `extra.text_history`，恢复正文在原卷中有明确起止定位。全文、匹配段落字母及完整题干/选项均需等值核验；规范化只处理排版空白、全角 ASCII 与等价引号，保留英文词界、数字小数点及其他标点符号。

`source.files` 是结构化多来源入口，每项含仓库根相对 `path/role/locator`；兼容 `source.origin_file` 仅保留首个原文件，旧值在 `_legacy_origin_file`。解析引用含 PDF 页码或 DOCX 正文块/表格行及题号。词汇与模板保留文本锚点；不会把包含省略号的旧指针当完整路径。

版权状态在 `source.copyright`，未知授权明确为 `authorization_status=unknown`；权利人、允许用途、有效期没有证据时保持空值。存在这些字段不代表已取得使用授权。

官方要求通过 `exam_requirement_ids` 对接仓库根 `权威资料/requirements.jsonl`，`requirement_mappings` 保存官方原文定位、来源 URL、初标方法和待专家审核状态。`source.verified` 与 `extra.content_review.expert_review` 分开；脚本不会生成专家姓名、审核日期或“已审核”。CSE 当前与历史版本均记录在 `ontology/standards.json`，原先把 CET 4/6 直接换成 CSE 4/5 的数值已移到历史初标字段。

图谱先修提议使用 `rel=prerequisite_candidate/proposed_rel=prereq_of/active=false`；知识点的待审列表保存在 `candidate_prereq`，正式 `prereq` 保持空值。学习路径只能使用专家核定且激活的正式先修边。

听力文字稿入口是 `listening/transcripts.jsonl`；题目通过 `extra.listening_transcript_ids` 关联题组，通过 `extra.spoken_question_source` 保存口述问题原文与绑定证据。原文存在但文本层损坏的来源标为提取失败，见 `manifest/source_transcript_audit.jsonl`，不能当成来源缺失。旧 PDF 排序提取的 {stats['listening']['superseded_transcripts_retained_for_audit']} 条稿只保留审计，不作为活动稿使用。

听力题组引用 `extra.audio.files` 中的原 MP3，题组 ID 供播放器组织播放；`start_seconds/end_seconds=null` 表示尚未校对片段。只有纸面选项的记录通过 `extra.question_prompt_availability` 记录口述题目可用性；整卷音频有 {stats['questions']['with_audio']} 题关联，仍有 {quality['missing_exact_paper_audio']} 题缺少确切音频，口述问题未恢复 {quality['listening_missing_printed_or_transcribed_question_prompt']} 题。2015 年资料标题与现代听力题型冲突，历史适用版本通过 `extra.exam_design_applicability` 明确待核验，2016 官方技能只作为学习映射依据。`difficulty=null` 和 `difficulty_metadata.status=pending_calibration` 表示无实测校准，不能据此运行 IRT 诊断。

仍缺答案 {quality['missing_answer']}、逐题解析 {quality['missing_analysis']}、完整三段解析 {quality['missing_full_structured_analysis']}；匹配陈述缺失 {quality['missing_matching_statement']}，仔细阅读提问缺失 {quality['missing_careful_reading_question']}。待专家审核 {quality['pending_expert_review']}，待难度校准 {quality['difficulty_pending_calibration']}。其余选项、词库、段落字母、音频缺口完整列在 `manifest/stats.json.remaining_gaps`；原文恢复及剩余边界问题见 `manifest/original_stem_recovery_report.json`、`manifest/reading_resource_recovery_report.json`；扫描件与字体损坏来源清单见 `manifest/answers_fill_report.json.source_diagnostics`。2026-10-06 起由 `fill_answers_ocr.py` 以 Windows OCR 重建损坏源文本并补绑答案/解析(证据分级、全部待审),逐卷结果与剩余缺口见 `manifest/answers_fill_ocr_report.json`。

在仓库根使用 Python 运行以下命令（需要 `pymupdf/python-docx/pandas/xlrd`）：

```powershell
python .\\数据集\\四六级\\scripts\\migrate_v2_schema.py
python .\\数据集\\四六级\\scripts\\fill_answers.py --src '英语四六级资料合集（2026年最新）(1)' --stage '数据集\\四六级\\scripts\\_staging\\answers' --kb '数据集\\四六级'
python .\\数据集\\四六级\\scripts\\repair_kb.py
python .\\数据集\\四六级\\scripts\\build_stats.py --kb '数据集\\四六级'
python -m unittest discover -s tests -p test_cet_repair.py
python .\\审查\\validate_kb.py
```

基础生成器使用增量合并，保留 v2 答案、审核及扩展字段。新增原始资料后可运行 `scripts/rebuild.py --extract` 完整重建，再检查统计与统一验收结果。只做当前数据修复时运行 `scripts/rebuild.py`。系统无 Python 时可把 `python` 换为 Codex 内置运行时 `C:\\Users\\sg\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe`。

使用时先按知识点/题型检索，打开 `content` 与共享 `extra.passage_id`，检查原始答案和解析来源。自动判分应排除 `extra.active=false`、`extra.scoring_eligible=false`、来源冲突、缺答案和选项不完整记录；面向正式用户的发布仍需内容专家审核。保留全库用于修订和检索，不以发布筛选掩盖剩余缺口。
'''
    (kb/'README.md').write_text(readme,encoding='utf-8')
    ingest=f'''# CET 来源与构建记录

本文件由 `scripts/build_stats.py` 随当前全库生成。统计日期 {stats['generated']}；题目 {len(allq)}，答案 {ans}，原文逐题解析 {analysis}。运行增量合并保留原文本、人工字段与隔离历史；不再使用旧版“幂等覆盖”方式。

| 管线 | 输入 | 产物与证据 |
| --- | --- | --- |
| build_vocab.py | 本地词汇 XLS/PDF/DOCX | vocabulary/*.jsonl，原文件与文本锚点 |
| build_questions.py | 归档内 DOCX 和独立 DOCX | questions、reading passages、写译中间资料、paper/parse manifests |
| build_questions_pdf.py | 2024.12、2025.06、2025.12 有文本层试卷 | 增量题目/语篇；原有字段优先保留 |
| build_writing_translation.py | 写译专项真题/参考 PDF、组合答案 PDF、已收录试卷 | 完整题目边界；候选原文、PDF 页码/区间；错误页眉与混入页脚隔离历史 |
| build_templates.py | 模板 DOCX/PDF | 功能标签、原文件和文本锚点 |
| migrate_v2_schema.py | 全库原有与新增资料 | v2 字段、题型细粒度知识/能力；Unicode 物理行安全 |
| docx_source.py | 原 Word 编号 XML、正文及表格 | 可见题号/选项字母，多级重启和精确段落定位 |
| restore_original_stems.py / recover_reading_resources.py | 独立原题的完整编号块和显式标签 | 原匹配陈述、仔细阅读提问、A-O词库和字母段落；无法唯一恢复则保留缺口 |
| recover_listening.py | 全源 PDF/DOCX | source_transcript_audit、listening/transcripts、严格问题/选项唯一绑定；旧排序稿停用留存 |
| fill_answers.py | 解析册/参考答案 DOCX/PDF | 明确源答案和逐题原文解析；冲突/旧误抽答案隔离；source_diagnostics |
| fill_answers_ocr.py + ocr_batch.ps1 | 文本层损坏/双栏排版的解析 PDF(Windows OCR zh-Hans-CN,200dpi,结果缓存在 scripts/_staging/ocr_cache) | OCR 重建文本后按证据分级绑定(level_a 题干/选项命中、level_b 专用册+题号交叉核验或整册对齐、印刷答案表)；全部 pending_expert_review；报告 manifest/answers_fill_ocr_report.json |
| repair_kb.py | 本地完整文件、权威资料 catalog/requirements/rubrics | 精确路径、官方要求、学习映射、音频题组、待审与版权状态 |
| build_stats.py | 所有正式 JSONL | stats、README、本来源记录；保留全部缺陷计数 |

本次相对基线：保留全部5294基线ID，新增行 {len(added_records)}（停用伪题 {quality['inactive_parser_artifacts']}，其余待专家确认）；新增空白题答案 {added}，隔离原有答案 {withdrawn}，净变化 {ans-835}。活动原文解析 {analysis}，完整三段解析 {stats['questions']['with_full_structured_analysis']}；旧错关联解析保存在 analysis_history，不计入活动解析。当前数值以 stats 为准。

当前学习资源唯一 ID {stats['quality']['resources_unique_ids']}，重复 ID {stats['quality']['resource_duplicate_ids']}。写作题目 {stats['writing']['with_prompt']}/{len(writing)}、范文 {stats['writing']['with_model_essay']}/{len(writing)}；翻译原文 {stats['translation']['with_source_text']}/{len(trans)}、译文 {stats['translation']['with_reference']}/{len(trans)}。所有旧混入文本保存在 history/_legacy_text 或完整候选引用中。

仍需处理：答案 {quality['missing_answer']}，原文解析 {quality['missing_analysis']}，完整三段解析 {quality['missing_full_structured_analysis']}；选项与词库、匹配段落字母缺口见 stats.remaining_gaps。写作 2022.12 CET4 第三套范文在源专项册中重复标“第二套”，已按独立第三套答案册首页的卷首身份、完整范文和标题纠正关联，证据见 task_source_bindings.jsonl 与 source_evidence，继续待专家复核。

确切音频已关联 {stats['questions']['with_audio']}/{detail['cet4']['by_module'].get('听力理解',0)+detail['cet6']['by_module'].get('听力理解',0)} 道听力题；缺确切音频 {quality['missing_exact_paper_audio']}。整卷 MP3 的关联不代表题组起止时间已校对；只有纸面选项、没有口述稿时继续列为内容缺口。源明确共用音频说明存 binding_evidence，不猜跨卷替代。

2026.06 试卷和部分解析册是扫描件或损坏字体，需 OCR/人工转录；逐文件名单见 answers_fill_report.source_diagnostics。2024.06 CET4 原题有文本层，但旧 PDF 生成器遗漏该场次，列排版/题号/选项完整性仍需修正；写译任务已从专项与原题独立恢复，未添加残缺客观题冒充整卷。

2015 标题资料包含现代新闻听力指令，原始来源真实性和历史题型仍待确认，见 repair_report.historical_source_papers_pending_authentication。CSE GF0018-2024 现行、2018 历史版均保留；CET 数字不充当 CSE 等级。官方样卷由独立补充目录维护，不覆盖历年题库。

专家审核、难度校准与版权确认仍待完成；题目授权未知 {quality['questions_rights_unknown']} 条，学习资源授权未知 {quality['resources_rights_unknown']} 条。目录标签“大纲词汇”仅为本地来源命名，尚未鉴定为官方词汇表。先修边也继续标 proposed_pending_subject_expert。

复跑：在仓库根执行 `python 数据集/四六级/scripts/rebuild.py --extract`；测试 `python -m unittest discover -s tests -p test_cet_repair.py`，再执行 `python 审查/validate_kb.py`。
'''
    (kb/'manifest/ingest_log.md').write_text(ingest,encoding='utf-8')

if __name__=='__main__': main()
