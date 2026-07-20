from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_CENTER
import arabic_reshaper
from bidi.algorithm import get_display
import io
import os
from datetime import datetime
from xml.sax.saxutils import escape


BRAND_BLUE = colors.HexColor("#1F5C99")
LIGHT_BLUE = colors.HexColor("#EEF4FB")
DARK_GRAY = colors.HexColor("#404040")

# ─── Arabic + Latin font registration ────────────────────────────────────────
# نستخدم خطين مدمجين جوه المشروع (مش معتمدين على السيرفر):
# - Noto Naskh Arabic: للحروف العربية
# - DejaVu Sans: للأرقام والحروف اللاتينية (زي أكواد ISS-2026-0001)
# لأن أي خط عربي بمفرده غالباً ملوش حروف/رموز لاتينية، والعكس صحيح.
_FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "fonts")
pdfmetrics.registerFont(TTFont("Arabic", os.path.join(_FONT_DIR, "NotoNaskhArabic-Regular.ttf")))
pdfmetrics.registerFont(TTFont("Arabic-Bold", os.path.join(_FONT_DIR, "NotoNaskhArabic-Bold.ttf")))
pdfmetrics.registerFont(TTFont("Latin", os.path.join(_FONT_DIR, "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("Latin-Bold", os.path.join(_FONT_DIR, "DejaVuSans-Bold.ttf")))

# نطاقات اليونيكود للحروف العربية (بعد التشكيل بتاع arabic_reshaper بتتحول لأشكال عرض)
_ARABIC_RANGES = [
    (0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF), (0xFE70, 0xFEFF),
]


def _is_arabic_char(ch: str) -> bool:
    code = ord(ch)
    return any(start <= code <= end for start, end in _ARABIC_RANGES)


def ar(text, bold: bool = False) -> str:
    """
    يحوّل أي نص (عربي أو مختلط عربي/إنجليزي/أرقام) لعلامات <font> جاهزة للطباعة:
    - reshape + get_display: يربط الحروف العربية ويرتب النص بصرياً (RTL)
    - تقسيم النص لأجزاء عربي / لاتيني، وتوصيل كل جزء بالخط المناسب له
      (خط عربي واحد غالباً مبيدعمش أرقام وحروف إنجليزية، فلازم خطين).
    """
    if text is None:
        return "—"
    text = str(text)
    reshaped = arabic_reshaper.reshape(text)
    display = get_display(reshaped)

    ar_font = "Arabic-Bold" if bold else "Arabic"
    lat_font = "Latin-Bold" if bold else "Latin"

    runs = []
    current_font = None
    current_chars = []
    for ch in display:
        font = ar_font if _is_arabic_char(ch) else lat_font
        if current_font is None:
            current_font = font
        if font != current_font and ch != " ":
            runs.append((current_font, "".join(current_chars)))
            current_chars = [ch]
            current_font = font
        else:
            current_chars.append(ch)
    if current_chars:
        runs.append((current_font, "".join(current_chars)))

    parts = [f'<font face="{font}">{escape(chunk)}</font>' for font, chunk in runs]
    return "".join(parts)


def build_pdf(title: str, subtitle: str, rows: list, ref_number: str = "") -> bytes:
    """
    Generic receipt builder.
    rows = list of (label, value) tuples
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )

    story = []

    # Header
    header_data = [[
        Paragraph(ar(title, bold=True), ParagraphStyle(
            "title", fontSize=16, textColor=colors.white,
            alignment=TA_CENTER, fontName="Arabic-Bold"
        )),
    ]]
    header_table = Table(header_data, colWidths=[17*cm])
    header_table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), BRAND_BLUE),
        ("TOPPADDING", (0,0), (-1,-1), 12),
        ("BOTTOMPADDING", (0,0), (-1,-1), 12),
        ("ROUNDEDCORNERS", [5]),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 0.4*cm))

    # Subtitle & ref
    story.append(Paragraph(
        ar(subtitle, bold=True),
        ParagraphStyle("subtitle", fontSize=12, textColor=BRAND_BLUE, alignment=TA_CENTER, fontName="Arabic-Bold")
    ))
    if ref_number:
        story.append(Paragraph(
            ar(f"رقم المرجع: {ref_number}"),
            ParagraphStyle("ref", fontSize=10, textColor=DARK_GRAY, alignment=TA_CENTER, fontName="Arabic")
        ))
    story.append(Spacer(1, 0.4*cm))
    story.append(HRFlowable(width="100%", thickness=1, color=BRAND_BLUE))
    story.append(Spacer(1, 0.4*cm))

    # Data rows
    table_data = []
    for label, value in rows:
        table_data.append([
            Paragraph(ar(label, bold=True), ParagraphStyle(
                "label", fontSize=10, textColor=DARK_GRAY, fontName="Arabic-Bold", alignment=TA_CENTER
            )),
            Paragraph(ar(value) if value not in (None, "") else "—", ParagraphStyle(
                "value", fontSize=10, textColor=DARK_GRAY, fontName="Arabic", alignment=TA_CENTER
            ))
        ])

    data_table = Table(table_data, colWidths=[6*cm, 11*cm])
    data_table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), colors.white),
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [colors.white, LIGHT_BLUE]),
        ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#CCCCCC")),
        ("TOPPADDING", (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ("LEFTPADDING", (0,0), (-1,-1), 10),
        ("RIGHTPADDING", (0,0), (-1,-1), 10),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
    ]))
    story.append(data_table)
    story.append(Spacer(1, 0.6*cm))

    # Footer
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#CCCCCC")))
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph(
        ar(f"تاريخ الطباعة: {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  نظام إدارة المستودع"),
        ParagraphStyle("footer", fontSize=8, textColor=colors.HexColor("#999999"), alignment=TA_CENTER, fontName="Arabic")
    ))

    doc.build(story)
    return buffer.getvalue()


def generate_order_receipt(order, gate_passes=None) -> bytes:
    rows = [
        ("الكود التسلسلي", order.reference_code or "—"),
        ("رقم الأمر", order.order_number),
        ("نوع الأمر", "أمر شغل" if order.order_type.value == "work_order" else "أمر صيانة"),
        ("الحالة", order.status.value),
        ("المستودع المصدر", order.supplier.name if order.supplier else "—"),
        ("المشرف المستلم", order.receiving_supervisor.full_name if order.receiving_supervisor else "—"),
        ("المشرف المُصدِر", order.issuing_supervisor.full_name if order.issuing_supervisor else "—"),
        ("السائق", order.driver_name or "—"),
        ("تاريخ الإنشاء", order.created_at.strftime("%Y-%m-%d %H:%M") if order.created_at else "—"),
        ("ملاحظات", order.notes or "—"),
    ]
    if gate_passes:
        for i, gp in enumerate(gate_passes, 1):
            rows.append((f"Gate Pass #{i}", gp.gate_pass_code))
    return build_pdf("وصل أمر عمل", "تفاصيل الأمر", rows, ref_number=order.reference_code or order.order_number)


def generate_issuance_receipt(issuance) -> bytes:
    type_map = {
        "network_consumption": "استهلاك داخل الشبكة",
        "personal_custody_temporary": "عهدة شخصية مؤقتة",
        "personal_custody_permanent": "عهدة شخصية دائمة",
        "damaged": "تالف",
    }
    rows = [
        ("الكود التسلسلي", issuance.reference_code or "—"),
        ("رقم الأمر", issuance.order.order_number if issuance.order else "—"),
        ("المادة", issuance.material.name if issuance.material else "—"),
        ("الكمية", f"{issuance.quantity} {issuance.material.unit.value if issuance.material else ''}"),
        ("نوع الصرف", type_map.get(issuance.issuance_type.value, issuance.issuance_type.value)),
        ("رقم MDR", issuance.mdr_number or "—"),
        ("اسم المستلم", issuance.recipient_name or "—"),
        ("المشرف", issuance.supervisor.full_name if issuance.supervisor else "—"),
        ("السائق", issuance.driver_name),
        ("من المخزون العام", "نعم" if issuance.is_from_general_stock else "لا"),
        ("التاريخ والوقت", issuance.created_at.strftime("%Y-%m-%d %H:%M") if issuance.created_at else "—"),
        ("ملاحظات", issuance.notes or "—"),
    ]
    return build_pdf("وصل إصدار مواد", "تفاصيل عملية الإصدار", rows, ref_number=issuance.reference_code or str(issuance.id))


def generate_borrowing_receipt(borrow) -> bytes:
    source_label = "—"
    if getattr(borrow, "source_type", None) and borrow.source_type == "contractor":
        source_label = f"مقاول: {borrow.contractor_name}"
    elif borrow.source_order:
        source_label = borrow.source_order.order_number
    elif borrow.source_description:
        source_label = borrow.source_description

    rows = [
        ("الكود التسلسلي", borrow.reference_code or "—"),
        ("الاتجاه", "تسليف لمقاول" if getattr(borrow, "direction", None) == "lend_out" else "استلاف"),
        ("أمر الاستلاف", borrow.borrowing_order.order_number if borrow.borrowing_order else "—"),
        ("المصدر / الجهة", source_label),
        ("المادة", borrow.material.name if borrow.material else "—"),
        ("الكمية", f"{borrow.quantity} {borrow.material.unit.value if borrow.material else ''}"),
        ("المشرف المسجِّل", borrow.supervisor.full_name if borrow.supervisor else "—"),
        ("الحالة", "مُسترجع" if borrow.status.value == "returned" else "معلق"),
        ("تاريخ الاستلاف", borrow.created_at.strftime("%Y-%m-%d %H:%M") if borrow.created_at else "—"),
        ("تاريخ الإرجاع", borrow.return_date.strftime("%Y-%m-%d %H:%M") if borrow.return_date else "—"),
        ("ملاحظات", borrow.notes or "—"),
    ]
    return build_pdf("وصل استلاف", "تفاصيل عملية الاستلاف", rows, ref_number=borrow.reference_code or str(borrow.id))


def generate_transfer_receipt(transfer) -> bytes:
    rows = [
        ("الكود التسلسلي", transfer.reference_code or "—"),
        ("المادة", transfer.material.name if transfer.material else "—"),
        ("الكمية", f"{transfer.quantity} {transfer.material.unit.value if transfer.material else ''}"),
        ("المشرف المسجِّل", transfer.supervisor.full_name if transfer.supervisor else "—"),
        ("الموقع من", transfer.location_from),
        ("الموقع إلى", transfer.location_to),
        ("التاريخ والوقت", transfer.created_at.strftime("%Y-%m-%d %H:%M") if transfer.created_at else "—"),
        ("ملاحظات", transfer.notes or "—"),
    ]
    return build_pdf("وصل نقل داخلي", "تفاصيل عملية النقل", rows, ref_number=transfer.reference_code or str(transfer.id))


def generate_return_receipt(ret) -> bytes:
    classification_map = {
        "damaged": "تالف",
        "reuse": "إعادة استخدام",
        "maintenance": "صيانة"
    }
    rows = [
        ("الكود التسلسلي", ret.reference_code or "—"),
        ("رقم الأمر", ret.order.order_number if ret.order else "—"),
        ("المادة", ret.material.name if ret.material else "—"),
        ("الكمية", f"{ret.quantity} {ret.material.unit.value if ret.material else ''}"),
        ("نوع الإرجاع", classification_map.get(ret.return_classification.value, ret.return_classification.value)),
        ("المشرف", ret.supervisor.full_name if ret.supervisor else "—"),
        ("التاريخ والوقت", ret.created_at.strftime("%Y-%m-%d %H:%M") if ret.created_at else "—"),
        ("ملاحظات", ret.notes or "—"),
    ]
    return build_pdf("وصل مرتجع", "تفاصيل عملية الإرجاع", rows, ref_number=ret.reference_code or str(ret.id))


def generate_order_materials_receipt(order, materials_status: list) -> bytes:
    """
    وصل قابل للطباعة لحالة المواد المسجلة على أمر معين (كام دخل، كام خرج، الباقي فين).
    materials_status = list of dicts: {name, received, issued, remaining, unit}
    """
    rows = [
        ("رقم الأمر", order.order_number),
        ("الكود التسلسلي", order.reference_code or "—"),
        ("الحالة العامة", order.status.value),
    ]
    for m in materials_status:
        rows.append((
            f"{m['name']} ({m['unit']})",
            f"وارد: {m['received']} | صادر: {m['issued']} | متبقي بالمخزن: {m['remaining']}"
        ))
    return build_pdf("وصل حالة مواد الأمر", f"أمر رقم {order.order_number}", rows, ref_number=order.reference_code or order.order_number)
