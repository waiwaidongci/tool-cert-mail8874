"""同轮比对领域逻辑的回归测试。

运行：cd backend && python -m unittest discover -s tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.domain import analysis
from src.domain.demo import demo_revised_rows, demo_rows
from src.domain.spec import COMPARISON, INSTRUMENT, STANDARD, WORKING


def _rows(instruments, comparisons, round_no='Q'):
    rows = [{
        'record_type': INSTRUMENT, 'asset_id': asset_id, 'asset_name': name,
        'work_area': '作业区', 'owner': '班组',
        'asset_class': STANDARD if asset_id.startswith('S') else WORKING,
    } for asset_id, name in instruments]
    rows += [{
        'record_type': COMPARISON, 'comparison_id': code, 'round_no': round_no,
        'asset_a': asset_a, 'asset_b': asset_b, 'difference': difference, 'tolerance': tolerance,
    } for code, asset_a, asset_b, difference, tolerance in comparisons]
    return rows


def _group(result, group_no):
    return next(group for group in result['groups'] if group['group_no'] == group_no)


def _bounds(group):
    return {asset['asset_id']: (asset['lower'], asset['upper']) for asset in group['assets']}


class SnapshotTest(unittest.TestCase):
    def test_demo_batch_has_every_group_kind(self):
        result = analysis.analyze(demo_rows())
        self.assertEqual([group['status'] for group in result['groups']],
                         ['ok', 'pending', 'conflict', 'ok', 'ok'])
        self.assertEqual(_group(result, 'G003')['conflicts'], ['CMP-005', 'CMP-006', 'CMP-007'])
        self.assertEqual(_bounds(_group(result, 'G002')), {})

    def test_standard_is_anchored_at_zero(self):
        # 差值为 A−B，记录 S1 与 A 的差为 0.2，即 x_S1 − x_A = 0.2，标准器为零时 x_A = −0.2。
        result = analysis.analyze(_rows(
            [('S1', '标准器'), ('A', '工作器具')],
            [('c1', 'S1', 'A', 0.2, 0.05)]))
        self.assertEqual(_bounds(_group(result, 'G001')), {'S1': (0.0, 0.0), 'A': (-0.25, -0.15)})

    def test_multiple_standards_share_the_zero_anchor(self):
        result = analysis.analyze(_rows(
            [('S1', '标准器'), ('S2', '标准器'), ('A', '工作器具')],
            [('c1', 'S1', 'A', 0.0, 0.1), ('c2', 'S2', 'A', 0.2, 0.1)]))
        self.assertEqual(_bounds(_group(result, 'G001')),
                         {'S1': (0.0, 0.0), 'S2': (0.0, 0.0), 'A': (-0.1, -0.1)})

    def test_chain_interval_matches_exactly(self):
        result = analysis.analyze(_rows(
            [('S1', '标准器'), ('A', '工作器具'), ('B', '工作器具')],
            [('c1', 'S1', 'A', 0.1, 0.05), ('c2', 'A', 'B', 0.1, 0.05)]))
        self.assertEqual(_bounds(_group(result, 'G001')),
                         {'S1': (0.0, 0.0), 'A': (-0.15, -0.05), 'B': (-0.3, -0.1)})

    def test_conflict_reports_only_the_negative_cycle(self):
        result = analysis.analyze(_rows(
            [('S1', '标准器'), ('A', '工作器具'), ('B', '工作器具'), ('C', '工作器具')],
            [('p1', 'S1', 'A', 0.0, 0.1), ('p2', 'S1', 'B', 0.0, 0.1),
             ('p3', 'A', 'B', 1.0, 0.01), ('p4', 'S1', 'C', 0.0, 0.1)]))
        group = _group(result, 'G001')
        self.assertEqual(group['status'], analysis.CONFLICT)
        self.assertEqual(group['conflicts'], ['p1', 'p2', 'p3'])
        self.assertEqual(group['assets'], [])

    def test_unreferenced_instrument_is_pending(self):
        result = analysis.analyze(_rows([('A', '工作器具')], []))
        self.assertEqual(result['groups'][0]['status'], analysis.PENDING)


class IncrementalTest(unittest.TestCase):
    def setUp(self):
        self.baseline = analysis.analyze(demo_rows())

    def test_changes_keep_group_numbers(self):
        result = analysis.analyze(demo_revised_rows(), baseline=self.baseline)
        changes = {group['group_no']: group['change'] for group in result['groups']}
        self.assertEqual(changes['G001'], 'split')
        self.assertEqual(changes['G002'], 'merge')
        self.assertEqual(changes['G003'], 'corrected')
        self.assertEqual(changes['G004'], 'merge')  # 原成员并入 G002 后按原组号撤回
        self.assertEqual(changes['G005'], 'unchanged')
        self.assertEqual(_group(result, 'G006')['change'], 'split')
        self.assertEqual(_group(result, 'G006')['members'], ['QC-202'])

    def test_unchanged_group_reuses_previous_numbers(self):
        result = analysis.analyze(demo_revised_rows(), baseline=self.baseline)
        self.assertEqual(_bounds(_group(result, 'G005')),
                         _bounds(_group(self.baseline, 'G005')))

    def test_withdrawn_group_is_kept_for_audit(self):
        result = analysis.analyze(demo_revised_rows(), baseline=self.baseline)
        withdrawn = _group(result, 'G004')
        self.assertEqual(withdrawn['status'], analysis.WITHDRAWN)
        self.assertEqual(withdrawn['assets'], [])
        self.assertIn('撤回', withdrawn['message'])

    def test_round_mismatch_is_rejected(self):
        with self.assertRaises(ValueError):
            analysis.analyze(_rows([('A', '工作器具')], [], round_no='R9'), baseline=self.baseline)


class ResumeTest(unittest.TestCase):
    def test_interruption_keeps_completed_groups(self):
        saved = {}

        def stop_after_two(done, total):
            saved.update(done)
            return len(done) < 2

        with self.assertRaises(analysis.Interrupted):
            analysis.analyze(demo_rows(), checkpoint=stop_after_two)
        self.assertEqual(len(saved), 2)

        seen = []

        def resume(done, total):
            seen.append(len(done))
            return True

        resumed = analysis.analyze(demo_rows(), progress={'done': saved}, checkpoint=resume)
        original = analysis.analyze(demo_rows())
        self.assertEqual(seen, [3, 4, 5])
        for left, right in zip(original['groups'], resumed['groups']):
            self.assertEqual((left['status'], left['assets']), (right['status'], right['assets']))

    def test_restarted_run_matches_uninterrupted_run(self):
        original = analysis.analyze(demo_revised_rows(), baseline=analysis.analyze(demo_rows()))
        saved = {}

        def stop(done, total):
            if len(done) >= 2:
                saved.update(done)
                return False
            saved.update(done)
            return True

        with self.assertRaises(analysis.Interrupted):
            analysis.analyze(demo_revised_rows(), baseline=analysis.analyze(demo_rows()), checkpoint=stop)
        resumed = analysis.analyze(demo_revised_rows(), baseline=analysis.analyze(demo_rows()),
                                   progress={'done': saved}, checkpoint=lambda done, total: True)
        for left, right in zip(original['groups'], resumed['groups']):
            self.assertEqual((left['group_no'], left['change'], left['status'], left['assets']),
                             (right['group_no'], right['change'], right['status'], right['assets']))


class ValidationTest(unittest.TestCase):
    def test_unknown_asset_reference_is_rejected(self):
        with self.assertRaises(ValueError):
            analysis.analyze(_rows([('A', '工作器具')],
                                   [('c1', 'A', 'GHOST', 0.0, 0.1)]))

    def test_negative_tolerance_is_rejected(self):
        with self.assertRaises(ValueError):
            analysis.analyze(_rows([('A', '工作器具')],
                                   [('c1', 'A', 'A', 0.0, -0.1)]))

    def test_mixed_rounds_are_rejected(self):
        rows = _rows([('A', '工作器具'), ('B', '工作器具')],
                     [('c1', 'A', 'B', 0.0, 0.1)], round_no='R1')
        rows.append({'record_type': COMPARISON, 'comparison_id': 'c2', 'round_no': 'R2',
                     'asset_a': 'A', 'asset_b': 'B', 'difference': 0.0, 'tolerance': 0.1})
        with self.assertRaises(ValueError):
            analysis.analyze(rows)


if __name__ == '__main__':
    unittest.main()
