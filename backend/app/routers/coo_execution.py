"""COO daily execution, WIP/handoff & capacity, and physical BOM usage.

Revisi #53 (COO-S-005 Daily Execution & Quantity Control), #54 (COO-S-006 WIP,
Handoff & Capacity), #57 (COO-S-009 BOM, Pemakaian Fisik & Batas Biaya).

Three read-only boards. They derive every number from transactions that already
exist (production movements, BOM items, physical consumption, capacity
snapshots) instead of trusting a hand-typed summary, and they expose the
identity of the source row so a COO can drill down.

Quantity invariant enforced and surfaced everywhere::

    qty_in == qty_done + qty_reject + wip

A row that violates it is reported as a reconciliation problem rather than
silently clamped, because silent clamping is what made the old board lie.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_roles
from ..database import get_db
from .. import coo_actions
from ..models import (
    Article,
    BOMItem,
    CapacitySnapshot,
    MaterialConsumption,
    Order,
    ProductionMovement,
    Role,
)
from ..workflow import route_for, role as role_of

router = APIRouter(prefix="/coo", tags=["coo-execution"])

# Roles that may read the COO execution boards. Siti (COO_MANAGER) owns them;
# production/printing PICs see their own floor; CEO and CFO read for oversight.
EXEC_ROLES = (
    Role.CEO,
    Role.COO_MANAGER,
    Role.PRODUCTION_PIC,
    Role.PRINTING_PIC,
    Role.CFO_MANAGER,
    Role.CMO_MANAGER,
)

# A process is DONE-looking when it has input, no open WIP, and the row is not
# held. Kept as a plain string set so the same vocabulary is shared with
# workflow.STATUSES without importing the mutable registry.
OPEN_STATUSES = {"WAITING", "IN_PROCESS", "HOLD"}

# Threshold (percent) above which committed load is called out as a conflict.
CAPACITY_CONFLICT_PCT = 100


def _num(value) -> int:
    """Coerce a possibly-None SQL aggregate to int without leaking Decimal/None."""
    return int(value or 0)


def _dec(value) -> float:
    return float(value or 0)


def _article_index(db: Session, article_ids) -> dict:
    """Map article id -> (article, order) for the ids that are in play."""
    if not article_ids:
        return {}
    rows = (
        db.query(Article, Order)
        .join(Order, Order.id == Article.order_fk)
        .filter(Article.id.in_(sorted(article_ids)))
        .all()
    )
    return {a.id: (a, o) for a, o in rows}


def _movement_rollup(db: Session, movements) -> dict:
    """Group movements per article+process, preserving the physical identity.

    The board must count a physical quantity exactly once per process. Movements
    are the ledger of record, so we aggregate them per (article, process) and
    keep the row ids so the UI can drill down to the exact transactions.
    """
    buckets = {}
    for mv in movements:
        key = (mv.article_id, (mv.process or "").upper())
        bucket = buckets.setdefault(
            key,
            {
                "qty_in": 0,
                "qty_done": 0,
                "qty_reject": 0,
                "movement_ids": [],
                "statuses": set(),
                "pics": set(),
                "reject_reasons": [],
                "target_dates": [],
            },
        )
        bucket["qty_in"] += _num(mv.qty_in)
        bucket["qty_done"] += _num(mv.qty_done)
        bucket["qty_reject"] += _num(mv.qty_reject)
        bucket["movement_ids"].append(mv.id)
        bucket["statuses"].add((mv.status or "WAITING").upper())
        if mv.pic_name:
            bucket["pics"].add(mv.pic_name)
        if mv.reject_reason:
            bucket["reject_reasons"].append(mv.reject_reason)
        if mv.target_date:
            bucket["target_dates"].append(mv.target_date)
    return buckets


def _status_from_bucket(bucket) -> str:
    statuses = bucket["statuses"]
    if "HOLD" in statuses:
        return "HOLD"
    if "IN_PROCESS" in statuses:
        return "IN_PROCESS"
    if statuses == {"DONE"}:
        return "DONE"
    return "WAITING"


def _article_reconciliation(article, buckets_for_article) -> list:
    """Report route quantities that cannot be explained by the ledger.

    Revisi #54: "Angka yang sama berisiko dihitung berulang". The invariant is
    checked per article, not per process, because a quantity that appears in two
    processes without the upstream done quantity is a duplicate, not progress.
    """
    issues = []
    route = route_for(article)
    if not route:
        issues.append(
            {
                "code": "ROUTE_MISSING",
                "detail": f"Artikel {article.article_code} belum punya rute produksi",
            }
        )
        return issues
    if len(set(route)) != len(route):
        issues.append(
            {
                "code": "ROUTE_DUPLICATE_PROCESS",
                "detail": f"Rute artikel {article.article_code} mengulang proses: {' > '.join(route)}",
            }
        )
    previous_done = None
    for index, process in enumerate(route):
        bucket = buckets_for_article.get(process)
        if bucket is None:
            continue
        qty_in = bucket["qty_in"]
        done = bucket["qty_done"]
        reject = bucket["qty_reject"]
        wip = qty_in - done - reject
        if wip < 0:
            issues.append(
                {
                    "code": "QTY_OVER_ACCOUNTED",
                    "process": process,
                    "detail": (
                        f"{process} artikel {article.article_code}: done+reject "
                        f"({done}+{reject}) melebihi qty_in ({qty_in})"
                    ),
                }
            )
        available = article.qty if index == 0 else (previous_done or 0)
        if available is not None and qty_in > available:
            issues.append(
                {
                    "code": "QTY_IN_EXCEEDS_UPSTREAM",
                    "process": process,
                    "detail": (
                        f"{process} artikel {article.article_code}: qty_in {qty_in} "
                        f"melebihi sumber sah {available}"
                    ),
                }
            )
        previous_done = done
    return issues


def _step_actions(process, bucket, route, sequence, actor_role, target_date, today) -> dict:
    """Aksi yang boleh dijalankan aktor ini pada satu langkah, plus alasannya.

    Revisi #53: papan tidak boleh hanya menampilkan status. Ia harus menyatakan
    aksi mana yang sah, siapa yang berwenang, dan apa yang menghalangi — supaya
    COO bisa melihat proses mana yang macet bukan karena kerja, tapi karena
    wewenang yang tidak ada di lantai.

    Aksi HANDOFF dinilai dengan parameter yang WAJAR untuk langkah ini
    (tujuan = proses berikutnya di rute, qty = qty_done langkah ini), bukan
    dengan payload kosong. Kalau tidak, HANDOFF akan selalu tampak dilarang
    hanya karena papan tidak menerima input — dan itu membuat papan berbohong.
    Blocker yang tersisa (mis. tidak ada qty untuk dikirim) tetap dilaporkan
    apa adanya.
    """
    qty_in = _num(bucket["qty_in"]) if bucket else 0
    qty_done = _num(bucket["qty_done"]) if bucket else 0
    qty_reject = _num(bucket["qty_reject"]) if bucket else 0
    view = {
        "process": process,
        "sequence": sequence,
        "qty_in": qty_in,
        "qty_done": qty_done,
        "qty_reject": qty_reject,
        "statuses": sorted(bucket["statuses"]) if bucket else [],
        "process_upper": process,
    }
    # Tujuan handoff yang wajar: proses berikutnya yang benar-benar ada di rute.
    route_upper = [str(p).strip().upper() for p in route]
    here = next((i for i, p in enumerate(route_upper)
                 if p == str(process).strip().upper()), None)
    default_to_process = (
        route_upper[here + 1] if here is not None and here + 1 < len(route_upper) else None
    )
    # Qty yang wajar dikirim: output proses ini (jika belum ada, biarkan 0
    # supaya blocker QTY_SENT_REQUIRED yang jujur yang muncul).
    default_qty_sent = qty_done if qty_done > 0 else 0

    steps = []
    for action in coo_actions.ALLOWED_ACTIONS:
        verdict = coo_actions.evaluate(
            action,
            actor_role,
            bucket=view,
            target_date=target_date,
            today=today,
            route=route,
            qty_sent=default_qty_sent if action == coo_actions.HANDOFF else 0,
            to_process=default_to_process if action == coo_actions.HANDOFF else None,
        )
        steps.append(
            {
                "action": action,
                "allowed": verdict["allowed"],
                # Kalau aktor bukan pemegang kewenangan, papan tetap menunjukkan
                # siapa yang harus memicunya — bukan sekadar tombol mati.
                "authorised": verdict["allowed"] or all(
                    b["code"] != "ROLE_NOT_AUTHORISED" for b in verdict["blockers"]
                ),
                "roles": verdict["roles"],
                "required_fields": verdict["required_fields"],
                "reason_required": verdict["reason_required"],
                "to_status": verdict["to_status"],
                "blockers": verdict["blockers"],
            }
        )
    for entry, action in zip(steps, coo_actions.ALLOWED_ACTIONS):
        if action == coo_actions.HANDOFF:
            # Supaya UI tidak perlu menebak: papan menyebut tujuan & qty yang
            # dinilainya, dan ui bisa membandingkan dengan input operator.
            entry["evaluated_with"] = {
                "to_process": default_to_process,
                "qty_sent": default_qty_sent,
            }
    allowed_here = [s["action"] for s in steps if s["allowed"]]
    return {
        "actions": steps,
        "allowed_actions": allowed_here,
        "authorised_roles": sorted(
            {r for action in coo_actions.ALLOWED_ACTIONS for r in coo_actions.roles_for(action)}
        ),
    }


def _daily_execution_row(article, order, route, buckets_for_article, today,
                         actor_role="COO_MANAGER") -> dict:
    steps = []
    target_today = 0
    realised_today = 0
    total_in = total_done = total_reject = total_wip = 0
    for sequence, process in enumerate(route, start=1):
        bucket = buckets_for_article.get(process)
        qty_in = _num(bucket["qty_in"]) if bucket else 0
        done = _num(bucket["qty_done"]) if bucket else 0
        reject = _num(bucket["qty_reject"]) if bucket else 0
        wip = qty_in - done - reject
        due_today = bool(
            bucket and any(d == today for d in bucket["target_dates"])
        )
        # Target hari ini hanya dihitung dari langkah yang jatuh tempo hari ini,
        # bukan dari seluruh order — kalau tidak, papan selalu tampak terlambat.
        step_target = qty_in if due_today else 0
        target_today += step_target
        if due_today:
            realised_today += done
        total_in += qty_in
        total_done += done
        total_reject += reject
        total_wip += max(wip, 0)
        movement_ids = sorted(bucket["movement_ids"]) if bucket else []
        steps.append(
            {
                "process": process,
                "sequence": sequence,
                "status": _status_from_bucket(bucket) if bucket else "NOT_STARTED",
                "qty_in": qty_in,
                "qty_done": done,
                "qty_reject": reject,
                "qty_wip": wip,
                "target_today": step_target,
                "realised_today": done if due_today else 0,
                "due_today": due_today,
                "target_dates": sorted({d.isoformat() for d in (bucket["target_dates"] if bucket else [])}),
                "pic_names": sorted(bucket["pics"]) if bucket else [],
                "movement_ids": movement_ids,
                "reject_reasons": bucket["reject_reasons"] if bucket else [],
                "balanced": wip >= 0,
                # Revisi #54: WIP bukan angka tebakan. Setiap langkah menyebut
                # transaksi sumbernya, jadi angka di papan bisa ditelusuri
                # sampai movement id dan qty mentahnya.
                "wip_source": {
                    "movement_ids": movement_ids,
                    "formula": "qty_in - qty_done - qty_reject",
                    "qty_in": qty_in,
                    "qty_done": done,
                    "qty_reject": reject,
                    "derived": True,
                    "derived_from": f"production_movements{tuple(movement_ids)}" if movement_ids else None,
                },
                # Revisi #53: aksi yang sah di langkah ini + siapa yang berwenang.
                "actions": _step_actions(process, bucket, route, sequence, actor_role,
                                         bucket["target_dates"][0] if bucket and bucket["target_dates"] else None,
                                         today),
            }
        )
    return {
        "order_id": order.order_id,
        "buyer": order.buyer,
        "overall_status": order.overall_status,
        "article_id": article.id,
        "article_code": article.article_code,
        "garment_type": article.garment_type,
        "production_route": " > ".join(route),
        "article_qty": _num(article.qty),
        "target_today": target_today,
        "realised_today": realised_today,
        "attainment_percent": round(realised_today / target_today * 100, 1) if target_today else None,
        "qty_in": total_in,
        "qty_done": total_done,
        "qty_reject": total_reject,
        "qty_wip": total_wip,
        "balanced": total_in == total_done + total_reject + total_wip,
        "steps": steps,
    }


@router.get("/daily-execution")
def daily_execution(
    order_fk: Optional[int] = Query(None),
    on_date: Optional[date] = Query(None, description="Tanggal eksekusi; default hari ini"),
    db: Session = Depends(get_db),
    user=Depends(require_roles(*EXEC_ROLES)),
):
    """Papan eksekusi harian: target vs realisasi per order/artikel.

    Revisi #53: hanya menampilkan langkah yang eligible dari rute aktif artikel,
    dan setiap angka membawa identitas transaksi sumbernya.
    """
    today = on_date or date.today()

    query = (
        db.query(Article, Order)
        .join(Order, Order.id == Article.order_fk)
        .filter(Order.overall_status != "CLOSED")
    )
    if order_fk is not None:
        query = query.filter(Article.order_fk == order_fk)
    article_pairs = query.order_by(Order.id, Article.id).all()

    article_ids = [a.id for a, _ in article_pairs]
    movements = []
    if article_ids:
        movements = (
            db.query(ProductionMovement)
            .filter(ProductionMovement.article_id.in_(article_ids))
            .order_by(ProductionMovement.id)
            .all()
        )
    rollup = _movement_rollup(db, movements)
    actor_role = role_of(user)

    rows = []
    for article, order in article_pairs:
        route = route_for(article)
        buckets_for_article = {
            process: rollup[(article.id, process)]
            for process in route
            if (article.id, process) in rollup
        }
        # Masukkan juga proses yang tercatat tapi tidak ada di rute, supaya
        # eksekusi liar tidak hilang dari papan.
        for (aid, process), bucket in rollup.items():
            if aid == article.id and process not in buckets_for_article:
                buckets_for_article[process] = bucket
        row = _daily_execution_row(article, order, route, buckets_for_article, today,
                                   actor_role=actor_role)
        row["reconciliation"] = _article_reconciliation(article, buckets_for_article)
        rows.append(row)

    totals = {
        "articles": len(rows),
        "target_today": sum(r["target_today"] for r in rows),
        "realised_today": sum(r["realised_today"] for r in rows),
        "qty_in": sum(r["qty_in"] for r in rows),
        "qty_done": sum(r["qty_done"] for r in rows),
        "qty_reject": sum(r["qty_reject"] for r in rows),
        "qty_wip": sum(r["qty_wip"] for r in rows),
        "unbalanced_articles": sum(0 if r["balanced"] else 1 for r in rows),
        "reconciliation_issues": sum(len(r["reconciliation"]) for r in rows),
    }
    totals["attainment_percent"] = (
        round(totals["realised_today"] / totals["target_today"] * 100, 1)
        if totals["target_today"]
        else None
    )
    return {
        "as_of": today.isoformat(),
        "generated_at": datetime.now(timezone.utc),
        "actor_role": role_of(user),
        "invariant": "qty_in = qty_done + qty_reject + wip",
        # Hanya tindakan server-side yang diizinkan; tidak ada pilihan bebas.
        "allowed_actions": list(coo_actions.ALLOWED_ACTIONS),
        "action_contract": coo_actions.contract_payload(role_of(user)),
        "totals": totals,
        "rows": rows,
    }


def _handoff_edges(db: Session, article_pairs):
    """Derive handoff antar proses dari selisih done upstream vs in downstream.

    Revisi #54: handoff harus terlihat dengan FROM, TO, qty sent, qty received,
    dan discrepancy. Ledger existing tidak punya tabel handoff tersendiri, jadi
    edge direkonstruksi dari transaksi proses yang berurutan dan discrepancy
    dihitung sebagai selisih yang belum diterima proses berikutnya.
    """
    edges = []
    for article, order in article_pairs:
        route = route_for(article)
        if len(route) < 2:
            continue
        movements = (
            db.query(ProductionMovement)
            .filter(ProductionMovement.article_id == article.id)
            .order_by(ProductionMovement.id)
            .all()
        )
        rollup = _movement_rollup(db, movements)
        for index in range(len(route) - 1):
            source, target = route[index], route[index + 1]
            source_bucket = rollup.get((article.id, source))
            target_bucket = rollup.get((article.id, target))
            sent = _num(source_bucket["qty_done"]) if source_bucket else 0
            received = _num(target_bucket["qty_in"]) if target_bucket else 0
            discrepancy = received - sent
            if sent == 0 and received == 0:
                continue
            edges.append(
                {
                    "order_id": order.order_id,
                    "article_id": article.id,
                    "article_code": article.article_code,
                    "from_process": source,
                    "to_process": target,
                    "qty_sent": sent,
                    "qty_received": received,
                    "discrepancy": discrepancy,
                    "remaining_balance": sent - received,
                    "status": (
                        "MATCHED"
                        if discrepancy == 0
                        else "PENDING_RECEIPT"
                        if discrepancy < 0
                        else "OVER_RECEIPT"
                    ),
                    "sender_pics": sorted(source_bucket["pics"]) if source_bucket else [],
                    "receiver_pics": sorted(target_bucket["pics"]) if target_bucket else [],
                    "movement_ids_sent": sorted(source_bucket["movement_ids"]) if source_bucket else [],
                    "movement_ids_received": sorted(target_bucket["movement_ids"]) if target_bucket else [],
                    # Revisi #54: setiap edge menyebut transaksi sumbernya, jadi
                    # qty sent/received bisa ditelusuri ke movement id — bukan
                    # angka rekonstruksi tanpa asal-usul.
                    "qty_source": {
                        "sent_from": "production_movements.qty_done",
                        "received_from": "production_movements.qty_in",
                        "sent_movement_ids": sorted(source_bucket["movement_ids"]) if source_bucket else [],
                        "received_movement_ids": sorted(target_bucket["movement_ids"]) if target_bucket else [],
                        "persisted": False,
                        "persistence_note": (
                            "Edge direkonstruksi dari urutan ProductionMovement; "
                            "tabel production_handoffs belum ada sehingga "
                            "batch_no/evidence_ref/shift/location belum tersimpan"
                        ),
                    },
                }
            )
    return edges


def _capacity_rows(db: Session, today: date, article_pairs):
    """Kapasitas terpakai vs tersedia per proses dari capacity_snapshots.

    commited load = sisa qty_in yang belum selesai (WIP terbuka) per proses,
    jadi utilization dihitung dari beban nyata di lantai, bukan dari angka
    yang diketik ulang.
    """
    article_ids = [a.id for a, _ in article_pairs]
    open_load = {}
    if article_ids:
        rows = (
            db.query(
                ProductionMovement.process,
                func.sum(
                    ProductionMovement.qty_in
                    - ProductionMovement.qty_done
                    - ProductionMovement.qty_reject
                ),
            )
            .filter(
                ProductionMovement.article_id.in_(article_ids),
                func.upper(ProductionMovement.status).in_(sorted(OPEN_STATUSES)),
            )
            .group_by(ProductionMovement.process)
            .all()
        )
        open_load = {(p or "").upper(): _num(q) for p, q in rows}

    # Ambil snapshot terbaru per proses yang tidak melewati tanggal papan.
    snapshots = (
        db.query(CapacitySnapshot)
        .filter(CapacitySnapshot.snapshot_date <= today)
        .order_by(CapacitySnapshot.snapshot_date.desc(), CapacitySnapshot.id.desc())
        .all()
    )
    latest = {}
    for snap in snapshots:
        latest.setdefault((snap.process or "").upper(), snap)

    rows = []
    for process in sorted(set(latest) | set(open_load)):
        snap = latest.get(process)
        capacity = _num(snap.capacity) if snap else None
        planned_load = _num(snap.planned_load) if snap else None
        committed = open_load.get(process, 0)
        is_stale = not snap or snap.snapshot_date != today
        # Utilization dihitung dari beban terkomitmen nyata, bukan dari
        # planned_load yang bisa kedaluwarsa.
        utilization = round(committed / capacity * 100, 1) if capacity else None
        rows.append(
            {
                "process": process,
                "snapshot_date": snap.snapshot_date.isoformat() if snap and snap.snapshot_date else None,
                "period": "DAY",
                "capacity_per_day": capacity,
                "available_capacity": max(capacity - committed, 0) if capacity is not None else None,
                "committed_load": committed,
                "planned_load": planned_load,
                "current_wip": committed,
                "queue": max(committed - (capacity or 0), 0) if capacity is not None else None,
                "utilization_percent": utilization,
                "is_stale": is_stale,
                "conflict": bool(utilization is not None and utilization > CAPACITY_CONFLICT_PCT),
                "source": "capacity_snapshots" if snap else "NO_SNAPSHOT",
                "snapshot_id": snap.id if snap else None,
            }
        )
    return rows


@router.get("/handoff-capacity")
def handoff_capacity(
    order_fk: Optional[int] = Query(None),
    on_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    user=Depends(require_roles(*EXEC_ROLES)),
):
    """Handoff antar proses + kapasitas terpakai vs tersedia."""
    today = on_date or date.today()

    query = (
        db.query(Article, Order)
        .join(Order, Order.id == Article.order_fk)
        .filter(Order.overall_status != "CLOSED")
    )
    if order_fk is not None:
        query = query.filter(Article.order_fk == order_fk)
    article_pairs = query.order_by(Order.id, Article.id).all()

    edges = _handoff_edges(db, article_pairs)
    capacity = _capacity_rows(db, today, article_pairs)

    # Discrepancy handoff dan konflik kapasitas wajib terlihat sebagai
    # tindak lanjut, bukan hanya tabel yang lewat.
    discrepancies = [e for e in edges if e["discrepancy"] != 0]
    conflicts = [c for c in capacity if c["conflict"]]
    bottlenecks = sorted(
        [c for c in capacity if c["utilization_percent"] is not None],
        key=lambda c: c["utilization_percent"],
        reverse=True,
    )
    return {
        "as_of": today.isoformat(),
        "generated_at": datetime.now(timezone.utc),
        "actor_role": role_of(user),
        "handoffs": edges,
        "capacity": capacity,
        "summary": {
            "handoff_count": len(edges),
            "discrepancy_count": len(discrepancies),
            "total_discrepancy": sum(e["discrepancy"] for e in edges),
            "capacity_rows": len(capacity),
            "conflict_count": len(conflicts),
            "bottleneck_process": bottlenecks[0]["process"] if bottlenecks else None,
            "stale_snapshots": sum(1 for c in capacity if c["is_stale"]),
        },
        "follow_ups": [
            {
                "kind": "HANDOFF_DISCREPANCY",
                "order_id": e["order_id"],
                "article_code": e["article_code"],
                "from_process": e["from_process"],
                "to_process": e["to_process"],
                "discrepancy": e["discrepancy"],
                "detail": (
                    f"Qty dikirim {e['qty_sent']} vs diterima {e['qty_received']} "
                    f"({e['status']}) pada {e['article_code']}"
                ),
            }
            for e in discrepancies
        ]
        + [
            {
                "kind": "CAPACITY_CONFLICT",
                "process": c["process"],
                "utilization_percent": c["utilization_percent"],
                "committed_load": c["committed_load"],
                "capacity_per_day": c["capacity_per_day"],
                "detail": (
                    f"{c['process']} terpakai {c['utilization_percent']}% "
                    f"({c['committed_load']}/{c['capacity_per_day']})"
                ),
            }
            for c in conflicts
        ],
    }


def _bom_budget_rows(db: Session, order_fk: Optional[int]):
    """Rencana vs pemakaian fisik per item BOM, dengan selisih yang terlihat.

    Revisi #57: Siti mencatat pemakaian fisik; unit cost & valuasi tetap milik
    CFO, jadi baris ini hanya mengekspos angka biaya sebagai referensi
    read-only, bukan sebagai input.
    """
    query = db.query(BOMItem).join(Article, Article.id == BOMItem.article_id)
    if order_fk is not None:
        query = query.filter(Article.order_fk == order_fk)
    items = query.order_by(BOMItem.id).all()
    if not items:
        return []

    item_ids = [i.id for i in items]
    actual_rows = (
        db.query(
            MaterialConsumption.bom_item_id,
            func.sum(MaterialConsumption.qty),
            func.sum(MaterialConsumption.qty * MaterialConsumption.actual_unit_cost),
        )
        .filter(MaterialConsumption.bom_item_id.in_(item_ids))
        .group_by(MaterialConsumption.bom_item_id)
        .all()
    )
    actual = {bid: (_dec(q), _dec(cost)) for bid, q, cost in actual_rows}

    articles = {a.id: a for a in db.query(Article).filter(Article.id.in_(
        sorted({i.article_id for i in items}))).all()}
    orders = {o.id: o for o in db.query(Order).filter(Order.id.in_(
        sorted({a.order_fk for a in articles.values()}))).all()}

    rows = []
    for item in items:
        article = articles.get(item.article_id)
        order = orders.get(article.order_fk) if article else None
        article_qty = _num(article.qty) if article else 0
        planned_qty = float(Decimal(str(item.qty_per_unit or 0)) * article_qty)
        planned_unit_cost = _dec(item.planned_unit_cost)
        planned_cost = planned_qty * planned_unit_cost
        actual_qty, actual_cost = actual.get(item.id, (0.0, 0.0))
        difference_qty = round(actual_qty - planned_qty, 4)
        rows.append(
            {
                "bom_item_id": item.id,
                "order_id": order.order_id if order else None,
                "order_fk": order.id if order else None,
                "article_id": item.article_id,
                "article_code": article.article_code if article else None,
                "article_qty": article_qty,
                "material_name": item.material_name,
                "unit": item.unit,
                "qty_per_unit": _dec(item.qty_per_unit),
                "planned_qty": round(planned_qty, 4),
                "actual_qty": round(actual_qty, 4),
                "difference_qty": difference_qty,
                "variance_percent": round(difference_qty / planned_qty * 100, 1) if planned_qty else None,
                "status": (
                    "MATCH"
                    if abs(difference_qty) < 1e-9
                    else "OVER_USAGE"
                    if difference_qty > 0
                    else "UNDER_USAGE"
                ),
                # Biaya hanya referensi read-only untuk Siti (revisi #57).
                "planned_unit_cost": planned_unit_cost,
                "planned_cost": round(planned_cost, 2),
                "actual_cost": round(actual_cost, 2),
                "difference_cost": round(actual_cost - planned_cost, 2),
                "cost_field_access": "READ_ONLY",
            }
        )
    return rows


@router.get("/bom-physical")
def bom_physical(
    order_fk: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    user=Depends(require_roles(*EXEC_ROLES)),
):
    """Pemakaian BOM fisik dibanding rencana, lengkap dengan selisih."""
    rows = _bom_budget_rows(db, order_fk)
    over = [r for r in rows if r["status"] == "OVER_USAGE"]
    return {
        "as_of": date.today().isoformat(),
        "generated_at": datetime.now(timezone.utc),
        "actor_role": role_of(user),
        "cost_access": "READ_ONLY",
        "summary": {
            "items": len(rows),
            "planned_qty": round(sum(r["planned_qty"] for r in rows), 4),
            "actual_qty": round(sum(r["actual_qty"] for r in rows), 4),
            "difference_qty": round(sum(r["difference_qty"] for r in rows), 4),
            "over_usage_items": len(over),
            "planned_cost": round(sum(r["planned_cost"] for r in rows), 2),
            "actual_cost": round(sum(r["actual_cost"] for r in rows), 2),
            "difference_cost": round(sum(r["difference_cost"] for r in rows), 2),
        },
        "rows": rows,
    }
