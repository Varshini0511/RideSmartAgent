# RideSmartAgent

AI-powered ride-hailing price comparison and booking agent for India. Compare prices across **Uber, Ola, Rapido & Namma Yatri** — book the cheapest ride with one click.

## Features

- **Live price comparison** — scrapes real-time quotes from Uber & Ola
- **Fare estimation** — distance-based pricing for Rapido & Namma Yatri
- **Race booking** — book across multiple providers simultaneously, first confirmed wins
- **AI price prediction** — learns your routes, predicts surge pricing
- **Anomaly detection** — flags unusual pricing with z-score analysis
- **Smart route suggestions** — suggests routes based on your travel patterns
- **LLM assistant** — natural language chat powered by Groq API
- **Preference learning** — adapts recommendations to your booking choices
- **ETA prediction** — predicts wait times from historical data

## Quick Start

```bash
# Clone
git clone https://github.com/YOUR_USERNAME/RideSmartAgent.git
cd RideSmartAgent

# Install
pip install -r requirements.txt
python -m playwright install chromium

# Set up API keys
cp .env.example .env
# Edit .env with your GROQ_API_KEY and GOOGLE_API_KEY

# Login to providers (one-time)
python -m ride_smart.login_setup uber
python -m ride_smart.login_setup ola

# Run
streamlit run ride_smart/streamlit_app.py --server.port 8502
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GROQ_API_KEY` | Optional | Groq API key for AI chat assistant |
| `GOOGLE_API_KEY` | Optional | Google Maps API for geocoding |

## AI Features

All AI features improve with usage — the more rides you compare, the better predictions get.

| Feature | How it works |
|---------|-------------|
| Price Prediction | Historical averages by route/provider/hour |
| Anomaly Detection | Z-score deviation from historical mean |
| Best Time to Book | Cheapest hour from hourly price patterns |
| Wait Recommendation | Current vs historical price comparison |
| Smart Routes | Time-of-day weighted route suggestions |
| Commute Detection | Auto-detects home-work patterns |
| Preference Learning | Tracks provider/price choices |

## Architecture

```
ride_smart/
├── providers/          # Uber, Ola, Rapido, Namma Yatri scrapers
├── ai/                 # AI/ML modules
│   ├── ride_history.py     # SQLite ride database
│   ├── llm_agent.py        # Groq LLM chat
│   ├── price_predictor.py  # Price forecasting
│   ├── anomaly_detector.py # Price anomaly detection
│   ├── smart_routes.py     # Route suggestions
│   ├── preference_learner.py # User preference learning
│   └── eta_predictor.py    # ETA prediction
├── orchestrator.py     # Booking flow + race booking
├── streamlit_app.py    # Web UI
├── comparator.py       # Price ranking engine
├── fare_estimator.py   # Distance-based fare calculation
└── models.py           # Data models
```

## Tech Stack

- **Frontend**: Streamlit + Folium maps
- **Scraping**: Playwright (browser automation)
- **AI/ML**: Groq API (LLM), SQLite (history), statistical models
- **Providers**: Uber, Ola (live scraping), Rapido, Namma Yatri (fare estimation)
