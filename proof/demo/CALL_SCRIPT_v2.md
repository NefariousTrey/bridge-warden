# Fraud drill test call: script v2

Version 2, 2026-10-26. Trey's choice: **no voiceover for the fraud part.** The real Twilio test call to
Trey's own phone is filmed and recorded, and the call audio is the sound.
(v1 is kept, unchanged, in `CALL_SCRIPT.md`.)

It is a **TEST**. No real payment. Nothing goes to PayPal unless Trey sends the report himself.

Target: **under 30 seconds** for the whole call. Short, calm, plain.

---

## 1. The call says (about 17 seconds, 45 words)

> **This is Bridge Warden.**
>
> **Fraud was detected on your PayPal account. Nothing was sent.**
>
> **We recommend you check your recent activity and lock your account.**
>
> **Press 1 for help securing your account.**
> **Press 2 to report this activity to PayPal.**
> **Press 3 if this was you.**

## 2. Trey presses one key (about 2 seconds)

For the film, press **1** (it shows the most). Film 2 and 3 as extra takes if there is time.

## 3. The call answers (about 6 seconds)

**Press 1 (help securing):**

> **Okay. The steps are on your screen now.**
> **First, open PayPal yourself, not from a link, and change your password.**

**Press 2 (report):**

> **Okay. Your report is ready in the app.**
> **Check it, then send it to PayPal yourself.**

**Press 3 (this was you):**

> **Okay. Thanks for checking.**
> **The payment stays on hold until you approve it in the app.**

**No key pressed:**

> **No problem. Everything stays on hold. You can choose in the app.**

## 4. Test calls always end with (about 3 seconds)

> **This was a test. Nothing happened to your money.**

(Real calls skip this line.)

## Time check (estimate at about 2.6 words a second; time it on the real call)

| Part | Seconds |
|---|---|
| Call opens | 17 |
| Key press | 2 |
| Answer (longest = 1) | 6 |
| "This was a test" | 3 |
| **Total** | **about 28** |

---

## Shot notes

1. **App, normal screen.** Green light. Caption: "Fraud drill. TEST. No real payment."
2. **Light turns red.** The status light goes red (Trey's red dot), marked TEST.
3. **Push alert shows.** The desktop / push alert pops up on screen. Hold 2 seconds so it can be read.
4. **Phone rings.** Phone on the desk, screen up, in frame. Let it ring 2 times.
5. **Call plays.** Pick up, speaker on. Record the call audio. Caption the words on screen.
6. **Keypress.** Show the thumb pressing **1** on the keypad, close up.
7. **Screen updates after the keypress.** Cut back to the app: the "secure your account" steps open
   (for 2: the ready-made PayPal report; for 3: the payment stays on hold, waiting for a green yes).
8. **History.** Show the new lines marked **TEST**.
9. **End card.** Logo + "From days to minutes."

Captions only. No voiceover for this part. The call audio is the only sound in it.

---

## Notes (honest list)

- **Keypress needs public HTTPS (not set up yet).** Twilio can only send the pressed key back to an `https://`
  address it can reach from the internet. Bridge Warden only listens on this computer today, so right now the
  call reads the choices and **you pick in the app**. Steps 6 and 7 need that public address first
  (for example a tunnel or a hosted judge build). Setting one up is Trey's call; nothing is set up, signed up
  for or paid for. When it is added, the callback must check Twilio's request signature so nobody else can
  fake a keypress.
- **The app's words are not changed yet.** Today the code (`bridge_warden/notify.py`) says
  "Hello, this is Bridge Warden..." and the menu is: 1 = keep blocked, 2 = how to lock PayPal, 3 = I'm fine.
  This v2 script is: 1 = help securing, 2 = report to PayPal, 3 = this was you. Matching the code to this
  script is a small change, waiting on Trey's OK.
- Bridge Warden **cannot lock PayPal or send the report for you**. The call only guides; Trey does the
  locking and the sending himself.
- The call says **"This is Bridge Warden"** first, so it never sounds like PayPal calling.
- Use **your own** Twilio and **your own** phone. Turn on the **experimental** call switch, then
  **Test my alert** in Settings. The call comes 30 seconds to 5 minutes later. Keep the camera rolling.
