"""S18: ISBN из примера промпта не может получить статус verified."""

from datetime import date

from karkas.agent.skills.S18_source_verification.run import verify_source


def test_prompt_example_isbn_is_unverified() -> None:
    src = {
        "ref": "SRC-05",
        "section": "additional",
        "citation": "Лутц М. Изучаем Python. 5-е изд. — СПб.: Питер, 2024. — ISBN 978-5-4461-1234-0.",
        "isbn": "978-5-4461-1234-0",
    }
    out = verify_source(src, None, date(2026, 10, 19))
    assert out["status"] == "unverified"
    assert "пример" in out["evidence"]["reason"]
