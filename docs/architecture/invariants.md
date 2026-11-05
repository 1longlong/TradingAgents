# Invariant Register

| ID | Statement | Source Requirement | Enforcing Component | Verification | Fallback |
|---|---|---|---|---|---|
| INV-01 | LLM outputs must never directly trigger trade execution. | FR-01 | src/safety/engine.py | Static analysis + negative test | Block execution, log violation |
| INV-02 | The rule engine must be the only entry point to the simulated executor. | FR-01 | src/safety/engine.py | Static analysis of imports | CI failure on direct executor calls |
| INV-03 | The audit log must be append-only. | FR-04 | src/trading/audit.py | Unit test attempts modification/deletion | Raise error and log attempt |
