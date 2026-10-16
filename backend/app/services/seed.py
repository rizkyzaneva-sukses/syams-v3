from sqlalchemy.orm import Session
from ..auth import hash_password
from ..models import User, Role

DEMO_PASSWORD = "demo123456789"


def seed(db: Session):
    if db.query(User).count() > 0:
        return

    users = [
        User(name="CEO Syams", email="ceo@syams.local", role=Role.CEO, password_hash=hash_password(DEMO_PASSWORD)),
        User(name="CMO Manager", email="cmo.manager@syams.local", role=Role.CMO_MANAGER, password_hash=hash_password(DEMO_PASSWORD)),
        User(name="CMO Support", email="cmo.support@syams.local", role=Role.CMO_SUPPORT, password_hash=hash_password(DEMO_PASSWORD)),
        User(name="CFO Manager", email="cfo.manager@syams.local", role=Role.CFO_MANAGER, password_hash=hash_password(DEMO_PASSWORD)),
        User(name="COO Manager", email="coo.manager@syams.local", role=Role.COO_MANAGER, password_hash=hash_password(DEMO_PASSWORD)),
        User(name="Sample PIC", email="sample.pic@syams.local", role=Role.SAMPLE_PIC, password_hash=hash_password(DEMO_PASSWORD)),
        User(name="Printing PIC", email="printing.pic@syams.local", role=Role.PRINTING_PIC, password_hash=hash_password(DEMO_PASSWORD)),
        User(name="Production PIC", email="production.pic@syams.local", role=Role.PRODUCTION_PIC, password_hash=hash_password(DEMO_PASSWORD)),
        User(name="CHRO Manager", email="chro.manager@syams.local", role=Role.CHRO_MANAGER, password_hash=hash_password(DEMO_PASSWORD)),
        User(name="HR Support", email="hr.support@syams.local", role=Role.HR_SUPPORT, password_hash=hash_password(DEMO_PASSWORD)),
        User(name="Shipment Admin", email="shipment.admin@syams.local", role=Role.SHIPMENT_ADMIN, password_hash=hash_password(DEMO_PASSWORD)),
    ]
    db.add_all(users)
    db.commit()
