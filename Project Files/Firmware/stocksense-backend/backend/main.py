from fastapi import FastAPI
import paho.mqtt.client as mqtt
import json
import asyncpg
import asyncio

app = FastAPI(title="StockSense Telemetry Backend")

DB_URI = "postgresql://admin:secretpassword@timescaledb:5432/stocksense_db"

# Global database connection pool & main event loop reference
db_pool = None
main_loop = None

async def init_db():
    global db_pool
    await asyncio.sleep(5)  # Give TimescaleDB time to boot up
    
    # Create persistent connection pool
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
        async with db_pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO telemetry(time, device_id, raw_weight, filtered_weight, rfid_tag, status)
                   VALUES (NOW(), $1, $2, $3, $4, $5)""",
                payload.get("device_id"),
                payload.get("raw_weight_g"),
                payload.get("filtered_wt_g"),
                payload.get("rfid_tag"),
                payload.get("status")
            )
            print(f"[DB SUCCESS] Saved telemetry from {payload.get('device_id')}")
    except Exception as e:
        print(f"[DB ERROR] Insert failed: {e}")

def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode())
        # Safely schedule async task into FastAPI's existing event loop
        if main_loop and main_loop.is_running():
            asyncio.run_coroutine_threadsafe(save_telemetry(data), main_loop)
    except Exception as e:
        print(f"[MQTT ERROR] Parsing failed: {e}")

@app.on_event("startup")
async def startup_event():
    global main_loop
    main_loop = asyncio.get_running_loop()
    
    await init_db()
    
    mqtt_client = mqtt.Client()
    mqtt_client.on_message = on_message
    
    print("[MQTT] Connecting to broker.hivemq.com...")
    mqtt_client.connect("broker.hivemq.com", 1883, 60)
    # --- UPDATE TOPIC HERE ---
    mqtt_client.subscribe("stocksense/kavindu/telemetry")
    mqtt_client.loop_start()

@app.on_event("shutdown")
async def shutdown_event():
    if db_pool:
        await db_pool.close()

@app.get("/api/v1/telemetry/latest")
async def get_latest_telemetry():
    if not db_pool:
        return []
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM telemetry ORDER BY time DESC LIMIT 20")
        return [dict(r) for r in rows]