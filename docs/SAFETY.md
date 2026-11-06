# Safety and limits
Built for a public site, in `safety.py` (details and settings at the top of that file and in `.env.example`):

1. **Rules**: a blocklist for sexual, hateful, violent / self-harm, illegal-instruction and child-safety content, plus personal data (emails, phone numbers, links) and attempts to hijack the AI. It sees through simple tricks such as `p0rn` or `f u c k` but leaves words like "Scunthorpe" or "naked mole rat" alone.
2. **AI review** of what people type (topic, their own questions) when a Gemini key is set. If it fails, the rules still apply.
3. **Output check**: what the AI writes is checked before it becomes a video, and written again once if it slips. Questions from Open Trivia DB are filtered too.
4. **Limits** (off until you set them in `.env`, for when the site is public): videos per visitor per 10 minutes and per day, a daily cap for the whole site (budget protection), and a one hour pause after repeated blocked requests. Local requests are exempt unless `STRICT_LIMITS=1`. Behind a proxy set `TRUST_PROXY=1`. With accounts, the per-visitor limits become per-plan quotas.
5. **Log**: blocked text goes to `logs/moderation.jsonl` (rule, place, short excerpt, hashed visitor id). Accepted text is never logged.

Security headers are set on every response. Run the tests with `python3 -m unittest discover tests`.
