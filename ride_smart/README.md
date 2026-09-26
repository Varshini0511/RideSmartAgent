# RideSmartAgent

Compare cab/auto prices across **Uber, Ola, Rapido & Namma Yatri** and book the cheapest — automatically.

## How it works

```
You: "Koramangala" → "Whitefield"

RideSmartAgent:
  1. Opens all 4 apps (via browser automation)
  2. Enters your route in each
  3. Extracts cab & auto prices
  4. Compares all options

Decision logic:
  • Cheapest cab ≤ ₹380 → Book cheapest cab
  • All cabs > ₹380     → Switch to auto, book cheapest auto
  • Booking doesn't confirm in 2 min → Try next cheapest option
  • Repeats until booked or all options exhausted
```

## Setup

```bash
# 1. Install dependencies
cd ride_smart
pip install -e .

# 2. Install Playwright browsers
playwright install chromium

# 3. Copy env and configure
cp .env.example .env

# 4. First-time login: run with visible browser to log into each app
python -m ride_smart.main
```

### First-time setup (important!)

On first run, the agent opens a **visible browser**. You need to manually log into each ride app once:
- Uber (m.uber.com)
- Ola (book.olacabs.com)
- Rapido (rapido.bike)
- Namma Yatri (nammayatri.in)

Sessions are saved to `browser_sessions/` and reused on subsequent runs.

## Usage

### CLI — one-shot
```bash
python -m ride_smart.main --pickup "Koramangala" --drop "Whitefield"
```

### CLI — interactive mode
```bash
python -m ride_smart.main
```

### CLI — auto-book
```bash
python -m ride_smart.main -p "Koramangala" -d "Whitefield" --book
```

### CLI — custom threshold
```bash
python -m ride_smart.main -p "Koramangala" -d "Whitefield" --threshold 350
```

### Streamlit UI
```bash
pip install -e ".[ui]"
streamlit run ride_smart/streamlit_app.py
```

## Architecture

```
ride_smart/
├── config.py          # Settings (thresholds, timeouts)
├── models.py          # RideQuote, RideType, Location
├── geocoder.py        # Address → lat/lng
├── providers/
│   ├── base.py        # Abstract RideProvider
│   ├── uber.py        # Uber web automation
│   ├── ola.py         # Ola web automation
│   ├── rapido.py      # Rapido web automation
│   └── namma_yatri.py # Namma Yatri web automation
├── comparator.py      # Price comparison + cab/auto threshold
├── orchestrator.py    # Fetch → Compare → Book with fallback
├── main.py            # CLI entry point
└── streamlit_app.py   # Streamlit visual UI
```

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `CAB_PRICE_THRESHOLD` | 380 | Switch to auto if cheapest cab exceeds this (₹) |
| `BOOKING_TIMEOUT` | 120 | Seconds before trying next option |
| `QUOTE_TIMEOUT` | 30 | Seconds to wait for each provider's quotes |
| `MAX_BOOKING_ATTEMPTS` | 4 | Max options to try before giving up |
| `HEADLESS_BROWSER` | false | Run browsers invisibly |
| `DEFAULT_CITY` | Bengaluru | City for geocoding |

## Important notes

- **Web scraping is inherently fragile.** When ride apps update their UI, the scrapers may need adjustment. Each provider is a separate module so fixes are isolated.
- **Login sessions expire.** If price fetching stops working, delete the `browser_sessions/` folder and re-login.
- **Auto-booking involves real money.** Test with `--book` only when you're ready to actually ride. Without `--book`, the agent only compares prices.
- **Surge pricing changes fast.** Prices shown are a snapshot — they may change by the time you book.
