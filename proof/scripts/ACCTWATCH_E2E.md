# acctwatch e2e proof (prepared, NOT run)

Each step needs Trey's yes first. Sandbox only. Play money only.

1. Start the watcher on this computer: `BW_PAYPAL_WEBHOOK_ID=... .venv/bin/python -m bridge_warden.acctwatch serve`
   (listens on 127.0.0.1:8766 only).
2. Give it a public HTTPS address (free): `cloudflared tunnel --url http://127.0.0.1:8766`. **This makes a public
   endpoint. Needs Trey's yes.**
3. `register_sandbox_webhook.py --url https://<tunnel>/paypal/webhook --yes-trey-said-so` and save the webhook id.
4. `stranger_sandbox_payout.py --to <sandbox personal email> --yes-trey-said-so`. **May ring Trey's phone.**
5. `latency_report.py audit/acctwatch_latency.jsonl` for the real numbers.

PayPal's simulator events cannot be verified (PayPal says so), so step 4 uses a real sandbox payout.
