import os
import json
from datetime import date

import gspread
from google.oauth2.service_account import Credentials

from database import get_db


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]


COMPANY_SHEETS = {
    "[8MBET] Attendance": "SHEET_8MBET",
    "[MJ88] Attendance": "SHEET_MJ88",
    "[ESEWA12] Attendance": "SHEET_ESEWA12",
    "[MAGAR33] Attendance": "SHEET_MAGAR33",
    "[NPR77] Attendance": "SHEET_NPR77",
}


def get_gspread_client():
    credentials_json = os.environ["GOOGLE_CREDENTIALS_JSON"]
    service_account_info = json.loads(credentials_json)

    creds = Credentials.from_service_account_info(
        service_account_info,
        scopes=SCOPES
    )

    return gspread.authorize(creds)


def get_cycle_period(today=None):
    if today is None:
        today = date.today()

    year = today.year
    month = today.month

    if today.day >= 21:
        start_year = year
        start_month = month

        if month == 12:
            end_year = year + 1
            end_month = 1
        else:
            end_year = year
            end_month = month + 1

    else:
        end_year = year
        end_month = month

        if month == 1:
            start_year = year - 1
            start_month = 12
        else:
            start_year = year
            start_month = month - 1

    start_date = date(start_year, start_month, 21)
    end_date = date(end_year, end_month, 20)

    tab_name = f"{start_date.strftime('%d/%m')}-{end_date.strftime('%d/%m')}"

    return start_date, end_date, tab_name


def get_spreadsheet_id(chat_title):
    variable_name = COMPANY_SHEETS.get(chat_title)

    if not variable_name:
        return None

    return os.environ.get(variable_name)


def get_or_create_sheet(spreadsheet, tab_name, headers):
    try:
        worksheet = spreadsheet.worksheet(tab_name)
    except Exception:
        worksheet = spreadsheet.add_worksheet(
            title=tab_name,
            rows=3000,
            cols=len(headers) + 3
        )
        worksheet.append_row(headers)

    return worksheet


def sync_company_to_sheet(chat_title):
    spreadsheet_id = get_spreadsheet_id(chat_title)

    if not spreadsheet_id:
        print(f"No spreadsheet ID for {chat_title}")
        return

    gc = get_gspread_client()
    spreadsheet = gc.open_by_key(spreadsheet_id)

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id
        FROM companies
        WHERE chat_title = %s
        """,
        (chat_title,)
    )

    company = cur.fetchone()

    if not company:
        cur.close()
        conn.close()
        print(f"No company found for {chat_title}")
        return

    company_id = company["id"]

    start_date, end_date, tab_name = get_cycle_period()

    cur.execute(
        """
        SELECT
            telegram_id,
            staff_id,
            real_name,
            username,
            status,
            is_active,
            created_at,
            updated_at
        FROM staff
        WHERE company_id = %s
        ORDER BY staff_id
        """,
        (company_id,)
    )

    staff_rows = cur.fetchall()

    cur.execute(
        """
        SELECT
            telegram_id,
            staff_id,
            name,
            type,
            out_time,
            in_time,
            duration,
            status,
            created_at
        FROM break_records
        WHERE company_id = %s
        AND out_time::date >= %s
        AND out_time::date <= %s
        ORDER BY out_time
        """,
        (company_id, start_date, end_date)
    )

    record_rows = cur.fetchall()

    cur.close()
    conn.close()

    staff_sheet = get_or_create_sheet(
        spreadsheet,
        "Staff",
        [
            "Telegram ID",
            "Staff ID",
            "Real Name",
            "Username",
            "Status",
            "Active",
            "Created At",
            "Updated At"
        ]
    )

    staff_sheet.clear()
    staff_sheet.append_row([
        "Telegram ID",
        "Staff ID",
        "Real Name",
        "Username",
        "Status",
        "Active",
        "Created At",
        "Updated At"
    ])

    staff_values = []

    for row in staff_rows:
        staff_values.append([
            row["telegram_id"],
            row["staff_id"],
            row["real_name"],
            row["username"] or "",
            row["status"],
            row["is_active"],
            str(row["created_at"]),
            str(row["updated_at"])
        ])

    if staff_values:
        staff_sheet.append_rows(staff_values)

    record_sheet = get_or_create_sheet(
        spreadsheet,
        tab_name,
        [
            "Telegram ID",
            "Staff ID",
            "Name",
            "Type",
            "Out Time",
            "In Time",
            "Duration",
            "Status",
            "Created At"
        ]
    )

    record_sheet.clear()
    record_sheet.append_row([
        "Telegram ID",
        "Staff ID",
        "Name",
        "Type",
        "Out Time",
        "In Time",
        "Duration",
        "Status",
        "Created At"
    ])

    record_values = []

    for row in record_rows:
        record_values.append([
            row["telegram_id"],
            row["staff_id"],
            row["name"],
            row["type"],
            str(row["out_time"]),
            str(row["in_time"]) if row["in_time"] else "",
            row["duration"],
            row["status"],
            str(row["created_at"])
        ])

    if record_values:
        record_sheet.append_rows(record_values)

    print(f"Synced {chat_title} to {tab_name}")


def sync_all_companies():
    for chat_title in COMPANY_SHEETS.keys():
        try:
            sync_company_to_sheet(chat_title)
        except Exception as e:
            print(f"Sync error for {chat_title}: {e}")