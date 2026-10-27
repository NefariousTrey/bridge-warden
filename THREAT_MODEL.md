# Bridge Warden: threat model (v3, Oct 26, 2026)

Bridge Warden sits between an AI agent and PayPal. The agent can only *propose* a payment; the rules decide
allow / hold / block, the owner says yes or no to holds, and every step is logged. This file lists what we
protect, who might attack it, where the trust lines are, what we found when we attacked our own v2, and what
is still open. Every fix has a test in `tests/test_hardening.py`.

## What we protect (assets)

1. **The owner's money**: no payment the owner's policy and answers didn't allow; never twice.
2. **The owner's yes**: a yes must mean "this exact payment, once, now", nothing else.
3. **Credentials**: the PayPal sandbox secret, the xAI key, the audit HMAC key.
4. **Private data**: payee emails, names and numbers in descriptions (what may leave the machine).
5. **The audit log**: the record of what happened, which also feeds the duplicate, speed and daily-cap rules.
6. **The policy**: the owner's limits and payee lists.

## Who might attack (attackers)

| Attacker | Can do | Wants |
|---|---|---|
| A. Prompt-injected or confused agent | Propose any action with any text, ids and amounts | Get money out without a real yes |
| B. Scammer writing the text the agent copies | Write the description / payee the agent passes on | Gift-card, "keep it secret", lookalike payee |
| C. Malicious web page in the owner's browser | Send requests to `127.0.0.1:8765`, DNS rebinding, framing | Click "yes" for the owner (CSRF), read the page |
| D. Network attacker | Sit between us and PayPal or xAI | Steal tokens, change replies |
| E. Model output | Whatever xAI (or a local LLM) replies | Loosen a verdict, inject text into the owner's screen |
| F. Local process as the same OS user | Read and write files | Edit the log or policy, approve its own holds |
| G. Accidents | Crashes, timeouts, two windows open, a typo in the policy | Pay twice or run with a broken policy |

## Trust boundaries

```
 untrusted                    | Bridge Warden (trusted code)                   | external, pinned
------------------------------+------------------------------------------------+-----------------------------
 agent / LLM proposal (A, B)  -> input checks -> rules -> gate --(TLS, pinned)--> api-m.sandbox.paypal.com
 xAI reply (E)                <- redacted, delimited data --(TLS, pinned)------> api.x.ai (ZDR checked)
 owner's browser (C)          -> web UI: host, login cookie, origin, nonce+hash
 owner's terminal             -> review (needs a real TTY), shown text made safe
 policy.json (F, G)           -> strict validation, SHA-256 logged, fail closed
 audit log (F, G)             <- append only, hash chain + HMAC, verified on start
 env secrets                  -> read at runtime only, scrubbed from every error and record
```

## What we found in v2 (and what v3 does)

Each item was reproduced against the v2 code before fixing (except where marked "by reading").

| # | Finding | Severity | v3 fix |
|---|---|---|---|
| 1 | **Action-id swap.** An agent could send a $120 payout to a known designer (held), then a $45 payout to `attacker@evil` with the *same* action id. The owner's "yes" on the designer card paid the attacker. | Critical | Ids are unique: first proposal wins; same id + different content is BLOCKED and logged (`id_reuse_refused`); same id + same content returns the first answer (safe retry). An approval must name the action's SHA-256; a mismatch does nothing. |
| 2 | **Disguised scam text passed.** `gi​ft cards` (zero-width space), `gіft cards` (Cyrillic і) and full-width `ｇｉｆｔ ｃａｒｄｓ` were ALLOWED. | High | Text is NFKC-normalized, invisible/bidi characters are removed, and a "skeleton" (confusables, accents, leetspeak mapped) is checked too. Hidden characters themselves trigger a HOLD; terminal control codes a BLOCK. |
| 3 | **Lookalike payee.** `wrіter@...` (Cyrillic) only got a "new payee" hold and looked identical to the known payee on screen. | High | BLOCK when a payee is a lookalike of a known or blocked payee; non-ASCII payees are shown escaped (`wr\u0456ter@...`). |
| 4 | **Amount parsing.** The float `20.5`, `"1e1"` and Arabic digits `"٢٠.٠٠"` were accepted; `"Infinity"` crashed. | High | Amounts must be strings of ASCII digits with at most the currency's decimals (0 for JPY/HUF/TWD), more than zero, at most 9 integer digits. Floats, bools, NaN, Infinity, signs and exponents are blocked. Canonical form ("20.50") is what is shown, hashed and sent. |
| 5 | **Capture id into URL path.** `capture_id="../../v1/payments/payouts"` was only held; a yes would put it in the PayPal URL. | High | Ids must match `^[A-Za-z0-9-]{4,64}$` in the rules AND again in the PayPal client before any path is built. |
| 6 | **Web UI** (by reading): no Host check (DNS rebinding could read the page and its token), no framing protection (clickjacking), no body-size cap, `?m=` let any link put a message on the page. | High | Host allowlist (421 otherwise), login link + HttpOnly SameSite=Strict cookie, Origin / Sec-Fetch-Site checks, form content type, 4 KB cap, single-use 15-minute nonce bound to action id + hash, strict CSP / XFO / no-referrer / no-store, server-side messages only. |
| 7 | **Redirects carry credentials** (by reading CPython): urllib copies the `Authorization` header to a redirect target. | Medium | One network module (`net.py`): pinned hosts (`api-m.sandbox.paypal.com`, `api.x.ai`), https on 443 only, no userinfo, redirects refused, TLS 1.2+ with certificate and hostname checks always on, response size cap. |
| 8 | **Crash or timeout mid-payment** (by reading): "executed" was written only after PayPal answered. A timeout left no record, so the next identical payment didn't look like a duplicate and didn't count toward the daily cap. | Medium | An `executing` intent is logged *before* calling PayPal. Unknown outcomes (timeout, network, 5xx) count as spent for the duplicate/speed/cap rules; only a clear PayPal 4xx rejection doesn't. Nothing is ever resumed or retried by the gate. Network retries inside one call reuse the same `PayPal-Request-Id`, so PayPal de-duplicates them. |
| 9 | **Audit log** (by reading): an unkeyed chain could be recomputed after an edit; cutting lines off the end went unnoticed; two processes (agent `propose` + owner `serve`) could interleave writes; nothing checked it on start. | Medium | HMAC-SHA256 per record (key from `CHECKER_AUDIT_KEY` or a 0600 key file), sequence numbers, a signed head file (catches truncation), `flock` across processes, rotation that keeps one chain, scrubbed records, verified on every start (refuses to run if broken). |
| 10 | **Policy** (by reading): a missing explicit file silently fell back to the example; a malformed one crashed with KeyError; floats in money fields were accepted; nothing recorded which policy was in force. | Medium | Strict validation with clear errors (fail closed before anything runs); money as strings; unknown keys rejected (catches typos); SHA-256 logged as `policy_loaded`, changes since last run logged as `policy_changed`, edits during a run logged as `policy_changed_on_disk` and shown on the page (the loaded policy stays in force until restart). |
| 11 | **Terminal injection** (by reading): the CLI printed raw descriptions, so ANSI codes could rewrite what the owner sees. | Medium | All agent text shown to the owner goes through `display_safe` (control/invisible characters made visible as `[U+XXXX]`). |
| 12 | **AI boundary** (by reading): payload sent as bare JSON; no rate limit; a failing xAI was called every time; reason text unbounded. | Low/Medium | Normalize before redaction (a zero-width `@` can't hide an email); leak check on normalized + skeleton text; payload inside `<payment_data>` with `<`/`>` escaped; 10 calls/minute; circuit breaker (3 failures -> 5 minutes off); reply capped and sanitized. The AI can still only make verdicts stricter. |
| 13 | **Optional local LLM summary** (by reading): could be pointed at any URL and got the payee unredacted. | Low | Loopback URLs only (the README always said "a model you run yourself"); payee replaced by "payee A"; reply sanitized and advisory only. |
| 14 | **Agent self-approval** (by reading): an agent with shell access could pipe "yes" into `review`. | Low (partial) | `review` needs a real terminal. See residual risk R1. |
| 15 | **Secrets in errors** (by reading): exception text went into the log as-is. | Low | Every log record and error is scrubbed of env secret values and token shapes (`Bearer ...`, `A21AA...`, `xai-...`). |
| 16 | Concurrent double approve | Not reproduced | One lock around propose/decide plus the file lock; tested with 8 threads (pays once). |

## User controls (added 9:20 AM ET)

The owner can switch checks, trust payees, pause or switch everything off (`controls`). Threats and answers:

| Threat | Answer |
|---|---|
| Agent turns checks off or trusts itself a payee | Loosening needs a real terminal and a typed confirm; an agent piping `yes` or the phrase is refused and logged (`control_refused`). Loosening only applies at the next start. Residual: an agent running as the same OS user can edit files (R1). |
| Scammer gets onto the trusted list | Trust never skips hard blocks; lookalikes of trusted, known or blocked payees are refused at load and blocked at payment; trusted + blocked is a policy error. |
| Owner talked into "just turn it off" | Plain-words warning of what is lost; hard blocks need the exact phrase `expose me to everything`; every change is logged and undoable. |
| Silent policy edits | Policy hash + control snapshot at every start; on-disk drift logged and shown on the page; a broken file fails closed. |
| Need to stop now | `controls pause` stops a running gate at once, including approvals already waiting. |
| Checks off still leak data | With the master switch off nothing is sent to xAI; the leak check itself can't be switched off. |

## Residual risks (not fixed, on purpose or out of reach)

- **R1. Same-OS-user agent with full shell.** If the agent runs as the owner's OS user, it can read the HMAC key
  file, edit the policy, or drive the owner's terminal. Bridge Warden makes this visible (policy hash, signed log,
  TTY check) but can't stop it in code. Real fix: run the agent as a different OS user (or container) that can't
  read `policy.json`, the audit key or the log. Documented in SECURITY.md.
- **R2. HMAC key on the same machine.** It detects tampering by anyone without the key. Put `CHECKER_AUDIT_KEY` in
  the owner's environment only for full protection.
- **R3. Certificate pinning.** We use the system CA store with full checks, not pinned certificates (pins break
  when PayPal or xAI rotate certs). An HTTPS proxy set in the environment is trusted only if its CA is trusted.
- **R4. Model limits.** The scam model and name scrubber are heuristics; the rules and the human yes are the real
  controls.
- **R5. Sandbox only.** Going live needs a fresh review (real limits, real payees, secrets manager).


## v4 additions (added 11:45 AM ET, Oct 26, 2026)

| Threat | Answer |
|---|---|
| Fake or hacked script on the History page | Only two self-hosted files run, each pinned by SHA-256 in the CSP and in `integrity=`. A changed file is refused by the browser. Other pages keep the v3 CSP unchanged. |
| AG Grid styling needs looser CSP | Not loosened. AG Grid's theme styles get a per-response nonce. Its inline `style=` attributes are **blocked** (about 14 console notices); the grid still works. `img-src data:` is allowed on History only, for AG Grid's icons. |
| AG Grid phones home | The bundle was checked: no fetch, XHR, beacon or WebSocket (tested). `connect-src 'self'` would block it anyway. |
| Judge mode leaks owner secrets or touches real money | Refuses to start if any owner secret is set (names listed, values never printed). Practice data only. Host allowlist, https Origin check, one shared practice cookie, tap rate limit (300/hour), history reset after 1,500 records. |
| Price check leaks private data | Off without the owner's own key. Sends at most 8 product words; payee, emails, numbers, amounts and private terms are removed first. Logged without the key. Only ever adds a HOLD. |
| Price check abused to block | It can't block or send; a fair or unknown price adds nothing. |
| Fraud drill used to scare or trick | Logged as TEST; ends with "This was a test." at the end of the call or as soon as the owner acts; ends by itself after 15 minutes; one test per 10 minutes; nothing sent to PayPal. |
| Webhook sends data out | Loopback addresses only (policy check and network check). |
| Report to PayPal sends data | It never sends anything. It builds a redacted summary and links to PayPal's own pages; the owner sends it. |
| Phone call reveals data | Off by default (dry run). The call says the amount and "new payee" only, never the payee's address. Only the owner's own Twilio and phone. |

R6. **Coverage.** Bridge Warden only sees actions that go through it. A payment made straight in PayPal is not seen.
R7. **Phone choices need a public HTTPS callback.** Locally, a real call can speak but can't hear the answer.
