#!/bin/bash
set -e

# --- PATCHED FOR MATRIXSWARM INSTALL DIR ---

# Usage: ./generate_certs.sh [output_dir] <server-ip-or-domain> [--name YourSwarmName]

# Default cert output dir
DEFAULT_CERT_DIR="$HOME/.matrixswarm/certs"

# If first arg is a dir, use it as base output dir
if [[ -d "$1" || "$1" == /* || "$1" == .* ]]; then
  OUTDIR="$1"
  shift
else
  OUTDIR="$DEFAULT_CERT_DIR"
fi

CN=$1
ORG_NAME="MatrixSwarm"

shift # Move past CN (now $2 or $3 is --name or nothing)

# Parse optional --name
while [[ "$1" != "" ]]; do
  case $1 in
    --name ) shift
             ORG_NAME="$1"
             ;;
  esac
  shift
done

if [ -z "$CN" ]; then
  echo "❌ Usage: $0 [output_dir] <server-ip-or-domain> [--name YourSwarmName]"
  exit 1
fi

DAYS=500
ROOT_CN="$ORG_NAME-Root"

CERT_HTTPS="$OUTDIR/https_certs"
CERT_SOCKET="$OUTDIR/socket_certs"

echo "⚠️ Nuking old certs in $OUTDIR ..."
rm -rf "$CERT_HTTPS" "$CERT_SOCKET"
mkdir -p "$CERT_HTTPS" "$CERT_SOCKET"

cd "$OUTDIR"

echo "🔧 Generating root CA for $ORG_NAME..."
openssl genrsa -out rootCA.key 2048
openssl req -x509 -new -nodes -key rootCA.key -sha256 -days $DAYS -out rootCA.pem \
  -subj "/C=US/ST=SwarmNet/L=Orbit/O=$ORG_NAME/CN=$ROOT_CN"

cp rootCA.* "$CERT_HTTPS/"
cp rootCA.* "$CERT_SOCKET/"

echo "🔐 Generating HTTPS certs for $CN..."
cd "$CERT_HTTPS"
openssl genrsa -out server.key 2048
openssl req -new -key server.key -out server.csr -subj "/C=US/ST=SwarmNet/L=Orbit/O=$ORG_NAME/CN=$CN"
openssl x509 -req -in server.csr -CA rootCA.pem -CAkey rootCA.key -CAcreateserial \
  -out server.crt -days $DAYS -sha256
cat server.crt rootCA.pem > server.fullchain.crt

echo "🔌 Generating WebSocket certs for $CN..."
cd "$CERT_SOCKET"

openssl genrsa -out server.key 2048
openssl req -new -key server.key -out server.csr -subj "/C=US/ST=SwarmNet/L=Orbit/O=$ORG_NAME/CN=$CN"
openssl x509 -req -in server.csr -CA rootCA.pem -CAkey rootCA.key -CAcreateserial \
  -out server.crt -days $DAYS -sha256
cat server.crt rootCA.pem > server.fullchain.crt

echo "🧠 Generating GUI client cert..."
openssl genrsa -out client.key 2048
openssl req -new -key client.key -out client.csr -subj "/C=US/ST=SwarmNet/L=Orbit/O=$ORG_NAME/CN=matrix-gui"
openssl x509 -req -in client.csr -CA rootCA.pem -CAkey rootCA.key -CAcreateserial \
  -out client.crt -days $DAYS -sha256

cd "$OUTDIR"

echo "✅ Cert generation complete!"
echo "📁 HTTPS certs   → $CERT_HTTPS/"
echo "📁 WebSocket certs → $CERT_SOCKET/"