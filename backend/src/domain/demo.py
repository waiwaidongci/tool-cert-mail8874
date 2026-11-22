"""澄岭计量室的同轮比对演练数据。

两个批次都属同一比对轮次 R1，模拟上游记录修订前后：
- 「发布批次」为首次导入的 R1 记录，含一个矛盾组、一个待核组和两个已解组。
- 「修订批次」为上游更正后的 R1 记录：CMP-001 更正，CMP-002/003/005/008 撤回，
  新增 CMP-009/010，用于演示按组号的更正、拆分、合并与撤回。
"""

from .spec import COMPARISON, INSTRUMENT, STANDARD, WORKING

DEMO_ROUND = 'R1'
DEMO_DATASET = '澄岭计量室 R1 同轮比对批次'
REVISED_DATASET = '澄岭计量室 R1 同轮比对修订批次'


def _instruments():
    return [
        ('STD-01', '工作基准量块', '计量室', '计量室', STANDARD),
        ('STD-02', '标准扭矩仪', '计量室', '计量室', STANDARD),
        ('STD-03', '标准压力计', '计量室', '计量室', STANDARD),
        ('STD-04', '标准量块', '计量室', '计量室', STANDARD),
        ('QC-201', '数显卡尺', '机加工区', '车削一班', WORKING),
        ('QC-202', '外径千分尺', '机加工区', '磨削班', WORKING),
        ('QC-203', '扭矩扳手', '装配区', '装配二班', WORKING),
        ('QC-204', '电子天平', '终检区', '来料检验班', WORKING),
        ('QC-205', '高度规', '终检区', '终检班', WORKING),
        ('QC-206', '指针式压力表', '装配区', '装配二班', WORKING),
        ('QC-209', '温湿度计', '终检区', '终检班', WORKING),
        ('QC-210', '塞规', '机加工区', '车削一班', WORKING),
    ]


def _instrument_rows():
    return [
        dict(record_type=INSTRUMENT, asset_id=asset_id, asset_name=name, work_area=area,
             owner=owner, asset_class=asset_class, comparison_id=None, round_no=None,
             asset_a=None, asset_b=None, difference=None, tolerance=None)
        for asset_id, name, area, owner, asset_class in _instruments()
    ]


def _comparison_rows(round_no, comparisons):
    return [
        dict(record_type=COMPARISON, asset_id=None, asset_name=None, work_area=None,
             owner=None, asset_class=None, comparison_id=code, round_no=round_no,
             asset_a=asset_a, asset_b=asset_b, difference=difference, tolerance=tolerance)
        for code, asset_a, asset_b, difference, tolerance in comparisons
    ]


_R1 = [
    # G001：STD-01 锚定，QC-201 与 QC-202 经两条记录相连
    ('CMP-001', 'STD-01', 'QC-201', -0.020, 0.010),
    ('CMP-002', 'QC-202', 'QC-201', 0.010, 0.010),
    ('CMP-003', 'STD-01', 'QC-202', -0.030, 0.010),
    # G002：两台工作器具互比，没有标准器，待核
    ('CMP-004', 'QC-203', 'QC-204', 1.200, 0.300),
    # G003：三条记录首尾相接形成负环，整组矛盾隔离
    ('CMP-005', 'STD-02', 'QC-205', 0.000, 0.010),
    ('CMP-006', 'QC-205', 'QC-206', 0.050, 0.005),
    ('CMP-007', 'STD-02', 'QC-206', 0.020, 0.005),
    # G004：独立标准器组
    ('CMP-008', 'STD-03', 'QC-209', -0.030, 0.010),
    # G005：两个批次都不变，重算时沿用上次结果
    ('CMP-011', 'STD-04', 'QC-210', 0.015, 0.010),
]

_R1_REVISED = [
    # CMP-001 更正差值
    ('CMP-001', 'STD-01', 'QC-201', -0.024, 0.010),
    # CMP-002、CMP-003 撤回后 QC-202 脱离 G001，成为独立待核组
    ('CMP-004', 'QC-203', 'QC-204', 1.200, 0.300),
    # CMP-005 撤回后 G003 矛盾消除，由 STD-02 锚定
    ('CMP-006', 'QC-205', 'QC-206', 0.050, 0.005),
    ('CMP-007', 'STD-02', 'QC-206', 0.020, 0.005),
    # CMP-008 撤回；新增 CMP-009/010 把 STD-03、QC-209 并入 G002
    ('CMP-009', 'STD-03', 'QC-204', 0.000, 0.050),
    ('CMP-010', 'QC-209', 'QC-203', -0.010, 0.020),
    # CMP-011 未变，G005 沿用上次结果
    ('CMP-011', 'STD-04', 'QC-210', 0.015, 0.010),
]


def demo_rows() -> list[dict]:
    """首次导入的 R1 发布批次。"""
    return _instrument_rows() + _comparison_rows(DEMO_ROUND, _R1)


def demo_revised_rows() -> list[dict]:
    """上游更正后的 R1 修订批次，用于增量重算演练。"""
    return _instrument_rows() + _comparison_rows(DEMO_ROUND, _R1_REVISED)
