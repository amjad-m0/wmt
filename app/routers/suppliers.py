from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime
from app.database import get_db
from app.auth import require_login, require_admin
from app.models.models import Supplier, User, AuditAction
from app.services.audit_service import log_action

router = APIRouter(prefix="/suppliers", tags=["suppliers"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def list_suppliers(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    suppliers = db.query(Supplier).filter(Supplier.is_deleted == False).order_by(Supplier.name).all()
    return templates.TemplateResponse("suppliers/list.html", {
        "request": request, "suppliers": suppliers, "current_user": current_user
    })


@router.get("/add", response_class=HTMLResponse)
async def add_supplier_page(request: Request, current_user: User = Depends(require_login)):
    return templates.TemplateResponse("suppliers/add.html", {
        "request": request, "current_user": current_user, "error": None
    })


@router.post("/add")
async def add_supplier(
    request: Request,
    name: str = Form(...),
    contact_person: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    agreement_date: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login)
):
    agreement_dt = None
    if agreement_date:
        try:
            agreement_dt = datetime.strptime(agreement_date, "%Y-%m-%d")
        except ValueError:
            pass

    supplier = Supplier(
        name=name,
        contact_person=contact_person,
        phone=phone,
        agreement_date=agreement_dt,
        notes=notes
    )
    db.add(supplier)
    db.flush()
    log_action(db, AuditAction.create, "supplier", supplier.id, current_user.id,
               after_data={"name": name, "contact_person": contact_person},
               description=f"إضافة مورد: {name}")
    db.commit()
    return RedirectResponse(url="/suppliers/", status_code=302)


@router.get("/{supplier_id}/edit", response_class=HTMLResponse)
async def edit_supplier_page(supplier_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id, Supplier.is_deleted == False).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="المورد غير موجود")
    return templates.TemplateResponse("suppliers/edit.html", {
        "request": request, "supplier": supplier, "current_user": current_user
    })


@router.post("/{supplier_id}/edit")
async def edit_supplier(
    supplier_id: int,
    name: str = Form(...),
    contact_person: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    agreement_date: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id, Supplier.is_deleted == False).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="المورد غير موجود")

    before = {"name": supplier.name, "phone": supplier.phone}

    agreement_dt = None
    if agreement_date:
        try:
            agreement_dt = datetime.strptime(agreement_date, "%Y-%m-%d")
        except ValueError:
            pass

    supplier.name = name
    supplier.contact_person = contact_person
    supplier.phone = phone
    supplier.agreement_date = agreement_dt
    supplier.notes = notes

    log_action(db, AuditAction.edit, "supplier", supplier.id, current_user.id,
               before_data=before,
               after_data={"name": name, "phone": phone},
               description=f"تعديل مورد: {name}")
    db.commit()
    return RedirectResponse(url="/suppliers/", status_code=302)


@router.post("/{supplier_id}/delete")
async def delete_supplier(supplier_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id, Supplier.is_deleted == False).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="المورد غير موجود")
    supplier.is_deleted = True
    supplier.deleted_at = datetime.utcnow()
    supplier.deleted_by_id = current_user.id
    log_action(db, AuditAction.delete, "supplier", supplier.id, current_user.id,
               description=f"حذف مورد: {supplier.name}")
    db.commit()
    return RedirectResponse(url="/suppliers/", status_code=302)
