from videoai.types import Segment, Transcript


def test_transcript_round_trip() -> None:
    transcript = Transcript("ja", (Segment(0, 1.5, "こんにちは"), Segment(1.5, 2, " 世界 ")))
    restored = Transcript.from_dict(transcript.to_dict())
    assert restored == transcript
    assert restored.text == "こんにちは 世界"
