# Bridge Warden call Worker (free Cloudflare, workers.dev)

A tiny Cloudflare Worker that answers Twilio during a Bridge Warden **test call**, so the caller can
**press or say** 1, 2, 3 or 4. It runs on the owner's own free Cloudflare account, on `workers.dev`.
No tunnel. No server to keep running. **Not deployed yet. No secrets set yet.**

## What it serves

| Path | What it does |
|---|---|
| `/voice` | The call script and the menu ("Press or say 1 ... Press 4 or say other."). |
| `/gather` | Reads the key press or the words. 1-3 = answer and end. 4 = asks what you need. Unclear = menu once more, then a safe end. |
| `/other` | Reads what you said after option 4. Answers (xAI, if set up) or explains the choices, then the menu once more. |
| `/robots.txt` | Search engines may see the home page only. AI scrapers are blocked. Call paths are blocked for all. |
| `/` | A one-line "nothing to see here" page. |

Same words and same rules as `bridge_warden/notify.py` and `proof/demo/CALL_SCRIPT_v3.md`.
A test (`tests/test_v4_call_menu.py`) checks that the Python and the Worker give the same answer.

Test calls (`?t=1`) always end with: **"This was a test. Nothing happened to your money."**
The call never says a person, agent or human is on the line.

## Safety

- **Signed requests only.** Every `/voice`, `/gather`, `/other` request must carry a good
  `X-Twilio-Signature`, checked with your `TWILIO_AUTH_TOKEN` secret. No token = every call request is refused (403).
- `ALLOW_UNSIGNED = "1"` turns that check off. **Local testing only. Never set it on the real Worker.**
- **Nothing is logged.** No `console.log`; `[observability]` is off in `wrangler.toml`. The caller's words
  are not stored.
- **xAI is optional.** Only with the `XAI_API_KEY` secret. It only gets the caller's short words (cleaned, max
  200 characters), never a phone number. For a choice it can only answer 1-4. Its answer is thrown away if it
  mentions a person or agent. No key = plain word matching, works fine.
  Note: each xAI use costs a small amount on your xAI account; check your xAI data settings (zero data retention) first.
- Keys live only in Cloudflare secrets. They are never in this folder.

## Test it on your computer (no account needed)

```
cd call-worker
node test/test_worker.mjs
```

Should print `worker tests ok`.

## Deploy steps (Trey runs these; nothing here has been run)

1. `cd call-worker`
2. `npx wrangler login`  (pick your own Cloudflare account)
3. `npx wrangler secret put TWILIO_AUTH_TOKEN`  (paste your Twilio auth token when asked)
4. Optional: `npx wrangler secret put XAI_API_KEY`
5. `npx wrangler deploy`
   It prints the address, like `https://bridge-warden-call.<your-subdomain>.workers.dev`.
6. On the computer that runs Bridge Warden, set `BW_CALL_URL` to that address (no slash at the end).
   With it set, the call uses the Worker (press or say). Without it, the call only speaks.
7. Open `https://bridge-warden-call.<your-subdomain>.workers.dev/robots.txt` to check it is live.
   Opening `/voice` in a browser should say 403 (that is correct: it is not Twilio).
8. Run **Test my alert** in Bridge Warden Settings.

To remove it later: `npx wrangler delete` (only when you want to).

Code is Apache 2.0 at the GitHub repo.

---

## Update 2026-10-26 (round 2): the guided walk and call-in

Where this section and the text above differ, **this section wins**.

### New paths

| Path | What it does |
|---|---|
| `/walk` | Walks the caller through PayPal's steps, one at a time: "Press 1 or say done when finished, press 2 or say repeat, press 3 or say skip." Then sums up what they did. Where they are in the walk is kept in the address (`i`, `a`, `x`), not stored. |
| `/inbound` | For when someone **calls in** to your Twilio number. Plays the same menu as a **demo** (always a test). It never reads the caller's number. |

- Every path still needs a good `X-Twilio-Signature`. No `TWILIO_AUTH_TOKEN` = refused (403).
- **Test calls:** any choice or anything said gets "This was just a test. No action is needed." then
  "If this were real, here is what you would do:" and the walk. No xAI in a test call.
- **Real calls:** choices 1 and 2 get the walk for that situation. The steps come only from PayPal's own pages
  (`src/steps.js`, made from `bridge_warden/paypal_steps.json`; a test keeps them the same).
- The call never gives a phone number. It says **"use the number on paypal.com"**.
- Words: `proof/demo/CALL_SCRIPT_v4.md`.

### Set up "A call comes in" (optional)

1. Twilio Console, your number, **Voice configuration**.
2. **A call comes in**: Webhook, `https://bridge-warden-call.<your-subdomain>.workers.dev/inbound`, HTTP POST.
3. Save. Call the number from a **verified** phone.

### Twilio trial limits (read 2026-10-26, twilio.com/docs/usage/trials and .../try-out-voice)

- Calls in are only allowed **from verified numbers** (up to 5). Others get Twilio error 21264.
- A trial call ends after **10 hops** (each answer is about one hop) or **10 minutes**. A long walk with
  many repeats may be cut off.
- Twilio says API-placed trial calls may be limited to its own sample scripts. **Not tested on a real trial.**
  Upgrading Twilio (costs money) removes the trial limits. Owner's choice.

Full plain steps for anyone: `SETUP_YOUR_OWN.md` (repo root).

Made by @Nefarious_Trey,  
with Grok.
