# Fraud drill test call: script

This is the first call script (v1, Oct 26, 2026), kept as a record. The words the call uses today are in
`bridge_warden/paypal_steps.json` and `bridge_warden/notify.py`, and the newest script is [CALL_SCRIPT_v4.md](CALL_SCRIPT_v4.md).

For Trey's real test call, to film for the demo.
It is a **TEST**. No real payment. Nothing goes to PayPal.

Whole call: **under 40 seconds**.

---

## Before you film

- Use **your own** Twilio and **your own** phone.
- Turn on the **experimental** call switch.
- Tap **Test my alert** in Settings.
- The call comes in **30 seconds to 5 minutes** later.
- Keep the camera rolling.

---

## 1. The AI says (about 12 seconds)

> **Bridge Warden here.**
>
> **This is a drill.**
>
> **A $250 payment to a new payee was blocked.**
>
> **Was this you?**
>
> **Say: keep blocked,**
> **show me how to lock PayPal,**
> **or I'm fine.**

---

## 2. Trey picks ONE (about 2 seconds)

**Choice A:**

> **Keep blocked.**

**Choice B:**

> **Show me how to lock PayPal.**

**Choice C:**

> **I'm fine.**

---

## 3. The AI answers (5 to 18 seconds)

**If A (keep blocked):**

> **Okay.**
> **Everything stays blocked**
> **until you say so in the app.**

**If B (lock PayPal):**

> **Open PayPal yourself.**
> **Do not use links from texts.**
> **Change your password.**
> **Turn on two-step login.**
> **The steps are in your app too.**

**If C (I'm fine):**

> **Okay.**
> **The payment stays blocked.**
> **Nothing was sent.**

---

## 4. The AI always ends with (about 4 seconds)

> **This was a test.**
>
> **Nothing happened to your money.**

---

## Time check

| Part | Seconds |
|---|---|
| AI opens | 12 |
| Trey answers | 2 |
| AI answers (longest = B) | 18 |
| "This was a test" | 4 |
| **Total (longest)** | **36** |

---

## Shot list for the demo

1. **App, Settings.** Tap **Test my alert**. Caption: "Fraud drill. TEST. No real payment."
2. **Light goes red.** The status bar turns red, marked TEST. Desktop alert pops up.
3. **Phone on the desk.** Wait. Then it **rings**. Caption: "Unannounced call, like the real thing."
4. **Pick up. Speaker on.** The AI script plays (part 1). Caption the words on screen.
5. **Trey answers.** Use **B: "Show me how to lock PayPal."** (it shows the most).
6. **AI reads the lock steps,** then **"This was a test."**
7. **Back to the app.** Show the **lock steps** page.
8. **Tap Report to PayPal.** Show the ready-made summary. Caption: "You send it yourself."
9. **History.** Show the lines marked **TEST**.
10. **End card:** "From days to minutes."

Captions only. No voiceover. No music.
The call audio is the only sound, if you keep it.

---

## Notes

- The real call feature is **experimental** and **waits for your test**.
- Phone choices (speaking or pressing 1, 2, 3) need a public HTTPS callback. Without one, the call reads the choices and **you pick in the app**.
- Today the app's call says "Hello, this is Bridge Warden..." and lists "Press 1, 2 or 3". If you want it to match this script word for word, say so. It is a small change.
