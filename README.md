# Clinical Data Ingestion API

A production-grade REST API for ingesting, versioning, and querying clinical pathology sample records. Built with FastAPI and PostgreSQL, designed for deployment in healthcare data pipelines.

---

## Overview

Clinical pathology labs generate large Excel/CSV datasets of sample records that are updated and re-uploaded regularly. This API handles the full ingestion lifecycle:

- Accepts `.xlsx`, `.xls`, and `.csv` uploads (auto-detects semicolon vs comma delimiter, handles UTF-8 BOM)
- Validates every row with Pydantic before any database writes
- Deduplicates by sample ID — detecting new records, unchanged records, and changed records
- Versions changed records rather than overwriting — full audit history preserved
- Reports exactly which fields changed on versioned rows in the upload response
- Logs every upload attempt to an audit table with row counts and timing

---

## Architecture

```
POST /upload_data
        │
        ├── File validation (extension, size)
        ├── Async parsing via run_in_executor (pandas — non-blocking)
        ├── Schema validation (required columns present)
        ├── Row-level Pydantic validation (all rows classified before any DB writes)
        │
        ├── Bronze layer: raw file reference saved to raw_files
        ├── Audit entry created in ingestion_log
        │
        ├── Batch deduplication query (one DB query for entire file)
        │       ├── New ID        → insert version 1
        │       ├── Unchanged     → update last_modified only
        │       └── Changed data  → retire old row, insert new version, record diff
        │
        ├── Bulk insert in single transaction
        └── Return summary with counts + field-level diffs for versioned rows
```

### Database — 4 tables (Medallion Architecture)

```
raw_files        Bronze layer — one row per uploaded file
ingestion_log    Audit log — one row per upload attempt
samples          Silver layer — versioned clinical records
rejected_rows    Rows that failed Pydantic validation
```

The `samples` table uses a `version` + `is_latest` versioning strategy. Sparse text groups (clinical info, macroscopic/microscopic descriptions, diagnoses, locations) are stored as compact JSONB — only non-empty values stored. Primary diagnosis and ICD codes are kept as flat columns for direct filtering.

---

## Tech Stack

| Component | Technology |
|---|---|
| Framework | FastAPI (async) |
| Database | PostgreSQL 17 |
| ORM | SQLAlchemy 2.0 async |
| DB driver | asyncpg |
| Migrations | Alembic |
| Validation | Pydantic v2 |
| File parsing | pandas + openpyxl |
| Settings | pydantic-settings |

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/upload/upload_data` | Upload Excel or CSV file |
| `GET` | `/samples` | List all current records (paginated) |
| `GET` | `/samples/{id}` | Get current record by ID |
| `GET` | `/samples/{id}/history` | All versions of a record |
| `GET` | `/samples/{id}/diff` | Field-level diff between versions |
| `GET` | `/samples/search/fulltext?q=` | Full-text search via PostgreSQL tsvector |
| `GET` | `/samples/filter/query` | Filter by gender, age, diagnosis year, ICD code |
| `GET` | `/health` | Health check |

Interactive docs available at `/docs` (Swagger UI) when running locally.

---

## Key Design Decisions

**Why versioning instead of overwriting?**
Clinical data requires a full audit trail. When a sample record changes, the old version is marked `is_latest=FALSE` and a new version is inserted. Nothing is ever deleted. The `/diff` endpoint shows exactly what changed between versions.

**Why JSONB for sparse fields?**
The source data has multiple slots for clinical info, macroscopic descriptions, microscopic descriptions, and diagnoses — most are empty for any given record. Storing these as flat nullable columns wastes space and makes the schema unwieldy. JSONB stores only non-empty values and integrates cleanly with PostgreSQL's full-text search pipeline.

**Why async?**
The API is built for concurrent use. All database operations use SQLAlchemy's async engine with connection pooling. CPU-bound work (pandas file parsing) runs in a thread pool executor so the event loop stays free during file processing.

**Why row-level validation before any DB writes?**
All rows are validated with Pydantic before the transaction begins. Valid rows insert, invalid rows go to `rejected_rows`. One bad row in a 500-row file never blocks the other 499.

**Why a Bronze layer?**
Saving raw file references before parsing means that if ingestion logic has a bug, the original data is always recoverable. This follows the Medallion Architecture pattern common in data engineering.

---

## Local Setup

**Prerequisites:** Python 3.11+, PostgreSQL 17

```bash
# 1. Clone and create virtual environment
git clone https://github.com/your-username/clinical-data-ingestion-api.git
cd clinical-data-ingestion-api
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create PostgreSQL database
psql -U postgres -c "CREATE USER api_user WITH PASSWORD 'your_password';"
psql -U postgres -c "CREATE DATABASE clinical_db OWNER api_user;"
psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE clinical_db TO api_user;"

# 4. Configure environment
cp .env.example .env
# Edit .env and set DATABASE_URL

# 5. Run
uvicorn main:app --reload
```

Open `http://localhost:8000/docs` for the interactive API.

---

## Upload Response Example

```json
{
  "file_name": "samples.xlsx",
  "rows_total": 43,
  "rows_inserted": 3,
  "rows_updated": 38,
  "rows_versioned": 2,
  "rows_rejected": 0,
  "ingestion_log_id": 5,
  "duplicate_file_warning": false,
  "missing_expected_columns": [],
  "versioned_diffs": [
    {
      "anonymized_sample_id": "a3f9c12b...001",
      "old_version": 1,
      "new_version": 2,
      "fields_changed": {
        "diagnosis_1": {
          "from_value": "Ganglio linfático: linfoma T angioinmunoblástico.",
          "to_value": "REVISED: Ganglio linfático: linfoma T angioinmunoblástico, estadio IV."
        },
        "age": {
          "from_value": 57,
          "to_value": 58
        }
      }
    }
  ]
}
```

---

## Project Structure

```
clinical-data-ingestion-api/
├── main.py                    # App entry point, lifespan, router registration
├── app/
│   ├── core/
│   │   ├── config.py          # Settings via pydantic-settings (.env)
│   │   └── logging.py         # Structured logging
│   ├── db/
│   │   ├── engine.py          # Async engine + connection pool
│   │   ├── session.py         # FastAPI dependency injection for DB sessions
│   │   └── init_db.py         # Table creation on startup
│   ├── models/
│   │   ├── raw_file.py        # Bronze layer
│   │   ├── ingestion_log.py   # Audit log
│   │   ├── sample.py          # Silver layer with versioning
│   │   └── rejected_row.py    # Validation failures
│   ├── schemas/
│   │   └── sample.py          # Pydantic validation + JSONB grouping logic
│   ├── services/
│   │   └── ingestion.py       # Deduplication, versioning, diff capture
│   ├── utils/
│   │   └── file_parser.py     # Async file parsing, delimiter detection
│   └── routers/
│       ├── upload.py          # POST /upload/upload_data
│       └── samples.py         # GET query endpoints
└── tests/                     # pytest test suite (in progress)
```

---

## What I Learned Building This

- Designing a schema for versioned clinical data — trade-offs between flat columns and JSONB for sparse fields
- Async Python patterns — `run_in_executor` for CPU-bound work, SQLAlchemy async sessions, connection pooling
- Debugging type mismatch bugs at system boundaries — timezone-aware vs naive datetimes across pandas, Pydantic, and PostgreSQL
- The Medallion Architecture pattern (Bronze/Silver layers) for production data ingestion pipelines
- FastAPI dependency injection and the `lifespan` context pattern for startup/shutdown
- Why row-level validation must be separated from DB writes in production systems

---

## Roadmap

- [ ] Unit and integration test suite (pytest + pytest-asyncio)
- [ ] Populate `search_vector` for full-text search across clinical fields
- [ ] Alembic migrations (currently using `create_all` for development)
- [ ] API key authentication middleware
- [ ] Docker + docker-compose for deployment
