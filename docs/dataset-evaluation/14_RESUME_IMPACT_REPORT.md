# Resume Impact Report — Verified Engineering Evidence

This report deliberately separates reproducible reliability work from capacity claims. The overnight capacity matrix stopped at concurrency 8 after a correctness oracle fired; there is **no verified performance improvement**, no measured 32/64-concurrency result, and no model-inference throughput claim.

## New results leaderboard

| Rank | Result | Engineering depth / relevance | Evidence strength and limit |
|---:|---|---|---|
| 1 | Reproduced and fixed a Linux TCP fault-probe hang caused by cross-thread socket close not unblocking `recv()`; bounded waits and thread exit are now part of the probe oracle. | Distributed systems, Python networking, CI reliability. | Reproduced with Linux faulthandler, then current-source Linux full suite: 214 passed, 49.91 s. Not yet confirmed by a new GitHub Actions run. |
| 2 | Exercised PostgreSQL Commit-Unknown recovery with a real protocol proxy that drops `ReadyForQuery` after COMMIT; the receipt recovered and idempotent replay did not double-charge. | Transaction semantics, idempotency, accounting correctness. | Real PostgreSQL: one receipt, one request audit, one provider attempt, 12 tokens; both proxy threads stopped. This is a targeted fault experiment, not a proof of all failure modes. |
| 3 | Ran shared Redis and PostgreSQL probes across two real Uvicorn processes, including rate-limit and cache sharing, distributed singleflight leases, and a budget race. | LLM platform, multi-instance coordination, shared state. | All probe oracles passed; synthetic deterministic provider only. |
| 4 | Stopped a capacity run at the first expired-reservation invariant, reconciled both orphan reservations, and verified terminal persisted state rather than continuing the load. | SRE discipline, budget accounting, recovery and auditability. | 3,565 reservations ended with 3,563 settled / 2 released / 0 reserved / 0 uncertain; 3,565 receipts; no duplicate receipt request IDs. Capacity results remain partial. |

## Capacity numbers: report only as censored observations

The completed concurrency-1 cells were 100% successful across target cache settings 0/0.5/0.9, with 4.737–9.720 attempted RPS and 222.900–324.237 ms P95. At concurrency 8, two cells passed at 17.170 and 23.100 RPS; the third returned 0/1,984 successful responses (all database-unavailable 503). The matrix stopped. These numbers do **not** establish service capacity or an SLO. Concurrency 32 and 64 were not run. No before/after optimization exists, so no improvement percentage is valid.

## Suggested resume bullets

The bullets below describe this engineering sprint. For each role, the Chinese and English bullets are parallel choices; numbers retain their evidence boundary.

### A. Python Backend / Distributed Systems

**中文**

1. 在 Linux 复现 PostgreSQL COMMIT ACK 丢失探针卡死，定位为跨线程关闭 socket 无法可靠唤醒阻塞 `recv()`；增加 socket deadline、`shutdown()` 与有界线程 join，并在当前源码 Linux 回归中通过 214 项测试。
2. 使用真实 PostgreSQL 协议代理模拟“服务端已提交、客户端未收到 ACK”，通过持久 receipt 查询恢复结算；重放后保持 12 tokens、1 receipt、1 audit、1 provider attempt，验证该故障场景下不重复扣费。
3. 运行冷预算、并发结算、Audit rollback、过期 reservation reconciliation 等 PostgreSQL 实验；负载后显式回收 2 个孤儿 reservation，最终数据库为 3,563 settled、2 released、0 pending/uncertain、0 重复 receipt。
4. 设计带数据库不变量停止条件的 PostgreSQL/Redis 容量实验；在 concurrency 8 出现 1,984/1,984 数据库不可用响应时立即停止，保留失败证据并完成 lease reconciliation，不把失败流量当吞吐。

**English**

1. Reproduced a Linux hang in a PostgreSQL COMMIT-ACK-loss proxy, traced it to cross-thread socket close not reliably waking blocking `recv()`, and added deadlines, `shutdown()`, and bounded thread joins; the current-source Linux regression suite passed 214 tests.
2. Injected a real PostgreSQL protocol failure after COMMIT completed but before the client received `ReadyForQuery`; recovered settlement from its durable receipt and verified idempotent replay retained exactly 12 tokens, one receipt, one audit, and one provider attempt.
3. Exercised PostgreSQL budget admission, concurrent finalization, audit rollback, and lease reconciliation; recovered two orphan reservations and verified 3,563 settled, two released, zero pending/uncertain reservations, and no duplicate receipt request IDs.
4. Built a PostgreSQL/Redis capacity experiment with persisted-state stop conditions; stopped immediately when an 8-concurrency cell returned 1,984 database-unavailable responses and reconciled its orphan reservations instead of presenting failed requests as throughput.

### B. LLM Platform / AI Infrastructure

**中文**

1. 用两个真实 Uvicorn 实例和共享 Redis 验证跨实例限流：20 个并发请求中 10 个准入、10 个拒绝；同时验证跨实例缓存一致性。
2. 验证 Redis 分布式 singleflight 与租约过期恢复：两个 Gateway 对相同输入返回等价结果，底层 synthetic provider 仅执行一次；旧 owner 无法释放新 owner 的租约。
3. 验证 Redis 不可用时两种限流策略的明确语义：fail-closed 返回依赖错误，fail-open 按配置准入；并保留独立 Redis adapter 的真实集成日志。
4. 为 Gateway CI 增加 45 分钟 job deadline、20 分钟 pytest deadline、实时日志、faulthandler 和独立 coverage 退出状态；当前本地完整测试 214 passed，combined coverage 84.02%（branch-only 71.28%，不得称为 84% branch coverage）。

**English**

1. Validated cross-instance Redis rate limiting with two real Uvicorn replicas: 20 concurrent requests yielded 10 admissions and 10 rejections; also verified shared-cache consistency.
2. Verified Redis distributed singleflight and lease recovery across Gateway replicas: equivalent responses required one synthetic provider execution, and a stale owner could not release a successor's lease.
3. Tested explicit Redis-outage policies: fail-closed classified the dependency error while fail-open admitted according to configuration; retained the live Redis adapter probe output.
4. Added bounded CI execution, live pytest output, faulthandler diagnostics, and independent test/coverage exit states; the current Windows run passed 214 tests with 84.02% combined coverage (71.28% branch-only, not 84% branch coverage).

### C. AI Application Backend

**中文**

1. 对 FastAPI Gateway 的真实 TCP SSE 路径执行 Uvicorn E2E：2 项测试通过，覆盖正常流、首 token 前 fallback、timeout 和首 token 后失败路径；这是协议/审计验证，不是生产流量 SLO。
2. 在 PostgreSQL 集成探针中验证幂等最终结算和 audit 事务回滚：并发重放最终只保留一个 request finalization，提交结果不确定时先查 receipt，不盲目重试。
3. 对当前源码容器执行构建与隔离 smoke：PostgreSQL migration 两次重复执行成功，Ready 在依赖恢复后返回 200，非 root UID 10001 且 rootfs 只读，SIGTERM 后容器以退出码 0 退出。
4. 针对现有固定种子 UltraChat/WildChat 的历史评测报告保留来源边界：987 请求中 475 HTTP 2xx、512 预期 guardrail 400、0 意外错误；这是本地 Mock Provider/SQLite 评测，不能写成真实模型质量或 PostgreSQL 容量。本轮没有重新运行该 987 请求数据集评测。

**English**

1. Ran two Uvicorn TCP SSE end-to-end tests for the FastAPI Gateway, covering normal streaming, pre-first-token fallback, timeout, and post-token failure behavior; this validates protocol/audit paths, not a production traffic SLO.
2. Exercised idempotent PostgreSQL finalization and audit-transaction rollback: concurrent replay converged on one durable finalization, and uncertain commit outcomes were recovered by receipt lookup rather than blind retry.
3. Built and smoke-tested the current-source container: PostgreSQL migrations succeeded twice, readiness returned 200 after dependency recovery, the process ran as UID 10001 on a read-only root filesystem, and SIGTERM ended with exit code 0.
4. Preserved the existing fixed-seed UltraChat/WildChat report boundary: its 987 local Mock Provider/SQLite requests comprised 475 HTTP 2xx, 512 expected guardrail 400s, and zero unexpected errors. This sprint did not rerun that dataset workload; it is not a real-model quality or PostgreSQL capacity result.

## Evidence map

| Claim | Source / test location | Raw evidence |
|---|---|---|
| Bounded Linux TCP proxy | `scripts/postgres_commit_ack_loss_probe.py`; `tests/integration/test_postgres_repository_integration.py` | `ci-diagnostics/linux-fixed-pytest.log`, `ci-diagnostics/linux-fixed-container.log` |
| Commit-Unknown / durable receipt | `scripts/postgres_integration_probe.py`; `scripts/postgres_commit_ack_loss_probe.py` | `database-invariants/postgres-final-probe.log`; `database-invariants/reconciled-state.txt` |
| Redis replicas and leases | `scripts/redis_adapter_integration_probe.py`; `scripts/redis_two_replica_integration_probe.py` | `provider-faults/redis-adapter-probe.log`; `provider-faults/redis-two-replica-probe.log` |
| TCP SSE | `tests/integration/test_uvicorn_streaming_e2e.py` | `junit-coverage/http-sse-e2e-attempt2.log` |
| Current source image | `Dockerfile`; `scripts/migrate_postgres.py` | `image-build/` build, migration, health, read-only, and SIGTERM logs |
| Final Windows suite and metrics | `pyproject.toml`, test files under `tests/` | `junit-coverage/pytest-attempt2.log`, `coverage.json`, `coverage-gate-attempt2.log` |

The raw evidence root is `E:\project-test-assets\01-gateway\results\overnight-sprint-20261010T155645Z\`. Before using the historical dataset bullet externally, keep the existing privacy-audit limitation in view: automated screening was performed, but semantic human review was not completed.
