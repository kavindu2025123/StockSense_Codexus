import json
import pandas as pd
import numpy as np
from sklearn.ensemble import IsolationForest
from statsmodels.tsa.holtwinters import ExponentialSmoothing


def run_ai_pipeline(csv_path: str = "stocksense_30d_telemetry.csv"):
    df = pd.read_csv(csv_path, parse_dates=["timestamp"])
    df["hour"] = df["timestamp"].dt.hour
    df["day_of_week"] = df["timestamp"].dt.dayofweek

    forecast_summary = []
    detected_anomalies_all = []

    print("\n" + "=" * 72)
    print("STOCKSENSE AI ENGINE — ANOMALY DETECTION & STOCKOUT FORECASTING")
    print("=" * 72)

    for bin_id, group in df.groupby("device_id"):
        group = group.sort_values("timestamp").copy()
        sku = group["sku"].iloc[0]
        unit_g = group["unit_weight_g"].iloc[0]
        reorder_g = group["reorder_point_g"].iloc[0]
        current_weight_g = group["filtered_weight_g"].iloc[-1]

        # --------------------------------------------------------------------
        # 1. ANOMALY DETECTION (ISOLATION FOREST ON NEGATIVE WEIGHT DELTAS)
        # --------------------------------------------------------------------
        # Filter out scheduled positive restocks so model learns normal pickups
        non_restock = group[group["delta_weight_g"] <= 0].copy()
        features = non_restock[["delta_weight_g", "hour", "day_of_week"]]

        iso_forest = IsolationForest(
            n_estimators=100, contamination=0.008, random_state=42
        )
        non_restock["anomaly_pred"] = iso_forest.fit_predict(features)

        # Keep sharp drops (< -3 units) flagged as outliers (-1)
        flagged = non_restock[
            (non_restock["anomaly_pred"] == -1)
            & (non_restock["delta_weight_g"] <= -3 * unit_g)
        ]

        for _, row in flagged.iterrows():
            detected_anomalies_all.append(
                {
                    "timestamp": row["timestamp"].strftime("%Y-%m-%d %H:%M"),
                    "device_id": bin_id,
                    "delta_weight_g": float(row["delta_weight_g"]),
                    "units_missing": int(abs(row["delta_weight_g"]) // unit_g),
                    "severity": "CRITICAL",
                    "reason": "Sudden unscheduled weight drop (IsolationForest outlier)",
                }
            )

        # --------------------------------------------------------------------
        # 2. DAILY CONSUMPTION FORECASTING (HOLT'S LINEAR TREND SMOOTHING)
        # --------------------------------------------------------------------
        group["date"] = group["timestamp"].dt.date
        # Sum only negative deltas (actual consumption, excluding restocks)
        daily_consumption = (
            group[group["delta_weight_g"] < 0]
            .groupby("date")["delta_weight_g"]
            .sum()
            .abs()
            .reindex(sorted(group["date"].unique()), fill_value=0.0)
        )

        # Fit Holt's Exponential Smoothing on the last 21 days of daily usage
        train_series = daily_consumption.iloc[-21:].astype(float)
        model = ExponentialSmoothing(
            train_series, trend="add", seasonal=None, initialization_method="estimated"
        ).fit()

        forecast_7d = model.forecast(7).clip(lower=unit_g)
        predicted_daily_burn_g = float(forecast_7d.mean())
        predicted_daily_units = round(predicted_daily_burn_g / unit_g, 1)

        # Calculate days until stock hits reorder threshold and 0g stockout
        days_to_reorder = max(
            0.0, round((current_weight_g - reorder_g) / predicted_daily_burn_g, 1)
        )
        days_to_stockout = max(
            0.0, round(current_weight_g / predicted_daily_burn_g, 1)
        )

        stockout_date = (
            group["timestamp"].iloc[-1] + pd.Timedelta(days=days_to_stockout)
        ).strftime("%Y-%m-%d")

        bin_result = {
            "device_id": bin_id,
            "sku": sku,
            "current_weight_g": round(float(current_weight_g), 1),
            "current_units": int(round(current_weight_g / unit_g)),
            "reorder_point_g": int(reorder_g),
            "predicted_daily_burn_g": round(predicted_daily_burn_g, 1),
            "predicted_daily_units": predicted_daily_units,
            "days_to_reorder": days_to_reorder,
            "days_to_stockout": days_to_stockout,
            "predicted_stockout_date": stockout_date,
            "next_7d_forecast_g": [round(float(x), 1) for x in forecast_7d.tolist()],
        }
        forecast_summary.append(bin_result)

        print(f"\n[{bin_id}] {sku}")
        print(f"  Current Stock        : {bin_result['current_weight_g']} g ({bin_result['current_units']} units)")
        print(f"  Predicted Burn Rate  : {bin_result['predicted_daily_burn_g']} g/day (~{predicted_daily_units} units/day)")
        print(f"  Days to Reorder Pt   : {days_to_reorder} days (Threshold: {reorder_g} g)")
        print(f"  Est. Stockout Date   : {stockout_date} ({days_to_stockout} days remaining)")
        print(f"  Anomalies Detected   : {len(flagged)}")

    output_payload = {
        "model_metadata": {
            "forecasting_algorithm": "Holt Linear Exponential Smoothing (statsmodels)",
            "anomaly_algorithm": "Isolation Forest (scikit-learn)",
            "training_window_days": 30,
        },
        "forecasts": forecast_summary,
        "anomalies": detected_anomalies_all,
    }

    with open("ai_forecast_output.json", "w") as f:
        json.dump(output_payload, f, indent=2)

    print("\n" + "=" * 72)
    print(f"Total Anomalies Flagged: {len(detected_anomalies_all)}")
    for a in detected_anomalies_all:
        print(f"  -> {a['timestamp']} | {a['device_id']} | {a['delta_weight_g']}g (-{a['units_missing']} units)")
    print("Exported API-ready output to ai_forecast_output.json")
    print("=" * 72 + "\n")


if __name__ == "__main__":
    run_ai_pipeline()