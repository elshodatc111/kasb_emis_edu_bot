ROLES = [
    "O'qituvchi",
    "O'quv bo'limi",
    "Kadrlar bo'limi",
    "Buxgalter",
    "Kasbiy bo'lim",
    "Rahbariyat (Super admin)",
    "Boshqa",
]

TOPICS = [
    "Tizimga kirish va rollar",
    "Statistika",
    "Xodimlar",
    "Hujjatlar va buyruqlar",
    "Juftliklar (para)",
    "Infrastruktura (bino, xona)",
    "Fanlar",
    "Mutaxassisliklar",
    "O'quv rejalar",
    "Guruhlar",
    "O'quvchilar",
    "Dars jadvali",
    "Elektron jurnal",
    "Darslarni almashtirish",
    "O'quv resurslari",
    "Taqvim-mavzu reja",
    "Topshiriqlar",
    "O'zlashtirish",
    "Monitoring",
    "Tarifikatsiya",
    "Kontingent",
    "Diplomlar",
    "Sertifikat (qisqa muddatli)",
    "Texnik xatolik",
    "Boshqa",
]

ROLE_STATUS_UZ = {
    "pending": "Kutilmoqda",
    "approved": "Ruxsat berilgan",
    "rejected": "Rad etilgan",
    "blocked": "Bloklangan",
}

# Viktorina savollari qaysi qo'llanmadan olinadi
ROLE_GUIDES = {
    "O'qituvchi": "O'qituvchi qo'llanmasi (elektron jurnal, dars jadvali, topshiriqlar, o'quv resurslari, taqvim-mavzu reja)",
    "O'quv bo'limi": "O'quv bo'limi qo'llanmasi (o'quvchilar, guruhlar, o'quv rejalar, dars jadvali, juftliklar, diplomlar)",
    "Kadrlar bo'limi": "Kadrlar bo'limi qo'llanmasi (xodimlar, buyruqlar, tarifikatsiya)",
    "Buxgalter": "Buxgalter qo'llanmasi",
    "Kasbiy bo'lim": "Kasbiy bo'lim qo'llanmasi (monitoring, statistika, kontingent)",
    "Rahbariyat (Super admin)": "Super admin qo'llanmasi (rollar, sozlamalar, texnikum ma'lumotlari, umumiy boshqaruv)",
    "Boshqa": "barcha qo'llanmalardan platformadan foydalanishning umumiy asoslari (tizimga kirish, rollar, asosiy bo'limlar)",
}

# Telegram tugmalarida ko'rsatiladigan rol belgilari (bazaga faqat rol nomi yoziladi)
ROLE_ICONS = {
    "O'qituvchi": "👩‍🏫",
    "O'quv bo'limi": "🎓",
    "Kadrlar bo'limi": "👥",
    "Buxgalter": "💰",
    "Kasbiy bo'lim": "🛠",
    "Rahbariyat (Super admin)": "🏛",
    "Boshqa": "👤",
}
