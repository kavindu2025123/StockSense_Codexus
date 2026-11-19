import numpy as np
import pandas as pd
from datetime import datetime, timedelta

np.random.seed(42)

BINS_CONFIG = [
    {
        "device_id": "BIN-01",
        "sector": "Pharmacy",
        "sku": "Amoxicillin 500mg Blister Boxes",
        "rfid_tag": "E200-3412-0194-88A1",
        "unit_weight_g": 45,
        "max_capacity_g": 5000,
        "reorder_point_g": 1200,
        "base_hourly_units": 0.9,  # ~21 units/day
    },
    {
        "device_id": "BIN-02",
        "sector": "Garment Factory",
        "sku": "Heavy-Duty Brass Zippers (Spools)",
        "rfid_tag": "E200-7821-9904-11B2",
        "unit_weight_g": 250,
        "max_capacity_g": 15000,
        "reorder_point_g": 3500,
        "base_hourly_units": 0.7,  # ~17 spools/day (weekdays higher)
    },
    {
        "device_id": "BIN-03",
        "sector": "Supermarket",
        "sku": "Ceylon Organic Tea Packs (200g)",
        "rfid_tag": "E200-5501-4432-77C1",
        "unit_weight_g": 200,
        "max_capacity_g": 10000,
        "reorder_point_g": 2000,
        "base_hourly_units": 0.85,  # ~20 packs/day (weekends higher)
    },
]


def generate_dataset(days: int = 30) -> pd.DataFrame:
    end_time = datetime.now().replace(minute=0, second=0, microsecond=0)
    start_time = end_time - timedelta(days=days)
    timestamps = pd.date_range(start=start_time, end=end_time, freq="1h")[:-1]

    records = []

    for cfg in BINS_CONFIG:
        current_weight = cfg["max_capacity_g"] * 0.88
        ema_weight = current_weight

        for idx, ts in enumerate(timestamps):
            hour = ts.hour
            is_weekend = ts.weekday() >= 5

            # Business hours activity curve (active 08:00 - 20:00, quiet overnight)
            if 8 <= hour <= 20:
                activity_mult = 1.4
                if cfg["sector"] == "Garment Factory" and is_weekend:
                    activity_mult = 0.2
                elif cfg["sector"] == "Supermarket" and is_weekend:
                    activity_mult = 1.8
            else:
                activity_mult = 0.05

            # Normal item removals (Poisson distribution)
            units_picked = np.random.poisson(cfg["base_hourly_units"] * activity_mult)
            delta_g = -(units_picked * cfg["unit_weight_g"])
            event_type = "PICKUP" if units_picked > 0 else "HEARTBEAT"
            is_injected_anomaly = 0

            # Inject realistic anomalies (unscheduled overnight drops / spillage)
            if cfg["device_id"] == "BIN-01" and idx == 410:  # 02:00 AM sudden drop
                delta_g = -15 * cfg["unit_weight_g"]  # -675g sudden drop
                event_type = "ANOMALY_DROP"
                is_injected_anomaly = 1
            elif cfg["device_id"] == "BIN-02" and idx == 555:  # Sudden 6-spool removal
                delta_g = -6 * cfg["unit_weight_g"]  # -1500g sudden drop
                event_type = "ANOMALY_DROP"
                is_injected_anomaly = 1
            elif cfg["device_id"] == "BIN-03" and idx == 650:  # Sudden 8-pack removal
                delta_g = -8 * cfg["unit_weight_g"]  # -1600g sudden drop
                event_type = "ANOMALY_DROP"
                is_injected_anomaly = 1

            current_weight = max(0.0, current_weight + delta_g)

            # Scheduled restock when stock falls near or below reorder point
            if current_weight <= cfg["reorder_point_g"] and 9 <= hour <= 16:
                restock_g = (cfg["max_capacity_g"] * 0.90) - current_weight
                restock_units = int(restock_g // cfg["unit_weight_g"])
                if restock_units > 0:
                    delta_g = restock_units * cfg["unit_weight_g"]
                    current_weight += delta_g
                    event_type = "RESTOCK"

            # Simulate HX711 raw noise (+/- 10g) and EMA filter (alpha = 0.2)
            raw_weight = max(0.0, round(current_weight + np.random.normal(0, 8), 1))
            ema_weight = round(0.2 * raw_weight + 0.8 * ema_weight, 1)

            records.append(
                {
                    "timestamp": ts,
                    "device_id": cfg["device_id"],
                    "sector": cfg["sector"],
                    "sku": cfg["sku"],
                    "rfid_tag": cfg["rfid_tag"],
                    "unit_weight_g": cfg["unit_weight_g"],
                    "reorder_point_g": cfg["reorder_point_g"],
                    "raw_weight_g": raw_weight,
                    "filtered_weight_g": ema_weight,
                    "delta_weight_g": round(delta_g, 1),
                    "event_type": event_type,
                    "injected_anomaly": is_injected_anomaly,
                }
            )

    df = pd.DataFrame(records)
    df.to_csv("stocksense_30d_telemetry.csv", index=False)
    print(f"Saved stocksense_30d_telemetry.csv ({len(df)} rows across 3 bins).")


if __name__ == "__main__":
    generate_dataset(days=30)