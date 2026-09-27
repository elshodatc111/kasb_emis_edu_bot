#!/usr/bin/env bash
# Google Cloud (yoki boshqa Ubuntu) serverda bir martalik sozlash skripti.
# Ishlatish: DEPLOY.md ga qarang. Bu skript hech qanday maxfiy kalitni o'zida saqlamaydi —
# .env faylini siz alohida, qo'lda to'ldirasiz.
set -euo pipefail

REPO_URL="https://github.com/elshodatc111/kasb_emis_edu_bot.git"
APP_DIR="$HOME/kasb_emis_edu_bot"

echo "== 1/4: Docker o'rnatilmoqda (agar hali yo'q bo'lsa) =="
if ! command -v docker >/dev/null 2>&1; then
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker "$USER"
    echo "Docker o'rnatildi. E'tibor bering: guruh o'zgarishi kuchga kirishi uchun bu skriptdan keyin"
    echo "bir marta chiqib (exit) qayta SSH orqali kirishingiz kerak bo'lishi mumkin."
else
    echo "Docker allaqachon o'rnatilgan, o'tkazib yuborildi."
fi

echo "== 2/4: 1 GB almashinuv fayli (swap) qo'shilmoqda (e2-micro'da xotira tanqis, bu xavfsizlik uchun) =="
if [ ! -f /swapfile ]; then
    sudo fallocate -l 1G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab > /dev/null
    echo "Swap qo'shildi."
else
    echo "Swap fayli allaqachon mavjud, o'tkazib yuborildi."
fi

echo "== 3/4: Loyihaning kodi olinmoqda =="
if [ -d "$APP_DIR/.git" ]; then
    git -C "$APP_DIR" pull
else
    git clone "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"
mkdir -p data

if [ ! -f .env ]; then
    cp .env.example .env
    echo "== 4/4: .env fayli namunadan yaratildi =="
else
    echo "== 4/4: .env fayli allaqachon mavjud, o'zgartirilmadi =="
fi

cat <<'EOF'

Tayyor! Endi QOLGAN ikkita qadamni qo'lda bajaring (maxfiy kalitlarni hech qachon
skriptga yoki chatga yozmang, faqat shu yerda, to'g'ridan-to'g'ri serverda kiriting):

  1) .env faylini to'ldiring:
       nano ~/kasb_emis_edu_bot/.env
     Kamida shularni kiriting: BOT_TOKEN, ADMIN_IDS, OPENAI_API_KEY, OPENAI_VECTOR_STORE_ID,
     DOMAIN (masalan: texnikum-elshod.duckdns.org), BASE_URL=https://<DOMAIN>, COOKIE_SECURE=1
     Saqlash: Ctrl+O, Enter, keyin Ctrl+X.

  2) Botni ishga tushiring:
       cd ~/kasb_emis_edu_bot && docker compose up -d --build

  Holatni tekshirish:  docker compose logs -f
  To'xtatish:          docker compose down
  Yangilash (kod o'zgarganda): git pull && docker compose up -d --build

EOF
