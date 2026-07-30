from database import get_db


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS companies (
        id SERIAL PRIMARY KEY,
        chat_title TEXT NOT NULL,
        telegram_chat_id BIGINT UNIQUE NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS staff (
        id SERIAL PRIMARY KEY,
        company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        telegram_id BIGINT NOT NULL,
        staff_id TEXT NOT NULL,
        name TEXT NOT NULL,
        real_name TEXT NOT NULL,
        username TEXT,
        status TEXT DEFAULT 'Active',
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(company_id, telegram_id)
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS roles (
        id SERIAL PRIMARY KEY,
        company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        telegram_id BIGINT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('user', 'leader', 'admin')),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(company_id, telegram_id)
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS break_records (
        id SERIAL PRIMARY KEY,
        company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        telegram_id BIGINT NOT NULL,
        staff_id TEXT NOT NULL,
        name TEXT NOT NULL,
        type TEXT NOT NULL CHECK (type IN ('Toilet', 'Smoke', 'Meal')),
        out_time TIMESTAMP NOT NULL,
        in_time TIMESTAMP,
        duration INTEGER,
        status TEXT NOT NULL DEFAULT 'Open'
            CHECK (status IN ('Open', 'Normal', 'Warning', 'Timeout', 'Cancelled')),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        sheet_row_number INTEGER,
        needs_sheet_sync BOOLEAN NOT NULL DEFAULT FALSE
    );
    """)

    cur.execute("ALTER TABLE break_records ADD COLUMN IF NOT EXISTS sheet_row_number INTEGER;")
    cur.execute("ALTER TABLE break_records ADD COLUMN IF NOT EXISTS needs_sheet_sync BOOLEAN NOT NULL DEFAULT FALSE;")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_break_records_pending_sync ON break_records (needs_sheet_sync, id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_break_records_company_out_time ON break_records (company_id, out_time);")

    conn.commit()
    cur.close()
    conn.close()
    print("Database ready.")


if __name__ == "__main__":
    init_db()
