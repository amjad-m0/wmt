from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime
import io
import json
from app.database import get_db
from app.auth import require_login, require_admin
from app.models.models import Issuance, Order, Material, OrderMaterial, User, AuditAction, IssuanceType
from app.services.pdf_service import generate_issuance_receipt
from app.services.audit_service import log_action
from app.services.reference_code_service import generate_reference_code
from app.services.number_utils import round_qty

router = APIRouter(prefix="/issuances", tags=["issuances"])
templates = Jinja2Templates(directory="app/templates")


def _build_order_materials_map(db: Session):
    order_materials = db.query(OrderMaterial).all()
    order_map = {}
    for om in order_materials:
        order_map.setdefault(om.order_id, []).append({
            "id": om.material_id, "name": om.material.name, "unit": om.material.unit.value
        })
    general_stock = db.query(Material).filter(Material.is_deleted == False, Material.is_general_stock == True).all()
    general_list = [{"id": m.id, "name": m.name, "unit": m.unit.value} for m in general_stock]
    return order_map, general_list


@router.get("/", response_class=HTMLResponse)
async def list_issuances(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    issuances = db.query(Issuance).filter(Issuance.is_deleted == False).order_by(Issuance.created_at.desc()).all()
    return templates.TemplateResponse("orders/issuances.html", {
        "request": request, "issuances": issuances, "current_user": current_user
    })


@router.get("/add", response_class=HTMLResponse)
async def add_issuance_page(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    orders = db.query(Order).filter(Order.is_deleted == False).order_by(Order.order_number).all()
    materials = db.query(Material).filter(Material.is_deleted == False).order_by(Material.name).all()
    order_map, general_list = _build_order_materials_map(db)
    return templates.TemplateResponse("orders/add_issuance.html", {
        "request": request, "current_user": current_user, "orders": orders, "materials": materials,
        "IssuanceType": IssuanceType,
        "order_materials_json": json.dumps(order_map), "general_stock_json": json.dumps(general_list),
        "error": None
    })


@router.post("/add")
async def add_issuance(
    request: Request,
    order_id: int = Form(...),
    material_id: int = Form(...),
    quantity: float = Form(...),
    driver_name: str = Form(...),
    recipient_name: str = Form(...),
    issuance_type: str = Form(...),
    mdr_number: Optional[str] = Form(None),
    is_from_general_stock: bool = Form(False),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login)
):
    orders = db.query(Order).filter(Order.is_deleted == False).all()
    materials = db.query(Material).filter(Material.is_deleted == False).all()
    order_map, general_list = _build_order_materials_map(db)

    def error(msg):
        return templates.TemplateResponse("orders/add_issuance.html", {
            "request": request, "current_user": current_user, "orders": orders, "materials": materials,
            "IssuanceType": IssuanceType,
            "order_materials_json": json.dumps(order_map), "general_stock_json": json.dumps(general_list),
            "error": msg
        })

    material = db.query(Material).filter(Material.id == material_id, Material.is_deleted == False).first()
    if not material:
        return error("المادة غير موجودة")

    qty = round_qty(quantity)
    if material.current_stock < qty:
        return error(f"الكمية المطلوبة ({qty}) تتجاوز المخزون المتاح ({material.current_stock})")

    material.current_stock = round_qty(material.current_stock - qty)

    om = db.query(OrderMaterial).filter(OrderMaterial.order_id == order_id, OrderMaterial.material_id == material_id).first()
    if om:
        om.quantity_issued = round_qty(om.quantity_issued + qty)

    issuance = Issuance(
        order_id=order_id, material_id=material_id, quantity=qty,
        supervisor_id=current_user.id, driver_name=driver_name, recipient_name=recipient_name,
        issuance_type=IssuanceType(issuance_type), mdr_number=mdr_number,
        is_from_general_stock=is_from_general_stock, notes=notes
    )
    db.add(issuance)
    db.flush()
    issuance.reference_code = generate_reference_code(db, Issuance, "issuance")

    log_action(db, AuditAction.create, "issuance", issuance.id, current_user.id,
               after_data={"material_id": material_id, "quantity": qty, "order_id": order_id, "issuance_type": issuance_type},
               description=f"إصدار {qty} {material.unit.value} من {material.name}")
    db.commit()
    return RedirectResponse(url="/issuances/", status_code=302)


@router.post("/{issuance_id}/return-to-stock")
async def return_to_stock(issuance_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    """استرجاع عدة (Tool) اتصرفت كعهدة مؤقتة - المستهلكات ميظهرش لها الزرار ده أصلاً"""
    issuance = db.query(Issuance).filter(Issuance.id == issuance_id, Issuance.is_deleted == False).first()
    if not issuance:
        raise HTTPException(status_code=404, detail="السجل غير موجود")
    if issuance.material.category.value != "tool":
        raise HTTPException(status_code=400, detail="الاسترجاع متاح للعدد فقط")
    if issuance.issuance_type.value != "personal_custody_temporary":
        raise HTTPException(status_code=400, detail="الاسترجاع متاح للعهدة المؤقتة فقط")
    if issuance.is_returned_to_stock:
        raise HTTPException(status_code=400, detail="تم استرجاع هذه العدة مسبقاً")

    issuance.is_returned_to_stock = True
    issuance.returned_to_stock_at = datetime.utcnow()
    issuance.material.current_stock = round_qty(issuance.material.current_stock + issuance.quantity)

    log_action(db, AuditAction.edit, "issuance", issuance.id, current_user.id,
               after_data={"is_returned_to_stock": True},
               description=f"استرجاع عدة للمخزون العام: {issuance.material.name}")
    db.commit()
    return RedirectResponse(url="/issuances/", status_code=302)


@router.get("/{issuance_id}/receipt")
async def issuance_receipt(issuance_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    issuance = db.query(Issuance).filter(Issuance.id == issuance_id).first()
    if not issuance:
        raise HTTPException(status_code=404, detail="السجل غير موجود")
    pdf_bytes = generate_issuance_receipt(issuance)
    return StreamingResponse(
        io.BytesIO(pdf_bytes), media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=issuance_{issuance_id}.pdf"}
    )


@router.post("/{issuance_id}/delete")
async def delete_issuance(issuance_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    issuance = db.query(Issuance).filter(Issuance.id == issuance_id, Issuance.is_deleted == False).first()
    if not issuance:
        raise HTTPException(status_code=404, detail="السجل غير موجود")
    if not issuance.is_returned_to_stock:
        issuance.material.current_stock = round_qty(issuance.material.current_stock + issuance.quantity)
    om = db.query(OrderMaterial).filter(OrderMaterial.order_id == issuance.order_id, OrderMaterial.material_id == issuance.material_id).first()
    if om:
        om.quantity_issued = round_qty(max(0, om.quantity_issued - issuance.quantity))
    issuance.is_deleted = True
    log_action(db, AuditAction.delete, "issuance", issuance.id, current_user.id,
               description=f"حذف إصدار: {issuance.quantity} من {issuance.material.name}")
    db.commit()
    return RedirectResponse(url="/issuances/", status_code=302)
