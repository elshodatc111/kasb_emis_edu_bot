# Serverga joylash (bepul, doimiy ishlaydigan)

Bu qo'llanma botni bepul, doimiy ishlaydigan bir VM (virtual server)ga, Docker yordamida,
avtomatik HTTPS bilan joylashtirish uchun. Kod tomonidan hech narsa qo'shimcha o'zgartirish
shart emas — loyiha allaqachon shunga tayyor (`Dockerfile`, `docker-compose.yml`, `Caddyfile`).

**Qaysi provayder?** Ikkalasi ham bepul, faqat 1-2-qadamlar farqlanadi (3-qadamdan boshlab bir xil):

- **B) Oracle Cloud (tavsiya qilinadi)** — kartadan haqiqiy pul yechilmaydi, faqat vaqtinchalik
  tekshiruv (3-5 kunda o'zi qaytadi). Ozgina ko'proq qadam talab qiladi.
- **A) Google Cloud** — ba'zi mamlakatlar/kartalarda ro'yxatdan o'tishda **$30 haqiqiy** (keyin
  qaytarib olsa bo'ladigan, lekin darhol emas) to'lov so'raydi. Agar sizga bu chiqmasa yoki
  boshqa (kredit) karta bilan chiqmasa, xohlasangiz shu yo'ldan davom etishingiz mumkin.

Umumiy vaqt: ~25-35 daqiqa, asosan kutish (VM yaratilishi, DNS tarqalishi).

## 0. Nima kerak bo'ladi

- Google yoki Oracle hisobi va bank kartasi (faqat tasdiqlash uchun).
- Ushbu GitHub repo: `https://github.com/elshodatc111/kasb_emis_edu_bot`
- `.env` fayilidagi maxfiy kalitlaringiz (BOT_TOKEN, OPENAI_API_KEY va h.k.) — **buni hech qachon
  chatga yoki skriptga yozmang, faqat serverning o'zida, to'g'ridan-to'g'ri kiritasiz.**

---

## 1B. Oracle Cloud'da VM yaratish (tavsiya qilinadi)

1. https://cloud.oracle.com/free ga kiring, **"Start for free"** bosing, ro'yxatdan o'ting
   (email, telefon, manzil, karta — faqat tekshiruv uchun, pul yechilmaydi).
2. Konsolga kirgach, chap yuqoridagi ☰ menyudan **Compute → Instances** ga o'ting, **Create instance** bosing.
3. Quyidagilarni sozlang:
   - **Name:** `texnikum-bot`
   - **Image and shape:** "Edit" bosing → **Image:** Canonical Ubuntu 24.04 → **Shape:** "Change shape"
     → **Ampere** → `VM.Standard.A1.Flex` tanlang, **1 OCPU / 6 GB RAM** qo'ying (yoki 2 OCPU/12 GB —
     ikkalasi ham "Always Free eligible" yozuvi bilan belgilangan bo'ladi, shuni tanlang).
   - **Networking:** standart (yangi VCN) qoldiring, **"Assign a public IPv4 address"** belgilangan bo'lsin.
   - **Add SSH keys:** "Generate a key pair for me" tanlang va **"Save private key"** tugmasi bilan
     `.key` faylni albatta kompyuteringizga saqlab oling (bu serverga kirish uchun yagona kalit —
     yo'qotsangiz qayta kira olmaysiz).
4. **Create** bosing, 1-2 daqiqada VM tayyor bo'ladi. Uning **Public IP** manzilini yozib oling.

### Statik IP va portlarni ochish (Oracle'ga xos, muhim)

Oracle'da ikkita joyda portni ochish kerak — GCP'dan farqli, shuni unutmang:

1. **IP'ni doimiy qilish:** instance sahifasida, "Attached VNIC" → VNIC ichiga kiring → IPv4 qatoridagi
   IP'ni bosing → **"Edit"** → ephemeral o'rniga **Reserved public IP** tanlang (yangi reserved IP yarating).
2. **Tarmoq (VCN) darajasida portlarni ochish:** instance sahifasidan "Virtual cloud network"ga o'ting →
   **Security Lists** (yoki Network Security Groups) → mavjud listni oching → **Add Ingress Rules**:
   - Source CIDR: `0.0.0.0/0`, IP Protocol: TCP, Destination Port: `80` — qo'shing
   - Yana bittasini qo'shing: Destination Port: `443`

Bu ikkalasini bajarmasangiz, server ishga tushsa ham sahifa tashqaridan ochilmaydi.

---

## 1A. Google Cloud'da VM yaratish (agar $30 talabi chiqmasa)

1. https://console.cloud.google.com ga kiring, kerak bo'lsa yangi loyiha yarating.
2. Chap menyudan **Compute Engine → VM instances** ga o'ting (birinchi marta yoqishni so'rasa, yoqing).
3. **Create instance** tugmasini bosing va quyidagilarni tanlang:
   - **Name:** `texnikum-bot`
   - **Region:** `us-central1` (yoki `us-west1` / `us-east1` — bepul tarif **faqat shu uchta hududda** ishlaydi)
   - **Machine type:** `e2-micro`
   - **Boot disk:** Ubuntu 24.04 LTS, 30 GB standart disk (o'zgartiring: "Change" → Ubuntu 24.04 LTS)
   - **Firewall:** "Allow HTTP traffic" va "Allow HTTPS traffic" katakchalarini belgilang
4. **Create** bosing, VM bir necha soniyada tayyor bo'ladi.
5. **VPC network → IP addresses** ga o'ting, yangi VM'ning IP'i qarshisida **"Promote to static address"**
   ni bosing — statik IP ishlab turgan VM'ga bog'liq bo'lsa bepul.

---

## 2. Bepul domen (DuckDNS)

1. https://www.duckdns.org ga kiring, Google hisobingiz bilan tizimga kiring.
2. "sub domain" maydoniga o'zingiz xohlagan nom yozing (masalan `texnikum-elshod`) va **add domain** bosing.
3. Hosil bo'lgan qatorda **"current ip"** maydoniga oldingi qadamda olgan statik/public IP manzilingizni
   yozing, **update ip** bosing.
4. Endi sizda `texnikum-elshod.duckdns.org` (yoki tanlagan nomingiz) domeni tayyor.

## 3. Serverga kirib, botni o'rnatish

**Google Cloud'da:** VM qatoridagi **SSH** tugmasini bosing — brauzerda terminal ochiladi, hech narsa
o'rnatish shart emas.

**Oracle Cloud'da:** kompyuteringizda terminal (Windows'da PowerShell) oching va 1B-qadamda saqlagan
kalit bilan ulaning:
```
chmod 600 ~/Downloads/ssh-key.key   (Windows PowerShell'da bu qatorni o'tkazib yuboring)
ssh -i ~/Downloads/ssh-key.key ubuntu@<PUBLIC_IP>
```

Ulangach, quyidagi buyruqni kiriting — bu butun sozlashni (Docker o'rnatish, kodni olish, swap
qo'shish, kerakli portlarni ochish) avtomatik bajaradi:

```bash
curl -fsSL https://raw.githubusercontent.com/elshodatc111/kasb_emis_edu_bot/main/deploy/bootstrap.sh | bash
```

Skript tugagach, `.env` faylini to'ldiring (**maxfiy kalitlarni faqat shu yerda kiriting**):

```bash
nano ~/kasb_emis_edu_bot/.env
```

Kamida quyidagilarni to'g'irlang:
- `BOT_TOKEN=` — @BotFather'dan olingan token
- `ADMIN_IDS=` — sizning Telegram ID'ingiz (masalan `123456789:Elshod Musurmonov`)
- `OPENAI_API_KEY=` va `OPENAI_VECTOR_STORE_ID=`
- `DOMAIN=texnikum-elshod.duckdns.org` (2-qadamda olgan domeningiz)
- `BASE_URL=https://texnikum-elshod.duckdns.org` (`http` emas, `https`!)
- `COOKIE_SECURE=1`

Saqlash: `Ctrl+O`, `Enter`, keyin `Ctrl+X`.

Botni ishga tushiring:

```bash
cd ~/kasb_emis_edu_bot && docker compose up -d --build
```

Birinchi marta rasm (image) yig'ilishi 1-2 daqiqa vaqt oladi. Caddy domeningiz uchun avtomatik
ravishda bepul HTTPS sertifikat oladi (bir necha soniya-daqiqa ichida, DNS allaqachon tarqalgan bo'lsa).

## 4. Tekshirish

- Brauzerda `https://texnikum-elshod.duckdns.org` ga kiring — kirish (login) sahifasi ochilishi kerak.
- Telegram'da botga `/start` yuboring — javob berishi kerak.
- Holatni jonli ko'rish: `docker compose logs -f` (chiqish: `Ctrl+C`, bot ishlashda davom etadi).

Agar sahifa ochilmasa: DNS tarqalishi ba'zan 5-10 daqiqa vaqt olishi mumkin — biroz kutib qayta
urinib ko'ring. Oracle'da bo'lsangiz, 1B-qadamdagi ikkita portni ochish bosqichini tekshiring.

## 5. Kundalik boshqaruv

| Vazifa | Buyruq |
|---|---|
| Loglarni ko'rish | `docker compose logs -f` |
| Botni to'xtatish | `docker compose down` |
| Botni qayta ishga tushirish | `docker compose restart` |
| Kod yangilanganda (GitHub'dan) | `git pull && docker compose up -d --build` |
| Ma'lumotlar bazasi zaxira nusxasi | `cp ~/kasb_emis_edu_bot/data/texnikum.db ~/texnikum-backup-$(date +%F).db` |

`data/` papkasi (ma'lumotlar bazasi) Docker konteynerdan tashqarida, serverning o'zida saqlanadi —
botni yangilash yoki qayta ishga tushirish ma'lumotlarni o'chirmaydi.

## 6. Xavfsizlik (eslatma)

- `.env` fayli hech qachon GitHub'ga yuklanmaydi (`.gitignore`da bor) — shunday qoldiring.
- `OPENAI_ADMIN_KEY` (agar ishlatsangiz) ham xuddi shunday — faqat serverdagi `.env`da.
- Serverga faqat SSH orqali kiring, `.env`ni va SSH kalit faylini hech kimga yubormang.

## Muammo yuzaga kelsa

- **Konteyner qayta-qayta o'chib-yonyapti:** `docker compose logs texnikum` — odatda `.env`da xato
  (masalan noto'g'ri `BOT_TOKEN`) bo'ladi.
- **HTTPS sertifikat olinmayapti:** `docker compose logs caddy` ni tekshiring; `DOMAIN` to'g'ri
  yozilganini va DNS statik IP'ga to'g'ri ishora qilayotganini tekshiring (`nslookup DOMAIN`).
- **Sahifa umuman ochilmayapti:**
  - Google Cloud: VM'ning firewall qoidalarida 80/443 portlari ochiqligini tekshiring.
  - Oracle Cloud: ham Security List (VCN darajasida), ham `bootstrap.sh` ochgan iptables qoidalarini
    tekshiring (`sudo iptables -L -n | grep -E '80|443'`).
- **Google Cloud'da $30 to'lov so'ralsa:** buni bosmang — boshqa (kredit) karta bilan urinib ko'ring
  yoki 1B-qadam bo'yicha Oracle Cloud'ga o'ting.
