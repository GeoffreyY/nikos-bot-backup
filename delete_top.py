import sys
from googleapiclient.discovery import build
from httplib2 import Http
from oauth2client import file as oafile, client as oaclient, tools as oatools

if len(sys.argv) == 2:
    rows = int(sys.argv[1])
else:
    rows = 1

SPREADSHEET_ID = '1-uwntIJDqMCnOUmvomK-5EqUnzHup2rABLBbhcotmZM'
SPREADSHEET_SCOPES = 'https://www.googleapis.com/auth/spreadsheets'
SPREADSHEET_CREDENTIALS_FILE = 'google/credentials.json'
SPREADSHEET_SECRETS_FILE = 'google/client_secret.json'

spreadsheet_store = oafile.Storage(SPREADSHEET_CREDENTIALS_FILE)
spreadsheet_creds = spreadsheet_store.get()
if not spreadsheet_creds or spreadsheet_creds.invalid:
    flow = oaclient.flow_from_clientsecrets(
        SPREADSHEET_SECRETS_FILE, SPREADSHEET_SCOPES)
    spreadsheet_creds = oatools.run_flow(flow, spreadsheet_store)
spreadsheet_service = build(
    'sheets', 'v4', http=spreadsheet_creds.authorize(Http()))

delete_row_body = {"requests": [{"deleteDimension": {
    "range": {
        "sheetId": 25658793,
        "dimension": "ROWS",
        "startIndex": 1,
        "endIndex": 1+rows
    }
}}, ], }

result = spreadsheet_service.spreadsheets().batchUpdate(
    spreadsheetId=SPREADSHEET_ID, body=delete_row_body).execute()
print(result)
