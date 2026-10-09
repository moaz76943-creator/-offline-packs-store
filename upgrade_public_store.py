import os
import json
import gzip
import hashlib

os.makedirs('packs', exist_ok=True)
os.makedirs('images', exist_ok=True)

# 1. إنشاء صور بمسميات عامة (Universal Asset Keys)
dummy_webp = b'RIFF\x1a\x00\x00\x00WEBPVP8 X\x0a\x00\x00\x00\x10\x00\x00\x00\x00\x00\x00\x00\x00\x00VP8I\x0e\x00\x00\x00\x01\x00\x00\xef\x00\x00\x01 \x01\x00\x02\x00\x03\x00'

for img_name in ['apple.webp', 'car.webp']:
    with open(os.path.join('images', img_name), 'wb') as f:
        f.write(dummy_webp)

# 2. بناء بيانات حزمة الألمانية A1 بروابط CDN سريعة ومسميات عامة
pack_data = {
    "language": "German",
    "level": "A1",
    "version": "4.0.0",
    "vocabulary": [
        {
            "word": "Apfel",
            "article": "der",
            "translation": "تفاحة",
            "image_url": "https://cdn.jsdelivr.net/gh/moaz76943-creator/-offline-packs-store@main/images/apple.webp"
        },
        {
            "word": "Auto",
            "article": "das",
            "translation": "سيارة",
            "image_url": "https://cdn.jsdelivr.net/gh/moaz76943-creator/-offline-packs-store@main/images/car.webp"
        }
    ]
}

pack_path = 'packs/deutsch_a1.pack.gz'
with gzip.open(pack_path, 'wt', encoding='utf-8') as f:
    json.dump(pack_data, f, ensure_ascii=False)

# 3. حساب حجم الملف وبصمة sha256 للتأكد من سلامة التنزيل
file_size = os.path.getsize(pack_path)
with open(pack_path, 'rb') as f:
    sha256_hash = hashlib.sha256(f.read()).hexdigest()

# 4. تحديث version.json ليشمل الهاش وحجم الملف
version_data = {
    "latest_version": "4.0.0",
    "packs": {
        "deutsch_a1": {
            "version": "4.0.0",
            "size_bytes": file_size,
            "sha256": sha256_hash,
            "file_url": "https://cdn.jsdelivr.net/gh/moaz76943-creator/-offline-packs-store@main/packs/deutsch_a1.pack.gz"
        }
    }
}

with open('version.json', 'w', encoding='utf-8') as f:
    json.dump(version_data, f, ensure_ascii=False, indent=2)

# 5. إنشاء فهرس اللغات والمستويات الديناميكي manifest.json
manifest_data = {
    "available_languages": [
        {
            "id": "de",
            "name": "Deutsch",
            "name_ar": "الألمانية",
            "flag": "🇩🇪",
            "levels": [
                {
                    "level_id": "deutsch_a1",
                    "title": "A1 - مبتدئ",
                    "words_count": 2,
                    "version": "4.0.0",
                    "pack_url": "https://cdn.jsdelivr.net/gh/moaz76943-creator/-offline-packs-store@main/packs/deutsch_a1.pack.gz"
                }
            ]
        }
    ]
}

with open('manifest.json', 'w', encoding='utf-8') as f:
    json.dump(manifest_data, f, ensure_ascii=False, indent=2)

print("تم تحديث المستودع العام بنجاح بجميع المعايير!")
