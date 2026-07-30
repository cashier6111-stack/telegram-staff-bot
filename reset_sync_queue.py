from database import get_db


conn = get_db()
cur = conn.cursor()
cur.execute("UPDATE break_records SET needs_sheet_sync = FALSE")
print(f"Cleared pending sync flags: {cur.rowcount}")
conn.commit()
cur.close()
conn.close()
