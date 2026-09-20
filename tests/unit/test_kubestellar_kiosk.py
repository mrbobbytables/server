"""Contracts for the KubeStellar kiosk proxy and authenticated agent gate."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
KIOSK = ROOT / "files" / "k0s" / "kiosk"
KIOSK_CONF = KIOSK / "nginx.conf"
KIOSK_JS = KIOSK / "kiosk-gate.js"
KIOSK_CSS = KIOSK / "kiosk-gate.css"
TMPFILES = ROOT / "files" / "k0s" / "sysext" / "k0s-manifests.conf"
SYSEXT = ROOT / "elements" / "oci" / "k0s-sysext.bst"
CONSOLE_MANIFEST = (
    ROOT
    / "files"
    / "k0s"
    / "manifests"
    / "kubestellar"
    / "40-kubestellar-console.yaml"
)
PROXY_MANIFEST = (
    ROOT
    / "files"
    / "k0s"
    / "manifests"
    / "kubestellar"
    / "41-kubestellar-kiosk-proxy.yaml"
)


def test_kiosk_assets_are_packaged_and_seeded() -> None:
    sysext = SYSEXT.read_text(encoding="utf-8")
    tmpfiles = TMPFILES.read_text(encoding="utf-8")

    assert KIOSK_CONF.is_file()
    assert KIOSK_JS.is_file()
    assert KIOSK_CSS.is_file()
    assert "freedesktop-sdk.bst:components/openssl.bst" in sysext
    assert "keyout sysext/usr/share/k0s/kiosk/key.pem" in sysext
    assert "path: files/k0s/kiosk" in sysext
    assert "directory: kiosk-src" in sysext
    assert "cp -a kiosk-src/. sysext/usr/share/k0s/kiosk/" in sysext
    assert "C+ /var/lib/k0s/kiosk - - - - /usr/share/k0s/kiosk" in tmpfiles


def test_proxy_injects_only_csp_safe_same_origin_assets() -> None:
    nginx = KIOSK_CONF.read_text(encoding="utf-8")

    assert (
        "proxy_pass "
        "http://kubestellar-console.kubestellar-console.svc.cluster.local:8080;"
    ) in nginx
    assert "proxy_redirect" in nginx
    assert 'proxy_set_header Accept-Encoding "";' in nginx
    assert "sub_filter_types" not in nginx
    assert (
        'sub_filter \'</head>\' '
        '\'<link rel="stylesheet" href="/kiosk-gate.css">'
        '<script src="/kiosk-gate.js"></script></head>\';'
    ) in nginx
    assert "<script defer" not in nginx
    assert "'</body>'" not in nginx
    assert "Content-Security-Policy" not in nginx


def test_gate_waits_for_session_and_blocks_until_agent_health() -> None:
    script = KIOSK_JS.read_text(encoding="utf-8")
    css = KIOSK_CSS.read_text(encoding="utf-8")

    assert "kc-has-session" in script
    assert "http://127.0.0.1:8585/health" in script
    assert "brew tap kubestellar/tap && brew install kc-agent" in script
    assert (
        'KAGENTI_CONTROLLER_URL="none" kc-agent -allowed-origins'
        " ${window.location.origin}"
    ) in script
    assert "aria-modal" in script
    assert "addEventListener('keydown'" in script
    assert "pointer-events: auto" in css
    assert "z-index: 2147483647" in css


def test_console_provides_local_and_oauth_login_options() -> None:
    console = CONSOLE_MANIFEST.read_text(encoding="utf-8")

    assert "name: DEV_MODE" in console
    assert 'value: "true"' in console
    assert "name: ALLOW_DEV_MODE_IN_CLUSTER" in console
    assert "hostPort:" not in console
    assert "name: GITHUB_CLIENT_ID" in console
    assert "name: GITHUB_CLIENT_SECRET" in console
    assert "name: kubestellar-console-github-oauth" in console
    assert "key: client-id" in console
    assert "key: client-secret" in console
    assert "optional: true" in console


def test_proxy_is_the_only_public_console_endpoint() -> None:
    proxy = PROXY_MANIFEST.read_text(encoding="utf-8")

    assert "name: kubestellar-kiosk-proxy" in proxy
    assert "hostPort: 8080" in proxy
    assert "mountPath: /etc/kubestellar-kiosk" in proxy
    assert "hostPath:\n          path: /var/lib/k0s/kiosk" in proxy
    assert "readOnly: true" in proxy
    assert (
        "nginx@sha256:62223d644fa234c3a1cc785ee14242ec47a77364226f1c811d2f669f96dc2ac8"
        in proxy
    )


def test_kiosk_gate_mitigates_dashboard_rate_limiting() -> None:
    script = KIOSK_JS.read_text(encoding="utf-8")

    assert "isApiRequest" in script
    assert "Retry-After" in script
    assert "429" in script
    assert "INITIAL_BACKOFF_MS = 500" in script
    assert "BACKOFF_FACTOR = 2" in script
    assert "MAX_RETRIES = 4" in script
    assert "STAGGER_INTERVAL_MS = 75" in script
    assert "MAX_RETRY_DELAY_MS = 30_000" in script
    assert "staggerRequest" in script
    assert "parseRetryAfter" in script
    assert "clampDelay" in script
    assert "DOMContentLoaded" in script


@pytest.mark.skipif(shutil.which("node") is None, reason="node not found")
def test_kiosk_gate_fetch_interceptor_behavior() -> None:
    node_test_script = f"""
const fs = require('fs');
const vm = require('vm');

const kioskCode = fs.readFileSync({json.dumps(str(KIOSK_JS))}, 'utf8');

function setupSandbox(mockFetch) {{
  const sandbox = {{
    window: {{
      location: {{ origin: 'http://localhost:8080' }},
      localStorage: {{ getItem: () => null }},
      setInterval: () => {{}},
    }},
    document: {{
      getElementById: () => null,
      addEventListener: () => {{}},
      body: {{ insertAdjacentHTML: () => {{}} }},
    }},
    setTimeout,
    clearTimeout,
    Date,
    URL,
    DOMException,
    console,
  }};
  sandbox.window.fetch = mockFetch;
  sandbox.window.window = sandbox.window;
  vm.runInNewContext(kioskCode, sandbox);
  return sandbox;
}}

(async () => {{
  // 1. Non-API pass through
  let nonApiCalled = false;
  const s1 = setupSandbox(async () => {{
    nonApiCalled = true;
    return {{ status: 200, ok: true }};
  }});
  const res1 = await s1.window.fetch('http://127.0.0.1:8585/health');
  if (!nonApiCalled || res1.status !== 200) throw new Error('Non-API pass-through failed');

  // 2. 429 retry with Retry-After header
  let flakyAttempts = 0;
  const s2 = setupSandbox(async () => {{
    flakyAttempts++;
    if (flakyAttempts <= 2) {{
      return {{
        status: 429,
        headers: {{ get: (k) => k.toLowerCase() === 'retry-after' ? '0.05' : null }}
      }};
    }}
    return {{ status: 200, ok: true, data: 'hydrated' }};
  }});
  const res2 = await s2.window.fetch('/api/mcp/clusters');
  if (res2.status !== 200 || flakyAttempts !== 3) {{
    throw new Error(`Expected 3 attempts and 200 OK, got ${{flakyAttempts}} attempts and status ${{res2.status}}`);
  }}

  // 3. Staggering burst requests
  const start = Date.now();
  const dispatchTimes = [];
  const s3 = setupSandbox(async () => {{
    dispatchTimes.push(Date.now() - start);
    return {{ status: 200, ok: true }};
  }});
  await Promise.all([
    s3.window.fetch('/api/mcp/clusters'),
    s3.window.fetch('/api/mcp/services'),
    s3.window.fetch('/api/kagent/status'),
  ]);
  if (dispatchTimes.length !== 3) throw new Error('Expected 3 dispatch times');
  if (dispatchTimes[1] - dispatchTimes[0] < 50) throw new Error('First stagger interval too short');
  if (dispatchTimes[2] - dispatchTimes[1] < 50) throw new Error('Second stagger interval too short');

  // 4. Max retries exhaustion
  let always429Attempts = 0;
  const s4 = setupSandbox(async () => {{
    always429Attempts++;
    return {{
      status: 429,
      headers: {{ get: () => '0.01' }}
    }};
  }});
  const res4 = await s4.window.fetch('/api/stellar/state');
  if (res4.status !== 429 || always429Attempts !== 5) {{
    throw new Error(`Expected 5 attempts and status 429, got ${{always429Attempts}} attempts and ${{res4.status}}`);
  }}

  // 5. AbortSignal cancellation
  const s5 = setupSandbox(async () => ({{ status: 200, ok: true }}));
  const controller = new AbortController();
  controller.abort();
  try {{
    await s5.window.fetch('/api/test', {{ signal: controller.signal }});
    throw new Error('Should have aborted');
  }} catch (err) {{
    if (err.name !== 'AbortError') throw err;
  }}

  // 6. Retry-After is clamped to a sane maximum
  const exportsSandbox = {{
    window: {{
      location: {{ origin: 'http://localhost:8080' }},
      localStorage: {{ getItem: () => null }},
      setInterval: () => {{}},
      fetch: async () => ({{ status: 200, ok: true }}),
    }},
    document: {{
      getElementById: () => null,
      addEventListener: () => {{}},
      body: {{ insertAdjacentHTML: () => {{}} }},
    }},
    module: {{ exports: {{}} }},
    setTimeout,
    clearTimeout,
    Date,
    URL,
    DOMException,
    console,
  }};
  exportsSandbox.window.window = exportsSandbox.window;
  vm.runInNewContext(kioskCode, exportsSandbox);
  const api = exportsSandbox.module.exports;
  const hugeDelay = api.parseRetryAfter({{ headers: {{ get: () => '600' }} }});
  if (hugeDelay !== api.MAX_RETRY_DELAY_MS) {{
    throw new Error(`Retry-After not clamped: got ${{hugeDelay}}`);
  }}
  const pastDate = api.parseRetryAfter({{
    headers: {{ get: () => new Date(Date.now() - 60000).toUTCString() }},
  }});
  if (pastDate !== 0) throw new Error(`Past Retry-After should be 0, got ${{pastDate}}`);
  const farDate = api.parseRetryAfter({{
    headers: {{ get: () => new Date(Date.now() + 3600000).toUTCString() }},
  }});
  if (farDate !== api.MAX_RETRY_DELAY_MS) {{
    throw new Error(`Far Retry-After not clamped: got ${{farDate}}`);
  }}

  // 7. Interceptor installs synchronously, before document.body exists
  let patchedBeforeBody = null;
  const headSandbox = {{
    window: {{
      location: {{ origin: 'http://localhost:8080' }},
      localStorage: {{ getItem: () => null }},
      setInterval: () => {{ throw new Error('gate loop started before DOM ready'); }},
      fetch: async () => ({{ status: 200, ok: true }}),
    }},
    document: {{
      readyState: 'loading',
      body: null,
      getElementById: () => null,
      addEventListener: (type) => {{
        if (type === 'DOMContentLoaded') patchedBeforeBody = true;
      }},
    }},
    setTimeout,
    clearTimeout,
    Date,
    URL,
    DOMException,
    console,
  }};
  const preInstallFetch = headSandbox.window.fetch;
  headSandbox.window.window = headSandbox.window;
  vm.runInNewContext(kioskCode, headSandbox);
  if (headSandbox.window.fetch === preInstallFetch) {{
    throw new Error('fetch was not patched at script evaluation time');
  }}
  if (patchedBeforeBody !== true) {{
    throw new Error('gate loop was not deferred to DOMContentLoaded');
  }}

  console.log('ALL_KIOSK_GATE_TESTS_PASSED');
}})().catch(err => {{
  console.error(err);
  process.exit(1);
}});
"""
    result = subprocess.run(
        ["node", "-e", node_test_script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"Node test failed:\n{result.stderr}\n{result.stdout}"
    assert "ALL_KIOSK_GATE_TESTS_PASSED" in result.stdout
