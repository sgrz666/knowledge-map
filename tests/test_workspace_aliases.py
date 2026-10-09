"""工作区别名是数据 locator 与 source 路径的一部分，缺失时先给出可执行命令，而不是让下游报 22 个读取错误。"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALIASES = {"权威资料": "官方权威资料", "教资": "教资原始资料"}


class WorkspaceAliasTests(unittest.TestCase):
    def test_alias_directories_resolve(self):
        for alias, target in ALIASES.items():
            with self.subTest(alias=alias):
                self.assertTrue((ROOT / alias).is_dir(),
                                "缺少工作区链接 %s -> %s；在仓库根执行: ln -s \"$(pwd)/%s\" %s（见 README『工作区别名』）"
                                % (alias, target, target, alias))

    def test_recorded_locator_roots_are_reachable(self):
        for path in ("权威资料/catalog.json", "权威资料/requirements.jsonl", "教资/真题"):
            with self.subTest(path=path):
                self.assertTrue((ROOT / path).exists(), "%s 不可解析，条款 locator 与题记录来源都会失效" % path)


if __name__ == "__main__":
    unittest.main()
