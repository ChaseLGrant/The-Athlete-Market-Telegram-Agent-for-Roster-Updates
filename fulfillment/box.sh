#!/usr/bin/env bash
# Hybrid RSA-OAEP + AES-256 envelope (openssl only). Used by fulfillment-db.yml and the private workspace.
#   box.sh seal PUBKEY.pem IN OUT     -> OUT = base64 "rsa(aeskey).aes(data)" envelope (one line)
#   box.sh open PRIVKEY.pem IN OUT
set -euo pipefail
mode=$1; key=$2; in=$3; out=$4; t=$(mktemp -d); trap 'rm -rf "$t"' EXIT
if [ "$mode" = seal ]; then
  openssl rand -hex 32 > "$t/k"
  openssl pkeyutl -encrypt -pubin -inkey "$key" -pkeyopt rsa_padding_mode:oaep -pkeyopt rsa_oaep_md:sha256 -in "$t/k" -out "$t/k.enc"
  openssl enc -aes-256-cbc -pbkdf2 -salt -pass file:"$t/k" -in "$in" -out "$t/d.enc"
  printf '%s.%s' "$(base64 -w0 "$t/k.enc")" "$(base64 -w0 "$t/d.enc")" > "$out"
else
  IFS=. read -r a b < "$in" || true
  printf '%s' "$a" | base64 -d > "$t/k.enc"; printf '%s' "$b" | base64 -d > "$t/d.enc"
  openssl pkeyutl -decrypt -inkey "$key" -pkeyopt rsa_padding_mode:oaep -pkeyopt rsa_oaep_md:sha256 -in "$t/k.enc" -out "$t/k"
  openssl enc -d -aes-256-cbc -pbkdf2 -pass file:"$t/k" -in "$t/d.enc" -out "$out"
fi
