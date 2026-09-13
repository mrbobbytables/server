#!/usr/bin/env bats
#
# Unit tests for files/bin/bluefin-kubestellar launcher and manager.
#
# Tests run in a temporary sandbox where kc-agent, brew, curl, and kill
# are replaced by stubs on PATH to verify orchestration, arguments,
# and environment isolation.

setup() {
    REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
    SCRIPT="${REPO_ROOT}/files/bin/bluefin-kubestellar"
    SANDBOX="${BATS_TEST_TMPDIR}/sandbox"
    STUB_DIR="${BATS_TEST_TMPDIR}/bin"
    LOG="${BATS_TEST_TMPDIR}/calls.log"
    STATE_DIR="${SANDBOX}/state"

    mkdir -p "$STUB_DIR" "$STATE_DIR"
    : > "$LOG"

    # Default stubs
    make_curl_stub 1 # default health fails unless overridden
    make_kc_agent_stub 0
    make_brew_stub 0
}

make_kc_agent_stub() {
    cat > "${STUB_DIR}/kc-agent" <<EOF
#!/usr/bin/env bash
echo "kc-agent \$*" >> "${LOG}"
echo "ENV_KAGENTI=\${KAGENTI_CONTROLLER_URL:-unset}" >> "${LOG}"
echo "ENV_ORIGINS=\${KC_ALLOWED_ORIGINS:-unset}" >> "${LOG}"
# If running in background test, background stub can sleep briefly
if [ "\${TEST_KC_BACKGROUND:-0}" = "1" ]; then
    sleep 30 &
    echo \$!
else
    exit $1
fi
EOF
    chmod +x "${STUB_DIR}/kc-agent"
}

make_brew_stub() {
    cat > "${STUB_DIR}/brew" <<EOF
#!/usr/bin/env bash
echo "brew \$*" >> "${LOG}"
if [ "\${1:-}" = "install" ] && [ "\${2:-}" = "kc-agent" ]; then
    cat > "${STUB_DIR}/kc-agent" << 'INNER'
#!/usr/bin/env bash
echo "kc-agent \$*" >> "${LOG}"
exit 0
INNER
    chmod +x "${STUB_DIR}/kc-agent"
fi
exit $1
EOF
    chmod +x "${STUB_DIR}/brew"
}

make_curl_stub() {
    cat > "${STUB_DIR}/curl" <<EOF
#!/usr/bin/env bash
echo "curl \$*" >> "${LOG}"
if [ "\${TEST_CURL_HEALTHY:-0}" = "1" ]; then
    exit 0
else
    exit $1
fi
EOF
    chmod +x "${STUB_DIR}/curl"
}

run_launcher() {
    run env PATH="${STUB_DIR}:${PATH}" \
        XDG_STATE_HOME="${SANDBOX}" \
        bash "$SCRIPT" "$@"
}

assert_log() {
    if ! grep -qF -- "$1" "$LOG"; then
        echo "expected call log to contain: $1" >&2
        cat "$LOG" >&2
        return 1
    fi
}

refute_log() {
    if grep -qF -- "$1" "$LOG"; then
        echo "expected call log NOT to contain: $1" >&2
        cat "$LOG" >&2
        return 1
    fi
}

@test "script exists and is executable" {
    [ -f "$SCRIPT" ]
    [ -x "$SCRIPT" ]
}

@test "script enforces strict bash mode" {
    run head -n 15 "$SCRIPT"
    [ "$status" -eq 0 ]
    [[ "$output" == *"set -euo pipefail"* ]]
}

@test "help option displays usage" {
    run_launcher --help
    [ "$status" -eq 0 ]
    [[ "$output" == *"Usage:"* ]]
    [[ "$output" == *"--origin"* ]]
    [[ "$output" == *"start"* ]]
    [[ "$output" == *"stop"* ]]
    [[ "$output" == *"status"* ]]
}

@test "unknown argument fails with error" {
    run_launcher --invalid-flag
    [ "$status" -ne 0 ]
    [[ "$output" == *"ERROR: Unknown option or command"* ]]
}

@test "missing kc-agent triggers brew tap and install" {
    rm -f "${STUB_DIR}/kc-agent"
    TEST_CURL_HEALTHY=1 run_launcher --foreground
    assert_log "brew tap kubestellar/tap"
    assert_log "brew install kc-agent"
}

@test "missing kc-agent with --no-install aborts without brew" {
    rm -f "${STUB_DIR}/kc-agent"
    run_launcher --no-install --foreground
    [ "$status" -ne 0 ]
    [[ "$output" == *"ERROR: kc-agent is not installed"* ]]
    refute_log "brew "
}

@test "missing both kc-agent and brew reports helpful error" {
    rm -f "${STUB_DIR}/kc-agent"
    rm -f "${STUB_DIR}/brew"
    run_launcher --foreground
    [ "$status" -ne 0 ]
    [[ "$output" == *"ERROR: kc-agent is not installed and cannot be auto-installed"* ]]
}

@test "foreground launch optimizes client environment and configures origin" {
    run_launcher --foreground --origin "http://test-origin:8080"
    [ "$status" -eq 0 ]
    assert_log "ENV_KAGENTI=none"
    assert_log "ENV_ORIGINS=http://test-origin:8080"
    assert_log "-allowed-origins http://test-origin:8080"
}

@test "bare URL argument is parsed as origin" {
    run_launcher --foreground "http://custom-node:8080"
    [ "$status" -eq 0 ]
    assert_log "-allowed-origins http://custom-node:8080"
}

@test "start skips relaunch if already healthy on health port" {
    TEST_CURL_HEALTHY=1 run_launcher
    [ "$status" -eq 0 ]
    [[ "$output" == *"already running and healthy"* ]]
    refute_log "kc-agent "
}

@test "status reports healthy when endpoint responds" {
    TEST_CURL_HEALTHY=1 run_launcher status
    [ "$status" -eq 0 ]
    [[ "$output" == *"running and healthy"* ]]
}

@test "status reports not running when endpoint is unreachable" {
    TEST_CURL_HEALTHY=0 run_launcher status
    [ "$status" -eq 3 ]
    [[ "$output" == *"not running"* ]]
}

@test "stop terminates recorded PID and cleans pidfile" {
    PID_FILE="${SANDBOX}/bluefin-server/kc-agent.pid"
    mkdir -p "${SANDBOX}/bluefin-server"
    sleep 30 &
    BG_PID=$!
    echo "$BG_PID" > "$PID_FILE"

    run_launcher stop
    [ "$status" -eq 0 ]
    [[ "$output" == *"Stopped kc-agent"* ]]
    [ ! -f "$PID_FILE" ]

    # Verify background process was killed
    ! kill -0 "$BG_PID" 2>/dev/null
}

@test "logs displays existing log file contents" {
    LOG_FILE="${SANDBOX}/bluefin-server/kc-agent.log"
    mkdir -p "${SANDBOX}/bluefin-server"
    echo "test kc-agent log line" > "$LOG_FILE"

    run_launcher logs
    [ "$status" -eq 0 ]
    [[ "$output" == *"test kc-agent log line"* ]]
}
