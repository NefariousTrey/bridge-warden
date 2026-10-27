# Security policy

Bridge Warden is a hackathon project that runs against the **PayPal sandbox only**. No real money moves.

## Reporting a problem

Please don't open a public issue for a security bug. Send a private message to the author,
@Nefarious_Trey on X, with what you found and how to reproduce it.
We'll answer within a few days and credit you in the fix unless you'd rather not be named.

## Design promises (tested)

These are what the code promises. Each is tested in `tests/` (mostly `tests/test_hardening.py`).

1. **The agent proposes; it never pays.** The only path to PayPal is the gate. Blocked actions never run.
2. **A yes is for one exact payment, once.** Approvals are bound to the action's SHA-256; buttons are single use
   and expire; held actions expire after `hold_expires_hours` (24 by default); an action id can't be reused
   for different content.
3. **The AI can only make things stricter.** xAI output is untrusted data: strict JSON, capped, sanitized,
   merged with "worst of", rate-limited, with a circuit breaker. If it fails, local rules decide.
4. **Fail closed.** Bad policy, broken audit log, malformed amount, odd characters or an unknown outcome
   mean "don't pay", never "pay".
5. **Never pay twice.** Every money call carries a `PayPal-Request-Id`; retries reuse it; the gate never re-runs
   a payment by itself; an unknown outcome counts toward limits.
6. **Only two hosts by default, always verified.** `api-m.sandbox.paypal.com` and `api.x.ai`, https only,
   certificates and hostnames checked, redirects refused. (The optional summary model must be on this machine.)
   v4 opt-in hosts, used only with the owner's own key: `api.twilio.com` and `api.trychannel3.com`.
   The alert webhook accepts loopback addresses only.
7. **Secrets stay in the environment.** Read at runtime, never printed, logged or written; scrubbed from
   errors and log records. `python -m bridge_warden selfcheck` scans for leaks and unsafe code.
8. **Private data stays home.** xAI sees a redacted summary inside a delimited data block, only with
   Zero Data Retention confirmed by the owner and by xAI's reply header.
9. **Tamper-evident audit log.** Hash chain + HMAC + signed head, append only, rotation keeps the chain,
   verified at every start.
10. **The owner's screen can't be spoofed.** HTML escaped, control/invisible characters shown as `[U+XXXX]`,
    lookalike payees blocked and non-ASCII payees shown escaped; strict CSP; login cookie; Host/Origin checks.

11. **The owner decides, reversibly.** Every check can be switched off by the owner, never by the agent:
    soft checks after a plain-words warning and `yes`; hard scam blocks (and the master switch while they
    are on) only after the strongest warning and typing `expose me to everything`. Trusted payees skip soft
    checks only. Changes need a real terminal, save the previous version, are logged with old and new policy
    hashes, and can be undone. Pause works at once. Malformed requests, approval hashes, the audit log,
    sandbox-only hosts, fail-closed policy loading and the xAI leak check can't be switched off.

12. **v4 page scripts are pinned.** Every page allows only its own inline script by hash. The History page
    also allows exactly two self-hosted files (AG Grid Community and `bw-grid.js`) by SHA-256, with matching
    `integrity=`. No CDN, no outside fonts. `/static/` serves only those two files, after login.
13. **v4 judge mode holds no secrets.** It refuses to start if any owner secret is in its environment, uses
    practice data only, and never talks to PayPal, xAI, Twilio or Channel3.
14. **v4 calls and price checks are opt-in.** Call me on fraud is a dry run unless the owner adds their own
    Twilio and sets `experimental: true`. Price sanity is off without `CHANNEL3_API_KEY`, sends at most 8
    product words, and can only HOLD.

## Running it safely

- Run the agent as a **different OS user** (or in a container) from the owner. It then can't read the policy,
  the audit key or the log, or answer `review`. This is the one protection code alone can't give you.
- Set `CHECKER_AUDIT_KEY` in the owner's environment (not a file the agent can read).
- Keep `.env` and `policy.json` out of version control (both are git-ignored).
- No dependencies outside the Python standard library at runtime.
