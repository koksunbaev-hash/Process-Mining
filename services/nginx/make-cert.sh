#!/usr/bin/env sh
# Generates the self-signed certificate the proxy serves.
#
# The IP has to appear in subjectAltName: browsers stopped accepting the
# Common Name years ago, and a certificate without a matching SAN is refused
# outright rather than with a click-through warning.
#
#   ./make-cert.sh 192.168.0.137
set -eu
HOST="${1:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
# hostname -I is Linux-only, and the exit status of that pipeline is awk's, so
# `set -e` does not catch it: on macOS or Git Bash HOST silently ends up empty,
# openssl then rejects "IP:" and its complaint disappears into /dev/null below.
if [ -z "$HOST" ]; then
  echo "usage: $0 <ip-or-hostname>    e.g. $0 192.168.0.137" >&2
  echo "(cannot guess it here: hostname -I is Linux-only)" >&2
  exit 1
fi
DIR="$(dirname "$0")/certs"
mkdir -p "$DIR"

ALT="DNS:localhost,IP:127.0.0.1,IP:${HOST}"
# openssl's stderr is not redirected on purpose. It costs a few progress dots
# and buys the actual complaint when something goes wrong - silently leaving a
# key with no certificate next to it turns into an nginx restart loop later,
# a long way from the cause. (Run this on the server: under Git Bash MSYS
# rewrites the leading slash of -subj into a Windows path and openssl refuses.)
openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
  -keyout "$DIR/server.key" -out "$DIR/server.crt" \
  -subj "/CN=${HOST}/O=Bakery QMS" \
  -addext "subjectAltName=${ALT}" \
  -addext "basicConstraints=CA:FALSE"

if [ ! -s "$DIR/server.crt" ] || [ ! -s "$DIR/server.key" ]; then
  echo "openssl produced no usable pair in $DIR - nginx would restart forever" >&2
  exit 1
fi

chmod 600 "$DIR/server.key"
echo "certificate for ${HOST} -> $DIR"
openssl x509 -in "$DIR/server.crt" -noout -subject -ext subjectAltName
