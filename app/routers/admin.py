from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.auth import require_admin, get_password_hash
from app.models.models import User, UserRole, AuditAction
from app.services.audit_service import log_action

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/users", response_class=HTMLResponse)
async def list_users(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    users = db.query(User).order_by(User.full_name).all()
    return templates.TemplateResponse("auth/users.html", {
        "request": request, "users": users, "current_user": current_user,
        "UserRole": UserRole
    })


@router.get("/users/add", response_class=HTMLResponse)
async def add_user_page(request: Request, current_user: User = Depends(require_admin)):
    return templates.TemplateResponse("auth/add_user.html", {
        "request": request, "current_user": current_user,
        "UserRole": UserRole, "error": None
    })


@router.post("/users/add")
async def add_user(
    request: Request,
    full_name: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    existing = db.query(User).filter(User.username == username).first()
    if existing:
        return templates.TemplateResponse("auth/add_user.html", {
            "request": request, "current_user": current_user,
            "UserRole": UserRole,
            "error": "اسم المستخدم موجود بالفعل"
        })

    user = User(
        full_name=full_name,
        username=username,
        hashed_password=get_password_hash(password),
        role=UserRole(role)
    )
    db.add(user)
    db.flush()
    log_action(db, AuditAction.create, "user", user.id, current_user.id,
               description=f"إضافة مستخدم: {full_name}")
    db.commit()
    return RedirectResponse(url="/admin/users", status_code=302)


@router.post("/users/{user_id}/toggle")
async def toggle_user(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="لا يمكن تعطيل حسابك")
    user.is_active = not user.is_active
    db.commit()
    return RedirectResponse(url="/admin/users", status_code=302)
