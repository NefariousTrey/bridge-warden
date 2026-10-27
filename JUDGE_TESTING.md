# Judge Guide

This is the one judge guide for Bridge Warden. (`proof/JUDGE_TESTING.md` only points here.)

## Good to know

1. Your judge key gives you 3 real test calls, free to you.
2. All AI is real xAI: the AI check, help chats, the AG chat panel, summaries and call replies. Free to you on our key (up to 1,000 messages per judge in all).
3. PayPal is sandbox only. No real money moves.
4. Judge mode runs the whole flow without a phone.
5. To run it yourself: it is open source. Bring your own Twilio and xAI keys.

The same guide is a page in the app: open **/judges** (top menu: **Judges**). No sign-in needed to read it.

Bridge Warden watches the payments your AI agent makes with PayPal.
It lets safe ones through, stops risky ones, and tells you right away.

**Tested in sandbox with sample data to verify it works as intended.**

Free for judges through Dec 15, 2026.

Judge login: in the Devpost testing notes.

Judge mode runs the whole flow without a phone. The voice call is optional (your own Twilio, since it's open source).

## Try it in 5 steps

1. **Sign in.** Open the demo link. Sign in with the judge login.
   Judge login: in the Devpost testing notes.

2. **Look at the light.** Home shows one big light at the top.
   Green means all is fine.

3. **Press "Test my alert".** Go to Settings. Find Alerts.
   Type the name you want the call to use. Then press **Test my alert**.

4. **Try a risky payment.** Send a risky sandbox payment. For example, the gift-card scam.
   Bridge Warden blocks it. The light turns red.

5. **Clear it, one step at a time.**
   Press **"Got it, I've seen the blocked ones"**. The light turns yellow.
   Then press **"It's fixed, confirm"**. The light turns green.

## What the lights mean

- **Green:** all is fine. Safe payments go through.
- **Yellow:** paused. Bridge Warden waits for you.
- **Red:** something needs you. Nothing risky is sent.

**Red never goes straight to green.**
Red goes to yellow first. Only you can turn it green.

## Where AG Studio shows up

Open **History**. The big table of money moves is AG Grid.
Below it is the BW AG Grid agent. It is an AG Studio dashboard and chat.
Ask it about the flagged payments. It reads only the sandbox sample data.

## Video and code

- Demo video: [YOUTUBE_LINK]
- Code: [REPO_LINK]

## Easier to read?

The Judge Guide page has **Light** and **Dark** buttons. So does every page, in Settings.

---

## More ways to try the call

These still work. They are the older notes, kept as they were.

### For judges: how to try the call

You do **not** need to give anyone your phone number. Pick any of these.

## 1. Watch the video

The v8 demo video (2:58, captions, YouTube link in the submission) shows the app with sample data in the
PayPal sandbox. Use way 2 to hear the call yourself.

## 2. Hear the call in your browser (no phone)

1. Run judge mode: `python -m bridge_warden judge`, then open `http://127.0.0.1:8765/`.
2. Click **Hear the call** (or go to `/hear`).
3. Pick a situation and press **Start the call**. Your browser reads the call out loud.
4. Use the buttons (1, 2, 3, 4, done, repeat, skip), or type what you would say.
   The microphone is off unless you tick the box.

It says **"Demo. Nothing happens to your money."** No number is needed. Nothing is sent anywhere.
It uses the same words and the same steps as the real phone call (tests check this).

## 3. Call in (optional, only if the owner has turned it on)

The owner may share a Twilio number that answers with the same demo call. On a free Twilio trial, only
phone numbers the owner has verified can call in, so this may not be open to everyone. The first two ways
show the same call.

## 4. Get a real test call (judges with a judge key)

If you are a judge, the **judge key** will be given in the submission notes. It is not in the code.

1. Open **Settings** and find **Test my alert**.
2. Paste the judge key into **Judge key**, then press **Test my alert**.
3. The test call comes shortly. Bridge Warden says hello, and the call ends with "This was a test".

Nothing happens to anyone's money. You can run one test every 20 minutes, the same as everyone else.
Without a judge key, Test my alert still works; the call just comes at a different time.
Optional: type a name in **What should the call call you?** and the test call says "Hello <name>, this is Bridge Warden." (blank = "Hello, this is Bridge Warden."); the name is used for that one call only and never logged.

**Please, no more than 3 real test calls per judge.** Judge test calls run on our own Twilio account.
(People who set up Bridge Warden themselves pay for their own calls.) Thank you!
The app also stops after 3 real test calls per judge key.

## Dev mode (practice switches)

Open **Settings**, then **Dev mode**, then press **Turn on Dev mode**. A bold red **TEST MODE** shows at the
top of every page. Use **Simulate pause** (yellow), **Simulate alert** (red), **Back to normal** (green), and
**Add TEST buy** / **Add TEST sell** (they show in Guard History marked TEST). Nothing reaches PayPal and
calls are practice only. While Dev mode is on, every page shows sample data only, marked
"SAMPLE DATA (TEST MODE)". Turn Dev mode off to go back to normal.

## Your data

- Ways 1 and 2 send nothing anywhere. No phone number is used.
- Ways 3 and 4 (judge test calls) go through **the maker's demo Twilio account**. So only those judge test
  calls show up in the maker's Twilio call log: who was called, when, and how long. **No sound is kept**:
  call recording is never turned on.
- Bridge Warden itself keeps no phone numbers. Its own log says only "call placed", and it stays on the
  computer running the app.
- When people set up Bridge Warden themselves, the call log lives only in **their own** Twilio account,
  under their control. We, the makers, get none of it. It also helps them watch their own call use and
  costs in the Twilio Console.
- The maker can delete these Twilio call logs with `python -m bridge_warden forget-calls`.
  Twilio has no "keep nothing" switch for calls, and says deleted data can stay in its backups for up to
  30 days. So this is "deleted on request", not "zero retention".

---

Made by @Nefarious_Trey,  
with Grok.


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
when you clear it in Settings or a later check comes back clean. A red light is never turned yellow.
Dev mode has a button to simulate this (marked TEST; PayPal is not called).

## The AI on the hosted judge demo

- Log in with your own judge key (same box as the login key). Your AI use is counted for your key only.
- The AI check, the help chats, the AG chat panel, summaries and call replies use real xAI on our key.
  It is free to you, up to 1,000 xAI messages per judge.
- After that, you see the sample answer with the note "Judge AI limit reached, showing sample answer".
  Nothing more is sent to xAI, so it never costs more.
- Your judge key is never stored. Only a salted fingerprint of it is counted.
- Judge mode (no login, on your own computer) has no xAI key. It always shows the sample answers.
- Every real alert or test call hangs up by itself after 30 minutes at most.
