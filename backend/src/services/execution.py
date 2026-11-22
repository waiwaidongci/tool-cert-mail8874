import logging
from datetime import timedelta
from sqlalchemy import and_, or_, select
from src.config.database import Session
from src.constants.enums import Status
from src.domain.analysis import Interrupted, analyze
from src.models.jobs import Run
from src.models.source import Dataset
from src.services.audit import record
from src.utils.exports import write_report
from src.utils.time import now

log = logging.getLogger(__name__)


def claim():
    stamp = now()
    with Session.begin() as db:
        query = select(Run).where(or_(Run.status == Status.QUEUED,
                                      and_(Run.status == Status.RUNNING, Run.lease_until < stamp),
                                      and_(Run.status == Status.RUNNING, Run.lease_until.is_(None))))
        job = db.scalar(query.order_by(Run.id).limit(1).with_for_update(skip_locked=True))
        if job is None:
            return None
        if job.attempt >= 3:
            job.status = Status.FAILED
            job.error = '后台进程多次中断，请发起新的运行'
            job.finished_at = stamp
            record(db, 'worker', 'analysis.failed', job.id, reason=job.error)
            return None
        job.status = Status.RUNNING
        job.attempt += 1
        job.lease_until = stamp + timedelta(minutes=3)
        records = db.get(Dataset, job.dataset_id).rows
        progress = dict(job.progress or {})
        return {
            'job_id': job.id, 'attempt': job.attempt, 'rows': records,
            'params': job.params, 'baseline_run_id': job.baseline_run_id,
            'progress': progress,
        }


def _baseline(db, run_id):
    if not run_id:
        return None
    item = db.get(Run, run_id)
    if not item or item.status != Status.COMPLETE or not item.result:
        return None
    return {**item.result, 'run_id': item.id}


def _checkpoint(job_id, attempt):
    """每算完一组保存进度并续租；返回 False 表示租约已被接管，应中断重算。"""

    def check(done, total):
        with Session.begin() as db:
            job = db.get(Run, job_id)
            if job is None or job.attempt != attempt or job.status != Status.RUNNING or job.lease_until is None:
                return False
            job.progress = {'done': done, 'total': total}
            job.lease_until = now() + timedelta(minutes=3)
        return True

    return check


def execute(lease):
    job_id, attempt = lease['job_id'], lease['attempt']
    result = export = failure = None
    try:
        with Session() as db:
            baseline = _baseline(db, lease['baseline_run_id'])
        result = analyze(lease['rows'], lease['params'], baseline=baseline,
                         progress=lease['progress'], checkpoint=_checkpoint(job_id, attempt))
        export = write_report(job_id, attempt, result)
    except Interrupted:
        log.info('Analysis %s interrupted, progress kept for resume', job_id)
        with Session.begin() as db:
            job = db.get(Run, job_id, with_for_update=True)
            if job and job.attempt == attempt and job.status == Status.RUNNING:
                # 主动让出租约，另一个 worker 可立即从已完成的组继续。
                job.lease_until = None
        return
    except ValueError as error:
        failure = str(error)[:500]
    except Exception:
        log.exception('Analysis %s failed', job_id)
        failure = '计算失败，请检查字段口径后重试'

    with Session.begin() as db:
        job = db.get(Run, job_id, with_for_update=True)
        if job.attempt != attempt or job.status != Status.RUNNING:
            return
        job.lease_until = None
        job.finished_at = now()
        job.status = Status.FAILED if failure else Status.COMPLETE
        job.result = None if failure else result
        job.export_file = export
        job.error = failure
        if failure is None:
            job.progress = None
        record(db, 'worker', f'analysis.{job.status}', job.id, attempt=attempt,
               groups=len(result['groups']) if result else None, reason=failure)
