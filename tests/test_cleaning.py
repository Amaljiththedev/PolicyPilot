from app.api.ingestion.cleaning import strip_boilerplate

FOOTER = "Your University – Handbook for Undergraduate Students /{} /"


def test_repeated_footer_removed_content_kept():
    pages = [f"Real content about topic {i}.\n{FOOTER.format(20 + i)}" for i in range(5)]
    cleaned, stats = strip_boilerplate("\n\n".join(pages))
    assert "Handbook for Undergraduate Students" not in cleaned
    assert "Real content about topic 3." in cleaned
    assert stats["removed_footer_lines"] == 5


def test_bare_page_numbers_removed():
    cleaned, stats = strip_boilerplate("Intro paragraph.\n12\nMore text.\n- 13 -\nEnd.")
    assert cleaned.split("\n") == ["Intro paragraph.", "More text.", "End."]
    assert stats["removed_page_numbers"] == 2


def test_line_seen_only_twice_is_kept():
    text = "Call 2222 in an emergency.\nOther.\nCall 2222 in an emergency."
    cleaned, _ = strip_boilerplate(text)
    assert cleaned.count("Call 2222") == 2


def test_numbers_inside_sentences_kept():
    cleaned, _ = strip_boilerplate("The TV licence costs £169.50 and the fine is up to £1,000.")
    assert "£169.50" in cleaned


def test_numbered_content_lines_kept():
    # degree classification table: starts with numbers, repeats a few times, is real content
    table = "70 to 100: First class\n60 to 69: Upper second class\n"
    cleaned, stats = strip_boilerplate((table + "Other text.\n") * 3)
    assert cleaned.count("First class") == 3
    assert stats["removed_footer_lines"] == 0
