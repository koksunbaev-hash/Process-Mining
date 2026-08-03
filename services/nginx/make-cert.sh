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
DIR="$(dirname "$0")/certs"
mkdir -p "$DIR"

ALT="DNS:localhost,IP:127.0.0.1,IP:${HOST}"
openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
  -keyout "$DIR/server.key" -out "$DIR/server.crt" \
  -subj "/CN=${HOST}/O=Bakery QMS" \
  -addext "subjectAltName=${ALT}" \
  -addext "basicConstraints=CA:FALSE" 2>/dev/null

chmod 600 "$DIR/server.key"
echo "certificate for ${HOST} -> $DIR"
openssl x509 -in "$DIR/server.crt" -noout -subject -ext subjectAltName
