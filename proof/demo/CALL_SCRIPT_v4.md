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
  **Test my alert** in Settings. The app says "Test started." The call comes with no warning,
  within 20 minutes. Keep the camera rolling.

---

# v4 additions (2026-10-26)

Copy of v3 above, plus what changed in v4. Where v3 and v4 differ, **v4 wins**.
The words below are printed from the real code (`bridge_warden/notify.py`), so they match the call.
The phone call, the Worker (`call-worker/`) and the browser demo (`/hear`) all use the same words and the
same steps, from one file: `bridge_warden/paypal_steps.json`. Tests keep all three the same.

## 1. Test calls

In a **test** call, any choice or anything said gets:

> This was just a test. No action is needed.
> If this were real, here is what you would do:

Then the caller is walked through PayPal's steps for that situation (below). The end is always:

> This was a test. Nothing happened to your money.

## 2. The guided walk (test and real)

One step at a time. After each step:

> Press 1 or say done when finished, press 2 or say repeat, press 3 or say skip.

- 1 / done / finished / ok / yes = done, next step.
- 2 / repeat / again = say the step again (up to 2 times, then move on).
- 3 / skip / later = skip, next step.
- Not understood: "Sorry, I did not get that." and the step again. Silence after the last try: "Let's move on."

At the end it sums up:

> Here is what you did. Done: (the steps you finished). Skipped: (the steps you skipped).

Real calls end with: "Bridge Warden keeps anything risky on hold until you decide in the app."

## 3. Never call a number from a call

The call never gives a phone number. When a step is about calling PayPal, it says **"use the number on
paypal.com"**. Nobody should call a number that was spoken in a call or written in a message.

## 4. What PayPal says to do, per situation (fetched 2026-10-26)

Only what PayPal's own public pages say. If a page does not say it, it is not here. Each step cites its page.

### A payment you did not make (`unauthorized`)

| # | The call says | Source |
|---|---|---|
| 1 | Open PayPal yourself. Type paypal.com or use the PayPal app. Do not use a link. | <https://www.paypal.com/us/security/protect-your-account> |
| 2 | Check your recent activity. Make sure it was not a family member or an automatic payment, like a subscription. | <https://www.paypal.com/us/cshelp/article/how-do-i-report-an-unauthorized-transaction-or-account-activity-help136> |
| 3 | Change your password and your security questions. | <https://www.paypal.com/us/cshelp/article/how-do-i-report-potential-fraud-spoof-or-unauthorized-transactions-to-paypal-help165> |
| 4 | Turn on 2-step verification. | <https://www.paypal.com/us/security/protect-your-account> |
| 5 | Go to the Resolution Center. Choose Report a problem, pick the payment, then choose I want to report unauthorized activity. | <https://www.paypal.com/us/cshelp/article/how-do-i-report-an-unauthorized-transaction-or-account-activity-help136> |
| 6 | Do it now. PayPal's User Agreement says to tell PayPal at once. If you wait more than 60 days after the statement that shows it, you may not get back money lost after that. | <https://www.paypal.com/us/legalhub/paypal/useragreement-full> |
| 7 | PayPal says it will email you within 10 days. If you need to call PayPal, use the number on paypal.com. Never use a number from a message or a call. | <https://www.paypal.com/us/cshelp/article/how-do-i-report-an-unauthorized-transaction-or-account-activity-help136> |

### A login you do not know (`takeover`)

| # | The call says | Source |
|---|---|---|
| 1 | Open PayPal yourself. Type paypal.com or use the PayPal app. Do not use a link. | <https://www.paypal.com/us/security/protect-your-account> |
| 2 | Change your password right away. | <https://www.paypal.com/us/security/protect-your-account> |
| 3 | Update your security questions. | <https://www.paypal.com/us/cshelp/article/how-do-i-report-potential-fraud-spoof-or-unauthorized-transactions-to-paypal-help165> |
| 4 | Go to Settings, then Security, then Manage your logins. Remove any device you do not know. | <https://www.paypal.com/us/cshelp/article/what-is-multi-factor-authentication-and-a-remembered-device-help1156> |
| 5 | Turn on 2-step verification. Never share the code. PayPal will never ask you for it. | <https://www.paypal.com/us/security/protect-your-account> |
| 6 | Check your recent activity. If you see a payment you did not make, report it in the Resolution Center. | <https://www.paypal.com/us/cshelp/article/how-do-i-report-an-unauthorized-transaction-or-account-activity-help136> |
| 7 | If you need to call PayPal, use the number on paypal.com. Never use a number from a message or a call. | <https://www.paypal.com/us/cshelp/article/what-are-common-scams-and-how-do-i-spot-them-help201> |

### A fake PayPal email, text or call (`phishing`)

| # | The call says | Source |
|---|---|---|
| 1 | Do not click links, open attachments, or call any number in the message. | <https://www.paypal.com/us/security/report-suspicious-messages> |
| 2 | Forward the whole email to phishing at paypal dot com. Then delete it. | <https://www.paypal.com/us/security/report-suspicious-messages> |
| 3 | For a text, forward it to phishing at paypal dot com, block the sender, then delete it. | <https://www.paypal.com/us/security/report-suspicious-messages> |
| 4 | If you clicked a link, open PayPal yourself, check your payments, and change your password. | <https://www.paypal.com/us/cshelp/article/how-do-i-remove-a-limitation-from-my-account-help535> |
| 5 | If you need to call PayPal, use the number on paypal.com. Never use a number from a message or a call. | <https://www.paypal.com/us/cshelp/article/what-are-common-scams-and-how-do-i-spot-them-help201> |

### A risky buy (`scam_buy`)

| # | The call says | Source |
|---|---|---|
| 1 | Do not pay an invoice or money request for something you did not order. Do not call a number in its note. Report it by logging in to PayPal. | <https://www.paypal.com/us/cshelp/article/what-are-common-scams-and-how-do-i-spot-them-help201> |
| 2 | When you buy from someone you do not know, pay with Goods and Services, not Friends and Family. A seller who pushes Friends and Family is a red flag. | <https://www.paypal.com/us/security/learn-about-scams> |
| 3 | If something went wrong, contact the seller first. | <https://www.paypal.com/us/legalhub/paypal/buyer-protection> |
| 4 | Then go to the Resolution Center, choose Report a problem, pick the payment, and pick the reason. | <https://www.paypal.com/us/cshelp/article/how-do-i-open-a-dispute-with-a-seller-help160> |
| 5 | Watch the time. Item not received: open it within 180 days of paying. Not as described: within 30 days of delivery, or 180 days of paying, whichever is sooner. | <https://www.paypal.com/us/legalhub/paypal/buyer-protection> |
| 6 | If you need to call PayPal, use the number on paypal.com. Never use a number from a message or a call. | <https://www.paypal.com/us/cshelp/article/what-are-common-scams-and-how-do-i-spot-them-help201> |

### A risky sale or a chargeback (`risky_sell`)

| # | The call says | Source |
|---|---|---|
| 1 | A real buyer won't overpay you. If a buyer overpays and asks you to send back the difference, do not send it. Think about canceling the order. | <https://www.paypal.com/us/cshelp/article/what-are-common-scams-and-how-do-i-spot-them-help201> |
| 2 | Do not accept a shipping label from the buyer. Ship only to the address on the Transaction Details page. | <https://www.paypal.com/us/cshelp/article/what-are-common-scams-and-how-do-i-spot-them-help201> |
| 3 | Keep proof that you shipped it and that it was delivered. | <https://www.paypal.com/us/legalhub/paypal/seller-protection> |
| 4 | If you get a chargeback, go to the Resolution Center, choose the case, and click Respond Now. Give tracking or proof of a refund. | <https://www.paypal.com/us/cshelp/article/what-is-a-chargeback-and-why-did-i-get-one-help607> |
| 5 | Answer PayPal's requests for papers on time. | <https://www.paypal.com/us/legalhub/paypal/seller-protection> |
| 6 | If you need to call PayPal, use the number on paypal.com. Never use a number from a message or a call. | <https://www.paypal.com/us/cshelp/article/what-are-common-scams-and-how-do-i-spot-them-help201> |

### A limited account (`limited`)

| # | The call says | Source |
|---|---|---|
| 1 | Open PayPal yourself. Type paypal.com or use the PayPal app. Do not use a link in the email. | <https://www.paypal.com/us/security/protect-your-account> |
| 2 | Go to the Resolution Center, or tap the bell at the top of your Dashboard, to see why. | <https://www.paypal.com/us/cshelp/article/why-is-my-paypal-account-limited-help534> |
| 3 | Finish every step PayPal asks for. If it asks for proof of identity, like a driver's license, upload it in your Notifications Center. | <https://www.paypal.com/us/cshelp/article/why-is-my-paypal-account-limited-help534> |
| 4 | If an email says you are limited but nothing shows in the Resolution Center, it may be fake. Forward it to phishing at paypal dot com and delete it. | <https://www.paypal.com/us/cshelp/article/why-is-my-paypal-account-limited-help534> |
| 5 | Then wait for PayPal to contact you. PayPal says that in most cases its phone team can't remove a limitation. | <https://www.paypal.com/us/cshelp/article/why-is-my-paypal-account-limited-help534> |
| 6 | If you need to call PayPal, use the number on paypal.com. Never use a number from a message or a call. | <https://www.paypal.com/us/cshelp/article/what-are-common-scams-and-how-do-i-spot-them-help201> |

## 5. Sample calls (printed from the code)

### Test call, press 1, then done on every step

Caller presses 1, then says or presses done each time.

```
BW: This is a Bridge Warden demo call. Nothing happens to your money.
BW: This is Bridge Warden. Fraud was detected on your PayPal account. Nothing was sent.
BW: We recommend you check your recent activity and lock your account.
BW: Press or say 1 for help securing your account. Press or say 2 to report this activity to PayPal. Press or say 3 if this was you. Press 4 or say other.
BW: You chose 1, help securing your account.
BW: This was just a test. No action is needed.
BW: If this were real, here is what you would do:
BW: This is about: a payment you did not make.
BW: I will take you through it one step at a time.
BW: Step 1 of 7.
BW: Open PayPal yourself. Type paypal.com or use the PayPal app. Do not use a link.
BW: Press 1 or say done when finished, press 2 or say repeat, press 3 or say skip.
BW: Step 2 of 7.
BW: Check your recent activity. Make sure it was not a family member or an automatic payment, like a subscription.
BW: Press 1 or say done when finished, press 2 or say repeat, press 3 or say skip.
BW: Step 3 of 7.
BW: Change your password and your security questions.
BW: Press 1 or say done when finished, press 2 or say repeat, press 3 or say skip.
BW: Step 4 of 7.
BW: Turn on 2-step verification.
BW: Press 1 or say done when finished, press 2 or say repeat, press 3 or say skip.
BW: Step 5 of 7.
BW: Go to the Resolution Center. Choose Report a problem, pick the payment, then choose I want to report unauthorized activity.
BW: Press 1 or say done when finished, press 2 or say repeat, press 3 or say skip.
BW: Step 6 of 7.
BW: Do it now. PayPal's User Agreement says to tell PayPal at once. If you wait more than 60 days after the statement that shows it, you may not get back money lost after that.
BW: Press 1 or say done when finished, press 2 or say repeat, press 3 or say skip.
BW: Step 7 of 7.
BW: PayPal says it will email you within 10 days. If you need to call PayPal, use the number on paypal.com. Never use a number from a message or a call.
BW: Press 1 or say done when finished, press 2 or say repeat, press 3 or say skip.
BW: Here is what you did.
BW: Done: opened PayPal yourself, checked recent activity, changed password and security questions, turned on 2-step verification, reported it in the Resolution Center, know the 60 day limit, know what happens next.
BW: This was a test. Nothing happened to your money.
```

### Real call, say "report", repeat once, skip once

Real alert about a fake message. Caller says report, asks to repeat step 1, then skips step 2.

```
BW: This is Bridge Warden. Fraud was detected on your PayPal account. Nothing was sent.
BW: We recommend you check your recent activity and lock your account.
BW: Press or say 1 for help securing your account. Press or say 2 to report this activity to PayPal. Press or say 3 if this was you. Press 4 or say other.
BW: Okay. Your report is ready in the app.
BW: Okay. I will walk you through what PayPal says to do.
BW: This is about: a fake paypal email, text or call.
BW: I will take you through it one step at a time.
BW: Step 1 of 5.
BW: Do not click links, open attachments, or call any number in the message.
BW: Press 1 or say done when finished, press 2 or say repeat, press 3 or say skip.
BW: Step 1 of 5.
BW: Do not click links, open attachments, or call any number in the message.
BW: Press 1 or say done when finished, press 2 or say repeat, press 3 or say skip.
BW: Step 2 of 5.
BW: Forward the whole email to phishing at paypal dot com. Then delete it.
BW: Press 1 or say done when finished, press 2 or say repeat, press 3 or say skip.
BW: Skipped.
BW: Step 3 of 5.
BW: For a text, forward it to phishing at paypal dot com, block the sender, then delete it.
BW: Press 1 or say done when finished, press 2 or say repeat, press 3 or say skip.
BW: Step 4 of 5.
BW: If you clicked a link, open PayPal yourself, check your payments, and change your password.
BW: Press 1 or say done when finished, press 2 or say repeat, press 3 or say skip.
BW: Step 5 of 5.
BW: If you need to call PayPal, use the number on paypal.com. Never use a number from a message or a call.
BW: Press 1 or say done when finished, press 2 or say repeat, press 3 or say skip.
BW: Here is what you did.
BW: Done: did not click or call, forwarded and blocked the text, checked payments and password, know to use the number on paypal.com.
BW: Skipped: forwarded and deleted the email.
BW: Bridge Warden keeps anything risky on hold until you decide in the app.
```

## 6. Someone calls in (`/inbound`)

If the Twilio number is set to send "A call comes in" to the Worker's `/inbound`, a caller hears the same
call as a **demo**: it says it is a demo first, it is always a test, and it never reads the caller's number.

## 7. Twilio trial limits that touch the walk

Twilio's trial page (read 2026-10-26, <https://www.twilio.com/docs/usage/trials/try-out-voice>) says a trial
call ends after **10 hops** (each answer the caller gives is one hop), **10 minutes**, or when the **75 free
minutes** run out. A 7-step walk with no repeats is about 8 hops, so it fits. Many repeats may cut the call
short on a trial. Not tested on a real call yet.

## 8. Try it with no phone

Open `/hear` in Bridge Warden. It plays the same call in your browser (your browser's voice). Buttons for
1-4 and done/repeat/skip, a box to type what you would say, and an optional mic. **Demo. Nothing happens to
your money.** No number needed, nothing is sent anywhere. The mic is off unless you tick the box (some
browsers send mic audio to the browser maker to turn it into words).
