import os
import json
import gzip
import hashlib

# 1. إنشاء مجلدات العمل
os.makedirs('packs', exist_ok=True)
os.makedirs('images', exist_ok=True)

# 2. إنشاء ملف الحماية .gitignore
gitignore_content = """
*.env
*.key
*.pem
__pycache__/
*.pyc
.DS_Store
*.log
"""
with open('.gitignore', 'w', encoding='utf-8') as f:
    f.write(gitignore_content.strip())

# 3. قائمة اللغات القياسية (100 لغة مع الرموز والأعلام والأسماء بالعربية)
languages_base = [
    ("de", "Deutsch", "الألمانية", "🇩🇪"),
    ("en", "English", "الإنجليزية", "🇬🇧"),
    ("fr", "Français", "الفرنسية", "🇫🇷"),
    ("es", "Español", "الإسبانية", "🇪🇸"),
    ("it", "Italiano", "الإيطالية", "🇮🇹"),
    ("tr", "Türkçe", "التركية", "🇹🇷"),
    ("ru", "Русский", "الروسية", "🇷🇺"),
    ("ar", "العربية", "العربية", "🇸🇦"),
    ("zh", "中文", "الصينية", "🇨🇳"),
    ("ja", "日本語", "اليابانية", "🇯🇵"),
    ("ko", "한국어", "الكورية", "🇰🇷"),
    ("pt", "Português", "البرتغالية", "🇵🇹"),
    ("nl", "Nederlands", "الهولندية", "🇳🇱"),
    ("pl", "Polski", "البولندية", "🇵🇱"),
    ("sv", "Svenska", "السويدية", "🇸🇪"),
    ("no", "Norsk", "النرويجية", "🇳🇴"),
    ("da", "Dansk", "الدانماركية", "🇩🇰"),
    ("fi", "Suomi", "الفنلندية", "🇫🇮"),
    ("el", "Ελληνικά", "اليونانية", "🇬🇷"),
    ("hi", "हिन्दी", "الهندية", "🇮🇳"),
    ("id", "Bahasa Indonesia", "الإندونيسية", "🇮🇩"),
    ("ms", "Bahasa Melayu", "الماليزية", "🇲🇾"),
    ("fa", "فارسی", "الفارسية", "🇮🇷"),
    ("ur", "اردو", "الأردية", "🇵🇰"),
    ("vi", "Tiếng Việt", "الفيتنامية", "🇻🇳"),
    ("th", "ไทย", "التايلاندية", "🇹🇭"),
    ("uk", "Українська", "الأوكرانية", "🇺🇦"),
    ("ro", "Română", "الرومانية", "🇷🇴"),
    ("hu", "Magyar", "المجرية", "🇭🇺"),
    ("cs", "Čeština", "التشيكية", "🇨🇿"),
    ("sk", "Slovenčina", "السلوفاكية", "🇸🇰"),
    ("bg", "Български", "البلغارية", "🇧🇬"),
    ("hr", "Hrvatski", "الكرواتية", "🇭🇷"),
    ("sr", "Српски", "الصربية", "🇷🇸"),
    ("sl", "Slovenščina", "السلوفينية", "🇸🇮"),
    ("et", "Eesti", "الإستونية", "🇪🇪"),
    ("lv", "Latviešu", "اللاتفية", "🇱🇻"),
    ("lt", "Lietuvių", "الليتوانية", "🇱🇹"),
    ("he", "עברית", "العبرية", "🇮🇱"),
    ("bn", "বাংলা", "البنغالية", "🇧🇩"),
    ("ta", "தமிழ்", "التاميلية", "🇮🇳"),
    ("te", "తెలుగు", "التيلوغوية", "🇮🇳"),
    ("ml", "മലയാളം", "المالايالامية", "🇮🇳"),
    ("sw", "Kiswahili", "السواحيلية", "🇰🇪"),
    ("tl", "Tagalog", "الفلبينية", "🇵🇭"),
    ("az", "Azərbaycan", "الأذربيجانية", "🇦🇿"),
    ("kk", "Қазақ", "الكازاخية", "🇰🇿"),
    ("uz", "Oʻzbek", "الأوزبكية", "🇺🇿"),
    ("ka", "ქართული", "الجورجية", "🇬🇪"),
    ("hy", "Հայերեն", "الأرمنية", "🇦🇲"),
    ("af", "Afrikaans", "الأفريقانية", "🇿🇦"),
    ("sq", "Shqip", "الألبانية", "🇦🇱"),
    ("am", "አማርኛ", "الأمهرية", "🇪🇹"),
    ("eu", "Euskara", "الباسكية", "🇪🇸"),
    ("be", "Беларуская", "البيلاروسية", "🇧🇾"),
    ("bs", "Bosanski", "البوسنية", "🇧🇦"),
    ("ca", "Català", "الكتالونية", "🇪🇸"),
    ("ceb", "Cebuano", "السيبوانية", "🇵🇭"),
    ("co", "Corsu", "الكورسيكية", "🇫🇷"),
    ("cy", "Cymraeg", "الويلزية", "🇬🇧"),
    ("eo", "Esperanto", "الإسبرانتو", "🌐"),
    ("fy", "Frysk", "الفريزية", "🇳🇱"),
    ("gl", "Galego", "الجاليكية", "🇪🇸"),
    ("gu", "ગુજરાતી", "الغوجاراتية", "🇮🇳"),
    ("ha", "Hausa", "الهوسا", "🇳🇬"),
    ("haw", "ʻŌlelo Hawaiʻi", "الهاوايية", "🇺🇸"),
    ("is", "Íslenska", "الأيسلندية", "🇮🇸"),
    ("ig", "Igbo", "الإيجبو", "🇳🇬"),
    ("ga", "Gaeilge", "الأيرلندية", "🇮🇪"),
    ("jv", "Basa Jawa", "الجاوية", "🇮🇩"),
    ("kn", "ಕನ್ನಡ", "الكانادا", "🇮🇳"),
    ("km", "ភាសាខ្មែរ", "الخميرية", "🇰🇭"),
    ("ku", "Kurdî", "الكردية", "🇮🇶"),
    ("ky", "Кыргызча", "القيرغيزية", "🇰🇬"),
    ("lo", "ພາສາລາວ", "اللاوية", "🇱🇦"),
    ("la", "Latina", "اللاتينية", "🇻🇦"),
    ("lb", "Lëtzebuergesch", "اللوكسمبورغية", "🇱🇺"),
    ("mk", "Македонски", "المقدونية", "🇲🇰"),
    ("mg", "Malagasy", "الملغاشية", "🇲🇬"),
    ("mt", "Malti", "المالطية", "🇲🇹"),
    ("mi", "Māori", "الماورية", "🇳🇿"),
    ("mr", "मराठी", "الماراثية", "🇮🇳"),
    ("mn", "Монгол", "المنغولية", "🇲🇳"),
    ("my", "မြန်မာ", "البورمية", "🇲🇲"),
    ("ne", "नेपाली", "النيبالية", "🇳🇵"),
    ("ps", "پښتو", "البشتو", "🇦🇫"),
    ("pa", "ਪੰਜਾਬੀ", "البنجابية", "🇮🇳"),
    ("sm", "Gagana Sāmoa", "الساموية", "🇼🇸"),
    ("gd", "Gàidhlig", "الغيلية الإسكتلندية", "🇬🇧"),
    ("sn", "chiShona", "الشونا", "🇿🇼"),
    ("sd", "سنڌي", "السندية", "🇵🇰"),
    ("si", "සිංහල", "السنهالية", "🇱🇰"),
    ("so", "Soomaali", "الصومالية", "🇸🇴"),
    ("su", "Basa Sunda", "السوندية", "🇮🇩"),
    ("tg", "Тоҷикӣ", "الطاجيكية", "🇹🇯"),
    ("tt", "Татар", "التتارية", "🇷🇺"),
    ("yo", "Yorùbá", "اليوروبا", "🇳🇬"),
    ("zu", "isiZulu", "الزولو", "🇿🇦"),
    ("xh", "isiXhosa", "الخوسية", "🇿🇦"),
    ("yi", "ייִדיש", "اليديشية", "🇮🇱")
]

# 4. بناء هيكل manifest.json و version.json لدعم الـ 100 لغة بالكامل
manifest = {"version": "4.0.0", "languages_count": len(languages_base), "languages": []}
version_index = {"latest_version": "4.0.0", "packs": {}}

for code, native_name, ar_name, flag in languages_base:
    pack_id = f"{code}_pack"
    file_name = f"{code}_master.pack.gz"
    cdn_url = f"https://cdn.jsdelivr.net/gh/moaz76943-creator/-offline-packs-store@main/packs/{file_name}"

    manifest["languages"].append({
        "code": code,
        "name": native_name,
        "name_ar": ar_name,
        "flag": flag,
        "pack_id": pack_id,
        "pack_url": cdn_url
    })

    version_index["packs"][pack_id] = {
        "version": "4.0.0",
        "file_url": cdn_url
    }

with open('manifest.json', 'w', encoding='utf-8') as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)

with open('version.json', 'w', encoding='utf-8') as f:
    json.dump(version_index, f, ensure_ascii=False, indent=2)

print(f"تم بنجاح إعداد المستودع العام لخدمة {len(languages_base)} لغة مع ملف الحماية .gitignore!")
