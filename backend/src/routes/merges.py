"""离线分包合并：建立合并、接收各库房计数包、退回换包与发布总榜。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.config.database import connection
from src.constants.enums import Role
from src.controllers.auth import allow, current
from src.models.identity import User
from src.models.jobs import MergeSession
from src.schemas.requests import MergePackageRequest, MergeRequest, MergeReturnRequest
from src.services import merges
from src.services.audit import record
from src.services.validation import normalize_params
from src.utils.time import iso

router = APIRouter(prefix='/merges')


@router.get('')
def index(db: Session = Depends(connection), actor: User = Depends(current)):
    return [{'id': item.id, 'name': item.name, 'rooms': item.rooms, 'state': item.state,
             'author': item.author, 'created_at': iso(item.created_at),
             'published_at': iso(item.published_at)}
            for item in db.scalars(select(MergeSession).order_by(MergeSession.id.desc()).limit(100))]


@router.post('', status_code=201)
def create(body: MergeRequest, db: Session = Depends(connection),
           actor: User = Depends(allow(Role.ADMIN, Role.ANALYST))):
    session = merges.create(db, body.name, body.rooms, normalize_params(body.params), actor.username)
    db.commit()
    return merges.snapshot(db, session)


@router.get('/{session_id}')
def detail(session_id: int, db: Session = Depends(connection), actor: User = Depends(current)):
    session = db.get(MergeSession, session_id)
    if not session:
        raise HTTPException(404, '找不到该合并')
    return merges.snapshot(db, session)


@router.post('/{session_id}/packages')
def receive(session_id: int, body: MergePackageRequest, db: Session = Depends(connection),
            actor: User = Depends(allow(Role.ADMIN, Role.ANALYST))):
    session = db.get(MergeSession, session_id)
    if not session:
        raise HTTPException(404, '找不到该合并')
    try:
        result, changed = merges.receive(db, session_id, {**body.model_dump(), 'actor': actor.username})
    except ValueError:
        # 被拒绝的到达也留痕，便于核对是谁在何时重发或换包。
        db.commit()
        raise
    if changed:
        state, missing, conflicts, accepted = merges.recompute(db, session)
        record(db, actor.username, 'merge.recounted', session_id, state=state,
               missing=missing, conflicts=conflicts['credential_count'])
    db.commit()
    return {**result, 'session': merges.snapshot(db, session)}


@router.post('/{session_id}/return')
def send_back(session_id: int, body: MergeReturnRequest, db: Session = Depends(connection),
              actor: User = Depends(allow(Role.ADMIN))):
    """冲突或口径不一致时退回换包：移除该库房已入账版本，换包前暂停发布。"""
    session = db.get(MergeSession, session_id)
    if not session:
        raise HTTPException(404, '找不到该合并')
    merges.return_room(db, session_id, body.room, body.note, actor.username)
    state, missing, conflicts, accepted = merges.recompute(db, session)
    db.commit()
    return merges.snapshot(db, session)


@router.post('/{session_id}/publish')
def publish(session_id: int, db: Session = Depends(connection),
            actor: User = Depends(allow(Role.ADMIN))):
    """库房齐备且无冲突后，加总计数并按原规则发布总榜。"""
    session = db.get(MergeSession, session_id, with_for_update=True)
    if not session:
        raise HTTPException(404, '找不到该合并')
    session = merges.published(db, session)
    record(db, actor.username, 'merge.confirmed', session_id, rooms=session.rooms)
    db.commit()
    return merges.snapshot(db, session)
