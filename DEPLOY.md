# Serverga joylash (Google Cloud, bepul, doimiy ishlaydigan)

Bu qo'llanma botni Google Cloud'ning **doimiy bepul (Always Free) e2-micro** serveriga, Docker
yordamida, avtomatik HTTPS bilan joylashtirish uchun. Kod tomonidan hech narsa qo'shimcha
o'zgartirish shart emas — loyiha allaqachon shunga tayyor (`Dockerfile`, `docker-compose.yml`, `Caddyfile`).

Umumiy vaqt: ~20-30 daqiqa, asosan kutish (VM yaratilishi, DNS tarqalishi).

## 0. Nima kerak bo'ladi

- Google hisobi (Gmail) va bank kartasi (faqat tasdiqlash uchun — bepul chegarada qolsangiz pul yechilmaydi).
- Ushbu GitHub repo: `https://github.com/elshodatc111/kasb_emis_edu_bot`
- `.env` fayilidagi maxfiy kalitlaringiz (BOT_TOKEN, OPENAI_API_KEY va h.k.) — **buni hech qachon
  chatga yoki skriptga yozmang, faqat serverning o'zida, to'g'ridan-to'g'ri kiritasiz.**

## 1. Google Cloud'da VM yaratish

1. https://console.cloud.google.com ga kiring, kerak bo'lsa yangi loyiha yarating.
2. Chap menyudan **Compute Engine → VM instances** ga o'ting (birinchi marta yoqishni so'rasa, yoqing).
3. **Create instance** tugmasini bosing va quyidagilarni tanlang:
   - **Name:** `texnikum-bot`
   - **Region:** `us-central1` (yoki `us-west1` / `us-east1` — bepul tarif **faqat shu uchta hududda** ishlaydi)
   - **Machine type:** `e2-micro`
   - **Boot disk:** Ubuntu 24.04 LTS, 30 GB standart disk (o'zgartiring: "Change" → Ubuntu 24.04 LTS)
   - **Firewall:** "Allow HTTP traffic" va "Allow HTTPS traffic" katakchalarini belgilang
4. **Create** bosing, VM bir necha soniyada tayyor bo'ladi.

## 2. Statik IP manzil biriktirish

IP manzil o'zgarib turmasligi uchun (aks holda domen har safar yangilanishi kerak bo'ladi):

1. **VPC network → IP addresses** ga o'ting.
2. Yangi yaratilgan VM'ning IP'i qarshisida **"Promote to static address"** ni bosing (yoki
   "Reserve external static IP address" orqali qo'lda yarating va shu VM'ga bog'lang).
3. Statik IP manzilni nusxalab oling — keyingi qadamda kerak bo'ladi.

Statik IP ishlab turgan VM'ga bog'liq bo'lsa — **bepul**. (Faqat VM'ni o'chirib, IP'ni "bo'sh"
holatda qoldirsangiz pullik bo'lib qoladi — shuning uchun VM'ni doim ishlab turgan holda qoldiring.)

## 3. Bepul domen (DuckDNS)

1. https://www.duckdns.org ga kiring, Google hisobingiz bilan tizimga kiring.
2. "sub domain" maydoniga o'zingiz xohlagan nom yozing (masalan `texnikum-elshod`) va **add domain** bosing.
3. Hosil bo'lgan qatorda **"current ip"** maydoniga 2-qadamdagi statik IP manzilingizni yozing, **update ip** bosing.
4. Endi sizda `texnikum-elshod.duckdns.org` (yoki tanlagan nomingiz) domeni tayyor — u statik IP'ga ishora qiladi.

## 4. Serverga kirib, botni o'rnatish

1. Google Cloud konsolida VM qatoridagi **SSH** tugmasini bosing — brauzerda terminal ochiladi
   (hech narsa o'rnatish shart emas).
2. Quyidagi buyruqni kiriting — bu butun sozlashni (Docker o'rnatish, kodni olish, swap qo'shish) avtomatik bajaradi:

   ```bash
   curl -fsSL https://raw.githubusercontent.com/elshodatc111/kasb_emis_edu_bot/main/deploy/bootstrap.sh | bash
   ```

3. Skript tugagach, `.env` faylini to'ldiring (**maxfiy kalitlarni faqat shu yerda kiriting**):

   ```bash
   nano ~/kasb_emis_edu_bot/.env
   ```

   Kamida quyidagilarni to'g'irlang:
   - `BOT_TOKEN=` — @BotFather'dan olingan token
   - `ADMIN_IDS=` — sizning Telegram ID'ingiz (masalan `123456789:Elshod Musurmonov`)
   - `OPENAI_API_KEY=` va `OPENAI_VECTOR_STORE_ID=`
   - `DOMAIN=texnikum-elshod.duckdns.org` (3-qadamda olgan domeningiz)
   - `BASE_URL=https://texnikum-elshod.duckdns.org` (`http` emas, `https`!)
   - `COOKIE_SECURE=1`

   Saqlash: `Ctrl+O`, `Enter`, keyin `Ctrl+X`.

4. Botni ishga tushiring:

   ```bash
   cd ~/kasb_emis_edu_bot && docker compose up -d --build
   ```

   Birinchi marta rasm (image) yig'ilishi 1-2 daqiqa vaqt oladi. Caddy domeningiz uchun avtomatik
   ravishda bepul HTTPS sertifikat oladi (bir necha soniya-daqiqa ichida, DNS allaqachon tarqalgan bo'lsa).

## 5. Tekshirish

- Brauzerda `https://texnikum-elshod.duckdns.org` ga kiring — kirish (login) sahifasi ochilishi kerak.
- Telegram'da botga `/start` yuboring — javob berishi kerak.
- Holatni jonli ko'rish: `docker compose logs -f` (chiqish: `Ctrl+C`, bot ishlashda davom etadi).

Agar sahifa ochilmasa: DNS tarqalishi ba'zan 5-10 daqiqa vaqt olishi mumkin — biroz kutib qayta urinib ko'ring.

## 6. Kundalik boshqaruv

| Vazifa | Buyruq |
|---|---|
| Loglarni ko'rish | `docker compose logs -f` |
| Botni to'xtatish | `docker compose down` |
| Botni qayta ishga tushirish | `docker compose restart` |
| Kod yangilanganda (GitHub'dan) | `git pull && docker compose up -d --build` |
| Ma'lumotlar bazasi zaxira nusxasi | `cp ~/kasb_emis_edu_bot/data/texnikum.db ~/texnikum-backup-$(date +%F).db` |

`data/` papkasi (ma'lumotlar bazasi) Docker konteynerdan tashqarida, serverning o'zida saqlanadi —
botni yangilash yoki qayta ishga tushirish ma'lumotlarni o'chirmaydi.

## 7. Xavfsizlik (eslatma)

- `.env` fayli hech qachon GitHub'ga yuklanmaydi (`.gitignore`da bor) — shunday qoldiring.
- `OPENAI_ADMIN_KEY` (agar ishlatsangiz) ham xuddi shunday — faqat serverdagi `.env`da.
- Serverga faqat SSH orqali (Google Cloud konsoli yoki o'z terminalingizdan) kiring, `.env`ni hech kimga yubormang.

## Muammo yuzaga kelsa

- **Konteyner qayta-qayta o'chib-yonyapti:** `docker compose logs texnikum` — odatda `.env`da xato
  (masalan noto'g'ri `BOT_TOKEN`) bo'ladi.
- **HTTPS sertifikat olinmayapti:** `docker compose logs caddy` ni tekshiring; `DOMAIN` to'g'ri
  yozilganini va DNS statik IP'ga to'g'ri ishora qilayotganini tekshiring (`nslookup DOMAIN`).
- **Sahifa umuman ochilmayapti:** Google Cloud konsolida VM'ning firewall qoidalarida 80/443 portlari
  ochiqligini tekshiring (1-qadamdagi katakchalar).
