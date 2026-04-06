# Axon OS

> An AI-native Linux scheduler engine powered by eBPF

Axon is an experimental project to build an **AI-native operating system** on top of the Linux kernel. Instead of replacing the kernel, Axon hooks into the scheduler using **eBPF** — safely, without kernel patches — and dynamically optimizes process priorities in real time.

---

## What It Does

- **Monitors** every context switch on the kernel scheduler via eBPF `RAW_TRACEPOINT`
- **Detects** CPU hog processes dynamically (switch count > 3× average)
- **Applies** rule-based priority adjustments using `setpriority()`
- **Recovers** processes back to their original priority after normal behavior resumes
- **Runs** as a systemd service, starting automatically at boot

---

## Architecture

```
┌─────────────────────────────────────────────┐
│                 Axon Engine                  │
│                                              │
│  eBPF Layer (Kernel Space)                   │
│  └── RAW_TRACEPOINT sched_switch             │
│       → captures pid, comm, runtime          │
│                                              │
│  Analyzer (every 2s, User Space)             │
│  ├── Rule matching  → static priority        │
│  ├── Hog detection  → dynamic nice +5        │
│  └── Recovery       → restore original nice  │
│                                              │
│  Governor                                    │
│  └── os.setpriority() → kernel scheduler     │
└─────────────────────────────────────────────┘
```

---

## Requirements

| Item | Version |
|------|---------|
| OS | Ubuntu 22.04 / 24.04 |
| Kernel | 6.x (tested on 6.8.0) |
| Python | 3.10+ |
| Packages | `bpfcc-tools` `libbpf-dev` `python3-bpfcc` |

---

## Quick Install

```bash
git clone https://github.com/axon-os/axon.git
cd axon
sudo bash install.sh
```

---

## Manual Install

```bash
# 1. Install dependencies
sudo apt update
sudo apt install -y bpfcc-tools libbpf-dev linux-headers-$(uname -r) python3-bpfcc bpftrace clang llvm build-essential

# 2. Install engine
sudo cp engine/axon_engine.py /usr/local/bin/axon_engine.py
sudo chmod +x /usr/local/bin/axon_engine.py

# 3. Install config
sudo mkdir -p /etc/axon
sudo cp config/rules.json /etc/axon/rules.json

# 4. Create data directory
sudo mkdir -p /var/lib/axon

# 5. Register systemd service
sudo cp systemd/axon.service /etc/systemd/system/axon.service
sudo systemctl daemon-reload
sudo systemctl enable axon
sudo systemctl start axon
```

---

## Usage

```bash
# Check status
sudo systemctl status axon

# Watch live logs
sudo journalctl -u axon -f

# Reload rules without restart
sudo systemctl kill -s SIGHUP axon

# Stop
sudo systemctl stop axon
```

---

## Priority Rules

Edit `/etc/axon/rules.json` to customize priorities:

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

- Range: `-20` (highest) to `19` (lowest)
- Prefix matching supported: `"systemd"` matches `systemd-journal`, `systemd-logind`, etc.
- Reload live: `sudo systemctl kill -s SIGHUP axon`

---

## Dynamic Detection

Beyond static rules, Axon automatically detects and throttles misbehaving processes:

| Condition | Action |
|-----------|--------|
| Switch count > avg × 3 | nice +5 (CPU hog) |
| Avg runtime > 50ms | nice +3 (monopoly) |
| Normal for 3 cycles | Restore original nice |

---

## Roadmap

- [x] **Stage 1** — eBPF scheduler monitor + rule-based governor + systemd service
- [ ] **Stage 2** — Package & publish on GitHub
- [ ] **Stage 3** — Custom Ubuntu derivative ISO
- [ ] **Stage 4** — Standalone distro + AI memory & power management

---

## License

MIT License

---

## Contributing

Issues and PRs welcome. This is an early-stage research project.
