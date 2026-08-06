from karaoke.reconcile import reconcile, AsrWord, _norm


def approx(a, b, tol=1e-6):
    return abs(a - b) < tol


def test_norm_lowercases_and_strips_punct_keeps_apostrophe():
    assert _norm("Hey,") == "hey"
    assert _norm("can't") == "can't"
    assert _norm("Mental-Pack") == "mentalpack"
    assert _norm("(No") == "no"


def test_all_matched_uses_asr_times():
    known = ["hello", "world"]
    asr = [AsrWord("Hello", 1.0, 1.5), AsrWord("world!", 1.5, 2.2)]
    assert reconcile(known, asr) == [(1.0, 1.5), (1.5, 2.2)]


def test_interpolates_missing_interior_word():
    known = ["hello", "brave", "world"]          # ASR missed "brave"
    asr = [AsrWord("hello", 0.0, 1.0), AsrWord("world", 3.0, 4.0)]
    out = reconcile(known, asr)
    assert out[0] == (0.0, 1.0)
    assert out[2] == (3.0, 4.0)
    assert out[1] == (1.0, 3.0)                  # one word spans the whole gap


def test_interpolates_two_missing_interior_words_evenly():
    known = ["a", "x", "y", "b"]
    asr = [AsrWord("a", 0.0, 1.0), AsrWord("b", 5.0, 6.0)]
    out = reconcile(known, asr)
    assert out[1] == (1.0, 3.0) and out[2] == (3.0, 5.0)   # 4s gap split in two


def test_leading_and_trailing_gaps():
    known = ["intro", "hello", "outro"]
    asr = [AsrWord("hello", 5.0, 5.5)]
    out = reconcile(known, asr)
    assert approx(out[0][1], 5.0) and approx(out[0][0], 5.0 - 0.35)  # ends at anchor
    assert out[1] == (5.0, 5.5)
    assert approx(out[2][0], 5.5) and approx(out[2][1], 5.85)        # starts at anchor end


def test_no_asr_lays_out_sequentially():
    out = reconcile(["a", "b"], [])
    assert approx(out[0][0], 0.0) and approx(out[0][1], 0.35)
    assert approx(out[1][0], 0.35) and approx(out[1][1], 0.70)


def test_repeated_phrase_anchors_in_order():
    known = ["na", "na", "na", "na"]
    asr = [AsrWord("na", 1.0, 1.2), AsrWord("na", 2.0, 2.2),
           AsrWord("na", 3.0, 3.2), AsrWord("na", 4.0, 4.2)]
    out = reconcile(known, asr)
    assert [s for s, _ in out] == [1.0, 2.0, 3.0, 4.0]


# --- bounds enforcement: no collapsed or absurdly long words ---
from karaoke.reconcile import _MIN_WORD, _MAX_WORD


def _monotonic_nonoverlapping(out):
    return all(out[i][1] <= out[i + 1][0] + 1e-9 for i in range(len(out) - 1))


def test_zero_gap_interior_run_is_not_collapsed():
    # anchors touch (b starts exactly when a ends) -> interior x,y had no budget
    known = ["a", "x", "y", "b"]
    asr = [AsrWord("a", 0.0, 1.0), AsrWord("b", 1.0, 2.0)]
    out = reconcile(known, asr)
    assert all(e - s >= _MIN_WORD - 1e-9 for s, e in out)   # nothing collapses
    assert _monotonic_nonoverlapping(out)


def test_overlong_matched_word_is_capped():
    known = ["ah"]
    asr = [AsrWord("ah", 10.0, 30.0)]                       # 20s held scream
    out = reconcile(known, asr)
    assert out[0][0] == 10.0
    assert approx(out[0][1], 10.0 + _MAX_WORD)              # fill capped, then holds


def test_anchor_count_counts_matched_known_words():
    from karaoke.reconcile import anchor_count
    known = ["hello", "brave", "new", "world"]
    asr = [AsrWord("hello", 0.0, 1.0), AsrWord("world", 3.0, 4.0)]
    assert anchor_count(known, asr) == 2          # hello + world match
    assert anchor_count(known, []) == 0


def test_interior_gap_shared_by_word_length():
    # "I" (1 char) and "cat" (3) share a 4s gap -> 1s and 3s, not 2s each
    known = ["a", "I", "cat", "b"]
    asr = [AsrWord("a", 0.0, 1.0), AsrWord("b", 5.0, 6.0)]
    out = reconcile(known, asr)
    assert out[1] == (1.0, 2.0)   # I: 4 * 1/4
    assert out[2] == (2.0, 5.0)   # cat: 4 * 3/4


def test_normal_durations_are_left_alone():
    known = ["a", "b"]
    asr = [AsrWord("a", 0.0, 2.0), AsrWord("b", 2.0, 5.0)]  # both within [min, max]
    out = reconcile(known, asr)
    assert out == [(0.0, 2.0), (2.0, 5.0)]
