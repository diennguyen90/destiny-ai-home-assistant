import re

from destiny_brain.fillers import FILLERS, WEB_FILLERS, FillerPicker


def test_filler_count_and_length():
    assert 16 <= len(FILLERS) <= 20
    assert len(set(FILLERS)) == len(FILLERS)
    for f in FILLERS:
        assert len(f) >= 61, f


def test_fillers_spoken_style():
    bad = re.compile(r"[*#_\[\]{}<>~]")
    for f in FILLERS:
        assert not bad.search(f), f
        assert all(ord(ch) < 0x2190 for ch in f), f


def test_no_repeat_in_last_five():
    p = FillerPicker()
    picks = [p.pick("d1") for _ in range(200)]
    for i, x in enumerate(picks):
        assert x not in picks[max(0, i - 5):i]


def test_devices_independent():
    collisions = 0
    for _ in range(400):
        p = FillerPicker()
        a = p.pick("a")
        collisions += p.pick("b") == a  # b has no history, so a's pick is allowed
    assert collisions > 0
    p = FillerPicker()
    assert p.pick(None) in FILLERS
    p.pick(None)
    assert ("_", "normal") in p._history


def test_web_fillers_rules():
    bad = re.compile(r"[*#_\[\]{}<>~]")
    assert 10 <= len(WEB_FILLERS) <= 14
    assert len(set(WEB_FILLERS)) == len(WEB_FILLERS)
    assert not set(WEB_FILLERS) & set(FILLERS)
    for f in WEB_FILLERS:
        assert len(f) >= 61, f
        assert not bad.search(f), f
        assert all(ord(ch) < 0x2190 for ch in f), f


def test_pick_kinds_independent():
    p = FillerPicker()
    picks = [p.pick("d1", "web") for _ in range(200)]
    for i, x in enumerate(picks):
        assert x in WEB_FILLERS
        assert x not in picks[max(0, i - 5):i]
    assert p.pick("d1") in FILLERS
    assert set(p._history) == {("d1", "web"), ("d1", "normal")}
    assert all(x in WEB_FILLERS for x in p._history[("d1", "web")])
    assert all(x in FILLERS for x in p._history[("d1", "normal")])
