# -*- coding: utf-8 -*-
"""生成四六级标准三段式解析小样并与原始解析进行对比复查。"""
import os
import sys
import json
import urllib.request
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KB_CET = ROOT / '数据集/四六级'

api_key = os.environ.get('DASHSCOPE_API_KEY')
if not api_key:
    print('缺少 DASHSCOPE_API_KEY 环境变量')
    sys.exit(1)

base_url = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'

# 加载阅读语篇
passages = {}
for line in (KB_CET / 'passages/reading.jsonl').open(encoding='utf-8'):
    if line.strip():
        r = json.loads(line)
        passages[r['resource_id']] = r['text']

# 挑选 5 道 CET-4 仔细阅读试题及 3 道听力试题
test_ids = [
    'cet4-2015-06-p1-reading-46',
    'cet4-2015-06-p1-reading-47',
    'cet4-2015-06-p1-reading-48',
    'cet4-2015-06-p1-listening-1',
    'cet4-2015-06-p1-listening-4'
]

test_qs = []
for p in sorted((KB_CET / 'questions').rglob('*.jsonl')):
    for line in p.open(encoding='utf-8'):
        if not line.strip():
            continue
        r = json.loads(line)
        if r['question_id'] in test_ids:
            test_qs.append(r)

print(f'准备为 {len(test_qs)} 道四六级题目生成三段式结构化解析小样...')

results = []
for q in test_qs:
    c = q.get('content', {})
    a = q.get('analysis', {})
    pid = q.get('extra', {}).get('passage_id')
    ptext = passages.get(pid, '')

    prompt = (
        "你是一位资深的大学英语四六级教研专家。请为以下四六级试题撰写标准的三段式结构化解析。\n\n"
        f"【试题背景】\n"
        f"题型: {q.get('question_type')}\n"
    )
    if ptext:
        prompt += f"篇章材料(节选):\n{ptext[:1200]}\n\n"
    prompt += (
        f"题干: {c.get('stem', '')}\n"
        f"选项: {json.dumps(c.get('options', {}), ensure_ascii=False)}\n"
        f"标准答案: {c.get('answer')}\n"
        f"出版物原始解析参考: {a.get('raw', '')[:800]}\n\n"
        "【撰写规范】\n"
        "请严格输出合法 JSON 格式，包含以下四个字段：\n"
        "{\n"
        '  "key_info": "题干关键信息提取（明确考查意图与核心关键词）",\n'
        '  "option_compare": "逐项对比分析（逐一解析A、B、C、D选项为什么对或错，指明干扰项的陷阱设计）",\n'
        '  "trace_back": "考点溯源与定位（定位原文段落/关键句或听力考点，分析推理逻辑）",\n'
        '  "explanation": "总体精析总结（归纳该题的核心做题技巧与结论）"\n'
        "}\n"
    )

    body = json.dumps({
        'model': 'qwen-plus',
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.2,
        'response_format': {'type': 'json_object'}
    }).encode('utf-8')

    req = urllib.request.Request(
        base_url,
        data=body,
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'}
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            content = data['choices'][0]['message']['content']
            parsed = json.loads(content)
            results.append({
                'question_id': q['question_id'],
                'question_type': q['question_type'],
                'stem': c.get('stem'),
                'options': c.get('options'),
                'answer': c.get('answer'),
                'raw_analysis': a.get('raw', '')[:200] + '...' if a.get('raw') else '',
                'structured_analysis': parsed
            })
            print(f"  [成功] {q['question_id']}")
    except Exception as e:
        print(f"  [失败] {q['question_id']}: {e}")
    time.sleep(0.5)

out_file = ROOT / '审查/四六级解析小样复查.json'
out_file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'完成！小样已保存至: {out_file}')
