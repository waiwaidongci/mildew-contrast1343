import json
from sqlalchemy import func, select
from src.config.database import Session
from src.constants.enums import Role
from src.domain.demo import demo_rows
from src.domain.merge import build_package
from src.domain.spec import SPEC
from src.models.identity import User
from src.models.jobs import MergeSession
from src.models.source import Dataset
from src.services import merges
from src.services.datasets import save
from src.services.validation import normalize_params
from src.utils.security import hash_password

DEMO_MERGE = '浦桥三库房 11 月 16–20 日分包汇总'


def seed_merge(db):
    """建立一份演示合并：三个库房各交一个计数包，库房齐备后发布总榜。"""
    if db.scalar(select(MergeSession).where(MergeSession.name == DEMO_MERGE)):
        return None
    params = normalize_params({field['key']: field['default'] for field in SPEC['params']})
    rows = demo_rows()
    rooms = sorted({row['room'] for row in rows})
    session = merges.create(db, DEMO_MERGE, rooms, params, 'seed')
    for room in rooms:
        package = build_package([row for row in rows if row['room'] == room], room, params,
                                f'PKG-20261120-{room}')
        package['params'] = params
        merges.receive(db, session.id, {**package, 'actor': 'seed'})
    merges.recompute(db, session)
    merges.published(db, session)
    return session.id


def seed():
    with Session.begin() as db:
        for role in Role:
            if not db.get(User, role.value):
                db.add(User(username=role.value, role=role, password_hash=hash_password(f'{role.value}-demo-2611')))
        item, created = save(db, SPEC['default_dataset'], SPEC['sample_name'], demo_rows(), 'seed')
        merge_id = seed_merge(db)
        return {'users': db.scalar(select(func.count()).select_from(User)),
                'datasets': db.scalar(select(func.count()).select_from(Dataset)),
                'seed_dataset_id': item.id, 'row_count': item.row_count, 'checksum': item.checksum,
                'created_dataset': created, 'seed_merge_id': merge_id}


if __name__ == '__main__':
    print(json.dumps(seed(), ensure_ascii=False))
