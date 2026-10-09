import os
import json
import gzip
import hashlib

# 1. تجهيز مجلدات العمل ومجلدات إجراءات غيت هاب (GitHub Actions)
os.makedirs('packs', exist_ok=True)
os.makedirs('images', exist_ok=True)
os.makedirs('.github/workflows', exist_ok=True)

# 2. إنشاء ملف فحص الأخطاء التلقائي (GitHub Actions CI/CD)
# هذا الملف عام وآمن تماماً، وظيفته فقط فحص صحة الـ JSON عند أي رفع لضمان عدم انهيار التطبيق
github_action_yml = """
name: Validate JSON Files
on: [push, pull_request]
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v3
      - name: Check JSON Syntax
        run: |
          find . -name "*.json" -not -path "*/.git/*" -print0 | xargs -0 -I {} bash -c 'jq . "{}" >/dev/null || (echo "❌ خطأ في تنسيق الملف: {}" && exit 1)'
"""
with open('.github/workflows/validate_json.yml', 'w', encoding='utf-8') as f:
    f.write(github_action_yml.strip())

# 3. وظيفة ضغط فائقة (Minification + Gzip) لحفظ الحزم وتقليل الحجم
def create_minified_pack(filename, data):
    path = os.path.join('packs', filename)
    with gzip.open(path, 'wt', encoding='utf-8') as f:
        # استخدام separators=(',', ':') يزيل كل الفراغات ويقلل الحجم بشكل كبير
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    
    file_size = os.path.getsize(path)
    with open(path, 'rb') as f:
        file_hash = hashlib.sha256(f.read()).hexdigest()
    
    return file_size, file_hash

# 4. تطبيق "التقسيم المعماري" (Chunking) - مثال على اللغة الألمانية
vocab_data = {"type": "vocabulary", "items": [{"word": "Apfel", "image": "apple.webp"}]}
verbs_data = {"type": "verbs", "items": [{"verb": "sein", "translation": "يكون"}]}
grammar_data = {"type": "grammar", "items": [{"rule": "Akkusativ", "desc": "المفعول به"}]}

# إنشاء 3 ملفات منفصلة بدلاً من ملف ضخم واحد
v_size, v_hash = create_minified_pack('de_vocab_a1.pack.gz', vocab_data)
vb_size, vb_hash = create_minified_pack('de_verbs_a1.pack.gz', verbs_data)
g_size, g_hash = create_minified_pack('de_grammar_a1.pack.gz', grammar_data)

# 5. بناء الفهرس الديناميكي (manifest.json) مع "الثيمات البصرية" (Theme Colors)
# سنضع عينة لـ 3 لغات فقط لتوضيح الفكرة (يتم تطبيقها على الـ 100 لغة)
manifest_data = {
    "version": "5.0.0",
    "global_cdn_base": "https://cdn.jsdelivr.net/gh/moaz76943-creator/-offline-packs-store@main",
    "languages": [
        {
            "code": "de",
            "name": "Deutsch",
            "name_ar": "الألمانية",
            "flag": "🇩🇪",
            "theme_color": "#FFCE00", # ثيم أصفر مميز للواجهات
            "chunks": {
                "vocabulary": {"file": "/packs/de_vocab_a1.pack.gz", "size": v_size, "sha256": v_hash},
                "verbs": {"file": "/packs/de_verbs_a1.pack.gz", "size": vb_size, "sha256": vb_hash},
                "grammar": {"file": "/packs/de_grammar_a1.pack.gz", "size": g_size, "sha256": g_hash}
            }
        },
        {
            "code": "es",
            "name": "Español",
            "name_ar": "الإسبانية",
            "flag": "🇪🇸",
            "theme_color": "#AA151B" # ثيم أحمر داكن
        },
        {
            "code": "fr",
            "name": "Français",
            "name_ar": "الفرنسية",
            "flag": "🇫🇷",
            "theme_color": "#0055A4" # ثيم أزرق فرنسي
        }
    ]
}

with open('manifest.json', 'w', encoding='utf-8') as f:
    json.dump(manifest_data, f, ensure_ascii=False, indent=2)

print("تم تطبيق جميع الخصائص المثالية (التصغير الفائق، التقسيم، الثيمات، وحماية غيت هاب) بأمان تام!")
