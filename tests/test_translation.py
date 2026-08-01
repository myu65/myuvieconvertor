import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from videoai.backends import OpenAICompatibleTranslator
from videoai.errors import BackendError
from videoai.types import Segment, Transcript


class _Handler(BaseHTTPRequestHandler):
    translated: object = [{"id": 0, "text": "Hello"}, {"id": 1, "text": "world"}]

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        json.loads(self.rfile.read(length))
        content = json.dumps(self.translated)
        body = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


@pytest.fixture
def translation_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        thread.join()


def _transcript() -> Transcript:
    return Transcript("ja", (Segment(0, 1, "こんにちは"), Segment(1, 2, "世界")))


def test_openai_translation_preserves_segment_timing(
    translation_server: str, tmp_path: Path
) -> None:
    result = OpenAICompatibleTranslator(translation_server, "key", "model").translate(
        _transcript(), "en", tmp_path
    )
    assert result.language == "en"
    assert [item.text for item in result.segments] == ["Hello", "world"]
    assert [(item.start, item.end) for item in result.segments] == [(0, 1), (1, 2)]


def test_openai_translation_rejects_changed_ids(
    translation_server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        _Handler, "translated", [{"id": 0, "text": "Hello"}, {"id": 2, "text": "world"}]
    )
    with pytest.raises(BackendError):
        OpenAICompatibleTranslator(translation_server, "", "model").translate(
            _transcript(), "en", tmp_path
        )
