import re

from destiny_brain.fillers import FILLERS, FillerPicker


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
    assert "_" in p._history
