"""Offline regressions for source extraction boundaries and numbered CET skills."""
import json
import unittest
from pathlib import Path

import build_index

ROOT=Path(__file__).resolve().parent


class CetSkillIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        catalog=json.loads((ROOT/'catalog.json').read_text(encoding='utf-8'))
        cls.source=next(s for s in catalog['sources'] if s['standard_id']=='cet.syllabus.2016')
        cls.lines=(ROOT.parent/cls.source['text_path']).read_text(encoding='utf-8').splitlines()

    def test_official_numbered_lists_are_complete(self):
        skills=build_index.cet_skills(self.source,self.lines)
        for module,count in {'听力':9,'阅读':10,'写作':11,'翻译':5,'口语':5}.items():
            rows=[r for r in skills if r['module']==module]
            self.assertEqual([r['skill_code'] for r in rows],[f'{n:02d}' for n in range(1,count+1)])
            for row in rows:
                loc=row['locator']
                self.assertIn(row['content'],'\n'.join(self.lines[loc['line_start']-1:loc['line_end']]))

    def test_short_required_skills_keep_stable_ids(self):
        with (ROOT/'requirements.jsonl').open(encoding='utf-8') as stream:
            rows={r['requirement_id']:r for r in (json.loads(x) for x in stream if x.strip())}
        for rid,text in {
            'r079':'０１ 理解主旨大意','r080':'０４ 推论隐含的意义','r081':'０５ 判断话语的交际功能',
            'r082':'０１ 理解主旨大意','r083':'０２ 理解细节信息','r084':'０４ 概括主旨大意','r085':'０５ 推论隐含的意义',
            'r086':'０１ 表达中心思想','r087':'０３ 表达观点、态度等','r088':'０６ 运用恰当的词汇',
            'r089':'０７ 运用正确的语法','r090':'０８ 运用合适的句子结构','r091':'０９ 使用正确的标点符号',
        }.items():
            self.assertEqual(rows['cet.syllabus.2016.'+rid]['content'],text)
        for rid in ('r003','r028','r050','r055','r065'):
            self.assertNotIn('cet.syllabus.2016.'+rid,rows)
        self.assertEqual(rows['cet.syllabus.2016.r005']['content'],'０２ 听懂重要信息或特定的细节')

    def test_two_columns_on_one_text_line_split_into_two_real_skills(self):
        lines=['[[PDF_PAGE 7]]','１．１．２ 考核的技能','A．理解明示的信息','０１ 理解主旨大意    ０２ 听懂重要信息或特定的细节','１．２ 阅读理解']
        rows=build_index.cet_skills(self.source,lines)
        self.assertEqual([r['content'] for r in rows],['０１ 理解主旨大意','０２ 听懂重要信息或特定的细节'])
        self.assertTrue(all(r['locator']['line_start']==4 and r['locator']['line_end']==4 for r in rows))

    def test_wrapped_skill_retains_complete_text_and_range(self):
        lines=['[[PDF_PAGE 7]]','１．１．２ 考核的技能','０７ 辨别语音特征（如理解重音','和语调等）','１．２ 阅读理解']
        row=build_index.cet_skills(self.source,lines)[0]
        self.assertEqual(row['content'],'０７ 辨别语音特征（如理解重音\n和语调等）')
        self.assertEqual((row['locator']['line_start'],row['locator']['line_end']),(3,4))

    def test_running_headers_and_empty_section_templates_are_not_requirements(self):
        self.assertTrue(build_index.cet_template('全 国 大 学 英 语 四 、六 级 考 试 大 纲(２０１６年 修 订 版)'))
        self.assertTrue(build_index.cet_template('２．２．２ 考试过程\n考试按以下步骤进行:'))
        self.assertTrue(build_index.cet_template('全 国 大 学 英 语 四 、六 级 考 试 大 纲(２０１６年 修 订 版)\n４．主观题评分'))
        self.assertFalse(build_index.cet_template('０１ 理解主旨大意'))


if __name__=='__main__':
    unittest.main()
