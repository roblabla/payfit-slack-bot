from datetime import date, datetime, timedelta
import time
import requests
from slack_sdk.webhook import WebhookClient
import os
#from slack_sdk.models import *

PAYFIT_URL = "https://api.payfit.com/"
PAYFIT_EMPLOYEES_ENDPOINT = f"{PAYFIT_URL}hr/employees"
PAYFIT_ABSENCES_ENDPOINT = f"{PAYFIT_URL}hr/employee-request/absences"
PAYFIT_REFRESH_ENDPOINT = f"{PAYFIT_URL}auth/accessToken"

SLACK_WEBHOOK = os.environ['SLACK_WEBHOOK']
ACCESS_TOKEN = os.environ['PAYFIT_ACCESS_TOKEN']
REFRESH_TOKEN = os.environ['PAYFIT_REFRESH_TOKEN']

THRESHOLD = 25

def get_new_token(access_token: str, refresh_token: str):
    cookies = dict(accessToken=access_token, refreshToken=refresh_token)
    return requests.post(PAYFIT_REFRESH_ENDPOINT, cookies=cookies).json()

def get_absences(access_token: str):
    cookies = dict(accessToken=access_token)
    return requests.post(PAYFIT_ABSENCES_ENDPOINT, cookies=cookies).json()

def get_employees(access_token: str):
    cookies = dict(accessToken=access_token)
    return requests.post(PAYFIT_EMPLOYEES_ENDPOINT, cookies=cookies).json()

def main():
    access_token = ACCESS_TOKEN
    refresh_token = REFRESH_TOKEN
    webhook = WebhookClient(SLACK_WEBHOOK)

    while True:
        data = get_new_token(access_token, refresh_token)
        access_token = data['accessToken']
        refresh_token = data['refreshToken']

        # TODO: save in sqlite or something.

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

        # Generate graph. It looks like this: each line has 28 cells.
        # Each cell can either be a square emoji or two spaces:
        # 🟩: Office work below ceil
        # 🟪: Office work over ceil
        # ⬜: Remote work/absentees.
        graphmsg = f"{num_present}/{THRESHOLD}\n"
        graphmsg += "```\n"

        below_ceil = min(num_present, THRESHOLD)
        above_ceil = max(num_present - THRESHOLD, 0)
        graph = "🟩" * below_ceil
        graph += "🟪" * above_ceil
        graph += "⬜" * len(absents)

        curchar = 0
        for i in range(len(employees)):
            if i % 28 == 0 and i != 0:
                graph = graph[:curchar] + "\n" + graph[curchar:]
                curchar += 1
            if graph[curchar] == " ":
                curchar += 2
            else:
                curchar += 1


        graphmsg += graph
        graphmsg += "\n```\n\n"
        graphmsg += "🟩: Office work under threshold\n"
        graphmsg += "🟪: Office work over threshold\n"
        graphmsg += "⬜: Remote work/absentee\n"


        print(f"There are {num_present} people at work.")

        if len(presents) >= THRESHOLD:
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
