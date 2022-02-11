from datetime import date, datetime, timedelta
import time
import requests
from slack_sdk.webhook import WebhookClient
import os
import math
#from slack_sdk.models import *
import textwrap
import hmac
import hashlib

PAYFIT_URL = "https://api.payfit.com/"
PAYFIT_EMPLOYEES_ENDPOINT = f"{PAYFIT_URL}hr/employees"
PAYFIT_ABSENCES_ENDPOINT = f"{PAYFIT_URL}hr/employee-request/absences"
PAYFIT_ACCOUNTS_ENDPOINT = f"{PAYFIT_URL}auth/accounts"
PAYFIT_LOGIN_ENDPOINT = f"{PAYFIT_URL}auth/signin"
PAYFIT_REFRESH_ENDPOINT = f"{PAYFIT_URL}auth/accessToken"
PAYFIT_UPDATE_CURRENT_ACCOUNT_ENDPOINT = f"{PAYFIT_URL}auth/updateCurrentAccount"

SLACK_WEBHOOK = os.environ['SLACK_WEBHOOK']
if 'PAYFIT_ACCESS_TOKEN' in os.environ:
    PAYFIT_ACCESS_TOKEN = os.environ['PAYFIT_ACCESS_TOKEN']
    PAYFIT_REFRESH_TOKEN = os.environ['PAYFIT_REFRESH_TOKEN']
else:
    PAYFIT_ACCESS_TOKEN = None
    PAYFIT_REFRESH_TOKEN = None
if 'PAYFIT_EMAIL' in os.environ:
    PAYFIT_EMAIL = os.environ['PAYFIT_EMAIL']
    PAYFIT_PASSWORD = os.environ['PAYFIT_PASSWORD']
else:
    PAYFIT_EMAIL = None
    PAYFIT_PASSWORD = None

THRESHOLD = 20
FORMATION = 0

def login(username: str, password: str):
    pw_hashed = hmac.digest(password.encode('utf-8'), b"", hashlib.sha256).hex()
    data = dict(email=username, password=pw_hashed,remember=True)
    resp = requests.post(PAYFIT_LOGIN_ENDPOINT, json=data)
    if not resp:
        print(resp.json())
        resp.raise_for_status()
    return resp.cookies['accessToken'], resp.cookies['refreshToken']

def get_accounts(access_token: str):
    cookies = dict(accessToken=access_token)
    resp = requests.get(PAYFIT_ACCOUNTS_ENDPOINT, cookies=cookies)
    if not resp:
        print(resp.json())
        resp.raise_for_status()
    return resp.json()

def update_current_account(access_token: str, refresh_token: str, companyId: str, employeeId: str):
    cookies = dict(accessToken=access_token, refreshToken=refresh_token)
    data = dict(companyId=companyId, employeeId=employeeId)
    resp = requests.post(PAYFIT_UPDATE_CURRENT_ACCOUNT_ENDPOINT, json=data, cookies=cookies)
    if not resp:
        print(resp.json())
        resp.raise_for_status()
    return resp.cookies['accessToken'], resp.cookies['refreshToken']

def get_new_token(access_token: str, refresh_token: str):
    cookies = dict(accessToken=access_token, refreshToken=refresh_token)
    resp = requests.post(PAYFIT_REFRESH_ENDPOINT, cookies=cookies)
    if not resp:
        print(resp.json())
        resp.raise_for_status()
    return resp.json()


def get_absences(access_token: str):
    cookies = dict(accessToken=access_token)
    resp = requests.post(PAYFIT_ABSENCES_ENDPOINT, cookies=cookies)
    if not resp:
        print(resp.json())
        resp.raise_for_status()
    return resp.json()

def get_employees(access_token: str):
    cookies = dict(accessToken=access_token)
    resp = requests.post(PAYFIT_EMPLOYEES_ENDPOINT, cookies=cookies)
    if not resp:
        print(resp.json())
        resp.raise_for_status()
    return resp.json()

def main():
    if PAYFIT_EMAIL is not None and PAYFIT_PASSWORD is not None:
        access_token, refresh_token = login(PAYFIT_EMAIL, PAYFIT_PASSWORD)
        print(f"Login successful!")

        # TODO: Account selector.
        acts = get_accounts(access_token)
        account = acts[0]['account']
        access_token, refresh_token = update_current_account(access_token, refresh_token, account['companyId'], account['employeeId'])

    elif PAYFIT_ACCESS_TOKEN is not None and PAYFIT_REFRESH_TOKEN is not None:
        access_token = PAYFIT_ACCESS_TOKEN
        refresh_token = PAYFIT_REFRESH_TOKEN
    else:
        raise Exception("No valid login method found.")

    webhook = WebhookClient(SLACK_WEBHOOK)

    while True:
        try:
            print(f"Refreshing token")
            data = get_new_token(access_token, refresh_token)
            access_token = data['accessToken']
            refresh_token = data['refreshToken']
        except requests.HTTPError:
            # if we failed to get new tokens, try to login.
            if PAYFIT_EMAIL is not None and PAYFIT_PASSWORD is not None:
                print("Failed to get new tokens. Reconnecting.")
                access_token, refresh_token = login(PAYFIT_EMAIL, PAYFIT_PASSWORD)
                access_token, refresh_token = update_current_account(access_token, refresh_token, account['companyId'], account['employeeId'])
            else:
                raise

        absences = get_absences(access_token)
        employeesFullInfo = get_employees(access_token)

        employees = [employee['id'] for employee in employeesFullInfo if employee['status']['isActive']]

        check_for = datetime.now()
        if 2 <= check_for.hour <= 12:
            time.sleep(60*60)
            continue

        if 12 < check_for.hour:
            check_for = check_for.date() + timedelta(days=1)
        else:
            check_for = check_for.date()

        if check_for.weekday() >= 5:
            check_for = check_for + timedelta(days=7 - check_for.weekday())

        absents = []

        for absence in absences['absences']:
            if not (absence['status'] == "success" or absence['status'] == "pending"):
                continue
            day, month, year = absence['begin'].split("/")
            absence_start = date(int(year), int(month), int(day))
            day, month, year = absence['end'].split("/")
            absence_end = date(int(year), int(month), int(day))
            if absence_start <= check_for <= absence_end:
                absents.append(absence['employeeId'])

        presents = set(employees) - set(absents)

        num_present = len(presents)

        # Generate a square grid (whose width/height is calculated as sqrt(num employees),
        # so it's a pretty square.
        # Each square represents the status of a single employee.
        graphmsg = f"{num_present}/{THRESHOLD+FORMATION}\n"
        graphmsg += "\n"

        formation = min(FORMATION, num_present)
        office_seat = num_present - formation
        below_ceil = min(office_seat, THRESHOLD)
        above_ceil = max(office_seat - THRESHOLD, 0)
        graph = "🟩" * below_ceil
        graph += "🟪" * above_ceil
        graph += "🟧" * formation
        graph += "⬜" * len(absents)

        max_char_per_line = min(round(math.sqrt(len(employees))), 25)

        graph = "\n".join(textwrap.wrap(graph, max_char_per_line))

        graphmsg += graph
        graphmsg += "\n\n\n"
        graphmsg += "🟩: Office work under threshold\n"
        graphmsg += "🟪: Office work over threshold\n"
        graphmsg += "🟧: In formation\n"
        graphmsg += "⬜: Remote work/absentee\n"

        print(graphmsg)


        if len(presents) >= THRESHOLD+FORMATION:
            webhook.send(
                text=f"There are too many people scheduled to go to the office tomorrow (currently, {len(presents)} people are scheduled to come in).",
                blocks=[
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": ":microbe: COVID Alert :microbe:"
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"Too many people are scheduled to work from the office on {check_for}.\nThere should only be a maximum of {THRESHOLD} people at the office at once."
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": graphmsg
                        }
                    },
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {
                                    "type": "plain_text",
                                    "text": "Schedule Remote work",
                                },
                                "url": "https://app.payfit.com/absences/new",
                            }
                        ]
                    }
                ]
            )

        time.sleep(60 * 60)


if __name__ == "__main__":
    main()
