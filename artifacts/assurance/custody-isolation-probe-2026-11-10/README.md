# Custody rule 4 probed with real OS users (AACP E-01)

`result.json` is the output of `python scripts/probe_custody_isolation.py --out result.json`. The probe starts a credential holder and an agent process in one Linux container and one PID namespace, with no network and the repository mounted read-only. The credential is synthetic and generated per run.

| Layout | Profile | Holder uid | Agent uid | Outcome |
|---|---|---|---|---|
| `same_user` (control) | `review` | 10001 | 10001 | The agent read the credential five ways: `/proc/<pid>/environ`, `/proc/<pid>/task/<pid>/environ`, `/proc/<pid>/mem`, `process_vm_readv` and after `ptrace` attach |
| `os_user` | `controlled_pilot` | 10003 | 10001 | All five, and eight more, were refused by the kernel with `PermissionError`; the credential was not read |
| `os_user` declared, uid shared | `controlled_pilot` | 10001 | 10001 | The guard refused to start the holder: it runs as an agent uid |
| `os_user` declared, root | `controlled_pilot` | 0 | 10001 | The guard refused to start the holder: it runs as root |

Fifteen techniques run in both layouts: `environ`, `task/<pid>/environ`, `mem` over every readable mapping, `process_vm_readv`, `maps`, `auxv`, `io`, `cmdline`, `status`, `fd`, `cwd`, `exe`, `root`, signal 0 and `ptrace` attach. `cmdline` and `status` are readable by any uid on Linux and hold no credential in either layout. The verdict needs every technique to have run against a holder that was still alive, and each technique that leaked under one uid to be refused with `PermissionError` under two. The credential reaches the agent on standard input, so it is in no command line.

## What it adds

The conformance tests K20 to K27 replace `os.getuid`, so they test the guard's arithmetic. Here the uids are real. The control matters: the same agent code that is denied under `os_user` reads the credential under `same_user`, so the denial is the uid split and not a probe that cannot read anything.

## What it does not show

- It is not the OT pilot. `deploy/ot-pilot/docker-compose.yml` sets no `REMORA_RUNTIME_PROFILE`, role or isolation, so the custody guard checks nothing there, and the pilot's API container holds the lease signing key and the plant write token in one process (NEGATIVE_RESULTS §104).
- One kernel (`linuxkit`, Docker Desktop) and one container runtime. No container escape, shared volume or temporary file, core dump, debugger with capabilities, signal other than 0, or credential fetched from a metadata service was tried. The container has no `ps`.
- The lease verify key the holder needs under rule 3 is random bytes. No lease is verified.
- The agent has no capabilities. An agent that can gain `CAP_SYS_PTRACE` or root is outside what a uid split claims.
