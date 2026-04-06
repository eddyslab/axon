#!/usr/bin/env bash
# Axon OS - uninstall.sh

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

info()  { echo -e "${GREEN}[Axon]${NC} $1"; }
error() { echo -e "${RED}[Axon]${NC} $1"; exit 1; }

if [ "$EUID" -ne 0 ]; then
    error "root 권한이 필요합니다. sudo bash uninstall.sh 로 실행하세요."
fi

info "Axon Engine 제거 중..."

systemctl stop axon    2>/dev/null || true
systemctl disable axon 2>/dev/null || true

rm -f /etc/systemd/system/axon.service
systemctl daemon-reload

rm -f /usr/local/bin/axon_engine.py

echo ""
read -p "설정 파일(/etc/axon)도 삭제할까요? [y/N] " confirm
if [[ "$confirm" =~ ^[Yy]$ ]]; then
    rm -rf /etc/axon
    info "설정 파일 삭제 완료"
fi

read -p "데이터 파일(/var/lib/axon)도 삭제할까요? [y/N] " confirm2
if [[ "$confirm2" =~ ^[Yy]$ ]]; then
    rm -rf /var/lib/axon
    info "데이터 파일 삭제 완료"
fi

echo ""
info "Axon Engine 제거 완료"
