# Set up your own call

Made by @Nefarious_Trey,  
with Grok.

Bridge Warden can **phone you** when it sees fraud. You use **your own** Twilio and **your own** phone.
Bridge Warden pays for nothing and never sees your Twilio password.

**Just want to hear it?** You do not need any of this. Open `/hear` in Bridge Warden. It plays the call
in your browser. No phone, no number, nothing sent.

Short words. One step at a time. Facts about Twilio were read on 2026-10-26 from
<https://www.twilio.com/docs/usage/trials> and <https://www.twilio.com/docs/usage/trials/try-out-voice>.
Twilio can change these. Check their pages.

---

## Part 1. Get a free Twilio trial

1. Go to twilio.com and sign up. No card needed for the trial.
2. Use **your own** phone number to sign up. Twilio checks it with a code. That number is now **verified**.
3. In the Twilio Console, open **Voice**, then **Try out Voice**. Twilio gives you a **trial number**.
4. Write down 3 things (keep them private, never post them):
   - Account SID (starts with `AC`)
   - Auth token
   - Your trial number (like `+15551234567`)

## Your name on the call (so it is not spam)

The call starts by saying **your** name: **"Hi Trey, this is Bridge Warden."** That way you know it is your own
alert, not a spam call. With no name set, it says **"Hi, this is Bridge Warden."**

- Set it in **Settings, Alerts, Your name for calls**, then **Save**. Or in `policy.json`:
  `"preferred_name": "Trey"`
- Letters, spaces, hyphens and apostrophes only (like `Mary-Jo O'Neil`). Up to 40. Anything else is refused,
  and the call uses the plain greeting.
- Real fraud calls use it after you restart Bridge Warden. Test calls never use it: they say "Hello, this is Bridge Warden." or "Hello <name>, ..." with the optional name typed on the Test my alert form (that name is used for that one call only, never logged or saved).
- With your Cloudflare Worker (Part 3), the name rides on the call address that Twilio signs, so nobody can
  change it on the way. The Worker checks the name again before it speaks it.
- The call in to your Twilio number (Part 4) is a demo. It never says a name.

## Part 2. Put the call on your computer (no Cloudflare)

This is the simple way. The call **speaks** the alert. You make your choice in the Bridge Warden app.

1. On the computer that runs Bridge Warden, set these 4 values in its environment
   (not in any file you share):
   - `TWILIO_ACCOUNT_SID` = your Account SID
   - `TWILIO_AUTH_TOKEN` = your auth token
   - `TWILIO_FROM_NUMBER` = your Twilio trial number
   - `BW_OWNER_PHONE` = your own (verified) phone number
2. In `policy.json`, under `notify`, set:
   `"call_on_fraud": {"enabled": true, "provider": "twilio", "experimental": true}`
3. Start Bridge Warden: `python -m bridge_warden serve --live`
4. Go to **Settings**, then **Test my alert**. You see "Test started." Your phone rings with no warning,
   within 20 minutes. One test per 20 minutes.
   It is a **test**. Nothing happens to your money.

Leave out any of the 4 values and it is a **dry run**: no call, just a line in the log.

## Part 3. Press or say your choice on the phone (your own Cloudflare Worker)

To press or say 1, 2, 3 or 4 **on the phone**, and get walked through PayPal's steps, Twilio needs a public
https address to send your answer to. That is a tiny **Cloudflare Worker** on **your own** free Cloudflare
account (a `workers.dev` address). No server to keep running.

1. Make a free Cloudflare account at cloudflare.com.
2. Install Node.js on your computer.
3. In a terminal:
   ```
   cd call-worker
   node test/test_worker.mjs          # should print: worker tests ok
   npx wrangler login                 # pick YOUR Cloudflare account
   npx wrangler secret put TWILIO_AUTH_TOKEN
   npx wrangler deploy
   ```
   - `secret put` asks for your Twilio auth token. Paste it there. It goes into Cloudflare, not into a file.
   - `deploy` prints your address, like `https://bridge-warden-call.<your-name>.workers.dev`.
   - Optional: `npx wrangler secret put XAI_API_KEY` (helps with unclear words on real calls; costs a little on
     your xAI account; never used in test calls). Without it, plain word matching works fine.
4. Check it: open `https://bridge-warden-call.<your-name>.workers.dev/robots.txt` (should show text).
   Opening `/voice` should say **forbidden**. That is right: only Twilio may use it.
5. On the Bridge Warden computer, set `BW_CALL_URL` to that address (no `/` at the end).
6. Run **Settings, Test my alert** again. Now you can press or say your choice on the phone.

Never set `ALLOW_UNSIGNED` on the real Worker. It is for testing on your own computer only.

To remove the Worker later: `npx wrangler delete` (only when you want to).

### Call voice (optional)
By default the call uses Twilio's free basic voice (`man`). No extra cost, but it sounds robotic. For a natural voice, set the Worker variable `CALL_VOICE`. Either add it to `call-worker/wrangler.toml`:
```
[vars]
CALL_VOICE = "Google.en-US-Chirp3-HD-Charon"
```
or in the Cloudflare dashboard, open Workers, then bridge-warden-call, then Settings, then Variables, and add the plain-text variable `CALL_VOICE`. If you place calls without the Worker, set `BW_CALL_VOICE` the same way on your computer.
Natural voices cost a small Twilio fee per 100 characters spoken, billed to your own Twilio account ([Twilio voice pricing](https://www.twilio.com/en-us/voice/pricing/us), as of Aug 2026):
- `Polly.Joanna` (Standard): $0.0008 per 100 characters, about $0.02 to $0.03 for a full call.
- `Polly.Joanna-Neural` (Neural): $0.0032 per 100 characters, about $0.07 to $0.13 for a full call.
- **Call voice (our Worker):** `Google.en-US-Chirp3-HD-Charon` (Google Generative): about $0.039 per call (~300 characters) plus Twilio's per-minute call price (about $0.014 a minute in the US). Use the exact Twilio form `Google.<locale>-Chirp3-HD-<Name>`.
- Leave it unset (or `man`) for the free voice. An unknown voice name falls back to the free voice.
[Voice list](https://www.twilio.com/docs/voice/twiml/say/text-speech)

### Change your call voice
**The easy way: Settings.** Sign in to Bridge Warden (open your app's address and enter your login key). Go to **Settings**, then **Alerts**, then **Call voice**. Pick a voice and press **Save**. Each voice shows its tier and rough cost per call. Your next call uses it, real or test, with no restart.

| Tier | Example | About per call (~300 characters) |
|---|---|---|
| Free | `man`, `woman` (robotic) | free |
| Standard | `Polly.Joanna`, `Polly.Matthew` | ~$0.0024 |
| Neural | `Polly.Joanna-Neural` | ~$0.0096 |
| Generative | `Google.en-US-Chirp3-HD-Charon` (our pick), `Polly.Matthew-Generative` | ~$0.039 |

Every call also pays Twilio's minute price (about $0.014 a minute in the US). Twilio bills your own account.
- **Default** means you have not picked a voice, so the server setting below is used. Bridge Warden's own Worker uses Charon.
- **While Dev/Test mode is on**, a pick only changes test calls. Your real fraud calls keep the voice you saved before.
- **The Test my alert form** has its own voice box, used for that one test call only and never saved. Judges use this one.
- The pick is saved as `"call_voice"` in your `policy.json`, and Settings only accepts voices from the list. If you edit the file by hand and the name is unknown, the call falls back to the free voice. The voice rides on the signed call link, so nobody can change it in the middle of a call.

**By hand (server default).** Set `CALL_VOICE` on your Worker (see above) or `BW_CALL_VOICE` on your computer or Render to any name from [Twilio's voice list](https://www.twilio.com/docs/voice/twiml/say/text-speech), for example `Polly.Joanna-Neural`. This is the voice used when nothing is picked in Settings.

## Part 4 (optional). Call your Twilio number and hear the demo

You can also **call in** to hear the demo call.

1. In the Twilio Console, open your trial number's settings.
2. Under **A call comes in**, choose **Webhook**, method **POST**, and paste:
   `https://bridge-warden-call.<your-name>.workers.dev/inbound`
3. Save. Call your Twilio number **from your verified phone**.
4. You hear: "This is a Bridge Warden demo call. Nothing happens to your money." Then the same menu.
   It is always a test. The Worker never reads or keeps the caller's number.

## Judge keys

Put one key per line (16+ characters) in a private file. Then set `BW_JUDGE_KEY_FILE` to that file. You can
join several files with `:` (on Windows, use `;`). Each key gets 3 test calls. Keys are never logged.

## Trial limits (read these)

- The trial lasts **30 days** and has **75 free call minutes**.
- You can only call, and get calls from, **verified** numbers. Up to **5**. Your sign-up number is one.
  A call in from a number you have not verified is refused by Twilio (error 21264).
- Calls only within **your own country**.
- The trial number is a **shared** Twilio number. To get your own number you must **upgrade** (that costs money).
- One call can last **10 minutes** at most, and ends after **10 hops** (each answer you give is about one hop).
  A long walk with lots of "repeat" may get cut off on a trial.
- Twilio's trial page also says calls made through its API on a trial may be limited to Twilio's own sample
  scripts. **We have not tested a real trial call yet.** If the call fails on a trial, the fix may be to
  upgrade your Twilio account. That is your choice and your money.

## Your data

**Your data stays on your computer.** You can download it or email yourself a copy (History page:
Download proof, or Email me my proof). The developer never gets it.

- **Twilio keeps a call log** in your own Twilio account: the two phone numbers, the time, how long the call
  lasted, and if it worked. Twilio keeps these logs for 13 months unless you delete them.
- **No sound is kept.** Bridge Warden never turns on call recording, so there is no audio.
- **When you set up your own copy, your calls go through your own Twilio account.** We, the makers of
  Bridge Warden, never see your call data. Nothing about your calls is sent to us.
  The call log lives only in **your own** Twilio account, under your control. It also helps you watch your
  own call use and costs in the Twilio Console.
- **What Bridge Warden keeps is on your own computer and accounts:**
  - Your computer: a signed history line like "call placed", with no phone numbers, tokens, or account ids.
  - Your Cloudflare Worker: no storage at all. If Twilio sends a bad request, it logs one line with field
    names only (no numbers, no words said) in your own Cloudflare account.
  - If you set your own xAI key on the Worker, the words you say on the call (up to 200 letters) go to xAI
    to understand your answer. Leave the key out and nothing goes to xAI.
- **Delete your call logs** any time. On your computer, run:
  `python -m bridge_warden forget-calls`
  (add `--dry-run` to only count them first). It deletes only finished calls between your Twilio number and
  your phone, plus any recordings on them, using Twilio's own delete. You can also delete them in the Twilio
  Console under the call logs.
  If Twilio says "not found" when deleting (we saw this on a free trial), use the Console instead.
- **This is not "zero retention".** Twilio has no switch to keep nothing for voice calls. After you delete,
  Twilio says copies can stay in its backups for up to 30 days, and some fields have a short minimum time
  before they can be removed. See Twilio's pages:
  [delete a call](https://www.twilio.com/docs/voice/api/call-resource#delete-a-call-resource),
  [call log retention](https://www.twilio.com/docs/voice/api/call-resource#call-resource-retention),
  [personal data](https://www.twilio.com/docs/glossary/what-is-personally-identifiable-information-pii).

## What we never do

- We never ask for your Twilio password or token. They stay on your computer and in your own Cloudflare.
- The call never gives a phone number. To call PayPal, **use the number on paypal.com**.
- The call cannot move money. Bridge Warden only holds risky payments until you say yes in the app.

## Dev/Test mode

While it is on, every page shows sample data only, marked "SAMPLE DATA (TEST MODE)". Your real money, history
and settings are hidden and unchanged until you turn it off.

## Status dots

The dot art is MIT licensed (see `LICENSE` in each dot folder). The code is Apache 2.0. The logo and music are
all rights reserved.

## No phone call? Free alerts

You always get the **in-app alert**: a red banner, a browser pop-up (if you allow it), and "Recent alerts" in
Settings > Alerts. Nothing to set up.

Free email (optional, off until you set all of these on your computer):

- `BW_SMTP_HOST`, `BW_SMTP_PORT` (587, or 465)
- `BW_SMTP_USER`, `BW_SMTP_PASSWORD`. For Gmail, use an **app password** (Google Account > Security >
  2-Step Verification > App passwords), never your real password.
- `BW_ALERT_EMAIL_FROM`, `BW_ALERT_EMAIL_TO`

The order is: a call if voice is set up, otherwise an email if email is set up, and the in-app alert always. They
run side by side, so if one breaks the others still go. The email says only "open Bridge Warden": no amounts, no
names, no links.

## Missed call? Call again

If you don't pick up (no answer, busy, failed, or voicemail), Bridge Warden sends the in-app alert and the email
right away, then calls again **15 minutes** later and again **15 minutes** after that (3 calls in all, over 30
minutes). Every missed call sends the email and the in-app alert again. It stops as soon as you answer or open the
alert in the app.

- **All 3 missed?** About 30 minutes in, it stops calling and sends **one** last message by email (if set up)
  and in the app: "We couldn't reach you by phone. Something in your PayPal needs attention. Check PayPal now."
  No money details, no links.
- **The light then stays red** until you respond yourself: "Got it, I've seen the blocked ones" on the home
  page, or your choice on the Held card. No timer and no later check turns it green. If something is still
  open after you respond, it steps down to yellow (paused) until you fix it.
- Change it in **Settings > Alerts > "Missed call? Call again"**: 1 to 120 minutes each, up to 3 retries, or `off`.
  It is saved in `policy.json` as `call_retry_minutes`.
- **Each retry is a paid Twilio call.**
- To know whether you answered, Twilio has to tell us. Set `BW_CALL_STATUS_URL=https://<your hosted app>/call-status`.
  Bridge Warden checks Twilio's signature on every report. Without it, Bridge Warden asks Twilio itself (a free
  read), and after 5 minutes with no answer it counts the call as missed.
- Voicemail detection (`BW_CALL_DETECT_MACHINE=on`) costs extra on Twilio, so it is off.
- The retry list is saved in `alert_retries.json` next to your audit log. It survives a restart and never calls
  twice for the same retry.
- Judges and test calls never retry.

## Watch your PayPal account (acctwatch)

Bridge Warden can also notice money that moves **outside** it (someone logged into your PayPal). PayPal tells us
by webhook. The light goes red and you get the call at once.

1. Run `python -m bridge_warden.acctwatch serve`. It listens on this computer only (127.0.0.1:8766).
2. Give it an HTTPS address with your own tunnel, for example `cloudflared tunnel --url http://127.0.0.1:8766`.
3. In your PayPal **sandbox** app, add a webhook to `https://<tunnel>/paypal/webhook` and set
   `BW_PAYPAL_WEBHOOK_ID` to its id.

Every webhook is checked with PayPal (verify-webhook-signature). Anything not verified, too old (over 5 minutes),
or already seen is refused. Each event is handled once. Dev mode never contacts PayPal.

The only thing it can do by itself is cancel an **unclaimed** payout (the money comes back to you). This is off
until you set `BW_ACCTWATCH_AUTOCANCEL=on`. For everything else, the call tells you what to do: open paypal.com
yourself, check Activity, and change your password.

A backup poller (`BW_ACCTWATCH_POLL=on`) reads PayPal Transaction Search. It is off by default and needs the
Transaction Search permission on your app. **PayPal can take up to about 3 hours to show new transactions there**,
so it is a backup, not the alarm.

Timings (webhook received, verified, checked, call sent) are saved in `acctwatch_latency.jsonl`.


## Lawful use

Do not use Bridge Warden to break the law or to harm anyone. Use it honestly. It is here to help protect your own money.

- It treats every user with the same respect.
- The AI stays calm, patient and kind, even when you are stressed or angry. It never stops protecting you.
- You are in charge of your own money and choices. Bridge Warden advises and protects. It never takes control
  away from you or acts against your wishes, except the safety holds you set up.
- Every AI request starts with a fixed rule that says the same thing. Payment data and what people type or say
  can never change it.
- The AI uses only facts from your PayPal data. It never makes up names, amounts, dates or events. If it
  is unsure, it says so.

**AI notice:** Bridge Warden is an AI and can make mistakes. It works from your PayPal data and is built to catch most problems, but it doesn't replace your own eyes. Check your PayPal activity yourself from time to time.

After every alert call (real, test or judge) and after every Bridge Warden money action, Bridge Warden
re-reads your PayPal state and compares it with its own log. It does not listen to or record your calls.
It looks for an action that did not land, an action that landed twice, or a state that does not match
the log. If something needs attention, the light turns yellow (paused), automatic actions wait (your own
approvals still work), you see a plain note in the app, and you get an email if email is set up. It clears
when you clear it in Settings or a later check comes back clean. A red light stays red until you respond;
if the problem is not fixed yet, it then steps down to yellow (see "Red, then yellow" below).
Dev mode has a button to simulate this (marked TEST; PayPal is not called).

## Update 2026-10-27: Red, then yellow (pause while you fix)

- **Green:** everything is working.
- **Yellow:** a state check found something, or Bridge Warden is paused while you fix a problem.
- **Red:** something bad happened. It stays red until you respond, even after a restart.
- **Off** also shows red. **Paused** shows yellow (see "Paused is yellow, Off is red" below).
- When you respond to a red ("Got it, I've seen the blocked ones" or "Got it, pause until I decide") but it is
  not fixed yet (a held payment still waits, or a state check is still open), the light steps **down to yellow**.
  Bridge Warden stays paused: new payments wait for you, so nothing piles up while you fix it.
- When it is all fixed, the light goes **green**. If your answer fixes everything, it goes straight to green.
- Every color change adds a line to **History** with the time, for example
  "Bridge Warden paused operations: light set to yellow while you fix it." and
  "Bridge Warden resumed operations: light set to green."
- A new problem while yellow turns the light red again. Dev mode Simulate buttons still work and are not logged.

## Update 2026-10-27: Paused is yellow, Off is red

- **Paused** (by you): the light is **yellow**. No money moves until you resume. Payments refused only because
  you paused do not turn it red.
- **Off**: the light is **red**. Nothing is checked, so nothing is guarded. Turn it back on to go green.
- An alert you have not answered yet still shows **red**, even while paused, until you respond. Then the
  red-then-yellow rules apply. "Keep everything blocked" counts as your answer: it pauses, and the light goes yellow.
- A missed-call final notice stays red until you clear it, even when Off.
- Email on every missed call stays the same.
- History gets a timed line for each change, for example "Bridge Warden paused by you: light set to yellow.",
  "Bridge Warden turned off: light set to red." and "Bridge Warden turned on: light set to green."

## Update 2026-10-27 (v6): the BW AG Grid agent (optional)

The History page sorts your spending (bills, subscriptions, gas, food, other), finds duplicate or unused
subscriptions, and flags money spikes. That part needs **no keys and no sign-up**. It is read-only and can
only raise the light, never turn it green or move money.

**Want the AI chats?** Set your own xAI key. It stays on your computer and is never logged:

    export XAI_API_KEY=...

Each answer shows the real tokens and cost xAI reports. xAI does not report credit left, so it says
"limit not available from provider".

**Want the AG Studio dashboard + chat panel? (optional, commercial software by AG Grid)**
1. Fetch it (needs Node/npm, downloads once, hash-checked): `bash scripts/fetch_ag_studio.sh`
2. Without a key it runs in **trial mode with a watermark**. To get a trial key, go to
   https://www.ag-grid.com/studio/license-pricing/?tab=trial and fill in: First Name, Last Name, work Email,
   Company (the marketing tick is optional), then the captcha. (AG's own console note also says you can email
   info@ag-grid.com for a trial key.) The page says the trial is 45 days; the EULA text says 30 days. Plan for 30.
3. Put the key in your environment: `export BW_AG_STUDIO_LICENSE_KEY=...` and restart Bridge Warden.
4. Open History. The panel "Ask the BW AG Grid agent" loads in its own frame. Its tools are read-only.

Read AG Grid's terms first: https://www.ag-grid.com/eula/AG-Grid-Enterprise-License-Latest.html.
Every outside service and library we use is listed in `NOTICE` and in README "Built with / third-party".

## Optional: real xAI on a hosted judge demo (Oct 27, 2026)

Set these in the Render dashboard (Environment). They are never in the repo, and never printed or logged.

- `XAI_API_KEY` (secret): your xAI key. Blank = no AI, sample answers only.
- `XAI_ZDR_CONFIRMED=1`: only after you turned on Zero Data Retention for your xAI team. Every reply is
  still checked for the ZDR header.
- `BW_JUDGE_KEY` or `BW_JUDGE_KEY_FILE` (secret): judge keys. Each judge logs in with their own key.
- `BW_JUDGE_XAI_CAP` (default 1000): xAI messages per judge key. At the cap: the sample answer and
  "Judge AI limit reached, showing sample answer". Nothing more is sent.
- `BW_CALL_MAX_SECONDS` (default 1800): every real call hangs up after this many seconds (Twilio TimeLimit).
- `BW_AG_STUDIO_LICENSE_KEY` (secret, optional): the build then fetches AG Studio with
  scripts/fetch_ag_studio.sh. The key is never echoed. Not set = no AG Studio panel.

The count is saved in the data folder (`audit/judge_xai.json`). Render's free plan has no disk, so the
count starts again from 0 when the service restarts, sleeps (after 15 minutes idle) or redeploys. A paid
Render disk keeps it. Either way, also set a spending limit (or prepaid credits only) on your xAI team.
That is the hard backstop. Requests by the owner (login key) and background checks are not judge-counted.
