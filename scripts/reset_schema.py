import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.database import Base, engine


def main() -> None:
    print("جاري حذف الجداول القديمة وإعادة إنشائها...")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    print("تم إنشاء الهيكل الجديد للقاعدة بنجاح")


if __name__ == "__main__":
    main()
