from sqlalchemy.orm import Session
from app.models.models import OrderMaterial
from app.services.number_utils import round_qty


def upsert_order_material(db: Session, order_id: int, material_id: int, qty_received_delta: float = 0, qty_issued_delta: float = 0):
    """
    يربط مادة بأمر معين فعلياً (مش نص وصفي) ويحدّث الكميات الواردة/الصادرة عليه.
    ده المصدر الوحيد للحقيقة لمعرفة "هل المادة دي فعلاً مسجلة على الأمر ده ولا لأ".
    """
    om = db.query(OrderMaterial).filter(
        OrderMaterial.order_id == order_id, OrderMaterial.material_id == material_id
    ).first()
    if om:
        if qty_received_delta:
            om.quantity_received = round_qty(om.quantity_received + qty_received_delta)
            om.quantity_required = om.quantity_received
        if qty_issued_delta:
            om.quantity_issued = round_qty(om.quantity_issued + qty_issued_delta)
    else:
        om = OrderMaterial(
            order_id=order_id, material_id=material_id,
            quantity_required=round_qty(qty_received_delta),
            quantity_received=round_qty(qty_received_delta),
            quantity_issued=round_qty(qty_issued_delta)
        )
        db.add(om)
    return om


def get_order_material_remaining(db: Session, order_id: int, material_id: int) -> float:
    """الكمية المتاحة فعلياً من مادة معينة في أمر معين (الوارد ناقص الصادر)."""
    om = db.query(OrderMaterial).filter(
        OrderMaterial.order_id == order_id, OrderMaterial.material_id == material_id
    ).first()
    if not om:
        return 0.0
    return round_qty(om.quantity_received - om.quantity_issued)
