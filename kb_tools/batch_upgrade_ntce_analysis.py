# -*- coding: utf-8 -*-
"""教师资格考试（NTCE）结构化三段式/四段式解析批量改写与生成引擎。

针对已有客观题答案但解析缺失或仅为 rule_kb_draft 占位存根的题目，
调用 DashScope Qwen 模型生成高质量的四段式结构化解析：
- key_info: 题干考查意图与核心关键词
- option_compare: 选项逐项剖析与陷阱辨析
- trace_back: 考点溯源与大纲定位
- explanation: 答题思路与综合精析

用法:
  python kb_tools/batch_upgrade_ntce_analysis.py --limit 50 --workers 5
  python kb_tools/batch_upgrade_ntce_analysis.py --subject yingyu --limit 20
  python kb_tools/batch_upgrade_ntce_analysis.py --all --workers 5
"""
import os
import sys
import json
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

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


def request_llm(prompt, timeout=40):
    body = json.dumps({
        'model': MODEL_NAME,
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.2,
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


def build_prompt(q, material_text, node_names):
    c = q.get('content', {})
    opts = c.get('options', [])
    opts_str = ' '.join(f"{o.get('key')}. {o.get('text')}" for o in opts)
    ans = c.get('answer')
    level = q.get('level', '')
    subject = q.get('subject', '')
    qtype = q.get('question_type', '单选')

    prompt = (
        "你是一位资深的教师资格考试（NTCE）命题与阅卷教研专家。请为以下教师资格考试试题撰写标准四段式结构化解析。\n\n"
        f"【试题背景】\n"
        f"学段: {level} | 科目: {subject} | 题型: {qtype}\n"
    )
    if material_text:
        prompt += f"材料背景(节选):\n{material_text[:1200]}\n\n"
    if node_names:
        prompt += f"关联大纲考点: {', '.join(node_names)}\n"

    prompt += (
        f"题干: {c.get('stem', '')}\n"
        f"选项: {opts_str}\n"
        f"标准答案: {ans}\n\n"
        "【撰写规范】\n"
        "请严格输出合法的 JSON 对象，不要输出任何额外的解释文本或 markdown 标记，字段包含：\n"
        "{\n"
        '  "key_info": "题干核心考点与意图提取（明确学科核心概念、考查意图与核心关键词）",\n'
        '  "option_compare": "逐项深度辨析（逐一剖析 A、B、C、D 各选项为何正确或错误，明确指出错误项的干扰陷阱）",\n'
        '  "trace_back": "考点溯源与大纲定位（定位至教资考纲、教育学/心理学/学科专业知识的对应具体理论与推导步骤）",\n'
        '  "explanation": "答题精析与考点总结（归纳该考点的命题规律、做题技巧与记忆要点）"\n'
        "}\n"
    )
    return prompt


def process_question(item, materials, nodes):
    q, file_path, row_idx = item
    mat_text = materials.get(q.get('material_id'), '')
    node_names = [nodes.get(nid) for nid in q.get('knowledge_node_ids', []) if nodes.get(nid)]

    prompt = build_prompt(q, mat_text, node_names)
    for attempt in range(3):
        try:
            parsed = request_llm(prompt)
            if isinstance(parsed, dict) and all(k in parsed for k in ('key_info', 'option_compare', 'trace_back', 'explanation')):
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


def is_eligible_ntce(r):
    c = r.get('content', {})
    a = r.get('analysis')
    ans = c.get('answer')
    if not ans:
        return False
    # 客观选择题（4个选项）
    opts = c.get('options')
    if not isinstance(opts, list) or len(opts) < 2:
        return False
    # 判断是否已有完整结构化解析
    if isinstance(a, dict) and a.get('key_info') and a.get('option_compare') and a.get('trace_back') and a.get('explanation'):
        return False
    return True


def main():
    if not API_KEY:
        print("错误: 缺少 DASHSCOPE_API_KEY 环境变量", flush=True)
        sys.exit(1)

    limit = 50
    workers = 5
    target_subject = None

    global MODEL_NAME
    if '--model' in sys.argv:
        MODEL_NAME = sys.argv[sys.argv.index('--model') + 1]
    if '--limit' in sys.argv:
        limit = int(sys.argv[sys.argv.index('--limit') + 1])
    if '--all' in sys.argv:
        limit = 999999
    if '--workers' in sys.argv:
        workers = int(sys.argv[sys.argv.index('--workers') + 1])
    if '--subject' in sys.argv:
        target_subject = sys.argv[sys.argv.index('--subject') + 1]

    print(f"=== 教资客观题结构化解析批量生成 ===", flush=True)
    print(f"模型: {MODEL_NAME} | 并发工作线程: {workers} | 计划处理上限: {limit} | 指定学科: {target_subject or '全部'}", flush=True)

    materials = load_materials()
    nodes = load_knowledge_nodes()
    print(f"加载关联材料: {len(materials)} 份, 知识图谱节点: {len(nodes)} 个", flush=True)

    todo = []
    files_map = {}
    for p in sorted((KB_NTCE / 'questions').rglob('*.jsonl')):
        if target_subject and p.parent.name != target_subject:
            continue
        rows = []
        for l in p.open(encoding='utf-8'):
            if l.strip():
                rows.append(json.loads(l))
        files_map[str(p)] = rows
        for idx, r in enumerate(rows):
            if is_eligible_ntce(r):
                todo.append((r, str(p), idx))
                if len(todo) >= limit:
                    break
        if len(todo) >= limit:
            break

    print(f"筛选出待处理题目: {len(todo)} 题", flush=True)
    if not todo:
        print("没有需要处理的题目。", flush=True)
        return

    success_count = 0
    fail_count = 0
    updated_files = set()

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
                target_row['analysis'] = {
                    'key_info': ans_data['key_info'],
                    'option_compare': ans_data['option_compare'],
                    'trace_back': ans_data['trace_back'],
                    'explanation': ans_data['explanation'],
                    'status': 'llm_draft_pending_expert',
                    'expert_verified': False,
                    'correct_answer': target_row['content']['answer'],
                    'method': f'{MODEL_NAME}_structured_v1',
                    'knowledge_node_ids': target_row.get('knowledge_node_ids', []),
                    'ability_ids': target_row.get('ability_ids', []),
                    'exam_requirement_ids': target_row.get('exam_requirement_ids', []),
                    'source_note': '以题干、选项与答案为基准，由学科大模型生成四段结构化解析；待学科专家终审。'
                }
                target_row['content']['analysis'] = ans_data['explanation']
                target_row.setdefault('extra', {})['analysis_status'] = 'structured_draft'
                updated_files.add(fpath)
                print(f"  [{success_count + fail_count}/{len(todo)}] [成功] {qid}", flush=True)

                if success_count % 30 == 0:
                    for uf in list(updated_files):
                        content = '\n'.join(jsonl_dumps(r) for r in files_map[uf]) + '\n'
                        atomic_write(Path(uf), content)
                    print(f"  --> 已增量持久化落盘 {len(updated_files)} 个文件", flush=True)
            else:
                fail_count += 1
                print(f"  [{success_count + fail_count}/{len(todo)}] [失败] {qid}: {res.get('error')}", flush=True)

    print(f"\n正在将新生成的结构化解析原子写入 {len(updated_files)} 个题目文件...", flush=True)
    for fpath in updated_files:
        rows = files_map[fpath]
        content = '\n'.join(jsonl_dumps(r) for r in rows) + '\n'
        atomic_write(Path(fpath), content)

    print(f"=== 批处理完成 ===", flush=True)
    print(f"成功: {success_count} 题 | 失败: {fail_count} 题 | 更新文件: {len(updated_files)} 个", flush=True)


if __name__ == '__main__':
    main()
