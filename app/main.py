from fastapi import FastAPI, Depends, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.exceptions import HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.database import get_db, engine, Base, SessionLocal
from app.auth import get_current_user_from_cookie, get_password_hash
from app.models.models import (Material, Order, Borrowing, OrderStatus,
                                  BorrowStatus, User, UserRole)
from app.routers import auth, materials, orders, issuances, borrowings, transfers, returns, search, admin, suppliers

# Create tables
Base.metadata.create_all(bind=engine)


def ensure_default_admin():
    db = SessionLocal()
    try:
        admin_user = db.query(User).filter(User.role == UserRole.admin).first()
        if admin_user:
            return

        default_username = "admin"
        default_password = "admin123"
        admin_user = User(
            username=default_username,
            full_name="Administrator",
            hashed_password=get_password_hash(default_password),
            role=UserRole.admin,
            is_active=True,
        )
        db.add(admin_user)
        db.commit()
        print(f"Default admin created: {default_username}/{default_password}")
    finally:
        db.close()


ensure_default_admin()

# Seed fixed suppliers (مستودع الدمام 314 / مستودع بن قريعة 310) if not present
def _seed_suppliers():
    from app.models.models import Supplier
    db = SessionLocal()
    try:
        fixed_names = ["مستودع الدمام 314", "مستودع بن قريعة 310"]
        for name in fixed_names:
            exists = db.query(Supplier).filter(Supplier.name == name).first()
            if not exists:
                db.add(Supplier(name=name))
        db.commit()
    finally:
        db.close()

_seed_suppliers()

app = FastAPI(title="نظام إدارة المستودع")

# Static files
os.makedirs("uploads", exist_ok=True)
app.mount("/static/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

templates = Jinja2Templates(directory="app/templates")

# Include routers
app.include_router(auth.router)
app.include_router(materials.router)
app.include_router(orders.router)
app.include_router(issuances.router)
app.include_router(borrowings.router)
app.include_router(transfers.router)
app.include_router(returns.router)
app.include_router(search.router)
app.include_router(admin.router)
app.include_router(suppliers.router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 302:
        return RedirectResponse(url=exc.headers.get("Location", "/auth/login"), status_code=302)
    return HTMLResponse(content=f"<h3 style='font-family:sans-serif;text-align:center;margin-top:100px;'>{exc.detail}</h3>", status_code=exc.status_code)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user_from_cookie(request, db)
    if not current_user:
        return RedirectResponse(url="/auth/login", status_code=302)

    stats = {
        "materials_count": db.query(Material).filter(Material.is_deleted == False).count(),
        "orders_open": db.query(Order).filter(Order.is_deleted == False, Order.status == OrderStatus.open).count(),
        "borrowings_pending": db.query(Borrowing).filter(Borrowing.is_deleted == False, Borrowing.status == BorrowStatus.pending).count(),
        "low_stock": db.query(Material).filter(Material.is_deleted == False, Material.current_stock < 10).count(),
    }
    recent_orders = db.query(Order).filter(Order.is_deleted == False).order_by(Order.created_at.desc()).limit(5).all()
    recent_borrowings = db.query(Borrowing).filter(Borrowing.is_deleted == False).order_by(Borrowing.created_at.desc()).limit(5).all()

    return templates.TemplateResponse("base/dashboard.html", {
        "request": request,
        "current_user": current_user,
        "stats": stats,
        "recent_orders": recent_orders,
        "recent_borrowings": recent_borrowings,
        "today": datetime.now().strftime("%Y-%m-%d")
    })


@app.get("/health")
async def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
