# Stage 3.9.8 Hotfix 1 — Historical Regression Compatibility

Apply this overlay **over the existing Stage 3.9.8 deployment**.

The authoritative Windows acceptance run proves the Stage 3.9.8 implementation itself is healthy through all pre-full-regression gates:

- runtime activation: PASS;
- Stage 3.9.8 contract route: PASS;
- Python compilation: PASS;
- canonical inventory: `1545 tests collected`;
- focused Stage 3.9.8: `14 passed`;
- Stage 3.9 E2E predecessor chain: `114 passed`;
- recovery authority regression: `82 passed`.

The final historical regression completed with only three stale control-chain assertions:

- `3 failed`;
- `1542 passed`;
- inventory unchanged at `1545`.

No runtime implementation, database migration, authority, recovery semantics, or canonical control chain is changed by this hotfix. Repository migration remains `53`; active control remains:

`stage3.9.8-restart-replay-recovery-e2e-verification`

The canonical suffix is now modeled correctly as:

`... -> Stage 3.9.6 -> Stage 3.9.7 -> Stage 3.9.8`

After applying the overlay, rerun:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_9_8_ACCEPTANCE.ps1
```

Stage 3.9.8 closes only when the final full historical regression reports zero failures.
