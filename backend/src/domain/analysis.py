"""同轮比对：器具偏差区间、组隔离、待核与增量重算。"""

import hashlib
import json
from collections import defaultdict

from .spec import COMPARISON, INSTRUMENT, SPEC, STANDARD, WORKING


OK = 'ok'
CONFLICT = 'conflict'
PENDING = 'pending'
WITHDRAWN = 'withdrawn'

STATUS_LABELS = {OK: '已解', CONFLICT: '矛盾隔离', PENDING: '待核', WITHDRAWN: '已撤回'}
CHANGE_LABELS = {'new': '新增', 'corrected': '更正', 'split': '拆分', 'merge': '合并',
                 'unchanged': '未变', 'withdrawn': '撤回'}

_FIELDS = {field['key']: field for field in SPEC['fields']}
_EPS = 1e-9


class Interrupted(Exception):
    """计算租约已被其他进程接管，当前进程应立即退出且不发布结果。"""


# ---------------------------------------------------------------- 输入校验

def _text(row, key, required=True):
    value = row.get(key)
    field = _FIELDS[key]
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValueError(f'{field["label"]}不能为空')
        return None
    if not isinstance(value, str) or len(value.strip()) > field.get('max_length', 300):
        raise ValueError(f'{field["label"]}须填写 1 至 {field["max_length"]} 个字符')
    return value.strip()


def _optional_text(row, key):
    return _text(row, key, required=False) or ''


def _number(row, key):
    value = row.get(key)
    if value is None or value == '':
        raise ValueError(f'{_FIELDS[key]["label"]}不能为空')
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{_FIELDS[key]["label"]}须为数字')
    return float(value)


def validate_rows(rows):
    """把导入行拆成器具台账与比对记录，并校验引用关系。"""
    instruments = {}
    comparisons = []
    seen = set()
    round_no = None
    for index, row in enumerate(rows, start=2):
        try:
            kind = row.get('record_type')
            if kind == INSTRUMENT:
                asset_id = _text(row, 'asset_id')
                if asset_id in instruments:
                    raise ValueError(f'器具 {asset_id} 的台账重复')
                asset_class = row.get('asset_class')
                if asset_class not in (STANDARD, WORKING):
                    raise ValueError('器具类别须为标准器或工作器具')
                instruments[asset_id] = {
                    'asset_id': asset_id,
                    'asset_name': _optional_text(row, 'asset_name'),
                    'work_area': _optional_text(row, 'work_area'),
                    'owner': _optional_text(row, 'owner'),
                    'asset_class': asset_class,
                }
            elif kind == COMPARISON:
                code = _text(row, 'comparison_id')
                if code in seen:
                    raise ValueError(f'比对记录 {code} 重复')
                seen.add(code)
                current_round = _text(row, 'round_no')
                if round_no is None:
                    round_no = current_round
                elif current_round != round_no:
                    raise ValueError('同一批次只能包含同一比对轮次')
                asset_a = _text(row, 'asset_a')
                asset_b = _text(row, 'asset_b')
                if asset_a == asset_b:
                    raise ValueError(f'比对记录 {code} 的器具 A 与器具 B 不能相同')
                difference = _number(row, 'difference')
                tolerance = _number(row, 'tolerance')
                if tolerance < 0:
                    raise ValueError(f'比对记录 {code} 的容差不能为负')
                comparisons.append({
                    'comparison_id': code, 'round_no': current_round,
                    'asset_a': asset_a, 'asset_b': asset_b,
                    'difference': difference, 'tolerance': tolerance,
                })
            else:
                raise ValueError('记录类型须为器具台账或比对记录')
        except ValueError as error:
            raise ValueError(f'CSV 第 {index} 行 · {error}') from None

    referenced = {comparison[key] for comparison in comparisons for key in ('asset_a', 'asset_b')}
    unknown = sorted(referenced - instruments.keys())
    if unknown:
        raise ValueError(f'比对记录引用了未登记的器具，例如 {unknown[0]}')
    if comparisons and round_no is None:
        raise ValueError('比对记录缺少比对轮次')
    return {'round': round_no or '', 'instruments': instruments, 'comparisons': comparisons}


# ---------------------------------------------------------------- 分组

def _find(parent, asset_id):
    while parent[asset_id] != asset_id:
        parent[asset_id] = parent[parent[asset_id]]
        asset_id = parent[asset_id]
    return asset_id


def _fingerprint(round_no, members, records, instruments):
    payload = {
        'round': round_no,
        'members': [
            [asset_id, instruments[asset_id]['asset_class'], instruments[asset_id]['asset_name'],
             instruments[asset_id]['work_area'], instruments[asset_id]['owner']]
            for asset_id in members
        ],
        'records': [
            [record['comparison_id'], record['asset_a'], record['asset_b'],
             record['difference'], record['tolerance']]
            for record in records
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _plans(data):
    """按比对关系取连通分量，形成稳定排序的组计划。"""
    instruments = data['instruments']
    parent = {asset_id: asset_id for asset_id in instruments}
    for record in data['comparisons']:
        left, right = _find(parent, record['asset_a']), _find(parent, record['asset_b'])
        if left != right:
            parent[max(left, right)] = min(left, right)

    buckets = defaultdict(lambda: {'members': [], 'records': []})
    for asset_id in sorted(instruments):
        buckets[_find(parent, asset_id)]['members'].append(asset_id)
    for record in data['comparisons']:
        buckets[_find(parent, record['asset_a'])]['records'].append(record)

    plans = []
    for bucket in sorted(buckets.values(), key=lambda item: item['members'][0]):
        members = bucket['members']
        records = sorted(bucket['records'], key=lambda item: item['comparison_id'])
        plans.append({
            'signature': '|'.join(members),
            'members': members,
            'records': records,
            'record_ids': [record['comparison_id'] for record in records],
            'anchored': any(instruments[asset_id]['asset_class'] == STANDARD for asset_id in members),
            'fingerprint': _fingerprint(data['round'], members, records, instruments),
        })
    return plans


# ---------------------------------------------------------------- 差分约束

def _relax(size, edges, source):
    """Bellman-Ford；返回距离与是否仍可松弛。"""
    distance = [float('inf')] * size
    distance[source] = 0.0
    for _ in range(size - 1):
        changed = False
        for start, end, weight, _record in edges:
            if distance[start] == float('inf'):
                continue
            candidate = distance[start] + weight
            if candidate < distance[end] - _EPS:
                distance[end] = candidate
                changed = True
        if not changed:
            return distance, False
    still = any(distance[start] != float('inf') and distance[start] + weight < distance[end] - _EPS
                for start, end, weight, _record in edges)
    return distance, still


def _cycle_records(size, edges):
    """返回一个负环上涉及的比对记录编号；无负环时返回空列表。"""
    distance = [0.0] * size
    predecessor = [None] * size
    last = None
    for _ in range(size):
        last = None
        for start, end, weight, record in edges:
            if distance[start] + weight < distance[end] - _EPS:
                distance[end] = distance[start] + weight
                predecessor[end] = (start, record)
                last = end
        if last is None:
            return []
    if last is None:
        return []
    node = last
    for _ in range(size):
        step = predecessor[node]
        if step is None:
            return []
        node = step[0]
    start = node
    records = []
    while True:
        step = predecessor[node]
        if step is None:
            return []
        node, record = step
        if record:
            records.append(record)
        if node == start:
            break
    return records


def _conflicts(size, edges):
    """反复摘除已发现的负环，汇总参与矛盾的比对记录。"""
    work = list(edges)
    found = set()
    for _ in range(len(edges) + 1):
        cycle = set(_cycle_records(size, work))
        if not cycle:
            break
        found |= cycle
        work = [edge for edge in work if edge[3] not in cycle]
    return sorted(found)


def _solve(plan, instruments, round_no):
    members = plan['members']
    index = {asset_id: position for position, asset_id in enumerate(members)}
    super_node = len(members)
    size = len(members) + 1
    edges = []
    for record in plan['records']:
        left = index[record['asset_a']]
        right = index[record['asset_b']]
        difference, tolerance = record['difference'], record['tolerance']
        # x_A - x_B <= d + t 与 x_B - x_A <= t - d
        edges.append((right, left, difference + tolerance, record['comparison_id']))
        edges.append((left, right, tolerance - difference, record['comparison_id']))
    if plan['anchored']:
        for asset_id in members:
            if instruments[asset_id]['asset_class'] == STANDARD:
                node = index[asset_id]
                edges.append((super_node, node, 0.0, None))
                edges.append((node, super_node, 0.0, None))

    solved = {
        'signature': plan['signature'], 'fingerprint': plan['fingerprint'],
        'members': members, 'records': plan['record_ids'], 'round': round_no,
        'conflicts': [], 'assets': [], 'status': OK, 'message': '',
    }
    conflicts = _conflicts(size, edges)
    if conflicts:
        solved.update(status=CONFLICT, conflicts=conflicts,
                      message=f'组内约束互相矛盾，整组隔离；请核对冲突记录 {("、".join(conflicts))}。')
        return solved
    if not plan['anchored']:
        message = ('组内没有标准器具作基准，绝对偏差无法锚定；补录标准器比对后重算。'
                   if plan['records'] else
                   '未参与任何比对记录，无法确定偏差；补录与标准器的比对后重算。')
        solved.update(status=PENDING, message=message)
        return solved

    upper, _ = _relax(size, edges, super_node)
    reverse, _ = _relax(size, [(end, start, weight, record) for start, end, weight, record in edges], super_node)
    if not all(upper[index[asset_id]] != float('inf') and reverse[index[asset_id]] != float('inf')
               for asset_id in members):
        solved.update(status=PENDING, message='部分器具与标准器之间没有比对链路，无法锚定；补录比对后重算。')
        return solved
    assets = []
    for asset_id in members:
        node = index[asset_id]
        high = round(upper[node], 6) + 0.0
        low = round(-reverse[node], 6) + 0.0
        if instruments[asset_id]['asset_class'] == STANDARD:
            low = high = 0.0
        if high < low:
            low = high = round((high + low) / 2, 6) + 0.0
        assets.append({
            'asset_id': asset_id,
            'asset_name': instruments[asset_id]['asset_name'],
            'work_area': instruments[asset_id]['work_area'],
            'owner': instruments[asset_id]['owner'],
            'asset_class': instruments[asset_id]['asset_class'],
            'lower': low, 'upper': high, 'width': round(high - low, 6) + 0.0,
        })
    solved['assets'] = assets
    solved['message'] = (
        f'标准器偏差按零锚定，{len(members)} 台器具的区间同时满足组内 '
        f'{len(plan["records"])} 条记录，区间宽度即最窄可行范围。'
    )
    return solved


# ---------------------------------------------------------------- 组号与变更

def _base_groups(baseline):
    return [group for group in (baseline or {}).get('groups', [])
            if group.get('status') != WITHDRAWN and group.get('group_no')]


def _group_number(value):
    text = str(value or '')
    return int(text[1:]) if text.startswith('G') and text[1:].isdigit() else 0


def _assign(plans, baseline):
    """尽量沿用上次组号：先精确匹配成员集合，再按成员重合度匹配。"""
    bases = _base_groups(baseline)
    assignment = {}
    used = set()
    for plan in plans:
        for group in bases:
            if group.get('signature') == plan['signature'] and group['group_no'] not in used:
                assignment[plan['signature']] = {'group_no': group['group_no'], 'base': group}
                used.add(group['group_no'])
                break

    pairs = []
    for plan in plans:
        if plan['signature'] in assignment:
            continue
        for group in bases:
            if group['group_no'] in used:
                continue
            overlap = len(set(plan['members']) & set(group.get('members', [])))
            if overlap:
                pairs.append((-overlap, _group_number(group['group_no']), plan['signature'], group))
    for _overlap, _no, signature, group in sorted(pairs, key=lambda item: item[:2]):
        if signature in assignment or group['group_no'] in used:
            continue
        assignment[signature] = {'group_no': group['group_no'], 'base': group}
        used.add(group['group_no'])

    next_number = max((_group_number(group.get('group_no')) for group in (baseline or {}).get('groups', [])),
                      default=0) + 1
    for plan in plans:
        if plan['signature'] in assignment:
            continue
        assignment[plan['signature']] = {'group_no': f'G{next_number:03d}', 'base': None}
        next_number += 1
    return assignment, used


def _change(plan, base):
    if base is None:
        return 'new'
    if plan['fingerprint'] == base.get('fingerprint') and base.get('status') in (OK, CONFLICT, PENDING):
        return 'unchanged'
    current, previous = set(plan['members']), set(base.get('members', []))
    if current < previous:
        return 'split'
    if current > previous:
        return 'merge'
    return 'corrected'


def _mark_split_offs(plans, assignment, changes):
    """把从原组拆出的新组也标为拆分，而不仅是原组本身。"""
    for plan in plans:
        if changes[plan['signature']] != 'new':
            continue
        members = set(plan['members'])
        for other in plans:
            base = assignment[other['signature']]['base']
            if base is None or changes[other['signature']] != 'split':
                continue
            if members < set(base.get('members', [])):
                changes[plan['signature']] = 'split'
                break


def _withdrawn_entry(base, plans):
    previous = set(base.get('members', []))
    current_sets = [set(plan['members']) for plan in plans]
    if any(previous < current for current in current_sets):
        change = 'merge'
    elif any(current < previous for current in current_sets):
        change = 'split'
    else:
        change = 'withdrawn'
    labels = {'merge': '并入新组后撤回原组号', 'split': '成员拆入新组后撤回原组号', 'withdrawn': '上游记录已不存在'}
    return {
        'group_no': base['group_no'], 'signature': base.get('signature', ''),
        'members': list(base.get('members', [])), 'records': list(base.get('records', [])),
        'status': WITHDRAWN, 'status_label': STATUS_LABELS[WITHDRAWN],
        'change': change, 'change_label': CHANGE_LABELS[change],
        'assets': [], 'conflicts': [], 'fingerprint': base.get('fingerprint'),
        'message': labels[change] + '，按原组号撤回。',
    }


# ---------------------------------------------------------------- 输出

def _fmt(value):
    if value is None:
        return '—'
    if isinstance(value, float):
        if abs(value) < 1e-9:
            value = 0.0
        return f'{value:.6f}'.rstrip('0').rstrip('.')
    return value


def _tables(groups, plans_by_group, baseline, round_no):
    assets_table = [{
        'group_no': group['group_no'], 'change': group['change_label'],
        'asset_id': asset['asset_id'], 'asset_name': asset['asset_name'],
        'work_area': asset['work_area'], 'asset_class': asset['asset_class'],
        'lower': _fmt(asset['lower']), 'upper': _fmt(asset['upper']),
        'width': _fmt(asset['width']),
    } for group in groups if group['status'] == OK for asset in group['assets']]
    tables = [{
        'title': f'{round_no} 轮已解组器具偏差区间' if round_no and round_no != '—' else '已解组器具偏差区间',
        'columns': [
            {'key': 'group_no', 'label': '组号'}, {'key': 'change', 'label': '变更'},
            {'key': 'asset_id', 'label': '器具编号'}, {'key': 'asset_name', 'label': '器具名称'},
            {'key': 'work_area', 'label': '作业区'}, {'key': 'asset_class', 'label': '器具类别'},
            {'key': 'lower', 'label': '下界'}, {'key': 'upper', 'label': '上界'},
            {'key': 'width', 'label': '区间宽度'},
        ],
        'rows': assets_table,
    }]

    tables.append({
        'title': '组状态与隔离说明',
        'columns': [
            {'key': 'group_no', 'label': '组号'}, {'key': 'status', 'label': '状态'},
            {'key': 'change', 'label': '变更'}, {'key': 'members', 'label': '器具'},
            {'key': 'record_count', 'label': '记录数'}, {'key': 'conflicts', 'label': '冲突记录'},
            {'key': 'message', 'label': '说明'},
        ],
        'rows': [{
            'group_no': group['group_no'], 'status': group['status_label'],
            'change': group['change_label'], 'members': '、'.join(group['members']),
            'record_count': len(group['records']),
            'conflicts': '、'.join(group['conflicts']) or '—',
            'message': group['message'],
        } for group in groups],
    })

    conflict_rows = []
    for group in groups:
        if not group['conflicts']:
            continue
        by_id = {record['comparison_id']: record for record in plans_by_group.get(group['group_no'], [])}
        for code in group['conflicts']:
            record = by_id.get(code, {})
            conflict_rows.append({
                'group_no': group['group_no'], 'comparison_id': code,
                'asset_a': record.get('asset_a') or '—', 'asset_b': record.get('asset_b') or '—',
                'difference': _fmt(record.get('difference')), 'tolerance': _fmt(record.get('tolerance')),
                'reason': '参与负环约束',
            })
    if conflict_rows:
        tables.append({
            'title': '冲突记录',
            'columns': [
                {'key': 'group_no', 'label': '组号'}, {'key': 'comparison_id', 'label': '比对记录'},
                {'key': 'asset_a', 'label': '器具 A'}, {'key': 'asset_b', 'label': '器具 B'},
                {'key': 'difference', 'label': '差值 A−B'}, {'key': 'tolerance', 'label': '容差'},
                {'key': 'reason', 'label': '原因'},
            ],
            'rows': conflict_rows,
        })

    if baseline:
        tables.append({
            'title': '相较接续结果的组变更',
            'columns': [
                {'key': 'group_no', 'label': '组号'}, {'key': 'change', 'label': '变更'},
                {'key': 'status', 'label': '状态'}, {'key': 'members', 'label': '器具'},
                {'key': 'message', 'label': '说明'},
            ],
            'rows': [{
                'group_no': group['group_no'], 'change': group['change_label'],
                'status': group['status_label'], 'members': '、'.join(group['members']),
                'message': group['message'],
            } for group in groups if group['change'] in ('corrected', 'split', 'merge', 'withdrawn')],
        })
    return tables


def _metrics(groups, instruments, comparisons):
    counts = {status: sum(1 for group in groups if group['status'] == status) for status in STATUS_LABELS}
    effective = [group for group in groups if group['status'] != WITHDRAWN]
    changes = lambda *items: sum(1 for group in effective if group['change'] in items)
    return [
        {'label': '器具台数', 'value': len(instruments), 'detail': '台账内全部标准器与工作器具'},
        {'label': '比对记录', 'value': len(comparisons), 'detail': '本批次参与约束的记录'},
        {'label': '已解组', 'value': counts[OK], 'detail': '已给出最窄偏差区间'},
        {'label': '矛盾组', 'value': counts[CONFLICT], 'detail': '整组隔离，等待核对冲突记录'},
        {'label': '待核组', 'value': counts[PENDING], 'detail': '缺少标准器具基准'},
        {'label': '冲突记录', 'value': sum(len(group['conflicts']) for group in groups),
         'detail': '参与负环的比对记录数'},
        {'label': '更正组', 'value': changes('corrected', 'split', 'merge'),
         'detail': '按原组号更正或拆分合并的组'},
        {'label': '沿用组', 'value': changes('unchanged'), 'detail': '内容未变，直接沿用上次结果'},
        {'label': '撤回组', 'value': counts[WITHDRAWN], 'detail': '按原组号撤回的组'},
    ]


def analyze(rows, params=None, baseline=None, progress=None, checkpoint=None):
    """计算一批比对记录。

    baseline 为上次已发布结果，用于按组增量重算；progress 保存已算完的组，
    checkpoint(done, total) 返回 False 表示租约已失效，应中断且不发布结果。
    """
    data = validate_rows(rows)
    round_no = data['round'] or '—'
    if baseline and baseline.get('round') not in (None, '', '—') and baseline['round'] != round_no:
        raise ValueError(f'接续结果属于 {baseline["round"]} 轮，与本批次 {round_no} 轮不一致')

    plans = _plans(data)
    assignment, used = _assign(plans, baseline)
    changes = {plan['signature']: _change(plan, assignment[plan['signature']]['base']) for plan in plans}
    _mark_split_offs(plans, assignment, changes)
    done = dict((progress or {}).get('done', {}))
    groups = []
    records_by_group = {}
    for plan in plans:
        slot = assignment[plan['signature']]
        base = slot['base']
        change = changes[plan['signature']]
        key = f'{plan["signature"]}#{plan["fingerprint"]}'
        if change == 'unchanged':
            solved = {field: base[field] for field in
                      ('status', 'assets', 'conflicts', 'message', 'signature', 'fingerprint',
                       'members', 'records')}
        elif key in done:
            solved = done[key]
        else:
            solved = _solve(plan, data['instruments'], round_no)
            done[key] = solved
            if checkpoint and not checkpoint(done, len(plans)):
                raise Interrupted()
        records_by_group[slot['group_no']] = plan['records']
        groups.append({
            **solved,
            'group_no': slot['group_no'],
            'change': change, 'change_label': CHANGE_LABELS[change],
            'status_label': STATUS_LABELS[solved['status']],
            'round': round_no,
        })

    withdrawn = []
    for group in (baseline or {}).get('groups', []):
        if group.get('status') != WITHDRAWN and group.get('group_no') not in used:
            entry = _withdrawn_entry(group, plans)
            entry['round'] = round_no
            withdrawn.append(entry)
    groups.extend(withdrawn)
    groups.sort(key=lambda group: group['group_no'])

    counts = {status: sum(1 for group in groups if group['status'] == status) for status in STATUS_LABELS}
    rounds = f'{round_no} 轮' if round_no and round_no != '—' else ''
    parts = [f'{rounds}同轮比对', f'{counts[OK]} 组给出偏差区间',
             f'{counts[CONFLICT]} 组矛盾隔离', f'{counts[PENDING]} 组待核']
    if counts[WITHDRAWN]:
        parts.append(f'{counts[WITHDRAWN]} 组撤回')
    headline = ' · '.join(parts)
    note = ('每条记录视为 |(x_A − x_B) − 差值| ≤ 容差；标准器偏差固定为零。'
            '对组内差分约束求最短路，得到同时满足全部记录的最窄上下界。'
            '组内出现负环即判为矛盾整组隔离，缺少标准器的组待核。')
    if baseline:
        changed = sum(1 for group in groups if group['status'] != WITHDRAWN
                      and group['change'] in ('corrected', 'split', 'merge'))
        reused = sum(1 for group in groups if group['change'] == 'unchanged')
        note += (f' 本次接续运行 {baseline.get("run_id", "上次结果")}，仅重算受影响组：'
                 f'{changed} 组按原组号更正或拆并，{reused} 组沿用，{counts[WITHDRAWN]} 组撤回。')
    else:
        note += ' 本次未接续上次结果，全部组独立计算。'

    public_groups = [{key: value for key, value in group.items()} for group in groups]
    chart_groups = [{'label': STATUS_LABELS[status], 'value': counts[status]}
                    for status in (OK, CONFLICT, PENDING, WITHDRAWN)]
    group_numbers = {}
    for group in groups:
        if group['status'] != WITHDRAWN:
            for asset_id in group['members']:
                group_numbers[asset_id] = group['group_no']
    return {
        'round': round_no,
        'headline': headline,
        'note': note,
        'metrics': _metrics(groups, data['instruments'], data['comparisons']),
        'tables': _tables(groups, records_by_group, baseline, round_no),
        'charts': [{'title': '组状态（组数）', 'kind': 'bar', 'series': chart_groups}],
        'groups': public_groups,
        'instruments': [{'asset_id': asset_id, **instrument, 'group_no': group_numbers.get(asset_id)}
                        for asset_id, instrument in sorted(data['instruments'].items())],
        'records': data['comparisons'],
        'baseline_run_id': (baseline or {}).get('run_id'),
    }
