from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/drive"]
SERVICE_ACCOUNT_FILE = "service_account.json"

creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE,
    scopes=SCOPES,
)

service = build("drive", "v3", credentials=creds)


drives = []
page_token = None

while True:
    response = service.drives().list(
        pageSize=100,
        pageToken=page_token
    ).execute()

    drives.extend(response.get("drives", []))
    page_token = response.get("nextPageToken")
    if not page_token:
        break

for d in drives:
    print(f"{d['id']}  {d['name']}")
