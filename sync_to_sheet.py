import os
import json
from datetime import date, datetime, time

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
    "[NPL11] Attendance": "SHEET_NPL11",
    "[CASHIER] Attendance": "SHEET_CASHIER",
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
            created_at,
            sheet_row_number
        FROM break_records
        WHERE id = %s
        """,
        (record_id,)
    )

    row = cur.fetchone()

    if not row:
        cur.close()
        conn.close()
        return

    _, _, tab_name = get_cycle_period(row["out_time"].date())

    headers = [
        "Telegram ID",
        "Staff ID",
        "Name",
        "Type",
        "Out Time",
        "In Time",
        "Duration",
        "Status",
        "Created At",
        "Record ID"
    ]

    worksheet = get_or_create_sheet(spreadsheet, tab_name, headers)

    values = [
        row["telegram_id"],
        row["staff_id"],
        row["name"],
        row["type"],
        format_time(row["out_time"]),
        format_time(row["in_time"]),
        row["duration"],
        row["status"],
        format_time(row["created_at"]),
        row["id"]
    ]

    target_row = None

    if row["sheet_row_number"]:
        try:
            check_value = worksheet.acell(f"J{row['sheet_row_number']}").value

            if str(check_value) == str(row["id"]):
                target_row = row["sheet_row_number"]
        except Exception:
            target_row = None

    if not target_row:
        try:
            cell = worksheet.find(str(row["id"]))
            if cell:
                target_row = cell.row
        except Exception:
            target_row = None

    if target_row:
        worksheet.update(
            f"A{target_row}:J{target_row}",
            [values]
        )

        cur.execute(
            """
            UPDATE break_records
            SET sheet_row_number = %s
            WHERE id = %s
            """,
            (target_row, record_id)
        )

        conn.commit()

    else:
        response = worksheet.append_row(values)

        updated_range = response["updates"]["updatedRange"]
        row_part = updated_range.split("!")[1].split(":")[0]
        new_row_number = int(row_part[1:])

        cur.execute(
            """
            UPDATE break_records
            SET sheet_row_number = %s
            WHERE id = %s
            """,
            (new_row_number, record_id)
        )

        conn.commit()

    cur.close()
    conn.close()

    try:
        worksheet.hide_columns(10)
    except Exception:
        pass

    print(f"Record {record_id} synced to {tab_name}")

def sync_monthly_summary_to_sheet(chat_title):
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
            staff_id,
            name,
            type,
            duration,
            status,
            out_time
        FROM break_records
        WHERE company_id = %s
        AND status != 'Open'
        ORDER BY out_time, staff_id, name
        """,
        (company_id,)
    )

    records = cur.fetchall()

    cur.close()
    conn.close()

    if not records:
        return

    grouped = {}

    for row in records:
        _, _, tab_name = get_cycle_period(row["out_time"].date())

        if tab_name not in grouped:
            grouped[tab_name] = {}

        key = f"{row['staff_id']}|{row['name']}"

        if key not in grouped[tab_name]:
            grouped[tab_name][key] = {
                "staff_id": row["staff_id"],
                "name": row["name"],
                "Toilet Total": 0,
                "Toilet Times": 0,
                "Smoke Total": 0,
                "Smoke Times": 0,
                "Meal Total": 0,
                "Meal Times": 0,
                "Warning Times": 0,
                "Timeout Times": 0,
                "Cancelled Times": 0,
            }

        action_type = row["type"]
        duration = row["duration"] or 0
        status = row["status"]

        if action_type == "Toilet":
            grouped[tab_name][key]["Toilet Total"] += duration
            grouped[tab_name][key]["Toilet Times"] += 1

        if action_type == "Smoke":
            grouped[tab_name][key]["Smoke Total"] += duration
            grouped[tab_name][key]["Smoke Times"] += 1

        if action_type == "Meal":
            grouped[tab_name][key]["Meal Total"] += duration
            grouped[tab_name][key]["Meal Times"] += 1

        if status == "Warning":
            grouped[tab_name][key]["Warning Times"] += 1

        if status == "Timeout":
            grouped[tab_name][key]["Timeout Times"] += 1

        if status == "Cancelled":
            grouped[tab_name][key]["Cancelled Times"] += 1

    headers = [
        "Staff ID",
        "Name",
        "Toilet Total Min",
        "Toilet Times",
        "Smoke Total Min",
        "Smoke Times",
        "Meal Total Min",
        "Meal Times",
        "Warning Times",
        "Timeout Times",
        "Cancelled Times"
    ]

    for tab_name, summary in grouped.items():
        summary_tab = f"Summary {tab_name}"

        worksheet = get_or_create_sheet(spreadsheet, summary_tab, headers)

        worksheet.clear()
        worksheet.append_row(headers)

        values = []

        for key in sorted(summary.keys()):
            data = summary[key]

            values.append([
                data["staff_id"],
                data["name"],
                data["Toilet Total"],
                data["Toilet Times"],
                data["Smoke Total"],
                data["Smoke Times"],
                data["Meal Total"],
                data["Meal Times"],
                data["Warning Times"],
                data["Timeout Times"],
                data["Cancelled Times"],
            ])

        if values:
            worksheet.append_rows(values)

    print(f"All monthly summaries synced for {chat_title}")