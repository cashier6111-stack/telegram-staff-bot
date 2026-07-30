import os
import time

import psycopg2
from psycopg2.extras import RealDictCursor


def get_db():
    database_url = os.environ["DATABASE_URL"]
    last_error = None
    for attempt in range(5):
        try:
            return psycopg2.connect(
                database_url,
                cursor_factory=RealDictCursor,
                connect_timeout=10,
            )
        except Exception as exc:
            last_error = exc
            print(f"Database connection retry {attempt + 1}/5:", exc)
            time.sleep(3)
    raise last_error
