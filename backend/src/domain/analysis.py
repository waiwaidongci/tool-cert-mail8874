"""校准证书的报告日快照、器具处置清单与分发判定。"""

from collections import Counter, defaultdict
from datetime import date

from .spec import ACTIVE, CERTIFICATE, INACTIVE, INSTRUMENT, SPEC


OVERDUE = '已过期'
MISSING = '缺少证书'
DUE_TODAY = '当日到期'
DUE_SOON = '即将到期'
VALID = '有效'
STATUS_ORDER = (OVERDUE, MISSING, DUE_TODAY, DUE_SOON, VALID)

_FIELDS = {field['key']: field for field in SPEC['fields']}
_COLUMNS = (
    ('asset_id', '器具编号'), ('asset_name', '器具名称'), ('work_area', '作业区'),
    ('owner', '责任班组'), ('status', '证书状态'), ('certificate_id', '证书编号'),
    ('issued_on', '签发日'), ('expires_on', '到期日'), ('days_remaining', '剩余天数'),
    ('action', '班组处置'),
)


def _text(row, key):
    value = row.get(key)
    field = _FIELDS[key]
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= field['max_length']:
        raise ValueError(f'{field["label"]}须填写 1 至 {field["max_length"]} 个字符')
    return value.strip()


def _day(value, label):
    if isinstance(value, str):
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            pass
        else:
            if parsed.isoformat() == value:
                return parsed
    raise ValueError(f'{label}须为有效的 YYYY-MM-DD 日期')


def validate_rows(rows):
    instruments = {}
    certificates = defaultdict(dict)
    for index, row in enumerate(rows, start=2):
        try:
            asset_id = _text(row, 'asset_id')
            kind = row.get('record_type')
            if kind == INSTRUMENT:
                if asset_id in instruments:
                    raise ValueError(f'器具 {asset_id} 的台账重复')
                status = row.get('asset_status')
                if status not in (ACTIVE, INACTIVE):
                    raise ValueError('器具状态须为在用或停用')
                instruments[asset_id] = {
                    'asset_id': asset_id, 'asset_status': status,
                    **{key: _text(row, key) for key in ('asset_name', 'work_area', 'owner')},
                }
            elif kind == CERTIFICATE:
                code = _text(row, 'certificate_id')
                issued = _day(row.get('issued_on'), '签发日')
                expires = _day(row.get('expires_on'), '到期日')
                if expires < issued:
                    raise ValueError(f'证书 {code} 的到期日早于签发日')
                if code in certificates[asset_id]:
                    raise ValueError(f'器具 {asset_id} 的证书 {code} 重复')
                certificates[asset_id][code] = (issued, expires)
            else:
                raise ValueError('记录类型须为器具台账或校准证书')
        except ValueError as error:
            raise ValueError(f'CSV 第 {index} 行 · {error}') from None

    unknown = sorted(certificates.keys() - instruments.keys())
    if unknown:
        raise ValueError(f'证书缺少对应的器具台账，例如 {unknown[0]}')
    return instruments, certificates


def _parameters(params):
    values = {}
    for field in SPEC['params']:
        key = field['key']
        value = params.get(key, field['default'])
        if field['type'] == 'date':
            value = _day(value, field['label'])
        elif type(value) is not int or not field['min'] <= value <= field['max']:
            raise ValueError(f'{field["label"]}须为 {field["min"]} 至 {field["max"]} 的整数')
        values[key] = value
    return values


def _asset_report(instrument, certificates, report_day, horizon):
    code = max(
        (code for code, (issued, _) in certificates.items() if issued <= report_day),
        key=lambda code: (certificates[code][0], code), default=None,
    )
    owner = instrument['owner']
    issued = expires = remaining = None
    if code is None:
        status = MISSING
        action = f'{owner}核对器具铭牌并向计量室补录证书。确认校准有效前暂停用于检验。'
    else:
        issued, expires = certificates[code]
        remaining = (expires - report_day).days
        if remaining < 0:
            status = OVERDUE
            action = f'{owner}停用并贴隔离标签，换用有效备用器具，登记送校。'
        elif remaining == 0:
            status = DUE_TODAY
            action = f'{owner}本班交接前安排换具和送校，次日启用前核对新证书。'
        elif remaining <= horizon:
            status = DUE_SOON
            action = f'{owner}在 {expires} 前预约送校并落实有效备用器具。'
        else:
            status = VALID
            action = f'{owner}继续使用，按台账日期复核校准计划。'

    return {
        **instrument, 'status': status, 'certificate_id': code,
        'issued_on': issued.isoformat() if issued else None,
        'expires_on': expires.isoformat() if expires else None,
        'days_remaining': remaining, 'action': action,
    }


def analyze(rows, params) -> dict:
    options = _parameters(params)
    day = options['report_day']
    horizon = options['horizon_days']
    threshold = options['min_coverage_percent']
    instruments, certificates = validate_rows(rows)
    snapshot = [
        _asset_report(instrument, certificates.get(asset_id, {}), day, horizon)
        for asset_id, instrument in instruments.items() if instrument['asset_status'] == ACTIVE
    ]
    snapshot.sort(key=lambda row: (STATUS_ORDER.index(row['status']), row['days_remaining'] or 0, row['asset_id']))
    counts = Counter(row['status'] for row in snapshot)
    total = len(snapshot)
    covered = total - counts[MISSING]
    coverage = f'{covered / total:.2%}' if total else '待核实'
    ready = total > 0 and covered * 100 >= threshold * total

    if ready:
        headline = f'{day} 班报可分发 · {covered}/{total} 台有证书，{counts[OVERDUE]} 台已过期'
    elif total:
        headline = f'{day} 班报暂停分发 · 已覆盖 {covered}/{total} 台，低于 {threshold}% 门槛'
    else:
        headline = f'{day} 班报暂停分发 · 台账无在用器具'

    return {
        'ready': ready,
        'headline': headline,
        'note': f'报告日 {day}，临期窗口 {horizon} 天。证书覆盖率 {coverage}，分发门槛 {threshold}%。'
                '已过期证书计入覆盖。同日签发按证书编号取字典序末位。',
        'metrics': [
            {'label': '在用器具', 'value': total, 'detail': '按导入台账的在用状态统计'},
            {'label': '证书覆盖率', 'value': coverage, 'detail': f'{covered}/{total} 台 · 门槛 {threshold}%'},
            {'label': '已过期', 'value': counts[OVERDUE], 'detail': '立即停用并换具'},
            {'label': '临期（含当日）', 'value': counts[DUE_SOON] + counts[DUE_TODAY],
             'detail': f'其中 {counts[DUE_TODAY]} 台当日到期'},
            {'label': '缺少证书', 'value': counts[MISSING], 'detail': '截至报告日无已签发证书'},
        ],
        'tables': [{
            'title': '在用器具证书与班组处置',
            'columns': [{'key': key, 'label': label} for key, label in _COLUMNS],
            'rows': snapshot,
        }],
        'charts': [{
            'title': '证书状态（器具数）', 'kind': 'bar',
            'series': [{'label': status, 'value': counts[status]} for status in STATUS_ORDER],
        }] if total else [],
    }
