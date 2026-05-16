from database import get_db

def add_staff(staff_id, name):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO staff (staff_id, name)
        VALUES (%s, %s)
        ON CONFLICT (staff_id)
        DO NOTHING
        """,
        (staff_id, name)
    )

    conn.commit()

    cur.close()
    conn.close()


def get_staff(staff_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM staff WHERE staff_id = %s",
        (staff_id,)
    )

    result = cur.fetchone()

    cur.close()
    conn.close()

    return result


def list_staff():
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM staff ORDER BY name"
    )

    result = cur.fetchall()

    cur.close()
    conn.close()

    return result