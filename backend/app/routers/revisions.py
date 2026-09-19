"""User-submitted revision proposals and their review history."""
from datetime import datetime
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session, defer

from ..auth import get_current_user
from ..audit import log_audit
from ..database import get_db
from ..models import RevisionProposal, RevisionStatusEvent, Role, User

router = APIRouter(prefix="/revisions", tags=["revisions"])
MAX_IMAGE_BYTES = 5 * 1024 * 1024


class StatusChange(BaseModel):
    expected_status: str
    status: str
    note: str = ""
    # Who or what is making this change — "Hermes", "GPT", "Claude", a human name.
    operator: str | None = None


def image_mime(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def allowed_next(proposal: RevisionProposal, user: User) -> list[str]:
    if proposal.status in {"REVISI", "TINJAU_ULANG"}:
        return ["CHECK"] if user.role == Role.CEO or user.role.value == proposal.owner_role else []
    if proposal.status == "CHECK" and (user.id == proposal.reported_by_id or user.role == Role.CEO):
        return ["SOLVED", "TINJAU_ULANG"]
    return []


def proposal_out(proposal: RevisionProposal, reporter_name: str, user: User) -> dict:
    return {
        "id": proposal.id,
        "module_name": proposal.module_name,
        "bug_description": proposal.bug_description,
        "expected_behavior": proposal.expected_behavior,
        "has_image": proposal.image_mime is not None,
        "reported_by_id": proposal.reported_by_id,
        "reported_by_name": reporter_name,
        "created_at": proposal.created_at.isoformat() + "Z",
        "owner_role": proposal.owner_role,
        "status": proposal.status,
        "status_note": proposal.status_note,
        "status_updated_at": proposal.status_updated_at.isoformat() + "Z" if proposal.status_updated_at else None,
        "status_updated_by_id": proposal.status_updated_by_id,
        # Who or what produced this revision — "Hermes", "GPT", "Claude", or a
        # human name. Null means the reporter did not declare an operator.
        "operator": proposal.operator,
        "allowed_next_statuses": allowed_next(proposal, user),
    }


@router.get("")
def list_revisions(limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0),
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (db.query(RevisionProposal, User.name)
            .options(defer(RevisionProposal.image_data))
            .join(User, User.id == RevisionProposal.reported_by_id)
            .order_by(RevisionProposal.id.desc()).offset(offset).limit(limit).all())
    return [proposal_out(proposal, name, user) for proposal, name in rows]


@router.post("", status_code=201)
async def create_revision(module_name: str = Form(...), bug_description: str = Form(...),
                          expected_behavior: str = Form(...), owner_role: str | None = Form(None),
                          operator: str | None = Form(None),
                          image: UploadFile | None = File(None),
                          db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    module_name = module_name.strip()
    bug_description = bug_description.strip()
    expected_behavior = expected_behavior.strip()
    if not module_name or len(module_name) > 120:
        raise HTTPException(422, "Modul wajib diisi (maksimal 120 karakter).")
    if not bug_description or len(bug_description) > 5000:
        raise HTTPException(422, "Bug wajib diisi (maksimal 5000 karakter).")
    if not expected_behavior or len(expected_behavior) > 5000:
        raise HTTPException(422, "Perilaku yang diharapkan wajib diisi (maksimal 5000 karakter).")
    owner_role = owner_role or user.role.value
    if owner_role not in {role.value for role in Role}:
        raise HTTPException(422, "Bagian owner tidak valid.")
    operator = (operator or "").strip()[:64] or None

    data = None
    mime = None
    if image is not None:
        data = await image.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(413, "Gambar maksimal 5 MB.")
        mime = image_mime(data)
        if mime is None:
            raise HTTPException(415, "Gunakan gambar PNG, JPG, atau WebP.")

    proposal = RevisionProposal(module_name=module_name, bug_description=bug_description,
                                expected_behavior=expected_behavior, image_data=data, image_mime=mime,
                                reported_by_id=user.id, owner_role=owner_role,
                                operator=operator)
    db.add(proposal)
    db.flush()
    log_audit(db, user, "CREATE", "RevisionProposal", proposal.id,
              f"{module_name} | operator={operator or '-'}")
    db.commit()
    db.refresh(proposal)
    return proposal_out(proposal, user.name, user)


@router.get("/{proposal_id}/history")
def revision_history(proposal_id: int, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    proposal = db.get(RevisionProposal, proposal_id)
    if proposal is None:
        raise HTTPException(404, "Usulan revisi tidak ditemukan.")
    events = (db.query(RevisionStatusEvent, User.name)
              .join(User, User.id == RevisionStatusEvent.changed_by_id)
              .filter(RevisionStatusEvent.proposal_id == proposal_id)
              .order_by(RevisionStatusEvent.id.asc()).all())
    return [{"from_status": event.from_status, "to_status": event.to_status,
             "note": event.note, "changed_by_name": name,
             "operator": event.operator,
             "created_at": event.created_at.isoformat() + "Z"} for event, name in events]


@router.patch("/{proposal_id}/status")
def change_revision_status(proposal_id: int, payload: StatusChange,
                           db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    proposal = (db.query(RevisionProposal).filter(RevisionProposal.id == proposal_id)
                .with_for_update().one_or_none())
    if proposal is None:
        raise HTTPException(404, "Usulan revisi tidak ditemukan.")
    if payload.expected_status != proposal.status:
        raise HTTPException(409, "Status sudah berubah. Muat ulang usulan sebelum melanjutkan.")
    if payload.status not in allowed_next(proposal, user):
        raise HTTPException(403, "Anda tidak berwenang mengubah status ke tahap ini.")
    note = payload.note.strip()
    if len(note) > 2000:
        raise HTTPException(422, "Catatan maksimal 2000 karakter.")
    if payload.status in {"CHECK", "TINJAU_ULANG"} and not note:
        raise HTTPException(422, "Catatan wajib diisi untuk tahap ini.")
    previous = proposal.status
    proposal.status = payload.status
    proposal.status_note = note or None
    proposal.status_updated_at = datetime.utcnow()
    proposal.status_updated_by_id = user.id
    event_operator = (payload.operator or "").strip()[:64] or proposal.operator
    db.add(RevisionStatusEvent(proposal_id=proposal.id, from_status=previous,
                               to_status=proposal.status, note=proposal.status_note,
                               changed_by_id=user.id, operator=event_operator))
    log_audit(db, user, "STATUS_CHANGE", "RevisionProposal", proposal.id,
              f"{previous} -> {proposal.status}: {note} | operator={event_operator or '-'}")
    db.commit()
    db.refresh(proposal)
    reporter = db.get(User, proposal.reported_by_id)
    return proposal_out(proposal, reporter.name, user)


@router.get("/{proposal_id}/image")
def get_revision_image(proposal_id: int, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    proposal = db.get(RevisionProposal, proposal_id)
    if proposal is None or proposal.image_data is None:
        raise HTTPException(404, "Gambar tidak ditemukan.")
    return Response(content=proposal.image_data, media_type=proposal.image_mime,
                    headers={"Content-Disposition": "inline"})
