# Texnikum yordamchi (Telegram bot + admin veb-panel)

Prof ta'lim (kasb-emis) platformasi bo'yicha texnikum xodimlarining savollariga qo'llanmalar asosida javob beruvchi
Telegram bot va uni boshqaruvchi veb-panel. Bitta Python dasturi ikkalasini ham ishga tushiradi.

**Asosiy imkoniyatlar**

- Xodim birinchi marta /start bosganda F.I.SH., telefon, texnikum va rolini kiritadi. So'rov adminga tushadi (Telegram tugmalari yoki veb-panel orqali "Ruxsat / Rad").
- Ruxsat olgan xodim savol yozadi, agent (OpenAI + qo'llanmalar) qisqa va aniq javob beradi. Javob topilmasa savol adminga uzatiladi.
- Xodim rasm yuborishi mumkin. Rasm **OpenAI ga yuborilmaydi**, **bot javob bermaydi**, rasm **diskka saqlanmaydi** (faqat Telegram `file_id` saqlanadi), admin uni panelda ko'radi va sizga Telegram xabari boradi.
- Audio, video va fayllar qabul qilinmaydi.
- Matndagi PINFL va pasport raqamlari OpenAI ga yuborilishidan oldin `[PINFL]`, `[PASPORT]` deb yashiriladi (panelda asl matn ko'rinadi).
- Veb-panel: Telegram ID orqali kirish (kod botga keladi), so'rovlar, foydalanuvchilar, jonli suhbatlar, suhbatga qo'shilish (matn, skrinshot, video), kunlik/haftalik/oylik hisobotlar, video rolik rejalari.

## 1. O'rnatish (Windows)

1. Python o'rnatilgan bo'lsin (3.14 yoki 3.12+). `python --version` bilan tekshiring.
2. Zip ni oching (masalan `C:\Texnikum\texnikum-bot`).
3. `setup.bat` ni ikki marta bosing. U virtual muhit yaratadi, kutubxonalarni o'rnatadi va `.env` faylini yaratadi.
   Agar Python 3.14 da o'rnatish xato bersa, Python 3.13 o'rnatib qayta urinib ko'ring.
4. `.env` faylini oching va to'ldiring:

| Kalit | Qayerdan olinadi |
|---|---|
| `BOT_TOKEN` | Telegramda @BotFather: `/newbot`, so'ng berilgan token |
| `ADMIN_IDS` | Telegram ID va ism: `123456789:Elshod Karimov`. Bir nechta bo'lsa vergul bilan. Ism foydalanuvchiga "Admin: Ism" deb ko'rinadi (ID ni @userinfobot dan oling) |
| `OPENAI_API_KEY` | platform.openai.com: API Keys: Create new secret key (loyiha uchun alohida kalit) |
| `OPENAI_VECTOR_STORE_ID` | Storage: Vector stores dagi `vs_...` (tayyor qiymat `.env.example` da) |

5. Telegramda botingizni oching va **/start** bosing (har bir admin buni bir marta qilishi shart, aks holda bot sizga kod yubora olmaydi).
6. `check.bat` ni ishga tushiring: Telegram, OpenAI kaliti, vector store va sinov savoli tekshiriladi.
7. `run.bat` bilan ishga tushiring. Panel: http://127.0.0.1:8000

## 2. Panelga kirish

Manzilga kiring, Telegram ID ingizni yozing. Bot Telegramga 6 xonali kod yuboradi, uni kiriting. Kod 5 daqiqa amal qiladi, seans 12 soat.

## 3. Kundalik ishlash

- **So'rovlar**: yangi xodimlar. "Ruxsat berish" bosilsa xodimga Telegramda xabar boradi.
- **Suhbatlar**: chap ro'yxatda "diqqat talab" (javobsiz savol, rasm, adminga murojaat) belgilari. Suhbatni ochib javob yozasiz. Javob yozganingizda suhbat "admin rejimi"ga o'tadi va bot shu xodimga javob bermay turadi. "Botga qaytarish" tugmasi yoki 60 daqiqa o'tishi (`ADMIN_MODE_TIMEOUT_MIN`) botni qaytaradi.
- **AI taklif**: admin javob yozishda qo'llanmadan tayyorlangan javob loyihasini oladi.
- **Hisobotlar**: kunlik 20:00, haftalik yakshanba 20:30, oylik 1-sana 09:00 (Toshkent vaqti) avtomatik yaratiladi va Telegramga qisqa xabar keladi. Istalgan vaqtda qo'lda ham yaratish mumkin.
- **Video rejalar**: takrorlanayotgan savollardan video rolik uchun sarlavha, ssenariy, qadamlar, skrinshotlar ro'yxati, ovozli matn va tekshiruv savollari tayyorlanadi (`.md` fayl sifatida yuklab olinadi). Har yakshanba avtomatik.

## 3a. Yangi imkoniyatlar

- **Bilimlar bazasi** (panel: "Bilimlar bazasi"). Bot javob bera olmagan savolga siz suhbatda javob yozasiz, xabar ostidagi "Bilimlar bazasiga qo'shish" havolasini bosasiz. Shu savol-javob darhol botga ta'sir qiladi (lokal qidiruv), 5 daqiqada OpenAI vector store'ga ham yuklanadi. Qo'lda yozuv qo'shish, tahrirlash, o'chirib qo'yish mumkin.
- **Ko'p so'raladigan savollar (FAQ)**. Har kuni 21:30 da AI so'nggi 30 kundagi savollarni tahlil qilib, "Kutilmoqda" ro'yxatiga yangi variantlar qo'yadi. Siz tasdiqlaysiz yoki tahrirlaysiz, keyin botdagi "Ko'p so'raladigan savollar" tugmasida chiqadi. "Hozir tahlil qilish" tugmasi bor.
- **Video kutubxona**. Videoni YouTube (yopiq havola) ga joylab, panelga sarlavha, havola va kalit so'zlarni kiriting. Bot mos savolga javob berganda videoni o'zi taklif qiladi, "Video darslar" tugmasida ham ko'rinadi. Video fayllar sizning kompyuteringizda ham, serverda ham saqlanmaydi.
- **Kunlik test**. Har kuni 12:20-13:00 oralig'ida (2 daqiqada bir guruhga, bir tekis) har bir tasdiqlangan xodimga roli bo'yicha 5 ta savol keladi, 3 variantli. To'g'ri bo'lsa "Siz to'g'ri javob berdingiz", noto'g'ri bo'lsa to'g'ri javob ko'rsatiladi. Savollar AI tomonidan qo'llanmadan tuziladi va bir xodimga takrorlanmaydi. Natijalar panelda ("Kunlik test"). Xodim "Kunlik test" tugmasi bilan ham boshlashi mumkin.
- **Javobsiz suhbat eslatmasi**. Admin javob yozmagan suhbatlar haqida 08:00-22:00 oralig'ida har 10 daqiqada adminlarga bitta yig'ma xabar boradi. Javob yozilishi bilan to'xtaydi.
- **Ish vaqti xabari**. Bot savolni adminga yo'naltirganda foydalanuvchiga yumshoq xabar beradi. Ish kunlari 09:00-19:00 da "admin tez orada javob beradi", boshqa vaqtda "admin darhol javob bera olmasligi mumkin" deb ogohlantiradi. Adminga xabar har doim darhol boradi.
- **Javob shablonlari**. Suhbat oynasida shablon tanlansa, matn xabar maydoniga tushadi. `{ism}` xodim ismiga almashadi.
- **Foydalanuvchi ma'lumotini tahrirlash**. "Foydalanuvchilar" ro'yxatida "Tahrirlash" tugmasi: F.I.SH., telefon, texnikum, rol va holat.
- **Rol cheklovi yo'q**: xodim boshqa lavozimdagi hamkasbi uchun ham savol berib, javob olishi mumkin.
- Barcha vaqtlar va kunlar `.env` dan o'zgartiriladi (`WORK_*`, `REMIND_*`, `QUIZ_*`, `FAQ_TIME`).

## 4. Qo'llanmalarni yangilash / video matnlarini qo'shish

`knowledge/` papkasiga yangi `.txt` fayl qo'shing (masalan Zoom video transkripti) yoki mavjudini almashtiring, keyin:

```
.venv\Scripts\activate
python -m scripts.upload_knowledge
```

Bir xil nomli fayl eskisini almashtiradi. Agent keyingi savoldan boshlab yangi ma'lumotdan foydalanadi.

## 5. Maxfiylik va xavfsizlik

- Rasmlar: bot faqat Telegram `file_id` ni saqlaydi. Panel rasmni ko'rsatishda Telegramdan xotiraga yuklab, brauzerga uzatadi (`Cache-Control: no-store`), diskka yozmaydi. Admin yuborgan rasm/video ham xotira orqali Telegramga uzatiladi (katta fayl yuklashda tizim vaqtincha fayl yaratishi va so'rov tugagach o'chirishi mumkin). Telegram serverlari fayllarni o'zida saqlashini unutmang.
- PINFL va pasport faqat **matn** xabarlarida yashiriladi. F.I.SH. yashirilmaydi. Xodimlarga savolda o'quvchi ma'lumotini yozmaslikni tushuntiring.
- OpenAI ga faqat matn boradi (`store=false`: javoblar OpenAI tomonida saqlanmaydi). API ma'lumotlari sukut bo'yicha model o'qitishga ishlatilmaydi.
- Suhbat tarixi `data/texnikum.db` (SQLite) faylida saqlanadi. Uni himoyalang va zaxira nusxa oling.
- Panel sukut bo'yicha faqat shu kompyuterdan ochiladi (127.0.0.1). Serverga joylashda HTTPS ishlating va `.env` da `COOKIE_SECURE=1`, `BASE_URL` ni o'zgartiring.
- O'zbekistonda shaxsiy ma'lumotlarni saqlash joyi bo'yicha qonun talablari bor. Serverga o'tishdan oldin yurist bilan maslahatlashing.

## 6. Muammolar

| Belgi | Sabab va yechim |
|---|---|
| "Kodni yuborib bo'lmadi" | Botga Telegramdan /start yuboring va `ADMIN_IDS` da ID to'g'riligini tekshiring |
| Bot javob bermayapti | `check.bat` ni ishga tushiring; OpenAI balansi va kalitni tekshiring |
| Har savolga "adminga yuborildi" | Vector store bo'sh yoki `OPENAI_VECTOR_STORE_ID` noto'g'ri; `check.bat` ko'rsatadi |
| Panelda rasm chiqmayapti | Fayl eskirgan yoki 20 MB dan katta (Telegram chegarasi) |
| `pip install` xato (Python 3.14) | Python 3.13 bilan `.venv` ni qayta yarating |

## 7. Testlar

```
.venv\Scripts\activate
pip install -r requirements-dev.txt
python -m pytest
```

Testlar Telegram va OpenAI ga ulanmaydi (soxta obyektlar bilan ishlaydi).

## 8. Tuzilma

```
app/main.py         ishga tushirish (bot + panel + rejalashtiruvchi)
app/agent.py        yagona AI agent (javob, hisobot xulosasi, video reja, javob taklifi)
app/bot/            Telegram bot (aiogram 3)
app/web/            admin panel (FastAPI + HTMX + WebSocket)
app/db.py           SQLite bazasi
app/privacy.py      PINFL/pasport yashirish
app/reports.py      hisobotlar va video rejalar
knowledge/          qo'llanmalarning matn nusxalari
scripts/            check_setup.py, upload_knowledge.py
```

## 9. Serverga joylash (keyinroq)

`Dockerfile` va `docker-compose.yml` tayyor: `docker compose up -d --build`. Oldiga HTTPS beruvchi Caddy yoki Nginx qo'ying.
Bitta jarayon ishlaydi, bot polling rejimida, shuning uchun bir vaqtda faqat bitta nusxa ishga tushiring.
