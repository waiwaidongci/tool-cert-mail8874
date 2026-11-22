INSTRUMENT = '器具台账'
COMPARISON = '比对记录'
STANDARD = '标准器'
WORKING = '工作器具'

SPEC = {
    'title': '计量室同轮比对偏差区间',
    'short_name': 'metrology-comparison',
    'subtitle': '同轮比对求各器具最窄偏差范围，矛盾组隔离、缺基准待核',
    'organization': '澄岭精密零件厂 · 质量计量室',
    'workflow': (
        '计量室把标准器具和工作器具放在同一轮比对中，逐对登记示值差值与允许容差。'
        '值班主管导入上游比对记录后，系统把互相有比对关系的器具划成一组，'
        '以标准器具的偏差为零，计算同时满足组内全部记录时每台器具的最窄偏差范围。'
        '有矛盾的整组隔离并列出冲突记录；没有标准器具作基准的组标记待核；其余组照常给出区间。'
    ),
    'pains': [
        '上游记录多次更正或撤回后，人工难以判断哪些器具区间需要随之修正。',
        '同一组内的容差链路较长，手工推算的区间往往比真实可行范围更宽。',
        '矛盾记录会把整组结果带偏，缺少基准的组又容易被误当成已定结果。',
    ],
    'steps': [
        '11 月 21 日，计量员导入本轮器具台账与同轮比对记录，其中含标准器具与三处作业区的工作器具。',
        '系统按比对关系把器具划分成组，标准器具偏差固定为零，逐组求解最窄偏差区间。',
        '含矛盾约束的组整组隔离，页面列出冲突的比对记录编号。',
        '没有标准器具与基准链路的组标记为待核，等待补录基准。',
        '其余组输出每台器具的下界、上界与区间宽度，供班组复核。',
        '上游更正或撤回比对记录后，只重算受影响的组，其余组沿用上次结果。',
        '重算期间页面保留上次已发布结果，全部组完成后一次性替换为新结果。',
    ],
    'methodology': [
        '每条比对记录给出差值 d 与容差 t，表示 |(x_A − x_B) − d| ≤ t；器具 A 的偏差为 x_A，标准器具的偏差固定为零。',
        '同一组内多台标准器具一并锚定为零，其余器具的上下界由差分约束最短路给出。',
        '把每条记录拆成两条差分约束，用最短路求各器具的可行上下界：上界为自基准出发的最短路，下界为到基准最短路取负。',
        '两条最短路之和即为区间宽度；在无矛盾时该区间内的任意值都可同时满足全部记录，因此是最窄范围。',
        '组内出现负环即为矛盾，整组隔离并标出参与负环的比对记录；没有标准器具的组无法锚定绝对偏差，标记待核；未参与任何比对的器具同样待核。',
        '上游批次按比对记录编号与器具编号对比上一次结果，记录更正、撤回或新增后，仅重算内容发生变化的组。',
        '组内容变化会按组号更正；组号消失则撤回；器具集合拆开或合并时，相关组都按受影响组处理。',
    ],
    'sample_name': '澄岭厂同轮比对记录.csv',
    'default_dataset': '澄岭计量室 R1 同轮比对批次',
    'entity': '器具台账与同轮比对记录',
    'run': '同轮比对重算',
    'decision': '偏差区间复核',
    'action': '登记复核结论',
    'modes': ['确认偏差区间', '隔离矛盾组', '催补基准'],
    'pages': ['计量值班台', '器具与比对记录', '同轮比对重算', '偏差区间', '区间复核', '结果归档'],
    'fields': [
        {'key': 'record_type', 'label': '记录类型', 'type': 'select', 'required': True,
         'options': [INSTRUMENT, COMPARISON]},
        {'key': 'asset_id', 'label': '器具编号（台账填写）', 'type': 'string', 'required': False, 'max_length': 40},
        {'key': 'asset_name', 'label': '器具名称（台账填写）', 'type': 'string', 'required': False, 'max_length': 80},
        {'key': 'work_area', 'label': '作业区（台账填写）', 'type': 'string', 'required': False, 'max_length': 60},
        {'key': 'owner', 'label': '责任班组（台账填写）', 'type': 'string', 'required': False, 'max_length': 60},
        {'key': 'asset_class', 'label': '器具类别（台账填写）', 'type': 'select', 'required': False,
         'options': [STANDARD, WORKING]},
        {'key': 'comparison_id', 'label': '比对记录编号（比对填写）', 'type': 'string', 'required': False, 'max_length': 60},
        {'key': 'round_no', 'label': '比对轮次（比对填写）', 'type': 'string', 'required': False, 'max_length': 20},
        {'key': 'asset_a', 'label': '器具 A 编号（比对填写）', 'type': 'string', 'required': False, 'max_length': 40},
        {'key': 'asset_b', 'label': '器具 B 编号（比对填写）', 'type': 'string', 'required': False, 'max_length': 40},
        {'key': 'difference', 'label': '差值 A−B（比对填写）', 'type': 'number', 'required': False},
        {'key': 'tolerance', 'label': '容差（比对填写）', 'type': 'number', 'required': False},
    ],
    'params': [],
    'fixture': {},
    'axes': '按比对组计数；矛盾组整组隔离，缺基准组待核，其余组输出器具偏差区间。',
}
