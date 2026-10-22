import math
from pathlib import Path
import sys
import unittest
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from analytics import distribution,reconcile_rows
from pipeline import parse_sheet,number,clean,category

class StatisticsTests(unittest.TestCase):
    def test_linear_quantiles_and_sample_stdev(self):
        d=distribution([1,2,3,4,None,float('nan'),float('inf'),True])
        self.assertEqual(d['n'],4);self.assertEqual(d['median'],2.5);self.assertEqual(d['q1'],1.75)
        self.assertAlmostEqual(d['stdev'],math.sqrt(5/3));self.assertEqual(sum(x['n'] for x in d['histogram']),4)
    def test_empty_single_constant_negative(self):
        self.assertEqual(distribution([])['n'],0)
        self.assertIsNone(distribution([2])['stdev'])
        self.assertEqual(distribution([2]*6)['outliers'],0)
        d=distribution([-4,-2,0]);self.assertEqual(sum(x['n'] for x in d['histogram']),3)
    def test_missing_is_not_zero(self):
        self.assertIsNone(number('-'));self.assertIsNone(number('<0.1'));self.assertIsNone(number(True))
        self.assertIsNone(number('12'));self.assertEqual(number(0),0)

class ParserTests(unittest.TestCase):
    def test_meal_headers_footer_and_dates_do_not_become_ingredients(self):
        rows=[['생산일자',datetime(2026,1,2)],['조식'],['메뉴명','원재료','1인량(g)','사용량(kg)','단위'],['국','양파',10,2,None],[None,'당근',5,1,None],['생산량','학교A',50,'포장방법 및 단위'],[None,'학교B',80,None],['중식'],['생산일자',datetime(2026,1,2),None,None,'제품명'],['메뉴명','원재료','1인량(g)','사용량(kg)','단위'],['밥','쌀',100,12,None]]
        rec,_,_=parse_sheet(enumerate(rows,1),'production','2')
        self.assertEqual(len(rec),3);self.assertEqual([r['material'] for r in rec],['양파','당근','쌀'])
        self.assertEqual(rec[-1]['meal'],'중식');self.assertEqual(rec[0]['work_date'],'2026-01-02')
        self.assertEqual(rec[0]['columns']['used'],3);self.assertEqual(rec[1]['menu'],'국')
    def test_shifted_recipe_columns(self):
        rs=[[None,'식단','식재','1인량','kg','비고'],[None,'국','양파',10,2,'memo'],[None,None,'당근',None,0,None]]
        rec,_,_=parse_sheet(enumerate(rs,1),'recipe','월-중')
        self.assertEqual(len(rec),2);self.assertEqual(rec[0]['columns']['material'],2)
        self.assertEqual(rec[1]['menu'],'국');self.assertIsNone(rec[1]['portion']);self.assertEqual(rec[1]['used'],0)
    def test_stock_equation_units_and_missing(self):
        rs=[['일 자',datetime(2026,1,1)],['No','업체명','품목명','전일재고','입고','단위','사용량','재고량'],[1,'업체','쌀',10,2,'kg',4,8],[2,'업체','양파',1,2,'kg',None,None],[3,'업체','계란',10,0,'ea',2,8]]
        rec,_,_=parse_sheet(enumerate(rs,1),'stock','1')
        self.assertEqual(rec[0]['issues'],[]);self.assertIsNone(rec[1]['used']);self.assertIn('단위 미확인',rec[2]['issues'])

class ReconciliationTests(unittest.TestCase):
    def row(self,material='쌀',used=2,day='2026-01-01',unit='kg',fid='a'):
        return {'material':material,'used':used,'work_date':day,'unit':unit,'file_id':fid}
    def test_common_dates_unit_missing_and_zero_stock(self):
        p=[self.row(),self.row(used=1),self.row('양파',None),self.row('고기',2,unit='ea'),self.row(day='2026-01-02')]
        s=[self.row(used=3,fid='b'),self.row('양파',2,fid='b'),self.row('고기',2,fid='b'),self.row('소금',0,fid='b')]
        result,common,union=reconcile_rows(p,s);by={r['material']:r for r in result}
        self.assertEqual(by['쌀']['status'],'일치');self.assertEqual(by['양파']['status'],'비교 불가')
        self.assertEqual(by['고기']['status'],'비교 불가');self.assertNotIn('소금',by)
        self.assertEqual(len(common),1);self.assertEqual(len(union),2)
    def test_conflicting_source_dates_are_excluded(self):
        rs,common,_=reconcile_rows([self.row(fid='a'),self.row(fid='other')],[self.row(fid='stock')])
        self.assertEqual(rs,[]);self.assertEqual(common,set())
    def test_skus_are_not_fuzzy_merged(self):
        rs,_,_=reconcile_rows([self.row('닭(국내산)')],[self.row('닭',fid='b')])
        self.assertEqual({r['status'] for r in rs},{'생산에만 기록','수불에만 기록'})

if __name__=='__main__':unittest.main()
