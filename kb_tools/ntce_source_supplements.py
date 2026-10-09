"""少量来源明确的参考要点与逐题解析草稿；不声称官方标准答案或专家通过。"""
import hashlib
import json
from build_kb import ROOT, OUT
from ntce_repair import read_rows, write_rows, reviewed_content, load_official, practice_rubric

COLLEGE_URL = 'https://dfl.aku.edu.cn/info/1641/6717.htm'
SCIENCE_POINTS = ['知识内容和论证须准确、符合科学认识。', '按具体学科内容安排价值与品德教育。',
                  '把育人要求落实到教学活动的各环节。', '持续提升教师的专业水平和思想修养。']
HEURISTIC_POINTS = ['激发学生主动参与学习。', '以提问等方式引导独立思考和推理。',
                    '让学生实践并独立处理问题。', '建立平等交流的师生关系。']
BRIEF = {
    'ntce.zhongxue.jiaoyuzhishi.2013a.q25': ('科学性与思想性', SCIENCE_POINTS, '这一原则要求把科学知识教学与价值、品德教育结合。', 768, 775),
    'ntce.zhongxue.jiaoyuzhishi.2018b.q25': ('科学性和思想性', SCIENCE_POINTS, '', 768, 775),
    'ntce.zhongxue.jiaoyuzhishi.2022a.q26': ('启发性', HEURISTIC_POINTS, '', 737, 743),
}
LAW = {
    'ntce.xiaoxue.zonghe.2017b.q07': ('C', '学校作出的处理决定', '本题问被申诉主体。争议决定由学校作出，因此选学校；教育行政部门在此承担受理职责，不能和被申诉主体混同。'),
    'ntce.xiaoxue.zonghe.2021b.q09': ('A', '县有关部门拖欠工资', '侵权主体是地方政府有关行政部门，适用教师法第三十九条第二款。同级人民政府属于法定申诉渠道；题列上一级人民政府本身和学校不是该款列出的对应渠道。'),
    'ntce.youer.zonghe.2019a.q08': ('A', '当地教育行政部门侵犯权益', '应针对行政部门侵权选择同级人民政府，或上一级人民政府有关部门。A同时呈现这两类渠道；法院、检察院不是本题法条规定的申诉受理主体，D改变了层级。'),
    'ntce.youer.zonghe.2023a.q08': ('B', '幼儿园侵犯进修培训权利', '侵权主体是教育机构，按第三十九条第一款向教育行政部门申诉。A、C是政府层级，D是纪检机关，均未对应本题学校或教育机构侵权的申诉渠道。'),
    'ntce.zhongxue.zonghe.2018a.q07': ('B', '当地教育行政部门侵犯权利', '第三十九条第二款把同级人民政府列为行政部门侵权的申诉渠道。A仍是同级教育行政部门，C只写上级政府，D是纪检部门，均与题列法定渠道不符。'),
}


def supplement(sync=True):
    sources, requirements = load_official()
    clause = next(r for r in requirements if r['requirement_id'] == 'law.teacher.2009.r040')
    local = OUT / 'sources/aku_education_reference.txt'
    if not local.exists():
        raise RuntimeError('缺少已采集的安康学院原文，请先恢复来源文件。')
    lines = local.read_text(encoding='utf-8').split('\n')
    reference_files = []
    for p in (local, local.with_suffix('.html')):
        reference_files.append({'path': p.relative_to(ROOT).as_posix(), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()})
    catalog = {'sources': [{'source_id': 'aku.education.20230520', 'name': '安康学院教育知识与能力学习资料',
                           'source_url': COLLEGE_URL, 'published_at': '2023-05-20', 'files': reference_files,
                           'scope': 'supplementary_learning_reference; not_official_exam_answer',
                           'copyright': {'authorization_status': 'unknown'}, 'expert_verified': False}]}
    (OUT / 'sources/catalog.json').write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding='utf-8')
    answer_count = analysis_count = 0
    for path in sorted((OUT / 'questions').glob('*/*/*.jsonl')):
        records = read_rows(path)
        for q in records:
            qid, c = q['question_id'], q['content']
            if reviewed_content(q) or q['review'].get('cross_question_risk'):
                continue
            if qid in BRIEF and not c.get('answer'):
                phrase, points, definition, start, end = BRIEF[qid]
                if phrase not in c['stem'] or not any(phrase.replace('与', '和') in line for line in lines[start - 1:end]):
                    raise RuntimeError('来源或题目已改变，停止使用旧定位：' + qid)
                basis = {'path': local.relative_to(ROOT).as_posix(), 'role': 'analysis_basis', 'source_url': COLLEGE_URL,
                         'locator': {'line_start': start, 'line_end': end}, 'scope': 'learning_reference_not_official_exam_answer'}
                before_state = {'answer': c.get('answer'), 'answer_status': c['answer_status'],
                                'answer_provenance': q['extra'].get('answer_provenance')}
                c['answer'] = '参考要点（待教研核定）：' + definition + '；'.join(points)
                c['answer_status'] = 'reference_only'
                q['extra']['answer_provenance'] = 'derived_reference'
                c['analysis'] = '题目直接要求该原则的落实要求；作答应逐项说明行动，而不只列出原则名称。' + definition + '；'.join(points)
                q['analysis'] = {'method': 'source_grounded_editorial_draft', 'correct_answer': c['answer'],
                                 'key_info': c['stem'], 'option_compare': None, 'trace_back': phrase + '的实施要求',
                                 'explanation': c['analysis'], 'status': 'derived_reference_pending_expert',
                                 'expert_verified': False, 'source_files': [basis], 'official_answer': False}
                rubric = practice_rubric(q)
                if not rubric.get('checked_by') and not rubric.get('question_specific_points'):
                    rubric['question_specific_points'] = [{'point_id': qid + '.p%d' % (i + 1), 'expected': point, 'source_files': [basis], 'official_score': None} for i, point in enumerate(points)]
                q['source']['files'].append(basis)
                q['extra'].setdefault('source_repairs', []).append({'kind': 'reference_points_from_learning_source',
                    'before': before_state, 'expert_verified': False})
                answer_count += 1
                analysis_count += 1
            elif qid in LAW and not c.get('analysis'):
                answer, key, explanation = LAW[qid]
                if c.get('answer') != answer or len(c['options']) != 4:
                    continue
                basis = {'path': sources[clause['standard_id']]['local_path'], 'role': 'analysis_basis',
                         'source_url': sources[clause['standard_id']]['source_url'], 'locator': clause['locator']}
                c['analysis'] = explanation
                q['analysis'] = {'method': 'source_grounded_editorial_draft', 'correct_answer': answer, 'key_info': key,
                                 'option_compare': explanation, 'trace_back': '教师法第三十九条：先区分教育机构与行政部门，再确定申诉主体或渠道。',
                                 'explanation': explanation, 'status': 'source_grounded_draft_pending_expert', 'expert_verified': False,
                                 'basis_requirement_ids': [clause['requirement_id']], 'source_files': [basis], 'official_answer': False}
                q['source']['files'].append(basis)
                analysis_count += 1
        write_rows(path, records)
    result = {'new_reference_answers': answer_count, 'new_explanations': analysis_count, 'expert_verified': False}
    print(json.dumps(result, ensure_ascii=False))
    if sync:
        from ntce_repair import repair
        repair(skip_outline=True)
    return result


if __name__ == '__main__':
    import sys
    supplement('--no-sync' not in sys.argv)
