"""离线分包入账、冲突核查与总榜发布。

入账顺序由包版本决定，与到达顺序无关：
- 同一包重试只确认一次，不重复计入，也不改动已发布总榜；
- 低于已入账版本的迟到包记为 stale，不能顶掉新版本；
- 库房换包提交更高版本时取代旧版本，并把合并退回待发布；
- 任一巡检凭据出现在两个库房的已入账包里即进入 conflict，暂停发布；
- 退回换包后重新核对，库房齐备且无冲突时才允许按原规则重新发布总榜。
"""

from sqlalchemy import select

from src.constants.enums import MergeState
from src.domain import merge
from src.models.jobs import MergeAttempt, MergePackage, MergeSession
from src.services.audit import record
from src.utils.time import iso, now


def _session(db, session_id, lock=False):
    return db.get(MergeSession, session_id, with_for_update=lock)


def _log(db, session_id, body, outcome, detail):
    db.add(MergeAttempt(
        session_id=session_id, room=str(body.get('room', ''))[:80],
        reference=str(body.get('reference', ''))[:120], version=body.get('version') or 0,
        checksum=str(body.get('checksum', ''))[:64], outcome=outcome, detail=detail[:500],
    ))


def latest_packages(db, session_id):
    return list(db.scalars(select(MergePackage).where(MergePackage.session_id == session_id)
                           .order_by(MergePackage.room)))


def _package_view(item):
    return {
        'room': item.room, 'version': item.version, 'reference': item.reference,
        'state': item.state,
        'positive_count': item.positive_count, 'negative_count': item.negative_count,
        'pattern_hits': item.pattern_hits, 'credentials': item.credentials,
        'checksum': item.checksum,
    }


def _state_inputs(packages):
    return [_package_view(item) for item in packages]


def _package_row(item):
    return {
        'room': item.room, 'reference': item.reference, 'version': item.version, 'state': item.state,
        'checksum': item.checksum, 'positive_count': item.positive_count,
        'negative_count': item.negative_count, 'total_count': item.positive_count + item.negative_count,
        'pattern_hits': item.pattern_hits, 'note': item.note, 'received_at': iso(item.received_at),
    }


def build_ledger(session, packages):
    """把各库房已入账计数逐项相加，按原规则排出总榜，并保留每个库房的贡献。"""
    packages = [item for item in packages if item.state == 'accepted']
    totals = merge.aggregate([_package_view(item) for item in packages])
    patterns = merge.rank_patterns(totals, session.params)
    positives, negatives = totals['positive_count'], totals['negative_count']
    if not positives or not negatives:
        missing = '见霉斑' if not positives else '未见霉斑'
        headline = f'合并后缺少{missing}的巡检，暂无法比较两组。'
    elif patterns:
        headline = f'合并 {len(packages)} 个库房、{positives + negatives} 条巡检，{patterns[0]["conditions"]}的增长倍数最高。'
    else:
        headline = '合并后的计数没有模式同时达到命中数与增长倍数门槛。'
    contributions = [{
        'room': item.room, 'reference': item.reference, 'version': item.version,
        'positive_count': item.positive_count, 'negative_count': item.negative_count,
        'total_count': item.positive_count + item.negative_count,
        'pattern_hits': item.pattern_hits, 'checksum': item.checksum,
        'received_at': iso(item.received_at),
    } for item in packages]
    return {
        'headline': headline,
        'totals': {'positive_count': positives, 'negative_count': negatives,
                   'total_count': positives + negatives, 'rooms': len(packages)},
        'patterns': patterns,
        'contributions': contributions,
        'note': (
            f'参与库房 {len(session.rooms)} 个，已入账 {len(packages)} 个。'
            f'湿度达到 {session.params["humidity_threshold"]:g}% 归入高湿，平滑量 {session.params["smoothing"]:g}；'
            f'门槛为正组命中至少 {session.params["min_positive_count"]} 条、'
            f'两组合计至少 {session.params["min_total_count"]} 条、增长至少 {session.params["min_growth"]:g} 倍。'
            '各库房巡检原表、单号与架位留在本地，合并只使用两组样本数、条件命中数和查重凭据。'
        ),
    }


def recompute(db, session):
    """根据已入账包推导状态；任何变化都会撤销已发布总榜，等待重新核对。"""
    packages = latest_packages(db, session.id)
    state, missing, conflicts, accepted = merge.derive_state(session.rooms, _state_inputs(packages))
    session.state = state
    session.ledger = None
    session.published_at = None
    return state, missing, conflicts, accepted


def receive(db, session_id, body):
    """按版本入账一个分包，返回 (结果, 是否改动总榜)。"""
    session = _session(db, session_id, lock=True)
    if not session:
        raise ValueError('找不到该合并')
    try:
        package = merge.normalize_package(body, session.params, session.rooms)
    except ValueError as error:
        _log(db, session.id, body, 'rejected', str(error))
        raise
    package['checksum'] = merge.package_checksum(package)
    existing = db.scalar(select(MergePackage).where(MergePackage.session_id == session.id,
                                                    MergePackage.room == package['room']))

    if existing and existing.checksum == package['checksum']:
        if existing.state == 'returned':
            _log(db, session.id, package, 'rejected', '该库房已退回换包，原包不能重新入账')
            raise ValueError(f'库房「{package["room"]}」已退回换包，请修改计数后提高版本号重新提交')
        _log(db, session.id, package, 'duplicate', '同一包重试，已确认入账')
        return {'outcome': 'duplicate', 'package': _package_view(existing)}, False

    if existing and package['version'] < existing.version:
        _log(db, session.id, package, 'stale',
             f'迟到版本 v{package["version"]}，当前已入账 v{existing.version}')
        return {'outcome': 'stale', 'package': _package_view(existing)}, False

    if existing and package['version'] == existing.version:
        detail = '该库房已退回换包，请提高版本号提交' if existing.state == 'returned' \
            else f'v{package["version"]} 已有不同内容的包'
        _log(db, session.id, package, 'rejected', detail)
        raise ValueError(f'库房「{package["room"]}」的 v{package["version"]} 已有不同内容，请核对后提高版本号换包')

    if existing:
        returned = existing.state == 'returned'
        updated = f'v{existing.version} → v{package["version"]}'
        details = f'{updated}（{"退回后换包" if returned else "更新"}）'
        existing.version = package['version']
        existing.reference = package['reference']
        existing.checksum = package['checksum']
        existing.state = 'accepted'
        existing.positive_count = package['positive_count']
        existing.negative_count = package['negative_count']
        existing.pattern_hits = package['pattern_hits']
        existing.credentials = package['credentials']
        existing.note = body.get('note')
        existing.received_at = now()
        item = existing
        outcome = 'replaced'
        record(db, body.get('actor', 'system'), 'merge.package.replaced', session.id,
               room=package['room'], version=package['version'])
    else:
        details = f'入账 v{package["version"]}'
        item = MergePackage(
            session_id=session.id, room=package['room'], reference=package['reference'],
            version=package['version'], state='accepted', checksum=package['checksum'],
            positive_count=package['positive_count'], negative_count=package['negative_count'],
            pattern_hits=package['pattern_hits'], credentials=package['credentials'],
            note=body.get('note'),
        )
        db.add(item)
        outcome = 'accepted'
        record(db, body.get('actor', 'system'), 'merge.package.accepted', session.id,
               room=package['room'], version=package['version'])
    db.flush()
    _log(db, session.id, package, outcome, details)
    return {'outcome': outcome, 'package': _package_view(item)}, True


def create(db, name, rooms, params, actor):
    rooms = merge.clean_rooms(rooms)
    session = MergeSession(name=name, rooms=rooms, params=params, state=MergeState.AWAITING, author=actor)
    db.add(session)
    db.flush()
    record(db, actor, 'merge.created', session.id, rooms=rooms, params=params)
    return session


def return_room(db, session_id, room, note, actor):
    """退回某库房换包：移除其已入账包，换包前保持暂停发布。"""
    session = _session(db, session_id, lock=True)
    if not session:
        raise ValueError('找不到该合并')
    item = db.scalar(select(MergePackage).where(MergePackage.session_id == session.id,
                                                MergePackage.room == room))
    if not item:
        raise ValueError('该库房没有可退回的已入账包')
    package = {'room': item.room, 'reference': item.reference, 'version': item.version,
               'checksum': item.checksum}
    if item.state == 'returned':
        return session, item
    item.state = 'returned'
    _log(db, session.id, package, 'returned', note)
    record(db, actor, 'merge.returned', session.id, room=room, note=note)
    return session, item


def published(db, session):
    """在库房齐备且无冲突时冻结当前计数为已发布总榜。"""
    packages = latest_packages(db, session.id)
    state, missing, conflicts, accepted = merge.derive_state(session.rooms, _state_inputs(packages))
    if state == 'awaiting':
        raise ValueError('仍有库房未入账：' + '、'.join(missing))
    if state == 'conflict':
        rooms = '、'.join(conflicts['rooms'])
        raise ValueError(f'{conflicts["credential_count"]} 条巡检凭据跨库房重复（{rooms}），请退回换包后重新核对')
    session.state = MergeState.PUBLISHED
    session.ledger = build_ledger(session, packages)
    session.published_at = now()
    record(db, 'system', 'merge.published', session.id,
           rooms=session.rooms, totals=session.ledger['totals'])
    return session


def snapshot(db, session):
    packages = latest_packages(db, session.id)
    attempts = list(db.scalars(select(MergeAttempt).where(MergeAttempt.session_id == session.id)
                               .order_by(MergeAttempt.id.desc()).limit(50)))
    state, missing, conflicts, accepted = merge.derive_state(session.rooms, _state_inputs(packages))
    accepted_rooms = {item['room'] for item in accepted}
    return {
        'id': session.id, 'name': session.name, 'rooms': session.rooms, 'params': session.params,
        'state': session.state, 'derived_state': state,
        'author': session.author, 'created_at': iso(session.created_at),
        'published_at': iso(session.published_at),
        'missing_rooms': missing, 'conflicts': conflicts,
        'accepted_rooms': sorted(accepted_rooms),
        'packages': [_package_row(item) for item in packages],
        'attempts': [{'room': item.room, 'reference': item.reference, 'version': item.version,
                      'outcome': item.outcome, 'detail': item.detail, 'created_at': iso(item.created_at)}
                     for item in attempts],
        'preview': build_ledger(session, packages) if accepted else None,
        'ledger': session.ledger,
        'credential_scheme': merge.CREDENTIAL_SCHEME,
        'pattern_keys': list(merge.PATTERN_KEYS),
    }
