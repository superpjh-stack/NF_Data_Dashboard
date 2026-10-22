from datetime import date,timedelta
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from eda import VERSION,temporal_baseline,cohort_analysis,date_coverage,score,render_document,load_report

class EDATests(unittest.TestCase):
    def record(self,i,value=10,**kwargs):
        return {'file_id':'file-a','work_date':(date(2026,1,1)+timedelta(days=i)).isoformat(),
                'meal':'중식','menu':'메뉴','material':'원재료','unit':'kg','portion':value,'sheet':'1','row':7,**kwargs}
    def test_future_targets_do_not_enter_training_median(self):
        rec=[self.record(i,10 if i<8 else 100) for i in range(10)]
        d=temporal_baseline(rec,minimum_train=2,minimum_days=2)
        self.assertEqual(d['status'],'evaluated');self.assertLess(d['train_last'],d['test_first'])
        self.assertEqual(d['covered_n'],2);self.assertEqual(d['pair_metrics']['mae'],90)
        self.assertTrue(all(p['predicted']==10 for p in d['predictions']))
        self.assertEqual(d['train_n']+d['test_n'],d['eligible_observations'])
    def test_same_date_observations_do_not_cross_split(self):
        rec=[self.record(i,value=10+j,meal=str(j)) for i in range(10) for j in range(2)]
        d=temporal_baseline(rec,2,2)
        self.assertEqual(d['train_n'],16);self.assertEqual(d['test_n'],4)
        self.assertEqual(d['train_days'],8);self.assertEqual(d['test_days'],2)
    def test_unseen_pairs_are_excluded_from_score_but_counted_in_coverage(self):
        rec=[self.record(i,menu='old' if i<8 else 'new') for i in range(10)]
        d=temporal_baseline(rec,2,2)
        self.assertEqual(d['covered_n'],0);self.assertEqual(d['unseen_pair_test_n'],2)
        self.assertEqual(d['coverage_percent'],0);self.assertIsNone(d['pair_metrics']['mae'])
    def test_ambiguous_and_repeated_event_rows(self):
        rec=[self.record(i) for i in range(10)]
        rec+=[self.record(0),self.record(1,value=25)]
        d=temporal_baseline(rec,2,2)
        self.assertEqual(d['ambiguous_events_excluded'],1)
        self.assertEqual(d['duplicate_event_rows_collapsed'],1)
        self.assertEqual(d['eligible_observations'],9)
    def test_missing_units_nonpositive_and_conflicting_sources(self):
        rec=[self.record(i) for i in range(10)]
        rec+=[self.record(15,None),self.record(16,0),self.record(17,-1),self.record(18,'10'),self.record(19,unit='ea'),self.record(0,file_id='other')]
        d=temporal_baseline(rec,2,2)
        self.assertEqual(d['excluded_rows']['1인량 결측·0·음수'],4)
        self.assertEqual(d['excluded_rows']['헤더 단위 미확인'],1)
        self.assertEqual(d['excluded_rows']['여러 파일의 날짜 충돌'],2)
    def test_missing_month_is_unobserved_not_zero_demand(self):
        d=date_coverage([self.record(0),self.record(60)])
        self.assertEqual(d['missing_months'],['2026-02']);self.assertEqual(d['months'][1]['n'],0)
        self.assertEqual(d['days'],2)
    def test_iqr_zero_and_small_cohorts_are_reported(self):
        rec=[self.record(i%5,10 if i<19 else 50) for i in range(20)]
        rec += [self.record(i,20,menu='small') for i in range(3)]
        d=cohort_analysis(rec)
        self.assertEqual(d['groups'],1);self.assertEqual(d['outlier_rows'],1)
        self.assertEqual(d['zero_iqr_groups'],1);self.assertEqual(d['eligible_rows'],20)
    def test_score_uses_actual_sum_denominator(self):
        d=score([{'actual':10,'predicted':8},{'actual':30,'predicted':26}])
        self.assertEqual(d['mae'],3);self.assertEqual(d['wape'],15)
        self.assertIsNone(score([])['mae'])
    def test_report_version_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'eda.json';p.write_text(json.dumps({'report_version':'old','source_meta':{}}))
            with patch('eda.REPORT',p):
                with self.assertRaises(ValueError):load_report()

class ReportVersionTests(unittest.TestCase):
    def test_source_parser_and_snapshot_mismatches_are_rejected(self):
        current={'dataset_id':'abc','parser_version':'1.1','created_at':'today'}
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'eda.json'
            for field in current:
                data={'report_version':VERSION,'source_meta':{**current,field:'wrong'}}
                p.write_text(json.dumps(data))
                with patch('eda.REPORT',p),patch('eda.a.connect'),patch('eda.a.meta',return_value=current):
                    with self.assertRaises(ValueError):load_report()
            p.write_text(json.dumps({'report_version':VERSION,'source_meta':current}))
            with patch('eda.REPORT',p),patch('eda.a.connect'),patch('eda.a.meta',return_value=current),patch('eda.summary_lines',return_value=[]):
                self.assertEqual(load_report()['source_meta'],current)

if __name__=='__main__':unittest.main()
