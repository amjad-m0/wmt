"""
مولّد الأكواد التسلسلية الفريدة (محاكاة دفتر الكربون).
كل حركة (أمر / Gate Pass / إصدار / استلاف / نقل / مرتجع) تاخد كود فريد
بالصيغة: PREFIX-YYYY-NNNN  مثال: ISS-2026-0001
الكود ثابت بمجرد توليده، ولا يتغير أو يُعاد استخدامه حتى لو حصل حذف لاحق (soft delete).
"""
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime


PREFIXES = {
    "work_order": "WO",
    "maintenance_order": "MO",
    "gate_pass": "GP",
    "issuance": "ISS",
    "borrowing": "BOR",
    "transfer": "TRF",
    "return": "RET",
}


def generate_reference_code(db: Session, model_class, prefix_key: str) -> str:
    """
    يولّد كود تسلسلي فريد لهذا النوع من الحركات لهذه السنة.
    مثال: ISS-2026-0001, ISS-2026-0002 ...
    """
    year = datetime.utcnow().year
    prefix = PREFIXES[prefix_key]
    year_prefix = f"{prefix}-{year}-"

    # نلاقي أعلى رقم متسلسل مستخدم لنفس البادئة والسنة (بما في ذلك المحذوف - الكود لا يُعاد استخدامه أبداً)
    count = db.query(func.count(model_class.id)).filter(
        model_class.reference_code.like(f"{year_prefix}%")
    ).scalar()

    next_number = (count or 0) + 1
    code = f"{year_prefix}{next_number:04d}"

    # في حالة تعارض نادر (سباق بين طلبين)، نزود الرقم لحد ما نلاقي كود فاضي
    while db.query(model_class).filter(model_class.reference_code == code).first() is not None:
        next_number += 1
        code = f"{year_prefix}{next_number:04d}"

    return code
