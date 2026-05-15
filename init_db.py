import os
import psycopg2

SQL = """
CREATE TABLE IF NOT EXISTS companies (
    id SERIAL PRIMARY KEY,
    chat_title TEXT NOT NULL UNIQUE,
    telegram_chat_id BIGINT UNIQUE,
    spreadsheet_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS staff (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    staff_id TEXT NOT NULL,
    name TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, staff_id)
);

CREATE TABLE IF NOT EXISTS break_records (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    staff_id TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('Toilet', 'Smoke', 'Meal')),
    out_time TIMESTAMP NOT NULL,
    in_time TIMESTAMP,
    duration INTEGER DEFAULT 0,
    status TEXT DEFAULT 'Normal' CHECK (
        status IN ('Normal', 'Warning', 'Timeout', 'Cancelled')
    ),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_break_records_company_out_time
ON break_records(company_id, out_time);

CREATE INDEX IF NOT EXISTS idx_break_records_staff_id
ON break_records(company_id, staff_id);
"""

conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur = conn.cursor()

cur.execute(SQL)
conn.commit()

cur.close()
conn.close()

print("Database ready.")