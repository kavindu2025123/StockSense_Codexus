from fastapi import FastAPI
from pathlib import Path
from fastapi.middleware.cors import CORSMiddleware
import paho.mqtt.client as mqtt
import json
import uuid
import asyncpg
import asyncio

app = FastAPI(title="StockSense Telemetry Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_URI = "postgresql://admin:secretpassword@timescaledb:5432/stocksense_db"
MQTT_BROKER = "broker.hivemq.com"
MQTT_TOPIC = "stocksense/kavindu_2026_node01/telemetry"
BASE_DIR = Path(__file__).resolve().parent

# Global database connection pool & main event loop reference
db_pool = None
main_loop = None
mqtt_client = None


async def init_db():
    global db_pool
    await asyncio.sleep(5)  # Give TimescaleDB time to boot up

    db_pool = await asyncpg.create_pool(DB_URI)

    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS telemetry (
                time TIMESTAMPTZ NOT NULL,
                device_id VARCHAR(64) NOT NULL,
                raw_weight DOUBLE PRECISION,
                filtered_weight DOUBLE PRECISION,
                rfid_tag VARCHAR(32),
                status VARCHAR(16)
            );
        """)
        try:
            await conn.execute("SELECT create_hypertable('telemetry', 'time', if_not_exists => TRUE);")
        except Exception as e:
            print(f"Hypertable Notice: {e}")


async def save_telemetry(payload):
    if not db_pool:
        return
    try:
        raw_w = payload.get("raw_weight_g") if payload.get("raw_weight_g") is not None else payload.get("raw_weight")
        filt_w = payload.get("filtered_wt_g") if payload.get("filtered_wt_g") is not None else payload.get("filtered_weight")

        async with db_pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO telemetry(time, device_id, raw_weight, filtered_weight, rfid_tag, status)
                   VALUES (NOW(), $1, $2, $3, $4, $5)""",
                payload.get("device_id"),
                raw_w,
                filt_w,
                payload.get("rfid_tag"),
                payload.get("status")
            )
            print(f"[DB SUCCESS] Saved telemetry from {payload.get('device_id')} ({filt_w}g)")
    except Exception as e:
        print(f"[DB ERROR] Insert failed: {e}")


def on_connect(client, userdata, flags, rc):
    print(f"[MQTT] Connected to {MQTT_BROKER} (rc={rc}), subscribing to {MQTT_TOPIC}")
    client.subscribe(MQTT_TOPIC)


def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode())
        if main_loop and main_loop.is_running():
            asyncio.run_coroutine_threadsafe(save_telemetry(data), main_loop)
    except Exception as e:
        print(f"[MQTT ERROR] Parsing failed: {e}")


@app.on_event("startup")
async def startup_event():
    global main_loop, mqtt_client
    main_loop = asyncio.get_running_loop()

    await init_db()

    unique_client_id = f"stocksense_api_{uuid.uuid4().hex[:8]}"
    mqtt_client = mqtt.Client(client_id=unique_client_id)
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message

    print(f"[MQTT] Connecting to {MQTT_BROKER} as {unique_client_id}...")
    mqtt_client.connect_async(MQTT_BROKER, 1883, 60)
    mqtt_client.loop_start()


@app.on_event("shutdown")
async def shutdown_event():
    if mqtt_client:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
    if db_pool:
        await db_pool.close()


@app.get("/api/v1/telemetry/latest")
async def get_latest_telemetry():
    if not db_pool:
        return []
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM telemetry ORDER BY time DESC LIMIT 20")
        return [dict(r) for r in rows]


@app.get("/api/v1/forecast")
def get_ai_forecast():
    forecast_file = BASE_DIR / "ai_forecast_output.json"
    if not forecast_file.exists():
        return {"forecasts": [], "anomalies": [], "error": "ai_forecast_output.json not found in backend folder"}
    with open(forecast_file, "r") as f:
        return json.load(f)