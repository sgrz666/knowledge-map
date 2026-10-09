"""依据应试考证系统设计规范附录 A.4，生成四六级与教资机器可执行的套卷规格元数据（PaperSpecification）。"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CET_KB = ROOT / "数据集" / "四六级"
NTCE_KB = ROOT / "数据集" / "教资"
sys.path.insert(0, str(CET_KB / "scripts"))
from cet_common import jsonl_dumps, load_jsonl


def generate_cet_paper_specs():
    papers_file = CET_KB / "manifest" / "papers.jsonl"
    papers = load_jsonl(papers_file)
    
    # 建立写译题目索引
    writing_map = {}
    for level in ["cet4", "cet6"]:
        w_file = CET_KB / "questions" / level / "writing.jsonl"
        if w_file.exists():
            for row in load_jsonl(w_file):
                ex = row.get("extra", {})
                writing_map[(row["exam"], ex.get("year"), ex.get("paper"))] = row["question_id"]
                
    trans_map = {}
    for level in ["cet4", "cet6"]:
        t_file = CET_KB / "questions" / level / "translation.jsonl"
        if t_file.exists():
            for row in load_jsonl(t_file):
                ex = row.get("extra", {})
                trans_map[(row["exam"], ex.get("year"), ex.get("paper"))] = row["question_id"]

    specs = []
    for p in papers:
        pid = p["paper_id"]
        exam = p["exam"]
        year = p["year"]
        paper_num = p["paper"]
        level = "cet4" if exam == "CET-4" else "cet6"
        
        q_file = CET_KB / "questions" / level / f"{year}_p{paper_num}.jsonl"
        paper_qids = []
        listening_qids = []
        reading_qids = []
        if q_file.exists():
            for row in load_jsonl(q_file):
                paper_qids.append(row["question_id"])
                if row.get("module") == "听力理解":
                    listening_qids.append(row["question_id"])
                elif row.get("module") == "阅读理解":
                    reading_qids.append(row["question_id"])
                
        w_qid = writing_map.get((exam, year, paper_num))
        t_qid = trans_map.get((exam, year, paper_num))
        
        all_qids = []
        if w_qid:
            all_qids.append(w_qid)
        all_qids.extend(listening_qids)
        all_qids.extend(reading_qids)
        if t_qid:
            all_qids.append(t_qid)
            
        spec = {
            "spec_id": f"spec.{pid}",
            "paper_id": pid,
            "exam": exam,
            "level": level,
            "year": year,
            "paper": paper_num,
            "title": f"{year} {exam} 全真模拟卷（第{paper_num}套）",
            "total_duration_minutes": 130,
            "total_score": 710,
            "passing_score": 425,
            "score_conversion": {
                "type": "norm_referenced_standardized_score",
                "mean": 500,
                "sd": 70,
                "formula": "ReportScore = 500 + 70 * ((RawScore / TotalRawScore * 100 - MeanRaw) / SDRaw)",
                "parameters": {
                    "listening_weight": 0.35,
                    "reading_weight": 0.35,
                    "writing_weight": 0.15,
                    "translation_weight": 0.15
                }
            },
            "parts": [
                {
                    "part_number": 1,
                    "name": "Part I Writing",
                    "module": "写作",
                    "duration_minutes": 30,
                    "score": 106.5,
                    "score_ratio": 0.15,
                    "question_type": "短文写作",
                    "question_ids": [w_qid] if w_qid else [],
                    "question_count": 1 if w_qid else 0,
                    "lock_policy": {
                        "locked_forward": True,
                        "allow_backtrack": False,
                        "auto_submit_on_timeout": True,
                        "sheet_submission": "answer_sheet_1_writing",
                        "description": "30分钟倒计时结束强制保存写作答案，锁定不可修改，不可回退"
                    }
                },
                {
                    "part_number": 2,
                    "name": "Part II Listening Comprehension",
                    "module": "听力理解",
                    "duration_minutes": 25,
                    "score": 248.5,
                    "score_ratio": 0.35,
                    "question_ids": listening_qids,
                    "question_count": len(listening_qids),
                    "lock_policy": {
                        "audio_stream_lock": True,
                        "allow_pause": False,
                        "allow_rewind": False,
                        "auto_submit_on_audio_end": True,
                        "sheet_submission": "answer_sheet_1",
                        "description": "听力音频播放完毕自动提交，模拟收取答题卡1，听力与写作彻底封锁"
                    }
                },
                {
                    "part_number": 3,
                    "name": "Part III Reading Comprehension",
                    "module": "阅读理解",
                    "duration_minutes": 40,
                    "score": 248.5,
                    "score_ratio": 0.35,
                    "question_ids": reading_qids,
                    "question_count": len(reading_qids),
                    "lock_policy": {
                        "sheet_submission": "answer_sheet_2",
                        "description": "阅读理解作答，计入答题卡2"
                    }
                },
                {
                    "part_number": 4,
                    "name": "Part IV Translation",
                    "module": "翻译",
                    "duration_minutes": 30,
                    "score": 106.5,
                    "score_ratio": 0.15,
                    "question_type": "段落翻译",
                    "question_ids": [t_qid] if t_qid else [],
                    "question_count": 1 if t_qid else 0,
                    "lock_policy": {
                        "sheet_submission": "answer_sheet_2",
                        "auto_submit_on_timeout": True,
                        "description": "全卷考试结束，自动提交答题卡2"
                    }
                }
            ],
            "question_ids": all_qids,
            "question_count": len(all_qids)
        }
        specs.append(spec)
        
    out_file = CET_KB / "manifest" / "paper_specs.jsonl"
    out_file.write_text("\n".join(jsonl_dumps(s) for s in specs) + "\n", encoding="utf-8")
    print(f"四六级套卷规格元数据生成完成：共 {len(specs)} 套 -> {out_file.name}")
    return len(specs)


def generate_ntce_paper_specs():
    configs = [
        # 幼儿园
        {"subject_code": "101", "name": "综合素质 (幼儿园)", "level": "youer", "subject": "zonghe", "exam_scope": "笔试科目一",
         "sections": [
             {"name": "单项选择题", "count": 29, "score_each": 2, "total_score": 58, "question_type": "单选"},
             {"name": "材料分析题", "count": 3, "score_each": 14, "total_score": 42, "question_type": "材料分析"},
             {"name": "写作题", "count": 1, "score_each": 50, "total_score": 50, "question_type": "写作"}
         ]},
        {"subject_code": "102", "name": "保教知识与能力", "level": "youer", "subject": "baojiao", "exam_scope": "笔试科目二",
         "sections": [
             {"name": "单项选择题", "count": 10, "score_each": 3, "total_score": 30, "question_type": "单选"},
             {"name": "简答题", "count": 2, "score_each": 15, "total_score": 30, "question_type": "简答"},
             {"name": "论述题", "count": 1, "score_each": 20, "total_score": 20, "question_type": "论述"},
             {"name": "材料分析题", "count": 2, "score_each": 20, "total_score": 40, "question_type": "材料分析"},
             {"name": "活动设计题", "count": 1, "score_each": 30, "total_score": 30, "question_type": "活动设计"}
         ]},
        # 小学
        {"subject_code": "201", "name": "综合素质 (小学)", "level": "xiaoxue", "subject": "zonghe", "exam_scope": "笔试科目一",
         "sections": [
             {"name": "单项选择题", "count": 29, "score_each": 2, "total_score": 58, "question_type": "单选"},
             {"name": "材料分析题", "count": 3, "score_each": 14, "total_score": 42, "question_type": "材料分析"},
             {"name": "写作题", "count": 1, "score_each": 50, "total_score": 50, "question_type": "写作"}
         ]},
        {"subject_code": "202", "name": "教育教学知识与能力", "level": "xiaoxue", "subject": "jiaoxue", "exam_scope": "笔试科目二",
         "sections": [
             {"name": "单项选择题", "count": 20, "score_each": 2, "total_score": 40, "question_type": "单选"},
             {"name": "简答题", "count": 3, "score_each": 10, "total_score": 30, "question_type": "简答"},
             {"name": "材料分析题", "count": 2, "score_each": 20, "total_score": 40, "question_type": "材料分析"},
             {"name": "教学设计题", "count": 1, "score_each": 40, "total_score": 40, "question_type": "教学设计"}
         ]},
        # 中学 (初中/高中通用科目一/科目二)
        {"subject_code": "301", "name": "综合素质 (中学)", "level": "zhongxue", "subject": "zonghe", "exam_scope": "笔试科目一",
         "sections": [
             {"name": "单项选择题", "count": 29, "score_each": 2, "total_score": 58, "question_type": "单选"},
             {"name": "材料分析题", "count": 3, "score_each": 14, "total_score": 42, "question_type": "材料分析"},
             {"name": "写作题", "count": 1, "score_each": 50, "total_score": 50, "question_type": "写作"}
         ]},
        {"subject_code": "302", "name": "教育知识与能力 (中学)", "level": "zhongxue", "subject": "jiaoyuzhishi", "exam_scope": "笔试科目二",
         "sections": [
             {"name": "单项选择题", "count": 21, "score_each": 2, "total_score": 42, "question_type": "单选"},
             {"name": "辨析题", "count": 4, "score_each": 8, "total_score": 32, "question_type": "辨析"},
             {"name": "简答题", "count": 4, "score_each": 10, "total_score": 40, "question_type": "简答"},
             {"name": "材料分析题", "count": 2, "score_each": 18, "total_score": 36, "question_type": "材料分析"}
         ]},
    ]
    
    # 补充初中/高中学科科目三规格
    subject_list = [
        ("yuwen", "语文"), ("shuxue", "数学"), ("yingyu", "英语"), ("wuli", "物理"),
        ("huaxue", "化学"), ("shengwu", "生物"), ("zhengzhi", "思想品德/政治"),
        ("lishi", "历史"), ("dili", "地理"), ("yinyue", "音乐"), ("tiyu", "体育"),
        ("meishu", "美术"), ("xinxi", "信息技术")
    ]
    
    for code_offset, (s_code, s_name) in enumerate(subject_list, 3):
        # 初中
        configs.append({
            "subject_code": f"3{code_offset:02d}",
            "name": f"{s_name}学科知识与教学能力 (初级中学)",
            "level": "chuzhong",
            "subject": s_code,
            "exam_scope": "笔试科目三",
            "sections": [
                {"name": "单项选择题", "count": 15, "score_each": 2, "total_score": 30, "question_type": "单选"},
                {"name": "简答题", "count": 3, "score_each": 10, "total_score": 30, "question_type": "简答"},
                {"name": "材料分析题", "count": 2, "score_each": 20, "total_score": 40, "question_type": "材料分析"},
                {"name": "教学设计题", "count": 1, "score_each": 50, "total_score": 50, "question_type": "教学设计"}
            ]
        })
        # 高中
        configs.append({
            "subject_code": f"4{code_offset:02d}",
            "name": f"{s_name}学科知识与教学能力 (高级中学)",
            "level": "gaozhong",
            "subject": s_code,
            "exam_scope": "笔试科目三",
            "sections": [
                {"name": "单项选择题", "count": 15, "score_each": 2, "total_score": 30, "question_type": "单选"},
                {"name": "简答题", "count": 3, "score_each": 10, "total_score": 30, "question_type": "简答"},
                {"name": "材料分析题", "count": 2, "score_each": 20, "total_score": 40, "question_type": "材料分析"},
                {"name": "教学设计题", "count": 1, "score_each": 50, "total_score": 50, "question_type": "教学设计"}
            ]
        })
        
    specs = []
    for cfg in configs:
        spec = {
            "spec_id": f"spec.ntce.{cfg['level']}.{cfg['subject_code']}",
            "exam": "NTCE",
            "school_level": cfg["level"],
            "subject_code": cfg["subject_code"],
            "subject": cfg["subject"],
            "title": f"教师资格考试模考规格 - {cfg['name']}",
            "total_duration_minutes": 120,
            "total_raw_score": 150,
            "report_score_max": 120,
            "passing_report_score": 70,
            "score_conversion": {
                "type": "criterion_referenced_piecewise_linear",
                "raw_scale": 150,
                "report_scale": 120,
                "passing_raw_threshold": 90,
                "passing_report_score": 70,
                "formula": "if RawScore < 90: ReportScore = (70 / 90) * RawScore; else: ReportScore = 70 + (50 / 60) * (RawScore - 90)",
                "description": "150分制卷面分通过线性分段函数转换为120分报告分，全国统一及格线为70分"
            },
            "sections": cfg["sections"]
        }
        specs.append(spec)
        
    out_file1 = NTCE_KB / "paper_specs.jsonl"
    out_file1.parent.mkdir(parents=True, exist_ok=True)
    out_file1.write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in specs) + "\n", encoding="utf-8")
    
    print(f"教资套卷规格元数据生成完成：共 {len(specs)} 科目规格 -> {out_file1}")
    return len(specs)


if __name__ == "__main__":
    generate_cet_paper_specs()
    generate_ntce_paper_specs()
