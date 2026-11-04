# Account-watch end-to-end proof, run on the owner's own computer (Oct 27, 2026)

Public copy of the run notes. Account IDs and local setup notes were removed; nothing else was changed.

**Result: WORKED.** One sandbox stranger payout -> PayPal webhook -> red -> **exactly one** phone call, answered.
Sandbox only (api-m.sandbox.paypal.com). Live PayPal never touched. 1.00 USD of play money to a made-up address.

- Where: the owner's own computer (Linux), a test copy of v4 with the one-alert-per-payout fix and call-id saving.
- Tunnel: cloudflared 2026.10.4 quick tunnel. A public probe reached the watcher (HTTP 400 for an unsigned probe, as designed).
- Run settings (copy only): voice on, retries off (`call_retry_minutes: []`), one-call-per-run guard, auto-cancel off, xAI off.
- Sandbox webhook (23 event types, deleted after the run) and one sandbox payout batch. IDs removed from this public copy.
- Twilio call: one call, its ID removed from this public copy.

## Timings (ET, Oct 27, 2026)
| Step | Time (ET) | Since payout API return |
|---|---|---|
| Payout sent | 1:33:35.097 AM | - |
| Payout API returned | 1:33:36.053 AM | 0 s |
| PayPal created batch PROCESSING event | 1:33:57.929 AM | 21.9 s |
| PayPal created item UNCLAIMED event | 1:34:07.371 AM | 31.3 s |
| First webhook arrived (PAYOUTS-ITEM.UNCLAIMED) | 1:34:13.974 AM | 37.9 s |
| Signature verified with PayPal | +628 ms | 38.5 s |
| Red decision | +629 ms (1:34:14.603 AM) | 38.6 s |
| Call request sent to Twilio | +659 ms (1:34:14.633 AM) | 38.6 s |
| Twilio call created | 1:34:15 AM | ~39 s |
| Twilio start_time (dialing / ringing) | 1:34:20 AM | **~44 s** (≈45 s from send) |
| Call ended (status completed, 52 s) | 1:35:12 AM | - |

Inside Bridge Warden: webhook in -> call request = **0.66 s**. Most of the end-to-end time is PayPal's sandbox
(~31 s to create the payout item event, then ~6.6 s to deliver it). Twilio's exact ring moment is not in its API
(Call Insights returned nothing); `start_time` is the closest stamp.

## One alert, one call
- 3 webhooks for the one payout: ITEM.UNCLAIMED (1:34:13.974), BATCH.SUCCESS (1:34:17.003), BATCH.PROCESSING (1:34:41.878; PayPal sent it at 1:34:01, delivered 40 s late).
- The first raised the red alert and the call. The other two were logged as `acctwatch_same_alert` (same payout batch): no new red item, no call.
- Twilio account shows exactly 1 call since 1:30 AM ET. The one-call guard was never needed.

## After-call check
- State check: `ok: true, problems: []` (light not yellow).
- Outside payout re-read at PayPal: batch `SUCCESS`, item `UNCLAIMED` ("outside payout re-checked at PayPal").
- Auto-cancel of the unclaimed item: skipped (off for this run).

## Email
- **No emails were sent**: no SMTP server was set up for this run (`email_ready: false`). Also, with voice on, the alert email only goes out after a missed call, and this call was answered.

## Cleanup (1:35:46 AM ET)
- Tunnel and watcher stopped. Deleted only the test webhook; the sandbox app was left with 0 webhooks.
- No repo files edited during the run.

## The call, as Trey reported it (user's report; no recording was made)
Trey's own account of the 1:34 AM ET sandbox call on Oct 27, 2026:
- The call told him about the payout.
- He said it was him (it was our own sandbox test).
- Bridge Warden replied OK, but kept the payout on hold until he approves it in the app.

What this shows: the talk-back works, and an answer on the phone can't clear a hold. Only the owner's own
approval in the app can.
