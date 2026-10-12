import os
import json
import gzip
from shared import dummy_webp

# إنشاء المجلدات التنظيمية
os.makedirs('packs', exist_ok=True)
os.makedirs('images', exist_ok=True)

# 1. إنشاء ملف فحص الإصدارات السريع في الجذر
version_data = {
    "latest_version": "4.0.0",
    "packs": {
        "deutsch_a1": {
            "version": "4.0.0",
            "file_url": "https://raw.githubusercontent.com/moaz76943-creator/-offline-packs-store/main/packs/deutsch_a1.pack.gz"
        }
    }
}

with open('version.json', 'w', encoding='utf-8') as f:
    json.dump(version_data, f, ensure_ascii=False, indent=2)

# 2. إنشاء بيانات حزمة المستوى الأول (A1)
pack_data = {
    "language": "German",
    "level": "A1",
    "version": "4.0.0",
    "vocabulary": [
        {
            "word": "Apfel",
            "article": "der",
            "translation": "تفاحة",
            "image_url": "https://raw.githubusercontent.com/moaz76943-creator/-offline-packs-store/main/images/apfel.webp"
        }
    ]
}

with gzip.open('packs/deutsch_a1.pack.gz', 'wt', encoding='utf-8') as f:
    json.dump(pack_data, f, ensure_ascii=False)

# 3. إنشاء صورة تجريبية بصيغة webp
with open('images/apfel.webp', 'wb') as f:
    f.write(dummy_webp)

print("تم تجهيز هيكل المستودع العام بنجاح!")
