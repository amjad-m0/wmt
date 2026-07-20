from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime
import io
from app.database import get_db
from app.auth import require_login, require_admin
from app.models.models import Return, Order, Material, User, ReturnClassification, AuditAction, MaintenanceStatus
from app.services.pdf_service import generate_return_receipt
from app.services.audit_service import log_action
from app.services.reference_code_service import generate_reference_code
from app.services.number_utils import round_qty

router = APIRouter(prefix="/returns", tags=["returns"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def list_returns(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    returns = db.query(Return).filter(Return.is_deleted == False).order_by(Return.created_at.desc()).all()
    return templates.TemplateResponse("returns/list.html", {
        "request": request, "returns": returns, "current_user": current_user,
        "ReturnClassification": ReturnClassification, "MaintenanceStatus": MaintenanceStatus
    })


@router.get("/add", response_class=HTMLResponse)
async def add_return_page(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    orders = db.query(Order).filter(Order.is_deleted == False).order_by(Order.order_number).all()
    materials = db.query(Material).filter(Material.is_deleted == False).order_by(Material.name).all()
    return templates.TemplateResponse("returns/add.html", {
        "request": request, "current_user": current_user, "orders": orders, "materials": materials,
        "ReturnClassification": ReturnClassification, "error": None
    })


@router.post("/add")
async def add_return(
    request: Request,
    order_id: int = Form(...),
    material_id: int = Form(...),
    quantity: float = Form(...),
    return_classification: str = Form(...),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login)
):
    orders = db.query(Order).filter(Order.is_deleted == False).all()
    materials_list = db.query(Material).filter(Material.is_deleted == False).all()

    material = db.query(Material).filter(Material.id == material_id, Material.is_deleted == False).first()
    if not material:
        return templates.TemplateResponse("returns/add.html", {
            "request": request, "current_user": current_user, "orders": orders, "materials": materials_list,
            "ReturnClassification": ReturnClassification, "error": "المادة غير موجودة"
        })

    classification = ReturnClassification(return_classification)
    qty = round_qty(quantity)

    ret = Return(
        order_id=order_id, material_id=material_id, quantity=qty,
        return_classification=classification, supervisor_id=current_user.id, notes=notes,
        maintenance_status=MaintenanceStatus.pending if classification == ReturnClassification.maintenance else None
    )
    db.add(ret)

    if classification == ReturnClassification.reuse:
        material.current_stock = round_qty(material.current_stock + qty)

    db.flush()
    ret.reference_code = generate_reference_code(db, Return, "return")
    log_action(db, AuditAction.create, "return", ret.id, current_user.id,
               after_data={"material_id": material_id, "quantity": qty, "classification": return_classification},
               description=f"مرتجع {qty} من {material.name} - {return_classification}")
    db.commit()
    return RedirectResponse(url="/returns/", status_code=302)


@router.post("/{return_id}/close")
async def close_maintenance(
    return_id: int,
    action: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login)
):
    ret = db.query(Return).filter(Return.id == return_id, Return.is_deleted == False).first()
    if not ret:
        raise HTTPException(status_code=404, detail="السجل غير موجود")
    if ret.return_classification != ReturnClassification.maintenance:
        raise HTTPException(status_code=400, detail="هذا الإجراء متاح فقط لمرتجعات الصيانة")
    if ret.maintenance_status != MaintenanceStatus.pending:
        raise HTTPException(status_code=400, detail="تم إغلاق هذا السجل مسبقاً")

    if action == "repaired":
        ret.maintenance_status = MaintenanceStatus.repaired
        ret.material.current_stock = round_qty(ret.material.current_stock + ret.quantity)
    elif action == "scrapped":
        ret.maintenance_status = MaintenanceStatus.scrapped
    else:
        raise HTTPException(status_code=400, detail="إجراء غير معروف")

    ret.closed_at = datetime.utcnow()
    ret.closed_by_id = current_user.id

    log_action(db, AuditAction.edit, "return", ret.id, current_user.id,
               before_data={"maintenance_status": "pending"},
               after_data={"maintenance_status": action},
               description=f"إغلاق أمر صيانة رقم {return_id} - {action}")
    db.commit()
    return RedirectResponse(url="/returns/", status_code=302)


@router.get("/{return_id}/receipt")
async def return_receipt(return_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    ret = db.query(Return).filter(Return.id == return_id).first()
    if not ret:
        raise HTTPException(status_code=404, detail="السجل غير موجود")
    pdf_bytes = generate_return_receipt(ret)
    return StreamingResponse(
        io.BytesIO(pdf_bytes), media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=return_{return_id}.pdf"}
    )


@router.post("/{return_id}/delete")
async def delete_return(return_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    ret = db.query(Return).filter(Return.id == return_id, Return.is_deleted == False).first()
    if not ret:
        raise HTTPException(status_code=404, detail="السجل غير موجود")
    if ret.return_classification == ReturnClassification.reuse:
        ret.material.current_stock = round_qty(ret.material.current_stock - ret.quantity)
    elif ret.return_classification == ReturnClassification.maintenance and ret.maintenance_status == MaintenanceStatus.repaired:
        ret.material.current_stock = round_qty(ret.material.current_stock - ret.quantity)
    ret.is_deleted = True
    log_action(db, AuditAction.delete, "return", ret.id, current_user.id,
               description=f"حذف مرتجع رقم {return_id}")
    db.commit()
    return RedirectResponse(url="/returns/", status_code=302)
