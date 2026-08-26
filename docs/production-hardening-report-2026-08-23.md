# 第二阶段 Production Hardening 最终报告 — 2026-08-23

## 1. Executive Summary

- 完成 30 个任务单元：5 项二轮 review、1 项基线、8 项 public-data、
  2 项 Redis、5 项 PostgreSQL、1 项 OTel、3 项负载验证、1 项 clean
  reproduction、1 项文档收口、3 组 demo/最终验收工作。
- 本轮落盘 44 个文件（按 2026-08-23 非缓存文件 mtime 口径：runtime 21、
  tests 6、scripts 7、migration 1、docs/deploy 7、root 2）。仓库开始时已
  有大量未提交修改，因此该数字不是 `git diff` 对干净 HEAD 的归因。
- 新增 11 个针对真实缺陷/invariant 的回归测试，最终为 116 passed。
- 执行 38 个独立 oracle 场景：15 个数据/缓存/故障/预算场景、8 个
  Redis/PostgreSQL/OTel 场景、10 个负载场景、4 个最终 demo、1 次干净复现。
- 最终结论：请求范围内可在当前机器安全完成的事项全部完成；结果是
  production-oriented hardening evidence，不是生产容量认证。

## 2. Baseline → Final

| Gate | 本轮复核检查点 | Final | 结果 |
| --- | --- | --- | --- |
| pytest | 113 passed（随后又补 3 项） | 116 passed / 10.15 s | PASS |
| Ruff | pass | pass / 0.03 s | PASS |
| compileall | pass | pass / 0.21 s | PASS |
| functional eval | 7/7 | 7/7 / 1.41 s | PASS |
| security eval | 8/8 | 8/8 / 0.71 s | PASS |
| original demo | pass | pass / 1.49 s | PASS |
| final demos | — | 4/4 / 1.02 s | PASS |
| dataset experiment | — | `all_oracles_pass=true` | PASS |
| real HTTP/Uvicorn | — | gateway + fault provider | PASS |
| multi-replica | SQLite 已复核；Redis/PG 新增 | Redis、PG 两副本通过 | PASS |
| Redis | runtime 未闭环 | Redis 7 实测通过 | PASS |
| PostgreSQL | migration design only | PostgreSQL 16 runtime 通过 | PASS |
| OpenTelemetry | bounded recorder only | Collector 实收 success/error spans | PASS |
| clean reproduction | — | 新副本安装后全部 gate exit 0 | PASS |

说明：曾误用不存在的 `eval/run_security_eval.py` 得到 exit 2；定位 Makefile 后
使用真实入口 `eval/run_eval.py --cases eval/security_cases.yaml` 重跑为 8/8。
这是一条命令路径错误，不计作产品测试失败。

## 3. Code Review Findings

上一轮正确的部分：治理流水线总体顺序、SQLite 原子 reservation、原子
request+attempt audit、whole-request deadline、offline replay 默认无 provider
副作用、failure policy、fail-fast config、singleflight 与 ports 边界均有真实
assert 支撑。

本轮发现并修复：

1. 客户端取消绕过异常清理，导致 reservation/singleflight 泄漏；现释放预算、
   记录 499 audit/metric 后重新抛出取消。
2. output guardrail/settlement 错误路径会重复写 provider decision；现只写一次。
3. 空 profile 的 cache key 未使用 resolved default profile；现按解析后 profile。
4. reload 在 provider/profile/guardrail 变化时可能复用陈旧 cache；兼容条件已收紧。
5. reload 生命周期可能过早关闭在途请求资源；retired container 延迟到 shutdown，
   并按对象身份只关闭一次。
6. audit endpoint 可跨 client 读取；现 owner 不匹配返回 404。
7. settle 可静默超过 reservation；现严格拒绝、显式 502 语义并释放 reservation。
8. 多轮消息逐条均不超长时可绕过 aggregate max length；现先检查整段输入。
9. mock/fake provider 忽略 `max_tokens`；现内容与 usage 都受 completion envelope 限制。
10. 空 API key 会发送 `Authorization: Bearer `，且 provider client 继承本机代理；
    现省略空 header 并使用 `trust_env=False`。
11. 两副本同时启动会触发 PostgreSQL catalog race；migration 加事务 advisory lock。
12. PostgreSQL audit 将 SQLite 风格整数传给 boolean 列；adapter 现显式转换。

## 4. Dataset Experiments

### WildChat

- Source：6 个 Parquet shard，529,428 raw rows / 523,975 eligible rows。
- Corpus：500 samples，seed 42，确定性 reservoir sampling，过滤 source 标注的
  toxic/redacted 行和 turn；raw dataset 未修改。
- SHA-256：`4deda7c80fe7782d96ec715a24dcb85a09ff6602decf628ede889f6a2eeb52aa`。
- Workload：30 条分布请求；20 个 200、10 个预期 guardrail 400、0 个无法解释的
  5xx；request_id 30/30，audit 30/30；p50/p95/p99 =
  507.16/521.17/522.41 ms。Oracle PASS。
- Cache：20 unique × 3 得 20 provider calls + 40 hits；30 unique 全 miss；
  10 个相同并发请求仅 1 次本地 provider call。Oracle PASS。

### UltraChat

- Source：1 个 Parquet，23,110 raw/eligible rows。
- Corpus：500 samples，seed 42，multi-turn role/content normalization；raw 未修改。
- SHA-256：`a65c424aa218dee302e7a39632a65c3f74ceb43f33d61de7fadceb03c69f3620`。
- Workload/Oracle：short、medium、long 各 4/4 HTTP 200；very-long 4/4 被 aggregate
  input guardrail 以 HTTP 400 拒绝且 0 provider attempts；token estimate、延迟、
  RSS 与 audit bytes 均采集。Oracle PASS。

标签和完整方法见 `docs/test-cards/public-dataset-production-evidence.md`。

## 5. Failure Experiments

| Scenario | Workload/Fault | Oracle | Result |
| --- | --- | --- | --- |
| timeout | public-data payload，local provider timeout，2 attempts | 502、`provider_timeout`、audit/trace/metrics 一致 | PASS |
| HTTP 500 | 同一 payload，provider 500，2 attempts | 502、`provider_bad_status`、四角证据一致 | PASS |
| connection/DNS | `nonexistent.invalid` | 502、2 个 `provider_failed`、无隐藏成功 | PASS |
| fallback | primary 500 → mock fallback | 200、attempts=`bad_status,bad_status,success` | PASS |
| all exhausted | HTTP 500 + DNS provider | 502、4 attempts、完整 decision/audit | PASS |
| budget single | 接近 quota 的真实长度请求 | settle 后 reservation=0 | PASS |
| budget race | 100 limit 上两个并发 unique 请求 | status 恰为 200/429；used=52、reserved=0 | PASS |

Audit transaction 另以 attempt #2 trigger failure 注入，request 与 attempt row 均为
0；client cancellation、output guardrail、unexpected error 的 release 由回归测试覆盖。

## 6. Production Backend Status

| Backend | 状态 | 真实证据 | 尚未证明 |
| --- | --- | --- | --- |
| SQLite | `[TEST VERIFIED]` | WAL、多连接预算原子性、audit rollback、两本地进程共享 audit/budget | 跨主机 HA |
| Redis | `[TEST VERIFIED]` | Redis 7；两个 Uvicorn 交替 20 请求恰好 10 admit/10 reject；A miss → B hit | cluster/failover/TLS/eviction/outage |
| PostgreSQL | `[TEST VERIFIED]` | PG16；重复/并发 migration、80+15+15 race、rollback、双 replica 跨读 | HA、备份恢复、pool saturation、TLS |
| OTel | `[TEST VERIFIED]` | Collector Contrib 0.135.0 实收 success 3 spans、error/fallback 5 spans，无 body/key | sampling/retention/dashboard/alert |

未使用真实付费 LLM；第三方 provider 的 vendor-specific 行为标记 `[UNVERIFIED]`。

## 7. Evidence Matrix

| Claim | 代码 | 测试/实验 | Result |
| --- | --- | --- | --- |
| cache 不绕过 guardrail | `chat_service.py`, `prompt_cache.py` | governed-output + public repeat/singleflight | TEST VERIFIED |
| budget 并发不超额 | `token_budget_service.py`, SQLite/PG repos | 100-token race + PG 80+15+15 | TEST VERIFIED |
| settle 不 silent overshoot | budget service/repos | under/over/single-use/idempotent tests | TEST VERIFIED |
| audit 原子且 client scoped | SQLite/PG repos, requests route | injected attempt #2 failure + owner test | TEST VERIFIED |
| offline replay 无正常副作用 | `scripts/replay_request.py` | counting-provider test | TEST VERIFIED |
| retry 有整体 deadline | fallback/failure policy | timeout/fallback tests + HTTP fault experiment | TEST VERIFIED |
| config/reload 安全 | container/admin/main | fail-fast + cache invalidation + lifecycle tests | TEST VERIFIED |
| aggregate guardrail | guardrail/chat service | multi-turn aggregate max regression | TEST VERIFIED |
| Redis 全局限流/cache | Redis Lua/cache adapters | two-replica probe | TEST VERIFIED |
| PostgreSQL runtime | PG connection/repos/migration | disposable PG + two Uvicorn | TEST VERIFIED |
| OTel 真出口 | OTel recorder + collector config | collector debug export | TEST VERIFIED |
| 真实 workload 稳定 | corpus/experiment scripts | WildChat/UltraChat oracles | TEST VERIFIED |

## 8. Performance Results

环境：Windows 11 10.0.26200，Ryzen 9 7845HX（12C/24T），31.2 GiB RAM，
CPython 3.11.9；单个真实 Uvicorn、loopback local provider、SQLite。均为 bounded
workstation smoke/load evidence，不称为 production benchmark。

| Workload | Requests / C | Duration s | p50 / p95 / p99 ms | Error | Attempts | Retry amp. |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| constant | 40 / 8 | 1.817 | 345.73 / 416.61 / 424.60 | 0% | 1.0 | 0.0 |
| ramp | 30 / 8 | 1.348 | 344.50 / 359.01 / 401.17 | 0% | 1.0 | 0.0 |
| spike | 40 / 32 | 1.892 | 1109.27 / 1495.94 / 1515.74 | 0% | 1.0 | 0.0 |
| cache-heavy | 60 / 12 | 0.969 | 169.79 / 256.36 / 306.05 | 0% | 0.067 | 0.0 |
| cache-miss | 40 / 12 | 1.761 | 506.10 / 571.59 / 573.19 | 0% | 1.0 | 0.0 |
| long-context | 20 / 4 | 1.756 | 322.98 / 436.75 / 502.66 | 0% | 0.2 | 0.0 |
| provider-latency | 30 / 8 | 1.406 | 353.16 / 398.18 / 402.14 | 0% | 1.0 | 0.0 |
| provider-timeout | 20 / 4 | 1.114 | 176.19 / 402.81 / 408.97 | 0% | 2.2 | 0.2 |
| retry-storm | 20 / 4 | 1.216 | 231.36 / 296.62 / 302.23 | 0% | 2.2 | 0.2 |
| soak | 80 / 8 | 3.602 | 355.03 / 403.24 / 409.18 | 0% | 1.0 | 0.0 |

Duration 由保存的 request/RPS 反算并四舍五入；原始 JSON 中保留精确 elapsed、
RPS、cache/fallback/budget/rate、CPU/RSS 和 backend error 字段。完整表见
`docs/load-test-results-2026-08-23.md`。

## 9. Files Changed

- Runtime（21）：`ChatService`、budget/cache services、ports/errors、composition/
  startup/lifecycle、HTTP audit/admin、SQLite/PG repos、Redis limiter/cache、OTel、
  provider adapters。
- Tests（6 个文件，11 个新增 test）：integration chat、production hardening、
  token budget、prompt cache、HTTP provider、mock providers。
- Scripts（7）：corpus builder、dataset orchestrator、fault provider、load tool、
  Redis probe、PostgreSQL probe、final demos。
- Migration/deploy（2）：PostgreSQL migration hardening、OTel Collector config。
- Docs/root（8）：README、pyproject optional dependencies、architecture、backend
  status、test cards、load evidence、本报告。

具体文件以 `git status --short` 为准；未 reset/clean/覆盖用户原有修改。

## 10. Commands Actually Run

核心实际命令如下（disposable DB credential 被有意省略）：

```powershell
python scripts/build_gateway_corpus.py --source wildchat --samples 500 --seed 42
python scripts/build_gateway_corpus.py --source ultrachat --samples 500 --seed 42
.\.venv\Scripts\python.exe scripts\dataset_gateway_experiment.py --requests 30
.\.venv\Scripts\python.exe scripts\redis_replica_probe.py
.\.venv\Scripts\python.exe scripts\postgres_integration_probe.py --database-url <disposable-postgresql-url>
.\.venv\Scripts\python.exe scripts\load_test.py --scenario <scenario> --requests <n> --concurrency <c> --process-pid 46128 --output <json>
.\.venv\Scripts\python.exe -m compileall -q app scripts eval tests
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe eval\run_eval.py
.\.venv\Scripts\python.exe eval\run_eval.py --cases eval\security_cases.yaml
.\.venv\Scripts\python.exe scripts\demo.py
.\.venv\Scripts\python.exe scripts\final_demos.py
Get-FileHash -Algorithm SHA256 <generated-fixture>
git status --short
git diff --check
git diff --stat
```

还实际启动并移除了 disposable `redis:7`、`postgres:16`、
`otel/opentelemetry-collector-contrib:0.135.0` containers，并启动两个 Redis/
PostgreSQL Gateway replicas 与独立 local fault-provider Uvicorn。Clean reproduction
使用 `uv venv <temp> --python 3.11` 和 `uv pip install -e "<temp>[dev]"` 后重跑
compileall/pytest/Ruff/eval/security/demo/final demos，全部 exit 0。

## 11. Remaining Blockers

1. 外部付费 provider：受安全约束未使用 key；需要测试账户、预算与明确授权后才能
   验证 vendor latency/billing/protocol。当前 local OpenAI-compatible fault path 已完成。
2. 生产运维属性：当前只有 disposable runtime；需要目标网络与 SLO、TLS/secrets、
   HA、备份恢复、failover、监控告警和长期 soak 才能认证生产部署。
3. 分布式 singleflight：产品当前只要求共享 cache value；若要求全局 cold-miss
   合并，需要新增 Redis lock/lease 的业务语义。当前限制已明确记录。
4. 临时目录清理：精确解析后执行 `Remove-Item -LiteralPath ... -Recurse` 仍被本机
   策略拒绝；两个本轮生成的 clean-copy 目录留在用户 Temp，可手工删除，且不影响仓库。

除此之外没有当前环境内仍可安全完成却未完成的项目。已有无关 Docker container
`tasklab-test` 未触碰。

## 12. Manual Review Priorities

1. `app/application/services/chat_service.py`：reservation 的所有成功、错误、取消路径，
   以及 `provider_trace_recorded` 是否保持单写。
2. `app/application/services/token_budget_service.py`：reserve/settle/release 状态机与
   over-envelope HTTP 语义。
3. `app/infrastructure/persistence/sqlite/repositories.py`：原子 admission、settle 条件与
   request+attempt transaction。
4. `app/infrastructure/persistence/postgresql/repositories.py`：行锁/advisory-key 语义、
   boolean 映射、transaction rollback。
5. `app/infrastructure/persistence/postgresql/connection.py` 与
   `migrations/postgresql/001_initial.sql`：并发 migration lock、幂等 DDL/constraints。
6. `app/core/container.py`、`app/main.py`、`app/interfaces/http/routes/admin.py`：backend
   composition、hot-reload compatibility、retired resource lifetime/close-once。
7. `app/infrastructure/redis/rate_limiter.py`：Lua `INCR`/`PEXPIRE` 原子窗口及 key scope；
   `prompt_cache.py` 的 TTL/policy fingerprint。
8. `app/infrastructure/observability/tracing.py`：span attribute allowlist 与 exporter
   shutdown，确认未来修改不会加入 prompt/response/key。
9. `tests/test_production_hardening.py` 与 `tests/integration/test_chat_api.py`：取消、reload、
   audit ownership、aggregate guardrail、trace invariant 是否覆盖真实 failure mode。
10. `scripts/dataset_gateway_experiment.py`、`scripts/load_test.py` 与正式 test cards：
    workload 分类、oracle、非预期 HTTP 的非零退出、指标口径及“不夸大 benchmark”。
