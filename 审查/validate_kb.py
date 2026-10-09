"""全库数据验收：结构错误与待补内容分开统计，两者均不冒充完整验收通过。"""
import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict, deque
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUBJECTIVE = {"简答", "材料分析", "教学设计", "活动设计", "论述", "写作", "辨析", "诊断", "解答", "结构化问答", "试讲", "短文写作", "段落汉译英"}
CHOICE_TYPES = {"单选", "多选"}
# 附录 A.6 的可计算量规只认 dimension_name/weight_score/criteria_levels；name/levels/max_level 是题内练习框架的字段。
# 同一维度同时带两套字段就是双真相：消费端取哪一份就会得到哪种分数与档位。
RUBRIC_LEGACY_DIM_KEYS = {"name", "levels", "max_level"}
RUBRIC_WEIGHTED_DIM_KEYS = {"dimension_name", "weight_score", "criteria_levels"}
REVIEWED = {"checked", "expert_reviewed", "expert", "专家审核", "已审核", "人工审核通过"}
# 附录 A.1 的存储层词表：任何越界取值都是结构性错误，而不是可接受的待办状态。
REVIEW_STATES = {"auto_parsed", "llm_enhanced", "checked", "expert_reviewed", "needs_fix", "quarantined"}
ANSWER_STATES = {"verified", "letter_only", "reference_only", "missing", "source_conflict"}
RESEARCH_USE_SCOPES = {"research_non_commercial"}
ANSWER_BLOCKING_RULES = {"Q_ANSWER_MISSING", "Q_ANSWER_INVALID", "Q_ANSWER_SOURCE_CONFLICT",
                         "Q_ANSWER_IDENTITY_MISMATCH", "Q_ANSWER_BINDING_PENDING", "Q_ANSWER_SOURCE_UNLOCATED"}
NTCE_SUBJECT_TERMS = {
    "zonghe": "综合素质", "baojiao": "保教", "jiaoxue": "教育教学", "jiaoyuzhishi": "教育知识", "mianshi": "面试",
    "yuwen": "语文", "shuxue": "数学", "yingyu": "英语", "zhengzhi": ("政治", "思想品德", "道德与法治"), "lishi": "历史", "dili": "地理",
    "wuli": "物理", "huaxue": "化学", "shengwu": "生物", "meishu": "美术", "yinyue": "音乐", "tiyu": "体育", "xinxi": "信息",
}
NTCE_LEVEL_SCOPE = {
    "youer": {"youer", "幼儿", "幼儿园"}, "xiaoxue": {"xiaoxue", "小学"},
    "chuzhong": {"chuzhong", "初中", "初级中学", "中学", "zhongxue"},
    "gaozhong": {"gaozhong", "高中", "高级中学", "中学", "zhongxue"},
    "zhongxue": {"zhongxue", "中学", "初中", "初级中学", "高中", "高级中学"},
    "zhongxiaoxue": {"zhongxiaoxue", "中小学", "zhongxue", "中学", "xiaoxue", "小学", "初级中学", "高级中学"},
}


def nonempty(value):
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None and value != [] and value != {}


def substantive_text(value, reject_letters=False):
    if not nonempty(value):
        return False
    if not isinstance(value, str):
        return False  # 状态对象、来源元数据和数字不是答案或解析正文。
    text = re.sub(r"[\s。．.!！,，;；:：、\u200b-\u200f\u2060\ufeff]+", "", value)
    if not text or re.fullmatch(r"\*{4,}", text):
        return False
    if text in {"缺", "略", "无", "暂无", "暂缺", "参见解析", "见解析", "答案略", "解析略", "待补", "待补充"}:
        return False
    return not (reject_letters and re.fullmatch(r"[A-O]+", text, re.I))


def usable_answer_field(record, issues):
    extra = record.get("extra") or {}
    return extra.get("active") is not False and extra.get("scoring_eligible") is not False and substantive_text((record.get("content") or {}).get("answer"), reject_letters=record.get("question_type") in SUBJECTIVE) and not any(i["rule"] in ANSWER_BLOCKING_RULES for i in issues)


def difficulty_is_calibrated(record):
    extra = record.get("extra") or {}
    metadata = record.get("difficulty_calibration") or extra.get("difficulty_metadata") or {}
    method = record.get("difficulty_method") or extra.get("difficulty_method") or metadata.get("method")
    if not method or method in {"heuristic", "estimated", "规则估计", "llm", "ai"}:
        return False
    if pending_review(metadata.get("status")) or metadata.get("status") in {"draft", "proposed", "estimated"}:
        return False
    return bool(metadata.get("evidence") or metadata.get("report_path") or
                (metadata.get("sample_count", 0) and metadata.get("response_dataset")) or
                (metadata.get("reviewer") and metadata.get("reviewed_at")))


def pending_review(status):
    value = str(status or "").lower()
    return "pending" in value or value in {"待审核", "待复核", "待专家审核"}


def cet_requirement_module(requirement):
    aliases = {"听力": "听力理解", "听力理解": "听力理解", "阅读": "阅读理解", "阅读理解": "阅读理解", "写作": "写作", "翻译": "翻译"}
    module = requirement.get("module")
    if module in aliases:
        return aliases[module]
    if module == "试卷结构":
        title = requirement.get("title", "")
        found = {value for term, value in aliases.items() if term in title}
        if len(found) == 1:
            return found.pop()
    return None


def json_rows(paths, failures):
    result = []
    for path in sorted(paths):
        with path.open(encoding="utf-8-sig") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    if not isinstance(data, dict):
                        raise ValueError("record must be an object")
                    result.append((data, path, line_number))
                except ValueError as exc:
                    failures.append({"rule": "JSON_INVALID", "severity": "error", "file": str(path.relative_to(ROOT)), "line": line_number, "detail": str(exc)})
    return result


@lru_cache(maxsize=50000)
def resolve_file(value, base_paths):
    if not isinstance(value, str) or not value or "..." in value or ";" in value:
        return None
    if value.startswith(("https://", "http://")):
        return None  # URL 是来源线索，不能替代本地文件存在性检查。
    path = Path(value.replace("\\", "/"))
    for base in base_paths:
        candidate = Path(base) / path
        if candidate.is_file():
            return candidate
    return None


def source_files(source):
    entries = source.get("files") or source.get("sources") or []
    result = []
    for item in entries if isinstance(entries, list) else []:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict):
            value = item.get("path") or item.get("local_path") or item.get("origin_file")
            if value:
                result.append(value)
    if not result and source.get("origin_file"):
        result.append(source["origin_file"])
    return result


@lru_cache(maxsize=3000)
def cached_file_hash(path, modified_ns, size):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def file_hash(path):
    stat = path.stat()
    return cached_file_hash(str(path), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=1000)
def physical_text_lines(path):
    return Path(path).read_text(encoding="utf-8-sig").split("\n")


def inspect_source_evidence(source, roots):
    issues = []
    entries = source.get("files") or source.get("sources") or []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        path = resolve_file(entry.get("path") or entry.get("local_path") or entry.get("origin_file"), roots)
        if path is None:
            continue  # 存在性由独立规则报告。
        if entry.get("sha256") and file_hash(path) != str(entry["sha256"]).lower():
            issues.append({"rule": "Q_SOURCE_HASH_MISMATCH", "severity": "error", "detail": f"题目来源文件哈希与记录不一致：{entry.get('path')}"})
        locator = entry.get("locator") or {}
        if not locator.get("context_sha256"):
            continue
        try:
            if locator.get("line_convention") != "physical_LF":
                raise ValueError("区间哈希需要明确LF物理行定位约定")
            start, end = locator.get("line_start"), locator.get("line_end")
            if any(isinstance(value, bool) or not isinstance(value, int) for value in (start, end)) or not 1 <= start <= end:
                raise ValueError("原文区间行号无效")
            lines = physical_text_lines(str(path))
            if end > len(lines):
                raise ValueError("原文区间超出物理行范围")
            digest = hashlib.sha256("\n".join(lines[start - 1:end]).encode("utf-8")).hexdigest()
            if digest != locator["context_sha256"]:
                issues.append({"rule": "Q_SOURCE_CONTEXT_MISMATCH", "severity": "error", "detail": "引用原文区间与记录哈希不一致，检查行号约定或源文变化"})
        except (UnicodeError, ValueError, TypeError) as exc:
            issues.append({"rule": "Q_SOURCE_CONTEXT_INVALID", "severity": "error", "detail": str(exc)})
    return issues


def option_keys(options, require_text=True):
    if isinstance(options, dict):
        return {key for key, text in options.items() if not require_text or substantive_text(text)}
    if isinstance(options, list):
        return {item.get("key") for item in options if isinstance(item, dict) and item.get("key") and (not require_text or substantive_text(item.get("text")))}
    return set()


def paper_identity(record):
    source, extra = record.get("source") or {}, record.get("extra") or {}
    year = source.get("year") or extra.get("year") or record.get("year")
    paper = source.get("paper") or extra.get("paper") or record.get("paper")
    ordinal = {"一": "1", "二": "2", "三": "3", "四": "4"}
    if paper is not None:
        paper = re.sub(r"[第套卷\s]", "", str(paper))
        paper = ordinal.get(paper, paper)
    return {"exam": record.get("exam"), "year": year, "paper": paper}


def inspect_answer_binding(record, roots):
    """只识别可机械证明的矛盾；有文件/正确哈希不等于答案已绑定当前题。"""
    issues = []
    source, extra, content = record.get("source") or {}, record.get("extra") or {}, record.get("content") or {}
    if not substantive_text(content.get("answer"), reject_letters=record.get("question_type") in SUBJECTIVE):
        return issues
    roles = {"answer_analysis", "answer_raw", "answer_key", "reference_answer", "official_answer", "original_answer"}
    entries = [e for e in source.get("files") or [] if isinstance(e, dict) and e.get("role") in roles and resolve_file(e.get("path"), roots)]
    generated = str(content.get("answer_status") or extra.get("answer_status") or "")
    analysis = record.get("analysis") or {}
    if "draft" in generated and isinstance(analysis, dict) and analysis.get("generation"):
        return issues  # 原创草稿依靠生成记录与内容复核，不能冒充公布答案。
    if not entries:
        return [{"rule": "Q_ANSWER_SOURCE_UNLOCATED", "severity": "gap", "detail": "有效答案缺少可定位的答案来源角色，不能用原题文件代替答案证据"}]
    number = extra.get("source_question_number") or extra.get("number") or record.get("question_number")
    identity = paper_identity(record)
    bound = False
    for entry in entries:
        locator = entry.get("locator") or {}
        located_number = locator.get("question_number") or locator.get("source_question_number")
        if number is not None and located_number is not None:
            if str(number) != str(located_number):
                issues.append({"rule": "Q_ANSWER_IDENTITY_MISMATCH", "severity": "error", "detail": f"答案定位题号{located_number}与本题原始题号{number}不一致"})
            else:
                bound = True
        located = paper_identity({"exam": entry.get("exam"), "source": locator})
        for field in ("exam", "year", "paper"):
            if identity[field] is not None and located[field] is not None and str(identity[field]) != str(located[field]):
                issues.append({"rule": "Q_ANSWER_IDENTITY_MISMATCH", "severity": "error", "detail": f"答案来源{field}与本题试卷身份不一致"})
    if not bound:
        issues.append({"rule": "Q_ANSWER_BINDING_PENDING", "severity": "gap", "detail": "答案来源未提供可核对的本题题号绑定；区间哈希不能代替题目身份核对"})
    return issues


@lru_cache(maxsize=1000)
def text_lines(path):
    return Path(path).read_text(encoding="utf-8-sig").splitlines()


@lru_cache(maxsize=1000)
def json_document(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def json_pointer(document, pointer):
    if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")):
        raise ValueError("JSON Pointer 必须为空或以斜杠开头")
    value = document
    for token in pointer.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not token.isdigit() or (len(token) > 1 and token.startswith("0")):
                raise ValueError("JSON 数组索引不合法")
            value = value[int(token)]
        else:
            value = value[token]
    return value


class SourceTableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.table = None
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "table":
            self.table = []
            self.tables.append(self.table)
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in {"td", "th"} and self.row is not None:
            self.cell = {"text": [], "rowspan": int(attributes.get("rowspan", 1)), "colspan": int(attributes.get("colspan", 1))}

    def handle_data(self, data):
        if self.cell is not None:
            self.cell["text"].append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.cell is not None:
            self.cell["text"] = "".join(self.cell["text"]).strip()
            self.row.append(self.cell)
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table":
            self.table = None


@lru_cache(maxsize=1000)
def html_table_rows(path, table_number):
    parser = SourceTableParser()
    parser.feed(Path(path).read_text(encoding="utf-8-sig"))
    raw_rows = parser.tables[table_number - 1]
    carry, expanded = {}, []
    for raw in raw_rows:
        values = {column: value for column, (value, _) in carry.items()}
        future = {column: (value, remaining - 1) for column, (value, remaining) in carry.items() if remaining > 1}
        column = 0
        for cell in raw:
            while column in values:
                column += 1
            for offset in range(cell["colspan"]):
                values[column + offset] = cell["text"]
                if cell["rowspan"] > 1:
                    future[column + offset] = (cell["text"], cell["rowspan"] - 1)
            column += cell["colspan"]
        expanded.append([values.get(i, "") for i in range(max(values, default=-1) + 1)])
        carry = future
    return expanded


def inspect_requirement(requirement, base_paths):
    issues = []

    def add(rule, detail, severity="gap"):
        issues.append({"rule": rule, "severity": severity, "detail": detail})

    content = str(requirement.get("content") or "").strip()
    if not content or re.fullmatch(r"[\d\s.,，%％分钟小时分题个秒—–/-]+", content):
        add("REQUIREMENT_CONTENT_FRAGMENT", "孤立数字或计量单位不能作为自包含考试要求")
    locator = requirement.get("locator")
    if not isinstance(locator, dict):
        add("REQUIREMENT_LOCATOR_UNINSPECTABLE", "条目定位未结构化，无法校验原文")
        return issues
    roots = tuple(str(p) for p in base_paths)
    if locator.get("json_path"):
        path = resolve_file(locator["json_path"], roots)
        if path is None:
            add("REQUIREMENT_TEXT_FILE_MISSING", "条目定位的官方JSON原文不存在")
            return issues
        try:
            document = json_document(str(path))
            pointer = locator["json_pointer"]
            original = json_pointer(document, pointer)
            quoted = requirement.get("original_text") or requirement.get("quote") or content
            if not isinstance(original, str) or str(quoted).replace("\r\n", "\n") != original.replace("\r\n", "\n"):
                add("REQUIREMENT_CONTENT_NOT_AT_LOCATOR", "能力描述与官方JSON定位的原文不一致", "error")
            if "official_descriptor_id" in locator:
                parent = json_pointer(document, pointer.rsplit("/", 1)[0])
                if not isinstance(parent, dict) or parent.get("id") != locator["official_descriptor_id"]:
                    add("REQUIREMENT_DESCRIPTOR_ID_MISMATCH", "能力描述ID与官方JSON记录不一致", "error")
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            add("REQUIREMENT_JSON_LOCATOR_INVALID", str(exc), "error")
        return issues
    if locator.get("html_path"):
        path = resolve_file(locator["html_path"], roots)
        if path is None:
            add("REQUIREMENT_TEXT_FILE_MISSING", "条目定位的HTML原文不存在")
            return issues
        try:
            for field in ("table", "row"):
                if isinstance(locator.get(field), bool) or not isinstance(locator.get(field), int) or locator[field] < 1:
                    raise ValueError("表格及行定位必须为从1开始的正整数")
            values = html_table_rows(str(path), locator["table"])[locator["row"] - 1]
            exam = requirement.get("exam_scope", [""])[0]
            if len(values) != 6:
                raise ValueError("CET考试结构表应有六个字段")
            if values[0] == "总计":
                expected = f"{exam}：题数总计{values[3]}；总分值比例{values[4]}；总考试时间{values[5]}。"
            else:
                expected = f"{exam}：试卷部分{values[0]}；测试内容{values[1]}；题型{values[2]}；题数{values[3]}；分值比例{values[4]}；考试时间{values[5]}。"
            if re.sub(r"\s+", "", content) != re.sub(r"\s+", "", expected):
                add("REQUIREMENT_CONTENT_NOT_AT_LOCATOR", "表格要求的题型/分值/时间与所定位原文行不一致", "error")
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            add("REQUIREMENT_TABLE_LOCATOR_INVALID", str(exc), "error")
        return issues
    if locator.get("table_path"):
        path = resolve_file(locator["table_path"], roots)
        if path is None:
            add("REQUIREMENT_TEXT_FILE_MISSING", "条目定位的Word表格文本不存在")
            return issues
        tables = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(tables, dict):
            tables = [tables]
        cells = [cell for table in tables if table.get("table") == locator.get("table") for cell in table.get("cells", []) if cell.get("row") == locator.get("row") and cell.get("column") == locator.get("column")]
        normalize = lambda value: re.sub(r"\s+", "", str(value))
        if not cells or not any(normalize(content) == normalize(cell.get("text", "")) for cell in cells):
            add("REQUIREMENT_CONTENT_NOT_AT_LOCATOR", "评分条目与Word表格定位单元格不一致", "error")
        return issues
    path = resolve_file(locator.get("text_path"), roots)
    if path is None:
        add("REQUIREMENT_TEXT_FILE_MISSING", "条目定位的原文文本不存在")
        return issues
    start, end = locator.get("line_start"), locator.get("line_end")
    if not isinstance(start, int) or not isinstance(end, int) or not 1 <= start <= end:
        add("REQUIREMENT_LINE_RANGE_INVALID", "条目定位行号不合法", "error")
        return issues
    lines = text_lines(str(path))
    if end > len(lines):
        add("REQUIREMENT_LINE_RANGE_INVALID", "条目定位超出原文行数", "error")
        return issues
    original = "\n".join(lines[start - 1:end])
    quoted = requirement.get("original_text") or requirement.get("quote") or content
    normalized = lambda value: re.sub(r"\s+", "", str(value))
    if normalized(quoted) not in normalized(original):
        add("REQUIREMENT_CONTENT_NOT_AT_LOCATOR", "声明的原文不出现在定位范围内；归纳描述应另存原文引用", "error")
    return issues


def rubric_shape_issues(rubric):
    """量规形状门禁：题内练习框架与附录 A.6 可计算量规不得混写，未经署名的专家声称不得存在。"""
    issues = []
    if not isinstance(rubric, dict):
        return issues
    review = rubric.get("review") if isinstance(rubric.get("review"), dict) else {}
    if rubric.get("expert_verified") is True and not (rubric.get("checked_by") or review.get("checked_by")):
        issues.append(("Q_RUBRIC_EXPERT_CLAIM", "量规标为 expert_verified 却没有具名审核人，自动生成不得声称已核", "error"))
    for index, dimension in enumerate(rubric.get("dimensions") or []):
        if not isinstance(dimension, dict):
            continue
        keys = set(dimension)
        if keys & RUBRIC_LEGACY_DIM_KEYS and keys & RUBRIC_WEIGHTED_DIM_KEYS:
            issues.append(("Q_RUBRIC_DUAL_TRUTH", f"第{index + 1}个维度同时带 name/levels/max_level 与 A.6 加权字段，取哪一份就会得到哪种分数", "error"))
    return issues


def inspect_question(record, context):
    issues = []

    def add(rule, detail, severity="gap"):
        issues.append({"rule": rule, "severity": severity, "detail": detail})

    content = record.get("content") or {}
    extra = record.get("extra") or {}
    source = record.get("source") or {}
    knowledge_ids = record.get("knowledge_node_ids") or []
    ability_ids = record.get("ability_ids") or []
    requirement_ids = record.get("exam_requirement_ids") or []
    question_type = record.get("question_type")
    module = record.get("module")
    qid = record.get("question_id")
    if not nonempty(qid):
        add("Q_ID_MISSING", "题目缺少唯一ID", "error")
    if not question_type or question_type in {"未标注", "未知", "待核", "unknown"}:
        add("Q_TYPE_UNVERIFIED", "题型尚未根据当前题目原文确认")
    if (extra.get("source_discovery") or {}).get("status") == "parser_artifact_outside_CET_number_range":
        add("Q_PARSER_ARTIFACT_INACTIVE", "编号解析产生的伪题保留历史ID，已停用，不能计作真实补充试题或用于判分")
    if not knowledge_ids:
        add("Q_KNOWLEDGE_MISSING", "题目未绑定知识点")
    knowledge = context.get("knowledge", {})
    expected_abilities = set()
    expected_requirements = set()
    pending_alignment = False
    for node_id in knowledge_ids:
        node = knowledge.get(node_id)
        if node is None:
            add("Q_KNOWLEDGE_DANGLING", f"知识点不存在：{node_id}", "error")
            continue
        expected_abilities.update(node.get("ability_ids") or context.get("node_abilities", {}).get(node_id, []))
        expected_requirements.update(node.get("exam_requirement_ids") or [])
        pending_alignment |= pending_review(node.get("mapping_status"))
        if node.get("assessable") is False or node_id in {"cet4.read", "cet4.listen", "cet6.read", "cet6.listen"} or node.get("granularity") in {"module", "subject_root"}:
            add("Q_KNOWLEDGE_TOO_BROAD", f"模块根节点不能替代具体考点：{node_id}")
        if context.get("dataset") == "cet":
            if module and node.get("module") and node["module"] != module and node["module"] != "词汇语法":
                add("Q_MODULE_MISMATCH", f"题目模块{module}与知识点模块{node['module']}不相容", "error")
            if node.get("exam") and record.get("exam") and node["exam"] != record["exam"]:
                add("Q_EXAM_MISMATCH", "题目考试与知识点考试不一致", "error")
        elif context.get("dataset") == "ntce":
            namespace = "shengkao" if record.get("exam") == "省考" else "ntce"
            expected_prefix = f"{namespace}.{record.get('level')}.{record.get('subject')}."
            if record.get("level") and record.get("subject") and not node_id.startswith(expected_prefix):
                add("Q_SUBJECT_MISMATCH", "知识点不属于题目的学段科目", "error")
    if not ability_ids:
        add("Q_ABILITY_MISSING", "题目没有能力映射")
    for ability_id in ability_ids:
        if ability_id not in context.get("abilities", {}):
            add("Q_ABILITY_DANGLING", f"能力ID不存在：{ability_id}", "error")
    if ability_ids and expected_abilities and not set(ability_ids).issubset(expected_abilities):
        add("Q_ABILITY_MISMATCH", "题目的能力标签与绑定知识点的能力映射不一致", "error")
    if not requirement_ids:
        add("Q_REQUIREMENT_MISSING", "缺少具体考试要求条目")
    for requirement_id in requirement_ids:
        requirement = context.get("requirements", {}).get(requirement_id)
        if requirement is None:
            add("Q_REQUIREMENT_DANGLING", f"考试要求条目不存在：{requirement_id}", "error")
            continue
        standard = context.get("standards", {}).get(requirement.get("standard_id"), {})
        scope = requirement.get("exam_scope") or standard.get("exam_scope") or []
        if isinstance(scope, str):
            scope = [scope]
        cet_scope = set(scope).intersection({"CET-4", "CET-6"})
        level = requirement.get("level") or []
        if isinstance(level, str):
            level = [level]
        exact_level = set(level).intersection({"CET-4", "CET-6"})
        if exact_level:
            cet_scope = exact_level
        if cet_scope and record.get("exam") in {"CET-4", "CET-6"} and record["exam"] not in cet_scope:
            add("Q_REQUIREMENT_SCOPE_MISMATCH", "引用了另一个考试的要求条目", "error")
        standard_id = requirement.get("standard_id", "")
        if (context.get("dataset") == "cet" and standard_id.startswith("ntce.")) or (context.get("dataset") == "ntce" and standard_id.startswith("cet.")):
            add("Q_REQUIREMENT_SCOPE_MISMATCH", "引用了另一类考试的要求条目", "error")
        if context.get("dataset") == "cet" and standard_id.startswith("cet."):
            required_module = cet_requirement_module(requirement)
            if module in {"听力理解", "阅读理解", "写作", "翻译"} and required_module and required_module != module:
                add("Q_REQUIREMENT_MODULE_MISMATCH", f"题目模块{module}不能直接测量{required_module}的考试要求", "error")
        if context.get("dataset") == "ntce" and requirement.get("standard_id", "").startswith("ntce."):
            requirement_subject = requirement.get("subject")
            subject = record.get("subject")
            term = NTCE_SUBJECT_TERMS.get(subject)
            terms = (term,) if isinstance(term, str) else term
            if requirement_subject and terms and requirement_subject != subject and not any(t in requirement_subject for t in terms):
                add("Q_REQUIREMENT_SCOPE_MISMATCH", "引用了另一个学科的考试要求条目", "error")
            requirement_level = requirement.get("level")
            allowed_levels = NTCE_LEVEL_SCOPE.get(record.get("level"))
            if requirement_level and allowed_levels and not set(level).intersection(allowed_levels):
                add("Q_REQUIREMENT_SCOPE_MISMATCH", "引用了另一个学段的考试要求条目", "error")
    if requirement_ids and expected_requirements and not set(requirement_ids).intersection(expected_requirements):
        add("Q_REQUIREMENT_MISMATCH", "题目与知识点的考试要求映射没有交集", "error")
    if expected_requirements and set(requirement_ids) - expected_requirements:
        add("Q_REQUIREMENT_BINDING_UNSUPPORTED", "题目额外引用了绑定知识点映射以外的条款，需提供独立映射证据")
    paths = source_files(source)
    base_paths = tuple(str(p) for p in context.get("base_paths", []))
    if not paths or not any(resolve_file(p, base_paths) for p in paths):
        add("Q_SOURCE_UNRESOLVED", "原题来源不能定位到本地文件")
    elif any(not resolve_file(p, base_paths) for p in paths):
        add("Q_SOURCE_PARTIALLY_UNRESOLVED", "多文件来源中有无法定位的引用")
    issues.extend(inspect_source_evidence(source, base_paths))
    issues.extend(inspect_answer_binding(record, base_paths))
    copyright_info = record.get("copyright") or source.get("copyright") or extra.get("copyright") or {}
    use_scope = copyright_info.get("use_scope")
    authorization = copyright_info.get("authorization_status")
    if authorization in {"authorized", "public_domain"} and not (copyright_info.get("evidence") or copyright_info.get("holder")):
        add("Q_COPYRIGHT_CLAIM_UNSUPPORTED", "声称已授权或公有领域但没有权利人及授权证据，只能记为 unknown", "error")
    if not use_scope:
        add("Q_COPYRIGHT_UNRESOLVED", "来源没有声明使用范围，按科研非商业边界需显式标注 research_non_commercial")
    elif use_scope not in RESEARCH_USE_SCOPES:
        add("Q_COPYRIGHT_SCOPE_OUT_OF_BOUNDS", f"使用范围“{use_scope}”超出科研非商业边界，需重新清权", "error")
    material_id = record.get("material_id")
    if material_id and material_id not in context.get("materials", {}):
        add("Q_MATERIAL_DANGLING", "材料引用不存在", "error")
    passage_id = extra.get("passage_id")
    passage = context.get("passages", {}).get(passage_id)
    if passage_id and passage is None:
        add("Q_PASSAGE_DANGLING", "语篇引用不存在", "error")
    if passage_id and passage is not None and not (nonempty(passage.get("text")) or nonempty(passage.get("content"))):
        add("Q_PASSAGE_EMPTY", "关联语篇正文为空")
    if passage:
        question_identity, passage_identity = paper_identity(record), paper_identity(passage)
        if any(question_identity[field] is not None and passage_identity[field] is not None and
               str(question_identity[field]) != str(passage_identity[field]) for field in ("exam", "year", "paper")):
            add("Q_PASSAGE_IDENTITY_MISMATCH", "关联语篇的考试、年月或卷别与题目不一致", "error")
        backlinks = passage.get("question_ids", (passage.get("extra") or {}).get("question_ids"))
        if backlinks is not None and (not isinstance(backlinks, list) or qid not in backlinks):
            add("Q_PASSAGE_IDENTITY_MISMATCH", "语篇已列出的关联题目不包含当前题目", "error")
    for transcript_id in extra.get("listening_transcript_ids") or []:
        transcript = context.get("transcripts", {}).get(transcript_id)
        if transcript is None:
            add("Q_TRANSCRIPT_DANGLING", f"听力文字稿引用不存在：{transcript_id}", "error")
            continue
        if not substantive_text(transcript.get("text")):
            add("Q_TRANSCRIPT_EMPTY", "引用的听力文字稿正文为空")
        original, linked = paper_identity(record), paper_identity(transcript)
        number = extra.get("source_question_number") or extra.get("number")
        numbers = (transcript.get("extra") or {}).get("question_numbers") or []
        if any(original[field] is not None and linked[field] is not None and str(original[field]) != str(linked[field])
               for field in ("exam", "year", "paper")) or (number is not None and str(number) not in {str(n) for n in numbers}):
            add("Q_TRANSCRIPT_IDENTITY_MISMATCH", "听力文字稿所属试卷或题组范围与本题不一致", "error")
    if context.get("dataset") == "cet" and question_type in {"仔细阅读", "长篇阅读", "选词填空"} and not (passage or content.get("passage") or extra.get("passage")):
        add("Q_PASSAGE_UNLINKED", "阅读题没有关联原文语篇")
    if not substantive_text(content.get("stem")) and module != "听力理解" and not (question_type == "选词填空" and passage):
        add("Q_STEM_EMPTY", "缺少当前题目的具体任务；阅读语篇不能代替仔细阅读题干")
    answer = content.get("answer")
    if not substantive_text(answer, reject_letters=question_type in SUBJECTIVE):
        add("Q_ANSWER_MISSING", "没有可判分的答案正文")
    if "source_conflict" in {content.get("answer_status"), extra.get("answer_status")}:
        add("Q_ANSWER_SOURCE_CONFLICT", "答案来源存在冲突，尚不能用于判分")
    keys = option_keys(content.get("options"), require_text=False)
    text_keys = option_keys(content.get("options"))
    if not keys and passage:
        keys = option_keys(passage.get("extra", {}).get("word_bank"), require_text=False)
        text_keys = option_keys(passage.get("extra", {}).get("word_bank"))
    if isinstance(answer, str) and re.fullmatch(r"[A-Z]", answer.strip()):
        if (keys and answer.strip() not in keys) or (module == "听力理解" and answer.strip() not in {"A", "B", "C", "D"}):
            add("Q_ANSWER_INVALID", "答案不在该题合法选项中", "error")
    if question_type in {"单选", "仔细阅读", "短篇新闻", "长对话", "听力篇章", "讲座/讲话", "选词填空", "长篇阅读"} and substantive_text(answer):
        if not isinstance(answer, str) or not re.fullmatch(r"[A-Z]", answer.strip()):
            add("Q_ANSWER_INVALID", "单选或匹配题答案必须为一个合法选项字母", "error")
    if question_type in {"单选", "多选", "仔细阅读", "短篇新闻", "长对话", "听力篇章", "讲座/讲话"} and not set("ABCD").issubset(text_keys):
        add("Q_OPTIONS_INCOMPLETE", "四选项客观题缺少完整的A至D选项")
    if question_type == "选词填空" and not set("ABCDEFGHIJKLMNO").issubset(text_keys):
        add("Q_OPTIONS_INCOMPLETE", "选词填空缺少完整的A至O共享词库")
    analysis = record.get("analysis") or content.get("analysis")
    if isinstance(analysis, dict):
        parts = ("key_info", "option_compare", "trace_back")
        if not all(substantive_text(analysis.get(k), reject_letters=True) for k in parts):
            add("Q_ANALYSIS_INCOMPLETE", "结构化解析缺少参考schema中的必要段落")
    elif not substantive_text(analysis, reject_letters=True):
        add("Q_ANALYSIS_MISSING", "没有逐题解析正文")
    else:
        add("Q_ANALYSIS_UNSTRUCTURED", "解析尚未转成结构化字段")
    difficulty = record.get("difficulty")
    if difficulty is None:
        add("Q_DIFFICULTY_MISSING", "没有难度标注或校准")
    elif isinstance(difficulty, bool) or not isinstance(difficulty, (int, float)) or not 0 <= difficulty <= 1:
        add("Q_DIFFICULTY_INVALID", "难度不符合0到1数值范围", "error")
    elif not difficulty_is_calibrated(record):
        add("Q_DIFFICULTY_UNCALIBRATED", "难度缺少教研标定或实测校准的方法及证据")
    rubric = record.get("rubric") or extra.get("rubric") or extra.get("scoring_rubric")
    rubric_id = record.get("rubric_id") or extra.get("rubric_id")
    if question_type in SUBJECTIVE:
        if rubric_id and not rubric:
            rubric = context.get("rubrics", {}).get(rubric_id)
            if rubric is None:
                add("Q_RUBRIC_DANGLING", f"评分量规ID不存在：{rubric_id}", "error")
        if not isinstance(rubric, dict) or not (rubric.get("dimensions") or rubric.get("criteria") or (rubric.get("bands") and rubric.get("feedback_dimensions"))):
            add("Q_RUBRIC_MISSING", "主观题缺少可计算评分维度，分值字段不能代替量规")
        elif rubric.get("status") in {"draft", "proposed", "待审核"} or pending_review(rubric.get("status")) or pending_review(rubric.get("review_status")) or rubric.get("verified") is False or rubric.get("expert_verified") is False:
            add("Q_RUBRIC_PENDING_REVIEW", "主观题量规尚未核验")
    elif question_type in CHOICE_TYPES and (rubric or rubric_id):
        add("Q_RUBRIC_ON_OBJECTIVE", "选择题按选项字母判分，携带主观题评分框架会成为只在正文可见的影子量规", "error")
    for rule, detail, severity in rubric_shape_issues(rubric):
        add(rule, detail, severity)
    review = record.get("review") or extra.get("review") or {}
    if review.get("status") not in REVIEW_STATES:
        add("Q_REVIEW_STATE_INVALID", f"复核状态“{review.get('status')}”不在附录 A.1 六态枚举内", "error")
    if content.get("answer_status") not in ANSWER_STATES:
        add("Q_ANSWER_STATE_INVALID", f"答案状态“{content.get('answer_status')}”不在附录 A.1 五态枚举内", "error")
    if "answer_status" in extra:
        add("Q_ANSWER_PROVENANCE_KEY_STALE", "extra.answer_status 是已废弃键，抽取形状应存 extra.answer_provenance", "error")
    if content.get("answer_status") == "source_conflict" and review and review.get("status") != "quarantined":
        add("Q_QUARANTINE_STATE_MISSING", "来源答案冲突题必须记为 quarantined，停留在瑕疵态会被当成可判分题目", "error")
    expert = (extra.get("content_review") or {}).get("expert_review") or {}
    human_review = review.get("status") in REVIEWED and review.get("checked_by") and (review.get("checked_at") or review.get("evidence"))
    nested_review = expert.get("status") in REVIEWED | {"approved", "passed"} and expert.get("reviewer") and (expert.get("reviewed_at") or expert.get("evidence"))
    if not (human_review or nested_review) or review.get("content_verified") is False:
        add("Q_CONTENT_PENDING_REVIEW", "题目内容与判分答案尚无可核验的专家审核记录")
    boundary = extra.get("source_boundary_verification") or {}
    boundary_status = review.get("source_boundary_status") or boundary.get("status")
    if review.get("cross_question_risk") or boundary_status in {"ambiguous_boundary_candidates", "ambiguous", "cross_question_risk"}:
        add("Q_SOURCE_BOUNDARY_AMBIGUOUS", "题干或选项含跨题混入风险，需核对原始题号边界与答案归属")
    mapping_status = review.get("requirement_mapping_status") or extra.get("requirement_mapping_status")
    if mapping_status in {"module_fallback", "module_only", "coarse", "模块兜底"}:
        add("Q_REQUIREMENT_MAPPING_COARSE", "只有模块级考试要求兜底，需要补具体条目映射")
    if requirement_ids and (pending_alignment or pending_review(mapping_status)):
        add("Q_REQUIREMENT_MAPPING_PENDING_REVIEW", "官方条目自动对齐或学科细点拆解尚未经教研复核")
    if review.get("status") in REVIEWED and not (review.get("checked_by") and (review.get("checked_at") or review.get("evidence"))):
        add("Q_REVIEW_EVIDENCE_MISSING", "声称人工或专家审核但缺少审核人及日期/证据", "error")
    if isinstance(analysis, dict) and analysis.get("method") in {"llm", "ai", "generated"} and review.get("status") not in REVIEWED:
        add("Q_AI_ANALYSIS_PENDING_REVIEW", "自动生成解析尚未经内容复核")
    if module == "听力理解":
        audio = extra.get("audio") or extra.get("audio_url") or extra.get("audio_path") or extra.get("audio_refs") or extra.get("audio_files")
        if isinstance(audio, dict):
            audio_paths = source_files(audio)
            remote = audio.get("url") or audio.get("audio_url")
        elif isinstance(audio, list):
            audio_paths, remote = source_files({"files": audio}), None
        else:
            audio_paths = [audio] if isinstance(audio, str) and not audio.startswith(("http://", "https://")) else []
            remote = audio if isinstance(audio, str) and audio.startswith(("http://", "https://")) else None
        if not remote and not any(resolve_file(p, base_paths) for p in audio_paths):
            add("Q_AUDIO_UNLINKED", "听力题未关联可播放的音频资源")
        elif any(not resolve_file(p, base_paths) for p in audio_paths):
            add("Q_AUDIO_SOURCE_UNRESOLVED", "关联的音频来源中有无法定位的文件")
        elif isinstance(audio, dict) and (audio.get("start_seconds") is None or audio.get("end_seconds") is None):
            add("Q_AUDIO_SEGMENT_UNSPECIFIED", "已关联音频但题组的起止时间尚未定位")
        elif isinstance(audio, dict):
            start, end = audio.get("start_seconds"), audio.get("end_seconds")
            if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in (start, end)) or not 0 <= start < end:
                add("Q_AUDIO_SEGMENT_INVALID", "音频起止时间必须为有效秒数，且结束晚于开始", "error")
    return issues


def inspect_resource(record, context):
    """学习资源沿用题目的引用契约，但不强加逐题答案与解析格式。"""
    projected = dict(record)
    projected["question_id"] = record.get("resource_id") or record.get("material_id")
    if not projected.get("source") and record.get("source_files"):
        projected["source"] = {"files": record["source_files"]}
    if record.get("material_id"):
        parts = str(record["material_id"]).split(".")
        if len(parts) >= 3 and parts[0] in {"ntce", "shengkao"}:
            projected.setdefault("level", parts[1])
            projected.setdefault("subject", parts[2])
    projected["content"] = record.get("content") if isinstance(record.get("content"), dict) else {}
    task_type = record.get("task_type")
    if task_type in {"short_essay", "paragraph_translation"}:
        projected["question_type"] = "短文写作" if task_type == "short_essay" else "段落汉译英"
    else:
        projected["question_type"] = None
    accepted = ("Q_ID_", "Q_KNOWLEDGE_", "Q_ABILITY_", "Q_REQUIREMENT_", "Q_SOURCE_", "Q_RUBRIC_", "Q_MODULE_", "Q_EXAM_", "Q_CONTENT_", "Q_REVIEW_", "Q_COPYRIGHT_")
    issues = [{**issue, "rule": "R_" + issue["rule"][2:], "detail": issue["detail"].replace("题目", "学习资源")} for issue in inspect_question(projected, context) if issue["rule"].startswith(accepted)]
    if record.get("material_id"):
        if not nonempty(record.get("text")):
            issues.append({"rule": "R_MATERIAL_TEXT_MISSING", "severity": "gap", "detail": "共享材料缺少正文"})
        for question_id in record.get("question_ids", []):
            if question_id not in context.get("question_ids", set()):
                issues.append({"rule": "R_QUESTION_DANGLING", "severity": "error", "detail": f"材料关联题目不存在：{question_id}"})
    if task_type in {"short_essay", "paragraph_translation"}:
        content = projected["content"]
        if not nonempty(content.get("prompt")):
            issues.append({"rule": "R_TASK_PROMPT_MISSING", "severity": "gap", "detail": "写译学习任务缺少题目要求或原文"})
        if not nonempty(content.get("reference_answer")):
            issues.append({"rule": "R_TASK_REFERENCE_MISSING", "severity": "gap", "detail": "写译学习任务缺少参考范文或译文"})
    return issues


def unique_index(data, id_field, issues, dataset):
    index = {}
    for record, path, line in data:
        key = record.get(id_field)
        if key in index:
            issues.append({"dataset": dataset, "rule": "ID_DUPLICATE", "severity": "error", "id": key, "file": str(path.relative_to(ROOT)), "line": line, "detail": f"{id_field}重复"})
        index[key] = record
    return index


def reachable(starts, adjacency):
    seen, todo = set(starts), deque(starts)
    while todo:
        for child in adjacency.get(todo.popleft(), ()):
            if child not in seen:
                seen.add(child)
                todo.append(child)
    return seen


def inspect_prerequisites(edges):
    """环检测覆盖全部先修边；正式学习路径只走已核定且有审核人的边。"""
    issues, cyclic, path_adjacency, path_indegree = [], defaultdict(set), defaultdict(set), {}
    for edge in edges:
        kind = edge.get("type") or edge.get("rel")
        if kind not in {"prereq_of", "prerequisite", "prerequisite_of", "prerequisite_candidate"}:
            continue
        a, b = edge.get("src"), edge.get("dst")
        review = edge.get("review") or {}
        # 规范 §3.4 的状态字段是 status；review_status 只作历史兼容读取。
        status = edge.get("status") or review.get("status") or edge.get("review_status")
        edge_approved = REVIEWED | {"verified", "approved", "passed"}
        if kind == "prerequisite_candidate" or pending_review(status) or status not in edge_approved:
            issues.append({"rule": "GRAPH_PREREQUISITE_PENDING_REVIEW", "severity": "gap", "id": f"{a}->{b}", "detail": "先修关系仍为候选或缺少教研复核依据"})
            cyclic[a].add(b)
            continue
        if not (edge.get("reviewed_by") or review.get("reviewed_by")):
            issues.append({"rule": "GRAPH_PREREQUISITE_EVIDENCE_MISSING", "severity": "error", "id": f"{a}->{b}", "detail": "先修边标为已核定却缺少审核人，不得进入正式学习路径"})
            cyclic[a].add(b)
            continue
        path_adjacency[a].add(b)
        cyclic[a].add(b)
    for adjacency, label in ((cyclic, "全部先修图（含候选）"), (path_adjacency, "正式学习路径图")):
        indegree = {}
        for node in set(adjacency) | {child for children in adjacency.values() for child in children}:
            indegree.setdefault(node, 0)
        for children in adjacency.values():
            for child in children:
                indegree[child] += 1
        todo, visited = deque(node for node, count in indegree.items() if count == 0), set()
        while todo:
            node = todo.popleft()
            visited.add(node)
            for child in adjacency[node]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    todo.append(child)
        if adjacency and len(visited) != len(indegree):
            issues.append({"rule": "GRAPH_PREREQUISITE_CYCLE", "severity": "error", "detail": f"{label}无法拓扑排序，环或依赖环的节点：" + ", ".join(sorted(set(indegree) - visited))})
    return issues


def load_context(dataset, requirements, standards, issues):
    base = ROOT / ("数据集/四六级" if dataset == "cet" else "数据集/教资")
    if dataset == "cet":
        knowledge_rows = json_rows([base / "ontology/knowledge_nodes.jsonl"], issues)
        ability_rows = json_rows([base / "ontology/ability_nodes.jsonl"], issues)
        passages = unique_index(json_rows([base / "passages/reading.jsonl"], issues), "resource_id", issues, dataset)
        transcript_path = base / "listening/transcripts.jsonl"
        transcripts = unique_index(json_rows([transcript_path], issues), "resource_id", issues, dataset) if transcript_path.is_file() else {}
        materials = {}
        material_rows = []
        rubric_path = base / "ontology/scoring_rubrics.jsonl"
        rubrics = unique_index(json_rows([rubric_path], issues), "rubric_id", issues, dataset) if rubric_path.is_file() else {}
        edge_rows = json_rows([base / "ontology/edges.jsonl"], issues)
        graph_rows = knowledge_rows + ability_rows
        graph_ids = {r.get("id") for r, _, _ in graph_rows}
        old_standards = json.loads((base / "ontology/standards.json").read_text(encoding="utf-8-sig"))
        graph_ids.update(r["id"] for r in old_standards.get("standards", []) + old_standards.get("素养目标", []))
        graph_ids.update(standards)
        graph_ids.update(requirements)
        roots = [ROOT, base, base / "scripts", ROOT / "英语四六级资料合集（2026年最新）(1)"]
        questions = json_rows(base.glob("questions/*/*.jsonl"), issues)
    else:
        graph_rows = json_rows([base / "graph/nodes.jsonl"], issues)
        knowledge_rows = [(r, p, n) for r, p, n in graph_rows if r.get("type") == "knowledge_node"]
        ability_rows = [(r, p, n) for r, p, n in graph_rows if r.get("type") == "ability"]
        passages, transcripts = {}, {}
        rubrics = {}
        for rubric_path in sorted((base / "rubrics").glob("*.json")):
            if rubric_path.name == "README.md":
                continue
            payload = json.loads(rubric_path.read_text(encoding="utf-8-sig"))
            entries = payload if isinstance(payload, list) else [payload]
            for entry in entries:
                if isinstance(entry, dict) and entry.get("rubric_id"):
                    rubrics.setdefault(entry["rubric_id"], entry)
        material_rows = json_rows(base.glob("materials/*/*/*.jsonl"), issues)
        materials = unique_index(material_rows, "material_id", issues, dataset)
        edge_rows = json_rows([base / "graph/edges.jsonl"], issues)
        graph_ids = {r.get("id") for r, _, _ in graph_rows}
        roots = [ROOT, base]
        questions = json_rows(base.glob("questions/*/*/*.jsonl"), issues)
    knowledge = unique_index(knowledge_rows, "id", issues, dataset)
    abilities = unique_index(ability_rows, "id", issues, dataset)
    adjacency = defaultdict(set)
    node_abilities = defaultdict(set)
    for edge, path, line in edge_rows:
        a, b = edge.get("src"), edge.get("dst")
        if a not in graph_ids or b not in graph_ids:
            issues.append({"dataset": dataset, "rule": "GRAPH_ENDPOINT_DANGLING", "severity": "error", "file": str(path.relative_to(ROOT)), "line": line, "detail": f"{a} → {b}"})
        kind = edge.get("type") or edge.get("rel")
        if kind in {"contains", "has_child"}:
            adjacency[a].add(b)
        if kind == "supports_ability" and a in abilities and b in knowledge:
            node_abilities[b].add(a)
    for issue in inspect_prerequisites([edge for edge, _, _ in edge_rows]):
        issues.append({**issue, "dataset": dataset})
    if dataset == "ntce":
        for node_id, node in knowledge.items():
            module = node.get("module")
            if module and node_id not in reachable([module], adjacency):
                issues.append({"dataset": dataset, "rule": "GRAPH_MODULE_KNOWLEDGE_UNREACHABLE", "severity": "error", "id": node_id, "detail": "模块不能沿包含关系到达知识点"})
    for node_id, node in knowledge.items():
        if node.get("assessable") is not False and not node.get("exam_requirement_ids"):
            issues.append({"dataset": dataset, "rule": "KN_REQUIREMENT_MISSING", "severity": "gap", "id": node_id, "detail": "知识点缺少具体考试要求映射"})
    return {"dataset": dataset, "knowledge": knowledge, "abilities": abilities, "node_abilities": node_abilities, "requirements": requirements, "standards": standards, "passages": passages, "transcripts": transcripts, "materials": materials, "material_rows": material_rows, "question_ids": {r.get("question_id") for r, _, _ in questions}, "rubrics": rubrics, "base_paths": roots}, questions


def validate():
    issues = []
    catalog_path = ROOT / "权威资料/catalog.json"
    if catalog_path.is_file():
        catalog = json.loads(catalog_path.read_text(encoding="utf-8-sig"))
        standards = {r["standard_id"]: r for r in catalog.get("sources", [])}
    else:
        standards = {}
        issues.append({"rule": "OFFICIAL_CATALOG_MISSING", "severity": "gap", "detail": "尚无本地官方资料索引"})
    requirement_path = ROOT / "权威资料/requirements.jsonl"
    requirement_rows = json_rows([requirement_path], issues) if requirement_path.is_file() else []
    requirements = unique_index(requirement_rows, "requirement_id", issues, "official")
    for standard_id, standard in standards.items():
        path = resolve_file(standard.get("local_path"), (str(ROOT), str(ROOT / "权威资料")))
        if not path:
            issues.append({"dataset": "official", "rule": "OFFICIAL_SOURCE_FILE_MISSING", "severity": "gap", "id": standard_id, "detail": "官方资料原文文件缺失"})
        elif standard.get("sha256") and hashlib.sha256(path.read_bytes()).hexdigest() != standard["sha256"]:
            issues.append({"dataset": "official", "rule": "OFFICIAL_SOURCE_HASH_MISMATCH", "severity": "error", "id": standard_id, "detail": "官方原文文件与记录校验值不一致"})
        if not standard.get("source_url") or not standard.get("authority"):
            issues.append({"dataset": "official", "rule": "OFFICIAL_PROVENANCE_INCOMPLETE", "severity": "gap", "id": standard_id, "detail": "来源URL或发布机构为空"})
    for requirement_id, requirement in requirements.items():
        if requirement.get("standard_id") not in standards:
            issues.append({"dataset": "official", "rule": "REQUIREMENT_STANDARD_DANGLING", "severity": "error", "id": requirement_id, "detail": "考试要求条目缺少标准原文"})
        if not requirement.get("locator"):
            issues.append({"dataset": "official", "rule": "REQUIREMENT_LOCATOR_MISSING", "severity": "gap", "id": requirement_id, "detail": "条目未记录原文定位"})
        for issue in inspect_requirement(requirement, [ROOT, ROOT / "权威资料"]):
            issue.update(dataset="official", id=requirement_id)
            issues.append(issue)
    metrics = {}
    for dataset in ("cet", "ntce"):
        context, data = load_context(dataset, requirements, standards, issues)
        unique_index(data, "question_id", issues, dataset)
        counts = Counter(total=len(data))
        for record, path, line in data:
            record_issues = inspect_question(record, context)
            counts["active_records"] += (record.get("extra") or {}).get("active") is not False
            counts["retained_parser_artifacts"] += any(i["rule"] == "Q_PARSER_ARTIFACT_INACTIVE" for i in record_issues)
            counts["without_structure_errors"] += not any(i["severity"] == "error" for i in record_issues)
            counts["complete_against_checked_requirements"] += not record_issues
            counts["with_knowledge"] += bool(record.get("knowledge_node_ids"))
            counts["with_ability"] += bool(record.get("ability_ids"))
            counts["with_requirement"] += bool(record.get("exam_requirement_ids"))
            counts["with_answer"] += nonempty(record.get("content", {}).get("answer"))
            counts["with_usable_answer_field"] += usable_answer_field(record, record_issues)
            analysis = record.get("analysis") or record.get("content", {}).get("analysis")
            if isinstance(analysis, dict):
                analysis_body = analysis.get("published_explanation") or analysis.get("raw_text") or analysis.get("raw") or analysis.get("explanation") or record.get("content", {}).get("analysis")
                if not analysis_body:
                    analysis_body = "\n".join(analysis[part] for part in ("key_info", "option_compare") if isinstance(analysis.get(part), str) and substantive_text(analysis[part], reject_letters=True))
            else:
                analysis_body = analysis
            counts["with_substantive_analysis_text"] += substantive_text(analysis_body, reject_letters=True)
            counts["with_complete_structured_analysis"] += isinstance(analysis, dict) and not any(i["rule"] == "Q_ANALYSIS_INCOMPLETE" for i in record_issues)
            counts["with_calibrated_difficulty"] += record.get("difficulty") is not None and not any(i["rule"] in {"Q_DIFFICULTY_INVALID", "Q_DIFFICULTY_UNCALIBRATED"} for i in record_issues)
            counts["with_content_expert_review"] += not any(i["rule"] == "Q_CONTENT_PENDING_REVIEW" for i in record_issues)
            counts["with_defined_copyright_scope"] += not any(i["rule"] == "Q_COPYRIGHT_UNRESOLVED" for i in record_issues)
            for issue in record_issues:
                issue.update(dataset=dataset, id=record.get("question_id"), file=str(path.relative_to(ROOT)), line=line)
                issues.append(issue)
        if dataset == "cet":
            base = ROOT / "数据集/四六级"
            resources = json_rows([p for folder in ("writing", "translation", "vocabulary", "passages", "listening") for p in (base / folder).glob("*.jsonl") if not p.name.startswith("_")], issues)
            unique_index(resources, "resource_id", issues, dataset)
        else:
            resources = context["material_rows"]
        counts["learning_resources"] = len(resources)
        for record, path, line in resources:
            resource_issues = inspect_resource(record, context)
            counts["resources_without_structure_errors"] += not any(i["severity"] == "error" for i in resource_issues)
            counts["resources_complete_against_checked_requirements"] += not resource_issues
            for issue in resource_issues:
                issue.update(dataset=dataset, id=record.get("resource_id") or record.get("material_id"), file=str(path.relative_to(ROOT)), line=line)
                issues.append(issue)        # 量规实体独立门禁：它们不被题目按 ID 引用，只在判分时由教研挑选，问题路径永远走不到。
        counts["rubric_entities"] = len(context["rubrics"])
        rubric_folder = "数据集/四六级/ontology/scoring_rubrics.jsonl" if dataset == "cet" else "数据集/教资/rubrics"
        for rubric_id, rubric_entity in sorted(context["rubrics"].items()):
            for rule, detail, severity in rubric_shape_issues(rubric_entity):
                issues.append({"dataset": dataset, "rule": rule, "severity": severity,
                               "id": rubric_id, "file": rubric_folder, "detail": detail})
        metrics[dataset] = dict(counts)
    # 补充官方样卷使用同一题目契约；计数单列，避免混成原题库净补量。
    supplemental = ROOT / "补充资料/四六级官方样题"
    if (supplemental / "questions.jsonl").is_file():
        context, _ = load_context("cet", requirements, standards, issues=[])
        context["base_paths"] = [ROOT, supplemental, ROOT / "权威资料"]
        sample_data = json_rows([supplemental / "questions.jsonl"], issues)
        sample_passages = json_rows([supplemental / "passages.jsonl"], issues) if (supplemental / "passages.jsonl").is_file() else []
        context["passages"].update(unique_index(sample_passages, "resource_id", issues, "cet_official_examples"))
        unique_index(sample_data, "question_id", issues, "cet_official_examples")
        sample_counts = Counter(total=len(sample_data))
        for record, path, line in sample_data:
            record_issues = inspect_question(record, context)
            sample_counts["without_structure_errors"] += not any(i["severity"] == "error" for i in record_issues)
            sample_counts["complete_against_checked_requirements"] += not record_issues
            sample_counts["with_answer"] += substantive_text(record.get("content", {}).get("answer"), reject_letters=record.get("question_type") in SUBJECTIVE)
            for issue in record_issues:
                issues.append({**issue, "dataset": "cet_official_examples", "id": record.get("question_id"), "file": str(path.relative_to(ROOT)), "line": line})
        for record, path, line in sample_passages:
            for issue in inspect_resource(record, context):
                issues.append({**issue, "dataset": "cet_official_examples", "id": record.get("resource_id"), "file": str(path.relative_to(ROOT)), "line": line})
        sample_counts["learning_resources"] = len(sample_passages)
        metrics["cet_official_examples"] = dict(sample_counts)
    by_rule = Counter(i["rule"] for i in issues)
    by_severity = Counter(i["severity"] for i in issues)
    report = {
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "scope": "两套主题库全量及静态引用、权威来源与具体要求条目；已输出共同题目格式的补充官方样卷亦单列全检；不证明每题答案正确或应用功能已完成",
        "complete": not issues, "structure_errors": by_severity["error"], "remaining_gaps": by_severity["gap"],
        "metrics": metrics, "by_rule": dict(sorted(by_rule.items())), "issues": issues,
    }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "审查/知识库验收结果.json")
    args = parser.parse_args()
    report = validate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    queue_path = args.output.with_name("知识库待补队列.jsonl")
    with queue_path.open("w", encoding="utf-8") as stream:
        for issue in report["issues"]:
            stream.write(json.dumps(issue, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "issues"}, ensure_ascii=False, indent=2))
    return 0 if report["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
