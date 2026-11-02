# Judge Guide

This is the one judge guide for Bridge Warden. (`proof/JUDGE_TESTING.md` only points here.)

## Good to know

1. First load can take about a minute. The free demo sleeps when nobody uses it.
2. All AI is real xAI: help chats, Ask AI about this, the AG chat panel and the money check summary. Free to you on our key (1,000 messages in all, shared by every judge).
3. No phone needed. No real phone calls. Hear the call plays the alert call in your browser.
4. PayPal is sandbox only. No real money moves.
5. All judges share one demo copy: Dev mode, TEST rows and alerts. Another judge may change or clear them. Please turn Dev mode off when you are done.
6. Want a real phone call? Press Deploy to Render below. Your own free copy, with your own Twilio.

More on these:

- The demo runs on Render's free plan. After a sleep, the first page may take about a minute. After that it is fast.
- Some screens for owners say "your own xAI key, billed to you". For a signed-in judge they say free, on our key.
- Its history is wiped when the service sleeps or restarts. That is normal.
- Dev mode, Pause and the light are shared by everyone on the demo. If another judge left Dev mode on, just use it.
  Call name, voice and retries are the owner's settings, so they are view-only for judges.

The same guide is a page in the app: open **/judges** (top menu: **Judges**). No sign-in needed to read it.

Bridge Warden watches the payments your AI agent makes with PayPal.
It lets safe ones through, stops risky ones, and tells you right away.

**Tested in sandbox with sample data to verify it works as intended.**

Free for judges through Dec 15, 2026. The judge key stops working on Dec 16, 2026.

Judge login: in the Devpost testing notes.

Judge mode runs the whole flow without a phone. The voice call is optional (your own Twilio, since it's open source).
On this demo, Test my alert opens Hear the call too. It never rings a phone.

## Try it in 6 steps

1. **Sign in.** Open the demo link. Give it up to a minute the first time.
   Paste your judge key in the **Login key** box and press **Log in**.
   Judge login: in the Devpost testing notes.

2. **Look at the light.** Home shows one big light at the top.
   Green means all is fine. A fresh copy has no payments yet, so it is green.

3. **Turn on Dev mode.** Go to **Settings**, then **Dev mode**, then press **Turn on Dev mode**.
   A red **TEST MODE** shows on every page. Now every page shows sample data, marked TEST.
   Nothing reaches PayPal. No phone rings.

4. **Try a risky payment.** In Settings, under Dev mode, press **Add TEST sell**.
   This is the gift-card scam: a "buyer" asks for a $480 refund by gift card, urgent and secret.
   Bridge Warden blocks it. Open **Home** or **History** to see it blocked, with the reasons.
   You can also press **Add TEST buy** (a $60 "brand-new PlayStation 5"). It is blocked too.
   TEST payments never change the real light. Step 5 shows the light.

5. **Turn the light red, then clear it one step at a time.**
   In Settings, under Dev mode, press **Raise TEST red**. The light turns red.
   Press **"I've seen this"**. The light turns yellow.
   Then press **"It's fixed"**. The light turns green.
   While the light is red, there is no "It's fixed" button. Red can't skip yellow.

6. **Hear the call.** Open **Hear the call** (`/hear`). Pick what happened and press **Start the call**.
   Your browser reads the call out loud. Use the buttons, or type what you would say.

When you are done, go to **Settings** and press **Turn off Dev mode**.

On your own computer (judge mode), use the scenario buttons on Home instead of Dev mode.

## Your own copy, in one click (Deploy to Render)

[Deploy to Render](https://render.com/deploy?repo=https://github.com/NefariousTrey/bridge-warden)

This makes a full Bridge Warden on **your own** free Render account, from `render.yaml` in this repo.

1. Press Deploy to Render. Sign in to Render (a free account is fine).
2. Render asks for a few boxes. All are optional. Type none in any box you want to skip.
3. Your phone and your own Twilio account details and Twilio number give you a real phone call. No Twilio: Test my alert plays the call in your browser.
4. Your own xAI key is optional. No key: the local safety rules still check every payment.
5. Your login key is made for you. Find it in Render: open your service, then Environment.
6. Your copy opens in Dev mode with sample data marked TEST. Nothing reaches PayPal.
7. For a real phone call, turn Dev mode off in Settings, then press Test my alert.

Render's free plan costs nothing. Real calls are billed by Twilio to your own Twilio account. A Twilio trial is free but can only call numbers you verified.

What Render asks (all optional; type `none` to skip a box):

| Box | What to put | If you skip it |
|---|---|---|
| `BW_OWNER_PHONE` | your phone, like `+15551234567` | no phone call |
| `TWILIO_ACCOUNT_SID` | your Twilio Account SID (starts with AC) | Test my alert plays the call in your browser |
| `TWILIO_AUTH_TOKEN` | your Twilio Auth Token | same |
| `TWILIO_FROM_NUMBER` | your Twilio phone number | same |
| `XAI_API_KEY` | your own xAI key | local safety rules only |
| `PAYPAL_CLIENT_ID`, `PAYPAL_SANDBOX_SECRET`, `BW_PAYPAL_WEBHOOK_ID` | your PayPal sandbox app and webhook | `/paypal-webhook` is off |

Made for you: `BW_LOGIN_KEY` (your login key: paste it on the login page) and `BW_CALL_LINK_KEY`. Set for you: `BW_DEMO_DATA=on`
(opens in Dev mode with sample data), `BW_FREE_PLAN=on`, `BW_DATA_DIR=bw-data`.

Why your own Twilio: the shared judge demo never rings a phone. Real calls need a Twilio account, and each person
uses their own, so calls and call logs stay in their own account. The button only works while the GitHub repo is
public. On the free plan the copy sleeps after 15 minutes idle and forgets its history when it does.

## What the lights mean

- **Green:** all is fine. Safe payments go through.
- **Yellow:** paused. Bridge Warden waits for you.
- **Red:** something needs you. Nothing risky is sent.

**Red never goes straight to green.**
Red goes to yellow first. Only you can turn it green.

## BW Light

BW Light is Bridge Warden's status light. It is one dot: red, yellow or green.
It shows BW's verdict on the account, and why.
You see it as a small card on every page, and as a widget in AG Studio.

It has two buttons:
- **"I've seen this"** steps red down to yellow.
- **"It's fixed"** turns yellow green.

**Red can never jump straight to green.** If the light is red, "It's fixed" is refused.
Only a real person's click works. The AI chat can't press them.
BW Light can't pay or move money.

## Where AG Studio shows up

Turn on Dev mode first (step 3). A fresh copy has no money moves, so History is empty without it.

Open **History**. The big table of money moves is AG Grid.
Below it is the BW AG Grid agent. It is an AG Studio dashboard and chat.
Press **Run the BW AG Grid agent now** to see what it finds in the sample data.
Ask the chat about spending or subscriptions. It reads only redacted sample data.

With no money data at all, the chat says so and asks you to turn on Dev mode. It does not ask xAI to guess.

On the hosted demo, the chats and "Ask AI about this" use real xAI on our key, also while Dev mode is on.
They only see redacted sample data. If the AI is off, the answer says "the AI is off right now".

## Video and code

- Demo video: [YOUTUBE_LINK]
- Code: https://github.com/NefariousTrey/bridge-warden

## Easier to read?

The Judge Guide page has **Light** and **Dark** buttons. So does every page, in Settings.

---

## About the alert call

You do **not** need to give anyone your phone number. There are no real phone calls for judges.

### 1. Watch the video

The demo video (YouTube link in the submission) shows the app with sample data in the PayPal sandbox.

### 2. Hear the call in your browser (no phone)

1. Open **Hear the call** (top of the Settings page, or go to `/hear`).
2. Pick a situation and press **Start the call**. Your browser reads the call out loud.
3. Use the buttons (1, 2, 3, 4, done, repeat, skip), or type what you would say.
   The microphone is off unless you tick the box.

It says **"Demo. Nothing happens to your money."** No number is needed. Nothing is sent anywhere.
It uses the same words and the same steps as the real phone call (tests check this).

You can also run it on your own computer: `python -m bridge_warden judge`, then open `http://127.0.0.1:8765/hear`.

### About "Test my alert"

**Test my alert** (in Settings) rings the owner's own phone, through their own Twilio.
On the hosted demo, a signed-in judge never gets a phone call. Pressing **Test my alert** opens
**Hear the call** instead, with the note "Judge demo: no phone call is placed." No Twilio, no text, no cost.

## Dev mode (practice switches)

Open **Settings**, then **Dev mode**, then press **Turn on Dev mode**. A bold red **TEST MODE** shows at the
top of every page. Use **Simulate pause** (yellow), **Simulate alert** (red), **Back to normal** (green),
**Raise TEST yellow** / **Raise TEST red** (the BW Light steps), and
**Add TEST buy** / **Add TEST sell** (they show in Guard History marked TEST). Nothing reaches PayPal and
no phone rings. While Dev mode is on, every page shows sample data only, marked
"SAMPLE DATA (TEST MODE)". Turn Dev mode off to go back to normal.

Simulate alert turns the big light red. To go back, press **Back to normal**.
To try the "I've seen this" and "It's fixed" buttons, use **Raise TEST red** instead.

## Your data

- Hear the call sends nothing anywhere. No phone number is used.
- Bridge Warden itself keeps no phone numbers.
- When people set up Bridge Warden themselves, their call log lives only in **their own** Twilio account,
  under their control. We, the makers, get none of it. **No sound is kept**: call recording is never turned on.
- Twilio has no "keep nothing" switch for calls, and says deleted data can stay in its backups for up to
  30 days. The owner can delete their Twilio call logs with `python -m bridge_warden forget-calls`.
  So this is "deleted on request", not "zero retention".

---

Made by @Nefarious_Trey,  
with Grok.


## Lawful use

Bridge Warden is for adults (18 and over). PayPal accounts also require 18+.

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

After every alert call (real or test) and after every Bridge Warden money action, Bridge Warden
re-reads your PayPal state and compares it with its own log. It does not listen to or record your calls.
It looks for an action that did not land, an action that landed twice, or a state that does not match
the log. If something needs attention, the light turns yellow (paused), automatic actions wait (your own
approvals still work), you see a plain note in the app, and you get an email if email is set up. It clears
when you clear it in Settings or a later check comes back clean. A red light is never turned yellow.
Dev mode has a button to simulate this (**Simulate check**, marked TEST; PayPal is not called).

## The AI on the hosted judge demo

- Log in with the judge key (same box as the login key). AI use is counted per key, and all judges share one key,
  so the cap is shared by every judge.
- The help chats, the AG chat panel and the money check summary use real xAI on our key.
  It is free to you, up to 1,000 xAI messages in all, shared by every judge (it resets when the service restarts).
- After that, you see the sample answer with the note "Judge AI limit reached, showing sample answer".
  Nothing more is sent to xAI, so it never costs more.
- Your judge key is never stored. Only a salted fingerprint of it is counted.
- Judge mode (no login, on your own computer) has no xAI key. It always shows the sample answers.
