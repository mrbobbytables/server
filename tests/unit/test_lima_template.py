from pathlib import Path
import shutil
import subprocess
import yaml

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_PATH = ROOT / ".github" / "scripts" / "bluefin-lima-template.yaml"


def test_lima_template_exists_and_parses():
    assert TEMPLATE_PATH.is_file(), "bluefin-lima-template.yaml missing"
    data = yaml.safe_load(TEMPLATE_PATH.read_text())
    assert isinstance(data, dict)


def test_lima_template_schema():
    data = yaml.safe_load(TEMPLATE_PATH.read_text())

    # base must extend template:_images/ubuntu-24.04
    assert "base" in data, "field 'base' must be set"
    assert "template:_images/ubuntu-24.04" in data["base"]

    # nested virtualization must use nestedVirtualization: true
    assert data.get("nestedVirtualization") is True
    assert "nested" not in data, "legacy 'nested' field must not be present"

    # vmType and arch must configure nested-virt QEMU
    assert data.get("vmType") == "qemu"
    assert data.get("arch") == "x86_64"

    # ssh section must not contain unknown field localShell
    if "ssh" in data:
        assert "localShell" not in data["ssh"]

    # containerd must not contain unknown field guest
    if "containerd" in data:
        assert "guest" not in data["containerd"]
        assert data["containerd"].get("system") is False

    # name should not be present in template schema
    assert "name" not in data


def test_lima_template_validation_if_limactl_available():
    limactl = shutil.which("limactl")
    if not limactl:
        return
    res = subprocess.run(
        [limactl, "validate", str(TEMPLATE_PATH)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"limactl validate failed:\n{res.stderr}\n{res.stdout}"
