from pathlib import Path


def test_prompt_build_managed_window_contract():
    root = Path(__file__).resolve().parents[2]
    js = (root / "src/nexuss/ui/p5.js").read_text(encoding="utf-8-sig")
    css = (root / "src/nexuss/ui/styles.css").read_text(encoding="utf-8-sig")

    for marker in (
        "engineering-progress-minimize",
        "engineering-progress-hide",
        "engineering-progress-restore",
        "engineeringProgressWindowState",
        "pointerdown",
        "pointermove",
        "nx-capability-dock",
    ):
        assert marker in js

    assert "#nx-capability-dock" in css
    assert "z-index: 4000 !important" in css
    assert ".engineering-progress-card.is-minimized" in css
