from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIALOG = ROOT / "apps" / "desktop" / "src" / "components" / "WorkstationSetupDialog.tsx"


def test_complete_status_notifies_parent_only_once() -> None:
    source = DIALOG.read_text(encoding="utf-8")
    effect_start = source.index('if (status?.setup.status !== "COMPLETE")')
    effect_end = source.index("async function beginSetup", effect_start)
    completion_effect = source[effect_start:effect_end]

    assert "const completionNotified = useRef(false);" in source
    assert "completionNotified.current = false;" in completion_effect
    assert "if (completionNotified.current) return;" in completion_effect
    assert "completionNotified.current = true;" in completion_effect
    assert completion_effect.count("onInstalled();") == 1
