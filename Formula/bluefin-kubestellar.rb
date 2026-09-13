# typed: false
# frozen_string_literal: true

class BluefinKubestellar < Formula
  desc "Single-command launcher and service wrapper for KubeStellar Console kc-agent"
  homepage "https://github.com/projectbluefin/server"
  version "26.08.0"
  license "Apache-2.0"

  depends_on "ublue-os/tap/kc-agent"

  def install
    (bin/"bluefin-kubestellar").write <<~SHELL
      #!/usr/bin/env bash
      exec "#{Formula["ublue-os/tap/kc-agent"].opt_bin}/kc-agent" "$@"
    SHELL
    chmod 0755, bin/"bluefin-kubestellar"
  end

  service do
    run [opt_bin/"bluefin-kubestellar"]
    environment_variables KAGENTI_CONTROLLER_URL: "none"
    keep_alive true
    log_path var/"log/bluefin-kubestellar.log"
    error_log_path var/"log/bluefin-kubestellar.log"
  end

  test do
    system bin/"bluefin-kubestellar", "--version"
  end
end
