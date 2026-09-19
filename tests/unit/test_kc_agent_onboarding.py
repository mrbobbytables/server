"""Contracts for automatic first-boot kc-agent and local k0s onboarding."""

from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
KC_SERVICE = ROOT / "files" / "k0s" / "sysext" / "kc-agent.service"
FIRST_BOOT_SERVICE = (
    ROOT / "files" / "os" / "systemd" / "system" / "k0s-first-boot.service"
)
JUSTFILE_SYS = ROOT / "files" / "os" / "justfile"
KC_INCLUDE = ROOT / "include" / "kc-agent.yml"
KC_BIN = ROOT / "elements" / "k0s" / "kc-agent-bin.bst"
SYSEXT = ROOT / "elements" / "oci" / "k0s-sysext.bst"


def test_kc_agent_version_and_element() -> None:
    assert KC_INCLUDE.is_file(), "include/kc-agent.yml missing"
    data = yaml.safe_load(KC_INCLUDE.read_text(encoding="utf-8"))
    version = data.get("variables", {}).get("kc-agent-version")
    assert version, "kc-agent-version variable missing"

    assert KC_BIN.is_file(), "elements/k0s/kc-agent-bin.bst missing"
    content = KC_BIN.read_text(encoding="utf-8")
    assert "(@): include/kc-agent.yml" in content
    assert "github:kubestellar/console/releases/download/v%{kc-agent-version}" in content
    assert "install -D -m 0755 kc-agent" in content


def test_kc_agent_service_contract() -> None:
    assert KC_SERVICE.is_file(), "kc-agent.service missing"
    text = KC_SERVICE.read_text(encoding="utf-8")
    assert "ConditionFileIsExecutable=/usr/bin/kc-agent" in text
    assert "-kubeconfig /var/lib/k0s/pki/admin.conf" in text
    assert "-allowed-origins http://localhost:8080,http://127.0.0.1:8080" in text
    assert "Environment=KAGENTI_CONTROLLER_URL=none" in text
    assert "After=network-online.target k0scontroller.service" in text
    assert "Wants=network-online.target" in text
    assert "Restart=always" in text
    assert "StateDirectory=kc-agent" in text


def test_sysext_packages_kc_agent_binary_and_service() -> None:
    sysext = SYSEXT.read_text(encoding="utf-8")
    assert "filename: k0s/kc-agent-bin.bst" in sysext
    assert "cp -a /usr/bin/kc-agent sysext/usr/bin/kc-agent" in sysext
    assert "chmod 0755 sysext/usr/bin/kc-agent" in sysext
    assert "cp -a sysext-src/kc-agent.service sysext/usr/lib/systemd/system/" in sysext


def test_first_boot_activates_kc_agent() -> None:
    service = FIRST_BOOT_SERVICE.read_text(encoding="utf-8")
    lines = [line.strip() for line in service.splitlines() if line.startswith("ExecStart")]
    assert "ExecStart=/usr/bin/systemctl enable --now k0scontroller.service" in lines
    assert "ExecStart=/usr/bin/systemctl enable --now kc-agent.service" in lines


def test_system_justfile_enables_kc_agent() -> None:
    justfile = JUSTFILE_SYS.read_text(encoding="utf-8")
    assert "systemctl enable --now k0scontroller.service" in justfile
    assert "systemctl enable --now kc-agent.service" in justfile
