
import MetaTrader5 as mt5
import pandas as pd
import requests
from datetime import datetime, timedelta
import time
import os

# ===========================
# Configuración general
# ===========================
SYMBOLS = ["EURUSD", "GBPUSD", "AUDUSD"]
CAPITAL_INICIAL = 1000
RIESGO_USD = 50
INTERVALO_MINUTOS = 15
MAGIC_NUMBER = 123456
HORAS_EXCLUIDAS = [13, 17, 18, 19, 20, 21, 3]  # Hora local (Colombia, = NY)

# ===========================
# Telegram
# ===========================
TELEGRAM_TOKEN = "7783097990:AAG0YdqLwKgEmU9fmHAlt_U9Uj3eEzY6p0g"
TELEGRAM_CHAT_ID = "960425952"
ULTIMO_MENSAJE = datetime.now() - timedelta(hours=1)

# ===========================
# Registro
# ===========================
REGISTRO_PATH = "registros/operaciones.csv"
os.makedirs("registros", exist_ok=True)

def enviar_telegram(mensaje):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje}
        requests.post(url, data=data)
    except Exception as e:
        print(f"[Telegram] Error: {e}")

def registrar_operacion(data):
    df = pd.DataFrame([data])
    if not os.path.exists(REGISTRO_PATH):
        df.to_csv(REGISTRO_PATH, index=False)
    else:
        df.to_csv(REGISTRO_PATH, mode='a', header=False, index=False)

def calcular_volumen(sl_pips):
    return round(RIESGO_USD / sl_pips, 2)

def detectar_entrada(symbol):
    h1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 6)
    m15 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 6)
    if h1 is None or m15 is None:
        return None

    df_h1 = pd.DataFrame(h1)
    df_m15 = pd.DataFrame(m15)
    if df_h1["close"].iloc[-1] > df_h1["close"].iloc[0]:
        tendencia = "buy"
    elif df_h1["close"].iloc[-1] < df_h1["close"].iloc[0]:
        tendencia = "sell"
    else:
        return None

    if tendencia == "buy" and df_m15["close"].iloc[-1] <= df_m15["high"].iloc[:-1].max():
        return None
    if tendencia == "sell" and df_m15["close"].iloc[-1] >= df_m15["low"].iloc[:-1].min():
        return None

    return tendencia

def enviar_orden(symbol, tendencia):
    if not mt5.symbol_select(symbol, True):
        enviar_telegram(f"❌ No se pudo seleccionar: {symbol}")
        return

    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if not info or not tick:
        enviar_telegram(f"❌ Error al obtener datos de {symbol}")
        return

    price = tick.ask if tendencia == "buy" else tick.bid
    sl_pips = max(info.trade_stops_level * info.point, 0.00020)
    sl = price - sl_pips if tendencia == "buy" else price + sl_pips
    volume = calcular_volumen(sl_pips / info.point)
    order_type = mt5.ORDER_TYPE_BUY if tendencia == "buy" else mt5.ORDER_TYPE_SELL

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": max(min(volume, info.volume_max), info.volume_min),
        "type": order_type,
        "price": price,
        "sl": round(sl, 5),
        "tp": 0,
        "deviation": 10,
        "magic": MAGIC_NUMBER,
        "comment": "Live Entry",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC
    }

    result = mt5.order_send(request)
    if result is None:
        enviar_telegram(f"❌ Error: order_send devolvió None para {symbol}")
        return
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        enviar_telegram(f"❌ ERROR {result.retcode} al enviar orden {symbol.upper()} {tendencia.upper()}\nDetalles: {result.comment}")
        return

    registrar_operacion({
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": symbol,
        "tipo": tendencia,
        "precio": round(price, 5),
        "sl": round(sl, 5),
        "tp": 0,
        "volumen": volume,
        "resultado": result.retcode
    })

    enviar_telegram(
        f"✅ ORDEN EJECUTADA: {symbol} {tendencia.upper()}\nPrecio: {round(price, 5)} | SL: {round(sl, 5)} | Vol: {volume}"
    )

# ===========================
# Loop principal
# ===========================
if not mt5.initialize():
    enviar_telegram("❌ No se pudo conectar a MT5")
    quit()

enviar_telegram("🤖 Bot activo para EUR/GBP/AUD con trailing 1:2")

while True:
    ahora = datetime.now()
    hora_local = ahora.hour

    for symbol in SYMBOLS:
        if hora_local not in HORAS_EXCLUIDAS:
            direccion = detectar_entrada(symbol)
            if direccion:
                enviar_orden(symbol, direccion)

    # Actualización de estado cada hora
    global ULTIMO_MENSAJE
    if (datetime.now() - ULTIMO_MENSAJE).seconds > 3600:
        enviar_telegram("🟢 Bot operativo buscando entradas...")
        ULTIMO_MENSAJE = datetime.now()

    time.sleep(INTERVALO_MINUTOS * 60)
