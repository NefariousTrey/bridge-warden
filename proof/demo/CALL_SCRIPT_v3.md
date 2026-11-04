# Fraud drill test call: script v3

Version 3, 2026-10-26. Same as v2, plus: **press OR say** each choice, and a new **option 4 ("other")**.
(v1 is kept, unchanged, in `CALL_SCRIPT.md`. v2 is kept, unchanged, in `CALL_SCRIPT_v2.md`.)
The words below are the exact words in the code: `bridge_warden/notify.py` and `call-worker/src/index.js`.

It is a **TEST**. No real payment. Nothing goes to PayPal unless Trey sends the report himself.
No voiceover for the fraud part: the real call is filmed and recorded, and the call audio is the sound.
The call never says a person is on the line. It is Bridge Warden talking, every time.

Target: **under 30 seconds** for options 1-3.

---

## 1. The call says (about 20 seconds)

> **This is Bridge Warden. Fraud was detected on your PayPal account. Nothing was sent.**
>
> **We recommend you check your recent activity and lock your account.**
>
> **Press or say 1 for help securing your account.**
> **Press or say 2 to report this activity to PayPal.**
> **Press or say 3 if this was you.**
> **Press 4 or say other.**

## 2. Trey presses a key OR says it (about 2 seconds)

What counts (keypad first, then words):

| Choice | Keypad | Words that work |
|---|---|---|
| 1 help securing | 1 | "one", "help", "help me", "secure", "lock" |
| 2 report | 2 | "two", "report" |
| 3 this was you | 3 | "three", "me", "it was me", "that was me" |
| 4 other | 4 | "four", "other", "something else" |

If the words are unclear, and xAI is set up, xAI may pick 1-4 (it can only pick a number). With no xAI,
plain word matching is used. Two different choices in one answer ("help, report") = asked again.

For the film, press **1** (it shows the most). Then take 2: **say "report"**. Extra takes: 3 and 4.

## 3. The call answers (about 6 seconds)

**1 (help securing):**

> **Okay. The steps are on your screen now.**
> **First, open PayPal yourself, not from a link, and change your password.**

**2 (report):**

> **Okay. Your report is ready in the app.**
> **Check it, then send it to PayPal yourself.**

**3 (this was you):**

> **Okay. Thanks for checking.**
> **The payment stays on hold until you approve it in the app.**

**4 (other):**

> **Okay. In a few words, tell me what you need.**

Then Trey says what he needs (one short answer, speech only):
- If it is clearly 1, 2 or 3 (for example "I want to report it"), the call gives that answer above.
- With xAI set up: Bridge Warden answers in 1-2 short sentences (advice only), then:
  **"To hear the menu again, stay on the line."** and the menu plays once more.
- With no xAI, or nothing heard:
  > **I can help you secure your account, report this activity, or check if this was you. Here is the menu again.**

  and the menu plays once more.
- An answer that says a person, agent or human will help is thrown away. The call never says that.

**Not heard / not clear (first time):**

> **Sorry, I did not get that. Here is the menu again.** (menu plays once more)

**Not heard / not clear (second time):**

> **No problem. Everything stays on hold. You can choose in the app.**

## 4. Test calls always end with (about 3 seconds)

> **This was a test. Nothing happened to your money.**

(Real calls skip this line.) Then the call hangs up.

## Time check (estimate at about 2.6 words a second; time it on the real call)

| Part | Seconds |
|---|---|
| Call opens + menu | 20 |
| Key press or word | 2 |
| Answer (longest = 1) | 6 |
| "This was a test" | 3 |
| **Total (1-3)** | **about 31** |
| Option 4 adds | about 10-15 |

About 31 seconds is a little over the 30 second goal. If it must be under 30, film option 1 by keypad and
cut the ring to one ring.

---

## Shot notes

1. **App, normal screen.** Green light. Caption: "Fraud drill. TEST. No real payment."
2. **Light turns red.** The status light goes red (Trey's red dot), marked TEST.
3. **Push alert shows.** Hold 2 seconds so it can be read.
4. **Phone rings.** Phone on the desk, screen up, in frame. Let it ring 2 times.
5. **Call plays.** Pick up, speaker on. Record the call audio. Caption the words on screen.
6. **Choice.** Take 1: thumb presses **1** on the keypad, close up. Take 2: Trey **says "report"**, caption
   "Said: report". This shows both ways work.
7. **Screen after the choice.** Cut back to the app: the "secure your account" steps (1), the ready-made
   PayPal report (2), or the payment on hold waiting for a green yes (3).
8. **Option 4 (extra take).** Say "other", then a short question like "what should I do now?". Caption the
   bot's answer. Make sure the caption says it is Bridge Warden answering.
9. **History.** Show the new lines marked **TEST**.
10. **End card.** Logo + "From days to minutes."

Captions only. No voiceover for this part. The call audio is the only sound in it.

---

## Notes (honest list)

- **Press-or-say needs a public https address.** Twilio sends the key or the words back to that address.
  Plan: the owner's own free Cloudflare Worker on workers.dev (`call-worker/`). It is **built but not
  deployed**; no secrets are set. With no Worker address (`BW_CALL_URL` not set), the call only speaks
  and you pick in the app.
- The Worker refuses any request that is not signed by Twilio (it checks `X-Twilio-Signature` with your own
  Twilio auth token).
- Bridge Warden **cannot lock PayPal or send the report for you**. The call only guides.
- The call says **"This is Bridge Warden"** first, so it never sounds like PayPal calling.
- Use **your own** Twilio and **your own** phone. Turn on the **experimental** call switch, then
  **Test my alert** in Settings. The call comes 30 seconds to 5 minutes later. Keep the camera rolling.
