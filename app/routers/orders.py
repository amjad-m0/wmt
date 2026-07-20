from fastapi import APIRouter, Depends, Request, Form, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional, List
import io
from datetime import datetime
from app.database import get_db
from app.auth import require_login, require_admin
from app.models.models import (Order, GatePass, GatePassMaterial, OrderMaterial,
                                 Material, User, OrderType, OrderStatus, AuditAction,
                                 MaterialCategory, MaterialUnit, Supplier)
from app.services.storage import upload_photo
from app.services.pdf_service import generate_order_receipt, generate_order_materials_receipt
from app.services.audit_service import log_action
from app.services.reference_code_service import generate_reference_code
from app.services.number_utils import round_qty
from app.services.order_material_service import upsert_order_material, get_order_material_remaining
from app.routers.materials import next_item_code

router = APIRouter(prefix="/orders", tags=["orders"])
templates = Jinja2Templates(directory="app/templates")


async def parse_material_rows(request: Request, db: Session, order: Order):
    form = await request.form()
    material_ids = form.getlist("gp_material_id")
    quantities = form.getlist("gp_quantity")
    new_names = form.getlist("gp_new_name")
    new_categories = form.getlist("gp_new_category")
    new_units = form.getlist("gp_new_unit")

    rows = []
    for i in range(len(material_ids)):
        mid = material_ids[i] if i < len(material_ids) else ""
        qty = quantities[i] if i < len(quantities) else ""
        nname = new_names[i] if i < len(new_names) else ""
        ncat = new_categories[i] if i < len(new_categories) else ""
        nunit = new_units[i] if i < len(new_units) else ""

        if not qty:
            continue
        try:
            qty_f = round_qty(float(qty))
        except ValueError:
            continue

        if mid == "__new__":
            if not nname:
                continue
            new_material = Material(
                item_code=next_item_code(db), name=nname, description=nname,
                category=MaterialCategory(ncat or "consumable"), unit=MaterialUnit(nunit or "units"),
                current_stock=0, is_general_stock=False, consultant_name=order.order_number,
            )
            db.add(new_material)
            db.flush()
            rows.append((new_material.id, qty_f))
        elif mid:
            try:
                rows.append((int(mid), qty_f))
            except ValueError:
                continue

    return rows


@router.get("/", response_class=HTMLResponse)
async def list_orders(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    orders = db.query(Order).filter(Order.is_deleted == False).order_by(Order.created_at.desc()).all()
    return templates.TemplateResponse("orders/list.html", {
        "request": request, "orders": orders, "current_user": current_user,
        "OrderType": OrderType, "OrderStatus": OrderStatus
    })


@router.get("/add", response_class=HTMLResponse)
async def add_order_page(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    materials = db.query(Material).filter(Material.is_deleted == False).order_by(Material.name).all()
    suppliers = db.query(Supplier).filter(Supplier.is_deleted == False).order_by(Supplier.name).all()
    return templates.TemplateResponse("orders/add.html", {
        "request": request, "current_user": current_user, "materials": materials, "suppliers": suppliers,
        "OrderType": OrderType, "error": None
    })


@router.post("/add")
async def add_order(
    request: Request,
    order_number: str = Form(...),
    order_type: str = Form(...),
    supplier_id: Optional[int] = Form(None),
    driver_name: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    gate_pass_code: Optional[str] = Form(None),
    document_photo: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login)
):
    materials = db.query(Material).filter(Material.is_deleted == False).all()
    suppliers = db.query(Supplier).filter(Supplier.is_deleted == False).order_by(Supplier.name).all()

    def error(msg):
        return templates.TemplateResponse("orders/add.html", {
            "request": request, "current_user": current_user, "materials": materials, "suppliers": suppliers,
            "OrderType": OrderType, "error": msg
        })

    if order_type == "work_order":
        if not gate_pass_code:
            return error("أمر الشغل يتطلب كود Gate Pass")
        if not document_photo or not document_photo.filename:
            return error("أمر الشغل يتطلب صورة وثيقة الوصل")
        if not driver_name:
            return error("يجب إدخال اسم السائق")

    order = Order(
        order_number=order_number, order_type=OrderType(order_type),
        receiving_supervisor_id=current_user.id, supplier_id=supplier_id,
        driver_name=driver_name, notes=notes, status=OrderStatus.open
    )
    db.add(order)
    db.flush()
    order.reference_code = generate_reference_code(db, Order, order_type)

    if order_type == "work_order" and gate_pass_code:
        photo_url = ""
        if document_photo and document_photo.filename:
            content = await document_photo.read()
            photo_url = await upload_photo(content, "gate_passes")

        gp = GatePass(
            order_id=order.id, gate_pass_code=gate_pass_code, document_photo_url=photo_url,
            driver_name=driver_name, receiving_supervisor_id=current_user.id
        )
        db.add(gp)
        db.flush()
        gp.reference_code = generate_reference_code(db, GatePass, "gate_pass")

        material_rows = await parse_material_rows(request, db, order)
        for material_id, qty in material_rows:
            material = db.query(Material).filter(Material.id == material_id).first()
            if not material:
                continue
            gpm = GatePassMaterial(gate_pass_id=gp.id, material_id=material_id, quantity=qty)
            db.add(gpm)
            material.current_stock = round_qty(material.current_stock + qty)
            upsert_order_material(db, order.id, material_id, qty)

    log_action(db, AuditAction.create, "order", order.id, current_user.id,
               after_data={"order_number": order_number, "type": order_type},
               description=f"إضافة أمر: {order_number}")
    db.commit()
    return RedirectResponse(url=f"/orders/{order.id}", status_code=302)


@router.get("/{order_id}", response_class=HTMLResponse)
async def view_order(order_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    order = db.query(Order).filter(Order.id == order_id, Order.is_deleted == False).first()
    if not order:
        raise HTTPException(status_code=404, detail="الأمر غير موجود")
    materials = db.query(Material).filter(Material.is_deleted == False).order_by(Material.name).all()
    materials_status = _compute_materials_status(db, order)
    return templates.TemplateResponse("orders/view.html", {
        "request": request, "order": order, "current_user": current_user,
        "materials": materials, "materials_status": materials_status,
        "OrderType": OrderType, "OrderStatus": OrderStatus
    })


def _compute_materials_status(db: Session, order: Order):
    from app.models.models import Issuance
    result = []
    order_materials = db.query(OrderMaterial).filter(OrderMaterial.order_id == order.id).all()
    for om in order_materials:
        issued_sum = db.query(Issuance).filter(
            Issuance.order_id == order.id, Issuance.material_id == om.material_id, Issuance.is_deleted == False
        ).all()
        issued_total = round_qty(sum(i.quantity for i in issued_sum))
        remaining = round_qty(om.quantity_received - issued_total)
        result.append({
            "material": om.material, "name": om.material.name, "unit": om.material.unit.value,
            "serial_number": om.material.serial_number, "item_code": om.material.item_code,
            "received": om.quantity_received, "issued": issued_total, "remaining": remaining,
            "status": "خرجت بالكامل" if remaining <= 0 else ("خرج جزء منها" if issued_total > 0 else "لسه في المستودع")
        })
    return result


@router.post("/{order_id}/close")
async def close_order(order_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    order = db.query(Order).filter(Order.id == order_id, Order.is_deleted == False).first()
    if not order:
        raise HTTPException(status_code=404, detail="الأمر غير موجود")
    order.status = OrderStatus.closed
    log_action(db, AuditAction.edit, "order", order.id, current_user.id,
               before_data={"status": "open"}, after_data={"status": "closed"},
               description=f"إغلاق الأمر: {order.order_number}")
    db.commit()
    return RedirectResponse(url=f"/orders/{order_id}", status_code=302)


@router.post("/{order_id}/reopen")
async def reopen_order(order_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    order = db.query(Order).filter(Order.id == order_id, Order.is_deleted == False).first()
    if not order:
        raise HTTPException(status_code=404, detail="الأمر غير موجود")
    order.status = OrderStatus.open
    log_action(db, AuditAction.edit, "order", order.id, current_user.id,
               before_data={"status": "closed"}, after_data={"status": "open"},
               description=f"إعادة فتح الأمر: {order.order_number}")
    db.commit()
    return RedirectResponse(url=f"/orders/{order_id}", status_code=302)


@router.get("/{order_id}/materials-receipt")
async def order_materials_receipt(order_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="الأمر غير موجود")
    materials_status = _compute_materials_status(db, order)
    pdf_bytes = generate_order_materials_receipt(order, materials_status)
    return StreamingResponse(
        io.BytesIO(pdf_bytes), media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=order_materials_{order.order_number}.pdf"}
    )


@router.post("/{order_id}/add-gate-pass")
async def add_gate_pass(
    order_id: int,
    request: Request,
    gate_pass_code: str = Form(...),
    driver_name: str = Form(...),
    document_photo: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login)
):
    order = db.query(Order).filter(Order.id == order_id, Order.is_deleted == False).first()
    if not order:
        raise HTTPException(status_code=404, detail="الأمر غير موجود")
    if order.order_type != OrderType.work_order:
        raise HTTPException(status_code=400, detail="Gate Pass لأوامر الشغل فقط")

    photo_url = ""
    if document_photo and document_photo.filename:
        content = await document_photo.read()
        photo_url = await upload_photo(content, "gate_passes")

    gp = GatePass(
        order_id=order_id, gate_pass_code=gate_pass_code, document_photo_url=photo_url,
        driver_name=driver_name, receiving_supervisor_id=current_user.id
    )
    db.add(gp)
    db.flush()
    gp.reference_code = generate_reference_code(db, GatePass, "gate_pass")

    material_rows = await parse_material_rows(request, db, order)
    for material_id, qty in material_rows:
        material = db.query(Material).filter(Material.id == material_id).first()
        if not material:
            continue
        gpm = GatePassMaterial(gate_pass_id=gp.id, material_id=material_id, quantity=qty)
        db.add(gpm)
        material.current_stock = round_qty(material.current_stock + qty)
        upsert_order_material(db, order_id, material_id, qty)

    log_action(db, AuditAction.create, "gate_pass", order_id, current_user.id,
               description=f"إضافة Gate Pass: {gate_pass_code} للأمر: {order.order_number}")
    db.commit()
    return RedirectResponse(url=f"/orders/{order_id}", status_code=302)


@router.post("/{order_id}/delete")
async def delete_order(order_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    order = db.query(Order).filter(Order.id == order_id, Order.is_deleted == False).first()
    if not order:
        raise HTTPException(status_code=404, detail="الأمر غير موجود")
    order.is_deleted = True
    order.deleted_at = datetime.utcnow()
    order.deleted_by_id = current_user.id
    log_action(db, AuditAction.delete, "order", order.id, current_user.id,
               description=f"حذف أمر: {order.order_number}")
    db.commit()
    return RedirectResponse(url="/orders/", status_code=302)


@router.get("/{order_id}/receipt")
async def download_order_receipt(order_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="الأمر غير موجود")
    pdf_bytes = generate_order_receipt(order, gate_passes=order.gate_passes)
    return StreamingResponse(
        io.BytesIO(pdf_bytes), media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=order_{order.order_number}.pdf"}
    )
