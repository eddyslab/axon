# Axon OS

> eBPF 기반 AI 네이티브 Linux 스케줄러 엔진

Axon은 Linux 커널 위에서 **AI 네이티브 운영체제**를 구현하는 실험적 프로젝트입니다. 커널을 교체하는 대신, **eBPF**를 사용해 스케줄러에 안전하게 후킹하여 커널 패치 없이 프로세스 우선순위를 실시간으로 최적화합니다.

---

## 주요 기능

- eBPF `RAW_TRACEPOINT`로 커널 스케줄러의 모든 컨텍스트 스위치 **실시간 모니터링**
- CPU 폭식 프로세스 **자동 탐지** (스위치 수 > 평균 × 3)
- `setpriority()`를 통한 **룰 기반 우선순위 자동 조정**
- 정상 복귀 시 원래 우선순위로 **자동 원복**
- systemd 서비스로 등록, **부팅 시 자동 시작**

---

## 아키텍처

```
┌─────────────────────────────────────────────┐
│                 Axon Engine                  │
│                                              │
│  eBPF Layer (커널 공간)                       │
│  └── RAW_TRACEPOINT sched_switch             │
│       → pid, comm, runtime 캡처              │
│                                              │
│  Analyzer (2초마다, 유저 공간)                │
│  ├── 룰 매칭    → 정적 우선순위 조정          │
│  ├── 폭식 탐지  → 동적 nice +5               │
│  └── 원복       → 원래 nice 복원             │
│                                              │
│  Governor                                    │
│  └── os.setpriority() → 커널 스케줄러        │
└─────────────────────────────────────────────┘
```

---

## 요구사항

| 항목 | 버전 |
|------|------|
| OS | Ubuntu 22.04 / 24.04 |
| 커널 | 6.x (6.8.0 테스트 완료) |
| Python | 3.10+ |
| 패키지 | `bpfcc-tools` `libbpf-dev` `python3-bpfcc` |

---

## 빠른 설치

```bash
git clone https://github.com/axon-os/axon.git
cd axon
sudo bash install.sh
```

---

## 수동 설치

```bash
# 1. 의존성 설치
sudo apt update
sudo apt install -y bpfcc-tools libbpf-dev linux-headers-$(uname -r) python3-bpfcc bpftrace clang llvm build-essential

# 2. 엔진 설치
sudo cp engine/axon_engine.py /usr/local/bin/axon_engine.py
sudo chmod +x /usr/local/bin/axon_engine.py

# 3. 설정 파일 설치
sudo mkdir -p /etc/axon
sudo cp config/rules.json /etc/axon/rules.json

# 4. 데이터 디렉토리 생성
sudo mkdir -p /var/lib/axon

# 5. systemd 서비스 등록
sudo cp systemd/axon.service /etc/systemd/system/axon.service
sudo systemctl daemon-reload
sudo systemctl enable axon
sudo systemctl start axon
```

---

## 사용법

```bash
# 상태 확인
sudo systemctl status axon

# 실시간 로그
sudo journalctl -u axon -f

# 재시작 없이 룰 리로드
sudo systemctl kill -s SIGHUP axon

# 중지
sudo systemctl stop axon
```

---

## 우선순위 룰 설정

`/etc/axon/rules.json` 을 수정해서 커스터마이징:

```json
{
  "rules": {
    "gnome-shell":  -5,
    "sshd":         -3,
    "systemd":      -3,
    "cupsd":        10,
    "avahi-daemon": 10
  }
}
```

- 범위: `-20` (최고 우선순위) ~ `19` (최저 우선순위)
- 접두사 매칭 지원: `"systemd"` → `systemd-journal`, `systemd-logind` 등 자동 매칭
- 실시간 리로드: `sudo systemctl kill -s SIGHUP axon`

---

## 동적 탐지

정적 룰 외에도 이상 프로세스를 자동으로 감지하고 조정합니다:

| 조건 | 조치 |
|------|------|
| 스위치 수 > 평균 × 3 | nice +5 (CPU 폭식) |
| 평균 런타임 > 50ms | nice +3 (독점) |
| 3 사이클 연속 정상 | 원래 nice 복원 |

---

## 개발 로드맵

- [x] **1단계** — eBPF 스케줄러 모니터 + 룰 기반 거버너 + systemd 서비스
- [ ] **2단계** — 패키지화 + GitHub 공개
- [ ] **3단계** — 커스텀 Ubuntu 파생 배포판 ISO
- [ ] **4단계** — 독립 배포판 + AI 메모리/전력 관리

---

## 라이선스

MIT License

---

## 기여

이슈와 PR 환영합니다. 초기 단계 연구 프로젝트입니다.
