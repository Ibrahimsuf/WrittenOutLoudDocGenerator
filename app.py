from __future__ import print_function

import os
import io
import json
from flask import Flask, render_template, request, flash
from google.oauth2 import service_account
from googleapiclient.discovery import build
from PyPDF2 import PdfReader
from rapidfuzz import fuzz
import logging
import traceback



# -------------------------
# Configuration constants
# -------------------------

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]

SERVICE_ACCOUNT_FILE = "service_account.json"
TEMPLATE_DOC_ID = "18csyiB4l_olvLnW_5wlOHYpZh-9LJFlGcU0r6dbpOBk"

# -------------------------
# App factory
# -------------------------

def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev_secret_key")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)
    # -------------------------
    # Helpers (close over config)
    # -------------------------

    def get_service_account_creds():
        return service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE,
            scopes=SCOPES,
        )

    def find_placeholder_index(service, document_id, placeholder):
        doc = service.documents().get(documentId=document_id).execute()
        content = doc.get("body", {}).get("content", [])

        for element in content:
            if "paragraph" not in element:
                continue

            for elem in element["paragraph"].get("elements", []):
                text = elem.get("textRun", {}).get("content", "")
                if placeholder in text:
                    start = elem.get("startIndex", 0) + text.index(placeholder)
                    end = start + len(placeholder)
                    return start, end

        raise ValueError(f"Placeholder '{placeholder}' not found")

    def find_text_page_in_pdf(drive_service, document_id, search_text):
        request = drive_service.files().export_media(
            fileId=document_id,
            mimeType="application/pdf",
        )
        pdf_content = request.execute()

        reader = PdfReader(io.BytesIO(pdf_content))

        for page_num, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if search_text in " ".join(text.split()):
                return page_num

        return None

    def fill_template(data):
        creds = get_service_account_creds()
        docs_service = build("docs", "v1", credentials=creds)
        drive_service = build("drive", "v3", credentials=creds)

        storyteller_names = [n.strip().title() for n in data["storyteller_names"]]
        name_bios = list(zip(storyteller_names, data.get("author_bios", [])))
        name_bios.sort(key=lambda x: x[0])

        storyteller_names = [n for n, _ in name_bios]
        data["author_bios"] = [b for _, b in name_bios]

        replacements = {
            "{{title}}": data["title"],
            "{{teacher_name}}": data["teacher_name"],
            "{{storyteller_names}}": ", ".join(storyteller_names),
            "{{dedication}}": data["dedication"],
            "{{author_bios}}": "\n".join(data.get("author_bios", [])),
            "{{chapter_titles}}": "\n".join(data["chapter_titles"]),
            "{{page_numbers}}": "Calculating page numbers...",
        }

        final_copy = (
            drive_service.files()
            .copy(
                fileId=TEMPLATE_DOC_ID,
                body={"name": data["title"]},
                supportsAllDrives=True,
            )
            .execute()
        )

        document_id = final_copy["id"]

        docs_service.documents().batchUpdate(
            documentId=document_id,
            body={
                "requests": [
                    {
                        "replaceAllText": {
                            "containsText": {"text": k, "matchCase": True},
                            "replaceText": v,
                        }
                    }
                    for k, v in replacements.items()
                ]
            },
        ).execute()

        start, end = find_placeholder_index(
            docs_service,
            document_id,
            "{{chapter_body}}",
        )

        requests = [
            {
                "deleteContentRange": {
                    "range": {"startIndex": start, "endIndex": end}
                }
            }
        ]

        index = start

        for i, (title, text) in enumerate(
            zip(data["chapter_titles"], data["chapter_texts"])
        ):
            if i > 0:
                requests.append({"insertPageBreak": {"location": {"index": index}}})
                index += 1

            title_text = f"{title.upper()}\n"
            body_text = f"{text}\n\n"

            requests.extend([
                {"insertText": {"location": {"index": index}, "text": title_text}},
                {
                    "updateParagraphStyle": {
                        "range": {
                            "startIndex": index,
                            "endIndex": index + len(title_text),
                        },
                        "paragraphStyle": {"alignment": "CENTER"},
                        "fields": "alignment",
                    }
                },
            ])

            index += len(title_text)

            requests.extend([
                {"insertText": {"location": {"index": index}, "text": body_text}},
                {
                    "updateParagraphStyle": {
                        "range": {
                            "startIndex": index,
                            "endIndex": index + len(body_text),
                        },
                        "paragraphStyle": {"alignment": "JUSTIFIED"},
                        "fields": "alignment",
                    }
                },
            ])

            index += len(body_text)

        docs_service.documents().batchUpdate(
            documentId=document_id,
            body={"requests": requests},
        ).execute()

        print(f"✅ Created: https://docs.google.com/document/d/{document_id}/edit")

        return document_id

    # -------------------------
    # Routes
    # -------------------------

    @app.route("/", methods=["GET", "POST"])
    def index():
        defaults = {}

        if request.method == "POST":
            logger.info("Received form data keys: %s", list(form.keys()))
            form = request.form.to_dict(flat=False)

            data = {
                "title": form.get("title", [""])[0].strip(),
                "storyteller_names": [
                    s.strip() for s in form.get("storyteller_name", []) if s.strip()
                ],
                "author_bios": [
                    s.strip()
                    for s in form.get("storyteller_description", [])
                    if s.strip()
                ],
                "teacher_name": form.get("teacher_name", [""])[0].strip(),
                "dedication": form.get("dedication", [""])[0].strip(),
                "chapter_titles": [
                    s.strip() for s in form.get("chapter_title", []) if s.strip()
                ],
                "chapter_texts": [
                    s.strip() for s in form.get("chapter_text", []) if s.strip()
                ],
            }

            try:
                doc_id = fill_template(data)

                creds = get_service_account_creds()
                drive = build("drive", "v3", credentials=creds)
                drive.permissions().create(
                    fileId=doc_id,
                    body={"type": "anyone", "role": "reader"},
                    supportsAllDrives=True,
                ).execute()

                return render_template(
                    "result.html",
                    doc_url=f"https://docs.google.com/document/d/{doc_id}/edit",
                )

            except Exception as e:
                logger.exception("Error creating document")
                flash("Error creating document. See server logs for details.", "danger")

        return render_template("index.html", defaults=defaults)

    @app.route("/health")
    def health():
        return "ok", 200

    return app

if __name__ == "__main__":
    create_app().run(debug=True, host="127.0.0.1", port=5000)
