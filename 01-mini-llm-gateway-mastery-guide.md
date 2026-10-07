# mini-llm-gateway 项目掌握手册

> 目标：从“代码在这里”走到“可以独立解释、调试、修改并接受面试追问”。  
> 证据基线：2026-08-16，当前工作树（不是只看 `HEAD`）。  
> 当前分支：`m3-routing-fallback`；当前 commit：`53cdf41cd65739927c7a85d809e602253e5d930c`。  
> 重要：考古时工作树已有 **47 个 tracked modified 项与 51 个 untracked 路径**。因此本文描述的是“当前工作树里的真实代码”，不能假定这些实现已经包含在上述 commit 中。

## 使用方法与证据等级

每轮控制在 60–90 分钟。不要提前读下一轮；每轮结束先填写 Learning Checkpoint，再让 ChatGPT/Codex 追问。

- `[TEST VERIFIED]`：当前代码存在，并有明确自动化测试；本次实际执行相应测试通过。
- `[CODE VERIFIED]`：已从当前代码确认，但没有找到足以证明该结论的自动化测试。
- `[MANUALLY VERIFIED]`：本次仓库考古实际运行过命令或脚本并观察到结果。
- `[DOC ONLY]`：只在 README/旧文档中看到，不能当成实现事实。
- `[UNVERIFIED]`：代码或设计可能支持，但没有当前测试或现场证据，或存在需要实验才能确认的边界。
- `[ROADMAP]`：当前未实现，仅是后续计划。

证据等级不要混读：`[TEST VERIFIED]` 只说明测试覆盖的具体断言，不自动证明高并发、真实网络、跨进程或 production-ready。

---

## 0. 当前仓库证据快照

### 0.1 仓库与运行基线

| 项目 | 当前证据 |
| --- | --- |
| 当前目录 | `D:\面试\github-projects\mini-llm-gateway` `[MANUALLY VERIFIED]` |
| 分支 / commit | `m3-routing-fallback` / `53cdf41cd65739927c7a85d809e602253e5d930c` `[MANUALLY VERIFIED]` |
| 工作树 | 非干净；本文基于工作树而非仅基于 commit `[MANUALLY VERIFIED]` |
| 主要语言/版本 | Python `>=3.11`；本次使用 Python 3.11.9 `[CODE VERIFIED]` `[MANUALLY VERIFIED]` |
| Web 框架 | FastAPI + Uvicorn；Pydantic v2；httpx `[CODE VERIFIED]` |
| 依赖入口 | `pyproject.toml`；未发现 requirements/Poetry/Pipenv/uv lock file `[CODE VERIFIED]` |
| 应用入口 | `app/main.py:app`；工厂为 `app.main:create_app` `[CODE VERIFIED]` |
| 启动命令 | `.venv\Scripts\python.exe -m uvicorn app.main:app --reload` 或 `make dev` `[CODE VERIFIED]` |
| 测试入口 | `.venv\Scripts\python.exe -m pytest -q` / `make test` `[CODE VERIFIED]` |
| 数据库 | SQLite，默认 `data/gateway.db`，WAL + foreign keys `[CODE VERIFIED]` |
| schema/migration | `app/infrastructure/persistence/sqlite/schema.py` + `connection.py:init_db/_ensure_column`；无独立 migrations 目录 `[CODE VERIFIED]` |
| 主要进程 | 一个 Uvicorn/FastAPI gateway 进程；provider 是进程内对象或出站 HTTP adapter `[CODE VERIFIED]` |
| 容器 | `Dockerfile` + 单服务 `docker-compose.yml`，映射 `8000:8000`、挂载 config/data `[CODE VERIFIED]` |
| composition root | `app/core/container.py:build_container` `[CODE VERIFIED]` |
| 当前测试结果 | 84 collected，84 passed in 8.84s `[MANUALLY VERIFIED]` |
| 其他现场结果 | demo 10/10、eval 7/7、安全 eval 8/8、ruff clean `[MANUALLY VERIFIED]` |
| replay 现场结果 | 对已有非缓存请求 `213252...` 比较得到 PASS `[MANUALLY VERIFIED]` |

README 两处写着“82 tests”；当前实际收集是 84。这里应以测试收集结果为准。`[DOC ONLY]`

### 0.2 核心模块

- HTTP：`app/interfaces/http/routes/chat.py`、`requests.py`、`admin.py`、`metrics.py`；鉴权在 `dependencies/auth.py`；request_id 在 `middleware.py`。`[CODE VERIFIED]`
- Application orchestrator：`app/application/services/chat_service.py:ChatService.chat`。`[TEST VERIFIED]`
- Provider boundary：`app/domain/ports/provider_port.py:ProviderPort`，实现由 `provider_registry.py:build_provider_registry` 创建。`[TEST VERIFIED]`
- Routing/Profile：`app/application/services/routing_service.py:RoutingService.resolve_candidates` + `app/domain/models/model_profile.py` + `app/infrastructure/config/mapper.py`。`[TEST VERIFIED]`
- Failure path：`fallback_service.py:FallbackService` + `circuit_breaker.py:CircuitBreaker` + provider domain errors。`[TEST VERIFIED]`
- Governance：`rate_limiter.py`、`token_budget_service.py`、`token_estimator.py`、`prompt_cache.py`、`guardrail_service.py`。`[TEST VERIFIED]`
- Audit/Persistence：`request_log_service.py`、`sqlite/schema.py`、`sqlite/repositories.py`。`[TEST VERIFIED]`
- Explainability/Replay：`decision_trace.py`、`ChatService._build_provider_trace/replay`、`scripts/replay_request.py`。`[TEST VERIFIED]`（仅测试到 `ChatService.replay` 的基本成功路径；CLI 的完整回归比较见现场证据）

### 0.3 已验证能力

- `/v1/chat` happy path、鉴权、request_id 响应头、priority routing、mock provider 调用。`[TEST VERIFIED]`
- provider error/模拟 timeout 后 retry 与下一候选成功；attempt 链返回和持久化。`[TEST VERIFIED]`
- circuit breaker 单元状态机 closed/open/half-open。`[TEST VERIFIED]`
- rate limit、token budget、输入 guardrail、stream 拒绝、profile 404。`[TEST VERIFIED]`
- exact cache miss → hit、hit 时 attempts 为空、decision trace 基本内容。`[TEST VERIFIED]`
- audit 查询、SQLite token usage、metrics、admin config key 脱敏。`[TEST VERIFIED]`
- OpenAI-compatible adapter 的成功解析、非 200、连接错误映射。`[TEST VERIFIED]`
- 未预料 provider 异常继续 fallback；pipeline 未预料异常写 audit 并转 `InternalError`。`[TEST VERIFIED]`

### 0.4 未验证或不能扩大声称的能力

- 真实 OpenAI/Ollama/vLLM 端到端调用、真实网络 timeout、真实模型质量。`[UNVERIFIED]`
- 多 worker/多 replica 的 rate limit、cache、circuit、metrics 一致性。`[UNVERIFIED]`
- budget 的并发原子性和“预检查后输出导致超额”边界。`[UNVERIFIED]`
- SQLite 锁竞争、吞吐、崩溃恢复，以及 request log 与 attempts 的事务完整性。`[UNVERIFIED]`
- admin hot reload 的并发切换、旧 provider `AsyncClient` 释放、状态迁移。`[UNVERIFIED]`
- audit endpoint 的租户隔离：代码只验证 API key，不校验该 request_id 是否属于当前 client。`[CODE VERIFIED]`
- streaming 实现不存在；当前只支持拒绝 `stream: true`。`[TEST VERIFIED]`
- `gateway.request_timeout_ms` 只被解析，没有进入调用路径。`[CODE VERIFIED]`
- `fallback.chain` 和 `fallback.trigger_on` 被解析/映射，但 `FallbackService.execute` 实际使用传入的 `routing.candidates`，没有读取这两个字段。`[CODE VERIFIED]`
- `OpenAICompatibleProvider.close()` 存在，但应用 lifespan 没有调用它。`[CODE VERIFIED]`

### 0.5 README/文档声明与当前代码差异

- “every call writes request_logs + provider_attempts”不准确：鉴权发生在 `ChatService` 之前，auth 失败只增加 metric 并返回 401，不会进入 `RequestLogService`；FastAPI schema 422 也不进入它。`[CODE VERIFIED]`
- `docs/architecture.md` 的 lifecycle 把 budget 写在 cache 前，当前 `ChatService.chat` 实际是 guardrail → token estimate/cache →（miss 才）budget。`[DOC ONLY]`
- README 把 `/v1/requests/{id}` 描述成“replays the full attempt chain”，实际 endpoint 只是读取历史记录；真正重新执行在 `scripts/replay_request.py` / `ChatService.replay`。`[CODE VERIFIED]`
- README 的 `X-RateLimit-*` 声称未在 HTTP 响应代码中找到；只确认 429 时可能设置 `Retry-After`。`[CODE VERIFIED]`
- config 中 Ollama/vLLM provider 默认注释且 disabled；adapter 存在不等于真实服务已验证。`[CODE VERIFIED]`

### 0.6 Roadmap/未实现

- semantic cache。`[ROADMAP]`
- Redis-backed cache 与 distributed rate limiter。`[ROADMAP]`
- SSE streaming。`[ROADMAP]`
- OpenTelemetry + GenAI semantic attributes。`[ROADMAP]`

---

## 1. 最终学会标准

完成全部 Round 后，你必须能不看资料回答并现场指向证据：

1. `/v1/chat` 从 ASGI middleware 到 response model 的完整真实函数链是什么？
2. `/v1/chat/completions` 与 `/v1/chat` 复用哪段逻辑，又丢掉了哪些治理元数据？
3. 为什么 `ChatService` 依赖 `ProviderPort` 字典，而不是 import `MockFastProvider`？
4. `config.yaml` 如何经过 `AppConfig.from_dict`、mapper、container 变成可调用 provider 顺序？
5. 当前真正驱动 fallback 顺序的是哪个字段？`fallback.chain/trigger_on` 当前到底有没有执行语义？
6. retry、fallback、circuit breaker 的作用域分别是什么？一次失败如何改变 attempt 和 circuit state？
7. mock timeout 与 httpx 真实 timeout 分别在哪里产生和转换？`request_timeout_ms` 为什么不能说已生效？
8. streaming、rate limit、profile、input guardrail、cache、budget、routing/provider、output guardrail、commit、audit 的准确顺序是什么？
9. 为什么 rate limit 与 token/cost budget 不是同一件事？它们分别存在哪里、何时更新？
10. `request_id` 如何进入 contextvar、响应头、错误体、request_logs 和 provider_attempts？哪些失败不会被 audit？
11. decision trace 保存哪些步骤？哪些信息是解释性派生值而不是 provider 原始事实？
12. replay 重放什么、跳过什么、仍会产生什么副作用？为什么 cache-hit 历史可能产生比较差异？
13. SQLite/in-memory 状态在单进程、multi-worker、multi-replica 下分别有什么边界？
14. 如何新增 OpenAI-compatible/vLLM/Ollama provider，最小修改哪些文件、什么情况下只改 config？
15. 84 个测试真实证明了什么，又没有证明什么？为什么不能声称 production-ready？

---

## 2. 项目最小系统地图

```text
Client
  -> RequestContextMiddleware.__call__                 app/interfaces/http/middleware.py
  -> require_api_key                                   app/interfaces/http/dependencies/auth.py
  -> chat / chat_completions                           app/interfaces/http/routes/chat.py
  -> _to_domain_request -> ChatRequest                 app/domain/ports/provider_port.py
  -> AppContainer.chat_service                         app/core/container.py
  -> ChatService.chat                                  app/application/services/chat_service.py
       -> RateLimiter.check
       -> _resolve_profile -> ModelProfile
       -> GuardrailService.check_input
       -> PromptCache.get
       -> TokenBudgetService.ensure_capacity           (cache miss only)
       -> RoutingService.resolve_candidates
       -> FallbackService.execute
            -> CircuitBreaker.allow_request
            -> ProviderPort.chat
                 -> BaseMockProvider.chat OR OpenAICompatibleProvider.chat
            -> ProviderAttempt[]
       -> GuardrailService.check_output
       -> TokenBudgetService.commit
       -> PromptCache.put
       -> RequestLogService.record_success/error
            -> request_logs + provider_attempts (SQLite)
  -> ChatOutcome
  -> ChatResponseOut OR ChatCompletionOut
  -> RequestContextMiddleware adds X-Request-ID
```

`[CODE VERIFIED]` `/v1/chat/completions` 不是独立 application 流程；它把 `payload.model` 同时作为 logical profile 与 outbound model 传入，再调用同一个 `ChatService.chat`。

`[CODE VERIFIED]` cache hit 是一条早返回支路：不会 routing、provider、output guardrail 或 budget check/commit；会写一条 success audit，attempts 为空，budget_before/after 为 null。

`[CODE VERIFIED]` auth 是 `ChatService` 之外的 FastAPI dependency，因此不在上面的 audit try/except 内。

---

## 3. 12 轮学习路线总览

| Round | 主题 | 时间 | 本轮新增概念 |
| --- | --- | --- | --- |
| 0 | 启动、入口与最小请求 | 60–75 分钟 | app factory、lifespan、container、TestClient |
| 1 | `/v1/chat` Happy Path | 75–90 分钟 | schema→domain→outcome、pipeline、I/O |
| 2 | ProviderPort 与依赖注入 | 60–90 分钟 | port、adapter、registry、composition root |
| 3 | Model Profile 与 Routing | 60–75 分钟 | config mapping、priority、candidate order、失效配置 |
| 4 | Retry/Fallback/Circuit Failure Path | 75–90 分钟 | error normalization、retry scope、fallback scope、circuit state |
| 5 | Governance Pipeline | 75–90 分钟 | rate、budget、cache、guardrail、token estimate |
| 6 | Audit / Attempt / Decision Trace | 75–90 分钟 | request_id、audit rows、attempt rows、trace |
| 7 | Replay / Regression Replay | 60–90 分钟 | replay payload、re-execution、comparison、side effect |
| 8 | Persistence 与 Multi-replica Boundary | 75–90 分钟 | WAL、atomicity、process-local state、consistency |
| 9 | Tests as Specification | 60–90 分钟 | fixture、unit/integration/eval、positive/negative evidence |
| 10 | Failure Lab | 90 分钟 | timeout lab、breaker lab、cache/audit lab |
| 11 | 亲手修改 + Interview | 75–90 分钟 | change slicing、test-first、production boundary、口述 |

---

### Round 0：项目如何启动 + 最小请求

#### 这一轮为什么学

先证明“程序如何成为一个可请求的对象”，解决入口、配置、数据库和依赖装配从哪里发生的问题；这一轮不解释架构名词。

#### 本轮只看什么

- `pyproject.toml`
- `Makefile`
- `Dockerfile`
- `docker-compose.yml`
- `app/main.py`
- `app/core/settings.py`
- `app/core/startup.py`
- `app/core/container.py`
- `app/interfaces/http/routes/health.py`
- `tests/integration/test_health.py`

#### 本轮暂时不要看什么

不要看 `ChatService`、routing、fallback、SQLite repository 细节、ADRs、roadmap。

#### 真实调用链

`python -m uvicorn app.main:app` → import `app.main:app` → `create_app()` → FastAPI lifespan → `bootstrap()` → `load_config()` → `init_db()` → `build_container()` → `app.state.container` → `health_check()` → `HealthResponse`。

#### 这一轮只掌握 3–5 个概念

1. module-level `app` 与 `create_app()` 的区别。
2. FastAPI lifespan 何时执行 bootstrap。
3. composition root 只是“对象装配地点”。
4. config path/database path 的默认值与环境变量前缀 `GW_`。

#### 给 ChatGPT / Codex 的学习提示词

```text
只带我学习 mini-llm-gateway 的 Round 0。只分析 pyproject.toml、Makefile、Dockerfile、docker-compose.yml、app/main.py、app/core/settings.py、app/core/startup.py、app/core/container.py、app/interfaces/http/routes/health.py、tests/integration/test_health.py。所有结论必须引用真实文件和函数。先让我自己追述从 uvicorn import 到 /health 的调用链，再解释最多 4 个概念。无法由代码或测试证明的内容写“未验证”。不要直接替我总结答案。最后只问我 5 个检查题，不给答案。
```

#### 我必须亲手完成

1. 执行：`.venv\Scripts\python.exe --version`、`.venv\Scripts\python.exe -m pytest tests/integration/test_health.py -q`。
2. 启动：`.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000`。
3. HTTP/httpx 路径：

   ```powershell
   .venv\Scripts\python.exe -c "import httpx; r=httpx.get('http://127.0.0.1:8000/health'); print(r.status_code, r.json(), r.headers.get('x-request-id'))"
   ```

4. HTTP/urllib 路径：

   ```powershell
   .venv\Scripts\python.exe -c "import json,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/health'); print(r.status, json.load(r), r.headers.get('x-request-id'))"
   ```

5. 停止服务后，把 `GW_DATABASE_PATH` 指向临时目录再启动，观察 `bootstrap()` 日志；不要删除或覆盖仓库现有 `data/gateway.db`。

#### 本轮代码证据

- `app/main.py` 中 lifespan 把 container 放到 `app.state.container`。
- `app/core/startup.py:bootstrap` 依次 load config、setup logging、init DB、build container。
- `Makefile:dev` 与 Docker CMD 都指向 `app.main:app`。
- health 测试只证明 `/health` 返回预期内容，不证明 chat pipeline。

#### 完成标准

在白板上不看代码画出“Uvicorn import → lifespan → bootstrap → container → route”，并能现场指出每个箭头对应的函数；能用 httpx 与 urllib 各完成一次 health 请求。

#### 5 道检查题

1. 为什么 `create_app(container=...)` 对测试有用？
2. `bootstrap()` 在 import 时还是 lifespan 时执行？
3. config 和 database 的默认路径分别在哪里定义？
4. Docker Compose 持久化了哪两个目录，哪个是只读？
5. `/health` 是否依赖 `ChatService`？如何从代码证明？

#### Learning Checkpoint

- 我追的链路：
uvicorn app.main:app
→ import app.main
→ module-level app = create_app()
→ create_app()
→ 创建 FastAPI app + 注册 lifespan + routers
→ application lifespan startup
→ bootstrap()
→ load_config()
→ setup_logging()
→ init_db()
→ build_container()
→ AppContainer
→ app.state.container
→ GET /health
→ health_check()
→ HealthResponse
- 入口：
app.main:app
- 核心函数：
create_app()
lifespan()
bootstrap()
load_config()
build_container()
health_check()
- 输入：
启动：
config_path
database_path
settings / GW_* 环境变量

/health：
GET /health
- 输出：
启动阶段：

AppContainer
→ app.state.container

HTTP 阶段：

{
  "status": "ok",
  "service": "mini-llm-gateway"
}

- I/O：
读取配置文件：config/config.yaml
初始化 SQLite：data/gateway.db


HTTP：
GET /health
→ HTTP response

其中 YAML loader 和 init_db() 的内部实现不属于本轮文件范围，因此内部细节 未验证。
- 新理解：
create_app() 是 app factory，module-level app 是真正交给 Uvicorn 的 FastAPI object。
create_app() 只是注册 lifespan；bootstrap() 在 lifespan startup 才执行。
bootstrap() 是启动协调者，build_container() 是它调用的 runtime 对象装配函数。
config/database path 来自函数参数或 settings，不是来自 AppContainer。
AppContainer 是 build_container() 的输出，最后挂到 app.state.container。
health_check() 本身不依赖 ChatService，但默认应用 startup 会创建 ChatService。
测试通过只能证明它实际 assert 的东西，不能自动扩大为整个系统已经验证。
- 未确认：
- Docker / Docker Compose 是否真实 build + run：未验证
- 真实 Uvicorn TCP 请求链：本轮未现场验证
- 当前 ASGITransport 测试是否触发 lifespan：现有测试断言未证明
- YamlConfigLoader 内部解析过程：本轮未验证
- init_db() 内部 SQLite schema/初始化过程：本轮未验证
- ChatService 内部请求 pipeline：本轮不学习
- 亲手验证证据：
- 下一轮第一步：

---

### Round 1：`/v1/chat` Happy Path

#### 这一轮为什么学

回答最核心问题：一个成功请求进入 HTTP 后真实经过哪些函数，以及 schema、domain DTO、application outcome、HTTP response 怎样转换。

#### 本轮只看什么

- `app/interfaces/http/middleware.py`
- `app/interfaces/http/dependencies/auth.py`
- `app/interfaces/http/dependencies/container.py`
- `app/interfaces/http/routes/chat.py`
- `app/interfaces/http/schemas/chat.py`
- `app/domain/ports/provider_port.py`
- `app/application/dto/chat_dto.py`
- `app/application/services/chat_service.py`
- `tests/integration/test_chat_api.py::test_chat_success`

#### 本轮暂时不要看什么

暂时不要展开 fallback/circuit、SQLite SQL、admin、metrics、replay。

#### 真实调用链

HTTP POST `/v1/chat` → `RequestContextMiddleware.__call__` → `require_api_key` → route `chat()` → `_to_domain_request()` → `ChatService.chat()` → success pipeline → `ChatOutcome` → `ChatResponseOut` → middleware 添加 `x-request-id` → JSON response。

Happy path 内部准确顺序：`_enforce_streaming` → `_enforce_rate_limit` → `_resolve_profile` → `_enforce_guardrails_input` → estimate + cache miss → budget ensure → routing → fallback/provider → output guardrail → budget commit → cache put → audit → metrics → return。

#### 这一轮只掌握 3–5 个概念

1. HTTP schema 与 domain dataclass 的边界。
2. FastAPI dependency 先于 route body 执行。
3. orchestrator 负责顺序，不负责 provider 细节。
4. `ChatOutcome` 到两个 HTTP response shape 的映射。
5. request_id 的 contextvar 与响应头传播。

#### 给 ChatGPT / Codex 的学习提示词

```text
只带我学习 Round 1：/v1/chat Happy Path。只使用 app/interfaces/http/middleware.py、dependencies/auth.py、dependencies/container.py、routes/chat.py、schemas/chat.py、app/domain/ports/provider_port.py、app/application/dto/chat_dto.py、app/application/services/chat_service.py、tests/integration/test_chat_api.py::test_chat_success。先让我逐函数追调用链，再解释最多 5 个概念。每个结论引用文件/函数/test；无法证明写“未验证”。不要直接替我总结答案。最后只问 5 个检查题，不给答案。
```

#### 我必须亲手完成

1. 用唯一 prompt 发一次 `/v1/chat`，保存 JSON，圈出 `request_id/provider/attempts/decision_trace/budget_*`。
2. httpx 路径：

   ```powershell
   .venv\Scripts\python.exe -c "import httpx,json; p={'profile':'fast-chat','messages':[{'role':'user','content':'round1-unique'}]}; r=httpx.post('http://127.0.0.1:8000/v1/chat',json=p,headers={'Authorization':'Bearer demo-key'}); print(r.status_code,r.headers.get('x-request-id')); print(json.dumps(r.json(),ensure_ascii=False,indent=2))"
   ```

3. urllib 路径：

   ```powershell
   .venv\Scripts\python.exe -c "import json,urllib.request; p=json.dumps({'profile':'fast-chat','messages':[{'role':'user','content':'round1-urllib'}]}).encode(); q=urllib.request.Request('http://127.0.0.1:8000/v1/chat',data=p,headers={'Authorization':'Bearer demo-key','Content-Type':'application/json'}); r=urllib.request.urlopen(q); print(r.status,r.headers.get('x-request-id')); print(json.dumps(json.load(r),ensure_ascii=False,indent=2))"
   ```

4. 在 `chat()`、`ChatService.chat()`、`RequestLogService.record_success()` 设置断点；只观察，不提交临时改动。
5. 执行目标测试：`.venv\Scripts\python.exe -m pytest tests/integration/test_chat_api.py::test_chat_success -q`。

#### 本轮代码证据

- request body 先成为 `ChatRequestIn`，再由 `_to_domain_request` 变成 `ChatRequest`。
- auth failure 发生在 `ChatService` 之前，因此不由它写 audit。
- response header `x-request-id` 与 `/v1/chat` body `request_id` 在 happy path 相同，测试有断言。
- `/v1/chat/completions` 返回简化 OpenAI shape，不回传 attempts/decision trace/budget。

#### 完成标准

不看资料口述完整 happy path，准确说出至少 8 个函数/对象，并能解释每次转换的输入输出；现场用 request_id 把响应头和响应体对上。

#### 5 道检查题

1. API key 在哪个函数解析，失败后为什么没有 request audit？
2. `profile` 为空时最终默认值在哪里解析？
3. `ChatOutcome` 与 `ChatResponseOut` 为什么不是同一个类？
4. cache hit 时 happy path 从哪里提前返回？
5. `/v1/chat/completions` 把 `model` 如何传给 domain request？

#### Learning Checkpoint

- 我追的链路：
- 入口：
- 核心函数：
- 输入：
- 输出：
- I/O：
- 新理解：
- 未确认：
- 亲手验证证据：
- 下一轮第一步：

---

### Round 2：Provider abstraction + dependency injection

#### 这一轮为什么学

回答“application service 为什么不直接依赖具体 provider”和“真实抽象边界在哪里”，并学会从 config 找到最终对象实例。

#### 本轮只看什么

- `app/domain/ports/provider_port.py`
- `app/domain/models/provider.py`
- `app/infrastructure/providers/base.py`
- `app/infrastructure/providers/mock_fast.py`
- `app/infrastructure/providers/fake_static.py`
- `app/infrastructure/providers/openai_compatible.py`
- `app/infrastructure/providers/provider_registry.py`
- `app/core/container.py`
- `tests/unit/test_providers.py`
- `tests/unit/test_openai_compatible_provider.py`
- `tests/unit/test_config_and_registry.py`

#### 本轮暂时不要看什么

不要读 guardrail/cache/audit/replay；不要先背 Clean Architecture 定义。

#### 真实调用链

`config.yaml providers` → `AppConfig.from_dict` → `build_provider_registry()` → concrete `ProviderPort` instances → `build_container()` 将 registry 注入 `FallbackService` 与 `ChatService` → `FallbackService._call_provider()` → polymorphic `provider.chat()` → `ChatResponse` 或 domain error。

#### 这一轮只掌握 3–5 个概念

1. port 的最小合同：`chat/provider_id/provider_type`。
2. adapter 负责把外部协议转换成 domain response/error。
3. registry 负责“类型/配置到实例”的选择。
4. composition root 是唯一集中知道 concrete classes 的位置之一。
5. test double 与真实 HTTP adapter 可被同一 fallback 处理。

#### 给 ChatGPT / Codex 的学习提示词

```text
只带我学习 Round 2 的 ProviderPort、adapter、registry 和 composition root。只分析本轮列出的真实文件。先让我从 config provider 条目追到 provider.chat 的调用链，再解释最多 5 个概念。所有结论引用具体类/函数/test；真实网络没有证据时写“未验证”。不要直接替我总结答案。最后只问 5 个检查题，不给答案。
```

#### 我必须亲手完成

1. 执行 `rg -n "ProviderPort|build_provider_registry|provider.chat" app tests`，给每个命中分“定义/装配/调用/测试”。
2. 在 Python REPL 调 `bootstrap()`，打印 `{id: type(p).__name__ for id,p in container.providers.items()}`。
3. 执行：`.venv\Scripts\python.exe -m pytest tests/unit/test_providers.py tests/unit/test_openai_compatible_provider.py tests/unit/test_config_and_registry.py -q`。
4. 画一张不超过 6 个节点的图：`ChatService → FallbackService → ProviderPort → Mock/OpenAI adapter`。

#### 本轮代码证据

- `ChatService`/`FallbackService` 类型依赖是 `dict[str, ProviderPort]`，不直接构造 concrete provider。
- `OpenAICompatibleProvider.chat` 把 httpx timeout/request error/non-200 转成三个 domain errors。
- 自动化测试没有覆盖 `httpx.TimeoutException` 分支，也没有访问真实 OpenAI/Ollama/vLLM。
- 未知 `type: mock` provider id 会退化为 `MockFastProvider`，但该实例内部 provider_id 固定为 `mock_fast`；这是新增 provider 时必须注意的语义。

#### 完成标准

能不使用“解耦”空话，具体说明：如果新增 adapter，哪一层变化、哪一层不变、错误必须转换成什么；能指出 registry 与 container 各自责任。

#### 5 道检查题

1. `ProviderPort.chat` 允许抛出哪些预期 domain error？
2. 谁把 `ProviderConfig` 变成 `ProviderBehavior`？
3. OpenAI-compatible URL 是怎样拼接的？
4. 为什么只实现 `ProviderPort` 还不够，通常还要注册 factory？
5. 哪些测试只用了 `httpx.MockTransport`，所以不能证明真实网络可用？

#### Learning Checkpoint

- 我追的链路：
- 入口：
- 核心函数：
- 输入：
- 输出：
- I/O：
- 新理解：
- 未确认：
- 亲手验证证据：
- 下一轮第一步：

---

### Round 3：Model Profile + Routing

#### 这一轮为什么学

回答 model profile 如何决定候选 provider，并识别“配置看起来存在”与“配置真正参与执行”的差别。

#### 本轮只看什么

- `config/config.yaml`
- `app/infrastructure/config/config_models.py`
- `app/infrastructure/config/yaml_config_loader.py`
- `app/infrastructure/config/mapper.py`
- `app/domain/models/model_profile.py`
- `app/application/services/routing_service.py`
- `app/application/services/chat_service.py::_resolve_profile`
- `app/application/services/chat_service.py` 中 routing 调用处
- `app/application/services/fallback_service.py::execute`
- `tests/unit/test_routing_service.py`
- `tests/unit/test_config_and_registry.py`

#### 本轮暂时不要看什么

不要展开 retry/backoff/circuit；不要把 `docs/architecture.md` 当执行证据。

#### 真实调用链

YAML `model_profiles` → `YamlConfigLoader.load` → `AppConfig.from_dict` → `profile_config_to_domain` → `AppContainer.profiles` → `ChatService._resolve_profile` → `RoutingService.resolve_candidates` 按 priority 升序 → `FallbackService.execute(candidate_order)`。

#### 这一轮只掌握 3–5 个概念

1. logical profile 与 physical provider。
2. config dataclass → domain model mapping。
3. priority 数字越小越先执行，Python sort 保持同优先级原顺序。
4. 当前只真正实现 priority；未知 strategy 保留配置顺序。
5. dead/partial config：fallback chain 与 trigger 并不驱动当前执行。

#### 给 ChatGPT / Codex 的学习提示词

```text
只带我学习 Round 3 的 config→profile→routing→candidate_order。先让我手工预测 fast-chat、fallback-chat、timeout-chat 的候选顺序，再逐函数核对。所有结论必须引用 config 字段、mapper、RoutingService、FallbackService 和具体测试。无法证明写“未验证”。特别检查 fallback.chain/trigger_on 是否真的被读取。不要直接替我总结答案。最后只问 5 个检查题，不给答案。
```

#### 我必须亲手完成

1. 手写三个 profile 的 routing 候选与 fallback 配置，先不运行。
2. 在 REPL 调 `container.routing.resolve_candidates(container.profiles['fallback-chat'])`，与手写结果比对。
3. 执行：`.venv\Scripts\python.exe -m pytest tests/unit/test_routing_service.py tests/unit/test_config_and_registry.py -q`。
4. 搜索 `fallback.chain`、`trigger_on` 的读取位置；把“被解析”和“被执行”分别列出来。
5. 只做临时内存实验：构造 routing candidates 与 fallback chain 不一致的 `ModelProfile`，调用 `resolve_candidates()`，确认谁决定顺序；不要改仓库配置。

#### 本轮代码证据

- `RoutingService.resolve_candidates` 是当前唯一路由算法入口。
- `preferences/capabilities/intent` 会进入 domain profile，但 routing 算法不读取它们。
- `FallbackService.execute` 只检查 `profile.fallback.enabled`；顺序来自参数 `candidate_order`。
- 因此不能声称当前按 cost/latency/capability 动态路由，也不能声称 `fallback.trigger_on` 控制了 fallback。

#### 完成标准

给任意 profile 配置，能在 2 分钟内预测 provider 顺序并指出实际读取字段；面对“为什么 fallback chain 是 X”追问时，能诚实解释当前配置与执行的偏差。

#### 5 道检查题

1. `default_profile` 在哪个函数生效？
2. priority 相同会如何排序，有哪个测试？
3. `capabilities.supports_streaming` 是否参与 streaming 判定？
4. fallback disabled 时为什么仍会构建完整 candidate list？最终在哪里截断？
5. 当前 `fallback.chain` 若与 routing candidates 不同，会以哪一个为准？

#### Learning Checkpoint

- 我追的链路：
- 入口：
- 核心函数：
- 输入：
- 输出：
- I/O：
- 新理解：
- 未确认：
- 亲手验证证据：
- 下一轮第一步：

### Round 4：Retry / Fallback / Circuit Breaker Failure Path

#### 这一轮为什么学

把三个容易混用的机制拆开：retry 是同一 provider 再试，fallback 是换候选，circuit breaker 是暂时拒绝调用；同时追清 timeout 的产生、转换、记录与 HTTP 映射。

#### 本轮只看什么

- `app/domain/errors.py`
- `app/domain/models/provider.py`
- `app/infrastructure/providers/base.py`
- `app/infrastructure/providers/mock_slow.py`
- `app/infrastructure/providers/openai_compatible.py`
- `app/application/services/fallback_service.py`
- `app/application/services/circuit_breaker.py`
- `app/application/services/chat_service.py::_build_provider_trace`
- `app/application/services/chat_service.py::_attempts_from_error`
- `app/interfaces/http/exception_handlers.py`
- `tests/unit/test_fallback_service.py`
- `tests/unit/test_circuit_breaker.py`
- `tests/integration/test_chat_api.py::test_chat_timeout_fallback`
- `tests/unit/test_unexpected_errors.py`

#### 本轮暂时不要看什么

不要研究 budget/cache/SQLite schema/replay；不要用 README 的“resilience”术语代替逐函数解释。

#### 真实调用链

`ChatService.chat` → `RoutingService.resolve_candidates` → `FallbackService.execute` → 对每个 candidate 调 `_try_provider` → `CircuitBreaker.allow_request` → `_call_provider` → `ProviderPort.chat` → domain error → `ProviderAttempt` → `CircuitBreaker.record_failure` → 若 error_code 在 retry_on 则 `_backoff_ms` + 同 provider 重试 → exhausted 后下一 candidate → 首次 success 返回；全部失败则 `FallbackExhaustedError.attempts` → `ChatService` audit → exception handler 映射 502。

Timeout 两条真实来源：

- mock：`BaseMockProvider.chat` 先 sleep，再由 `MockSlowProvider._should_timeout()` 返回 true，显式抛 `ProviderTimeoutError`；这不是网关 deadline。`[CODE VERIFIED]`
- real adapter：`httpx.TimeoutException` → `OpenAICompatibleProvider.chat` 捕获 → `ProviderTimeoutError`。`[CODE VERIFIED]`（timeout 分支未找到专门测试）

#### 这一轮只掌握 3–5 个概念

1. error normalization：不同 adapter 转成统一 domain error。
2. retry index 与 candidate attempt order 是两个维度。
3. circuit closed/open/half-open 状态机。
4. fallback exhausted 如何携带 attempts 进入 audit。
5. “timeout 配置”与“真实被 enforce 的 timeout”必须分开证明。

#### 给 ChatGPT / Codex 的学习提示词

```text
只带我学习 Round 4。用当前代码把一个 mock_slow timeout 从产生、转换、retry、circuit 计数、fallback、attempt 记录、decision trace 一直追到 HTTP/audit。先调用链后概念，最多 5 个概念。每个结论引用真实函数/test；区分 mock 模拟 timeout、httpx timeout、未使用的 gateway.request_timeout_ms。无法证明写“未验证”。不要直接替我总结答案。最后只问 5 个检查题，不给答案。
```

#### 我必须亲手完成

1. 执行目标测试：

   ```powershell
   .venv\Scripts\python.exe -m pytest tests/unit/test_fallback_service.py tests/unit/test_circuit_breaker.py tests/integration/test_chat_api.py::test_chat_timeout_fallback tests/unit/test_unexpected_errors.py -q
   ```

2. 对 `/v1/chat` 发 `timeout-chat`，记录 attempts 的 `(provider_id, attempt_order, retry_index, status, error_code)`。
3. httpx 路径：

   ```powershell
   .venv\Scripts\python.exe -c "import httpx,json; p={'profile':'timeout-chat','messages':[{'role':'user','content':'round4-timeout'}]}; r=httpx.post('http://127.0.0.1:8000/v1/chat',json=p,headers={'Authorization':'Bearer demo-key'}); print(json.dumps(r.json().get('attempts'),indent=2))"
   ```

4. urllib 路径：

   ```powershell
   .venv\Scripts\python.exe -c "import json,urllib.request; p=json.dumps({'profile':'fallback-chat','messages':[{'role':'user','content':'round4-fallback'}]}).encode(); q=urllib.request.Request('http://127.0.0.1:8000/v1/chat',data=p,headers={'Authorization':'Bearer demo-key','Content-Type':'application/json'}); print(json.dumps(json.load(urllib.request.urlopen(q))['attempts'],indent=2))"
   ```

5. 搜索 `request_timeout_ms` 全部引用，写出“parsed but not enforced”的证据链。
6. 用断点观察同一 provider 的 `retry_index=0/1` 与换 provider 后 `attempt_order` 的变化。

#### 本轮代码证据

- config `max_retries: 1` 表示每个 provider 最多调用 2 次，而不是整个请求最多 2 次。
- 每次 retryable failure 都会 `circuit.record_failure()`；因此一次逻辑请求可以贡献多个 failure count。
- circuit open 的 attempt 状态为 `circuit_open`，不会调用 provider，也不会再 retry 该 provider。
- `fallback_used = any(attempt.status != 'success')`；同一 provider retry 后成功也会被标记 true，语义并不严格等于“换了 provider”。`[CODE VERIFIED]`
- `fallback.trigger_on` 没有控制 failure 类型；预期 domain error 都被 `_FALLBACK_TRIGGERS` 捕获，未预料 `Exception` 也被转成 `provider_failed` 并继续。`[TEST VERIFIED]`

#### 完成标准

能画出二维 attempts 表（candidate order × retry index），并针对一个 timeout 准确口述“产生→domain error→attempt→breaker→retry/fallback→audit/HTTP”；能指出至少两个当前语义边界。

#### 5 道检查题

1. `retry_on` 使用的是 attempt 的 status 还是 error_code？
2. 为什么 threshold=3、max_retries=1 时 breaker 可能在第二个请求中打开？
3. 全部 provider 失败后 attempts 如何从 `FallbackService` 到达 audit？
4. mock_slow 的 `timeout_ms` 是否真的参与了超时判断？
5. 为什么当前 `fallback_used` 可能在没有切换 provider 时也为 true？

#### Learning Checkpoint

- 我追的链路：
- 入口：
- 核心函数：
- 输入：
- 输出：
- I/O：
- 新理解：
- 未确认：
- 亲手验证证据：
- 下一轮第一步：

---

### Round 5：Rate Limit / Budget / Cache / Guardrail Governance Pipeline

#### 这一轮为什么学

回答治理组件的真实执行顺序与状态位置，并解释 rate limit 与 token/cost budget 为什么不是同一问题。

#### 本轮只看什么

- `app/application/services/chat_service.py:chat`
- `app/application/services/rate_limiter.py`
- `app/application/services/token_estimator.py`
- `app/application/services/token_budget_service.py`
- `app/application/services/prompt_cache.py`
- `app/application/services/guardrail_service.py`
- `app/infrastructure/persistence/sqlite/repositories.py:TokenBudgetRepository`
- `config/config.yaml` 中 clients/token_estimation/guardrails/cache/streaming
- `tests/unit/test_rate_limiter.py`
- `tests/unit/test_token_estimator.py`
- `tests/unit/test_token_budget_service.py`
- `tests/unit/test_prompt_cache.py`
- `tests/unit/test_guardrail_service.py`
- `tests/integration/test_chat_api.py` 中 rate/budget/guardrail 测试
- `tests/integration/test_highlights.py::test_cache_miss_then_hit`

#### 本轮暂时不要看什么

不要展开 provider adapter、admin/reload、replay、metrics registry 实现。

#### 真实调用链

`ChatService.chat` → streaming policy → `RateLimiter.check`（进程内 deque）→ profile → `GuardrailService.check_input` → `TokenEstimator.estimate_messages` → `PromptCache.key/get` → hit 则 audit + return；miss 才 `TokenBudgetService.ensure_capacity` → provider path → output guardrail → `TokenBudgetService.commit`（SQLite increment）→ cache put → audit。

#### 这一轮只掌握 3–5 个概念

1. rate limit 限制请求频率；budget 限制周期累计 token/cost。
2. heuristic estimate 与 provider usage 的区别。
3. exact key + TTL + LRU cache。
4. input block、output block、output truncate 三种 guardrail 行为。
5. early return 会改变哪些治理步骤。

#### 给 ChatGPT / Codex 的学习提示词

```text
只带我学习 Round 5 的 governance pipeline。先让我从 ChatService.chat 逐行写出 streaming、rate、profile、input guardrail、cache、budget、provider、output guardrail、commit、audit 的顺序，再解释最多 5 个概念。所有结论引用函数/SQL/test；特别检查 cache hit 跳过什么、budget 是否原子、provider usage 是否被使用。无法证明写“未验证”。不要直接替我总结答案。最后只问 5 个检查题，不给答案。
```

#### 我必须亲手完成

1. 运行五组单元测试与两个 integration 目标：

   ```powershell
   .venv\Scripts\python.exe -m pytest tests/unit/test_rate_limiter.py tests/unit/test_token_estimator.py tests/unit/test_token_budget_service.py tests/unit/test_prompt_cache.py tests/unit/test_guardrail_service.py tests/integration/test_chat_api.py::test_rate_limit tests/integration/test_chat_api.py::test_token_budget_exceeded tests/integration/test_highlights.py::test_cache_miss_then_hit -q
   ```

2. 对同一唯一 prompt 连发两次，比较 attempts、cache_hit、budget_before/after、decision_trace。
3. httpx 路径：

   ```powershell
   .venv\Scripts\python.exe -c "import httpx,json; c=httpx.Client(base_url='http://127.0.0.1:8000',headers={'Authorization':'Bearer demo-key'}); p={'profile':'fast-chat','messages':[{'role':'user','content':'round5-cache-unique'}]}; a=c.post('/v1/chat',json=p).json(); b=c.post('/v1/chat',json=p).json(); print(json.dumps({'first':{k:a.get(k) for k in ('cache_hit','budget_before','budget_after','attempts')},'second':{k:b.get(k) for k in ('cache_hit','budget_before','budget_after','attempts')}},indent=2))"
   ```

4. urllib 路径：用 `burst-key` 连发 4 个不同 prompt，捕获 `urllib.error.HTTPError`，记录第 4 次状态与 `Retry-After`。
5. 用只读 SQL 查询当日 `token_budget_usage`，将一次 miss 前后增量与 heuristic token 数对上；优先复制数据库到临时目录实验，避免污染既有数据。
6. 构造 input guardrail block，并确认 provider attempts 为空、error audit 的 decision trace 只以通用 `error` 结束。

#### 本轮代码证据

- rate limiter 状态在 `RateLimiter._hits`，按 client_id 计 60 秒 sliding window，不持久化。
- budget usage 在 SQLite，period key 用本机 `datetime.now()` 格式化；pre-check 只检查 input estimate，commit 直接累加 total。
- 默认 cost-per-1k 与 client max_cost 都是 0，因此当前默认配置的 cost governance 实际不产生限制。
- cache key 包含 profile/model/messages/max_tokens/temperature，不含 client_id；hit 跳过 budget、provider 和 output guardrail。
- output truncate 后 cache 写入的是原始 `ChatResponse`，下一次 hit 直接使用原始 content，不再过 output guardrail；现有测试未覆盖这个边界。`[CODE VERIFIED]`

#### 完成标准

画出 miss 与 hit 两条不同 pipeline；用状态位置解释 rate/budget/cache 的单机差异；能指出至少三个“测试通过仍不代表 production-ready”的治理边界。

#### 5 道检查题

1. rate limit 与 budget 的 key、时间窗口和存储介质分别是什么？
2. 为什么 cache hit 的 budget_before/after 是 null？
3. 当前 budget pre-check 为什么仍可能让最终 usage 超限？
4. provider 返回的 usage 是否覆盖 estimator 结果？
5. output truncate 与 cache put 的顺序可能造成什么问题？

#### Learning Checkpoint

- 我追的链路：
- 入口：
- 核心函数：
- 输入：
- 输出：
- I/O：
- 新理解：
- 未确认：
- 亲手验证证据：
- 下一轮第一步：

---

### Round 6：Request Audit / ProviderAttempt / Decision Trace

#### 这一轮为什么学

回答一次请求如何用 request_id 串起响应、错误、治理决策、request_logs 与 provider_attempts，并区分“事件事实”和“事后解释”。

#### 本轮只看什么

- `app/core/request_context.py`
- `app/core/logging.py`
- `app/interfaces/http/middleware.py`
- `app/domain/models/provider.py:ProviderAttempt`
- `app/domain/models/decision_trace.py`
- `app/application/services/chat_service.py`
- `app/application/services/request_log_service.py`
- `app/infrastructure/persistence/sqlite/schema.py`
- `app/infrastructure/persistence/sqlite/repositories.py:RequestLogRepository`
- `app/interfaces/http/routes/requests.py`
- `tests/integration/test_chat_api.py::test_audit_lookup`
- `tests/integration/test_highlights.py`
- `tests/unit/test_unexpected_errors.py::test_unexpected_pipeline_error_is_audited`

#### 本轮暂时不要看什么

不要读 replay 脚本、admin hot reload、完整 metrics 实现、多副本设计。

#### 真实调用链

incoming/generate `x-request-id` → `request_id_var.set` → `get_request_id()` in auth/ChatService/error handler/log formatter → `FallbackService` 产生 `ProviderAttempt[]` → `ChatService._build_provider_trace` 产生解释步骤 → `RequestLogService.record_success/error` → `RequestLogRepository.insert_request` → 每个 attempt 单独 `insert_attempt` → GET `/v1/requests/{id}` → `get_request` + JSON fields decode → response。

#### 这一轮只掌握 3–5 个概念

1. correlation id 与业务主键 request_id。
2. request-level row 与 attempt-level rows 的一对多关系。
3. decision trace 是有序解释，不等同于原始 attempts。
4. config-driven body persistence 与 replay_payload 的区别。
5. audit coverage boundary。

#### 给 ChatGPT / Codex 的学习提示词

```text
只带我学习 Round 6 的 request_id、request_logs、provider_attempts、decision_trace。先让我从 middleware 追到 SQLite 查询结果，再解释最多 5 个概念。每个结论必须引用具体字段、函数、SQL 或测试。特别指出 auth/422 是否被 audit、request_body 与 replay_payload 是否受同一开关控制。无法证明写“未验证”。不要直接替我总结答案。最后只问 5 个检查题，不给答案。
```

#### 我必须亲手完成

1. 用自定义 `X-Request-ID: round6-manual-001` 发一次 fallback 请求。
2. httpx 路径：

   ```powershell
   .venv\Scripts\python.exe -c "import httpx,json; h={'Authorization':'Bearer demo-key','X-Request-ID':'round6-manual-001'}; p={'profile':'fallback-chat','messages':[{'role':'user','content':'round6-audit'}]}; r=httpx.post('http://127.0.0.1:8000/v1/chat',headers=h,json=p); a=httpx.get('http://127.0.0.1:8000/v1/requests/round6-manual-001',headers={'Authorization':'Bearer demo-key'}); print(r.status_code,r.headers.get('x-request-id')); print(json.dumps(a.json(),ensure_ascii=False,indent=2))"
   ```

3. urllib 路径：使用另一个 request_id 发 chat，再 GET audit；对比 header/body/DB 的 id。
4. 在 SQLite 中查询：

   ```sql
   SELECT request_id, client_id, model_profile, selected_provider, fallback_used,
          status, status_code, cache_hit, decision_trace, replay_payload
   FROM request_logs WHERE request_id = 'round6-manual-001';

   SELECT provider_id, attempt_order, retry_index, status, error_code, latency_ms
   FROM provider_attempts WHERE request_id = 'round6-manual-001'
   ORDER BY attempt_order, retry_index;
   ```

5. 发一次无 auth 请求，查询同 request_id 是否有 audit；记录“没有 row”也是证据。
6. 运行：`.venv\Scripts\python.exe -m pytest tests/integration/test_chat_api.py::test_audit_lookup tests/integration/test_highlights.py tests/unit/test_unexpected_errors.py::test_unexpected_pipeline_error_is_audited -q`。

#### 本轮代码证据

- `logging.persist_request_body=false` 时 `request_body` 为空，但 `replay_payload` 仍无条件持久化，包含完整 messages；这有隐私与数据保留含义。
- request row 与 attempts 分多个 connection/commit 插入，不是一个跨表事务；中途失败可能部分写入。`[CODE VERIFIED]`
- GET audit 只 require 有效 API key，没有 `data['client_id'] == client.client_id` 检查。`[CODE VERIFIED]`
- decision trace 的 “fallback candidate after N failed attempt(s)” 使用 candidate `attempt_order`，不是实际失败 attempt 数；有 retry 时文字可能低估失败次数。`[CODE VERIFIED]`

#### 完成标准

拿一个 request_id，从 HTTP response 定位 request_logs 和全部 attempts；能解释每个关键字段由谁写、何时写、哪些失败没有 row；能指出 audit 的事务与授权边界。

#### 5 道检查题

1. 客户端传入 request_id 与系统生成 request_id 的优先顺序是什么？
2. decision trace 与 provider_attempts 哪个更接近原始事实？
3. 为什么关闭 request_body persistence 仍不等于不保存 prompt？
4. request row 和 attempts 是否在同一事务写入？
5. 任意合法 client 能否查询别的 client 的 request_id？代码证据是什么？

#### Learning Checkpoint

- 我追的链路：
- 入口：
- 核心函数：
- 输入：
- 输出：
- I/O：
- 新理解：
- 未确认：
- 亲手验证证据：
- 下一轮第一步：

---

### Round 7：Replay / Regression Replay

#### 这一轮为什么学

拒绝根据“replay”名字猜功能：明确它读什么历史字段、重新执行什么、跳过什么、比较什么，以及会产生哪些真实副作用。

#### 本轮只看什么

- `app/application/services/chat_service.py:replay`
- `app/application/services/chat_service.py:_request_body_snapshot`
- `app/application/services/request_log_service.py`
- `app/infrastructure/persistence/sqlite/repositories.py:get_request`
- `scripts/replay_request.py`
- `tests/integration/test_highlights.py::test_replay_reproduces_decision`
- `tests/integration/test_highlights.py::test_audit_returns_parsed_decision_trace`
- `Makefile:replay`

#### 本轮暂时不要看什么

不要研究所有 schema migration、guardrail regex、metrics 实现；不要把 GET audit endpoint 称为 replay。

#### 真实调用链

CLI `--request-id` → `RequestLogRepository.get_request` 读取 original + attempts + replay_payload → `_rebuild_request` → 取 original.model_profile → 临时目录 `bootstrap(current config, temp replay.db)` → `ChatService.replay` → current routing → `FallbackService.execute` → 实际 provider call → 返回 current selected_provider/fallback_used/attempt signature → 与 original 三项比较 → exit 0 PASS 或 exit 1 REGRESSION。

#### 这一轮只掌握 3–5 个概念

1. replay payload 是重建请求的输入快照。
2. routing regression replay 不是完整 HTTP/request pipeline replay。
3. comparison signature 的精确字段。
4. side-effect boundary：跳过 gateway governance 不等于无副作用。
5. deterministic/non-deterministic provider 对 replay 稳定性的影响。

#### 给 ChatGPT / Codex 的学习提示词

```text
只带我学习 Round 7 的 replay。必须从 scripts/replay_request.py 的参数入口追到 ChatService.replay，再回到三项 comparison。先调用链后概念，最多 5 个。逐项列出 replay 重新执行、明确跳过、仍会改变或调用的东西；每项引用真实函数/test。无法证明写“未验证”。不要直接替我总结答案。最后只问 5 个检查题，不给答案。
```

#### 我必须亲手完成

1. 先用 `/v1/chat` 生成一条 cache miss 成功请求，保存 request_id。
2. 运行：`.venv\Scripts\python.exe scripts/replay_request.py --request-id <REQUEST_ID>`，记录 exit code 与 Original/Current。
3. 用 GET audit 检查 replay_payload。httpx：

   ```powershell
   .venv\Scripts\python.exe -c "import httpx,json; rid='<REQUEST_ID>'; r=httpx.get(f'http://127.0.0.1:8000/v1/requests/{rid}',headers={'Authorization':'Bearer demo-key'}); print(json.dumps(r.json().get('replay_payload'),ensure_ascii=False,indent=2))"
   ```

4. urllib 路径：GET 同一 audit endpoint 并打印 `model_profile/selected_provider/attempts`。
5. 再生成一条 cache-hit history，预测 replay 结果后运行；解释为什么 original attempts 为空而 current replay 会调用 provider。
6. 运行目标测试：`.venv\Scripts\python.exe -m pytest tests/integration/test_highlights.py::test_replay_reproduces_decision tests/integration/test_highlights.py::test_audit_returns_parsed_decision_trace -q`。

#### 本轮代码证据

- replay 跳过 auth、streaming、rate limit、guardrail、cache、budget、audit、metrics 的 `ChatService.chat` 流程。
- replay 仍调用 `FallbackService.execute`，会改变 replay container 内 circuit state；真实 adapter 下还会产生外部网络调用、费用或服务端副作用。不能说“纯计算无副作用”。
- CLI 使用 temp DB 避免写原 gateway DB，但 provider 调用不是假的。
- 当前 test 只直接测试 `ChatService.replay` 成功路径；不测试 CLI comparison、exit code、cache-hit、失败历史或真实 provider。
- original cache hit 的 attempts=[]，current replay 通常 attempts=[success]，比较签名会判变化；这是代码可推出但自动化未覆盖的边界。

#### 完成标准

能用一句精确话定义 replay：“用历史 replay_payload，在当前配置下重新执行 routing+fallback/provider，并比较 provider/fallback/attempt signature”；能列出 6 个跳过项和 3 个仍有副作用项。

#### 5 道检查题

1. replay 从哪个 DB 字段重建 messages？
2. 为什么它不消耗 gateway token budget，却可能消耗真实 provider 费用？
3. comparison 为什么可能对 cache-hit 历史报 regression？
4. GET `/v1/requests/{id}` 与 CLI replay 的本质区别是什么？
5. replay 会使用历史配置还是当前配置？证据在哪？

#### Learning Checkpoint

- 我追的链路：
- 入口：
- 核心函数：
- 输入：
- 输出：
- I/O：
- 新理解：
- 未确认：
- 亲手验证证据：
- 下一轮第一步：

---

### Round 8：Persistence / SQLite / Memory / Multi-replica Boundary

#### 这一轮为什么学

从状态所有权出发判断单机与多副本限制：哪些状态共享、哪些状态分裂、哪些操作不是原子事务，而不是泛泛说“SQLite 不适合生产”。

#### 本轮只看什么

- `app/infrastructure/persistence/sqlite/schema.py`
- `app/infrastructure/persistence/sqlite/connection.py`
- `app/infrastructure/persistence/sqlite/repositories.py`
- `app/application/services/rate_limiter.py`
- `app/application/services/prompt_cache.py`
- `app/application/services/circuit_breaker.py`
- `app/application/services/token_budget_service.py`
- `app/core/container.py`
- `app/interfaces/http/routes/admin.py`
- `docker-compose.yml`
- `docs/adr/0003-local-first-storage.md`（只作设计背景）
- `tests/unit/test_token_budget_service.py`
- `tests/unit/test_rate_limiter.py`
- `tests/unit/test_prompt_cache.py`

#### 本轮暂时不要看什么

不要重读完整 HTTP schema、provider mocks、guardrail regex、interview 脚本。

#### 真实调用链

bootstrap → `init_db`（schema version + idempotent columns）→ `build_container` → `ClientRepository.sync` → 创建 process-local limiter/cache/breakers/metrics → request 时 sync repository 每方法新 connection → WAL/foreign keys → commit。Admin reload → `bootstrap()` 新 container → 替换 `app.state.container` → 新的全部进程内状态。

#### 这一轮只掌握 3–5 个概念

1. durable SQLite state 与 process-local memory state。
2. connection-per-method 不等于跨方法事务。
3. check-then-commit race。
4. multi-worker 与 multi-replica 状态分片/重复配额。
5. hot reload 的状态重置与资源生命周期。

#### 给 ChatGPT / Codex 的学习提示词

```text
只带我学习 Round 8。先把每类状态放进表格：owner、存储、key、更新函数、进程重启后是否保留、多 replica 是否共享。只使用本轮文件和 SQL。然后用两个并发请求和两个 replica 推演 rate limit、budget、cache、circuit、metrics、audit。每个结论引用函数/SQL/test；无法证明写“未验证”。不要直接替我总结答案。最后只问 5 个检查题，不给答案。
```

#### 我必须亲手完成

1. 画状态表：clients、token_budget_usage、request_logs、provider_attempts、config_events、rate hits、cache entries、breaker state、metrics counters。
2. 只读执行 `PRAGMA journal_mode; PRAGMA foreign_keys; PRAGMA table_info(request_logs);`，与 schema 代码对照。
3. 创建两个独立 `build_container(config, same_temp_db)`，证明 rate limiter/cache/breaker 对象不是同一个；再说明它们若共享 SQLite 文件，哪些 row 会共享。
4. 对 budget 写并发时序：A snapshot=10、B snapshot=10、A commit、B commit；预测是否能超额。不要把推演当成已完成并发压测。
5. 调 admin reload 前后比较 `id(container.rate_limiter/cache/circuit_breakers)`；使用临时进程/数据库，不污染长期服务。
6. 运行相关测试：`.venv\Scripts\python.exe -m pytest tests/unit/test_token_budget_service.py tests/unit/test_rate_limiter.py tests/unit/test_prompt_cache.py -q`。

#### 本轮代码证据

- SQLite 持久化 client/budget/audit/config event；rate/cache/breaker/metrics 都在 Python 对象内。
- `TokenBudgetService.ensure_capacity` 的 SELECT 与 `commit` 的 UPSERT 是两个方法/connection，不是原子 reservation。
- `RequestLogRepository.insert_request` 与每个 `insert_attempt` 分别 commit，不能承诺 all-or-nothing audit。
- sync sqlite3 调用直接发生在 async request handler 路径，会阻塞 event loop；当前没有 load test 证据。
- reload 新建 container，进程内限流窗口、cache、breaker 和 metrics 会清零；旧 OpenAI client 没有在 lifespan/reload 关闭。

#### 完成标准

面对“部署 3 个 replicas 会怎样”，能逐机制回答而不是只说“用 Redis/Postgres”；能画出至少两个 race 时序并指出需要哪类原子操作。

#### 5 道检查题

1. WAL 解决了什么，又没有解决什么？
2. 两个 worker 的 burst-key 各能允许多少请求？为什么？
3. budget 为什么可能跨 replica 超限？
4. hot reload 后 breaker 为什么重新 closed？
5. request row 成功但某个 attempt row 失败时会留下什么状态？

#### Learning Checkpoint

- 我追的链路：
- 入口：
- 核心函数：
- 输入：
- 输出：
- I/O：
- 新理解：
- 未确认：
- 亲手验证证据：
- 下一轮第一步：

---

### Round 9：Tests as Specification

#### 这一轮为什么学

把测试当“可执行的有限规格”：每个声称都要找到断言，同时主动记录没有被断言的生产边界。

#### 本轮只看什么

- `tests/conftest.py`
- `tests/integration/test_health.py`
- `tests/integration/test_chat_api.py`
- `tests/integration/test_highlights.py`
- `tests/unit/test_circuit_breaker.py`
- `tests/unit/test_fallback_service.py`
- `tests/unit/test_guardrail_service.py`
- `tests/unit/test_openai_compatible_provider.py`
- `tests/unit/test_prompt_cache.py`
- `tests/unit/test_rate_limiter.py`
- `tests/unit/test_routing_service.py`
- `tests/unit/test_token_budget_service.py`
- `tests/unit/test_token_estimator.py`
- `tests/unit/test_unexpected_errors.py`
- `eval/run_eval.py`
- `eval/eval_cases.yaml`
- `eval/security_cases.yaml`
- `.github/workflows/ci.yml`

#### 本轮暂时不要看什么

不要读 README 的 feature list；不要新增测试或修代码；不要把 test name 当证据，必须读 assert。

#### 真实调用链

pytest → fixtures `make_test_config/container/client` → temp SQLite → `create_app(container)` → TestClient request/直接 service call → assert；CI → install dev deps → ruff → pytest。Eval → YAML cases → fresh temp DB/TestClient → `_check` 仅比较指定 response fields。

#### 这一轮只掌握 3–5 个概念

1. unit、in-process integration、eval 各自证明范围。
2. fixture config 与生产 config 的差异。
3. assertion-level evidence，而不是 test count 崇拜。
4. negative evidence：没有测试不是“代码错误”，但不能扩大声称。
5. deterministic fake 与真实系统差距。

#### 给 ChatGPT / Codex 的学习提示词

```text
只带我学习 Round 9。让我逐个能力建立“结论→具体 test→关键 assert→没有证明什么”矩阵。只使用 tests、eval 和 CI 文件；需要理解被测函数时再最小回看源码。先测试调用链后概念，最多 5 个。不要按测试名猜，必须引用 assert。无法证明写“未验证”。不要直接替我总结答案。最后只问 5 个检查题，不给答案。
```

#### 我必须亲手完成

1. 执行 `.venv\Scripts\python.exe -m pytest --collect-only -q`，确认当前是 84 tests。
2. 执行 `.venv\Scripts\python.exe -m pytest -q`，保存耗时与结果。
3. 执行 `.venv\Scripts\python.exe eval/run_eval.py` 与 `--cases eval/security_cases.yaml`。
4. 执行 `.venv\Scripts\python.exe -m ruff check .`。
5. 建立 12 行证据矩阵：happy path、auth、routing、retry、fallback、circuit、rate、budget、cache、guardrail、audit、replay。
6. 为每行再写一个“仍未证明”：例如真实网络、多线程竞争、CLI exit code、租户隔离、resource close。

#### 本轮代码证据

- 本次实际结果：84/84 passed；demo 10/10；eval 7/7；security eval 8/8；ruff clean。`[MANUALLY VERIFIED]`
- integration 是 TestClient + temp SQLite + mock provider，不是启动外部 Uvicorn/真实 provider 的 system test。
- circuit breaker 有状态机单测，但没有完整 HTTP 请求驱动 closed→open→half-open 的 integration test。
- retry 没有一个命名清晰、精确断言 backoff 与 retry_index 的专门单测；timeout/fallback integration 会间接走 max_retries=1。
- `scripts/replay_request.py` CLI comparison 没有自动化测试；`ChatService.replay` 只有基本成功路径。
- admin reload endpoint 本身没有测试；只测试了 admin config 和鉴权。

#### 完成标准

随机抽一个 README feature，你能在 60 秒内给出：代码文件、测试函数、关键 assert、未覆盖边界；找不到就明确降级为 CODE VERIFIED/UNVERIFIED，而不是替项目补证据。

#### 5 道检查题

1. 84 passed 能否证明真实 Ollama 可用？为什么？
2. 哪个测试证明 unexpected pipeline error 仍被 audit？
3. cache test 有没有证明跨 replica 一致性？
4. eval `_check` 实际比较哪些字段？
5. CI 当前在哪个 Python 版本跑，是否有多数据库/多 OS matrix？

#### Learning Checkpoint

- 我追的链路：
- 入口：
- 核心函数：
- 输入：
- 输出：
- I/O：
- 新理解：
- 未确认：
- 亲手验证证据：
- 下一轮第一步：

---

### Round 10：Failure Lab

#### 这一轮为什么学

把纸面机制变成可观测证据：主动制造 timeout、breaker state change、cache/audit 差异，并从 response、metrics、SQLite 三个角度互相校验。

#### 本轮只看什么

- `config/config.yaml`
- `scripts/demo.py`
- `app/application/services/fallback_service.py`
- `app/application/services/circuit_breaker.py`
- `app/application/services/chat_service.py`
- `app/application/services/prompt_cache.py`
- `app/application/services/request_log_service.py`
- `app/infrastructure/persistence/sqlite/schema.py`
- `tests/integration/test_chat_api.py`
- `tests/integration/test_highlights.py`

#### 本轮暂时不要看什么

不要改真实 provider key；不要使用生产/重要数据库；不要先做 Level A/B/C 修改。

#### 真实调用链

实验请求 → mock failure injection → retry/circuit/fallback → attempts/decision trace → request log + attempt rows → `/metrics`；治理实验第二次 exact request → cache early return → audit row attempts 为空。

#### 这一轮只掌握 3–5 个概念

1. 可控初始状态。
2. 单一故障注入变量。
3. response、DB、metric 三角验证。
4. breaker 需要跨请求保留同一 container。
5. 实验结果与代码推演不一致时优先保留原始证据。

#### 给 ChatGPT / Codex 的学习提示词

```text
只担任 Round 10 Failure Lab 教练。一次只做一个实验：先让我写预测，再运行，再要求我从 response attempts、decision_trace、SQLite request_logs/provider_attempts、metrics 找证据。所有解释引用真实函数/SQL/test；无法证明写“未验证”。不要提前告诉我结果或直接替我总结。每个实验结束问 5 个检查题，不给答案。
```

#### 我必须亲手完成

执行本节后面的 Lab A/B/C。HTTP 实验都同时保留两条客户端路径：

- httpx：适合连续请求、headers/JSON 对比。
- urllib：用 `urllib.request.Request` 发请求，用 `urllib.error.HTTPError` 读取 4xx/5xx body。

先在临时数据库/独立 TestClient 进程操作；每个 prompt 与 request_id 唯一，避免 cache 污染 failure 实验。

#### 本轮代码证据

- timeout profile 的 primary 是 mock_slow，配置 max_retries=1，所以在未受 circuit 影响时应出现两个 timeout attempts 后换 mock_fast。
- breaker 由同一 `AppContainer.circuit_breakers[provider_id]` 跨请求保留。
- cache hit audit 仍写 request_logs，但 provider_attempts 应为 0 行。
- request_id 可以将 response、audit 与 SQL 行对齐。

#### 完成标准

三个实验各有“预测、原始输出、SQL、结论、反例/限制”；任何一个实验只看 HTTP 200 而没看 attempts/DB，都不算完成。

#### 5 道检查题

1. 为什么 failure prompt 必须唯一？
2. breaker 实验为什么必须复用同一个 container/进程？
3. retry 与 fallback 在 attempts 表里如何区分？
4. cache hit 为什么没有 provider_attempts？
5. 看到 fallback response 200，为什么仍不能说 primary 健康？

#### Learning Checkpoint

- 我追的链路：
- 入口：
- 核心函数：
- 输入：
- 输出：
- I/O：
- 新理解：
- 未确认：
- 亲手验证证据：
- 下一轮第一步：

---

### Round 11：亲手修改一个小功能 + Interview 验收

#### 这一轮为什么学

从“能解释”升级到“能安全改变”：选择一个跨至少两层的小改动，先写失败测试，再实现、回归、口述 trade-off；最后用面试脚本验收。

#### 本轮只看什么

- 根据所选 Level 只看第 5 节列出的最小文件集合
- 对应 `tests/unit/` 与 `tests/integration/` 目标文件
- `pyproject.toml` 的 pytest/ruff 配置
- 本文第 6 节面试脚本

#### 本轮暂时不要看什么

不要同时做三个候选；不要顺手重构目录、升级依赖或改数据库 schema；不要先让 AI 给最终实现。

#### 真实调用链

选择一个可观察行为 → 写 failing test → 最小 domain/application/infrastructure/HTTP 修改 → target tests → full suite → ruff → 用 request/SQL 验证 → git diff 只审自己的文件 → 面试口述 change before/after。

#### 这一轮只掌握 3–5 个概念

1. change slice 与最小文件集合。
2. test-first 的可观察行为。
3. 跨层契约不变量。
4. regression scope。
5. production boundary 的诚实表达。

#### 给 ChatGPT / Codex 的学习提示词

```text
只担任 Round 11 修改教练。我会在 Level A/B/C 中选一个。先要求我说明当前行为、目标行为、最小文件、失败测试和不变量；不要给最终实现。每一步只分析当前 diff，并引用真实函数/test。无法证明写“未验证”。target test 通过后再要求 full pytest、ruff 和一次手工验证。最后进入 20–25 分钟面试，一次只问一个问题，不给答案；如果我只说术语，继续追问文件、函数、测试、数据库字段或失败场景。
```

#### 我必须亲手完成

1. 只选择第 5 节一个 Level，先写一页 change contract。
2. 运行 target test，确认先红后绿；保存失败与通过输出。
3. 运行 `.venv\Scripts\python.exe -m pytest -q` 与 `.venv\Scripts\python.exe -m ruff check .`。
4. 如果改动影响 HTTP，同时用 httpx 与 urllib 各验证一次；如果影响 persistence，再查询对应 SQL。
5. 执行 `git diff -- <最小文件集合>`，逐行解释每个修改。
6. 按第 6 节进行一次 20–25 分钟录音式口述，不能看手册。

#### 本轮代码证据

- failing test 必须能在修改前稳定复现目标缺口。
- 实现必须穿过至少两个代码层，而不是只改 README/config 文案。
- full suite 证明没有破坏现有 84 个断言，但仍不等于 production 验证。
- 最终 diff 不应包含无关业务代码、数据库文件、pycache 或依赖变动。

#### 完成标准

能提交一个小而完整的 change slice：测试先失败后通过、full suite/ruff 通过、手工证据完整；能在 5 分钟内解释 why/where/test/failure/boundary。

#### 5 道检查题

1. 修改前的行为由哪个 test 或代码路径证明？
2. 你的新测试为什么不是只测实现细节？
3. 改动跨了哪两个层，契约在哪里？
4. 哪个失败场景最可能产生 regression？
5. 这个改动之后仍有哪些 production boundary？

#### Learning Checkpoint

- 我追的链路：
- 入口：
- 核心函数：
- 输入：
- 输出：
- I/O：
- 新理解：
- 未确认：
- 亲手验证证据：
- 下一轮第一步：

---

## 4. Failure Lab 详细实验卡

所有实验先使用 fresh process + 临时 SQLite，确保 cache、rate limiter、breaker、metrics 初始状态可控。不要把仓库现有 `data/gateway.db` 当实验沙盒。每次请求显式传唯一 `X-Request-ID`。

### Lab A：Provider timeout → retry → fallback

**初始状态**

- 使用默认 `timeout-chat`：routing candidates 为 `mock_slow(priority=1)`、`mock_fast(priority=2)`。
- fresh container；`mock_slow` breaker 为 closed；prompt 从未缓存。
- retry `max_retries=1`，所以每个 provider 最多尝试 2 次。

**怎么制造故障**

1. 启动 fresh gateway。
2. POST `/v1/chat`，profile=`timeout-chat`，唯一 prompt=`lab-a-timeout-<timestamp>`，header `X-Request-ID: lab-a-001`。
3. httpx 与 urllib 至少各执行一次，但必须换 prompt/request_id，防止第二次命中 cache。

**应观察什么**

- HTTP 最终应 200，selected provider 为 `mock_fast`。
- attempts 在 breaker 初始 closed 时应包含 `mock_slow retry_index=0 timeout`、`mock_slow retry_index=1 timeout`、`mock_fast success`。
- decision trace 应有两个 provider_failed(timeout) 和 provider_selected(mock_fast)。
- `fallback_used=true`。

**查询什么日志/数据库**

```sql
SELECT request_id, selected_provider, fallback_used, status_code, decision_trace
FROM request_logs WHERE request_id = 'lab-a-001';

SELECT provider_id, attempt_order, retry_index, status, error_code, latency_ms
FROM provider_attempts WHERE request_id = 'lab-a-001'
ORDER BY attempt_order, retry_index;
```

另查 `/metrics` 的 `llm_gateway_provider_attempts_total` 与 `llm_gateway_fallbacks_total`。注意 metrics 只在 `ChatService._record_success_metrics` 统一记录最终 attempts。

**什么结果才算证据**

response attempts、DB attempts、decision trace 三者 provider/status/retry_index 一致；最终 200 不能单独算证据。若 attempts 数不同，先检查 breaker 是否已被前序请求打开、prompt 是否 cache hit。

### Lab B：Circuit breaker closed → open → half-open → open

**初始状态**

- fresh process；`mock_error` breaker closed；failure threshold=3，recovery timeout=2000ms，max retries=1。
- 使用 `fallback-chat`，每次请求都换 prompt，避免 cache。

**怎么制造故障**

1. 请求 1：`lab-b-1`。`mock_error` 两次失败，failure count 预计为 2；`mock_stable` 返回成功。
2. 请求 2：`lab-b-2`。第一次 `mock_error` 失败把 count 推到 3 并 open；其 retry_index=1 在 `allow_request()` 被记为 `circuit_open`；随后 fallback。
3. 立即请求 3：`lab-b-3`。`mock_error` 应直接 `circuit_open`，不产生 provider latency。
4. 等待略多于 2 秒，先 GET `/metrics`：`sync_circuit_metrics()` 访问 `breaker.state`，应触发/呈现 half-open=2。
5. 请求 4：`lab-b-4`。half-open probe 调用永远失败的 `mock_error`，随后 breaker reopen=1。

**应观察什么**

- 每个请求的 attempts/retry_index 不同。
- breaker metric：closed=0、open=1、half-open=2、probe failure 后 open=1。
- request 3 的 `mock_error` attempt status=`circuit_open`，latency_ms 默认 0。

**查询什么日志/数据库**

```sql
SELECT request_id, provider_id, attempt_order, retry_index, status, error_code, latency_ms
FROM provider_attempts
WHERE request_id IN ('lab-b-1','lab-b-2','lab-b-3','lab-b-4')
ORDER BY request_id, attempt_order, retry_index;
```

同时保存四次 `/metrics` 快照中：

```text
llm_gateway_circuit_breaker_state{provider="mock_error"} ...
```

**什么结果才算证据**

必须同时有：跨请求的 attempt 变化、metric 状态值、等待时间记录。只调用 `CircuitBreaker` 单元对象能证明状态机，但不能证明它已接入 HTTP failure path；本实验要证明接入链。

### Lab C：Exact cache 对 budget/provider/audit 的影响

**初始状态**

- fresh process/fresh DB；cache enabled；demo-client budget usage=0。
- 唯一 payload 固定不变，两次请求只更换 request_id，不更换 profile/messages/max_tokens/temperature。

**怎么制造治理分支**

1. 第一次 request_id=`lab-c-miss`：cache miss，走 provider、budget commit、audit。
2. 第二次 request_id=`lab-c-hit`：相同 payload，cache hit early return。
3. 分别 GET audit，再查询 budget usage。

**应观察什么**

- miss：`cache_hit=false`、attempts 至少 1、budget_before/after 为数字。
- hit：`cache_hit=true`、attempts=[]、budget_before/after=null、decision trace 在 cache_hit 结束。
- hit 的 selected_provider 来自 cached `ChatResponse.provider_id`，但本次没有 provider call。

**查询什么日志/数据库**

```sql
SELECT request_id, selected_provider, cache_hit, cache_key,
       budget_before, budget_after, estimated_tokens, cost_saved_usd
FROM request_logs
WHERE request_id IN ('lab-c-miss','lab-c-hit')
ORDER BY created_at;

SELECT request_id, COUNT(*) AS attempt_count
FROM provider_attempts
WHERE request_id IN ('lab-c-miss','lab-c-hit')
GROUP BY request_id;

SELECT client_id, period, tokens_used, cost_used_usd
FROM token_budget_usage WHERE client_id='demo-client';
```

**什么结果才算证据**

第二次 request log 存在但没有 attempt rows，budget usage 在第二次后不增加，并且两个 request 的 cache_key 相同。然后写出边界：这证明当前实现的 hit 语义，不证明该语义适合所有计费/租户策略。

---

## 5. 亲手修改候选（只选一个）

手册不提供最终实现。每个候选都要求先写失败测试，再做最小修改。

### Level A：给 request audit 加 client ownership 校验

**当前缺口**：`GET /v1/requests/{request_id}` 只要求任意有效 API key，未比较 audit row 的 `client_id`。`[CODE VERIFIED]`

**最小文件集合**

- `app/interfaces/http/routes/requests.py`
- `app/application/services/request_log_service.py`
- `app/infrastructure/persistence/sqlite/repositories.py`（若把过滤下推到查询）
- `tests/integration/test_chat_api.py`

**测试入口**

- 新增：client A 创建请求；client B 查询得到 404 或明确的授权错误；client A 仍能查询。
- 目标：`.venv\Scripts\python.exe -m pytest tests/integration/test_chat_api.py -q`

**修改顺序**

1. 决定跨租户时返回 404 还是 403，并写成 test contract。
2. 先写 integration failing test。
3. 让 service/repository 接受 client_id 并做最小过滤。
4. route 传入 authenticated `client.client_id`。
5. full suite + 两个 API key 的 httpx/urllib 手工验证。

**验证方法**

检查响应状态、error.request_id、DB row 未被删除；确认 admin 是否需要跨租户查询（当前没有 admin audit endpoint，别顺手扩 scope）。

### Level B：让 fallback chain 与 routing candidates 的语义不再互相欺骗

**当前缺口**：`fallback.chain`/`trigger_on` 被解析和展示，但执行顺序来自 routing candidates。`[CODE VERIFIED]`

**最小文件集合**

- `app/domain/models/model_profile.py`
- `app/application/services/chat_service.py`
- `app/application/services/fallback_service.py`
- `app/infrastructure/config/mapper.py`（仅在契约变化时）
- `tests/unit/test_fallback_service.py`
- `tests/integration/test_chat_api.py`

**测试入口**

- 新增一个 routing candidates 与 fallback chain 故意不同的 profile。
- 分别断言 primary selection、allowed trigger、fallback order、disabled 行为。

**修改顺序**

1. 先写一页语义：routing 选 primary，chain 只列后继，还是 chain 包含 primary？
2. 写不一致配置的 failing test。
3. 只在一个层次合成最终 candidate order，避免 routing/fallback 两边各排一次。
4. 明确 trigger_on 使用 domain error_code 还是 attempt status。
5. 更新现有 tests，运行 full suite；不要只让 config 与 tests 再次恰好相同。

**验证方法**

从 response attempts 和 SQL provider_attempts 证明顺序；用一个“不在 trigger_on”的错误证明不会 fallback，或明确移除这个假配置字段。

### Level C：让 `gateway.request_timeout_ms` 成为可证明的请求 deadline

**当前缺口**：该字段被解析但没有用于 `ChatService`/`FallbackService`/provider call；mock timeout 也不是 deadline。`[CODE VERIFIED]`

**最小文件集合**

- `app/application/services/chat_service.py`
- `app/application/services/fallback_service.py`（若 deadline 要覆盖 retries/backoff）
- `app/domain/errors.py`
- `app/interfaces/http/exception_handlers.py`（若新增 error code/status）
- `tests/integration/test_chat_api.py`
- `tests/unit/test_fallback_service.py`

**测试入口**

- 使用一个可控 slow provider，断言整体 deadline、HTTP status/error code、audit、attempt chain。
- 区分 provider timeout 与 gateway request timeout；不要复用同一名字掩盖语义。

**修改顺序**

1. 定义 deadline 包围范围：只包 provider，还是整个 governance pipeline？
2. 定义取消传播、attempt 记录、retry/fallback 是否仍允许。
3. 写稳定的 async failing tests，避免依赖过窄 wall-clock。
4. 最小实现并校验 audit/HTTP mapping。
5. full suite + live httpx/urllib slow request。

**验证方法**

保存 elapsed time、error body、request_logs/provider_attempts；明确哪些 cleanup 在 cancellation 下执行。这个 Level 不能只用“测试跑得更快”作为证据。

---

## 6. 20–25 分钟项目深挖脚本

使用规则：面试官一次只问一个主问题，等候回答；若回答只有术语，就从对应追问中选一个继续，不一次抛出整组。

### 0–3 分钟：Happy Path

**主问题 1**：请从 `POST /v1/chat` 进入开始，逐函数讲到 HTTP response。

追问池：

- 哪个文件生成 request_id？
- auth 在 ChatService 前还是后？
- schema 到 domain request 的函数名是什么？
- cache hit 与 miss 在哪个函数分叉？
- 哪个测试证明 response header 与 body request_id 相同？

### 3–5 分钟：Provider abstraction

**主问题 2**：为什么 ChatService 不直接依赖 `MockFastProvider`？真实抽象边界在哪里？

追问池：

- `ProviderPort` 有哪三个成员？
- concrete adapter 在哪里注册？
- 外部 HTTP error 在哪里转成 domain error？
- 新增 Ollama 时什么情况下只改 config？

### 5–7 分钟：Routing/Profile

**主问题 3**：一个 logical profile 怎样变成 ordered provider candidates？

追问池：

- priority 同值如何排序，哪个测试？
- capabilities/preferences 是否参与路由？
- `fallback.chain` 当前有没有决定顺序？证据函数是什么？
- 未知 routing strategy 如何处理？

### 7–11 分钟：Retry/Fallback/Circuit Breaker

**主问题 4**：retry、fallback、circuit breaker 分别解决什么问题，作用域是什么？

追问池：

- 一个 timeout 从哪里产生、在哪里转换、在哪里记录？
- `attempt_order` 与 `retry_index` 如何区分？
- threshold=3/max_retries=1 时状态如何变化？
- `fallback_used` 是否一定表示换 provider？
- 全部失败时 attempts 怎样进入 audit？

### 11–14 分钟：Budget/Governance

**主问题 5**：准确说出 governance pipeline 顺序，并解释 rate limit 与 budget 的区别。

追问池：

- 各自状态存在哪里？
- cache hit 跳过哪些步骤？
- budget pre-check 检查 input 还是 total？
- provider usage 有没有被使用？
- output truncation 与 cache 有什么边界？

### 14–17 分钟：Audit

**主问题 6**：request_id 如何串起 request audit、provider attempts 和 decision trace？

追问池：

- `request_logs` 的哪个字段保存 trace？
- attempt 的 retry_index 在哪个表？
- auth failure 有没有 audit？
- request/attempt insert 是否同一事务？
- audit endpoint 如何做租户 ownership？

### 17–19 分钟：Replay

**主问题 7**：不要根据名字，精确定义本项目 replay 到底重放什么。

追问池：

- 从哪个字段重建请求？
- 跳过哪些治理步骤？
- 为什么仍可能产生真实费用？
- comparison 比较哪三类值？
- cache-hit history 为什么可能报变化？

### 19–22 分钟：Multi-replica

**主问题 8**：部署两个 gateway replicas 后，哪些状态一致，哪些会分裂？

追问池：

- rate/cache/circuit/metrics 的 owner 是谁？
- budget check+commit 是否原子？
- SQLite 同文件与每 replica 独立文件分别怎样？
- hot reload 会清空什么？

### 22–25 分钟：Production boundary

**主问题 9**：现在你能诚实声称什么，哪些还不能声称 production-ready？

追问池：

- 哪个测试证明你的声称？
- 真实 provider 的证据在哪里？
- 安全 eval 能否证明 prompt injection 防护完备？
- API key、audit data、replay payload 有什么安全边界？
- 如果只允许优先做三项生产化工作，你选什么，为什么？

**评分规则**

- 0 分：只说术语。
- 1 分：能说机制但不能指文件。
- 2 分：能指文件/函数。
- 3 分：还能给 test/SQL/失败实验。
- 4 分：能主动说出未验证边界与 trade-off。

9 个主问题满分 36；达到 27 且没有把 `[UNVERIFIED]` 说成已验证，才算“可以独立面试深挖”。

---

## 7. Production boundary：当前不能诚实扩大声称的地方

| 主题 | 当前事实 | 不能声称 | 下一类证据 |
| --- | --- | --- | --- |
| 真实 provider | adapter + MockTransport tests 存在 | OpenAI/Ollama/vLLM 已端到端可用 | sandbox key/local server system test |
| Timeout | mock 显式抛错；httpx 有 timeout mapping | gateway 全请求 deadline 已实现 | 使用 `request_timeout_ms` 的稳定 deadline tests |
| Routing | priority sorting | cost/latency/capability routing | 新算法 + deterministic tests/metrics |
| Fallback config | enabled 生效 | chain/trigger_on 生效 | 不一致配置测试 + 实现 |
| Rate limit | 单进程 sliding window | distributed quota | Redis/原子脚本 + multi-node tests |
| Budget | SQLite usage + basic tests | 严格并发配额/真实计费 | reservation/transaction/concurrency tests |
| Cache | 单进程 exact TTL/LRU | 跨租户/跨副本一致、安全 replay | ownership policy + distributed cache tests |
| Guardrail | regex/heuristic cases 8/8 | 防住所有 prompt injection/PII | threat model、持续 red-team、模型/规则评估 |
| Audit | request/attempt rows 可查 | every call、事务完整、租户隔离 | pre-route audit、transaction、ownership test |
| Replay | routing/fallback/provider re-execution | 完整请求无副作用重放 | CLI tests、dry-run provider、cache/failure cases |
| Hot reload | container 可替换 | 无中断、状态/资源安全迁移 | concurrency + cleanup tests |
| SQLite | local WAL | 高吞吐 HA storage | Postgres/shared store/load/failover tests |
| Streaming | 明确拒绝 | SSE/streaming 已支持 | `[ROADMAP]` 实现与断连/cancel tests |
| Secrets | config/admin redaction response | secret-at-rest/rotation 已完备 | secret manager、hash/encrypt、rotation tests |

优先生产化的三类风险应是：

1. **共享状态与原子性**：distributed rate limit、budget reservation、durable audit transaction。
2. **真实 provider 与 deadline/resource lifecycle**：真实 HTTP system test、全链路 timeout/cancellation、AsyncClient close。
3. **安全与租户边界**：audit ownership、API key storage/rotation、replay payload retention/redaction。

---

## 8. 重要结论证据台账（唯一计数）

以下计数按本节唯一编号，不按全文标签出现次数。一个结论只放进一个主证据等级，避免重复统计。

### `[TEST VERIFIED]`：18 条

1. T1 `/health` 与 `/v1/chat` happy path。
2. T2 missing/wrong API key 返回 401。
3. T3 request_id response header/body 关联。
4. T4 priority routing 排序与同优先级稳定性。
5. T5 provider error 后 fallback 成功与 attempts 顺序。
6. T6 模拟 timeout 后 fallback 成功。
7. T7 circuit closed/open/half-open 状态机。
8. T8 单进程 sliding-window rate limit 与 Retry-After。
9. T9 SQLite token budget snapshot/commit/exceeded。
10. T10 input/output guardrail 基本 block/truncate。
11. T11 exact cache key、TTL/LRU、miss→hit。
12. T12 request audit lookup 与 attempts 查询。
13. T13 decision trace 基本 selected/failed steps 与 JSON decode。
14. T14 `ChatService.replay` 基本成功决策。
15. T15 OpenAI-compatible response parse、bad status、connect error。
16. T16 unexpected provider exception 继续 fallback。
17. T17 unexpected pipeline exception 写 audit 并转 internal error。
18. T18 streaming 拒绝、metrics endpoint、admin config redaction 的现有断言。

### `[CODE VERIFIED]`：15 条

1. C1 application entrypoint、lifespan、bootstrap、composition root。
2. C2 `ChatService.chat` 的准确治理顺序与 cache early return。
3. C3 `fallback.chain/trigger_on` 当前不驱动执行。
4. C4 `gateway.request_timeout_ms` 只解析未使用。
5. C5 auth/schema failure 不进入 ChatService audit。
6. C6 未发现 `X-RateLimit-*` response headers，仅有 Retry-After。
7. C7 cache hit 跳过 budget/provider/output guardrail。
8. C8 output truncate 后缓存原始 response 的 bypass 边界。
9. C9 budget pre-check/commit 非同一原子 reservation，且 pre-check 只看 input。
10. C10 request row 与 attempt rows 分别 commit。
11. C11 audit GET 缺少 client ownership check。
12. C12 replay 只重跑 routing+fallback/provider，且仍有 provider/circuit 副作用。
13. C13 rate/cache/circuit/metrics 是 process-local。
14. C14 hot reload 重建状态，应用没有调用 provider close。
15. C15 provider usage 未进入 accounting，默认 cost 配置为零。

### `[MANUALLY VERIFIED]`：5 条（不纳入最终要求的四类计数）

1. M1 Python 3.11.9，84 collected/84 passed。
2. M2 demo 10/10。
3. M3 eval 7/7。
4. M4 security eval 8/8，ruff clean。
5. M5 现有一条非缓存历史请求 replay CLI PASS。

### `[UNVERIFIED]`：11 条

1. U1 真实 OpenAI/Ollama/vLLM 端到端调用。
2. U2 真实网络 timeout/cancellation 行为。
3. U3 多 replica 共享状态一致性。
4. U4 SQLite 高并发锁竞争、吞吐、崩溃恢复。
5. U5 budget 并发超额的实测幅度与修复方案。
6. U6 hot reload 并发安全、连接泄漏和在途请求行为。
7. U7 replay CLI 对 cache-hit/失败历史/随机 provider 的正确性。
8. U8 guardrail 对未收录攻击与真实模型输出的覆盖率。
9. U9 非零 cost budget 与真实 provider usage 对账。
10. U10 当前 Docker image/Compose 在本机完整 build+run。
11. U11 多 Uvicorn workers 的 rate/cache/circuit/metrics 行为实测。

### `[ROADMAP]`：4 条

1. R1 semantic cache。
2. R2 Redis-backed cache + distributed rate limiter。
3. R3 SSE streaming。
4. R4 OpenTelemetry GenAI traces。

---

## 9. 生成后自检

1. **所有文件名来自真实仓库？** 是；所有本轮路径均在当前 `rg --files` 结果中，本文本身是唯一新增学习文档。
2. **是否把 README 声明误当实现？** 否；82 tests、every call audit、X-RateLimit、Ollama/vLLM 等均重新分级。
3. **每轮是否 <= 60–90 分钟？** 是；总览给出每轮预算，Round 10 固定 90 分钟。
4. **每轮是否都有实际操作？** 是；每轮包含测试/搜索/请求/断点/SQL/实验中的至少一类。
5. **Happy Path 是否早于 Failure Path？** 是；Round 1 Happy Path，Round 4 才进入 failure path。
6. **是否至少一个真实 Failure Lab？** 是；Lab A/B/C 共三个可执行实验。
7. **是否最终要求自己修改代码？** 是；Round 11 提供 A/B/C 三个跨层候选，不给最终实现。
8. **是否诚实写出 production boundary？** 是；第 7 节逐项列出不能声称和所需下一证据。

完成这份手册的标准不是“读完”，而是你能拿一个新的 request_id，从 HTTP、函数调用、attempts、decision trace、SQLite、tests 六个方向互相证明同一条故事，并在证据不足时主动说“未验证”。
