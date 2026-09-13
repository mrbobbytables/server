"""Contracts for the kc-agent launcher and setup-kubestellar recipe."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JUSTFILE = ROOT / "Justfile"
LAUNCHER = ROOT / "files" / "bin" / "bluefin-kubestellar"
KC_AGENT_FORMULA = ROOT / "Formula" / "kc-agent.rb"
BLUEFIN_FORMULA = ROOT / "Formula" / "bluefin-kubestellar.rb"


def test_setup_kubestellar_recipe_contract() -> None:
    justfile = JUSTFILE.read_text(encoding="utf-8")

    assert "setup-kubestellar ORIGIN=" in justfile
    start = justfile.index("setup-kubestellar ORIGIN=")
    recipe = justfile[start:]

    assert "./files/bin/bluefin-kubestellar --origin \"{{ORIGIN}}\"" in recipe
    before_lines = [line.strip() for line in justfile[:start].splitlines() if line.strip()]
    assert "[group('dev')]" in before_lines[-1] or "[group('dev')]" in before_lines[-2]



def test_bluefin_kubestellar_launcher_script_contract() -> None:
    assert LAUNCHER.is_file()
    script = LAUNCHER.read_text(encoding="utf-8")

    assert script.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in script
    assert "KAGENTI_CONTROLLER_URL" in script
    assert "KC_ALLOWED_ORIGINS" in script
    assert "brew tap kubestellar/tap" in script
    assert "brew install kc-agent" in script
    assert "/health" in script


def test_homebrew_formulas_contract() -> None:
    assert KC_AGENT_FORMULA.is_file()
    assert BLUEFIN_FORMULA.is_file()

    kc_agent = KC_AGENT_FORMULA.read_text(encoding="utf-8")
    bluefin = BLUEFIN_FORMULA.read_text(encoding="utf-8")

    # kc-agent formula verifies client environment optimization & background service
    assert "class KcAgent < Formula" in kc_agent
    assert "KAGENTI_CONTROLLER_URL" in kc_agent
    assert "service do" in kc_agent
    assert "bluefin-kubestellar" in kc_agent

    # bluefin-kubestellar formula provides service & launcher
    assert "class BluefinKubestellar < Formula" in bluefin
    assert "service do" in bluefin
    assert "KAGENTI_CONTROLLER_URL" in bluefin
