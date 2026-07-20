from fastapi import APIRouter, Depends, Request, Form, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime
from app.database import get_db
from app.auth import require_login, require_admin
from app.models.models import Material, MaterialCategory, MaterialUnit, User, AuditAction, Supplier, Order
from app.services.storage import upload_photo
from app.services.audit_service import log_action
from app.services.number_utils import round_qty
from app.services.order_material_service import upsert_order_material

router = APIRouter(prefix="/materials", tags=["materials"])
templates = Jinja2Templates(directory="app/templates")


def parse_date(date_str: Optional[str]):
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None


def next_item_code(db: Session) -> int:
    from sqlalchemy import func
    max_code = db.query(func.max(Material.item_code)).scalar()
    return (max_code or 0) + 1


@router.get("/", response_class=HTMLResponse)
async def list_materials(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    materials = db.query(Material).filter(Material.is_deleted == False).order_by(Material.name).all()
    supervisors = db.query(User).filter(User.is_active == True).all()
    return templates.TemplateResponse("materials/list.html", {
        "request": request, "materials": materials, "supervisors": supervisors,
        "current_user": current_user, "categories": MaterialCategory, "units": MaterialUnit
    })


@router.get("/add", response_class=HTMLResponse)
async def add_material_page(request: Request, current_user: User = Depends(require_login), db: Session = Depends(get_db)):
    supervisors = db.query(User).filter(User.is_active == True).all()
    suppliers = db.query(Supplier).filter(Supplier.is_deleted == False).order_by(Supplier.name).all()
    orders = db.query(Order).filter(Order.is_deleted == False).order_by(Order.order_number).all()
    return templates.TemplateResponse("materials/add.html", {
        "request": request, "current_user": current_user, "supervisors": supervisors,
        "suppliers": suppliers, "orders": orders,
        "categories": MaterialCategory, "units": MaterialUnit, "error": None
    })


@router.post("/add")
async def add_material(
    request: Request,
    name: str = Form(...),
    description: str = Form(...),
    category: str = Form(...),
    unit: str = Form(...),
    current_stock: float = Form(...),
    is_general_stock: bool = Form(False),
    holder_id: Optional[int] = Form(None),
    serial_number: Optional[str] = Form(None),
    linked_order_id: Optional[int] = Form(None),
    related_gate_pass_no: Optional[str] = Form(None),
    expiry_date: Optional[str] = Form(None),
    supplier_id: Optional[int] = Form(None),
    photo: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login)
):
    supervisors = db.query(User).filter(User.is_active == True).all()
    suppliers = db.query(Supplier).filter(Supplier.is_deleted == False).order_by(Supplier.name).all()
    orders = db.query(Order).filter(Order.is_deleted == False).order_by(Order.order_number).all()

    def error(msg):
        return templates.TemplateResponse("materials/add.html", {
            "request": request, "current_user": current_user, "supervisors": supervisors,
            "suppliers": suppliers, "orders": orders,
            "categories": MaterialCategory, "units": MaterialUnit, "error": msg
        })

    if category == "device":
        if not serial_number:
            return error("الرقم التسلسلي إجباري لفئة (معدة)")
    else:
        serial_number = None

    linked_order = None
    if is_general_stock:
        linked_order_id = None
        related_gate_pass_no = None
    else:
        if not linked_order_id:
            return error("لازم تختار أمر العمل/الصيانة اللي المادة دي مسجلة عليه (أو تخليها مخزون عام)")
        linked_order = db.query(Order).filter(Order.id == linked_order_id, Order.is_deleted == False).first()
        if not linked_order:
            return error("الأمر المختار غير موجود")
        if linked_order.order_type.value == "work_order":
            if not related_gate_pass_no:
                return error("رقم الـ Gate Pass إجباري لو المادة على أمر شغل")
        else:
            related_gate_pass_no = None

    photo_url = None
    if photo and photo.filename:
        content = await photo.read()
        photo_url = await upload_photo(content, "materials")

    stock = round_qty(current_stock)
    material = Material(
        item_code=next_item_code(db), name=name, description=description,
        category=MaterialCategory(category), unit=MaterialUnit(unit),
        current_stock=stock, is_general_stock=is_general_stock,
        holder_id=holder_id if category == "tool" else None,
        serial_number=serial_number, linked_order_id=linked_order_id,
        related_gate_pass_no=related_gate_pass_no, expiry_date=parse_date(expiry_date),
        supplier_id=supplier_id if supplier_id else None, photo_url=photo_url
    )
    db.add(material)
    db.flush()

    # الربط الفعلي بالأمر (مش نص وصفي) - ده اللي بيضمن ظهورها في صفحة الأمر وحساب المخزون صح
    if linked_order_id:
        upsert_order_material(db, linked_order_id, material.id, qty_received_delta=stock)

    log_action(db, AuditAction.create, "material", material.id, current_user.id,
               after_data={"name": name, "category": category, "stock": material.current_stock, "item_code": material.item_code},
               description=f"إضافة مادة: {name} (كود {material.item_code})")
    db.commit()
    return RedirectResponse(url="/materials/", status_code=302)


@router.get("/bulk-add", response_class=HTMLResponse)
async def bulk_add_materials_page(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    orders = db.query(Order).filter(Order.is_deleted == False).order_by(Order.order_number).all()
    return templates.TemplateResponse("materials/bulk_add.html", {
        "request": request, "current_user": current_user, "orders": orders, "error": None
    })


@router.post("/bulk-add")
async def bulk_add_materials(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login)
):
    orders = db.query(Order).filter(Order.is_deleted == False).order_by(Order.order_number).all()
    form = await request.form()
    names = form.getlist("bulk_name")
    categories = form.getlist("bulk_category")
    units = form.getlist("bulk_unit")
    serials = form.getlist("bulk_serial")
    order_ids = form.getlist("bulk_order_id")
    gate_passes = form.getlist("bulk_gate_pass")
    quantities = form.getlist("bulk_quantity")

    def error(msg):
        return templates.TemplateResponse("materials/bulk_add.html", {
            "request": request, "current_user": current_user, "orders": orders, "error": msg
        })

    created = []
    for i in range(len(names)):
        name = names[i].strip() if i < len(names) else ""
        if not name:
            continue
        category = categories[i] if i < len(categories) else "consumable"
        unit = units[i] if i < len(units) else "each"
        serial = serials[i].strip() if i < len(serials) else ""
        order_id_raw = order_ids[i] if i < len(order_ids) else ""
        gate_pass_no = gate_passes[i].strip() if i < len(gate_passes) else ""
        qty_raw = quantities[i] if i < len(quantities) else "0"

        if category == "device" and not serial:
            return error(f"الصف رقم {i+1} ({name}): الرقم التسلسلي إجباري لفئة (معدة)")
        if not order_id_raw:
            return error(f"الصف رقم {i+1} ({name}): لازم تختار أمر العمل/الصيانة")

        order = db.query(Order).filter(Order.id == int(order_id_raw), Order.is_deleted == False).first()
        if not order:
            return error(f"الصف رقم {i+1} ({name}): الأمر المختار غير موجود")
        if order.order_type.value == "work_order" and not gate_pass_no:
            return error(f"الصف رقم {i+1} ({name}): رقم الـ Gate Pass إجباري لأمر شغل")

        try:
            qty = round_qty(float(qty_raw))
        except ValueError:
            qty = 0.0

        material = Material(
            item_code=next_item_code(db), name=name, description=name,
            category=MaterialCategory(category), unit=MaterialUnit(unit),
            current_stock=qty, is_general_stock=False,
            serial_number=serial or None,
            linked_order_id=order.id,
            related_gate_pass_no=gate_pass_no or None if order.order_type.value == "work_order" else None
        )
        db.add(material)
        db.flush()
        upsert_order_material(db, order.id, material.id, qty_received_delta=qty)
        created.append(material)

        log_action(db, AuditAction.create, "material", material.id, current_user.id,
                   after_data={"name": name, "category": category, "item_code": material.item_code},
                   description=f"إضافة جماعية: {name} (كود {material.item_code}) على أمر {order.order_number}")

    if not created:
        return error("لازم تضيف صف واحد على الأقل ببيانات كاملة")

    db.commit()
    return RedirectResponse(url="/materials/", status_code=302)


@router.get("/{material_id}", response_class=HTMLResponse)
async def view_material(material_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    material = db.query(Material).filter(Material.id == material_id, Material.is_deleted == False).first()
    if not material:
        raise HTTPException(status_code=404, detail="المادة غير موجودة")
    return templates.TemplateResponse("materials/view.html", {
        "request": request, "material": material, "current_user": current_user
    })


@router.get("/{material_id}/edit", response_class=HTMLResponse)
async def edit_material_page(material_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    material = db.query(Material).filter(Material.id == material_id, Material.is_deleted == False).first()
    if not material:
        raise HTTPException(status_code=404, detail="المادة غير موجودة")
    supervisors = db.query(User).filter(User.is_active == True).all()
    suppliers = db.query(Supplier).filter(Supplier.is_deleted == False).order_by(Supplier.name).all()
    orders = db.query(Order).filter(Order.is_deleted == False).order_by(Order.order_number).all()
    return templates.TemplateResponse("materials/edit.html", {
        "request": request, "material": material, "supervisors": supervisors, "suppliers": suppliers,
        "orders": orders, "current_user": current_user, "categories": MaterialCategory, "units": MaterialUnit
    })


@router.post("/{material_id}/edit")
async def edit_material(
    material_id: int,
    request: Request,
    name: str = Form(...),
    description: str = Form(...),
    category: str = Form(...),
    unit: str = Form(...),
    current_stock: float = Form(...),
    is_general_stock: bool = Form(False),
    holder_id: Optional[int] = Form(None),
    serial_number: Optional[str] = Form(None),
    linked_order_id: Optional[int] = Form(None),
    related_gate_pass_no: Optional[str] = Form(None),
    expiry_date: Optional[str] = Form(None),
    supplier_id: Optional[int] = Form(None),
    photo: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    material = db.query(Material).filter(Material.id == material_id, Material.is_deleted == False).first()
    if not material:
        raise HTTPException(status_code=404, detail="المادة غير موجودة")

    supervisors = db.query(User).filter(User.is_active == True).all()
    suppliers = db.query(Supplier).filter(Supplier.is_deleted == False).order_by(Supplier.name).all()
    orders = db.query(Order).filter(Order.is_deleted == False).order_by(Order.order_number).all()

    def error(msg):
        return templates.TemplateResponse("materials/edit.html", {
            "request": request, "material": material, "supervisors": supervisors, "suppliers": suppliers,
            "orders": orders, "current_user": current_user, "categories": MaterialCategory, "units": MaterialUnit,
            "error": msg
        })

    if category == "device":
        if not serial_number:
            return error("الرقم التسلسلي إجباري لفئة (معدة)")
    else:
        serial_number = None

    if is_general_stock:
        linked_order_id = None
        related_gate_pass_no = None
    else:
        if not linked_order_id:
            return error("لازم تختار أمر العمل/الصيانة اللي المادة دي مسجلة عليه (أو تخليها مخزون عام)")
        linked_order = db.query(Order).filter(Order.id == linked_order_id, Order.is_deleted == False).first()
        if not linked_order:
            return error("الأمر المختار غير موجود")
        if linked_order.order_type.value == "work_order":
            if not related_gate_pass_no:
                return error("رقم الـ Gate Pass إجباري لو المادة على أمر شغل")
        else:
            related_gate_pass_no = None

    before = {"name": material.name, "stock": material.current_stock, "category": material.category.value}

    if photo and photo.filename:
        content = await photo.read()
        material.photo_url = await upload_photo(content, "materials")

    material.name = name
    material.description = description
    material.category = MaterialCategory(category)
    material.unit = MaterialUnit(unit)
    material.current_stock = round_qty(current_stock)
    material.is_general_stock = is_general_stock
    material.holder_id = holder_id if category == "tool" else None
    material.serial_number = serial_number
    material.linked_order_id = linked_order_id
    material.related_gate_pass_no = related_gate_pass_no
    material.expiry_date = parse_date(expiry_date)
    material.supplier_id = supplier_id if supplier_id else None

    log_action(db, AuditAction.edit, "material", material.id, current_user.id,
               before_data=before,
               after_data={"name": name, "stock": material.current_stock, "category": category},
               description=f"تعديل مادة: {name}")
    db.commit()
    return RedirectResponse(url=f"/materials/{material_id}", status_code=302)


@router.post("/{material_id}/increase-stock")
async def increase_stock(
    material_id: int,
    amount: float = Form(...),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login)
):
    material = db.query(Material).filter(Material.id == material_id, Material.is_deleted == False).first()
    if not material:
        raise HTTPException(status_code=404, detail="المادة غير موجودة")
    if amount <= 0:
        raise HTTPException(status_code=400, detail="الكمية المضافة لازم تكون أكبر من صفر")

    before_stock = material.current_stock
    material.current_stock = round_qty(material.current_stock + amount)

    # لو المادة مرتبطة بأمر، الكمية الجديدة تتسجل على رصيد الأمر ده كمان
    if material.linked_order_id:
        upsert_order_material(db, material.linked_order_id, material.id, qty_received_delta=amount)

    log_action(db, AuditAction.edit, "material", material.id, current_user.id,
               before_data={"stock": before_stock},
               after_data={"stock": material.current_stock, "added": amount},
               description=f"زيادة كمية {material.name}: +{amount} (بواسطة {current_user.full_name}) - {notes or ''}")
    db.commit()
    return RedirectResponse(url=f"/materials/{material_id}", status_code=302)


@router.post("/{material_id}/delete")
async def delete_material(material_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    material = db.query(Material).filter(Material.id == material_id, Material.is_deleted == False).first()
    if not material:
        raise HTTPException(status_code=404, detail="المادة غير موجودة")
    material.is_deleted = True
    material.deleted_at = datetime.utcnow()
    material.deleted_by_id = current_user.id
    log_action(db, AuditAction.delete, "material", material.id, current_user.id,
               description=f"حذف مادة: {material.name}")
    db.commit()
    return RedirectResponse(url="/materials/", status_code=302)
