from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from typing import Optional
from datetime import datetime
from app.database import get_db
from app.auth import require_login
from app.models.models import (Order, Material, Issuance, Borrowing,
                                  Transfer, Return, AuditLog, User)

router = APIRouter(prefix="/search", tags=["search"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def search_page(
    request: Request,
    q: Optional[str] = Query(None),
    entity_type: Optional[str] = Query(None),
    supervisor_id: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login)
):
    results = {"orders": [], "materials": [], "issuances": [],
               "borrowings": [], "transfers": [], "returns": []}

    supervisors = db.query(User).filter(User.is_active == True).all()

    date_from_dt = None
    date_to_dt = None
    if date_from:
        try:
            date_from_dt = datetime.strptime(date_from, "%Y-%m-%d")
        except:
            pass
    if date_to:
        try:
            date_to_dt = datetime.strptime(date_to, "%Y-%m-%d")
        except:
            pass

    if q or entity_type or supervisor_id or date_from or date_to:

        # Search Orders
        if not entity_type or entity_type == "orders":
            order_q = db.query(Order).filter(Order.is_deleted == False)
            if q:
                order_q = order_q.filter(
                    or_(Order.order_number.ilike(f"%{q}%"),
                        Order.notes.ilike(f"%{q}%"),
                        Order.driver_name.ilike(f"%{q}%"))
                )
            if supervisor_id:
                order_q = order_q.filter(
                    or_(Order.receiving_supervisor_id == supervisor_id,
                        Order.issuing_supervisor_id == supervisor_id)
                )
            if date_from_dt:
                order_q = order_q.filter(Order.created_at >= date_from_dt)
            if date_to_dt:
                order_q = order_q.filter(Order.created_at <= date_to_dt)
            results["orders"] = order_q.order_by(Order.created_at.desc()).limit(50).all()

        # Search Materials
        if not entity_type or entity_type == "materials":
            mat_q = db.query(Material).filter(Material.is_deleted == False)
            if q:
                mat_q = mat_q.filter(
                    or_(Material.name.ilike(f"%{q}%"),
                        Material.description.ilike(f"%{q}%"))
                )
            if supervisor_id:
                mat_q = mat_q.filter(Material.holder_id == supervisor_id)
            results["materials"] = mat_q.order_by(Material.name).limit(50).all()

        # Search Issuances
        if not entity_type or entity_type == "issuances":
            iss_q = db.query(Issuance).filter(Issuance.is_deleted == False)
            if supervisor_id:
                iss_q = iss_q.filter(Issuance.supervisor_id == supervisor_id)
            if date_from_dt:
                iss_q = iss_q.filter(Issuance.created_at >= date_from_dt)
            if date_to_dt:
                iss_q = iss_q.filter(Issuance.created_at <= date_to_dt)
            results["issuances"] = iss_q.order_by(Issuance.created_at.desc()).limit(50).all()

        # Search Borrowings
        if not entity_type or entity_type == "borrowings":
            bor_q = db.query(Borrowing).filter(Borrowing.is_deleted == False)
            if supervisor_id:
                bor_q = bor_q.filter(
                    or_(Borrowing.borrowing_supervisor_id == supervisor_id,
                        Borrowing.source_supervisor_id == supervisor_id)
                )
            if date_from_dt:
                bor_q = bor_q.filter(Borrowing.created_at >= date_from_dt)
            if date_to_dt:
                bor_q = bor_q.filter(Borrowing.created_at <= date_to_dt)
            results["borrowings"] = bor_q.order_by(Borrowing.created_at.desc()).limit(50).all()

        # Search Transfers
        if not entity_type or entity_type == "transfers":
            tra_q = db.query(Transfer).filter(Transfer.is_deleted == False)
            if supervisor_id:
                tra_q = tra_q.filter(
                    or_(Transfer.from_supervisor_id == supervisor_id,
                        Transfer.to_supervisor_id == supervisor_id,
                        Transfer.witness_supervisor_id == supervisor_id)
                )
            if date_from_dt:
                tra_q = tra_q.filter(Transfer.created_at >= date_from_dt)
            if date_to_dt:
                tra_q = tra_q.filter(Transfer.created_at <= date_to_dt)
            results["transfers"] = tra_q.order_by(Transfer.created_at.desc()).limit(50).all()

        # Search Returns
        if not entity_type or entity_type == "returns":
            ret_q = db.query(Return).filter(Return.is_deleted == False)
            if supervisor_id:
                ret_q = ret_q.filter(Return.supervisor_id == supervisor_id)
            if date_from_dt:
                ret_q = ret_q.filter(Return.created_at >= date_from_dt)
            if date_to_dt:
                ret_q = ret_q.filter(Return.created_at <= date_to_dt)
            results["returns"] = ret_q.order_by(Return.created_at.desc()).limit(50).all()

    total = sum(len(v) for v in results.values())

    return templates.TemplateResponse("search/search.html", {
        "request": request, "current_user": current_user,
        "results": results, "total": total,
        "supervisors": supervisors,
        "q": q or "", "entity_type": entity_type or "",
        "supervisor_id": supervisor_id,
        "date_from": date_from or "", "date_to": date_to or ""
    })


@router.get("/audit", response_class=HTMLResponse)
async def audit_log(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login)
):
    from app.auth import require_admin
    from app.models.models import UserRole
    if current_user.role != UserRole.admin:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="للمدير فقط")

    logs = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(200).all()
    return templates.TemplateResponse("search/audit.html", {
        "request": request, "current_user": current_user, "logs": logs
    })
