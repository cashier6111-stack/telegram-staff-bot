import os
import json
import re
import time
from datetime import date, datetime, timedelta, timezone

import gspread
from google.oauth2.service_account import Credentials

from database import get_db


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

KH_TZ = timezone(timedelta(hours=7))


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
    return datetime.now(KH_TZ).date()


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


def get_or_create_sheet(spreadsheet, tab_name, headers, hide_record_id=False):
    created = False

    try:
        worksheet = spreadsheet.worksheet(tab_name)
    except Exception:
        worksheet = spreadsheet.add_worksheet(
            title=tab_name,
            rows=3000,
            cols=len(headers) + 3
        )
        worksheet.append_row(headers)
        created = True

    # Hide J (Record ID) only when a record sheet is first created.
    # This avoids a Google Sheets write request on every attendance sync.
    if created and hide_record_id:
        try:
            worksheet.hide_columns(9, 10)
        except Exception as e:
            print(f"Hide Record ID column warning for {tab_name}:", e)

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


def _extract_appended_row_number(response):
    """
    Extract the appended row number from the Google Sheets API response.
    Example updatedRange:
    '21/07-20/08'!A1555:J1555
    """
    try:
        updated_range = response["updates"]["updatedRange"]
        first_cell = updated_range.rsplit("!", 1)[-1].split(":", 1)[0]
        match = re.search(r"(\d+)$", first_cell)
        if match:
            return int(match.group(1))
    except Exception:
        pass

    return None


def _find_record_row(worksheet, record_id):
    """
    Find a record only in hidden Record ID column J.
    Used as a repair fallback when the DB row pointer is missing/wrong.
    """
    try:
        cell = worksheet.find(str(record_id), in_column=10)
        if cell:
            return cell.row
    except Exception as e:
        print(f"Record ID lookup warning ({record_id}):", e)

    return None


def sync_record_to_sheet(chat_title, record_id):
    spreadsheet = open_company_spreadsheet(chat_title)

    if not spreadsheet:
        return False

    conn = get_db()
    cur = conn.cursor()

    try:
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
            return False

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

        worksheet = get_or_create_sheet(
            spreadsheet,
            tab_name,
            headers,
            hide_record_id=True
        )

        values = [
            row["telegram_id"],
            row["staff_id"],
            row["name"],
            row["type"],
            format_time(row["out_time"]),
            format_time(row["in_time"]),
            row["duration"] if row["duration"] is not None else "",
            row["status"],
            format_time(row["created_at"]),
            row["id"]
        ]

        target_row = None

        # 1) Fast path: use row pointer saved in PostgreSQL.
        #    Validate J first so we never overwrite another person's row.
        if row["sheet_row_number"]:
            try:
                check_value = worksheet.acell(
                    f"J{row['sheet_row_number']}"
                ).value

                if str(check_value) == str(row["id"]):
                    target_row = row["sheet_row_number"]
            except Exception as e:
                print(
                    f"Stored row validation warning "
                    f"record={record_id} row={row['sheet_row_number']}:",
                    e
                )

        # 2) Repair path: stored pointer is missing/wrong.
        if not target_row:
            target_row = _find_record_row(worksheet, row["id"])

        # 3) Update existing row, or append only if this Record ID
        #    genuinely does not exist in the period sheet.
        if target_row:
            worksheet.update(
                f"A{target_row}:J{target_row}",
                [values]
            )

            if row["sheet_row_number"] != target_row:
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
            response = worksheet.append_row(
                values,
                value_input_option="USER_ENTERED"
            )

            new_row_number = _extract_appended_row_number(response)

            # Rare fallback if API response did not contain updatedRange.
            if not new_row_number:
                time.sleep(0.5)
                new_row_number = _find_record_row(
                    worksheet,
                    row["id"]
                )

            if not new_row_number:
                raise RuntimeError(
                    f"Could not determine Google Sheet row "
                    f"for record {record_id}"
                )

            cur.execute(
                """
                UPDATE break_records
                SET sheet_row_number = %s
                WHERE id = %s
                """,
                (new_row_number, record_id)
            )
            conn.commit()

        print(
            f"Record {record_id} synced to {tab_name} "
            f"(row {target_row or new_row_number})"
        )

        return True

    finally:
        cur.close()
        conn.close()


def _build_period_summary_rows(company_id, start_dt, end_dt):
    conn = get_db()
    cur = conn.cursor()

    try:
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
            AND out_time >= %s
            AND out_time < %s
            AND status != 'Open'
            ORDER BY out_time, staff_id, name
            """,
            (company_id, start_dt, end_dt)
        )

        records = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    summary = {}

    for row in records:
        # Important: staff_id + historical name is intentionally the key.
        # If either changes, Summary treats it as a new identity.
        key = (str(row["staff_id"]), str(row["name"]))

        if key not in summary:
            summary[key] = {
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

        # Cancelled records are counted only as Cancelled,
        # not as normal break time/count.
        if status != "Cancelled":
            if action_type == "Toilet":
                summary[key]["Toilet Total"] += duration
                summary[key]["Toilet Times"] += 1
            elif action_type == "Smoke":
                summary[key]["Smoke Total"] += duration
                summary[key]["Smoke Times"] += 1
            elif action_type == "Meal":
                summary[key]["Meal Total"] += duration
                summary[key]["Meal Times"] += 1

        if status == "Warning":
            summary[key]["Warning Times"] += 1
        elif status == "Timeout":
            summary[key]["Timeout Times"] += 1
        elif status == "Cancelled":
            summary[key]["Cancelled Times"] += 1

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

    return values


SUMMARY_HEADERS = [
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


def sync_period_summary_to_sheet(
    chat_title,
    start_date_text,
    end_date_text
):
    """
    Rebuild only one requested period Summary.
    This is used after /resyncperiod so we do not rewrite every historical
    Summary tab and hit Google's write quota.
    """
    spreadsheet = open_company_spreadsheet(chat_title)

    if not spreadsheet:
        return False

    start_date = datetime.strptime(
        start_date_text,
        "%Y-%m-%d"
    )
    end_date = datetime.strptime(
        end_date_text,
        "%Y-%m-%d"
    )

    end_exclusive = end_date + timedelta(days=1)

    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            SELECT id
            FROM companies
            WHERE chat_title = %s
            """,
            (chat_title,)
        )
        company = cur.fetchone()
    finally:
        cur.close()
        conn.close()

    if not company:
        return False

    values = _build_period_summary_rows(
        company["id"],
        start_date,
        end_exclusive
    )

    tab_name = (
        f"{start_date.strftime('%d/%m')}-"
        f"{end_date.strftime('%d/%m')}"
    )
    summary_tab = f"Summary {tab_name}"

    worksheet = get_or_create_sheet(
        spreadsheet,
        summary_tab,
        SUMMARY_HEADERS
    )

    worksheet.clear()
    worksheet.append_row(SUMMARY_HEADERS)

    if values:
        worksheet.append_rows(
            values,
            value_input_option="USER_ENTERED"
        )

    print(
        f"Period summary synced for {chat_title}: "
        f"{summary_tab}"
    )

    return True


def sync_monthly_summary_to_sheet(chat_title):
    """
    Rebuild every historical cycle Summary for this company.
    Use sparingly because this can generate many Google write requests.
    """
    spreadsheet = open_company_spreadsheet(chat_title)

    if not spreadsheet:
        return False

    conn = get_db()
    cur = conn.cursor()

    try:
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
            return False

        company_id = company["id"]

        cur.execute(
            """
            SELECT DISTINCT out_time::date AS record_date
            FROM break_records
            WHERE company_id = %s
            ORDER BY record_date
            """,
            (company_id,)
        )

        dates = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    periods = {}

    for item in dates:
        record_date = item["record_date"]
        start_date, end_date, tab_name = get_cycle_period(record_date)
        periods[tab_name] = (start_date, end_date)

    for tab_name, (start_date, end_date) in periods.items():
        sync_period_summary_to_sheet(
            chat_title,
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d")
        )
        # Stagger full-history rebuilds to reduce write bursts.
        time.sleep(1.0)

    print(
        f"All monthly summaries synced for {chat_title}"
    )

    return True


def safe_resync_period_to_sheet(
    chat_title,
    start_date_text,
    end_date_text,
    delay_seconds=2.0,
    max_retries=5
):
    """
    Safely resync one Telegram group's records for a date range.

    - Reads source data from PostgreSQL.
    - Syncs one record at a time.
    - Sleeps between records to stay below Google per-minute quotas.
    - Retries 429/quota failures with increasing backoff.
    - Rebuilds only the requested period Summary at the end.
    """
    start_date = datetime.strptime(
        start_date_text,
        "%Y-%m-%d"
    )
    end_date = datetime.strptime(
        end_date_text,
        "%Y-%m-%d"
    )

    if end_date < start_date:
        raise ValueError(
            "End date cannot be earlier than start date."
        )

    end_exclusive = end_date + timedelta(days=1)

    conn = get_db()
    cur = conn.cursor()

    try:
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
            return {
                "total": 0,
                "synced": 0,
                "failed": 0
            }

        company_id = company["id"]

        cur.execute(
            """
            SELECT id
            FROM break_records
            WHERE company_id = %s
            AND out_time >= %s
            AND out_time < %s
            ORDER BY id
            """,
            (
                company_id,
                start_date,
                end_exclusive
            )
        )

        rows = cur.fetchall()

    finally:
        cur.close()
        conn.close()

    total = len(rows)
    synced = 0
    failed = 0

    print(
        f"Safe resync started: {chat_title} "
        f"{start_date_text} -> {end_date_text}, "
        f"{total} records"
    )

    for index, row in enumerate(rows, start=1):
        record_id = row["id"]
        success = False

        for attempt in range(1, max_retries + 1):
            try:
                result = sync_record_to_sheet(
                    chat_title,
                    record_id
                )

                if not result:
                    raise RuntimeError(
                        f"sync_record_to_sheet returned False "
                        f"for record {record_id}"
                    )

                success = True
                synced += 1

                print(
                    f"Resync {index}/{total}: "
                    f"record {record_id} synced"
                )
                break

            except Exception as e:
                error_text = str(e).lower()

                print(
                    f"Resync record {record_id} "
                    f"attempt {attempt}/{max_retries} failed:",
                    e
                )

                if (
                    "429" in error_text
                    or "quota exceeded" in error_text
                    or "rate limit" in error_text
                ):
                    wait_seconds = min(
                        120,
                        20 * attempt
                    )
                else:
                    wait_seconds = min(
                        30,
                        3 * attempt
                    )

                print(
                    f"Waiting {wait_seconds}s before retry..."
                )
                time.sleep(wait_seconds)

        if not success:
            failed += 1
            print(
                f"Giving up record {record_id} "
                f"after {max_retries} attempts."
            )

        time.sleep(delay_seconds)

    # One summary rebuild only, not all historical summaries.
    try:
        sync_period_summary_to_sheet(
            chat_title,
            start_date_text,
            end_date_text
        )
    except Exception as e:
        print("Period summary resync error:", e)

    result = {
        "total": total,
        "synced": synced,
        "failed": failed
    }

    print(
        f"Safe resync completed: {chat_title}, "
        f"total={total}, synced={synced}, failed={failed}"
    )

    return result
