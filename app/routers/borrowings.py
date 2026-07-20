from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional
import io
from datetime import datetime
from app.database import get_db
from app.auth import require_login, require_admin
from app.models.models import (Borrowing, Order, Material, User, BorrowStatus, AuditAction,
                                 BorrowSourceType, BorrowDirection, BorrowReturnDestination)
from app.services.pdf_service import generate_borrowing_receipt
from app.services.audit_service import log_action
from app.services.reference_code_service import generate_reference_code
from app.services.number_utils import round_qty
from app.services.order_material_service import upsert_order_material, get_order_material_remaining

router = APIRouter(prefix="/borrowings", tags=["borrowings"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def list_borrowings(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    borrowings = db.query(Borrowing).filter(Borrowing.is_deleted == False).order_by(Borrowing.created_at.desc()).all()
    return templates.TemplateResponse("borrowing/list.html", {
        "request": request, "borrowings": borrowings, "current_user": current_user,
        "BorrowStatus": BorrowStatus
    })


@router.get("/add", response_class=HTMLResponse)
async def add_borrowing_page(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    orders = db.query(Order).filter(Order.is_deleted == False).order_by(Order.order_number).all()
    materials = db.query(Material).filter(Material.is_deleted == False).order_by(Material.name).all()
    return templates.TemplateResponse("borrowing/add.html", {
        "request": request, "current_user": current_user,
        "orders": orders, "materials": materials, "error": None
    })


@router.post("/add")
async def add_borrowing(
    request: Request,
    borrowing_order_id: int = Form(...),
    borrow_kind: str = Form(...),  # internal / from_contractor / to_contractor
    source_order_id: Optional[int] = Form(None),
    contractor_name: Optional[str] = Form(None),
    material_id: int = Form(...),
    quantity: float = Form(...),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login)
):
    orders = db.query(Order).filter(Order.is_deleted == False).all()
    materials = db.query(Material).filter(Material.is_deleted == False).all()
    qty = round_qty(quantity)

    def error(msg):
        return templates.TemplateResponse("borrowing/add.html", {
            "request": request, "current_user": current_user,
            "orders": orders, "materials": materials, "error": msg
        })

    material = db.query(Material).filter(Material.id == material_id, Material.is_deleted == False).first()
    if not material:
        return error("المادة غير موجودة")

    if borrow_kind == "internal":
        source_type = BorrowSourceType.internal
        direction = BorrowDirection.borrow_in
        if not source_order_id:
            return error("يجب اختيار أمر العمل المصدر للاستلاف الداخلي")

        # ✅ التحقق الحقيقي: هل المادة دي فعلاً موجودة في أمر المصدر بالكمية المطلوبة؟
        remaining = get_order_material_remaining(db, source_order_id, material_id)
        if remaining < qty:
            source_order = db.query(Order).filter(Order.id == source_order_id).first()
            return error(
                f"المادة غير متوفرة في أمر المصدر ({source_order.order_number if source_order else source_order_id}) "
                f"بالكمية المطلوبة — المتاح فعلياً: {remaining} {material.unit.value} فقط"
            )
    elif borrow_kind == "from_contractor":
        source_type = BorrowSourceType.contractor
        direction = BorrowDirection.borrow_in
        if not contractor_name:
            return error("اسم المقاول إجباري عند الاستلاف من مقاول")
    elif borrow_kind == "to_contractor":
        source_type = BorrowSourceType.contractor
        direction = BorrowDirection.lend_out
        if not contractor_name:
            return error("اسم المقاول إجباري عند التسليف لمقاول")
        # التسليف لمقاول بيخرج من مخزون أمرنا نفسه - لازم يكون متاح
        remaining = get_order_material_remaining(db, borrowing_order_id, material_id)
        if remaining < qty and not material.is_general_stock:
            return error(f"الكمية غير متوفرة في أمرك لتسليفها — المتاح: {remaining} {material.unit.value}")
    else:
        return error("نوع العملية غير معروف")

    borrowing = Borrowing(
        borrowing_order_id=borrowing_order_id,
        source_type=source_type,
        direction=direction,
        contractor_name=contractor_name if source_type == BorrowSourceType.contractor else None,
        source_order_id=source_order_id if source_type == BorrowSourceType.internal else None,
        material_id=material_id,
        quantity=qty,
        supervisor_id=current_user.id,  # المشرف المسجل هو المستخدم الحالي دايماً
        notes=notes,
        status=BorrowStatus.pending
    )
    db.add(borrowing)
    db.flush()
    borrowing.reference_code = generate_reference_code(db, Borrowing, "borrowing")

    # تحديث الأرصدة الفعلية حسب نوع العملية
    if direction == BorrowDirection.borrow_in:
        if source_type == BorrowSourceType.internal:
            # يتخصم من أمر المصدر ويتضاف لحساب أمرنا
            upsert_order_material(db, source_order_id, material_id, qty_issued_delta=qty)
            upsert_order_material(db, borrowing_order_id, material_id, qty_received_delta=qty)
        else:
            # من مقاول خارجي: المادة بتدخل فعلياً للمخزون
            material.current_stock = round_qty(material.current_stock + qty)
            upsert_order_material(db, borrowing_order_id, material_id, qty_received_delta=qty)
    else:  # lend_out to contractor
        material.current_stock = round_qty(material.current_stock - qty)
        upsert_order_material(db, borrowing_order_id, material_id, qty_issued_delta=qty)

    log_action(db, AuditAction.create, "borrowing", borrowing.id, current_user.id,
               after_data={"material_id": material_id, "quantity": qty, "borrow_kind": borrow_kind},
               description=f"{'تسليف' if direction == BorrowDirection.lend_out else 'استلاف'} {qty} من المادة رقم {material_id}")
    db.commit()
    return RedirectResponse(url="/borrowings/", status_code=302)


@router.get("/{borrowing_id}/return", response_class=HTMLResponse)
async def return_borrowing_page(borrowing_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    borrowing = db.query(Borrowing).filter(Borrowing.id == borrowing_id, Borrowing.is_deleted == False).first()
    if not borrowing:
        raise HTTPException(status_code=404, detail="السجل غير موجود")
    if borrowing.status == BorrowStatus.returned:
        raise HTTPException(status_code=400, detail="تم إرجاع هذا الاستلاف مسبقاً")
    orders = db.query(Order).filter(Order.is_deleted == False).order_by(Order.order_number).all()
    return templates.TemplateResponse("borrowing/return.html", {
        "request": request, "current_user": current_user, "borrowing": borrowing, "orders": orders
    })


@router.post("/{borrowing_id}/return")
async def return_borrowing(
    borrowing_id: int,
    destination_type: str = Form(...),  # same_source / different_order / general_stock
    destination_order_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login)
):
    borrowing = db.query(Borrowing).filter(Borrowing.id == borrowing_id, Borrowing.is_deleted == False).first()
    if not borrowing:
        raise HTTPException(status_code=404, detail="سجل الاستلاف غير موجود")
    if borrowing.status == BorrowStatus.returned:
        raise HTTPException(status_code=400, detail="تم إرجاع هذا الاستلاف مسبقاً")

    qty = borrowing.quantity
    material = borrowing.material

    # المادة بترجع فعلياً - نرجعها من حساب أمرنا الحالي أولاً
    upsert_order_material(db, borrowing.borrowing_order_id, borrowing.material_id, qty_received_delta=-qty)

    if destination_type == "general_stock":
        material.current_stock = round_qty(material.current_stock + qty)
        borrowing.return_destination_type = BorrowReturnDestination.general_stock
    elif destination_type == "same_source" and borrowing.source_order_id:
        upsert_order_material(db, borrowing.source_order_id, borrowing.material_id, qty_issued_delta=-qty)
        borrowing.return_destination_type = BorrowReturnDestination.same_source
        borrowing.return_destination_order_id = borrowing.source_order_id
    elif destination_type == "different_order" and destination_order_id:
        upsert_order_material(db, destination_order_id, borrowing.material_id, qty_received_delta=qty)
        borrowing.return_destination_type = BorrowReturnDestination.different_order
        borrowing.return_destination_order_id = destination_order_id
    else:
        raise HTTPException(status_code=400, detail="وجهة الإرجاع غير صحيحة")

    borrowing.status = BorrowStatus.returned
    borrowing.return_date = datetime.utcnow()

    log_action(db, AuditAction.edit, "borrowing", borrowing.id, current_user.id,
               before_data={"status": "pending"},
               after_data={"status": "returned", "destination": destination_type},
               description=f"إرجاع استلاف رقم {borrowing_id} - الوجهة: {destination_type}")
    db.commit()
    return RedirectResponse(url="/borrowings/", status_code=302)


@router.get("/{borrowing_id}/receipt")
async def borrowing_receipt(borrowing_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    borrowing = db.query(Borrowing).filter(Borrowing.id == borrowing_id).first()
    if not borrowing:
        raise HTTPException(status_code=404, detail="السجل غير موجود")
    pdf_bytes = generate_borrowing_receipt(borrowing)
    return StreamingResponse(
        io.BytesIO(pdf_bytes), media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=borrowing_{borrowing_id}.pdf"}
    )


@router.post("/{borrowing_id}/delete")
async def delete_borrowing(borrowing_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    borrowing = db.query(Borrowing).filter(Borrowing.id == borrowing_id, Borrowing.is_deleted == False).first()
    if not borrowing:
        raise HTTPException(status_code=404, detail="السجل غير موجود")
    borrowing.is_deleted = True
    log_action(db, AuditAction.delete, "borrowing", borrowing.id, current_user.id,
               description=f"حذف استلاف رقم {borrowing_id}")
    db.commit()
    return RedirectResponse(url="/borrowings/", status_code=302)
