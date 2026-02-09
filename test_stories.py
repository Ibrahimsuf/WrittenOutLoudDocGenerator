import pytest
from bs4 import BeautifulSoup
from app import create_app, convert_html_to_requests
import json


BASE_PAYLOAD = {
    "title": "The River and the Stone",
    "storyteller_name": "A. Lewis",
    "storyteller_description": "A traveler collecting oral histories.",
    "teacher_name": "Dr. K. Morales",
    "dedication": "For those who listen carefully.",
    "chapter_title": "Beginnings",
    "chapter_text": (
        "Once there was a village beside a river.\n\rThey lived in harmony with the land.\n\r And they lived in harmony with the river.\n"
    ),
}

PAYLOAD_DOUBLE_NEWLINE = {
        "title": "Drift Test",
        "storyteller_name": ["Alice", "Bob"],
        "storyteller_description": ["Bio Alice", "Bio Bob"],
        "teacher_name": "Prof X",
        "dedication": "To all readers",
        "chapter_title": ["One", "Two", "Three", "Four", "Five"],
        "chapter_text": [
            "This is normal text.\n\n\u200b\u200b\u200bHidden zero-width spaces included.\nEnd of chapter.",
            "Text 2"*1000,
            "Text 3"*1000,
            "Text 4"*1000,
            "Text 5"*1000,
        ],
    }

CONTROL_CHAR_STRINGS = [
    "null\x00byte",
    "bell\x07sound",
    "back\x08space",
    "escape\x1b[31mRED\x1b[0m",
    "carriage\rreturn",
    "line\nbreak",
    "tab\tchar",
    "unit\x1fseparator",
    "zero\u200bwidth\u200cjoiner",
]

@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["PROPAGATE_EXCEPTIONS"] = True
    return app.test_client()


def extract_doc_link(response):
    soup = BeautifulSoup(response.data, "html.parser")
    link = soup.find(
        "a",
        class_="btn btn-success",
        string="Open Document in Google Docs",
    )
    doc_url = link["href"] if link else None
    if doc_url:
        print(f"Generated doc URL: {doc_url}")
    return doc_url


def test_basic_post(client):
    response = client.post(
        "/",
        data=BASE_PAYLOAD,
        content_type="application/x-www-form-urlencoded",
    )
    assert response.status_code == 200
    doc_url = extract_doc_link(response)
    assert doc_url is not None
    assert doc_url.startswith("https://docs.google.com")
def test_carriage_return(client):
    with open("input2.json", "r") as f:
        payload = json.load(f)
    response = client.post(
        "/",
        data=payload,
        content_type="application/x-www-form-urlencoded",
    )
    assert response.status_code == 200
    doc_url = extract_doc_link(response)
    assert doc_url is not None
    assert doc_url.startswith("https://docs.google.com")
def test_inserting_after_end_bug(client):
    with open("input3.json", "r") as f:
        payload = json.load(f)
    response = client.post(
        "/",
        data=payload,
        content_type="application/x-www-form-urlencoded",
    )
    assert response.status_code == 200
    doc_url = extract_doc_link(response)
    assert doc_url is not None
    assert doc_url.startswith("https://docs.google.com")
def test_double_newline_paragraphs(client):
    response = client.post(
        "/",
        data=PAYLOAD_DOUBLE_NEWLINE,
        content_type="application/x-www-form-urlencoded",
    )
    assert response.status_code == 200
    doc_url = extract_doc_link(response)
    assert doc_url is not None
    assert doc_url.startswith("https://docs.google.com")
@pytest.mark.parametrize(
    "payload",
    [
        # trailing whitespace
        {**BASE_PAYLOAD, "title": "  Leading and trailing  "},
        # special characters
        {**BASE_PAYLOAD, "storyteller_name": "Élise O'Connor & Sons <Test>"},
        # empty strings
        {**BASE_PAYLOAD, "chapter_text": ""},
        # very long text
        {**BASE_PAYLOAD, "chapter_text": "Lorem ipsum " * 1000},
    ],
)
def test_edge_cases(client, payload):
    response = client.post(
        "/",
        data=payload,
        content_type="application/x-www-form-urlencoded",
    )
    assert response.status_code == 200
    doc_url = extract_doc_link(response)
    assert doc_url is not None
    assert doc_url.startswith("https://docs.google.com")


@pytest.mark.parametrize("control_str", CONTROL_CHAR_STRINGS)
@pytest.mark.parametrize(
    "field",
    [
        "title",
        "storyteller_name",
        "storyteller_description",
        "teacher_name",
        "dedication",
        "chapter_title",
        "chapter_text",
    ],
)
def test_control_characters(client, field, control_str):
    payload = {**BASE_PAYLOAD, field: f"prefix-{control_str}-suffix"}

    response = client.post(
        "/",
        data=payload,
        content_type="application/x-www-form-urlencoded",
    )

    assert response.status_code == 200
    doc_url = extract_doc_link(response)
    assert doc_url is not None
    assert doc_url.startswith("https://docs.google.com")


def test_html_escaping(client):
    payload = {**BASE_PAYLOAD, "chapter_text": "<script>alert('xss')</script>"}
    response = client.post(
        "/",
        data=payload,
        content_type="application/x-www-form-urlencoded",
    )
    assert response.status_code == 200
    doc_url = extract_doc_link(response)
    assert doc_url is not None
    assert doc_url.startswith("https://docs.google.com")

def test_less_bios_than_authors(client):
    payload = BASE_PAYLOAD
    payload["storyteller_name"] = ["Author 1", "Author 2", "Author 3"]
    payload["storyteller_description"] = ["Bio 1", "Bio 2"]
    response = client.post(
        "/",
        data=payload,
        content_type="application/x-www-form-urlencoded",
    )
    assert response.status_code == 200
    doc_url = extract_doc_link(response)
    assert doc_url is not None
    assert doc_url.startswith("https://docs.google.com")


def test_html_to_requests():
    app = create_app()
    requests = convert_html_to_requests(0, '<p>This text is <strong>bold. </strong>This is in <em>italics. </em>This is <em>underlined</em></p>')
    expected_result = ([{'insertText': {'location': {'index': 0}, 'text': 'This text is '}}, {'updateTextStyle': {'range': {'startIndex': 0, 'endIndex': 13}, 'textStyle': {'bold': False, 'italic': False, 'underline': False}, 'fields': 'bold,italic,underline'}}, {'insertText': {'location': {'index': 13}, 'text': 'bold. '}}, {'updateTextStyle': {'range': {'startIndex': 13, 'endIndex': 19}, 'textStyle': {'bold': True, 'italic': False, 'underline': False}, 'fields': 'bold,italic,underline'}}, {'insertText': {'location': {'index': 19}, 'text': 'This is in '}}, {'updateTextStyle': {'range': {'startIndex': 19, 'endIndex': 30}, 'textStyle': {'bold': False, 'italic': False, 'underline': False}, 'fields': 'bold,italic,underline'}}, {'insertText': {'location': {'index': 30}, 'text': 'italics. '}}, {'updateTextStyle': {'range': {'startIndex': 30, 'endIndex': 39}, 'textStyle': {'bold': False, 'italic': True, 'underline': False}, 'fields': 'bold,italic,underline'}}, {'insertText': {'location': {'index': 39}, 'text': 'This is '}}, {'updateTextStyle': {'range': {'startIndex': 39, 'endIndex': 47}, 'textStyle': {'bold': False, 'italic': False, 'underline': False}, 'fields': 'bold,italic,underline'}}, {'insertText': {'location': {'index': 47}, 'text': 'underlined'}}, {'updateTextStyle': {'range': {'startIndex': 47, 'endIndex': 57}, 'textStyle': {'bold': False, 'italic': True, 'underline': False}, 'fields': 'bold,italic,underline'}}, {'insertText': {'location': {'index': 57}, 'text': '\n'}}], 58)
    assert requests == expected_result

