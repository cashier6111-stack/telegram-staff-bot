import time

from sync_to_sheet import COMPANY_SHEETS, sync_monthly_summary_to_sheet


for company_name in COMPANY_SHEETS:
    try:
        success = sync_monthly_summary_to_sheet(
            company_name,
            all_periods=True,
        )
        print(f"Summary rebuild {company_name}: {success}")
        time.sleep(3)
    except Exception as exc:
        print(f"Summary rebuild failed for {company_name}:", exc)
        if "429" in str(exc):
            print("Google quota reached. Wait 90 seconds before continuing.")
            time.sleep(90)
