#!/bin/bash
set -e

# 🔧 Accept IP/domain + optional name
CN=$1
ORG_NAME="MatrixSwarm"

# Check for optional --name
while [[ "$2" != "" ]]; do
  case $2 in
    --name ) shift
             ORG_NAME="$2"
             ;;
  esac
  shift
done

if [ -z "$CN" ]; then
  echo "❌ Usage: ./generate_socket_certs.sh <server-ip-or-domain> [--name YourSwarmName]"
  exit 1
fi

DAYS=500
ROOT_CN="$ORG_NAME-Root"

echo "⚠️ Nuking old certs..."
rm -rf https_certs socket_certs
mkdir -p https_certs socket_certs

echo "🔧 Generating root CA for $ORG_NAME..."
openssl genrsa -out rootCA.key 2048
openssl req -x509 -new -nodes -key rootCA.key -sha256 -days $DAYS -out rootCA.pem \
  -subj "/C=US/ST=SwarmNet/L=Orbit/O=$ORG_NAME/CN=$ROOT_CN"

cp rootCA.* https_certs/
cp rootCA.* socket_certs/

echo "🔐 Generating HTTPS certs for $CN..."
cd https_certs
openssl genrsa -out server.key 2048
openssl req -new -key server.key -out server.csr -subj "/C=US/ST=SwarmNet/L=Orbit/O=$ORG_NAME/CN=$CN"
openssl x509 -req -in server.csr -CA rootCA.pem -CAkey rootCA.key -CAcreateserial \
  -out server.crt -days $DAYS -sha256
cat server.crt rootCA.pem > server.fullchain.crt
cd ..

echo "🔌 Generating WebSocket certs for $CN..."
cd socket_certs

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
cd ..

echo "✅ Cert generation complete!"
echo "📁 HTTPS certs → ./https_certs/"
echo "📁 WebSocket certs → ./socket_certs/"
