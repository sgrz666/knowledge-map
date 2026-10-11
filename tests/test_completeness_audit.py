"""完整性快照是库内容的函数：重跑不改一个字节，落盘那份不许落后于库。

修补按批次进行时，唯一的进度证据就是这份快照的差异。快照里只要掺进钟点，
每批重跑都会显示"文件变了"，也就没人能靠 diff 判断这一批到底补掉了哪几格。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.knowledge.completeness import audit_ntce

SNAPSHOT = ROOT / '审查' / '教资完整性核对.json'


def render(report):
    return json.dumps(report, ensure_ascii=False, indent=2)


def test_audit_output_carries_no_clock():
    assert 'generated_at' not in audit_ntce()


def test_rerunning_the_audit_changes_nothing():
    assert render(audit_ntce()) == render(audit_ntce())


def test_committed_snapshot_is_reproducible_from_the_library():
    assert SNAPSHOT.read_text(encoding='utf-8') == render(audit_ntce())
