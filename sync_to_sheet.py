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


def today_kh():
    return date.today()


def format_time(value):
    if not value:
        return ""
    return value.strftime("%Y-%m-%d %I:%M:%S %p")


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
        today = today_kh()

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


def open_company_spreadsheet(chat_title):
    spreadsheet_id = get_spreadsheet_id(chat_title)

    if not spreadsheet_id:
        print(f"No spreadsheet ID for {chat_title}")
        return None

    gc = get_gspread_client()
    return gc.open_by_key(spreadsheet_id)


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


def find_row_by_id(worksheet, record_id):
    values = worksheet.get_all_values()

    for index, row in enumerate(values, start=1):
        if row and row[0] == str(record_id):
            return index

    return None


def sync_staff_to_sheet(chat_title):
    spreadsheet = open_company_spreadsheet(chat_title)

    if not spreadsheet:
        return

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
        return

    company_id = company["id"]

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

    cur.close()
    conn.close()

    headers = [
        "Telegram ID",
        "Staff ID",
        "Real Name",
        "Username",
        "Status",
        "Active",
        "Created At",
        "Updated At"
    ]

    worksheet = get_or_create_sheet(spreadsheet, "Staff", headers)

    worksheet.clear()
    worksheet.append_row(headers)

    values = []

    for row in staff_rows:
        values.append([
            row["telegram_id"],
            row["staff_id"],
            row["real_name"],
            row["username"] or "",
            row["status"],
            row["is_active"],
            format_time(row["created_at"]),
            format_time(row["updated_at"])
        ])

    if values:
        worksheet.append_rows(values)

    print(f"Staff synced for {chat_title}")


def sync_record_to_sheet(chat_title, record_id):
    spreadsheet = open_company_spreadsheet(chat_title)

    if not spreadsheet:
        return

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            id,
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
        WHERE id = %s
        """,
        (record_id,)
    )

    row = cur.fetchone()

    cur.close()
    conn.close()

    if not row:
        return

    _, _, tab_name = get_cycle_period(row["out_time"].date())

    headers = [
        "Record ID",
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

    worksheet = get_or_create_sheet(spreadsheet, tab_name, headers)

    values = [
        row["id"],
        row["telegram_id"],
        row["staff_id"],
        row["name"],
        row["type"],
        format_time(row["out_time"]),
        format_time(row["in_time"]),
        row["duration"],
        row["status"],
        format_time(row["created_at"])
    ]

    target_row = find_row_by_id(worksheet, row["id"])

    if target_row:
        worksheet.update(f"A{target_row}:J{target_row}", [values])
    else:
        worksheet.append_row(values)

    print(f"Record {record_id} synced to {tab_name}")