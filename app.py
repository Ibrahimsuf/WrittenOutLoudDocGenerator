from __future__ import print_function
import os
import io
from flask import Flask, render_template, request, flash
from google.oauth2 import service_account
from googleapiclient.discovery import build
from PyPDF2 import PdfReader
from rapidfuzz import fuzz
import json

# --- Config ---
SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]
SERVICE_ACCOUNT_FILE = "service_account.json"
TEMPLATE_DOC_ID = "18csyiB4l_olvLnW_5wlOHYpZh-9LJFlGcU0r6dbpOBk"
OUTPUT_NAME = "Filled_Story_Document"

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev_secret_key")

def get_service_account_creds():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    return creds

def find_placeholder_index(service, document_id, placeholder):
    """Find start and end indices of a placeholder string in the doc."""
    doc = service.documents().get(documentId=document_id).execute()
    content = doc.get("body", {}).get("content", [])
    for element in content:
        if "paragraph" not in element:
            continue
        for elem in element["paragraph"].get("elements", []):
            text_run = elem.get("textRun", {})
            text = text_run.get("content", "")
            if placeholder in text:
                start = elem.get("startIndex", 0) + text.index(placeholder)
                end = start + len(placeholder)
                return start, end
    raise ValueError(f"Placeholder '{placeholder}' not found in document.")


def find_text_page_in_pdf(drive_service, document_id, search_text):
    """Export doc as PDF and find which page the text appears on."""
    # Export the document as PDF
    request = drive_service.files().export_media(
        fileId=document_id,
        mimeType='application/pdf'
    )
    pdf_content = request.execute()

    # Read the PDF content
    pdf_file = io.BytesIO(pdf_content)
    pdf_reader = PdfReader(pdf_file)

    # Search through each page
    for page_num, page in enumerate(pdf_reader.pages, start=1):
        text = page.extract_text() or ""
        normalized_text = ' '.join(text.split())
        if search_text in normalized_text:
            return page_num
    return None


def get_all_chapter_pages(drive_service, document_id, chapter_titles):
    """Get page numbers for all chapters."""
    chapter_pages = {}

    for title in chapter_titles:
        page_num = find_text_page_in_pdf(drive_service, document_id, title.upper())
        chapter_pages[title] = page_num

    return chapter_pages


def delete_document(drive_service, document_id):
    """Delete a document by moving it to trash."""
    try:
        drive_service.files().delete(fileId=document_id, supportsAllDrives=True).execute()
        print(f"🗑️  Deleted temporary document: {document_id}")
    except Exception as e:
        print(f"⚠️  Could not delete temporary document: {e}")


def fill_template(data):
    """Core logic: create temp copy, fill, compute page numbers, create final copy.

    Returns (final_document_id, chapter_pages)
    """
    creds = get_service_account_creds()
    docs_service = build("docs", "v1", credentials=creds)
    drive_service = build("drive", "v3", credentials=creds)

    # Step 1: Create TEMPORARY document to get page numbers
    print("📝 Creating temporary document to calculate page numbers...")
    temp_copy = (
        drive_service.files()
        .copy(fileId=TEMPLATE_DOC_ID, body={"name": f"{OUTPUT_NAME}_TEMP"}, supportsAllDrives=True)
        .execute()
    )
    temp_document_id = temp_copy.get("id")

    # Step 2: Fill temporary document with content (without page numbers)
    storyteller_names = [name.strip().title() for name in data["storyteller_names"]]
    # sort storyteller names alphabetically and do with author bios as well
    name_bios = [(name, bio) for name, bio in zip(storyteller_names, data.get("author_bios", []))]
    name_bios.sort(key=lambda x: x[0])
    storyteller_names = [nb[0] for nb in name_bios]
    data["author_bios"] = [nb[1] for nb in name_bios]
    replacements = {
        "{{title}}": data["title"],
        "{{teacher_name}}": data["teacher_name"],
        "{{storyteller_names}}": ", ".join(storyteller_names),
        "{{dedication}}": data["dedication"],
        "{{author_bios}}": "\n".join(data.get("author_bios", [])),
        "{{chapter_titles}}": "\n".join([title for idx, title in enumerate(data["chapter_titles"]) ]),
        "{{page_numbers}}": "Calculating page numbers...",  # Temporary placeholder
    }

    requests = [
        {
            "replaceAllText": {
                "containsText": {"text": key, "matchCase": True},
                "replaceText": value,
            }
        }
        for key, value in replacements.items()
    ]

    docs_service.documents().batchUpdate(
        documentId=temp_document_id, body={"requests": requests}
    ).execute()

    # Handle chapter body insertion
    insert_index = find_placeholder_index(docs_service, temp_document_id, "{{chapter_body}}")
    requests = []

    requests.append({
        "deleteContentRange": {
            "range": {"startIndex": insert_index[0], "endIndex": insert_index[1]}
        }
    })

    location_index = insert_index[0]

    for i, (title, text) in enumerate(zip(data["chapter_titles"], data["chapter_texts"])):
        title_text = f"{title.upper()}\n"
        body_text = f"{text}\n\n"

        if i > 0:
            requests.append({
                "insertPageBreak": {"location": {"index": location_index}}
            })
            location_index += 1

        requests.append({
            "insertText": {"location": {"index": location_index}, "text": title_text}
        })
        title_start = location_index
        title_end = title_start + len(title_text)
        location_index = title_end

        requests.append({
            "updateParagraphStyle": {
                "range": {"startIndex": title_start, "endIndex": title_end},
                "paragraphStyle": {"alignment": "CENTER"},
                "fields": "alignment"
            }
        })

        requests.append({
            "insertText": {"location": {"index": location_index}, "text": body_text}
        })
        body_start = location_index
        body_end = body_start + len(body_text)
        location_index = body_end

        requests.append({
            "updateParagraphStyle": {
                "range": {"startIndex": body_start, "endIndex": body_end},
                "paragraphStyle": {"alignment": "JUSTIFIED"},
                "fields": "alignment"
            }
        })

    docs_service.documents().batchUpdate(
        documentId=temp_document_id, body={"requests": requests}
    ).execute()

    # Step 3: Get page numbers from temporary document
    print("📄 Finding page numbers for chapters...")
    chapter_pages = get_all_chapter_pages(drive_service, temp_document_id, data["chapter_titles"])

    print("\n📖 Chapter Page Numbers:")
    for title, page_num in chapter_pages.items():
        if page_num:
            print(f"  • {title}: Page {page_num}")
        else:
            print(f"  • {title}: Not found")

    # Step 4: Format page numbers string
    page_numbers_text = "\n".join([
        str(page_num) if page_num is not None else "Not found"
        for page_num in chapter_pages.values()
    ])

    # Step 5: Delete temporary document
    delete_document(drive_service, temp_document_id)

    # Step 6: Create FINAL document with actual page numbers
    print("\n📝 Creating final document with page numbers...")
    final_copy = (
        drive_service.files()
        .copy(fileId=TEMPLATE_DOC_ID, body={"name": OUTPUT_NAME}, supportsAllDrives=True)
        .execute()
    )
    final_document_id = final_copy.get("id")

    # Update replacements with actual page numbers
    replacements["{{page_numbers}}"] = page_numbers_text

    requests = [
        {
            "replaceAllText": {
                "containsText": {"text": key, "matchCase": True},
                "replaceText": value,
            }
        }
        for key, value in replacements.items()
    ]

    docs_service.documents().batchUpdate(
        documentId=final_document_id, body={"requests": requests}
    ).execute()

    # Handle chapter body insertion for final document
    insert_index = find_placeholder_index(docs_service, final_document_id, "{{chapter_body}}")
    requests = []

    requests.append({
        "deleteContentRange": {
            "range": {"startIndex": insert_index[0], "endIndex": insert_index[1]}
        }
    })

    location_index = insert_index[0]

    for i, (title, text) in enumerate(zip(data["chapter_titles"], data["chapter_texts"])):
        title_text = f"{title.upper()}\n"
        body_text = f"{text}\n\n"

        if i > 0:
            requests.append({
                "insertPageBreak": {"location": {"index": location_index}}
            })
            location_index += 1

        requests.append({
            "insertText": {"location": {"index": location_index}, "text": title_text}
        })
        title_start = location_index
        title_end = title_start + len(title_text)
        location_index = title_end

        requests.append({
            "updateParagraphStyle": {
                "range": {"startIndex": title_start, "endIndex": title_end},
                "paragraphStyle": {"alignment": "CENTER"},
                "fields": "alignment"
            }
        })

        requests.append({
            "insertText": {"location": {"index": location_index}, "text": body_text}
        })
        body_start = location_index
        body_end = body_start + len(body_text)
        location_index = body_end

        requests.append({
            "updateParagraphStyle": {
                "range": {"startIndex": body_start, "endIndex": body_end},
                "paragraphStyle": {"alignment": "JUSTIFIED"},
                "fields": "alignment"
            }
        })

    docs_service.documents().batchUpdate(
        documentId=final_document_id, body={"requests": requests}
    ).execute()

    print(f"\n✅ Final document created: https://docs.google.com/document/d/{final_document_id}/edit")

    return final_document_id, chapter_pages


@app.route("/", methods=["GET", "POST"])
def index():
    defaults = {}
    if request.method == "POST":
        form_data = request.form.to_dict(flat=False)
        title = form_data.get("title", [""])[0].strip()
        storyteller_names = [s.strip() for s in form_data.get("storyteller_name", []) if s.strip()]
        author_bios = [s.strip() for s in form_data.get("storyteller_description", []) if s.strip()]
        teacher_name = form_data.get("teacher_name", [""])[0].strip()
        dedication = form_data.get("dedication", [""])[0].strip()
        chapter_titles = [s.strip() for s in form_data.get("chapter_title", []) if s.strip()]
        chapter_texts = [s.strip() for s in form_data.get("chapter_text", []) if s.strip()]

        data = {
            "title": title,
            "storyteller_names": storyteller_names,
            "teacher_name": teacher_name,
            "dedication": dedication,
            "chapter_titles": chapter_titles,
            "chapter_texts": chapter_texts,
            "author_bios": author_bios,
        }

        try:
            doc_id, chapter_pages = fill_template(data)
            # share with anyone with the link
            creds = get_service_account_creds()
            drive_service = build("drive", "v3", credentials=creds)
            drive_service.permissions().create(
                fileId=doc_id,
                body={"type": "anyone", "role": "reader"},
                supportsAllDrives=True,
            ).execute()
            return render_template("result.html", doc_url=f"https://docs.google.com/document/d/{doc_id}/edit", chapter_pages=chapter_pages)
        except Exception as e:
            flash(f"Error creating document: {e}", "danger")
            return render_template("index.html", defaults=defaults)

    return render_template("index.html", defaults=defaults)

@app.route("/health")
def health():
    return "ok", 200

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
