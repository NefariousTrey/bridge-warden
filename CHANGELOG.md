# Changelog

Made by @Nefarious_Trey,  
with Grok.

Dated notes from the build, oldest first. They were copied here from README.md on Nov 4, 2026, word for word,
so the README can tell one current story. The README describes Bridge Warden as it is today; if a note
below disagrees with the README, the README wins.

## v1.0.0-judging (Nov 4, 2026)

- README tells one story: Bridge Warden stands between scammers and your PayPal. Dated notes moved here.
- The hosted judge demo runs on Render. The old "not deployed" lines in the README are gone.
- Timing, said one way everywhere: a real fraud alert rang the phone in about 44 seconds in the sandbox run.
  The Test my alert drill waits up to 20 minutes on purpose, so it feels like a surprise.
- Judge guide (`/judges` and JUDGE_TESTING.md): the whole demo site sits behind a site login, which is in the
  Devpost private testing notes. Two new notes: the free server sleeps when idle, and the AG Studio trial
  license may show a small watermark near the end of judging.
- Legal notice (acceptable use, as is, liability) is now also in JUDGE_TESTING.md and SETUP_YOUR_OWN.md, and
  SETUP_YOUR_OWN.md says Bridge Warden is for adults (18 and over).
- Credit lines in code headers now use the two-line form.
- Shipped again, as public proof: the cleaned sandbox run notes
  ([proof/ACCTWATCH_E2E_RESULT_PC_20261027.md](proof/ACCTWATCH_E2E_RESULT_PC_20261027.md)) and the call scripts
  ([v1](proof/demo/CALL_SCRIPT.md), [v2](proof/demo/CALL_SCRIPT_v2.md), [v3](proof/demo/CALL_SCRIPT_v3.md),
  [v4](proof/demo/CALL_SCRIPT_v4.md)). This updates the Oct 27 correction below.
- Still not in this repo (named in older notes below): screenshots (`proof/ui/`, `proof/ag-agent/`), video files
  and frames (`*.mp4`, `proof/video/`), `DEMO_VIDEO_SCRIPT.md`, and the screenshot scripts
  (`proof/scripts/shots*.py`). Watch the demo video instead: https://youtu.be/gcGDCPxvk98

## v4 (Oct 26, 2026)

## New in v4: the Bridge Warden app

**Pitch: Bridge Warden shrinks the time fraud goes unnoticed from days to minutes, saving users and PayPal.**

Run `python -m bridge_warden serve --live` and open the login link it prints. It runs only on this computer.

- **One light, three colors.** Green: everything working. Yellow: paused, or a check needs a look. Red: something
  bad happened (until you respond), or Bridge Warden is off. Safe payments go
  through silently. You only hear from Bridge Warden when something is wrong.
- **Held card:** Send (one tap, for this exact payment, once), Hold, or Cancel. **Blocked card:** Why? in plain
  words. Nothing on the page can unblock a hard block.
- **Red-light flow:** "What do you want me to do?" Keep everything blocked / Show me how to lock PayPal /
  I'm fine. Bridge Warden can block and guide you. It **can't** lock PayPal for you.
- **Report to PayPal:** a ready summary (what happened, times, amounts, IDs from the audit log, names removed)
  plus links to PayPal's own Resolution Center and fraud page. **You send it yourself.** Nothing is reported
  for you.
- **Check my money:** read-only. Recent activity and subscriptions from PayPal (sandbox). It never changes
  anything. The AI chat gives advice only: it can never send, approve or change settings.
- **Alerts:** desktop alerts, plus an optional webhook to an address on this computer only (loopback).
- **Settings:** a switch per check, trusted list, master pause, and plain-words warnings. Turning a hard block
  off still needs the phrase `expose me to everything` **and** a real terminal (same rules as v3).
- **History:** every move, signed and chained, TEST lines marked. Download it as proof for a dispute. Shown as
  a sortable grid (AG Grid), with the plain table kept as a fallback.

### Call me on fraud (proven live in the PayPal sandbox)

- **Off by default.** With no setup it is a **dry run**: it writes "would call owner" in the log. No call.
- A real call only happens if **you** put **your own** Twilio account on this computer
  (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, `BW_OWNER_PHONE`) **and** set
  `"experimental": true` under `notify.call_on_fraud`. Every user pays their own Twilio. We pay for nothing.
- **Proven live, Oct 27, 2026 (PayPal sandbox, real phone).** A fake $1 payout sent straight to PayPal, not
  through Bridge Warden, rang the owner's phone in about **44 seconds**. Bridge Warden's own part took
  **0.66 s** (webhook in, verified with PayPal, red, call request out). The rest is PayPal's sandbox delivering
  the event. PayPal sent **3 webhooks** for that one payout: Bridge Warden made **one** alert and **one** call.
  The after-call check re-read the payout at PayPal and came back clean.
  Trey's own report of the call (no recording was made): it told him about the payout, he said it was him, and
  Bridge Warden said OK but kept it on hold until he approves it in the app. A phone answer can't clear a hold.
  Proof: [proof/ACCTWATCH_E2E_RESULT_PC_20261027.md](proof/ACCTWATCH_E2E_RESULT_PC_20261027.md).
  Call script: [proof/demo/CALL_SCRIPT.md](proof/demo/CALL_SCRIPT.md).

### Test my alert (a fraud drill)

Settings → **Test my alert** starts a drill that feels real but is not:

1. It is logged as **TEST**. No real payment. Nothing is sent to PayPal.
2. The light goes red and an alert fires. If xAI is set up, xAI gets a redacted message marked TEST
   (Zero Data Retention) and acts as if it were real, so you learn the real flow.
3. While the drill runs, **every** money action waits for you (any payee, any app).
4. A call comes with no warning, within 20 minutes (dry run unless your own Twilio is set). The app only says
   "Test started." so the call feels like a real alert. One test per 20 minutes (checked on the server).
5. It ends with **"This was a test."** at the end of the call, or as soon as you act in the app. It also ends
   by itself after 15 minutes, and you can end it any time.

### Sponsor tools (nothing signed up, nothing deployed)

- **AG Grid Community (MIT, free, no license key).** History grid in Bridge Warden colors. The files are
  self-hosted in `bridge_warden/static/` and pinned by SHA-256 hash in the page's security rules
  (CSP) and in `integrity=`. No CDN, no outside calls. If the grid does not load, the plain table stays.
- **Render-ready judge mode.** `render-judge.yaml` + `python -m bridge_warden judge`. Practice data only: no
  PayPal, no xAI, no keys. It **refuses to start** if any owner secret is in its environment. It has
  play-the-agent buttons (safe, gift-card scam, prompt injection, new payee, too-cheap seller). Not deployed.
  Run it locally: `python -m bridge_warden judge` then open `http://127.0.0.1:8765/`.
- **Channel3 price sanity (soft check).** A price far below what stores ask (under 40% of the typical price,
  needs 3+ store prices) gets **held** for your yes. It never blocks or sends. **Off unless you set your own
  `CHANNEL3_API_KEY`.** Only up to 8 product words are sent (no payee, emails, numbers, amounts or private
  terms). You can switch it off like any soft check (`controls off price_sanity`). Mocked in tests.

### v4 test results

v4 results (Oct 26, 2026): **315 passed, 2 skipped** offline (the 2 skipped are the live tests);
live sandbox + live xAI: **2 passed**. `selfcheck: ok`. Screenshots: `proof/ui/`. Captioned demo (2 min 43 s,
no sound): `proof/demo/bridge-warden-v4-demo-captioned.mp4`.

## Update 2026-10-26: Trey's status dots and color-blind mode

- **Status light** is now Trey's energy-ring art (plain ring, 64 px on screen, 96/128 px files):
  green = all clear, red = issue / payment held, **yellow = paused / attention** (yellow replaces the old gray).
  (Since 2026-10-27: Off shows red, not yellow. See "Paused is yellow, Off is red" below.)
  Alt text: "All clear", "Issue: payment held", "Paused / attention". The screen-reader word is now "Yellow".
- **Color-blind mode** (Settings, default **off**, one tap either way): swaps the big light for Trey's yellow orbs
  with a hidden symbol: X = issue, ! = attention, check = all clear (96 px on screen, 128/256 px files).
  Saved in `policy.json` as `"ui": {"colorblind_mode": true}`, with a copy in `policy_history/` and a
  `ui_pref_changed` line in the signed log. Display only: it never changes what money can move. On a view-only
  run (no `policy.json`) it lasts for the session only.
- **List rows** (Recent money moves) get a 24 px ring + crisp-glyph dot in both modes.
- Images are local files only, served from an allowlist at `/assets/dots/` (PNG/WebP, `nosniff`). The page CSP is
  unchanged (`img-src 'self'`, no inline styles or scripts beyond the hashed ones).
- Art: `assets/dots-trey-energy-20261026/`, `assets/dots-trey-cvd-20261026/`. Art by @Nefarious_Trey, MIT (own `LICENSE`
  in each folder; was Apache 2.0 earlier on Oct 26). The logo and any music stay all rights reserved: see `ASSETS_NOTICE.md`.
- Results (Oct 26, 2026): **348 passed, 2 skipped** offline (33 new in `tests/test_v4_dots.py`). `selfcheck: ok`.
  New screenshots: `proof/ui/26-…` to `proof/ui/35-…` (script: `proof/scripts/shots_dots_20261026.py`).


## Update 2026-10-26 (later): full dots, not rings

Trey said: "You made my dot a ring." Fixed. The normal-mode status light and the 24px list dots now use
`assets/dots-trey-energy-full-20261026/`. It keeps his whole dot: the smoky inner disc stays solid as painted,
the bright rim and spark halo stay, and only the area outside the halo fades out. A soft dark disc sits
under it so it reads on the white card. Same sizes (24/48/96/128/256), PNG + WebP, plain (`-full-`) and with
the glyph (`-full-glyph-`). Made from copies of his 3 originals. Build script:
`proof/scripts/make_trey_full_dots_20261026.py`. MIT (own `LICENSE`), same notice as the energy folder.

The old ring set in `assets/dots-trey-energy-20261026/` is still on disk, just not used. Colour-blind mode
is unchanged. Screenshots: `proof/ui/36-*` to `proof/ui/40-*`.

Correction (same day, Trey's rule): the full dots are now a clean circle cut from his image. Everything
inside the circle (rim, spark halo, inner disc and the background smoke) is kept exactly as he made it. No
brightness-to-alpha, no dark parts removed, no backing disc. Only pixels outside the circle are clear.
The first pass (with fades and a backing disc) is kept outside the repo
(not shipped).

Tight pass (same day, Trey: "close, your ring isn't touching the edge"): the circle cut now sits right on
the outer edge of his glowing ring, so the ring touches the edge of the image (1px anti-aliased edge; a
little outer spark fuzz is clipped). The ring center and outer edge were measured from each of his images,
not guessed: fit a circle to the brightest point on 360 rays, then take the radius where the median
brightness falls halfway from the ring peak to the background. Measured, in source pixels:
red center (578.5, 861.5), ring peak r 348.5, cut r 388.0; green (578.3, 840.4), 349.5, 372.5;
yellow (573.0, 840.8), 349.5, 379.0. Saved in `assets/dots-trey-energy-full-20261026/measured-radii-tight-20261026.json`.
Everything inside the circle is still exactly as he made it: no brightness-to-alpha, no fades, no backing
disc. Same file names, so the app wiring is unchanged. The loose pass is kept outside the repo
(not shipped). Screenshots: `proof/ui/41-*` to
`proof/ui/45-*` (script: `proof/scripts/shots_tightdots_20261026.py`). Results: **352 passed, 2 skipped**;
`selfcheck: ok`.

**Trey's dots carry their own non-color cue.** Look at the center of each dot: the dense middle is slanted
a different way in red, green and yellow, so you can tell them apart without color. Trey designed that into
the art before colour-blind mode ever came up. Colour-blind mode (the hidden-symbol orbs) builds on it; it
does not replace it.

## Update 2026-10-26: press or say the call menu, and the call Worker

- The test call menu now takes a **key press or spoken words**: "Press or say 1 for help securing your account.
  Press or say 2 to report this activity to PayPal. Press or say 3 if this was you. Press 4 or say other."
  Option 4 asks what you need, answers briefly (advice only), and offers the menu again. It never says a person
  is on the line. Unclear answers get the menu once more, then a safe end. Test calls end with
  "This was a test. Nothing happened to your money." Script: `proof/demo/CALL_SCRIPT_v3.md`.
- Twilio needs a public https address for this. It is a small **Cloudflare Worker** on the free `workers.dev`
  plan, in `call-worker/` (no tunnel). It checks Twilio's signature and logs nothing. **Not deployed.**
  Steps: `call-worker/README_WORKER.md`. Set `BW_CALL_URL` to the Worker address to use it; without it the call
  only speaks and you choose in the app.
- xAI is optional for unclear words (`XAI_API_KEY` as a Worker secret). Without it, plain word matching works.
- `/robots.txt` on the app and the Worker: search engines see public pages only, AI scrapers are blocked, and
  call/API paths are blocked for all. Responses carry `X-Robots-Tag: noai, noimageai`.
- Tests: `tests/test_v4_call_menu.py` and `node call-worker/test/test_worker.mjs`.

## Update 2026-10-26 (round 2): set up your own call, judges, and the guided walk

- **Set up your own call:** [SETUP_YOUR_OWN.md](SETUP_YOUR_OWN.md). Free Twilio trial, your own phone, your own
  free Cloudflare Worker (optional), trial limits. You pay your own Twilio; we pay for nothing.
- **Judges:** [JUDGE_TESTING.md](JUDGE_TESTING.md). No one has to give a phone number.
- **Hear the call in your browser:** open `/hear` (link in Settings and on the judge page). Your browser reads
  the call out loud. Buttons, typing, or an optional mic. "Demo. Nothing happens to your money." No number,
  nothing sent anywhere.
- **Guided walk:** after a choice, the call walks you through **what PayPal says to do**, one step at a time
  (done / repeat / skip), then sums up. Six situations: a payment you did not make, a login you do not know,
  a fake PayPal message, a risky buy, a risky sale or chargeback, a limited account. Every step cites a PayPal
  page (read 2026-10-26). Nothing PayPal does not say. The call never gives a phone number: "use the number
  on paypal.com". Test calls say "This was just a test. No action is needed." first.
- Same words in the phone call, the Worker and the browser demo, from one file
  (`bridge_warden/paypal_steps.json`). Script: [proof/demo/CALL_SCRIPT_v4.md](proof/demo/CALL_SCRIPT_v4.md).
- Call-in demo: the Worker's `/inbound` (see `call-worker/README_WORKER.md`). On a Twilio trial only verified
  numbers can call in.
- **Since then:** a real call was placed and answered from a live PayPal sandbox event (Oct 27; see
  "Call me on fraud" above). The app is not deployed publicly.
- Copyright lines read: "Copyright 2026 Trey (@Nefarious_Trey)".
- Tests: `tests/test_v4_hear.py`, `tests/test_v4_call_menu.py`, `node call-worker/test/test_worker.mjs`.

## Update 2026-10-26 (night): host your own copy on Render (optional)

Our prize target is **AG Grid** (the History grid). Render is **only** an easy way to host your own copy.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/NefariousTrey/bridge-warden)

(For a fork, change the repo in that link to yours. `render.yaml` must stay at the repo root.
Docs: https://render.com/docs/deploy-to-render and https://render.com/docs/blueprint-spec .)

- Render asks you for: your Twilio Account SID, Auth Token and phone number, your own phone, your preferred
  name, and the call voice (blank = "man", Twilio's free voice; or a Chirp voice like `Google.en-US-Chirp3-HD-Charon`).
  (Since 2026-11-02 Render no longer asks for the name and voice. Add `BW_PREFERRED_NAME` or `BW_CALL_VOICE`
  later under Environment if you want them. See the 2026-11-02 update below.)
- Render makes two random secrets for you: `BW_LOGIN_KEY` (paste it on the login page) and `BW_CALL_LINK_KEY`.
- Your copy answers the call menu itself (`/voice`, `/gather`, `/other`, `/walk`), so you do **not** need the
  Cloudflare Worker. Each call link is signed and expires (same check as the Worker); Twilio's own signature is
  also accepted. Call logs stay in **your** Twilio account.
- **Free plan: no disk.** History, audit log and settings changes are lost when the service sleeps (15 minutes
  idle), restarts or redeploys. You will need to log in again. Your Twilio settings are kept. A paid plan plus a
  disk (`BW_DATA_DIR=/var/data`) keeps them. See https://render.com/docs/free .
- The hosted copy is the dashboard plus real alert calls. Your AI agent still runs on your own computer.
- `python -m bridge_warden serve` stays localhost-only, exactly as before.

Made by @Nefarious_Trey,  
with Grok.  
Copyright 2026 Trey (@Nefarious_Trey).

## Update 2026-11-02: one-click Deploy to Render, with your own Twilio

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/NefariousTrey/bridge-warden)

One click makes a full Bridge Warden on **your own** free Render account. Render asks for a few boxes, all
optional (type `none` to skip one): your phone, your own Twilio Account SID, Auth Token and phone number, your own
xAI key, and your PayPal sandbox app and webhook. Your login password (`BW_LOGIN_KEY`) is made for you: find it in
Render, under your service, Environment.

- **The real phone call is still here.** It uses **your own** Twilio account, so you set up Twilio yourself
  (console.twilio.com: Account SID, Auth Token, a Twilio number). A Twilio trial is free but only calls numbers
  you verified in Twilio, and plays a short trial message first. The shared judge demo never rings a phone.
- No Twilio yet: **Test my alert** opens Hear the call, the same call in your browser.
- No xAI key: the local safety rules still check every payment. (AI calls also need `XAI_ZDR_CONFIRMED=1`.)
- No PayPal boxes: `/paypal-webhook` is off.
- A fresh copy opens in **Dev mode** with sample data marked TEST (`BW_DEMO_DATA=on`). Turn Dev mode off in
  Settings to use your own data, and for a real Test my alert phone call (Dev mode never rings a phone).
- Costs: Render free plan $0 (sleeps after 15 minutes idle; history is lost on sleep or redeploy). Twilio bills
  **your** Twilio account for real calls. xAI bills **your** key if you add one. PayPal sandbox is free.
- The button only works while this GitHub repo is public.
- Steps and the full box list: [JUDGE_TESTING.md](JUDGE_TESTING.md) ("Your own copy, in one click").

## Update 2026-10-27: Red, then yellow (pause while you fix)

- **Green:** everything is working.
- **Yellow:** a state check found something, or Bridge Warden is paused while you fix a problem.
- **Red:** something bad happened. It stays red until you respond, even after a restart.
- **Off** also shows red. **Paused** shows yellow (see "Paused is yellow, Off is red" below).
- When you respond to a red ("Got it, I've seen the blocked ones" or "Got it, pause until I decide") but it is
  not fixed yet (a held payment still waits, or a state check is still open), the light steps **down to yellow**.
  Bridge Warden stays paused: new payments wait for you, so nothing piles up while you fix it.
- When it is all fixed, the light still waits on **yellow** until you click **It's fixed** (or Ignore with
  **I'm sure** ticked). Red never goes straight to green.
- Every color change adds a line to **History** with the time, for example
  "Bridge Warden paused operations: light set to yellow while you fix it." and
  "Bridge Warden resumed operations: light set to green."
- A new problem while yellow turns the light red again. Dev mode Simulate buttons still work and are not logged.

## Update 2026-10-27: Paused is yellow, Off is red

- **Paused** (by you): the light is **yellow**. No money moves until you resume. Payments refused only because
  you paused do not turn it red.
- **Off**: the light is **red**. Nothing is checked, so nothing is guarded. Turn it back on and it steps to **yellow**; your own
  **It's fixed** click turns it green.
- An alert you have not answered yet still shows **red**, even while paused, until you respond. Then the
  red-then-yellow rules apply. "Keep everything blocked" counts as your answer: it pauses, and the light goes yellow.
- A missed-call final notice stays red until you clear it, even when Off.
- Email on every missed call stays the same.
- History gets a timed line for each change, for example "Bridge Warden paused by you: light set to yellow.",
  "Bridge Warden turned off: light set to red." and "Bridge Warden turned on: light set to yellow until you confirm."

## Update 2026-10-27 (v6): the BW AG Grid agent on History

**What it does (History page).**
- Sorts your spending into **bills, subscriptions, gas, food and other**: a donut, month bars and a sortable
  AG Grid, in Bridge Warden colors. Data: `/money-map.json` (owner login only).
- Flags **money spikes**: a burst of refunds, failed payments, and amounts far above your usual for a place.
- Finds **duplicate subscriptions** (same service paid twice), ones that look **unused**, and price rises.
- Reads Bridge Warden's own signed log (read-only) for stuck reds, repeat blocks and holds, and cross-checks
  xAI's notes against the real rules and amounts. A contradiction becomes a flag.
- **Local rules decide. AI only explains.** No AI call is needed for any flag.

**What it can and can't do.** It can only **raise** the light, to yellow or red. It can never turn it
green, approve, release a hold or move money. "I've seen this" (or answering the fraud call) steps red down
to yellow, never to green. Only you turn yellow green: "It's fixed", or Ignore with the
"I'm sure, I want to ignore this" tick and the note "We recommend fixing this instead of ignoring it. It's
your money, your call." Sending a held payment also needs an "I'm sure" tick. Every step is in History.
Tested end to end in Dev mode (`proof/ag-agent/`, `tests/test_v6_ag_agent.py`).

**BW Light.** BW Light is Bridge Warden's status light: one red, yellow or green dot that shows BW's verdict on
the account, plus the reason and the last time it went red. It is a small card on every BW page (works with no
script) and an AG Studio custom widget (`bridge_warden/ag_light.py`, `bridge_warden/static/bw-light-widget.js`).
It has two owner buttons. "I've seen this" steps red down to yellow. "It's fixed" turns yellow green. **Red can
never jump straight to green**: if the light is red, "It's fixed" is refused and logged
(`owner_light_ok_refused`). The buttons run BW's existing owner rules only. They need your login, the same
origin and a one-time token tied to the light you saw. The AI chat gets no tool for them, and the widget drops
any click that is not a real person's click. BW Light has no way to pay, release a hold or move money.

**Two chats, two lanes (both read-only).** History has the BW AG Grid agent chat (past patterns); the home page
has the "now" chat (what is happening right now). Both use xAI with your own `XAI_API_KEY`, give short
step-by-step fix walk-throughs, and can't approve, ignore, turn green or move money.

**Real usage numbers only.** Under each answer: the tokens and cost xAI reports for that call
(`usage.cost_in_usd_ticks`, 10,000,000,000 ticks = $1). Where a provider gives no limit:
"limit not available from provider". We never estimate.

| Provider | Per-call use | Cost | Limit / remaining |
|---|---|---|---|
| xAI | yes (tokens) | yes (per answer) | not available from provider |
| Twilio | yes (call length) | yes (call price) | yes (account balance) |
| PayPal | n/a (no usage billing) | n/a | n/a |

**Ask the BW AG Grid agent (AG Studio, optional).** A dashboard + AI chat panel built with AG Studio's Agent
Framework (`AgStudioAiModule`, `createAiHarness`, `directLlmRunner`) and our own xAI adapter.
- The browser talks only to Bridge Warden (`/ag-studio/v1/responses`); the server calls xAI with your key.
  **The xAI key never reaches the browser.** 4 custom tools, all read-only: `bw_spending_categories`,
  `bw_subscriptions`, `bw_audit_flags`, `bw_show_issue` (points at a button, never presses it).
- AG Studio is **commercial** and **not in this repo**. Get it with `scripts/fetch_ag_studio.sh`
  (ag-studio 3.0.0 from npm, SHA-256 pinned, saved to the git-ignored `bridge_warden/vendor/ag-studio/`).
- Licence key: `export BW_AG_STUDIO_LICENSE_KEY=...` (env only, never logged). AG Grid's licence design needs the
  key in the page, so it is sent only to the logged-in owner. With no key it runs in trial mode with a
  watermark. Trial: https://www.ag-grid.com/studio/license-pricing/?tab=trial
- It runs in its own framed page, `/ag-studio/panel` (owner login, `frame-ancestors 'self'`, scripts hash-pinned,
  inline styles allowed only inside that frame). The History page CSP stays strict. Without AG Studio, History
  shows the plain AG Grid Community view and everything else works.
- Known: AG Grid Community still logs about 280 "inline style blocked" CSP notices per History load (cosmetic,
  the grid renders). The Studio panel is narrow at small widths.

**Proof.** Screenshots `proof/ag-agent/01-…` to `08-…` (+ `RESULT.json`), video frames at 1920x1080 in
`proof/video/` (`frame-01-…` to `frame-04-…`, `bw-ag-agent-frames-1920x1080.mp4`). The Studio chat answer in
the frames is a labeled **TEST STUB**, not a real xAI call. Script: `proof/scripts/shots_ag_agent_v6_20261027.py`.
Tests: **881 passed, 2 skipped**, plus `node tests/node/test_bw_studio.mjs` and `node call-worker/test/test_worker.mjs`.

## Update 2026-10-27 (v6, audit fixes)

Corrections from the v6 audit. The text before each edit is kept in a dated backup (not shipped).

- **Credit.** Designed and built by @Nefarious_Trey, with Grok as a coding assistant. The credit reads
  "Made by @Nefarious_Trey, with Grok." The copyright line reads "Copyright 2026 Trey (@Nefarious_Trey)".
- **Red never straight to green, Off included.** Off shows red. Turning Bridge Warden back on now steps to
  **yellow** (paused) with the card "Back on: confirm all is fine". Only the owner's own **It's fixed** click (or
  Ignore with **I'm sure** ticked) turns it green. The lines above that said "goes straight to green" and
  "turn it back on to go green" are corrected. Tests: `tests/test_v6_red_never_green.py`,
  `tests/test_v5_pauseoff.py`.
- **Paths.** Build-box paths and the PC run notes were removed from the shipped files.
- **Demo video.** The final cut is `bw_demo_v9_20261028.mp4`, 2:58. The public YouTube link is added at submission.

## Correction (Oct 27, 2026): files not in this repo

The repo was slimmed to the app, tests, licenses and how-to docs. Some lines above name files that are
**not in this repo** any more. Please use these instead:

- **Demo video, captioned demos, video frames** (`*.mp4`, `proof/demo/`, `proof/video/`, `DEMO_VIDEO_SCRIPT.md`):
  watch the demo video: https://youtu.be/gcGDCPxvk98. It is also linked on the Devpost page.
- **Call scripts** (`proof/demo/CALL_SCRIPT*.md`): the words of the call are in the code,
  `bridge_warden/paypal_steps.json` and `bridge_warden/notify.py`, and the tests check them.
  You can also hear the call in your browser at `/hear` (judge mode).
- **Screenshots** (`proof/ui/`, `proof/ag-agent/`): see the demo video and the Devpost gallery.
  The Judge Guide screenshots are here: `proof/judges/judges-light.png` and `proof/judges/judges-dark.png`.
- **Screenshot scripts** (`proof/scripts/shots*.py`): not shipped.
- **Run notes** (`proof/ACCTWATCH_E2E_RESULT_PC_20261027.md`): not shipped. How to run that check:
  `proof/scripts/ACCTWATCH_E2E.md`.
- **Judges:** start with the Judge Guide page, **/judges**, or `JUDGE_TESTING.md`.
- Code: https://github.com/NefariousTrey/bridge-warden

Made by @Nefarious_Trey,  
with Grok.

## Update 2026-10-28: PayPal account events on your Render copy, with an xAI second look

- Your Render copy now has `POST /paypal-webhook` for PayPal **sandbox** webhooks. It is off ("not set up")
  until you fill in `PAYPAL_CLIENT_ID`, `PAYPAL_SANDBOX_SECRET` and `BW_PAYPAL_WEBHOOK_ID` in Render.
  How to register `https://bridge-warden.onrender.com/paypal-webhook` with PayPal: see
  [SETUP_YOUR_OWN.md](SETUP_YOUR_OWN.md), "On your Render copy (no tunnel needed)".
- No login on that one address, but every event still gets the acctwatch checks: 64 KB cap, PayPal headers,
  sandbox cert host, 5 minute window, replay guard, and PayPal's own signature check on the raw body.
- After the fixed rules, if `XAI_API_KEY` is set (and `XAI_ZDR_CONFIRMED=1`), events the rules did not flag get an
  xAI second look on a scrubbed summary (no emails, names or private words; a leak check runs before sending).
  Stricter only: xAI can turn an event red, never clear one. xAI errors keep the rules result. Same rate limit,
  breaker and ZDR checks as the payment checks. Each look is saved in History.
- Tests: `tests/test_v6_hosted_paypal_events.py` (all faked: no PayPal, Twilio or xAI calls).
