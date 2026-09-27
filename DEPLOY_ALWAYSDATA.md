# Serverga joylash — alwaysdata.com (vaqtinchalik, bepul)

Bu qo'llanma botni sizda allaqachon bor **alwaysdata.com Free** hisobiga joylashtirish uchun.
Bu Docker ishlatmaydi (alwaysdata'da bunga ruxsat yo'q) — kod to'g'ridan-to'g'ri Python
muhitida (`venv`) SSH orqali ishga tushiriladi.

**Muhim eslatma:** alwaysdata Free tarifi juda kichik resurs beradi (256 MB RAM, ¼ CPU, 1 GB disk).
Shuning uchun buni **vaqtinchalik/sinov** joylashtirish sifatida ko'ring — agar botga foydalanuvchilar
ko'payib, xotira yetishmay qolsa yoki jarayon vaqti-vaqti bilan qayta ishga tushib tursa, avvalroq
tayyorlagan **Oracle Cloud** (`DEPLOY.md`) yo'liga o'tish tavsiya etiladi — u bepul va bir necha
o'n baravar kuchliroq (6+ GB RAM, to'liq server).

Umumiy vaqt: ~15-20 daqiqa.

## 0. Nima kerak bo'ladi

- alwaysdata kabinetingiz (https://admin.alwaysdata.com) — sizda allaqachon bor.
- Ushbu GitHub repo: `https://github.com/elshodatc111/kasb_emis_edu_bot`
- `.env` fayilidagi maxfiy kalitlaringiz (BOT_TOKEN, OPENAI_API_KEY va h.k.)

## 1. SSH'ni yoqish

1. https://admin.alwaysdata.com ga kiring.
2. Chap menyudan **Advanced → Remote access (SSH)** ga o'ting.
3. SSH foydalanuvchi bo'lmasa, yarating (parol qo'ying, eslab qoling).
4. Sahifada ko'rsatilgan ulanish buyrug'ini nusxalab oling, masalan:
   ```
   ssh <account>@ssh-<account>.alwaysdata.net
   ```

## 2. Kodni serverga olish va sozlash

SSH orqali ulaning (yuqoridagi buyruq bilan, parolingizni kiritasiz), so'ng ketma-ket bajaring:

```bash
git clone https://github.com/elshodatc111/kasb_emis_edu_bot.git
cd kasb_emis_edu_bot
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
mkdir -p data
cp .env.example .env
```

## 3. `.env` faylini to'ldirish

```bash
nano .env
```

Kamida quyidagilarni to'g'irlang (`admin.alwaysdata.com` bosh sahifasida hisobingiz nomi —
masalan `codestartuz` — va standart domeningiz `codestartuz.alwaysdata.net` ko'rinishida bo'ladi,
uni **Web → Sites** bo'limidan ham ko'rishingiz mumkin):

- `BOT_TOKEN=` — @BotFather'dan olingan token
- `ADMIN_IDS=` — sizning Telegram ID'ingiz (masalan `123456789:Elshod Musurmonov`)
- `OPENAI_API_KEY=` va `OPENAI_VECTOR_STORE_ID=`
- `BASE_URL=https://codestartuz.alwaysdata.net` (o'zingizning hisob nomingiz bilan, `http` emas `https`!)
- `COOKIE_SECURE=1`
- `WEB_HOST=` va `WEB_PORT=` qatorlarini o'zgartirishning hojati yo'q — alwaysdata o'zining
  IP/PORT qiymatlarini avtomatik beradi va kod ularni ustun qo'yadi (bu allaqachon moslangan).

Saqlash: `Ctrl+O`, `Enter`, keyin `Ctrl+X`.

## 4. "Site" (dastur) yaratish

1. https://admin.alwaysdata.com da chap menyudan **Web → Sites** ga o'ting, **Add a site** bosing.
2. Quyidagilarni tanlang/kiriting:
   - **Type:** `User program`
   - **Command:**
     ```
     /home/<account>/kasb_emis_edu_bot/venv/bin/python -m app.main
     ```
     (`<account>` o'rniga o'z hisob nomingizni yozing — buyruqning to'liq yo'lini bilish uchun
     SSH'da `pwd` va `which python` buyruqlarini ishlatishingiz mumkin.)
   - **Working directory:** `/home/<account>/kasb_emis_edu_bot`
3. **Save/Add** bosing. Pastda avtomatik yaratilgan domen — `<account>.alwaysdata.net` — ko'rinadi
   (agar kerak bo'lsa shu yerda "Domains" qismida tekshiring/qo'shing).

Bu dastur endi doimiy ishlab turadi: ichida bot ham (Telegram bilan), veb-panel ham, kunlik
test/hisobot rejalari (APScheduler) ham — barchasi bitta jarayonda, xuddi kompyuteringizda
ishlaganidek.

## 5. Tekshirish

- Brauzerda `https://<account>.alwaysdata.net` ga kiring — kirish (login) sahifasi ochilishi kerak.
- Telegram'da botga `/start` yuboring — javob berishi kerak.
- Loglarni ko'rish: admin panelida **Web → Sites** → saytingiz → **Logs**, yoki SSH orqali:
  ```bash
  tail -f ~/admin/logs/sites/*<account>*
  ```

## 6. Kodni yangilash (keyinchalik)

```bash
ssh <account>@ssh-<account>.alwaysdata.net
cd kasb_emis_edu_bot
git pull
source venv/bin/activate
pip install -r requirements.txt
```

So'ng admin panelida **Web → Sites** → saytingiz qatorida **Restart** tugmasini bosing
(yangi kod ishga tushishi uchun jarayonni qayta ishga tushirish kerak).

## Muammo yuzaga kelsa

- **Sahifa ochilmayapti / 502 xato:** Loglarni tekshiring (5-qadam). Ko'pincha `.env`da xato
  (noto'g'ri `BOT_TOKEN` yoki `OPENAI_API_KEY`) yoki `Command`dagi yo'l noto'g'ri yozilgan bo'ladi.
- **"ModuleNotFoundError":** `venv/bin/python` to'g'ri yo'lda ekanini tekshiring (`Command`
  maydonida to'liq, mutlaq yo'l bo'lishi shart — nisbiy yo'l ishlamaydi).
- **Xotira yetmayapti (jarayon kutilmaganda o'chib qolsa):** Free tarifda atigi 256 MB RAM bor —
  agar bu doimiy muammoga aylansa, Oracle Cloud'ga o'tish vaqti keldi (`DEPLOY.md`ga qarang) —
  u yerda ma'lumotlar bazangizni (`data/texnikum.db` faylini) shunchaki ko'chirib olib, davom
  ettirsa bo'ladi.
- **Ma'lumotlar bazasi zaxira nusxasi:**
  ```bash
  cp ~/kasb_emis_edu_bot/data/texnikum.db ~/texnikum-backup-$(date +%F).db
  ```
