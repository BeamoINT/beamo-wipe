"""Current boot guidance must match the Windows manual restart route."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_print_boot_card_says_windows_uses_manual_restart():
    card = (ROOT / "docs/boot-card.md").read_text(encoding="utf-8")
    assert "On Windows, save your work, use the normal Restart command" in card
    assert "choose this USB from the boot menu" in card
    assert "Approve\nthe operating system's permission prompt" not in card


def test_shipped_helper_separates_windows_and_linux_restart_routes():
    english = (ROOT / "helper/index.html").read_text(encoding="utf-8")
    french = (ROOT / "helper/fr.html").read_text(encoding="utf-8")
    german = (ROOT / "helper/de.html").read_text(encoding="utf-8")
    assert "On Windows, save your work and use Restart" in english
    assert "On supported Linux desktops, a guided restart may be offered" in english
    assert "Sous Windows, enregistrez votre travail et utilisez Redémarrer" in french
    assert "Unter Windows speichern Sie Ihre Arbeit und verwenden Neu starten" in german
