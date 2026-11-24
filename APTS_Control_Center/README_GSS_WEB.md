# Control Center — aptsGSS Web integration

Module: gss_web, default port 8802. Rilis 2026-10-07 menambahkan halaman Human Layer dan Human Interaction. Includes Mulai, Hentikan, Buka Web,
process log and web health inspection. Web health is not GSS/DB health; open
the console for governance readiness.

- root omitted/empty: inherit modules.gss.root.
- interpreter: explicit gss_web python, then gss python, then GSS .venv interpreter
  if present, then the Control Center interpreter.
- API port: inherits modules.gss.port; the launcher passes --api-port.
- Mission port: inherits modules.mission.port; the launcher passes --mission-port agar Human Layer dapat membuat dan meninjau canonical mission melalui loopback BFF.
- The Control Center only stops processes it owns.
- Keep config.json if it contains your local paths. Run MERGE_GSS_WEB_CONFIG.py
  to add the new module without modifying any existing module configuration.
- Start/restart Control Center after installation; start GSS first, then gss_web.
- Existing Vulndesk Web functionality remains present.

Validation: 17 local Control Center synthetic tests passed. GSS Human Layer/Web targeted suite: 35 tests passed dengan stub driver database; no live APTS service or target was started.
