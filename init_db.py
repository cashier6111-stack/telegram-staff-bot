import os
import psycopg2


FIRST_ADMIN_ID = 8439975606


SQL = """
CREATE TABLE IF NOT EXISTS companies (
    id SERIAL PRIMARY KEY,
    chat_title TEXT NOT NULL,
    telegram_chat_id BIGINT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS staff (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    telegram_id BIGINT NOT NULL,
    staff_id TEXT NOT NULL,
    real_name TEXT NOT NULL,
    username TEXT,
    status TEXT DEFAULT 'Active',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, telegram_id),
    UNIQUE(company_id, staff_id)
);

CREATE TABLE IF NOT EXISTS roles (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    telegram_id BIGINT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'leader', 'admin')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, telegram_id)
);

CREATE TABLE IF NOT EXISTS break_records (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    telegram_id BIGINT NOT NULL,
    staff_id TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('Toilet', 'Smoke', 'Meal')),
    out_time TIMESTAMP NOT NULL,
    in_time TIMESTAMP,
    duration INTEGER DEFAULT 0,
    status TEXT DEFAULT 'Open' CHECK (
        status IN ('Open', 'Normal', 'Warning', 'Timeout', 'Cancelled')
    ),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur = conn.cursor()

cur.execute("""
ALTER TABLE staff
ADD COLUMN IF NOT EXISTS telegram_id BIGINT;

ALTER TABLE staff
ADD COLUMN IF NOT EXISTS real_name TEXT;

ALTER TABLE staff
ADD COLUMN IF NOT EXISTS username TEXT;

ALTER TABLE staff
ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'Active';

ALTER TABLE staff
ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;

ALTER TABLE staff
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
""")

conn.commit()

cur.close()
conn.close()

print("Database ready.")