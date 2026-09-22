#!/usr/bin/env python3
"""Automated end-to-end browser test for KubeStellar Console.

Tests:
1. Console availability at http://127.0.0.1:8080/
2. Automated login flow (Cluster Access / GitHub OAuth / Dev Mode / Token Login)
3. Dashboard navigation and DOM rendering of live cluster resources (rejecting demo mode)
4. Kiosk gate overlay and kc-agent interaction on port 8585
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.request
from typing import Any

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="KubeStellar Console automated browser verification")
    parser.add_argument(
        "--console-url",
        default="http://127.0.0.1:8080",
        help="Base URL of KubeStellar console (default: http://127.0.0.1:8080)",
    )
    parser.add_argument(
        "--agent-url",
        default="http://127.0.0.1:8585",
        help="Base URL of kc-agent (default: http://127.0.0.1:8585)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Max timeout in seconds to wait for console readiness (default: 60)",
    )
    parser.add_argument(
        "--cluster-telemetry-timeout",
        type=int,
        default=CLUSTER_TELEMETRY_TIMEOUT,
        help=(
            "Max timeout in seconds to wait for live cluster resources to render "
            f"(default: {CLUSTER_TELEMETRY_TIMEOUT}); upstream populates cluster health "
            "asynchronously after boot"
        ),
    )
    return parser.parse_args()

def wait_for_http_ready(url: str, timeout: int, check_healthz: bool = True) -> bool:
    print(f"==> Waiting for {url} to be ready (timeout: {timeout}s)...")
    start = time.time()
    endpoint = f"{url.rstrip('/')}/healthz" if check_healthz else f"{url.rstrip('/')}/health"
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(endpoint, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, context=ctx, timeout=2) as resp:
                if resp.status == 200:
                    print(f"==> Endpoint {endpoint} is ready!")
                    return True
        except Exception:
            # Fall back to root URL check if healthz endpoint is not implemented
            try:
                root_req = urllib.request.Request(url.rstrip('/'), headers={"Accept": "text/html"})
                with urllib.request.urlopen(root_req, context=ctx, timeout=2) as resp:
                    if resp.status in (200, 302, 301):
                        print(f"==> Root URL {url} is ready (HTTP {resp.status})!")
                        return True
            except Exception:
                pass
            time.sleep(1)
    return False


# Upstream synthetic demo fixtures injected by the console demo data
# (pkg/api/handlers/demo_data.go GetDemoClusters).
DEMO_CLUSTER_NAMES = (
    "kind-local",
    "minikube",
    "k3s-edge",
    "eks-prod-us-east-1",
    "gke-staging",
    "aks-dev-westeu",
    "openshift-prod",
    "oci-oke-phoenix",
    "alibaba-ack-shanghai",
    "do-nyc1-prod",
    "rancher-mgmt",
    "vllm-gpu-cluster",
)

# Console routes that render one DOM element per discovered cluster, paired
# with the selector that only exists once a cluster was actually returned by
# the API. Static card containers and their headings are deliberately excluded:
# they render with empty data and would let the gate pass without any
# discovered cluster.
#   /clusters  -> ClusterGrid renders SortableClusterItem with
#                 data-testid="cluster-row-${cluster.name}"
#                 (web/src/components/clusters/components/ClusterDragReorder.tsx)
#   /workloads -> Clusters Overview grid renders one
#                 data-testid="cluster-card" per cluster
#                 (web/src/components/workloads/Workloads.parts.tsx)
# The dashboard landing page has no such per-cluster testid, so these pages
# must be visited explicitly for the DOM verification to mean anything.
CLUSTER_RESOURCE_PAGES = (
    ("/clusters", "[data-testid^='cluster-row-']"),
    ("/workloads", "[data-testid='cluster-card']"),
)

# Live control-plane / in-cluster identifiers that never appear in demo data.
LIVE_CLUSTER_TEXT_MARKERS = ("its1", "wds1", "in-cluster")

# Default budget for live cluster resources to render. Upstream ListClusters
# returns clusters with HealthUnknown and fills health in asynchronously after
# boot, so a short budget flakes on an otherwise healthy install. Override with
# --cluster-telemetry-timeout.
CLUSTER_TELEMETRY_TIMEOUT = 120


def assert_no_demo_fixtures(driver: webdriver.Chrome) -> None:
    """Fail if the rendered page contains upstream synthetic demo cluster fixtures."""
    page_text = driver.find_element(By.TAG_NAME, "body").text
    for demo_name in DEMO_CLUSTER_NAMES:
        if demo_name in page_text:
            raise AssertionError(
                f"Detected synthetic demo cluster '{demo_name}' in console DOM; demo mode was not rejected!"
            )


def verify_live_cluster_resources(
    driver: webdriver.Chrome,
    console_url: str,
    timeout: int = CLUSTER_TELEMETRY_TIMEOUT,
) -> None:
    """Verify that actual Kubernetes cluster resources are discovered and rendered in the DOM,
    ensuring unconfigured demo placeholders or synthetic dev mode do not pass silently.
    """
    print("==> Verifying live cluster resources are rendered in the DOM (rejecting demo mode)...")

    # 1. Reject synthetic demo mode flag in localStorage if explicitly active
    try:
        demo_mode_flag = driver.execute_script("return window.localStorage.getItem('kc-demo-mode')")
    except WebDriverException as exc:
        print(f"==> Warning: could not read kc-demo-mode from localStorage: {exc}")
    else:
        if demo_mode_flag == "true":
            raise AssertionError("Console is running in synthetic demo mode (kc-demo-mode=true in localStorage)")

    # 2. Visit each cluster-listing route and wait for a real per-cluster
    #    element (or live cluster identifiers), re-checking for demo fixtures on
    #    every pass so late-rendered async demo content cannot slip through a
    #    single early scan.
    base_url = console_url.rstrip("/")
    start = time.time()
    found_resource = False
    while not found_resource and time.time() - start < timeout:
        for route, selector in CLUSTER_RESOURCE_PAGES:
            driver.get(f"{base_url}{route}")
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))

            assert_no_demo_fixtures(driver)

            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            if elements and any(el.is_displayed() for el in elements):
                found_resource = True
                print(f"==> Found live cluster resource element on {route}: {selector}")
                break

            body_text = driver.find_element(By.TAG_NAME, "body").text
            if any(term in body_text for term in LIVE_CLUSTER_TEXT_MARKERS):
                if "No clusters connected" not in body_text:
                    found_resource = True
                    print(f"==> Discovered live cluster workload indicators in {route} DOM text.")
                    break

        if not found_resource:
            time.sleep(2)

    if not found_resource:
        raise AssertionError(
            f"Timed out after {timeout}s waiting for live Kubernetes cluster resources "
            f"(per-cluster rows or cards on {', '.join(route for route, _ in CLUSTER_RESOURCE_PAGES)}, "
            "or initialized ControlPlanes) to be rendered in the DOM."
        )

    # 3. Final demo scan after the async content settled.
    assert_no_demo_fixtures(driver)

    print("==> Live cluster workload DOM rendering verified successfully!")


def run_browser_verification(
    console_url: str,
    agent_url: str,
    cluster_telemetry_timeout: int = CLUSTER_TELEMETRY_TIMEOUT,
) -> None:
    chrome_opts = Options()
    chrome_opts.add_argument("--headless=new")
    chrome_opts.add_argument("--no-sandbox")
    chrome_opts.add_argument("--disable-dev-shm-usage")
    chrome_opts.add_argument("--disable-gpu")
    chrome_opts.add_argument("--ignore-certificate-errors")

    driver = webdriver.Chrome(options=chrome_opts)
    try:
        print(f"==> Navigating to {console_url}/...")
        driver.get(console_url)

        # 1. Wait for page body to load
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        current_url = driver.current_url
        print(f"==> Current URL: {current_url}, Title: {driver.title}")

        # Check for cluster access, dev login, or OAuth buttons
        access_selectors = [
            "[data-testid='cluster-access-button']",
            "[data-testid='dev-login-button']",
            "button.login-button",
            "button.access-button",
            "a.login-button",
        ]
        login_buttons = []
        for sel in access_selectors:
            login_buttons.extend(driver.find_elements(By.CSS_SELECTOR, sel))

        if not login_buttons:
            login_buttons = driver.find_elements(
                By.XPATH,
                "//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'cluster access') or "
                "contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'sign in') or "
                "contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'login') or "
                "contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'continue')]",
            )

        if login_buttons:
            print("==> Found login/access button. Triggering automated click...")
            login_buttons[0].click()
            time.sleep(2)

        # 2. Wait for main UI / navigation / dashboard container
        print("==> Verifying console dashboard UI rendering...")
        WebDriverWait(driver, 15).until(
            lambda d: d.find_elements(By.TAG_NAME, "nav")
            or d.find_elements(By.TAG_NAME, "main")
            or d.find_elements(By.ID, "root")
            or "KubeStellar" in d.title
        )
        print(f"==> Successfully verified console UI! Page title: {driver.title}")

        # 3. Verify actual Kubernetes cluster resources are rendered (rejecting demo mode)
        verify_live_cluster_resources(driver, console_url, timeout=cluster_telemetry_timeout)

        # 4. Check kiosk gate behavior on the landing page again, since the
        #    cluster verification navigated away to the cluster listing routes.
        driver.get(console_url)
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        gate_elements = driver.find_elements(By.ID, "kubestellar-kiosk-gate")
        agent_healthy = False
        try:
            with urllib.request.urlopen(f"{agent_url.rstrip('/')}/health", timeout=1) as resp:
                if resp.status == 200:
                    agent_healthy = True
        except Exception:
            agent_healthy = False

        if agent_healthy:
            print("==> kc-agent is healthy: verifying gate overlay is dismissed.")
            assert len(gate_elements) == 0 or not gate_elements[0].is_displayed(), (
                "Gate overlay should be dismissed when kc-agent is healthy!"
            )
        else:
            print(f"==> kc-agent is not running on {agent_url} (or inactive). Gate status checked.")

        print("==> All browser automated end-to-end checks passed!")
    finally:
        driver.quit()


def main() -> None:
    args = parse_args()
    if not wait_for_http_ready(args.console_url, timeout=args.timeout, check_healthz=True):
        print(f"ERROR: Timed out waiting for console at {args.console_url}", file=sys.stderr)
        sys.exit(1)

    run_browser_verification(
        args.console_url,
        args.agent_url,
        cluster_telemetry_timeout=args.cluster_telemetry_timeout,
    )


if __name__ == "__main__":
    main()
