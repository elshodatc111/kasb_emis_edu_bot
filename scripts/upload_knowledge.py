"""knowledge/ papkasidagi .txt qo'llanmalarni OpenAI vector store ga yuklaydi (yoki yangilaydi).

Ishlatish:
    python -m scripts.upload_knowledge            # OPENAI_VECTOR_STORE_ID dagi storega yuklaydi (bo'sh bo'lsa yangisini yaratadi)
Bir xil nomli fayl bo'lsa, eskisi o'chirilib, yangisi yuklanadi.
"""
from __future__ import annotations

import sys
from pathlib import Path

from openai import OpenAI

from app.config import ROOT, load_settings


def main() -> int:
    s = load_settings()
    if not s.openai_api_key:
        print("OPENAI_API_KEY ko'rsatilmagan (.env)")
        return 1
    client = OpenAI(api_key=s.openai_api_key)
    vs_id = s.vector_store_id
    if not vs_id:
        vs = client.vector_stores.create(name="texnikum-qollanma")
        vs_id = vs.id
        print(f"Yangi vector store yaratildi: {vs_id}\n.env fayliga OPENAI_VECTOR_STORE_ID={vs_id} deb yozing.")
    files = sorted((ROOT / "knowledge").glob("*.txt"))
    if not files:
        print("knowledge/ papkasida .txt fayl yo'q")
        return 1

    existing = {}
    for vf in client.vector_stores.files.list(vector_store_id=vs_id, limit=100):
        try:
            existing[client.files.retrieve(vf.id).filename] = vf.id
        except Exception:  # noqa: BLE001
            pass

    for path in files:
        if path.name in existing:
            print(f"O'chirilmoqda (eski nusxa): {path.name}")
            client.vector_stores.files.delete(existing[path.name], vector_store_id=vs_id)
        print(f"Yuklanmoqda: {path.name} ...", end=" ", flush=True)
        with open(path, "rb") as fh:
            vf = client.vector_stores.files.upload_and_poll(vector_store_id=vs_id, file=fh)
        print(vf.status)
    print("Tayyor.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
