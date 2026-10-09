import gzip, json, os

os.makedirs('images', exist_ok=True)
dummy_webp = b'RIFF\x1a\x00\x00\x00WEBPVP8 X\x0a\x00\x00\x00\x10\x00\x00\x00\x00\x00\x00\x00\x00\x00VP8I\x0e\x00\x00\x00\x01\x00\x00\xef\x00\x00\x01 \x01\x00\x02\x00\x03\x00'

for img_name in ['apfel.webp', 'auto.webp']:
    with open(os.path.join('images', img_name), 'wb') as img_file:
        img_file.write(dummy_webp)

data = {
    'language': 'German',
    'version': '4.0.0',
    'vocabulary': [
        {
            'word': 'Apfel',
            'article': 'der',
            'translation': 'تفاحة',
            'image_url': 'https://raw.githubusercontent.com/moaz76943-creator/-offline-packs-store/main/images/apfel.webp'
        },
        {
            'word': 'Auto',
            'article': 'das',
            'translation': 'سيارة',
            'image_url': 'https://raw.githubusercontent.com/moaz76943-creator/-offline-packs-store/main/images/auto.webp'
        }
    ]
}

with gzip.open('deutsch_deep_master.pack.gz', 'wt', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False)

print('تم إنشاء الصور وملف الحزمة بنجاح!')
