def round_qty(value: float) -> float:
    """
    تقريب أي كمية لرقمين عشريين كحد أقصى، عشان نمنع مشاكل دقة الأرقام العشرية
    (زي إن 20 تتحول لـ 19.999999999996 بعد كذا عملية جمع/طرح على float).
    """
    if value is None:
        return value
    return round(float(value), 2)
