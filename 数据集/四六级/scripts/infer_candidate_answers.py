# -*- coding: utf-8 -*-
"""四六级缺失答案真题：基于语篇证据链的候选答案推导与四段式解析生成引擎。

针对 content.answer 为 None 的四六级试题（包括缺少答案卷、历史来源冲突或隔离存根）：
1. 动态加载阅读理解语篇（reading passages）与听力录音文字稿（listening transcripts）；
2. 提取已有的出版物参考解析或历史候选线索（如有）；
3. 提示大模型定位原文证据句（evidence_quote），推导高置信度候选答案（candidate_answer）；
4. 同步生成星火标准四段式解析（key_info, option_compare, trace_back, explanation）；
5. 结果落入 extra.candidate_inference 与 analysis，绝不污染 content.answer，保持判分安全合规。

用法:
  python 数据集/四六级/scripts/infer_candidate_answers.py --limit 50 --workers 5
  python 数据集/四六级/scripts/infer_candidate_answers.py --all --workers 6
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

ROOT = Path(__file__).resolve().parents[3]
KB_CET = ROOT / '数据集/四六级'
sys.path.insert(0, str(KB_CET / 'scripts'))
from cet_common import jsonl_dumps

API_KEY = os.environ.get('DASHSCOPE_API_KEY')
BASE_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'
MODEL_NAME = os.environ.get('DASHSCOPE_MODEL', 'qwen-plus')


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


def build_inference_prompt(q, ptext):
    c = q.get('content', {})
    extra = q.get('extra', {})
    opts = c.get('options')
    if isinstance(opts, dict):
        opts_str = json.dumps(opts, ensure_ascii=False)
    elif isinstance(opts, list):
        opts_str = ' '.join(f"{o.get('key')}. {o.get('text')}" for o in opts)
    else:
        opts_str = str(opts)

    # 提取历史候选或来源解析线索
    clues = []
    cur_raw = q.get('analysis', {}).get('raw') if isinstance(q.get('analysis'), dict) else None
    if cur_raw:
        clues.append(f"现有出版物原始解析参考: {cur_raw[:600]}")
    if extra.get('answer_history'):
        for hist in extra['answer_history']:
            if isinstance(hist, dict) and hist.get('answer'):
                clues.append(f"历史候选答案记录: {hist.get('answer')} (原因: {hist.get('reason')})")
    if extra.get('analysis_history'):
        for hist in extra['analysis_history']:
            if isinstance(hist, dict):
                raw = hist.get('analysis', {}).get('raw')
                if raw and raw != cur_raw:
                    clues.append(f"出版物历史解析节选: {raw[:300]}")
    clues_str = ('\n【参考线索】\n' + '\n'.join(clues)) if clues else ''

    if q.get('question_type') == '长篇阅读' and not opts_str.strip('{} '):
        opts_str = "段落字母匹配 [A] - [O]（从所附材料各段首字母标记中，选出唯一能支持题干陈述的段落字母）"

    prompt = (
        "你是一位资深的大学英语四六级教研命题与阅卷专家。以下是一道缺失官方标准答案的四六级真题。\n"
        "请根据给定的语篇材料、题干和选项，严密推导唯一最佳候选答案，并撰写标准的三段式结构化解析。\n\n"
        f"【试题背景】\n"
        f"考试级别: {q.get('exam')} | 题型: {q.get('question_type')}\n"
    )
    max_len = 7500 if q.get('question_type') == '长篇阅读' else 2500
    if ptext:
        prompt += f"\n【篇章/听力原文】\n{ptext[:max_len]}\n"
    prompt += (
        f"\n题干: {c.get('stem', '')}\n"
        f"选项: {opts_str}\n"
        f"{clues_str}\n\n"
        "【作答规范】\n"
        "请严格输出合法的 JSON 对象，不要输出任何额外的 markdown 代码标记或解释，包含以下字段：\n"
        "{\n"
        '  "predicted_answer": "推导出的最佳候选答案选项字母（如 A, B, C, D 或选词填空/长篇匹配的 A-O 字母）",\n'
        '  "confidence": "推导置信度（high / medium / low）",\n'
        '  "evidence_quote": "原文中最核心的直接证据句或定位句（英文原文摘录）",\n'
        '  "key_info": "题干核心关键词与考查意图提取",\n'
        '  "option_compare": "逐项对比剖析（说明为什么正确选项符合原文，其他选项为何是干扰项/错误陷阱）",\n'
        '  "trace_back": "考点溯源与定位分析（定位原文具体位置及因果/转折/细节推导链条）",\n'
        '  "explanation": "解题思路归纳与核心技巧总结"\n'
        "}\n"
    )
    return prompt


def process_question(item, reading_passages, listening_transcripts):
    q, file_path, row_idx = item
    pid = q.get('extra', {}).get('passage_id')
    ptext = reading_passages.get(pid, '')
    if not ptext and q.get('extra', {}).get('listening_transcript_ids'):
        lt_ids = q['extra']['listening_transcript_ids']
        if isinstance(lt_ids, list):
            texts = [listening_transcripts.get(tid, '') for tid in lt_ids if listening_transcripts.get(tid)]
            ptext = '\n\n'.join(texts)
        elif isinstance(lt_ids, str):
            ptext = listening_transcripts.get(lt_ids, '')

    prompt = build_inference_prompt(q, ptext)
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


def is_eligible_for_inference(r):
    c = r.get('content', {})
    extra = r.get('extra', {})
    # 候选条件：没有正式答案，且尚未完成候选推导
    has_answer = bool(c.get('answer'))
    has_candidate = bool(extra.get('candidate_inference') and extra.get('candidate_answer'))
    # 排除不是单题选择/填空/长篇匹配的异常题
    opts = c.get('options')
    is_matching = r.get('question_type') == '长篇阅读' and bool(extra.get('passage_id'))
    has_opts = bool(opts and len(opts) > 0) or is_matching
    return (not has_answer) and (not has_candidate) and has_opts


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

    print(f"=== 四六级缺失答案真题：候选推导与结构化解析引擎 ===", flush=True)
    print(f"模型: {MODEL_NAME} | 并发工作线程: {workers} | 计划处理上限: {limit}", flush=True)

    reading_passages, listening_transcripts = load_passages()
    print(f"加载阅读语篇: {len(reading_passages)} 篇, 听力文字稿: {len(listening_transcripts)} 篇", flush=True)

    todo = []
    files_map = {}
    for p in sorted((KB_CET / 'questions').rglob('*.jsonl')):
        rows = []
        for l in p.open(encoding='utf-8'):
            if l.strip():
                rows.append(json.loads(l))
        files_map[str(p)] = rows
        for idx, r in enumerate(rows):
            if is_eligible_for_inference(r):
                todo.append((r, str(p), idx))
                if len(todo) >= limit:
                    break
        if len(todo) >= limit:
            break

    print(f"筛选出待推导候选答案题目: {len(todo)} 题", flush=True)
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
        futures = {executor.submit(process_question, item, reading_passages, listening_transcripts): item for item in todo}
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
                    'evidence_quote': ans_data.get('evidence_quote', ''),
                    'method': f'{MODEL_NAME}_grounded_candidate_v1',
                    'status': 'candidate_pending_expert_review',
                    'expert_verified': False
                }

                # 填充四段式结构化解析草稿，保留已有出版物 raw
                prev_raw = target_row.get('analysis', {}).get('raw') if isinstance(target_row.get('analysis'), dict) else None
                target_row['analysis'] = {
                    'key_info': ans_data['key_info'],
                    'option_compare': ans_data['option_compare'],
                    'trace_back': ans_data['trace_back'],
                    'explanation': ans_data['explanation'],
                    'raw': prev_raw,
                    'status': 'candidate_draft_pending_expert',
                    'method': f'{MODEL_NAME}_grounded_candidate_v1',
                    'expert_verified': False,
                    'source_note': '原题来源缺失官方答案；本候选答案与解析由学科大模型基于语篇证据链独立推导，待专家终审。'
                }
                target_extra['analysis_status'] = 'candidate_structured_draft'

                updated_files.add(fpath)
                print(f"  [{success_count + fail_count}/{len(todo)}] [成功] {qid} -> 候选答案: {cand_ans}", flush=True)
                if dry_run:
                    print(f"      [证据句]: {ans_data.get('evidence_quote')}", flush=True)
                    print(f"      [选项辨析]: {ans_data.get('option_compare')[:120]}...", flush=True)

                if not dry_run and success_count % 30 == 0:
                    save_updated(updated_files, files_map)
                    print(f"  --> 已增量持久化落盘 {len(updated_files)} 个文件", flush=True)
            else:
                fail_count += 1
                print(f"  [{success_count + fail_count}/{len(todo)}] [失败] {qid}: {res.get('error')}", flush=True)

    if dry_run:
        print(f"\n=== 演示推导完成 (dry-run 未写入文件) ===", flush=True)
        print(f"成功推导: {success_count} 题 | 失败: {fail_count} 题", flush=True)
        return

    print(f"\n正在完成最终原子写入（共 {len(updated_files)} 个题目文件）...", flush=True)
    save_updated(updated_files, files_map)

    print(f"=== 批处理完成 ===", flush=True)
    print(f"成功: {success_count} 题 | 失败: {fail_count} 题 | 更新文件: {len(updated_files)} 个", flush=True)


if __name__ == '__main__':
    main()
