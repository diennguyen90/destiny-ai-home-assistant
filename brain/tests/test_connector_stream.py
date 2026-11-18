import importlib.util

_spec = importlib.util.spec_from_file_location("stream_client", "/connector/stream_client.py")
sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc)

D1 = b'{"type":"delta","text":"Hi"}\n'
END = b'{"type":"end","speech":"Hi","conversation_id":"c","continue_conversation":false}\n'


def test_lost_line_verbatim():
    assert sc.LOST_LINE == " Sorry, I lost my train of thought."


def test_split_chunks():
    raw = D1 + END
    chunks = [raw[:5], raw[5:40], raw[40:]]
    out = list(sc.parse_ndjson_lines(chunks))
    assert [e["type"] for e in out] == ["delta", "end"]
    assert out[0]["text"] == "Hi"


def test_multiple_events_per_chunk():
    out = list(sc.parse_ndjson_lines([D1 + D1 + END]))
    assert len(out) == 3


def test_garbled_and_blank_skipped():
    out = list(sc.parse_ndjson_lines([b"\n\nnot json\n[1,2]\n" + D1 + b'{"nope":1}\n' + END]))
    assert [e["type"] for e in out] == ["delta", "end"]


def test_trailing_line_without_newline_flushed():
    out = list(sc.parse_ndjson_lines([D1, END.rstrip(b"\n")]))
    assert [e["type"] for e in out] == ["delta", "end"]


def test_multibyte_split_across_chunks():
    raw = '{"type":"delta","text":"é🌟"}\n'.encode()
    out = list(sc.parse_ndjson_lines([raw[:20], raw[20:]]))
    assert out[0]["text"] == "é🌟"


def test_missing_end_reported():
    events = list(sc.parse_ndjson_lines([D1]))
    assert not sc.has_end(events)
    assert sc.has_end(list(sc.parse_ndjson_lines([D1, END])))


def test_decoder_incremental():
    d = sc.NdjsonDecoder()
    assert d.feed(D1[:10]) == []
    assert d.feed(D1[10:])[0]["text"] == "Hi"
    assert d.flush() == []
