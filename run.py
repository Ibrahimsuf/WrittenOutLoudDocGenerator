from google.oauth2 import service_account
from googleapiclient.discovery import build

SERVICE_ACCOUNT_FILE = 'service_account.json'
SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/documents'
]

# Authenticate
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)

drive_service = build('drive', 'v3', credentials=credentials)
docs_service = build('docs', 'v1', credentials=credentials)

SHARED_DRIVE_ID = '0AE0YZ4clOzQ7Uk9PVA'

# Step 1: Create the Google Doc in the shared drive
file_metadata = {
    'name': 'New Document',
    'mimeType': 'application/vnd.google-apps.document',
    'parents': [SHARED_DRIVE_ID]
}

doc_file = drive_service.files().create(
    body=file_metadata,
    supportsAllDrives=True,
    fields='id, name, webViewLink'
).execute()

doc_id = doc_file['id']
print(f"Created document: {doc_file['name']} (ID: {doc_id})")

# Step 2: Add content to the document
requests = [
    {
        'insertText': {
            'location': {'index': 1},
            'text': 'Hello from the service account! This text is added programmatically.'
        }
    }
]

docs_service.documents().batchUpdate(
    documentId=doc_id,
    body={'requests': requests}
).execute()

print(f"Added content to document ID: {doc_id}")

# Step 3: Make the document viewable by anyone with the link
permission = {
    'type': 'anyone',
    'role': 'reader'
}

drive_service.permissions().create(
    fileId=doc_id,
    body=permission,
    fields='id',
    supportsAllDrives=True
).execute()

# Step 4: Get the shareable link
doc_file = drive_service.files().get(
    fileId=doc_id,
    fields='webViewLink',
    supportsAllDrives=True
).execute()

print(f"Document is now viewable by anyone with the link: {doc_file['webViewLink']}")
