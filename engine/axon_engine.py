#!/usr/bin/env python3
# /usr/local/bin/axon_engine.py
# Axon OS - Integrated Scheduler Engine v0.2
# systemd 서비스용: 룰 외부 파일 분리, 로그 syslog 출력, SIGHUP 룰 리로드

from bcc import BPF
import os, json, time, signal, sys, logging
from collections import defaultdict

# ─────────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────────
RULES_PATH        = "/etc/axon/rules.json"
LOG_PATH          = "/var/log/axon.log"
DATA_PATH         = "/var/lib/axon/engine_data.json"

ANALYZE_INTERVAL  = 2.0
SWITCH_MULTIPLIER = 3.0
RUNTIME_THRESHOLD = 50_000   # us
DYNAMIC_NICE_STEP = 5
RECOVERY_CYCLES   = 3

KERNEL_PREFIXES = (
    "kworker", "rcu_", "ksoftirq",
    "migration", "watchdog", "kswapd",
    "khugepaged", "kthread",
)

# ─────────────────────────────────────────────────
# 로깅 설정 (systemd journald + 파일 동시 출력)
# ─────────────────────────────────────────────────
def setup_logging():
    logger = logging.getLogger("axon")
    logger.setLevel(logging.INFO)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    # stdout → journald가 수집
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    # 파일 로그
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    fh = logging.FileHandler(LOG_PATH)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger

logger = setup_logging()

# ─────────────────────────────────────────────────
# 룰 로드 (SIGHUP으로 리로드 가능)
# ─────────────────────────────────────────────────
PRIORITY_RULES = {}

def load_rules():
    global PRIORITY_RULES
    try:
        with open(RULES_PATH) as f:
            data = json.load(f)
        PRIORITY_RULES = data.get("rules", {})
        logger.info(f"룰 로드 완료: {len(PRIORITY_RULES)}개 ({RULES_PATH})")
    except FileNotFoundError:
        logger.warning(f"룰 파일 없음: {RULES_PATH} → 기본 룰 사용")
        PRIORITY_RULES = {
            "gnome-shell":  -5,
            "sshd":         -3,
            "systemd":      -3,
            "python3":       5,
            "dbus-daemon":   5,
            "cupsd":        10,
            "cups-browsed": 10,
            "avahi-daemon": 10,
            "polkitd":       7,
        }
    except Exception as e:
        logger.error(f"룰 로드 실패: {e}")

# ─────────────────────────────────────────────────
# eBPF 프로그램
# ─────────────────────────────────────────────────
BPF_PROGRAM = """
#include <uapi/linux/ptrace.h>
#include <linux/sched.h>

struct sched_event_t {
    u32 prev_pid;
    u32 next_pid;
    u64 prev_runtime;
    char prev_comm[TASK_COMM_LEN];
    char next_comm[TASK_COMM_LEN];
};

BPF_PERF_OUTPUT(sched_events);
BPF_HASH(start_time, u32, u64);

RAW_TRACEPOINT_PROBE(sched_switch) {
    struct task_struct *prev = (struct task_struct *)ctx->args[1];
    struct task_struct *next = (struct task_struct *)ctx->args[2];

    u32 prev_pid, next_pid;
    bpf_probe_read_kernel(&prev_pid, sizeof(prev_pid), &prev->pid);
    bpf_probe_read_kernel(&next_pid, sizeof(next_pid), &next->pid);

    struct sched_event_t event = {};
    event.prev_pid = prev_pid;
    event.next_pid = next_pid;
    bpf_probe_read_kernel_str(event.prev_comm, sizeof(event.prev_comm), prev->comm);
    bpf_probe_read_kernel_str(event.next_comm, sizeof(event.next_comm), next->comm);

    if (prev_pid != 0) {
        u64 *start = start_time.lookup(&prev_pid);
        if (start) {
            u64 now = bpf_ktime_get_ns();
            event.prev_runtime = now - *start;
            start_time.delete(&prev_pid);
        }
    }
    if (next_pid != 0) {
        u64 now = bpf_ktime_get_ns();
        start_time.update(&next_pid, &now);
    }

    sched_events.perf_submit(ctx, &event, sizeof(event));
    return 0;
}
"""

# ─────────────────────────────────────────────────
# 상태
# ─────────────────────────────────────────────────
class ProcStat:
    def __init__(self):
        self.comm           = ""
        self.switches       = 0
        self.total_switches = 0
        self.runtime_sum    = 0
        self.runtime_count  = 0
        self.nice_applied   = None
        self.nice_original  = None
        self.dynamic_nice   = None
        self.normal_cycles  = 0

procs        = defaultdict(ProcStat)
event_count  = 0
idle_count   = 0
start_ts     = time.time()
action_log   = []
running      = True
reload_rules = False

# ─────────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────────
def is_kernel_thread(comm):
    return comm.startswith(KERNEL_PREFIXES)

def match_rule(comm):
    if comm in PRIORITY_RULES:
        return PRIORITY_RULES[comm]
    for rule, nice in PRIORITY_RULES.items():
        if comm.startswith(rule):
            return nice
    return None

def get_current_nice(pid):
    try:
        return os.getpriority(os.PRIO_PROCESS, pid)
    except:
        return None

def set_nice(pid, comm, target, reason):
    p = procs[pid]
    current = p.nice_applied

    if p.nice_original is None:
        p.nice_original = get_current_nice(pid) or 0

    if current == target:
        return False

    try:
        os.setpriority(os.PRIO_PROCESS, pid, target)
        prev      = current if current is not None else 0
        direction = "↑" if target < prev else "↓"
        logger.info(f"[{reason:<8}] {comm:<18} pid={pid:<8} nice: {prev:>3} → {target:>3} {direction}")
        action_log.append({
            "time":   round(time.time() - start_ts, 1),
            "reason": reason,
            "comm":   comm,
            "pid":    pid,
            "from":   prev,
            "to":     target,
        })
        p.nice_applied = target
        return True
    except (ProcessLookupError, PermissionError):
        return False

# ─────────────────────────────────────────────────
# eBPF 이벤트 핸들러
# ─────────────────────────────────────────────────
def handle_event(cpu, data, size):
    global event_count, idle_count
    event = bpf["sched_events"].event(data)
    event_count += 1

    prev_pid = event.prev_pid
    next_pid = event.next_pid

    if prev_pid == 0:
        idle_count += 1
        return

    prev_comm = event.prev_comm.decode("utf-8", errors="replace").rstrip("\x00")
    next_comm = event.next_comm.decode("utf-8", errors="replace").rstrip("\x00")

    p = procs[prev_pid]
    p.comm            = prev_comm
    p.switches       += 1
    p.total_switches += 1

    if event.prev_runtime > 0:
        p.runtime_sum   += event.prev_runtime
        p.runtime_count += 1

    if next_pid != 0:
        procs[next_pid].comm = next_comm

# ─────────────────────────────────────────────────
# 분석 + 거버너
# ─────────────────────────────────────────────────
def analyze():
    active_procs = {
        pid: p for pid, p in procs.items()
        if p.comm and p.switches > 0 and not is_kernel_thread(p.comm)
    }

    if not active_procs:
        for p in procs.values():
            p.switches = p.runtime_sum = p.runtime_count = 0
        return

    switch_values = [p.switches for p in active_procs.values()]
    avg_switches  = sum(switch_values) / len(switch_values) if switch_values else 1

    for pid, p in active_procs.items():
        comm = p.comm
        avg_runtime_us = (p.runtime_sum / p.runtime_count / 1000) if p.runtime_count else 0

        rule_nice = match_rule(comm)
        if rule_nice is not None:
            set_nice(pid, comm, rule_nice, "룰")
            p.switches = p.runtime_sum = p.runtime_count = 0
            continue

        is_hog  = p.switches > avg_switches * SWITCH_MULTIPLIER
        is_long = avg_runtime_us > RUNTIME_THRESHOLD

        if is_hog or is_long:
            p.normal_cycles = 0
            base   = p.nice_original or 0
            target = min(19, base + DYNAMIC_NICE_STEP)
            reason = "폭식" if is_hog else "독점"
            p.dynamic_nice = target
            set_nice(pid, comm, target, reason)

        elif p.dynamic_nice is not None:
            p.normal_cycles += 1
            if p.normal_cycles >= RECOVERY_CYCLES:
                original = p.nice_original or 0
                set_nice(pid, comm, original, "원복")
                p.dynamic_nice  = None
                p.normal_cycles = 0

        p.switches = p.runtime_sum = p.runtime_count = 0

    for pid, p in procs.items():
        if pid not in active_procs:
            p.switches = p.runtime_sum = p.runtime_count = 0

# ─────────────────────────────────────────────────
# 데이터 저장
# ─────────────────────────────────────────────────
def save_data():
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    applied = {
        str(pid): {
            "comm":           p.comm,
            "original_nice":  p.nice_original,
            "current_nice":   p.nice_applied,
            "total_switches": p.total_switches,
        }
        for pid, p in procs.items() if p.nice_applied is not None
    }
    out = {
        "meta": {
            "timestamp":    time.time(),
            "elapsed_sec":  round(time.time() - start_ts, 2),
            "event_count":  event_count,
            "action_count": len(action_log),
        },
        "rules":      PRIORITY_RULES,
        "applied":    applied,
        "action_log": action_log[-100:],  # 최근 100건만 유지
    }
    with open(DATA_PATH, "w") as f:
        json.dump(out, f, indent=2)

# ─────────────────────────────────────────────────
# 시그널 핸들러
# ─────────────────────────────────────────────────
def signal_handler(sig, frame):
    global running
    logger.info("종료 시그널 수신")
    running = False

def sighup_handler(sig, frame):
    global reload_rules
    logger.info("SIGHUP 수신 → 룰 리로드 예약")
    reload_rules = True

# ─────────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("Axon Engine v0.2 시작")
    load_rules()

    logger.info("eBPF 훅 로딩 중...")
    bpf = BPF(text=BPF_PROGRAM)
    bpf["sched_events"].open_perf_buffer(handle_event, page_cnt=128)
    logger.info("eBPF 훅 로드 완료")

    signal.signal(signal.SIGINT,  signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGHUP,  sighup_handler)

    last_analyze = time.time()
    last_save    = time.time()

    while running:
        bpf.perf_buffer_poll(timeout=100)

        now = time.time()

        if now - last_analyze >= ANALYZE_INTERVAL:
            if reload_rules:
                load_rules()
                reload_rules = False
            analyze()
            last_analyze = now

        # 30초마다 데이터 저장
        if now - last_save >= 30:
            save_data()
            last_save = now

    save_data()
    logger.info(f"Axon Engine 종료 완료 | 총 이벤트: {event_count:,} | 조정: {len(action_log)}회")
