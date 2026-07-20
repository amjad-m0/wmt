from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional
import io
from app.database import get_db
from app.auth import require_login, require_admin
from app.models.models import Transfer, Material, User, AuditAction
from app.services.pdf_service import generate_transfer_receipt
from app.services.audit_service import log_action
from app.services.reference_code_service import generate_reference_code
from app.services.number_utils import round_qty

router = APIRouter(prefix="/transfers", tags=["transfers"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def list_transfers(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    transfers = db.query(Transfer).filter(Transfer.is_deleted == False).order_by(Transfer.created_at.desc()).all()
    return templates.TemplateResponse("transfers/list.html", {
        "request": request, "transfers": transfers, "current_user": current_user
    })


@router.get("/add", response_class=HTMLResponse)
async def add_transfer_page(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    materials = db.query(Material).filter(Material.is_deleted == False).order_by(Material.name).all()
    return templates.TemplateResponse("transfers/add.html", {
        "request": request, "current_user": current_user, "materials": materials, "error": None
    })


@router.post("/add")
async def add_transfer(
    request: Request,
    material_id: int = Form(...),
    quantity: float = Form(...),
    location_from: str = Form(...),
    location_to: str = Form(...),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login)
):
    qty = round_qty(quantity)
    transfer = Transfer(
        material_id=material_id, quantity=qty, supervisor_id=current_user.id,
        location_from=location_from, location_to=location_to, notes=notes
    )
    db.add(transfer)
    db.flush()
    transfer.reference_code = generate_reference_code(db, Transfer, "transfer")

    log_action(db, AuditAction.create, "transfer", transfer.id, current_user.id,
               after_data={"material_id": material_id, "quantity": qty},
               description=f"نقل داخلي: {qty} من المادة رقم {material_id} بواسطة {current_user.full_name}")
    db.commit()
    return RedirectResponse(url="/transfers/", status_code=302)


@router.get("/{transfer_id}/receipt")
async def transfer_receipt(transfer_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    transfer = db.query(Transfer).filter(Transfer.id == transfer_id).first()
    if not transfer:
        raise HTTPException(status_code=404, detail="السجل غير موجود")
    pdf_bytes = generate_transfer_receipt(transfer)
    return StreamingResponse(
        io.BytesIO(pdf_bytes), media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=transfer_{transfer_id}.pdf"}
    )


@router.post("/{transfer_id}/delete")
async def delete_transfer(transfer_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    transfer = db.query(Transfer).filter(Transfer.id == transfer_id, Transfer.is_deleted == False).first()
    if not transfer:
        raise HTTPException(status_code=404, detail="السجل غير موجود")
    transfer.is_deleted = True
    log_action(db, AuditAction.delete, "transfer", transfer.id, current_user.id,
               description=f"حذف نقل داخلي رقم {transfer_id}")
    db.commit()
    return RedirectResponse(url="/transfers/", status_code=302)
