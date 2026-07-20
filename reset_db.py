"""
يمسح قاعدة بيانات التطبيق وينشئها من جديد فاضية.
استخدمه وأنت لسه بتجرب النظام (بيانات تجريبية بس).
تشغيل: python reset_db.py
"""
from urllib.parse import urlparse
import psycopg2

from app.config import get_settings

settings = get_settings()
parsed = urlparse(settings.DATABASE_URL)

target_db = parsed.path.lstrip("/") or "postgres"
user = parsed.username or "wms_user"
password = parsed.password or "wms_password"
host = parsed.hostname or "localhost"
port = parsed.port or 5432
admin_db = "postgres"

conn = psycopg2.connect(
    dbname=admin_db,
    user=user,
    password=password,
    host=host,
    port=port,
)
conn.autocommit = True
cur = conn.cursor()

print(f"جاري قطع أي اتصالات مفتوحة بقاعدة {target_db}...")
cur.execute(
    f"""
    SELECT pg_terminate_backend(pid)
    FROM pg_stat_activity
    WHERE datname = '{target_db}' AND pid <> pg_backend_pid();
    """
)

print(f"جاري مسح قاعدة {target_db}...")
cur.execute(f'DROP DATABASE IF EXISTS "{target_db}";')

print(f"جاري إنشاء قاعدة {target_db} من جديد...")
cur.execute(f'CREATE DATABASE "{target_db}" OWNER "{user}";')

cur.close()
conn.close()
print(f"✅ تم! تم إنشاء قاعدة {target_db} من جديد. شغّل السيرفر أو run init_admin.py لإنشاء المستخدم الإداري.")
