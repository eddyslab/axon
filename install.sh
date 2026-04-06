#!/usr/bin/env bash
# Axon OS - install.sh
# One-shot installer for Axon Engine

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()    { echo -e "${GREEN}[Axon]${NC} $1"; }
warning() { echo -e "${YELLOW}[Axon]${NC} $1"; }
error()   { echo -e "${RED}[Axon]${NC} $1"; exit 1; }

# ── 루트 확인 ──────────────────────────────────────
if [ "$EUID" -ne 0 ]; then
    error "root 권한이 필요합니다. sudo bash install.sh 로 실행하세요."
fi

# ── 커널 버전 확인 ──────────────────────────────────
KERNEL=$(uname -r)
KERNEL_MAJOR=$(echo "$KERNEL" | cut -d. -f1)
if [ "$KERNEL_MAJOR" -lt 5 ]; then
    error "커널 5.x 이상이 필요합니다. 현재: $KERNEL"
fi
info "커널 버전 확인: $KERNEL ✓"

# ── 의존성 설치 ─────────────────────────────────────
info "의존성 패키지 설치 중..."
apt-get update -qq
apt-get install -y -qq \
    bpfcc-tools \
    libbpf-dev \
    linux-headers-$(uname -r) \
    python3-bpfcc \
    bpftrace \
    clang \
    llvm \
    build-essential
info "의존성 설치 완료 ✓"

# ── eBPF 환경 검증 ──────────────────────────────────
info "eBPF 환경 검증 중..."
if ! bpftrace -e 'BEGIN { exit(); }' &>/dev/null; then
    error "eBPF 환경 검증 실패. 커널 설정을 확인하세요."
fi
info "eBPF 환경 정상 ✓"

# ── 파일 설치 ───────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

info "엔진 설치 중..."
cp "$SCRIPT_DIR/engine/axon_engine.py" /usr/local/bin/axon_engine.py
chmod +x /usr/local/bin/axon_engine.py

info "설정 파일 설치 중..."
mkdir -p /etc/axon
if [ ! -f /etc/axon/rules.json ]; then
    cp "$SCRIPT_DIR/config/rules.json" /etc/axon/rules.json
    info "룰 파일 설치 완료: /etc/axon/rules.json ✓"
else
    warning "기존 룰 파일 유지: /etc/axon/rules.json (덮어쓰지 않음)"
fi

mkdir -p /var/lib/axon
info "데이터 디렉토리 생성: /var/lib/axon ✓"

# ── systemd 서비스 등록 ─────────────────────────────
info "systemd 서비스 등록 중..."
cp "$SCRIPT_DIR/systemd/axon.service" /etc/systemd/system/axon.service
systemctl daemon-reload
systemctl enable axon
systemctl start axon
info "서비스 등록 및 시작 완료 ✓"

# ── 완료 ────────────────────────────────────────────
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  Axon Engine 설치 완료!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "  상태 확인:       sudo systemctl status axon"
echo "  실시간 로그:     sudo journalctl -u axon -f"
echo "  룰 리로드:       sudo systemctl kill -s SIGHUP axon"
echo "  중지:            sudo systemctl stop axon"
echo "  제거:            sudo bash uninstall.sh"
echo ""
