# Stage 3.9.3 Hotfix 1

This hotfix corrects only the Python import bootstrap used by the live Stage 3.9.3 acceptance client.

Apply the package over the existing `D:\mission_orchestrator` tree, preserving paths, then rerun `STAGE3_9_3_ACCEPTANCE.ps1`.

Expected first two gates after the fix:

```text
[PASS] runtime Stage 3.9.3 active with migration 53 and no authority expansion
[PASS] live Stage 3.9.3 canonical segment QUALIFIED, including exact replay idempotency
```

The remaining acceptance script then performs compilation, canonical inventory, focused regressions, predecessor compatibility, planning structural compatibility, and the full historical regression.
