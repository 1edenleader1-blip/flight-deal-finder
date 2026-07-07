# Flight Deal Finder

Searches a route across the next 12 months (or however long you choose),
including mixing different airlines together (flying out on one, back on
another) when that's cheaper than any single ticket — then emails you a
weekly summary of the best options, with booking links where available.
Runs automatically on a free GitHub Actions schedule.

## How it works

- **Search**: uses the [Travelpayouts Data API](https://www.travelpayouts.com/),
  which serves cached real fare data (refreshed roughly every 48 hours to a
  week) from actual searches. For every month in your search window it runs:
  1. A round-trip calendar query — cheapest single-ticket price for each day
     of the month, for your chosen length of stay.
  2. Two one-way queries (outbound and inbound directions) — the cheapest
     one-way fares found that month, each with a direct booking link.
  
  It then pairs up the cheapest outbound + cheapest inbound one-ways
  (checking the gap between them fits your nights range) and compares that
  combined price against the round-trip price for similar dates. Whichever
  is cheaper wins — that's the "mix and match" logic. When it's the paired
  one-ways and they're on different airlines, the email flags it clearly as
  "2 separate bookings."
- **Rank**: sorts everything found by price and keeps the top few per route.
- **Email**: builds an HTML summary and sends it via Gmail SMTP.
- **Schedule**: a GitHub Actions workflow runs the whole thing every Monday
  at 06:00 UTC (edit the cron line in
  `.github/workflows/weekly-search.yml` to change the time — cron is
  always UTC).

## Two things worth understanding

**Not every result has a booking link.** The one-way ("2 separate
bookings") results come with direct Aviasales booking links. The
round-trip ("single ticket") results currently don't — for those, take the
price and dates shown and search them yourself on the airline's site or
Google Flights.

**"2 separate bookings" itineraries are two independent tickets.** When
mixing airlines is cheaper, you'd book the outbound and inbound
separately. If your first flight is delayed and you miss the "connection,"
neither airline is obligated to rebook you, unlike a single ticket. The
email always flags these so you can weigh the savings against that risk.

## One-time setup

### 1. Sign up for Travelpayouts (free)
1. Go to https://www.travelpayouts.com/ and register as a partner.
   During sign-up you may be asked about a website or platform — for
   personal use, it's fine to note that you don't have one yet or are
   using this for personal travel research.
2. Once logged in, find your API token in your account's **API** section
   (also listed at https://www.travelpayouts.com/programs/100/tools/api).
   Copy it — you'll need it below.

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
In your GitHub repo: **Settings → Secrets and variables → Actions → Secrets
tab → Repository secrets → New repository secret**. Add these three, each
as its own separate entry with just its own name and value (no extra text):

| Secret name              | Value                                    |
|---------------------------|-------------------------------------------|
| `TRAVELPAYOUTS_TOKEN`     | Your API token from step 1                 |
| `GMAIL_ADDRESS`           | The Gmail address you're sending from      |
| `GMAIL_APP_PASSWORD`      | The 16-character app password from step 2 |

### 5. Edit `config.yaml`
This is where you define **what** to search and **who** gets the email —
no code changes needed. Open `config.yaml` and edit:

- `email.from_address` — should match the Gmail account from step 2
- `email.recipients` — list of email addresses to send the summary to
- `searches` — one block per route you want tracked. Each has:
  - `origin` / `destination` — IATA airport codes (e.g. `AKL`, `NRT`)
  - `nights.min` / `nights.max` — trip length range to search across
  - optional overrides: `currency`, `results_per_search`, `search_window_days`

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
export TRAVELPAYOUTS_TOKEN="..."
export GMAIL_ADDRESS="..."
export GMAIL_APP_PASSWORD="..."
python main.py
```

## Adding or changing routes later
Just edit `searches:` in `config.yaml` and push — no other changes needed.
Add as many saved searches as you like; each gets its own section in the
weekly email.

## Notes & troubleshooting
- If a run's log shows requests failing for a specific route, that's
  printed clearly (`!! round-trip calendar request failed...` or
  `!! one-way GraphQL request failed...`) and that piece is just skipped
  rather than crashing the whole run — check the printed error text for
  details (e.g. an invalid IATA code or a token issue).
- Because this reads from a search cache rather than live inventory, very
  low-traffic routes may return fewer or no results. It works best on
  routes people actually search for regularly.
- Always double check prices before booking — fares change constantly.
