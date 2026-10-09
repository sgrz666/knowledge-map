# -*- coding: utf-8 -*-
"""四六级结构化三段式解析批量改写与生成引擎。

用法:
  python 数据集/四六级/scripts/batch_upgrade_analysis.py --limit 50 --workers 5
  python 数据集/四六级/scripts/batch_upgrade_analysis.py --all --workers 5
"""
import os
import sys
import json
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
KB_CET = ROOT / '数据集/四六级'
sys.path.insert(0, str(KB_CET / 'scripts'))
from cet_common import jsonl_dumps

API_KEY = os.environ.get('DASHSCOPE_API_KEY')
BASE_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'
MODEL_NAME = os.environ.get('DASHSCOPE_MODEL', 'qwen-plus')


def load_passages():
    reading_passages = {}
    rpath = KB_CET / 'passages/reading.jsonl'
    if rpath.exists():
        for l in rpath.open(encoding='utf-8'):
            if l.strip():
                row = json.loads(l)
                reading_passages[row['resource_id']] = row.get('text', '')

    listening_transcripts = {}
    lpath = KB_CET / 'listening/transcripts.jsonl'
    if lpath.exists():
        for l in lpath.open(encoding='utf-8'):
            if l.strip():
                row = json.loads(l)
                listening_transcripts[row['resource_id']] = row.get('text', '')
    return reading_passages, listening_transcripts


def request_llm(prompt, timeout=35):
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


def build_prompt(q, ptext):
    c = q.get('content', {})
    a = q.get('analysis', {})
    opts_str = json.dumps(c.get('options', {}), ensure_ascii=False)
    raw_str = (a.get('raw') or '')[:1000]

    prompt = (
        "你是一位资深的大学英语四六级教研专家。请为以下四六级试题撰写标准的三段式结构化解析。\n\n"
        f"【试题背景】\n"
        f"题型: {q.get('question_type')}\n"
    )
    if ptext:
        prompt += f"篇章材料(节选):\n{ptext[:1200]}\n\n"
    prompt += (
        f"题干: {c.get('stem', '')}\n"
        f"选项: {opts_str}\n"
        f"标准答案: {c.get('answer')}\n"
    )
    if raw_str:
        prompt += f"出版物原始解析参考: {raw_str}\n"
    prompt += (
        "\n【撰写规范】\n"
        "请严格输出合法的 JSON 对象，不要输出任何额外的解释文本或 markdown 代码标记，字段包含：\n"
        "{\n"
        '  "key_info": "题干关键信息提取（明确考查意图与核心关键词）",\n'
        '  "option_compare": "逐项对比分析（逐一解析A、B、C、D选项为什么对或错，指明干扰项的陷阱设计）",\n'
        '  "trace_back": "考点溯源与定位（定位原文段落/关键句或听力考点，分析推理逻辑）",\n'
        '  "explanation": "总体精析总结（归纳该题的核心做题技巧与结论）"\n'
        "}\n"
    )
    return prompt


def process_question(item, reading_passages, listening_transcripts):
    q, file_path, row_idx = item
    pid = q.get('extra', {}).get('passage_id')
    ptext = reading_passages.get(pid, '')
    if not ptext and q.get('extra', {}).get('listening_transcript_ids'):
        lt_ids = q['extra']['listening_transcript_ids']
        if isinstance(lt_ids, list) and lt_ids:
            ptext = listening_transcripts.get(lt_ids[0], '')

    prompt = build_prompt(q, ptext)
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


def atomic_write(path, text, encoding='utf-8'):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name('.' + p.name + '.' + os.urandom(4).hex() + '.tmp')
    try:
        tmp.write_text(text, encoding=encoding)
        tmp.replace(p)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def save_updated(updated_files, files_map):
    for fpath in list(updated_files):
        rows = files_map[fpath]
        content = '\n'.join(jsonl_dumps(r) for r in rows) + '\n'
        atomic_write(fpath, content)


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

    print(f"=== 四六级结构化解析批量生成 ===")
    print(f"模型: {MODEL_NAME} | 并发工作线程: {workers} | 计划处理上限: {limit}")

    reading_passages, listening_transcripts = load_passages()
    print(f"加载阅读语篇: {len(reading_passages)} 篇, 听力文字稿: {len(listening_transcripts)} 篇")

    # 扫描待处理题目
    todo = []
    files_map = {}
    for p in sorted((KB_CET / 'questions').rglob('*.jsonl')):
        rows = []
        for l in p.open(encoding='utf-8'):
            if l.strip():
                rows.append(json.loads(l))
        files_map[str(p)] = rows
        for idx, r in enumerate(rows):
            c = r.get('content', {})
            a = r.get('analysis', {})
            # 候选条件：有正确答案，且尚未具备完整的 key_info 和 option_compare
            if c.get('answer') and not (isinstance(a, dict) and a.get('key_info') and a.get('option_compare')):
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
        futures = {executor.submit(process_question, item, reading_passages, listening_transcripts): item for item in todo}
        for future in as_completed(futures):
            res = future.result()
            qid = res['question_id']
            if res.get('status') == 'success':
                success_count += 1
                fpath = res['file_path']
                idx = res['row_idx']
                ans_data = res['result']

                # 回填结构化字段，保留原始 raw 记录
                target_row = files_map[fpath][idx]
                prev_analysis = target_row.get('analysis') or {}
                raw_text = prev_analysis.get('raw') if isinstance(prev_analysis, dict) else None

                target_row['analysis'] = {
                    'key_info': ans_data['key_info'],
                    'option_compare': ans_data['option_compare'],
                    'trace_back': ans_data['trace_back'],
                    'explanation': ans_data['explanation'],
                    'raw': raw_text,
                    'status': 'llm_structured_from_source' if raw_text else 'llm_generated_draft',
                    'method': f'{MODEL_NAME}_structured_v1',
                    'expert_verified': False
                }
                target_row.setdefault('extra', {})['analysis_status'] = 'structured_draft'
                updated_files.add(fpath)
                print(f"  [{success_count + fail_count}/{len(todo)}] [成功] {qid}", flush=True)

                if success_count % 30 == 0:
                    save_updated(updated_files, files_map)
                    print(f"  --> 已增量持久化落盘 {len(updated_files)} 个文件", flush=True)
            else:
                fail_count += 1
                print(f"  [{success_count + fail_count}/{len(todo)}] [失败] {qid}: {res.get('error')}", flush=True)

    # 最终完整写盘
    print(f"\n正在完成最终原子写入（共 {len(updated_files)} 个题目文件）...", flush=True)
    save_updated(updated_files, files_map)

    print(f"=== 批处理完成 ===", flush=True)
    print(f"成功: {success_count} 题 | 失败: {fail_count} 题 | 更新文件: {len(updated_files)} 个", flush=True)


if __name__ == '__main__':
    main()
