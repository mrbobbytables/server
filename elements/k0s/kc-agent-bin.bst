kind: manual
description: |
  Import the upstream kc-agent release binary.

  kc-agent connects the KubeStellar Console browser session to the local
  k0s cluster via WebSocket, reading /var/lib/k0s/pki/admin.conf.

(@): include/kc-agent.yml

build-depends:
  # Base runtime providing /bin/sh and install in the sandbox.
  - base/base-stack.bst

variables:
  # Do not try to strip the pre-built upstream binary.
  strip-binaries: ""

sources:
  - kind: tar
    url: github:kubestellar/console/releases/download/v%{kc-agent-version}/kc-agent_%{kc-agent-version}_linux_amd64.tar.gz
    ref: 052b80bd0700f1c7e22ed5d6ad7547a45d6441d6a2cd40609fed1e69bf592df2

config:
  install-commands:
    - |
      if [ "%{arch}" != "x86_64" ]; then
        echo "ERROR: elements/k0s/kc-agent-bin.bst pins the upstream kc-agent amd64 binary;" >&2
        echo "       arch=%{arch} has no pinned source. Add an arch-conditional" >&2
        echo "       source before building kc-agent for %{arch}." >&2
        exit 1
      fi
    - install -D -m 0755 kc-agent "%{install-root}/usr/bin/kc-agent"
