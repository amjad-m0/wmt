"""
Run this once after setting up the database to create the first Admin user.
Usage: python init_admin.py
"""
import sys
sys.path.insert(0, ".")

from app.database import SessionLocal, engine, Base
from app.models.models import User, UserRole
from app.auth import get_password_hash

Base.metadata.create_all(bind=engine)

db = SessionLocal()

username = input("اسم المستخدم للمدير (username): ").strip()
full_name = input("الاسم الكامل: ").strip()
password = input("كلمة المرور: ").strip()

existing = db.query(User).filter(User.username == username).first()
if existing:
    print("❌ اسم المستخدم موجود بالفعل!")
else:
    admin = User(
        username=username,
        full_name=full_name,
        hashed_password=get_password_hash(password),
        role=UserRole.admin,
        is_active=True
    )
    db.add(admin)
    db.commit()
    print(f"✅ تم إنشاء حساب المدير: {username}")

db.close()
