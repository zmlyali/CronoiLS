# Cronoi LS — Proje Haritası

> **Tek referans dosya.** Tüm dosyaların ne olduğu, nerede durduğu ve ne zaman değiştirildiği burada.

---

## 📁 Dizin Yapısı

```
cronoi_project/
│
├── frontend/
│   └── Cronoi_LS_v2.html          ← ANA UYGULAMA — tek dosyada full UI
│                                     6 adım workflow, constraint picker,
│                                     3D palet/TIR görünüm, senaryo analizi
│                                     API modu + local fallback
│
├── backend/
│   ├── app/
│   │   ├── main.py                ← FastAPI app, router kayıtları, CORS
│   │   ├── models.py              ← SQLAlchemy ORM modelleri (tüm tablolar)
│   │   │
│   │   ├── core/
│   │   │   ├── config.py          ← Settings (pydantic-settings, .env okur)
│   │   │   ├── database.py        ← Async engine, get_db() dependency
│   │   │   └── auth.py            ← JWT, bcrypt, get_current_user()
│   │   │
│   │   ├── api/v1/
│   │   │   ├── shipments.py       ← CRUD + optimize endpoint + polling
│   │   │   └── constraints.py     ← Constraint havuzu CRUD + validate
│   │   │   (TODO: auth.py, scenarios.py, catalog.py, vehicles.py)
│   │   │
│   │   └── services/
│   │       ├── optimizer.py       ← BinPackingOptimizer3D + ScenarioOptimizer
│   │       └── constraint_engine.py ← ConstraintEngine, kural değerlendirme
│   │
│   ├── schema.sql                 ← Ana PostgreSQL şeması (tüm tablolar)
│   ├── constraint_schema.sql      ← Kısıt tabloları + seed data
│   ├── requirements.txt           ← Python bağımlılıkları
│   ├── Dockerfile                 ← Backend container
│   └── .env.example               ← Environment variables şablonu
│
├── docs/
│   ├── PRODUCT_FEATURES.md        ← Ürün özellikleri, roadmap, KPIs
│   └── SPRINT_1_PLAN.md           ← Sprint 1 görev planı
│
├── docker-compose.yml             ← PostgreSQL + Redis + API + Worker
└── README.md                      ← Bu dosya
```

---

## 🏗️ Mimari Özet

```
Browser (Cronoi_LS_v2.html)
    │
    ├─ API.ping()  →  bağlantı var mı?
    │
    ├─ [ONLINE]  →  FastAPI (port 8000)
    │                   │
    │               Celery Worker
    │                   │
    │               PostgreSQL  ←→  Redis
    │
    └─ [OFFLINE] →  Local JS (BinPackingOptimizer class)
                     Tüm özellikler offline da çalışır
```

---

## 🔑 Temel Dosyalar ve Sorumlulukları

| Dosya | Sorumluluk | Durum |
|---|---|---|
| `frontend/Cronoi_LS_v2.html` | Tüm UI, API layer, local fallback | ✅ Hazır |
| `backend/app/models.py` | DB şeması ORM olarak | ✅ Hazır |
| `backend/app/core/config.py` | Env variables | ✅ Hazır |
| `backend/app/core/database.py` | Async DB bağlantısı | ✅ Hazır |
| `backend/app/core/auth.py` | JWT + bcrypt | ✅ Hazır |
| `backend/app/main.py` | FastAPI app | ⚠️ Router bağlantıları eksik |
| `backend/app/api/v1/shipments.py` | Sevkiyat API | ⚠️ DB bağlantıları TODO |
| `backend/app/api/v1/constraints.py` | Kısıt havuzu API | ⚠️ DB bağlantıları TODO |
| `backend/app/services/optimizer.py` | Bin packing Python | ✅ Çalışır |
| `backend/app/services/constraint_engine.py` | Kısıt kuralları | ✅ Çalışır |
| `backend/schema.sql` | PostgreSQL DDL | ✅ Hazır |
| `backend/constraint_schema.sql` | Kısıt tabloları DDL | ✅ Hazır |
| `docker-compose.yml` | Tüm servisleri başlatır | ✅ Hazır |

**TODO (bir sonraki oturum):**
- `backend/app/api/v1/auth.py` — register/login endpoints
- `backend/app/api/v1/scenarios.py` — senaryo generate
- `shipments.py` ve `constraints.py`'deki TODO'ları gerçek DB koduyla doldur
- `main.py`'de tüm router'ları bağla

---

## 🚀 Çalıştırma

```bash
# 1. Env dosyasını hazırla
cd backend
cp .env.example .env
# .env içindeki SECRET_KEY'i değiştir

# 2. Docker Compose ile tümünü başlat
cd ..
docker-compose up -d

# 3. Veritabanını oluştur
docker-compose exec api python -c "
import asyncio
from app.core.database import init_db
asyncio.run(init_db())
"

# 4. API docs
open http://localhost:8000/api/docs

# 5. Frontend — doğrudan tarayıcıda aç
open frontend/Cronoi_LS_v2.html
```

---

## 📊 Dosya Değişiklik Geçmişi

| Tarih | Değişiklik | Dosyalar |
|---|---|---|
| 2026-03-23 | v1.1 HTML prototip (orjinal) | Cronoi_LS_v1_1_.html |
| 2026-03-23 | Mimari karar: FastAPI + PostgreSQL | schema.sql, docker-compose.yml |
| 2026-03-23 | Kısıt bilgi havuzu tasarımı | constraint_schema.sql, constraint_engine.py |
| 2026-03-23 | v2.0 UI: constraint picker + API layer | Cronoi_LS_v2.html |
| 2026-03-23 | Backend foundation: models + auth + db | models.py, core/ |
