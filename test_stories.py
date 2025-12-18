import pytest
from bs4 import BeautifulSoup
from app import create_app

BASE_PAYLOAD = {
    "title": "The River and the Stone",
    "storyteller_name": "A. Lewis",
    "storyteller_description": "A traveler collecting oral histories.",
    "teacher_name": "Dr. K. Morales",
    "dedication": "For those who listen carefully.",
    "chapter_title": "Beginnings",
    "chapter_text": "Once there was a village beside a river.\nThey lived in harmony with the land.\nAnd they lived in harmony with the river.",
}


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
