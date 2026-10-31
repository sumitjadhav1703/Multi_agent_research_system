# Reliability and interface repair

Keep the existing Streamlit application, four research stages, Groq model, and
dark/orange identity. A separate frontend would add deployment work without
addressing the provider failure. Merely catching the critic exception would
leave duplicated requests and broken progress behavior.

1. Share orchestration between the UI and CLI. Preserve completed stages on
   failure, expose a safe error and provider cooldown, and resume explicitly.
2. Bound model output and agent loops. Construct clients only when needed so
   missing configuration does not crash the landing page.
3. Refine the existing interface: native containers, clickable examples,
   live stage progress, report/review/evidence tabs, responsive spacing,
   accessible contrast, and downloads available before review finishes.
4. Test rate-limit recovery, input limits, missing configuration, and reruns
   without provider calls. Inspect desktop/mobile rendering locally.
5. Correct setup documentation and provide reproducible dependencies.

The user selected keeping and polishing dark/orange. This work does not raise
Groq quotas, add providers, add persistence, or claim independent fact checking.
Live provider behavior needs valid deployment credentials and quota.
