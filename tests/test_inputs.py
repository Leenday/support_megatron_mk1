import json

import pytest

from megatron.inputs import RequestFileError, load_requests


def test_text_file_one_request_per_line(tmp_path):
    path = tmp_path / "requests.txt"
    path.write_text("# comment\nпринтер не печатает\n\n  VPN drops  \n", encoding="utf-8")
    assert [r.text for r in load_requests(path)] == ["принтер не печатает", "VPN drops"]


def test_jsonl_keeps_multi_line_text_and_labels(tmp_path):
    path = tmp_path / "requests.jsonl"
    rows = [
        {"id": 7, "text": "Не доставляется СМС\n\nПопытки:\n402255223", "expected": "network"},
        {"text": "VPN drops", "queue": "ignored extra key"},
    ]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n\n")
    first, second = load_requests(path)
    assert first.text == rows[0]["text"]
    assert (first.id, first.expected) == (7, "network")
    assert (second.id, second.expected) == (None, None)


@pytest.mark.parametrize("line", ['{"text": ""}', '{"body": "no text key"}', "not json"])
def test_bad_jsonl_line_names_the_line(tmp_path, line):
    path = tmp_path / "requests.jsonl"
    path.write_text('{"text": "ok"}\n' + line + "\n", encoding="utf-8")
    with pytest.raises(RequestFileError, match=r"requests\.jsonl:2"):
        load_requests(path)
