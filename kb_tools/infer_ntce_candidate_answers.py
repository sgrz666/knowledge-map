# -*- coding: utf-8 -*-
"""教师资格考试（NTCE）缺失答案客观题：学科理论推导与结构化解析生成引擎。

针对 content.answer 为 None 的教资客观选择题：
1. 注入题干、选项、学段科目、材料背景及关联考试大纲知识节点；
2. 提示大模型严密推导最佳候选答案（candidate_answer），给出理论论证与置信度；
3. 同步生成四段式深度结构化解析（key_info, option_compare, trace_back, explanation）；
4. 结果落入 extra.candidate_inference 与 analysis，绝不污染 content.answer，保持判分安全合规。

用法:
  python kb_tools/infer_ntce_candidate_answers.py --limit 50 --workers 5
  python kb_tools/infer_ntce_candidate_answers.py --all --workers 6
"""
import os
import sys
import json
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parents[1]
KB_NTCE = ROOT / '数据集' / '教资'
sys.path.insert(0, str(ROOT / 'kb_tools'))
from ntce_io import atomic_write

API_KEY = os.environ.get('DASHSCOPE_API_KEY')
BASE_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'
MODEL_NAME = os.environ.get('DASHSCOPE_MODEL', 'qwen-plus')


def jsonl_dumps(row):
    text = json.dumps(row, ensure_ascii=False)
    return text.replace('\x85', '\\u0085').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')


def load_materials():
    materials = {}
    for mf in KB_NTCE.glob('materials/*/*/*.jsonl'):
        for line in mf.open(encoding='utf-8'):
            if line.strip():
                m = json.loads(line)
                materials[m['material_id']] = m.get('text', '')
    return materials


def load_knowledge_nodes():
    nodes = {}
    npath = KB_NTCE / 'graph/nodes.jsonl'
    if npath.exists():
        for line in npath.open(encoding='utf-8'):
            if line.strip():
                n = json.loads(line)
                nodes[n['id']] = n.get('name', '')
    return nodes


def request_llm(prompt, timeout=45):
    body = json.dumps({
        'model': MODEL_NAME,
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.1,
        'response_format': {'type': 'json_object'}
    }).encode('utf-8')

    req = urllib.request.Request(
        BASE_URL,
        data=body,
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {API_KEY}'}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        res = json.loads(resp.read().decode('utf-8'))
        content = res['choices'][0]['message']['content']
        return json.loads(content)


def build_ntce_inference_prompt(q, material_text, node_names):
    c = q.get('content', {})
    opts = c.get('options', [])
    opts_str = ' '.join(f"{o.get('key')}. {o.get('text')}" for o in opts)
    level = q.get('level', '')
    subject = q.get('subject', '')
    qtype = q.get('question_type', '单选')

    prompt = (
        "你是一位资深的教师资格考试（NTCE）教研命题与阅卷专家。以下是一道缺失官方标准答案的教资客观选择题。\n"
        "请结合教育学、心理学或学科专业理论体系，严密推导唯一最佳候选答案，并撰写标准四段式结构化解析。\n\n"
        f"【试题背景】\n"
        f"学段: {level} | 科目: {subject} | 题型: {qtype}\n"
    )
    if material_text:
        prompt += f"\n【材料背景(节选)】\n{material_text[:1200]}\n"
    if node_names:
        prompt += f"【考查大纲关联】: {', '.join(node_names)}\n"

    prompt += (
        f"\n题干: {c.get('stem', '')}\n"
        f"选项: {opts_str}\n\n"
        "【作答规范】\n"
        "请严格输出合法的 JSON 对象，不要输出任何额外的 markdown 代码标记或解释，包含以下字段：\n"
        "{\n"
        '  "predicted_answer": "推导出的最佳候选答案选项字母（如 A, B, C, D）",\n'
        '  "confidence": "推导置信度（high / medium / low）",\n'
        '  "key_info": "题干核心考查意图与关键考点提取",\n'
        '  "option_compare": "逐项深度辨析（逐一剖析各选项为何正确或错误，指明错误项的干扰陷阱）",\n'
        '  "trace_back": "考点溯源与大纲定位（定位至教资考试大纲、教育学/心理学/学科专业理论与推导步骤）",\n'
        '  "explanation": "解题思路归纳与记忆要点总结"\n'
        "}\n"
    )
    return prompt


def process_question(item, materials, nodes):
    q, file_path, row_idx = item
    mat_text = materials.get(q.get('material_id'), '')
    node_names = [nodes.get(nid) for nid in q.get('knowledge_node_ids', []) if nodes.get(nid)]

    prompt = build_ntce_inference_prompt(q, mat_text, node_names)
    for attempt in range(3):
        try:
            parsed = request_llm(prompt)
            if isinstance(parsed, dict) and parsed.get('predicted_answer') and all(k in parsed for k in ('key_info', 'option_compare', 'trace_back', 'explanation')):
                return {
                    'question_id': q['question_id'],
                    'file_path': file_path,
                    'row_idx': row_idx,
                    'result': parsed,
                    'status': 'success'
                }
        except Exception as e:
            if attempt == 2:
                return {
                    'question_id': q['question_id'],
                    'file_path': file_path,
                    'row_idx': row_idx,
                    'error': str(e),
                    'status': 'error'
                }
            time.sleep(1.0)
    return {'question_id': q['question_id'], 'status': 'failed'}


def is_eligible_ntce_unanswered(r):
    c = r.get('content', {})
    extra = r.get('extra', {})
    ans = c.get('answer')
    opts = c.get('options')
    # 候选条件：没有答案，但有选择题选项（客观题），且尚未完成候选推导
    has_answer = bool(ans)
    has_candidate = bool(extra.get('candidate_inference') and extra.get('candidate_answer'))
    is_choice = isinstance(opts, list) and len(opts) >= 2
    return (not has_answer) and (not has_candidate) and is_choice


def main():
    if not API_KEY:
        print("错误: 缺少 DASHSCOPE_API_KEY 环境变量", flush=True)
        sys.exit(1)

    limit = 50
    workers = 5
    global MODEL_NAME
    if '--model' in sys.argv:
        MODEL_NAME = sys.argv[sys.argv.index('--model') + 1]
    if '--limit' in sys.argv:
        limit = int(sys.argv[sys.argv.index('--limit') + 1])
    if '--all' in sys.argv:
        limit = 999999
    if '--workers' in sys.argv:
        workers = int(sys.argv[sys.argv.index('--workers') + 1])

    print(f"=== 教资缺失答案客观题：理论推导与结构化解析引擎 ===", flush=True)
    print(f"模型: {MODEL_NAME} | 并发工作线程: {workers} | 计划处理上限: {limit}", flush=True)

    materials = load_materials()
    nodes = load_knowledge_nodes()
    print(f"加载关联材料: {len(materials)} 份, 知识图谱节点: {len(nodes)} 个", flush=True)

    todo = []
    files_map = {}
    for p in sorted((KB_NTCE / 'questions').rglob('*.jsonl')):
        rows = []
        for l in p.open(encoding='utf-8'):
            if l.strip():
                rows.append(json.loads(l))
        files_map[str(p)] = rows
        for idx, r in enumerate(rows):
            if is_eligible_ntce_unanswered(r):
                todo.append((r, str(p), idx))
                if len(todo) >= limit:
                    break
        if len(todo) >= limit:
            break

    print(f"筛选出待推导候选答案客观题: {len(todo)} 题", flush=True)
    if not todo:
        print("没有需要推导的题目。", flush=True)
        return

    success_count = 0
    fail_count = 0
    updated_files = set()

    dry_run = '--dry-run' in sys.argv
    if dry_run:
        print("[!] 运行模式: --dry-run (仅演示推导过程，不写入文件)", flush=True)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_question, item, materials, nodes): item for item in todo}
        for future in as_completed(futures):
            res = future.result()
            qid = res['question_id']
            if res.get('status') == 'success':
                success_count += 1
                fpath = res['file_path']
                idx = res['row_idx']
                ans_data = res['result']

                target_row = files_map[fpath][idx]
                target_extra = target_row.setdefault('extra', {})

                # 记录高可信候选答案（绝不改写 content.answer 保持判分安全）
                cand_ans = ans_data['predicted_answer'].strip().upper()
                target_extra['candidate_answer'] = cand_ans
                target_extra['candidate_inference'] = {
                    'candidate_answer': cand_ans,
                    'confidence': ans_data.get('confidence', 'medium'),
                    'method': f'{MODEL_NAME}_deduced_candidate_v1',
                    'status': 'candidate_pending_expert_review',
                    'expert_verified': False
                }

                # 填充四段式结构化解析草稿
                target_row['analysis'] = {
                    'key_info': ans_data['key_info'],
                    'option_compare': ans_data['option_compare'],
                    'trace_back': ans_data['trace_back'],
                    'explanation': ans_data['explanation'],
                    'status': 'candidate_draft_pending_expert',
                    'method': f'{MODEL_NAME}_deduced_candidate_v1',
                    'expert_verified': False,
                    'source_note': '原题来源缺失官方答案；本候选答案与解析由学科大模型基于考纲理论体系独立推导，待专家终审。'
                }
                target_extra['analysis_status'] = 'candidate_structured_draft'

                updated_files.add(fpath)
                print(f"  [{success_count + fail_count}/{len(todo)}] [成功] {qid} -> 候选答案: {cand_ans}", flush=True)
                if dry_run:
                    print(f"      [考点定位]: {ans_data.get('key_info')}", flush=True)
                    print(f"      [选项剖析]: {ans_data.get('option_compare')[:120]}...", flush=True)

                if not dry_run and success_count % 30 == 0:
                    for uf in list(updated_files):
                        content = '\n'.join(jsonl_dumps(r) for r in files_map[uf]) + '\n'
                        atomic_write(Path(uf), content)
                    print(f"  --> 已增量持久化落盘 {len(updated_files)} 个文件", flush=True)
            else:
                fail_count += 1
                print(f"  [{success_count + fail_count}/{len(todo)}] [失败] {qid}: {res.get('error')}", flush=True)

    if dry_run:
        print(f"\n=== 演示推导完成 (dry-run 未写入文件) ===", flush=True)
        print(f"成功推导: {success_count} 题 | 失败: {fail_count} 题", flush=True)
        return

    print(f"\n正在完成最终原子写入（共 {len(updated_files)} 个题目文件）...", flush=True)
    for fpath in updated_files:
        rows = files_map[fpath]
        content = '\n'.join(jsonl_dumps(r) for r in rows) + '\n'
        atomic_write(Path(fpath), content)

    print(f"=== 批处理完成 ===", flush=True)
    print(f"成功: {success_count} 题 | 失败: {fail_count} 题 | 更新文件: {len(updated_files)} 个", flush=True)


if __name__ == '__main__':
    main()
