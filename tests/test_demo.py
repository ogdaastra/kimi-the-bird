"""The end-to-end visitor-note demonstration (mocked Haiku, no credits)."""

from kimi.demo import run_demo


def test_demo_runs_end_to_end(tmp_path):
    lines: list[str] = []
    code = run_demo(live=False, data_dir=tmp_path / "demo", out=lines.append)
    text = "\n".join(lines)
    assert code == 0, text
    for step in range(1, 8):
        assert f"Step {step}:" in text
    assert "Detected note #1 from Alice" in text
    assert "<visitor_note id=\"1\" from=\"Alice\"" in text
    assert "read_note" in text and "completed" in text
    assert "Shrine board - Kimi:" in text
    assert "After restart Kimi still remembers" in text
