from karaoke.metadata import TrackMeta, parse_folder_name, resolve_metadata


def test_parse_folder_name_basic():
    m = parse_folder_name("Radiohead - Creep")
    assert m.artist == "Radiohead"
    assert m.title == "Creep"


def test_parse_folder_name_extra_dashes():
    m = parse_folder_name("Sufjan Stevens - Should Have Known - Demo")
    assert m.artist == "Sufjan Stevens"
    assert m.title == "Should Have Known - Demo"


def test_parse_folder_name_no_separator():
    m = parse_folder_name("MysteryTrack")
    assert m.artist is None
    assert m.title == "MysteryTrack"


def test_resolve_prefers_override_then_folder():
    folder = TrackMeta(artist="FolderArtist", title="FolderTitle")
    r = resolve_metadata(TrackMeta("Over", "Ride"), tags=None, folder=folder)
    assert (r.artist, r.title) == ("Over", "Ride")
    r = resolve_metadata(None, tags=TrackMeta("TagA", "TagT"), folder=folder)
    assert (r.artist, r.title) == ("TagA", "TagT")
    r = resolve_metadata(None, tags=None, folder=folder)
    assert (r.artist, r.title) == ("FolderArtist", "FolderTitle")


def test_resolve_fills_missing_fields_across_sources():
    r = resolve_metadata(TrackMeta(None, "OTitle"),
                         tags=TrackMeta("TagArtist", "TagTitle"),
                         folder=None)
    assert r.title == "OTitle"
    assert r.artist == "TagArtist"
