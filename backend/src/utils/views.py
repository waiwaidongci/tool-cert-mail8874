from src.utils.time import iso


def dataset(item):
    return {'id': item.id, 'name': item.name, 'filename': item.filename, 'row_count': item.row_count,
            'checksum': item.checksum, 'author': item.author, 'created_at': iso(item.created_at)}


def run(item, detail=False):
    progress = item.progress or {}
    done = len(progress.get('done', {}))
    total = progress.get('total')
    item_view = {'id': item.id, 'dataset_id': item.dataset_id, 'name': item.name, 'status': item.status,
                 'baseline_run_id': item.baseline_run_id, 'author': item.author,
                 'review': item.review, 'decision': item.decision,
                 'created_at': iso(item.created_at), 'finished_at': iso(item.finished_at),
                 'has_export': bool(item.export_file), 'error': item.error,
                 'round': (item.result or {}).get('round'),
                 'progress': {'done': done, 'total': total} if item.status == 'running' else None}
    if detail:
        item_view.update(params=item.params, result=item.result, review_note=item.review_note)
    return item_view
