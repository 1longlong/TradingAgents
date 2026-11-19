# Live and external-service tests

External-service tests live here and require explicit network, credential and
cost authorization before execution. Offline runs must not be reported as live
verification. From the repository root, when separately authorized:

```bash
python -m pytest -q test/live
```
