# Release checklist

- [ ] `pytest`, Ruff, compileall, functional eval, and security eval pass.
- [ ] Run final demos and review failure/audit evidence.
- [ ] Apply and test SQLite/PostgreSQL migrations; exercise reservation reconciliation.
- [ ] Run disposable Redis and PostgreSQL backup/restore drills where available.
- [ ] Run `scripts/distributed_singleflight_probe.py` against two replicas.
- [ ] Validate alert YAML and target Prometheus rule loading.
- [ ] Run clean-install and Docker Compose smoke checks.
- [ ] Check license, docs, changelog, migration notes, secret scan, `git diff --check`, and `git status`.
- [ ] Do not tag or push until human review accepts the evidence and known limits.
