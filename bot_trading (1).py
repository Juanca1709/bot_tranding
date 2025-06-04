import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timedelta
import time
import os
import schedule
import requests
from pytz import timezone

# =======================
# CONFIGURACIÓN GENERAL
# =======================
SYMBOLS = ["EURUSD", "GBPUSD", "AUDUSD"]
CAPITAL_INICIAL = 1000
MAGIC_NUMBER = 123456
MIN_SL_PIPS = 0.0015  # 15 pips en formato decimal
RR_TRIGGER = 1  # Trailing desde 1:1
INTERVALO_MINUTOS = 15
HORAS_EXCLUIDAS = [13, 16, 17, 18, 19, 20, 21, 3]

# Telegram
TELEGRAM_TOKEN = "7783097990:AAG0YdqLwKgEmU9fmHAlt_U9Uj3eEzY6p0g"
TELEGRAM_CHAT_ID = "960425952"
ULTIMO_MENSAJE = datetime.now() - timedelta(hours=1)

# Variables globales
ordenes_enviadas = set()
hora_ultima_alerta = {}
os.makedirs("registros", exist_ok=True)
REGISTRO_PATH = "registros/operaciones.csv"
capital_actual = CAPITAL_INICIAL
perdida_diaria = 0
fecha_actual = datetime.now().date()

# =======================
# FUNCIONES AUXILIARES
# =======================
def enviar_telegram(mensaje):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje}
        requests.post(url, data=data)
    except:
        pass

def calcular_volumen(riesgo, sl_pips):
    valor_por_pip = 10  # para pares con 2 decimales (0.0001 * 100,000 * 1 lote estándar)
    return round(min(max(riesgo / (sl_pips * valor_por_pip), 0.01), 10.0), 2)

def registrar_operacion(data):
    df = pd.DataFrame([data])
    if not os.path.exists(REGISTRO_PATH):
        df.to_csv(REGISTRO_PATH, index=False)
    else:
        df.to_csv(REGISTRO_PATH, mode='a', header=False, index=False)

def es_vela_dominante(open, close, high, low):
    return abs(close - open) / (high - low + 1e-6) >= 0.6

def orden_abierta(symbol):
    ordenes = mt5.positions_get(symbol=symbol)
    return len(ordenes) > 0

def gestionar_operaciones():
    global capital_actual, perdida_diaria, fecha_actual

    ahora = datetime.now()
    if ahora.date() != fecha_actual:
        perdida_diaria = 0
        fecha_actual = ahora.date()

    posiciones = mt5.positions_get()
    for pos in posiciones:
        order_time = datetime.fromtimestamp(pos.time)
        entry_price = pos.price_open
        symbol = pos.symbol
        direction = "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL"

        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            continue

        actual_price = tick.bid if direction == "BUY" else tick.ask

        # Trailing Stop desde 1:1
        if (direction == "BUY" and actual_price >= entry_price + MIN_SL_PIPS) or \
           (direction == "SELL" and actual_price <= entry_price - MIN_SL_PIPS):
            new_sl = round(entry_price, 5)
            mt5.order_modify(pos.ticket, sl=new_sl, tp=0, deviation=10)

        # Cierre tras 2h si va en ganancia
        if ahora - order_time > timedelta(hours=2):
            if (direction == "BUY" and actual_price > entry_price) or \
               (direction == "SELL" and actual_price < entry_price):
                close_request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": symbol,
                    "volume": pos.volume,
                    "type": mt5.ORDER_TYPE_SELL if direction == "BUY" else mt5.ORDER_TYPE_BUY,
                    "position": pos.ticket,
                    "price": actual_price,
                    "deviation": 10,
                    "magic": MAGIC_NUMBER,
                    "comment": "Cierre por tiempo",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_FOK
                }
                result = mt5.order_send(close_request)
                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                    enviar_telegram(f"🕒 Cierre por tiempo: {symbol} {direction} con ganancia")

# =======================
# LÓGICA DE ENTRADA
# =======================
def detectar_y_enviar_orden(symbol):
    global capital_actual, perdida_diaria

    if orden_abierta(symbol):
        return

    if perdida_diaria >= 0.05 * capital_actual:
        print(f"[INFO] Límite de pérdida diaria alcanzado: {symbol}")
        return

    m15 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 100)
    if m15 is None or len(m15) < 40:
        return

    df = pd.DataFrame(m15)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df.set_index('time', inplace=True)

    for i in range(len(df)-20, len(df)-5):
        row = df.iloc[i]
        if not es_vela_dominante(row['open'], row['close'], row['high'], row['low']):
            continue

        direction = None
        if row['close'] > df['high'].iloc[i-5:i].max():
            direction = 'BUY'
        elif row['close'] < df['low'].iloc[i-5:i].min():
            direction = 'SELL'
        else:
            continue

        tick = mt5.symbol_info_tick(symbol)
        info = mt5.symbol_info(symbol)
        if not tick or not info:
            return

        entry_price = tick.ask if direction == 'BUY' else tick.bid
        sl_price = entry_price - MIN_SL_PIPS if direction == 'BUY' else entry_price + MIN_SL_PIPS
        tp_price = entry_price + MIN_SL_PIPS if direction == 'BUY' else entry_price - MIN_SL_PIPS

        min_distance = info.trade_stops_level * info.point
        if abs(entry_price - sl_price) < min_distance:
            sl_price = entry_price - min_distance if direction == 'BUY' else entry_price + min_distance

        sl_pips = abs(entry_price - sl_price) / 0.0001
        riesgo_usd = capital_actual * 0.01
        volume = calcular_volumen(riesgo_usd, sl_pips)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": mt5.ORDER_TYPE_BUY if direction == 'BUY' else mt5.ORDER_TYPE_SELL,
            "price": entry_price,
            "sl": round(sl_price, 5),
            "tp": round(tp_price, 5),
            "deviation": 10,
            "magic": MAGIC_NUMBER,
            "comment": "TP1_2 + Trailing + Cierre2h",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK
        }

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            enviar_telegram(f"✅ ORDEN {symbol} {direction} | Entrada: {round(entry_price,5)} | SL: {round(sl_price,5)} | TP: {round(tp_price,5)} | Vol: {volume}")
            registrar_operacion({
                "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "symbol": symbol,
                "tipo": direction,
                "precio": entry_price,
                "sl": sl_price,
                "tp": tp_price,
                "volumen": volume,
                "resultado": result.retcode
            })

# =======================
# LOOP PRINCIPAL
# =======================
if not mt5.initialize():
    enviar_telegram("❌ No se pudo conectar a MT5")
    quit()

enviar_telegram("🤖 Bot activo con EURUSD/GBPUSD/AUDUSD")

schedule.every().day.at("19:00").do(lambda: enviar_telegram("⏰ Resumen pendiente..."))

def orden_abierta(symbol):
    """Verifica si hay una orden abierta para el símbolo especificado."""
    posiciones = mt5.positions_get(symbol=symbol)
    return posiciones is not None and len(posiciones) > 0

hora_ultima_alerta = {}

while True:
    ahora_col = datetime.now(timezone("America/Bogota"))
    hora_ny = ahora_col.astimezone(timezone("America/New_York")).hour

    gestionar_operaciones()

    for symbol in SYMBOLS:
        if hora_ny in HORAS_EXCLUIDAS:
            hora_actual = datetime.now().strftime("%Y-%m-%d %H")
            if hora_ultima_alerta.get(symbol) != hora_actual:
                enviar_telegram(f"⛔️ Hora no operativa, sin entradas para {symbol}")
                hora_ultima_alerta[symbol] = hora_actual
            continue

        if orden_abierta(symbol): 
            print(f"[INFO] {symbol} ya tiene una operación activa.")
            continue

        detectar_y_enviar_orden(symbol)

    if (datetime.now() - ULTIMO_MENSAJE).seconds > 3600:
        enviar_telegram("🟢 Bot operativo buscando entradas...")
        ULTIMO_MENSAJE = datetime.now()

    schedule.run_pending()
    time.sleep(INTERVALO_MINUTOS * 60)

