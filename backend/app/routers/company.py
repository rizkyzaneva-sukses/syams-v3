"""Gambar unggahan (logo, desain artikel, size chart) dan profil perusahaan untuk dokumen SPK & Invoice.

* Logo perusahaan hanya bisa diunggah dan diganti oleh CEO (pemilik).
* Gambar desain dan size chart diunggah tim CMO/Sample saat membuat PO — bukan link Drive.
* Semua gambar disaring: harus benar-benar gambar (diverifikasi PIL), ukuran dibatasi, dan dikecilkan
  supaya database dan PDF tidak membengkak. Gambar tidak pernah ditimpa; mengganti = unggahan baru.
"""
import json
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..audit import log_audit
from ..auth import get_current_user, require_roles
from ..cfo_models import StoredImage
from ..database import get_db
from ..models import Invoice, Order, POIntake, Quotation, Role, SystemConfig, User
from ..invoice_document import build_invoice_pdf

router = APIRouter(tags=["company"])
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_SIDE = {"LOGO": 800, "DESIGN": 1800, "SIZE_CHART": 1800}
UPLOAD_ROLES = {
    "LOGO": (Role.CEO,),
    "DESIGN": (Role.CEO, Role.CMO_MANAGER, Role.CMO_SUPPORT, Role.SAMPLE_PIC),
    "SIZE_CHART": (Role.CEO, Role.CMO_MANAGER, Role.CMO_SUPPORT, Role.SAMPLE_PIC),
}
DEFAULT_PROFILE = {
    "name": "SYAMS Manufacturing",
    "tagline": "Screen printing, Sewing, Setting , Adfruk service etc.",
    "phone": "082117116036",
    "email": "syamsproduction15@gmail.com",
    "address": "",
    "logo_image_id": None,
}


def process_image(raw: bytes, kind: str) -> tuple[bytes, str, int, int]:
    """Verifikasi isi file sebagai gambar, kecilkan, lalu encode ulang. Mengembalikan (bytes, mime, w, h)."""
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        probe = Image.open(BytesIO(raw))
        probe.verify()
        image = Image.open(BytesIO(raw))
        image = ImageOps.exif_transpose(image)
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise HTTPException(422, "File bukan gambar yang valid (gunakan PNG, JPG, atau WEBP)")
    if image.format and image.format.upper() not in ("PNG", "JPEG", "MPO", "WEBP"):
        raise HTTPException(422, "Format gambar harus PNG, JPG, atau WEBP")
    limit = MAX_SIDE[kind]
    if max(image.size) > limit:
        image.thumbnail((limit, limit))
    has_alpha = image.mode in ("RGBA", "LA", "P") and ("A" in image.getbands() or "transparency" in image.info)
    out = BytesIO()
    if has_alpha or kind == "LOGO":
        image.convert("RGBA").save(out, format="PNG", optimize=True)
        mime = "image/png"
    else:
        image.convert("RGB").save(out, format="JPEG", quality=86, optimize=True)
        mime = "image/jpeg"
    return out.getvalue(), mime, image.size[0], image.size[1]


@router.post("/files/images", status_code=201)
async def upload_image(kind: str = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    kind = kind.upper()
    if kind not in MAX_SIDE:
        raise HTTPException(422, "Jenis gambar tidak dikenal (LOGO, DESIGN, atau SIZE_CHART)")
    if user.role not in UPLOAD_ROLES[kind]:
        raise HTTPException(403, "Peran Anda tidak boleh mengunggah gambar jenis ini")
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if not raw:
        raise HTTPException(422, "File kosong")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Ukuran gambar maksimal 8 MB")
    data, mime, width, height = process_image(raw, kind)
    image = StoredImage(kind=kind, filename=(file.filename or "")[:200], mime=mime, width=width, height=height,
                        data=data, created_by_id=user.id)
    db.add(image)
    db.flush()
    log_audit(db, user, "UPLOAD", "StoredImage", image.id, f"{kind} {file.filename or ''} {width}x{height}")
    db.commit()
    return {"id": image.id, "kind": kind, "mime": mime, "width": width, "height": height, "size": len(data)}


@router.get("/files/images/{image_id}")
def get_image(image_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    image = db.get(StoredImage, image_id)
    if not image:
        raise HTTPException(404, "Gambar tidak ditemukan")
    return Response(content=image.data, media_type=image.mime,
                    headers={"Cache-Control": "private, max-age=86400", "Content-Disposition": "inline"})


# ───────────────────────────── Profil perusahaan ─────────────────────────────

class ProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    tagline: Optional[str] = Field(default=None, max_length=200)
    phone: Optional[str] = Field(default=None, max_length=60)
    email: Optional[str] = Field(default=None, max_length=120)
    address: Optional[str] = Field(default=None, max_length=300)
    logo_image_id: Optional[int] = None


def load_profile(db: Session) -> dict:
    record = db.query(SystemConfig).filter_by(key="company_profile").first()
    profile = dict(DEFAULT_PROFILE)
    if record and record.value:
        try:
            profile.update(json.loads(record.value))
        except ValueError:
            pass
    return profile


@router.get("/company/profile")
def get_profile(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return load_profile(db)


@router.put("/company/profile")
def put_profile(data: ProfileIn, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.CEO))):
    if data.logo_image_id is not None:
        logo = db.get(StoredImage, data.logo_image_id)
        if not logo or logo.kind != "LOGO":
            raise HTTPException(422, "Logo harus berupa gambar yang diunggah sebagai LOGO")
    record = db.query(SystemConfig).filter_by(key="company_profile").with_for_update().first()
    if record is None:
        from datetime import datetime
        record = SystemConfig(key="company_profile", value="{}", updated_at=datetime.utcnow())
        db.add(record)
    record.value = json.dumps(data.model_dump(), ensure_ascii=False)
    log_audit(db, user, "UPDATE", "CompanyProfile", None, f"logo={data.logo_image_id}; name={data.name}")
    db.commit()
    return load_profile(db)


# ───────────────────────────── Proforma Invoice (PDF) ─────────────────────────────

@router.get("/cfo/invoices/{invoice_id}/pdf")
def invoice_pdf(invoice_id: int, db: Session = Depends(get_db),
                user: User = Depends(require_roles(Role.CFO_MANAGER, Role.CMO_SUPPORT, Role.CMO_MANAGER, Role.CEO))):
    invoice = db.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(404, "Invoice tidak ditemukan")
    order = db.get(Order, invoice.order_fk)
    quotation = db.query(Quotation).filter_by(order_fk=order.id).order_by(Quotation.id.desc()).first()
    po = db.query(POIntake).filter_by(order_fk=order.id).first()
    profile = load_profile(db)
    logo = db.get(StoredImage, profile["logo_image_id"]) if profile.get("logo_image_id") else None
    pdf = build_invoice_pdf(invoice, order, quotation, profile, logo.data if logo else None,
                            billed_to=order.buyer, po_number=po.po_number if po else None)
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="proforma-{invoice.id}.pdf"'})
