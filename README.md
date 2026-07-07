# Flight Deal Finder

Searches a route across the next 12 months (or however long you choose),
including mixing different airlines together (flying out on one, back on
another) when that's cheaper than any single ticket — then emails you a
weekly summary of the best options. Runs automatically on a free GitHub
Actions schedule.

## How it works

- **Search**: uses the [Duffel API](https://duffel.com/), which searches
  real airline inventory. For each sampled date combination, the tool runs:
  1. A normal round-trip search (one ticket, possibly with a connection)
  2. A one-way search for the outbound leg
  3. A one-way search for the inbound leg
  
  It then compares the round-trip price against the cost of combining the
  cheapest outbound + cheapest inbound (even from two unrelated airlines),
  and keeps whichever is cheaper. That's the "mix and match" logic.
- **Rank**: sorts everything found by price and keeps the top few per route.
- **Email**: builds an HTML summary and sends it via Gmail SMTP.
- **Schedule**: a GitHub Actions workflow runs the whole thing every Monday
  at 06:00 UTC (edit the cron line in
  `.github/workflows/weekly-search.yml` to change the time — cron is
  always UTC).

## A key thing to understand before you start

**There is no "click to book" link in the email.** Duffel is built for
companies building their own checkout flow, not a consumer travel site —
so the email gives you the exact price, dates, and airline(s), and you then
search those same dates yourself on the airline's website or Google Flights
to actually buy the ticket. That's a couple of extra minutes per deal.

**"2 separate bookings" itineraries are two independent tickets.** When
mixing airlines is cheaper, you'll book the outbound and inbound
separately — on two different airlines' websites. If your first flight is
delayed and you miss the "connection," neither airline is obligated to
rebook you, unlike a single ticket. The email always flags these clearly so
you can weigh the savings against that risk (a longer layover buffer or
travel insurance can help).

## One-time setup

### 1. Sign up for Duffel (free, ~1 minute)
1. Go to https://app.duffel.com/ and create an account.
2. In the dashboard, go to **Settings → API keys** and copy your **test**
   access token to try things out first, then switch to a **live** access
   token once you're happy (see note on live vs test below).
3. In **Settings**, set your account's **billing currency** to whatever
   currency you want prices shown in (e.g. NZD, USD) — Duffel prices all
   offers in that currency automatically, so you don't set currency
   per-search.

**Test vs live mode**: your test token returns fake sandbox flights (not
real prices) — fine for confirming the tool runs end-to-end, but not useful
for real deal-hunting. For real fares, use a live token. Duffel's search
pricing is usage-based (a small per-search fee only kicks in once your
search volume gets high relative to bookings) — for one person tracking a
handful of routes weekly, this tool's usage should stay effectively free or
very close to it; check current pricing at https://duffel.com/pricing
since this may change.

### 2. Create a Gmail app password
Gmail SMTP won't accept your normal password from scripts.
1. Turn on 2-Step Verification on the Gmail account you'll send from:
   https://myaccount.google.com/signinoptions/two-step-verification
2. Generate an app password: https://myaccount.google.com/apppasswords
3. Save the 16-character password it gives you — you'll need it below.

### 3. Push this project to a GitHub repo
```bash
cd flight-deal-finder
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

### 4. Add your secrets to the repo
In your GitHub repo: **Settings → Secrets and variables → Actions → New
repository secret**. Add these three:

| Secret name          | Value                                      |
|-----------------------|---------------------------------------------|
| `DUFFEL_API_KEY`      | Your Duffel access token from step 1         |
| `GMAIL_ADDRESS`       | The Gmail address you're sending from        |
| `GMAIL_APP_PASSWORD`  | The 16-character app password from step 2   |

### 5. Edit `config.yaml`
This is where you define **what** to search and **who** gets the email —
no code changes needed. Open `config.yaml` and edit:

- `email.from_address` — should match the Gmail account from step 2
- `email.recipients` — list of email addresses to send the summary to
- `searches` — one block per route you want tracked. Each has:
  - `origin` / `destination` — IATA airport codes (e.g. `AKL`, `NRT`)
  - `nights.min` / `nights.max` — trip length range to search across (the
    tool tests both ends of this range on each sampled date)
  - optional overrides: `max_stopovers`, `results_per_search`,
    `search_window_days`, `date_sample_interval_days`

Commit and push your changes:
```bash
git add config.yaml
git commit -m "Configure my routes"
git push
```

### 6. Test it
Go to your repo's **Actions** tab → **Weekly Flight Deal Search** →
**Run workflow** to trigger it immediately instead of waiting for Monday.
Check the run logs, and check your inbox.

## Running locally instead (optional)
```bash
pip install -r requirements.txt
export DUFFEL_API_KEY="..."
export GMAIL_ADDRESS="..."
export GMAIL_APP_PASSWORD="..."
python main.py
```

## Adding or changing routes later
Just edit `searches:` in `config.yaml` and push — no other changes needed.
Add as many saved searches as you like; each gets its own section in the
weekly email.

## Notes & tuning
- `date_sample_interval_days` (default 14) controls how many dates get
  checked across your `search_window_days` — a smaller number finds more
  precise cheap dates but makes many more API calls and takes longer to
  run. 14 days is a reasonable balance for a 12-month window.
- If you hit rate limits, lower `max_parallel_requests` in `config.yaml`.
- Always double check prices before booking — fares change constantly, and
  offers can shift by the time you go to book.
