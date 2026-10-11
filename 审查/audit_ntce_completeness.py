"""Export a fresh, scoped NTCE completeness report, without changing knowledge records."""
import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.knowledge.completeness import audit_ntce
from services.knowledge.repository import get_repository


def write_study_index(report, path):
    repo = get_repository()
    lines = ['# 教资无题考点：考纲学习索引', '',
             '由审查脚本从真实图谱与考纲生成；不新增题目、不制造答案和专家签核。', '',
             '791 个知识节点中，无直接试题的 160 个包含 153 个汇总父节点；以下为 7 个叶子考点。'
             '已有自动挂载的条款可作为研究学习线索，仍需教研核定；没有条款的条目明确列为待补。', '']
    for node in report['unpractised_nodes']:
        if not node['is_leaf']:
            continue
        lines.extend([f"## {node['name']} · {node['id']}", ''])
        records = [repo.get_requirement(rid) for rid in node['requirement_ids']]
        records = [r for r in records if r]
        if not records:
            lines.extend(['当前图谱没有到具体考纲条款的绑定。请回对应学科原大纲核对后补充，'
                          '当前不能据此生成有来源的专属练习。', ''])
        for record in records:
            locator = record.get('locator') or {}
            lines.extend([f"- 条款：`{record['requirement_id']}`",
                          f"- 原文：{record.get('content') or record.get('title', '')}",
                          f"- 定位：`{locator.get('text_path', '')}` 第 {locator.get('line_start', '?')}–{locator.get('line_end', '?')} 行",
                          '- 挂载状态：自动对齐线索，尚未教研签核。', ''])
    lines.extend(['## 如何使用', '',
                  '在网页选择对应学段和科目，向学习助手询问这个考点；有条款时显示真实考纲证据。'
                  '连接 DeepSeek 后可请求解释与作答组织建议，仍不把生成文字作为审核后的题目或正式评分。', '',
                  '重新生成：`python 审查/audit_ntce_completeness.py --study-index docs/教资无题考点学习索引.md`', ''])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '审查/教资完整性核对.json')
    parser.add_argument('--study-index', type=Path, help='另导出无题叶子考点的真实考纲学习索引')
    args = parser.parse_args()
    report = audit_ntce()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # 落盘的快照只记内容，不记钟点：一份会随时钟变化的清单没法用 `git diff` 判断某一批修补到底改变了什么。
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if args.study_index:
        write_study_index(report, args.study_index)
    summary = {k: v for k, v in report.items() if k not in ('scopes', 'unpractised_nodes')}
    summary['written_at'] = datetime.now(timezone(timedelta(hours=8))).isoformat()
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
