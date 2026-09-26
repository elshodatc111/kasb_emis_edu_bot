from app.privacy import mask_sensitive


def test_pinfl_masked():
    text, n = mask_sensitive("PINFL: 51805055530014 bo'yicha topilmadi")
    assert "51805055530014" not in text and "[PINFL]" in text and n == 1


def test_pinfl_with_separators():
    text, n = mask_sensitive("5180 5055 5300 14 va 51805-05553-0014")
    assert "[PINFL]" in text and n == 2 and not any(ch.isdigit() for ch in text)


def test_passport_masked():
    for raw in ("AE2744857", "AE 2744857", "ae-2744857", "АА1234567"):
        text, n = mask_sensitive(f"pasport {raw} xato")
        assert n == 1 and "[PASPORT]" in text, raw


def test_id_card_needs_hint():
    text, n = mask_sensitive("Passport raqami: 123456789")
    assert n == 1 and "123456789" not in text
    text2, n2 = mask_sensitive("Xonada 123456789 ta stul")
    assert n2 == 0


def test_no_false_positives():
    for s in ("Telefon +998901234567", "Sana 01.09.2026 12:30", "10-25 (Asosiy bino)", "KT-IV 0000001 diplom",
              "1 semestr 30 kredit 3600 soat", "2026-09-26"):
        assert mask_sensitive(s) == (s, 0), s


def test_empty():
    assert mask_sensitive(None) == ("", 0)
    assert mask_sensitive("") == ("", 0)
