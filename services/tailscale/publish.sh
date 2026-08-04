#!/bin/sh
# Publish the stack on the public internet through Tailscale Funnel.
#
#   sh services/tailscale/publish.sh          # publish
#   sh services/tailscale/publish.sh off      # take it down again
#
# Funnel hands out a real certificate for <machine>.<tailnet>.ts.net and
# accepts connections on Tailscale's edge, so nothing has to be forwarded on
# the router and the machine needs no public address of its own. It only
# supports 443, 8443 and 10000 - which is exactly the pair this stack already
# uses.
#
# The target is the TLS proxy rather than the applications directly:
#   funnel :443  -> nginx :443  -> qms:8000
#   funnel :8443 -> nginx :8443 -> process-mining:8000
#
# `https+insecure` because that certificate is the self-signed one made by
# make-cert.sh, and the hop is over the loopback where there is nobody to
# impersonate anyone. Going through nginx keeps the rate limits and the
# X-Forwarded-Proto header that Django needs in one place, instead of
# depending on what the tunnel happens to add.

set -eu

if ! command -v tailscale >/dev/null 2>&1; then
  echo "tailscale is not installed. See docs/PUBLIC-ACCESS.md, step 1." >&2
  exit 1
fi

if [ "${1:-on}" = "off" ]; then
  tailscale funnel --https=443   off || true
  tailscale funnel --https=8443  off || true
  tailscale funnel --https=10000 off || true
  echo "Funnel is off. The stack is reachable on the LAN and the tailnet only."
  exit 0
fi

# --bg keeps it running after this shell exits and survives reboots.
tailscale funnel --bg --https=443   https+insecure://127.0.0.1:443
tailscale funnel --bg --https=8443  https+insecure://127.0.0.1:8443
# The phone app's backend. Funnel serves these three ports and no others,
# which is why the proxy listens on 10000 rather than something tidier.
tailscale funnel --bg --https=10000 https+insecure://127.0.0.1:10000

echo
tailscale funnel status
echo
echo "Add the hostname printed above to ALLOWED_HOSTS and CSRF_TRUSTED_ORIGINS"
echo "in .env, then: docker compose up -d qms"
