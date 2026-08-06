from karaoke.lyrics import parse_lyrics


def test_parse_drops_blank_lines_and_section_headers():
    raw = "[Verse 1]\nHello there\n\n  world  \n[Chorus]\nLa la la\n"
    assert parse_lyrics(raw) == ["Hello there", "world", "La la la"]


def test_parse_empty_returns_empty():
    assert parse_lyrics("\n\n  \n") == []


def test_parse_strips_standalone_dashes_keeps_hyphens_and_parens():
    raw = "Hey - we want our violence doubled (No but really in a loving way)\n" \
          "You mental-pack the boil-in-bag\n" \
          "-\n"
    out = parse_lyrics(raw)
    assert out[0] == "Hey we want our violence doubled (No but really in a loving way)"
    assert out[1] == "You mental-pack the boil-in-bag"   # internal hyphens kept
    assert len(out) == 2                                  # the lone "-" line dropped
