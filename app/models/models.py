from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean, DateTime,
    ForeignKey, Enum as SAEnum, JSON
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


# ─── ENUMS ───────────────────────────────────────────────────────────────────

class UserRole(str, enum.Enum):
    admin = "admin"
    supervisor = "supervisor"

class MaterialCategory(str, enum.Enum):
    cable = "cable"
    consumable = "consumable"
    tool = "tool"
    device = "device"

class MaterialUnit(str, enum.Enum):
    meters = "meters"
    units = "units"
    each = "each"

class OrderType(str, enum.Enum):
    work_order = "work_order"
    maintenance_order = "maintenance_order"

class OrderStatus(str, enum.Enum):
    open = "open"
    partially_received = "partially_received"
    fully_received = "fully_received"
    issued = "issued"
    closed = "closed"
    missing_materials = "missing_materials"          # ينقصه مواد
    completed_via_borrow = "completed_via_borrow"    # مكتمل بالاستلاف
    lent_to_other_order = "lent_to_other_order"       # تم الاستلاف منه (أعطى لأمر تاني)
    borrow_returned = "borrow_returned"                # تم رد الاستلاف

class ReturnClassification(str, enum.Enum):
    damaged = "damaged"
    reuse = "reuse"
    maintenance = "maintenance"

class BorrowStatus(str, enum.Enum):
    pending = "pending"
    returned = "returned"

class BorrowSourceType(str, enum.Enum):
    internal = "internal"       # استلاف داخلي (من أمر عمل تاني)
    contractor = "contractor"   # من/إلى مقاول خارجي

class BorrowDirection(str, enum.Enum):
    borrow_in = "borrow_in"     # استلاف (بناخد إحنا)
    lend_out = "lend_out"       # تسليف (بندي إحنا لمقاول)

class BorrowReturnDestination(str, enum.Enum):
    same_source = "same_source"          # يرجع لنفس أمر المصدر
    different_order = "different_order"  # يرجع لأمر عمل تاني
    general_stock = "general_stock"      # يرجع للمخزون العام

class IssuanceType(str, enum.Enum):
    network_consumption = "network_consumption"       # استهلاك داخل الشبكة
    personal_custody_temporary = "personal_custody_temporary"   # عهدة شخصية مؤقتة
    personal_custody_permanent = "personal_custody_permanent"   # عهدة شخصية دائمة
    damaged = "damaged"                                # تالف

class MaintenanceStatus(str, enum.Enum):
    pending = "pending"       # قيد الفحص/الصيانة
    repaired = "repaired"     # تم الإصلاح وإعادة التنشيط
    scrapped = "scrapped"     # تكهين نهائي (تالف تماماً)

class AuditAction(str, enum.Enum):
    create = "create"
    edit = "edit"
    delete = "delete"
    restore = "restore"


# ─── USERS ───────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(100), nullable=False)
    username = Column(String(50), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(SAEnum(UserRole), nullable=False, default=UserRole.supervisor)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    issued_orders = relationship("Order", foreign_keys="Order.issuing_supervisor_id", back_populates="issuing_supervisor")
    received_orders = relationship("Order", foreign_keys="Order.receiving_supervisor_id", back_populates="receiving_supervisor")
    tool_holdings = relationship("Material", foreign_keys="Material.holder_id", back_populates="holder")
    # (تم إلغاء العلاقات القديمة borrowings_made/transfers_from/transfers_to بعد تبسيط الجداول للمشرف الواحد)
    audit_logs = relationship("AuditLog", back_populates="user")


# ─── SUPPLIERS ───────────────────────────────────────────────────────────────

class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    contact_person = Column(String(100), nullable=True)
    phone = Column(String(50), nullable=True)
    agreement_date = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)
    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deleted_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# ─── MATERIALS ───────────────────────────────────────────────────────────────

class Material(Base):
    __tablename__ = "materials"

    id = Column(Integer, primary_key=True, index=True)
    item_code = Column(Integer, unique=True, nullable=True, index=True)  # كود الصنف الثابت (1 = عداد، 2 = جوينت، إلخ)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    category = Column(SAEnum(MaterialCategory), nullable=False)
    unit = Column(SAEnum(MaterialUnit), nullable=False)
    current_stock = Column(Float, nullable=False, default=0)
    photo_url = Column(String(500), nullable=True)
    holder_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # tools only
    is_general_stock = Column(Boolean, default=False)
    # --- Warehouse requirements additions ---
    serial_number = Column(String(150), nullable=True)          # السيريال نمبر
    consultant_name = Column(String(150), nullable=True)        # (قديم) نص وصفي فقط - غير مستخدم للربط الفعلي
    linked_order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)  # ربط فعلي بأمر العمل/الصيانة
    supply_source = Column(String(200), nullable=True)          # (قديم - غير مستخدم في الفورم حالياً)
    related_gate_pass_no = Column(String(100), nullable=True)   # رقم Gate Pass المرتبط (لو المادة جايه على أمر شغل)
    expiry_date = Column(DateTime(timezone=True), nullable=True)  # تاريخ انتهاء الصلاحية/الضمان
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True)
    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deleted_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    holder = relationship("User", foreign_keys=[holder_id], back_populates="tool_holdings")
    supplier = relationship("Supplier", foreign_keys=[supplier_id])
    linked_order = relationship("Order", foreign_keys=[linked_order_id])
    order_materials = relationship("OrderMaterial", back_populates="material")
    issuances = relationship("Issuance", back_populates="material")
    borrowings = relationship("Borrowing", back_populates="material")
    transfers = relationship("Transfer", back_populates="material")
    returns = relationship("Return", back_populates="material")


# ─── ORDERS ──────────────────────────────────────────────────────────────────

class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    reference_code = Column(String(50), unique=True, nullable=True, index=True)  # كود تسلسلي فريد (دفتر الكربون)
    order_number = Column(String(100), nullable=False, unique=True, index=True)
    order_type = Column(SAEnum(OrderType), nullable=False)
    status = Column(SAEnum(OrderStatus), nullable=False, default=OrderStatus.open)
    notes = Column(Text, nullable=True)
    receiving_supervisor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    issuing_supervisor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True)  # المستودع المصدر (الدمام/بن قريعة)
    driver_name = Column(String(100), nullable=True)
    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deleted_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    receiving_supervisor = relationship("User", foreign_keys=[receiving_supervisor_id], back_populates="received_orders")
    issuing_supervisor = relationship("User", foreign_keys=[issuing_supervisor_id], back_populates="issued_orders")
    supplier = relationship("Supplier", foreign_keys=[supplier_id])
    gate_passes = relationship("GatePass", back_populates="order", cascade="all, delete-orphan")
    order_materials = relationship("OrderMaterial", back_populates="order")
    issuances = relationship("Issuance", back_populates="order")
    borrowings_as_source = relationship("Borrowing", foreign_keys="Borrowing.source_order_id", back_populates="source_order")
    borrowings_as_borrower = relationship("Borrowing", foreign_keys="Borrowing.borrowing_order_id", back_populates="borrowing_order")
    returns = relationship("Return", back_populates="order")


class GatePass(Base):
    __tablename__ = "gate_passes"

    id = Column(Integer, primary_key=True, index=True)
    reference_code = Column(String(50), unique=True, nullable=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    gate_pass_code = Column(String(100), nullable=False)
    document_photo_url = Column(String(500), nullable=False)
    driver_name = Column(String(100), nullable=False)
    receiving_supervisor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    notes = Column(Text, nullable=True)
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    order = relationship("Order", back_populates="gate_passes")
    receiving_supervisor = relationship("User", foreign_keys=[receiving_supervisor_id])
    materials = relationship("GatePassMaterial", back_populates="gate_pass", cascade="all, delete-orphan")


class GatePassMaterial(Base):
    __tablename__ = "gate_pass_materials"

    id = Column(Integer, primary_key=True, index=True)
    gate_pass_id = Column(Integer, ForeignKey("gate_passes.id"), nullable=False)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False)
    quantity = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    gate_pass = relationship("GatePass", back_populates="materials")
    material = relationship("Material")


class OrderMaterial(Base):
    __tablename__ = "order_materials"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False)
    quantity_required = Column(Float, nullable=False)
    quantity_received = Column(Float, nullable=False, default=0)
    quantity_issued = Column(Float, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    order = relationship("Order", back_populates="order_materials")
    material = relationship("Material", back_populates="order_materials")


# ─── ISSUANCES ───────────────────────────────────────────────────────────────

class Issuance(Base):
    __tablename__ = "issuances"

    id = Column(Integer, primary_key=True, index=True)
    reference_code = Column(String(50), unique=True, nullable=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False)
    quantity = Column(Float, nullable=False)
    supervisor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    driver_name = Column(String(100), nullable=False)
    recipient_name = Column(String(150), nullable=False, default="")  # اسم المستلم للمواد المصروفة
    issuance_type = Column(SAEnum(IssuanceType), nullable=False, default=IssuanceType.network_consumption)
    mdr_number = Column(String(100), nullable=True)            # رقم مرجعي MDR
    notes = Column(Text, nullable=True)
    is_from_general_stock = Column(Boolean, default=False)
    # --- استرجاع العدة (Tools) المُصرَّفة كعهدة مؤقتة فقط - المستهلكات لا ترجع أبداً ---
    is_returned_to_stock = Column(Boolean, default=False)
    returned_to_stock_at = Column(DateTime(timezone=True), nullable=True)
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    order = relationship("Order", back_populates="issuances")
    material = relationship("Material", back_populates="issuances")
    supervisor = relationship("User", foreign_keys=[supervisor_id])


# ─── BORROWING ───────────────────────────────────────────────────────────────

class Borrowing(Base):
    __tablename__ = "borrowings"

    id = Column(Integer, primary_key=True, index=True)
    reference_code = Column(String(50), unique=True, nullable=True, index=True)
    borrowing_order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    source_type = Column(SAEnum(BorrowSourceType), nullable=False, default=BorrowSourceType.internal)
    direction = Column(SAEnum(BorrowDirection), nullable=False, default=BorrowDirection.borrow_in)
    contractor_name = Column(String(200), nullable=True)  # إجباري لو source_type = contractor
    source_order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    source_description = Column(String(200), nullable=True)  # if not from an order
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False)
    quantity = Column(Float, nullable=False)
    supervisor_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # المشرف المسجّل دخوله وقت العملية (تلقائي)
    status = Column(SAEnum(BorrowStatus), nullable=False, default=BorrowStatus.pending)
    return_date = Column(DateTime(timezone=True), nullable=True)
    return_destination_type = Column(SAEnum(BorrowReturnDestination), nullable=True)
    return_destination_order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    notes = Column(Text, nullable=True)
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    borrowing_order = relationship("Order", foreign_keys=[borrowing_order_id], back_populates="borrowings_as_borrower")
    source_order = relationship("Order", foreign_keys=[source_order_id], back_populates="borrowings_as_source")
    return_destination_order = relationship("Order", foreign_keys=[return_destination_order_id])
    material = relationship("Material", back_populates="borrowings")
    supervisor = relationship("User", foreign_keys=[supervisor_id])


# ─── TRANSFERS ───────────────────────────────────────────────────────────────

class Transfer(Base):
    __tablename__ = "transfers"

    id = Column(Integer, primary_key=True, index=True)
    reference_code = Column(String(50), unique=True, nullable=True, index=True)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False)
    quantity = Column(Float, nullable=False)
    supervisor_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # المشرف المسجّل دخوله وقت العملية (تلقائي)
    location_from = Column(String(200), nullable=False)
    location_to = Column(String(200), nullable=False)
    notes = Column(Text, nullable=True)
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    material = relationship("Material", back_populates="transfers")
    supervisor = relationship("User", foreign_keys=[supervisor_id])


# ─── RETURNS ─────────────────────────────────────────────────────────────────

class Return(Base):
    __tablename__ = "returns"

    id = Column(Integer, primary_key=True, index=True)
    reference_code = Column(String(50), unique=True, nullable=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False)
    quantity = Column(Float, nullable=False)
    return_classification = Column(SAEnum(ReturnClassification), nullable=False)
    supervisor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    # --- Maintenance & closing workflow (شاشة فحص الأجهزة المعطلة وإغلاق الأوامر) ---
    maintenance_status = Column(SAEnum(MaintenanceStatus), nullable=True)  # فقط للتصنيف "صيانة"
    closed_at = Column(DateTime(timezone=True), nullable=True)
    closed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    notes = Column(Text, nullable=True)
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    order = relationship("Order", back_populates="returns")
    material = relationship("Material", back_populates="returns")
    supervisor = relationship("User", foreign_keys=[supervisor_id])
    closed_by = relationship("User", foreign_keys=[closed_by_id])


# ─── AUDIT LOG ───────────────────────────────────────────────────────────────

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    action = Column(SAEnum(AuditAction), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(Integer, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    before_data = Column(JSON, nullable=True)
    after_data = Column(JSON, nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="audit_logs")
