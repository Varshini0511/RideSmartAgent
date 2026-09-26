"""AI modules for RideSmartAgent — prediction, learning, and NLP."""

from ride_smart.ai.ride_history import (
    init_db,
    save_comparison,
    save_booking,
    save_user_choice,
    get_all_history,
    get_frequent_routes,
    get_hourly_prices,
    get_price_stats,
    get_route_history,
    get_user_choices,
)
from ride_smart.ai.llm_agent import chat, get_recommendation, analyze_surge
from ride_smart.ai.price_predictor import (
    predict_price,
    best_time_to_book,
    surge_probability,
)
from ride_smart.ai.smart_routes import suggest_routes, detect_commute_pattern
from ride_smart.ai.anomaly_detector import detect_anomalies, is_surge_likely
from ride_smart.ai.preference_learner import (
    learn_preferences,
    personalized_ranking,
    should_wait_for_better_price,
)
from ride_smart.ai.eta_predictor import predict_eta, eta_reliability
