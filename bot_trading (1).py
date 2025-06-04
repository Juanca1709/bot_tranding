# === BOT DE TRADING EN TIEMPO REAL PARA MT5 ===
# Autor: Configurado para Juan Camilo - Deriv Demo
# Entrada inmediata durante la vela de las 13:30 UTC y 14:00 UTC

import MetaTrader5 as mt5
import pandas as pd
import datetime
import time
import os
import requests
import csv # Importar para el manejo de CSV
import decimal
from datetime import timezone

SYMBOLS = ["US Tech 100", "Wall Street 30", "Japan 225"]

# --- PARÁMETROS DE LA ESTRATEGIA ---
RISK_PERCENT = 0.02           # Porcentaje de riesgo por operación (2%).
SL_MIN_PTS = 30               # Stop Loss Mínimo en PUNTOS
RR_RATIO = 1.0                # Ratio Riesgo/Recompensa (1:1)

# === DEFINICIÓN DE LA PRIMERA VELA DE TRAMPA (13:25 M5 UTC) ===
TRAP_M5_CANDLE_OPEN_HOUR_UTC_1 = 13     # Hora UTC de APERTURA de la vela de trampa M5
TRAP_M5_CANDLE_OPEN_MINUTE_UTC_1 = 25   # Minuto UTC de APERTURA de la vela de trampa M5

# Momento en que se DISPONE de los datos finales de la vela de trampa (después de su cierre).
TRAP_CANDLE_EVAL_HOUR_UTC_1 = 13
TRAP_CANDLE_EVAL_MINUTE_UTC_1 = 30 

# Hora de inicio para la búsqueda de entradas (no antes de esta hora).
TRADE_ENTRY_START_HOUR_UTC_1 = 13
TRADE_ENTRY_START_MINUTE_UTC_1 = 30

# Hora UTC de fin de la ventana de monitoreo M1 para buscar la ruptura.
MONITORING_END_HOUR_UTC_1 = 13 
MONITORING_END_MINUTE_UTC_1 = 35 

# === NUEVA DEFINICIÓN DE LA SEGUNDA VELA DE TRAMPA (13:55 M5 UTC) ===
TRAP_M5_CANDLE_OPEN_HOUR_UTC_2 = 13     # Hora UTC de APERTURA de la vela de trampa M5
TRAP_M5_CANDLE_OPEN_MINUTE_UTC_2 = 55   # Minuto UTC de APERTURA de la vela de trampa M5

# Momento en que se DISPONE de los datos finales de la vela de trampa (después de su cierre).
TRAP_CANDLE_EVAL_HOUR_UTC_2 = 14
TRAP_CANDLE_EVAL_MINUTE_UTC_2 = 00 

# Hora de inicio para la búsqueda de entradas (no antes de esta hora).
TRADE_ENTRY_START_HOUR_UTC_2 = 14
TRADE_ENTRY_START_MINUTE_UTC_2 = 00

# Hora UTC de fin de la ventana de monitoreo M1 para buscar la ruptura.
MONITORING_END_HOUR_UTC_2 = 14 
MONITORING_END_MINUTE_UTC_2 = 5

CSV_FILE = "operaciones_institucional.csv" # Cambiado a un nombre más específico

TELEGRAM_TOKEN = "7783097990:AAG0YdqLwKgEmU9fmHAlt_U9Uj3eEzY6p0g" 
TELEGRAM_CHAT_ID = "960425952"

# --- Variables Globales de Estado del Bot ---
# Almacena las trampas detectadas para el día (High, Low, Time) por símbolo.
global_trampas_detectadas_1 = {} 
global_trampas_detectadas_2 = {} 

# Indica si ya se ha ejecutado una operación para un símbolo específico en el día actual para cada trampa.
operacion_hoy_ejecutada_1 = {symbol: False for symbol in SYMBOLS}
operacion_hoy_ejecutada_2 = {symbol: False for symbol in SYMBOLS}

# Variables para el seguimiento de velas M1 ya evaluadas.
ultima_vela_m1_evaluada_1 = {symbol: None for symbol in SYMBOLS}
ultima_vela_m1_evaluada_2 = {symbol: None for symbol in SYMBOLS}

# Para rastrear operaciones abiertas por el bot y evitar monitoreo duplicado de cierres.
open_bot_orders = {} # {ticket: {"symbol": symbol, "type": "buy/sell", "entry_price": price}}
# Para registrar tickets ya notificados de cierre
notified_closed_orders = set()

# --- FUNCIONES DE SOPORTE ---

def send_telegram(msg):
    """Envía un mensaje a Telegram."""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
        requests.post(url, data=data)
    except Exception as e:
        print(f"[Telegram] Error al enviar mensaje: {e}")

def obtener_velas(symbol, timeframe, n=100):
    """Obtiene datos de velas de MT5."""
    tf = mt5.TIMEFRAME_M5 if timeframe == "M5" else mt5.TIMEFRAME_M1
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, n)
    df = pd.DataFrame(rates)
    if df.empty:
        return df
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    df.set_index('time', inplace=True)
    return df[['open', 'high', 'low', 'close']]

def calcular_volumen(symbol, sl_puntos, capital):
    """Calcula el volumen de la operación basado en el riesgo porcentual y el capital."""
    info = mt5.symbol_info(symbol)
    if info is None or not info.visible:
        print(f"Error: Símbolo {symbol} no encontrado o no visible para cálculo de volumen.")
        return 0.0

    point = info.point 
    trade_contract_size = info.trade_contract_size 

    # --- DEBUG INFO SIMBOLO EN CALCULAR_VOLUMEN ---
    print(f"DEBUG VOLUMEN: {symbol} - Point: {point}, Digits: {info.digits}, Contract Size: {trade_contract_size}")
    # --- FIN DEBUG INFO SIMBOLO EN CALCULAR_VOLUMEN ---

    if point == 0 or trade_contract_size == 0:
        print(f"Error: El valor del punto o tamaño del contrato es cero para {symbol}. No se puede calcular el volumen.")
        return 0.0

    valor_punto = point * trade_contract_size 

    if valor_punto == 0: 
        print(f"Error: El valor del punto final es cero para {symbol} (después de cálculos iniciales).")
        return 0.0

    riesgo_dinero = capital * RISK_PERCENT
    
    if sl_puntos <= 0:
        print(f"Error: SL en puntos debe ser positivo para {symbol} para calcular volumen.")
        return 0.0
    
    volumen_calculado = riesgo_dinero / (sl_puntos * valor_punto) 
    
    min_volume = info.volume_min
    max_volume = info.volume_max
    volume_step = info.volume_step

    if volume_step == 0: 
        print(f"Advertencia: volume_step es cero para {symbol}. Usando 0.01 como fallback.")
        volume_step = 0.01

    volumen_calculado = round(volumen_calculado / volume_step) * volume_step
    volumen = max(min_volume, min(volumen_calculado, max_volume))
    
    # --- CORRECCIÓN AQUÍ: Determinar los decimales del volume_step ---
    # Opción 1: Usando la librería decimal (más robusta para floats complejos)
    decimal_volume_step = decimal.Decimal(str(volume_step))
    decimals_to_round = -decimal_volume_step.as_tuple().exponent if volume_step > 0 else 2 # Fallback
    
    # Opción 2: Usando math.log10 (más simple para 0.1, 0.01, etc.)
    # if volume_step > 0:
    #     decimals_to_round = int(round(-math.log10(volume_step), 0))
    # else:
    #     decimals_to_round = 2 # Fallback si volume_step es 0

    volumen_final = round(volumen, decimals_to_round) 
    print(f"DEBUG VOLUMEN: Volumen calculado: {volumen_calculado}, Volumen final ajustado: {volumen_final} (Redondeado a {decimals_to_round} decimales)")

    return volumen_final

import MetaTrader5 as mt5

# Asumiendo que RISK_PERCENT está definido en algún lugar del script
# Por ejemplo:
RISK_PERCENT = 0.01 # 1% de riesgo por operación

def calcular_volumen(symbol, sl_puntos, capital):
    info = mt5.symbol_info(symbol)
    if info is None or not info.visible:
        print(f"Error: Símbolo {symbol} no encontrado o no visible para cálculo de volumen.")
        return 0.0

    point = info.point
    trade_contract_size = info.trade_contract_size

    # --- MODIFICACIÓN POTENCIAL PARA JAPAN 225 ---
    valor_punto_real = point * trade_contract_size # Valor por defecto

    if symbol == "Japan 225":
        # Investiga el valor real del punto para Japan 225 con tu bróker.
        # Ejemplo: Si el valor de un punto es 0.5 USD por cada unidad de volumen (lote 1.0)
        # Y si trade_contract_size ya es 1.0 y point es 1.0, pero el valor es 0.5 USD,
        # significa que point * trade_contract_size da 1.0 pero debería dar 0.5.
        # Por lo tanto, necesitamos un factor de corrección.
        
        # Una forma más segura es consultar la especificación del contrato y si 
        # tu bróker lo define de forma diferente, aplicar un ajuste.
        # Digamos que 1.0 lote de Japan 225 vale 0.5 USD por punto.
        # Y mt5.symbol_info('Japan 225').point es 1.0
        # Entonces, (1.0 lot * 1.0 point) vale 0.5 USD.
        # Actualmente tu código calcula: valor_punto = 1.0 * 1.0 = 1.0
        # Necesitas que valor_punto sea 0.5
        # Por ejemplo, si descubres que para Japan 225, 1.0 lote de volumen es 0.5 USD/punto:
        valor_punto_real = 0.5 # Este valor DEBE ser confirmado con las especificaciones de tu bróker.
        print(f"DEBUG VOLUMEN: AJUSTE ESPECIAL PARA JAPAN 225. Valor de punto usado: {valor_punto_real}")

    # --- FIN MODIFICACIÓN POTENCIAL ---

    if valor_punto_real == 0: 
        print(f"Error: El valor del punto final es cero para {symbol} (después de cálculos iniciales).")
        return 0.0

    riesgo_dinero = capital * RISK_PERCENT
    
    if sl_puntos <= 0:
        print(f"Error: SL en puntos debe ser positivo para {symbol} para calcular volumen.")
        return 0.0
    
    volumen_calculado = riesgo_dinero / (sl_puntos * valor_punto_real) # Usar valor_punto_real
    
    min_volume = info.volume_min
    max_volume = info.volume_max
    volume_step = info.volume_step

    # --- INICIO DEL CÓDIGO FALTANTE PARA DEFINIR volumen_final ---
    # Asegurarse de que el volumen esté dentro de los límites y sea un múltiplo del step
    
    # Redondear el volumen_calculado al múltiplo más cercano de volume_step
    # Esto se hace dividiendo por volume_step, redondeando al entero más cercano, y luego multiplicando por volume_step
    volumen_final = round(volumen_calculado / volume_step) * volume_step
    
    # Asegurarse de que el volumen_final no sea menor que min_volume
    if volumen_final < min_volume:
        volumen_final = min_volume
    
    # Asegurarse de que el volumen_final no sea mayor que max_volume
    if volumen_final > max_volume:
        volumen_final = max_volume
    
    # Asegurarse de que el volumen final no sea cero si el calculado fue positivo
    if volumen_final == 0 and volumen_calculado > 0:
        volumen_final = min_volume # O manejar como un error si 0 no es aceptable

    # --- FIN DEL CÓDIGO FALTANTE ---

    return volumen_final

# --- FUNCIÓN registrar_operacion_csv (MODIFICACIÓN) ---
def registrar_operacion_csv(timestamp, ticket, symbol, tipo, entry_price, close_price, profit, sl, tp, volume, risk_money, status):
    """Registra los detalles de una operación en un archivo CSV, evitando duplicados y filtrando símbolos.
    Ahora incluye close_price, profit y risk_money."""
    
    # Asegúrate de que CSV_FILE y SYMBOLS estén definidos globalmente o pasados como argumentos si no lo están.
    # Ejemplo:
    # CSV_FILE = "operaciones_bot.csv"
    # SYMBOLS = ["US Tech 100", "Wall Street 30", "Japan 225"]

    if symbol not in SYMBOLS: # Solo guardar operaciones de los símbolos listados
        return

    # Verificar si el ticket ya existe en el CSV para evitar duplicados
    # Es importante que esta verificación se haga con el ticket de la POSICIÓN
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, mode='r', newline='') as file:
            reader = csv.reader(file)
            header = next(reader, None) # Leer la cabecera
            if header: # Si hay cabecera, buscamos la columna del Ticket
                try:
                    ticket_col_index = header.index("Ticket")
                except ValueError:
                    # Si 'Ticket' no está en la cabecera, asumimos la segunda columna como fallback
                    ticket_col_index = 1 
            else:
                ticket_col_index = 1 # Si no hay cabecera, asumimos segunda columna

            for row in reader:
                if len(row) > ticket_col_index and row[ticket_col_index] == str(ticket):
                    # print(f"DEBUG: Operación Ticket {ticket} ya existe en CSV. No duplicar.")
                    return # Ya existe, no duplicar

    existe = os.path.exists(CSV_FILE)
    with open(CSV_FILE, mode='a', newline='') as file:
        writer = csv.writer(file)
        if not existe:
            # --- CABECERA ACTUALIZADA ---
            writer.writerow(["Timestamp", "Ticket", "Symbol", "Type", "Entry Price", "Close Price", "Profit", "SL", "TP", "Volume", "Risk Money", "Status"])
        # --- FILA DE DATOS ACTUALIZADA ---
        writer.writerow([timestamp, ticket, symbol, tipo, entry_price, close_price, profit, sl, tp, volume, risk_money, status])
    
    print(f"✅ Operación Ticket {ticket} registrada en {CSV_FILE}")


def abrir_operacion(symbol, direccion, precio_entrada, sl, tp, volumen, riesgo_dinero_estimado):
    """Envía una orden de mercado para abrir una operación."""
    info = mt5.symbol_info(symbol)
    if info is None or not info.visible:
        send_telegram(f"❌ Error al abrir operación: Símbolo {symbol} no encontrado o no visible.")
        return False

    # --- DEBUG INFO SIMBOLO ---
    print(f"DEBUG SYMBOL INFO: {symbol} - Point: {info.point}, Digits: {info.digits}, Trade Contract Size: {info.trade_contract_size}")
    # --- FIN DEBUG INFO SIMBOLO ---

    tipo_mt5 = mt5.ORDER_TYPE_BUY if direccion == "compra" else mt5.ORDER_TYPE_SELL

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        send_telegram(f"❌ Error al obtener tick para {symbol}.")
        return False

    current_price = tick.ask if tipo_mt5 == mt5.ORDER_TYPE_BUY else tick.bid

    # --- DEBUG PRECIOS RECIBIDOS EN ABRIR_OPERACION ---
    print(f"DEBUG RECIBIDOS EN abrir_operacion: Entrada: {precio_entrada:.{info.digits}f}, SL: {sl:.{info.digits}f}, TP: {tp:.{info.digits}f}, Volumen: {volumen}")
    # --- FIN DEBUG PRECIOS RECIBIDOS ---

    # Redondear los precios a los decimales que maneja el broker
    sl_rounded = round(sl, info.digits)
    tp_rounded = round(tp, info.digits)
    current_price_rounded = round(current_price, info.digits)

    # --- DEBUG PRECIOS REDONDEADOS ---
    print(f"DEBUG REDONDEADOS PARA MT5: SL: {sl_rounded:.{info.digits}f}, TP: {tp_rounded:.{info.digits}f}, Current Price: {current_price_rounded:.{info.digits}f}")
    # --- FIN DEBUG PRECIOS REDONDEADOS ---

    filling_mode = mt5.ORDER_FILLING_FOK 

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volumen,
        "type": tipo_mt5,
        "price": current_price_rounded, 
        "sl": sl_rounded,            
        "tp": tp_rounded,            
        "deviation": 20,
        "magic": 10001,
        "type_filling": filling_mode,
        "comment": "Bot institucional M5+M1"
    }

    result = mt5.order_send(request)

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        send_telegram(f"❌ Error al abrir operación para {symbol}: {result.retcode}\nMensaje: {result.comment}")
        print(f"Error en order_send: {result.retcode} - {result.comment} (Símbolo: {symbol}, Volumen: {volumen}, SL: {sl_rounded}, TP: {tp_rounded})") 
        return False

    print(f"✅ Orden enviada correctamente para {symbol}: #{result.order}")
    send_telegram(
        f"✅ ORDEN EJECUTADA (LIVE)\n"
        f"Tiempo: {datetime.datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
        f"Símbolo: {symbol}\n"
        f"Tipo: {direccion.capitalize()}\n"
        f"Precio: {current_price_rounded:.{info.digits}f}\n" # Usar el precio real de ejecución
        f"SL: {sl_rounded:.{info.digits}f}\n"
        f"TP: {tp_rounded:.{info.digits}f}\n"
        f"Volumen: {volumen}\n"
        f"Riesgo estimado: ${riesgo_dinero_estimado:.2f}"
    )
    
    # Registrar la operación en el CSV
    # Corregida la llamada a registrar_operacion_csv con los argumentos correctos
    registrar_operacion_csv(
        datetime.datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'), # timestamp
        result.order,                                                        # ticket
        symbol,                                                              # symbol
        direccion.capitalize(),                                              # tipo
        current_price_rounded,                                               # entry_price
        0.0,                                                                 # close_price (0.0 para ordenes OPEN)
        0.0,                                                                 # profit (0.0 para ordenes OPEN)
        sl_rounded,                                                          # sl
        tp_rounded,                                                          # tp
        volumen,                                                             # volume
        riesgo_dinero_estimado,                                              # risk_money (¡AHORA INCLUIDO!)
        "OPEN"                                                               # status (¡AHORA INCLUIDO!)
    )

    # --- INICIO DE LA MODIFICACIÓN AQUÍ ---
    # Cambia este bloque:
    open_bot_orders[result.order] = {
        "symbol": symbol,
        "direction": direccion, # Cambié "type" a "direction" para consistencia.
        "entry_price": current_price_rounded,
        "sl": sl_rounded,        # AÑADE ESTO
        "tp": tp_rounded,        # AÑADE ESTO
        "volume": volumen,       # AÑADE ESTO
        "initial_risk_money": riesgo_dinero_estimado # AÑADE ESTO
    }
    # --- FIN DE LA MODIFICACIÓN AQUÍ ---
    
    return True

def detectar_trampa(symbol, df_m5, candle_open_time_to_find):
    """
    Detecta la vela de trampa M5 buscando la vela que abre en el 'candle_open_time_to_find'.
    Retorna el high, low y tiempo de apertura de esa vela.
    """
    if df_m5.empty:
        return None
    
    # Asegúrate de que las fechas coincidan si la trampa se busca en el día actual
    # La fecha de la vela M5 (df_m5.index[-1].date()) debería ser la misma que 'now.date()'
    
    target_candle_open_datetime = datetime.datetime.combine(
        now.date(), # Usar la fecha actual del bot
        candle_open_time_to_find, 
        tzinfo=timezone.utc 
    )

    try:
        # Asegurarse de que la vela existe en el índice exacto
        if target_candle_open_datetime in df_m5.index:
            vela_trampa = df_m5.loc[target_candle_open_datetime]
            return {"high": vela_trampa['high'], "low": vela_trampa['low'], "time": target_candle_open_datetime}
        else:
            print(f"{symbol}: Vela M5 con apertura {target_candle_open_datetime.strftime('%H:%M')} no encontrada en los datos. Última vela: {df_m5.index[-1].strftime('%H:%M') if not df_m5.empty else 'N/A'}")
            return None
    except KeyError:
        print(f"{symbol}: Error al buscar vela M5 para {target_candle_open_datetime.strftime('%H:%M')}. Puede que la vela no exista o el índice sea incorrecto.")
        return None

# --- FUNCIÓN monitorear_operaciones_abiertas (REEMPLAZAR COMPLETO) ---
def monitorear_operaciones_abiertas():
    global notified_closed_orders

    # Obtener todas las posiciones abiertas
    positions = mt5.positions_get()
    
    # Obtener los tickets de las posiciones actualmente abiertas
    current_open_position_tickets = {pos.ticket for pos in positions}

    # Identificar qué operaciones del bot ya no están abiertas (fueron cerradas)
    # y no han sido notificadas previamente
    closed_positions_tickets_from_bot = [
        ticket for ticket in open_bot_orders.keys()
        if ticket not in current_open_position_tickets and ticket not in notified_closed_orders
    ]

    for closed_ticket in closed_positions_tickets_from_bot:
        if closed_ticket in open_bot_orders:
            # Recuperar los detalles de la orden que teníamos guardados de abrir_operacion
            order_details = open_bot_orders[closed_ticket]
            symbol = order_details['symbol']
            direction = order_details['direction']
            entry_price = order_details['entry_price']
            volume = order_details['volume']
            sl = order_details['sl']
            tp = order_details['tp']
            initial_risk_money = order_details['initial_risk_money']

            # Buscar el deal de cierre asociado a esta posición
            # Buscamos deals desde el inicio del día para no perder cierres recientes
            now_utc = datetime.datetime.now(timezone.utc)
            start_of_day_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
            
            deals = mt5.history_deals_get(start_of_day_utc, now_utc)

            deal_de_cierre = None
            if deals:
                for deal in deals:
                    # deal.position_id es el ticket de la POSICIÓN original
                    # deal.entry == mt5.DEAL_ENTRY_OUT indica que es un deal de CIERRE
                    # Aseguramos que el deal sea del mismo símbolo
                    if deal.position_id == closed_ticket and deal.entry == mt5.DEAL_ENTRY_OUT and deal.symbol == symbol:
                        deal_de_cierre = deal
                        break

            msg_telegram = ""
            if deal_de_cierre:
                close_price = deal_de_cierre.price
                profit = deal_de_cierre.profit
                # Determinar si fue ganancia o pérdida
                status = "GANANCIA" if profit >= 0 else "PÉRDIDA"

                # Obtener info_symbol para formatear precios con los dígitos correctos
                info_symbol = mt5.symbol_info(symbol)
                digits = info_symbol.digits if info_symbol else 2 # Fallback si no se obtiene info_symbol

                # Construir el mensaje para Telegram
                msg_telegram = (
                    f"🔔 CIERRE DE OPERACIÓN: {symbol}\n"
                    f"Ticket: {closed_ticket}\n"
                    f"Tipo: {direction.upper()}\n"
                    f"Precio de Entrada: {entry_price:.{digits}f}\n"
                    f"Precio de Cierre: {close_price:.{digits}f}\n"
                    f"Ganancia/Pérdida: ${profit:.2f} ({status})\n"
                    f"Volumen: {volume:.2f}\n"
                    f"SL: {sl:.{digits}f}, TP: {tp:.{digits}f}"
                )
                print(f"DEBUG: Deal de cierre encontrado para posición {closed_ticket}. Ganancia/Pérdida: {profit:.2f}")

                # Registrar en CSV
                registrar_operacion_csv(
                    # Asegúrate que registrar_operacion_csv acepta estos argumentos
                    datetime.datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'), # Timestamp del cierre
                    closed_ticket, symbol, direction.capitalize(), entry_price, close_price, profit,
                    sl, tp, volume, initial_risk_money, status
                )

            else:
                # Si no se encontró un deal de cierre, podría ser un cierre manual o por condiciones no capturadas
                # O si el deal está en un historial más antiguo (aunque buscamos desde inicio del día).
                print(f"DEBUG: No se encontró deal de cierre específico para la posición {closed_ticket}. Podría ser un cierre manual, por SL/TP, o el deal no está en el historial reciente.")
                
                info_symbol = mt5.symbol_info(symbol)
                digits = info_symbol.digits if info_symbol else 2

                msg_telegram = (
                    f"❌ CIERRE DE OPERACIÓN (Posible Cierre SL/TP o Manual/No Deal Encontrado)\n"
                    f"Símbolo: {symbol}\n"
                    f"Ticket: {closed_ticket}\n"
                    f"Tipo: {direction.upper()}\n"
                    f"Precio de Entrada: {entry_price:.{digits}f}\n"
                    f"Ganancia/Pérdida: Desconocida (revisar MT5)\n"
                    f"Volumen: {volume:.2f}\n"
                    f"Estado: Cerrada"
                )
                # Registrar con estado desconocido
                registrar_operacion_csv(
                    # Asegúrate que registrar_operacion_csv acepta estos argumentos
                    datetime.datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'), # Timestamp del cierre
                    closed_ticket, symbol, direction.capitalize(), entry_price, 0.0, 0.0, # Precio de cierre y profit desconocidos
                    sl, tp, volume, initial_risk_money, "CLOSED_UNKNOWN"
                )

            send_telegram(msg_telegram)
            notified_closed_orders.add(closed_ticket) # Marcar como notificado
            del open_bot_orders[closed_ticket] # Eliminar del diccionario de órdenes abiertas del bot

    # Opcional: Limpiar notified_closed_orders periódicamente para no crecer indefinidamente
    # if len(notified_closed_orders) > 1000: # Ejemplo, ajusta el límite según tu volumen de operaciones
    #     notified_closed_orders.clear()
    
# --- INICIAR MT5 ---
if not mt5.initialize():
    print("❌ No se pudo iniciar MT5. Asegúrate de que MT5 está abierto y tienes una cuenta conectada.")
    send_telegram("❌ Bot de Trading: No se pudo iniciar MT5. Revisar conexión o terminal.")
    quit()

capital_inicial = mt5.account_info().equity
if capital_inicial <= 0:
    print("❌ Capital no disponible o cero. No se puede operar.")
    send_telegram("❌ Bot de Trading: Capital no disponible o cero. Revisar cuenta.")
    mt5.shutdown()
    quit()

print(f"📊 Bot activo. Capital inicial: {capital_inicial:.2f} USD. Esperando ventana de operación...")
send_telegram(f"📊 Bot activo con Índices bursátiles . Capital: {capital_inicial:.2f} USD. Esperando ventana de operación.")

# Para gestionar el reset diario de las banderas de operación.
last_check_date = datetime.datetime.now(timezone.utc).date() 

# --- BUCLE PRINCIPAL DEL BOT ---
while True:
    now = datetime.datetime.now(timezone.utc)
    current_date = now.date()
    current_hour_utc = now.hour
    current_minute_utc = now.minute

    # --- Reset diario de banderas ---
    if current_date > last_check_date:
        for symbol in SYMBOLS:
            operacion_hoy_ejecutada_1[symbol] = False
            operacion_hoy_ejecutada_2[symbol] = False
            ultima_vela_m1_evaluada_1[symbol] = None 
            ultima_vela_m1_evaluada_2[symbol] = None 
        global_trampas_detectadas_1 = {} 
        global_trampas_detectadas_2 = {} 
        open_bot_orders = {} # Limpiar operaciones abiertas del bot
        notified_closed_orders = set() # Limpiar tickets notificados
        print("🚩 Nuevo día de trading. Resetando estado de operaciones y trampas detectadas.")
        send_telegram("🚩 Nuevo día de trading. Bot listo para operar.")
        last_check_date = current_date 

    # --- Monitorear y notificar cierres de operaciones ---
    monitorear_operaciones_abiertas()

    # --- Lógica de Detección de la PRIMERA Trampa (Evaluación a las 13:30 UTC) ---
    if current_hour_utc == TRAP_CANDLE_EVAL_HOUR_UTC_1 and \
       current_minute_utc == TRAP_CANDLE_EVAL_MINUTE_UTC_1:
        
        if not global_trampas_detectadas_1: 
            print(f"⏳ {now.strftime('%H:%M')}: Intentando detectar PRIMERA vela de trampa M5 (abre {TRAP_M5_CANDLE_OPEN_HOUR_UTC_1}:{TRAP_M5_CANDLE_OPEN_MINUTE_UTC_1}, cierra {TRAP_CANDLE_EVAL_HOUR_UTC_1}:{TRAP_CANDLE_EVAL_MINUTE_UTC_1})...")
            newly_detected_traps_1 = {} 

            for symbol in SYMBOLS:
                if not operacion_hoy_ejecutada_1[symbol]: 
                    df_m5 = obtener_velas(symbol, "M5", 10) 
                    trampa = detectar_trampa(symbol, df_m5, datetime.time(TRAP_M5_CANDLE_OPEN_HOUR_UTC_1, TRAP_M5_CANDLE_OPEN_MINUTE_UTC_1))
                    if trampa:
                        newly_detected_traps_1[symbol] = trampa
                        print(f"✅ {symbol}: PRIMERA Trampa M5 (13:25-13:30) detectada. High: {trampa['high']:.{mt5.symbol_info(symbol).digits}f}, Low: {trampa['low']:.{mt5.symbol_info(symbol).digits}f}")
                        send_telegram(f"✅ {symbol}: Trampa 13:25-13:30 (M5) detectada. High: {trampa['high']:.{mt5.symbol_info(symbol).digits}f}, Low: {trampa['low']:.{mt5.symbol_info(symbol).digits}f}")
                    else:
                        print(f"❌ {symbol}: No se encontró la PRIMERA vela de trampa M5 con apertura a {TRAP_M5_CANDLE_OPEN_HOUR_UTC_1}:{TRAP_M5_CANDLE_OPEN_MINUTE_UTC_1}.")
            
            global_trampas_detectadas_1 = newly_detected_traps_1 
            
            if not global_trampas_detectadas_1:
                print("No se detectaron trampas para ningún símbolo en 13:30 UTC. Esperando la siguiente ventana de detección.")
        
    # --- Lógica de Detección de la SEGUNDA Trampa (Evaluación a las 14:00 UTC) ---
    if current_hour_utc == TRAP_CANDLE_EVAL_HOUR_UTC_2 and \
       current_minute_utc == TRAP_CANDLE_EVAL_MINUTE_UTC_2:
        
        if not global_trampas_detectadas_2: 
            print(f"⏳ {now.strftime('%H:%M')}: Intentando detectar SEGUNDA vela de trampa M5 (abre {TRAP_M5_CANDLE_OPEN_HOUR_UTC_2}:{TRAP_M5_CANDLE_OPEN_MINUTE_UTC_2}, cierra {TRAP_CANDLE_EVAL_HOUR_UTC_2}:{TRAP_CANDLE_EVAL_MINUTE_UTC_2})...")
            newly_detected_traps_2 = {} 

            for symbol in SYMBOLS:
                if not operacion_hoy_ejecutada_2[symbol]: 
                    df_m5 = obtener_velas(symbol, "M5", 10) 
                    trampa = detectar_trampa(symbol, df_m5, datetime.time(TRAP_M5_CANDLE_OPEN_HOUR_UTC_2, TRAP_M5_CANDLE_OPEN_MINUTE_UTC_2))
                    if trampa:
                        newly_detected_traps_2[symbol] = trampa
                        print(f"✅ {symbol}: SEGUNDA Trampa M5 (13:55-14:00) detectada. High: {trampa['high']:.{mt5.symbol_info(symbol).digits}f}, Low: {trampa['low']:.{mt5.symbol_info(symbol).digits}f}")
                        send_telegram(f"✅ {symbol}: Trampa 13:55-14:00 (M5) detectada. High: {trampa['high']:.{mt5.symbol_info(symbol).digits}f}, Low: {trampa['low']:.{mt5.symbol_info(symbol).digits}f}")
                    else:
                        print(f"❌ {symbol}: No se encontró la SEGUNDA vela de trampa M5 con apertura a {TRAP_M5_CANDLE_OPEN_HOUR_UTC_2}:{TRAP_M5_CANDLE_OPEN_MINUTE_UTC_2}.")
            
            global_trampas_detectadas_2 = newly_detected_traps_2 
            
            if not global_trampas_detectadas_2:
                print("No se detectaron trampas para ningún símbolo en 14:00 UTC. Esperando el día siguiente.")


    # --- Lógica de Monitoreo de Ruptura y Ejecución de la Operación ---
    # Esto se verifica continuamente dentro de las ventanas de monitoreo.
# --- Evaluación y Ejecución para la PRIMERA TRAMPA (13:30 a 13:35 UTC) ---
    effective_entry_start_time_1 = now.replace(
        hour=TRADE_ENTRY_START_HOUR_UTC_1,
        minute=TRADE_ENTRY_START_MINUTE_UTC_1,
        second=0,
        microsecond=0
    )
    monitoring_end_time_1 = now.replace(
        hour=MONITORING_END_HOUR_UTC_1,
        minute=MONITORING_END_MINUTE_UTC_1,
        second=0,
        microsecond=0
    )

    if global_trampas_detectadas_1 and \
       now >= effective_entry_start_time_1 and \
       now <= monitoring_end_time_1:

        symbols_to_monitor_1 = list(global_trampas_detectadas_1.keys())

        for symbol in symbols_to_monitor_1:
            if operacion_hoy_ejecutada_1[symbol]:
                continue

            info_symbol = mt5.symbol_info(symbol)
            if info_symbol is None:
                print(f"Error: No se pudo obtener información del símbolo {symbol} para el trade.")
                continue

            # --- CAMBIO CLAVE: OBTENER TICK ACTUAL EN LUGAR DE CERRAR VELA M1 ---
            tick_info = mt5.symbol_info_tick(symbol)
            if tick_info is None:
                print(f"Advertencia: No se pudo obtener tick actual para {symbol}. Saltando monitoreo de ruptura.")
                continue

            current_bid = tick_info.bid
            current_ask = tick_info.ask
            # --- FIN CAMBIO CLAVE ---

            nivel_trampa = global_trampas_detectadas_1[symbol]
            direccion = None
            entrada = 0.0 # Inicializar
            sl = 0.0      # Inicializar
            tp = 0.0      # Inicializar
            distancia_sl_puntos = 0.0 # Inicializar

            # --- DEBUG GENERAL DE LA TRAMPA Y TICKS ---
            print(f"DEBUG {symbol} ({now.strftime('%H:%M:%S')} UTC): Bid: {current_bid:.{info_symbol.digits}f}, Ask: {current_ask:.{info_symbol.digits}f}")
            print(f"DEBUG {symbol}: Niveles de Trampa - High: {nivel_trampa['high']:.{info_symbol.digits}f}, Low: {nivel_trampa['low']:.{info_symbol.digits}f}")
            # --- FIN DEBUG GENERAL ---

            # --- Condición de Compra: Ruptura al alza (bid cruza el high de la trampa) ---
            # CAMBIO: De 'vela_anterior' y 'close/low' a 'current_bid'
            if current_bid > nivel_trampa["high"]:
                direccion = "compra"
                entrada = nivel_trampa["high"]
                calculated_sl_base = nivel_trampa["low"]

                # --- DEBUG CALCULO SL (COMPRA) ---
                print(f"DEBUG CALC. SL COMPRA: Entrada: {entrada:.{info_symbol.digits}f}, Base SL: {calculated_sl_base:.{info_symbol.digits}f}")
                # --- FIN DEBUG CALCULO SL (COMPRA) ---

                distancia_sl_base_puntos = abs(entrada - calculated_sl_base) / info_symbol.point

                if distancia_sl_base_puntos < SL_MIN_PTS:
                    sl = entrada - (SL_MIN_PTS * info_symbol.point)
                    print(f"DEBUG SL AJUSTADO (MENOR MIN): SL_FINAL: {sl:.{info_symbol.digits}f} (por {SL_MIN_PTS} pts)")
                else:
                    sl = calculated_sl_base
                    print(f"DEBUG SL NO AJUSTADO: SL_FINAL: {sl:.{info_symbol.digits}f} (Base de Trampa)")

                # Asegurar que el SL está por debajo de la entrada para compra
                if sl >= entrada:
                    sl = entrada - (SL_MIN_PTS * info_symbol.point)
                    print(f"DEBUG SL AJUSTADO (POR ENCIMA DE ENTRADA): SL_FINAL: {sl:.{info_symbol.digits}f}")

                distancia_sl_puntos = abs(entrada - sl) / info_symbol.point
                tp = entrada + (distancia_sl_puntos * info_symbol.point * RR_RATIO)

                # --- DEBUG RESULTADO FINAL SL/TP COMPRA ---
                print(f"DEBUG FINAL SL/TP COMPRA: Distancia SL Puntos: {distancia_sl_puntos:.2f}, SL: {sl:.{info_symbol.digits}f}, TP: {tp:.{info_symbol.digits}f}")
                # --- FIN DEBUG RESULTADO FINAL SL/TP COMPRA ---

            # --- Condición de Venta: Ruptura a la baja (ask cruza el low de la trampa) ---
            # CAMBIO: De 'vela_anterior' y 'close/high' a 'current_ask'
            elif current_ask < nivel_trampa["low"]:
                direccion = "venta"
                entrada = nivel_trampa["low"]
                calculated_sl_base = nivel_trampa["high"]

                # --- DEBUG CALCULO SL (VENTA) ---
                print(f"DEBUG CALC. SL VENTA: Entrada: {entrada:.{info_symbol.digits}f}, Base SL: {calculated_sl_base:.{info_symbol.digits}f}")
                # --- FIN DEBUG CALCULO SL (VENTA) ---

                distancia_sl_base_puntos = abs(entrada - calculated_sl_base) / info_symbol.point

                if distancia_sl_base_puntos < SL_MIN_PTS:
                    sl = entrada + (SL_MIN_PTS * info_symbol.point)
                    print(f"DEBUG SL AJUSTADO (MENOR MIN): SL_FINAL: {sl:.{info_symbol.digits}f} (por {SL_MIN_PTS} pts)")
                else:
                    sl = calculated_sl_base
                    print(f"DEBUG SL NO AJUSTADO: SL_FINAL: {sl:.{info_symbol.digits}f} (Base de Trampa)")

                # Asegurar que SL está por encima de la entrada para venta
                if sl <= entrada:
                    sl = entrada + (SL_MIN_PTS * info_symbol.point)
                    print(f"DEBUG SL AJUSTADO (POR DEBAJO DE ENTRADA): SL_FINAL: {sl:.{info_symbol.digits}f}")

                distancia_sl_puntos = abs(sl - entrada) / info_symbol.point
                tp = entrada - (distancia_sl_puntos * info_symbol.point * RR_RATIO)

                # --- DEBUG RESULTADO FINAL SL/TP VENTA ---
                print(f"DEBUG FINAL SL/TP VENTA: Distancia SL Puntos: {distancia_sl_puntos:.2f}, SL: {sl:.{info_symbol.digits}f}, TP: {tp:.{info_symbol.digits}f}")
                # --- FIN DEBUG RESULTADO FINAL SL/TP VENTA ---

            if direccion:
                current_equity = mt5.account_info().equity
                riesgo_dinero_estimado = current_equity * RISK_PERCENT
                volumen = calcular_volumen(symbol, distancia_sl_puntos, current_equity)

                if volumen > 0:
                    if abrir_operacion(symbol, direccion, entrada, sl, tp, volumen, riesgo_dinero_estimado):
                        operacion_hoy_ejecutada_1[symbol] = True
                        if symbol in global_trampas_detectadas_1:
                            del global_trampas_detectadas_1[symbol]
                else:
                    send_telegram(f"❌ {symbol}: Volumen calculado es 0 o negativo. No se abre operación para PRIMERA TRAMPA. Se descarta señal para hoy.")
                    print(f"❌ {symbol}: Volumen calculado es 0 o negativo. No se abre operación para PRIMERA TRAMPA. Se descarta señal para hoy.")
                    if symbol in global_trampas_detectadas_1:
                        del global_trampas_detectadas_1[symbol]
            else:
                pass # No se ha cumplido la condición de ruptura aún

        # --- Mensaje de NO OPERACIÓN al final de la ventana de la PRIMERA TRAMPA ---
        if now.hour == MONITORING_END_HOUR_UTC_1 and now.minute == MONITORING_END_MINUTE_UTC_1 and \
           not now.second > 30:
            for symbol in symbols_to_monitor_1:
                if not operacion_hoy_ejecutada_1[symbol]:
                    msg = (
                        f"⚠️ {symbol}: No se tomó operación para la PRIMERA TRAMPA (13:30 UTC).\n"
                        f"Razón: No se cumplieron las condiciones de ruptura en tiempo real dentro de la ventana de monitoreo (hasta {MONITORING_END_HOUR_UTC_1}:{MONITORING_END_MINUTE_UTC_1} UTC)."
                    )
                    send_telegram(msg)
                    print(msg)
                    operacion_hoy_ejecutada_1[symbol] = True
                    if symbol in global_trampas_detectadas_1:
                        del global_trampas_detectadas_1[symbol]

            if not global_trampas_detectadas_1 and not any(op for op in operacion_hoy_ejecutada_1.values() if op is False):
                print("✅ Todas las operaciones pendientes para la PRIMERA TRAMPA ejecutadas o descartadas por tiempo/condición para hoy.")

   # --- Evaluación y Ejecución para la SEGUNDA TRAMPA (14:00 a 14:05 UTC) ---

    effective_entry_start_time_2 = now.replace(
        hour=TRADE_ENTRY_START_HOUR_UTC_2,
        minute=TRADE_ENTRY_START_MINUTE_UTC_2,
        second=0,
        microsecond=0
    )
    monitoring_end_time_2 = now.replace(
        hour=MONITORING_END_HOUR_UTC_2,
        minute=MONITORING_END_MINUTE_UTC_2,
        second=0,
        microsecond=0
    )

    if global_trampas_detectadas_2 and \
       now >= effective_entry_start_time_2 and \
       now <= monitoring_end_time_2:

        symbols_to_monitor_2 = list(global_trampas_detectadas_2.keys())

        for symbol in symbols_to_monitor_2:
            if operacion_hoy_ejecutada_2[symbol]:
                continue

            info_symbol = mt5.symbol_info(symbol)
            if info_symbol is None:
                print(f"Error: No se pudo obtener información del símbolo {symbol} para el trade.")
                continue

            # --- CAMBIO CLAVE: OBTENER TICK ACTUAL EN LUGAR DE CERRAR VELA M1 ---
            tick_info = mt5.symbol_info_tick(symbol)
            if tick_info is None:
                print(f"Advertencia: No se pudo obtener tick actual para {symbol}. Saltando monitoreo de ruptura.")
                continue

            current_bid = tick_info.bid
            current_ask = tick_info.ask
            # --- FIN CAMBIO CLAVE ---

            nivel_trampa = global_trampas_detectadas_2[symbol]
            direccion = None
            entrada = 0.0 # Inicializar
            sl = 0.0      # Inicializar
            tp = 0.0      # Inicializar
            distancia_sl_puntos = 0.0 # Inicializar

            # --- DEBUG GENERAL DE LA TRAMPA Y TICKS ---
            print(f"DEBUG {symbol} ({now.strftime('%H:%M:%S')} UTC): Bid: {current_bid:.{info_symbol.digits}f}, Ask: {current_ask:.{info_symbol.digits}f}")
            print(f"DEBUG {symbol}: Niveles de Trampa - High: {nivel_trampa['high']:.{info_symbol.digits}f}, Low: {nivel_trampa['low']:.{info_symbol.digits}f}")
            # --- FIN DEBUG GENERAL ---

            # --- Condición de Compra: Ruptura al alza (bid cruza el high de la trampa) ---
            # CAMBIO: De 'vela_anterior' y 'close/low' a 'current_bid'
            if current_bid > nivel_trampa["high"]:
                direccion = "compra"
                entrada = nivel_trampa["high"]
                calculated_sl_base = nivel_trampa["low"]

                # --- DEBUG CALCULO SL (COMPRA) ---
                print(f"DEBUG CALC. SL COMPRA: Entrada: {entrada:.{info_symbol.digits}f}, Base SL: {calculated_sl_base:.{info_symbol.digits}f}")
                # --- FIN DEBUG CALCULO SL (COMPRA) ---

                distancia_sl_base_puntos = abs(entrada - calculated_sl_base) / info_symbol.point

                if distancia_sl_base_puntos < SL_MIN_PTS:
                    sl = entrada - (SL_MIN_PTS * info_symbol.point)
                    print(f"DEBUG SL AJUSTADO (MENOR MIN): SL_FINAL: {sl:.{info_symbol.digits}f} (por {SL_MIN_PTS} pts)")
                else:
                    sl = calculated_sl_base
                    print(f"DEBUG SL NO AJUSTADO: SL_FINAL: {sl:.{info_symbol.digits}f} (Base de Trampa)")

                # Asegurar que el SL está por debajo de la entrada para compra
                if sl >= entrada:
                    sl = entrada - (SL_MIN_PTS * info_symbol.point)
                    print(f"DEBUG SL AJUSTADO (POR ENCIMA DE ENTRADA): SL_FINAL: {sl:.{info_symbol.digits}f}")

                distancia_sl_puntos = abs(entrada - sl) / info_symbol.point
                tp = entrada + (distancia_sl_puntos * info_symbol.point * RR_RATIO)

                # --- DEBUG RESULTADO FINAL SL/TP COMPRA ---
                print(f"DEBUG FINAL SL/TP COMPRA: Distancia SL Puntos: {distancia_sl_puntos:.2f}, SL: {sl:.{info_symbol.digits}f}, TP: {tp:.{info_symbol.digits}f}")
                # --- FIN DEBUG RESULTADO FINAL SL/TP COMPRA ---

            # --- Condición de Venta: Ruptura a la baja (ask cruza el low de la trampa) ---
            # CAMBIO: De 'vela_anterior' y 'close/high' a 'current_ask'
            elif current_ask < nivel_trampa["low"]:
                direccion = "venta"
                entrada = nivel_trampa["low"]
                calculated_sl_base = nivel_trampa["high"]

                # --- DEBUG CALCULO SL (VENTA) ---
                print(f"DEBUG CALC. SL VENTA: Entrada: {entrada:.{info_symbol.digits}f}, Base SL: {calculated_sl_base:.{info_symbol.digits}f}")
                # --- FIN DEBUG CALCULO SL (VENTA) ---

                distancia_sl_base_puntos = abs(entrada - calculated_sl_base) / info_symbol.point

                if distancia_sl_base_puntos < SL_MIN_PTS:
                    sl = entrada + (SL_MIN_PTS * info_symbol.point)
                    print(f"DEBUG SL AJUSTADO (MENOR MIN): SL_FINAL: {sl:.{info_symbol.digits}f} (por {SL_MIN_PTS} pts)")
                else:
                    sl = calculated_sl_base
                    print(f"DEBUG SL NO AJUSTADO: SL_FINAL: {sl:.{info_symbol.digits}f} (Base de Trampa)")

                # Asegurar que SL está por encima de la entrada para venta
                if sl <= entrada:
                    sl = entrada + (SL_MIN_PTS * info_symbol.point)
                    print(f"DEBUG SL AJUSTADO (POR DEBAJO DE ENTRADA): SL_FINAL: {sl:.{info_symbol.digits}f}")

                distancia_sl_puntos = abs(sl - entrada) / info_symbol.point
                tp = entrada - (distancia_sl_puntos * info_symbol.point * RR_RATIO)

                # --- DEBUG RESULTADO FINAL SL/TP VENTA ---
                print(f"DEBUG FINAL SL/TP VENTA: Distancia SL Puntos: {distancia_sl_puntos:.2f}, SL: {sl:.{info_symbol.digits}f}, TP: {tp:.{info_symbol.digits}f}")
                # --- FIN DEBUG RESULTADO FINAL SL/TP VENTA ---

            if direccion:
                current_equity = mt5.account_info().equity
                riesgo_dinero_estimado = current_equity * RISK_PERCENT
                volumen = calcular_volumen(symbol, distancia_sl_puntos, current_equity)

                if volumen > 0:
                    if abrir_operacion(symbol, direccion, entrada, sl, tp, volumen, riesgo_dinero_estimado):
                        operacion_hoy_ejecutada_2[symbol] = True
                        if symbol in global_trampas_detectadas_2:
                            del global_trampas_detectadas_2[symbol]
                else:
                    send_telegram(f"❌ {symbol}: Volumen calculado es 0 o negativo. No se abre operación para SEGUNDA TRAMPA. Se descarta señal para hoy.")
                    print(f"❌ {symbol}: Volumen calculado es 0 o negativo. No se abre operación para SEGUNDA TRAMPA. Se descarta señal para hoy.")
                    if symbol in global_trampas_detectadas_2:
                        del global_trampas_detectadas_2[symbol]
            else:
                pass # No se ha cumplido la condición de ruptura aún


        # --- Mensaje de NO OPERACIÓN al final de la ventana de la SEGUNDA TRAMPA ---
        if now.hour == MONITORING_END_HOUR_UTC_2 and now.minute == MONITORING_END_MINUTE_UTC_2 and \
           not now.second > 30:
            for symbol in symbols_to_monitor_2:
                if not operacion_hoy_ejecutada_2[symbol]:
                    msg = (
                        f"⚠️ {symbol}: No se tomó operación para la SEGUNDA TRAMPA (14:00 UTC).\n"
                        f"Razón: No se cumplieron las condiciones de ruptura en tiempo real dentro de la ventana de monitoreo (hasta {MONITORING_END_HOUR_UTC_2}:{MONITORING_END_MINUTE_UTC_2} UTC)."
                    )
                    send_telegram(msg)
                    print(msg)
                    operacion_hoy_ejecutada_2[symbol] = True
                    if symbol in global_trampas_detectadas_2:
                        del global_trampas_detectadas_2[symbol]

            if not global_trampas_detectadas_2 and not any(op for op in operacion_hoy_ejecutada_2.values() if op is False):
                print("✅ Todas las operaciones pendientes para la SEGUNDA TRAMPA ejecutadas o descartadas por tiempo/condición para hoy.")


    # --- Gestión de la espera fuera de las ventanas de operación ---
    else:
        # Calcular el tiempo hasta la próxima ventana de evaluación de trampa...
        next_eval_time_1 = now.replace(
            hour=TRAP_CANDLE_EVAL_HOUR_UTC_1, 
            minute=TRAP_CANDLE_EVAL_MINUTE_UTC_1,
            second=0,
            microsecond=0
        )
        next_eval_time_2 = now.replace(
            hour=TRAP_CANDLE_EVAL_HOUR_UTC_2, 
            minute=TRAP_CANDLE_EVAL_MINUTE_UTC_2,
            second=0,
            microsecond=0
        )
        
        target_next_action_time = None

        if now < next_eval_time_1: 
            target_next_action_time = next_eval_time_1
        elif now < next_eval_time_2: 
            target_next_action_time = next_eval_time_2
        else: 
            # Si ambas ventanas de hoy ya pasaron, la próxima es la primera del día siguiente.
            target_next_action_time = next_eval_time_1 + datetime.timedelta(days=1)
            # Asegurarse de que si el día actual ya pasó las 14:05, vaya al día siguiente.
            if now.hour >= MONITORING_END_HOUR_UTC_2 and now.minute >= MONITORING_END_MINUTE_UTC_2:
                 target_next_action_time = next_eval_time_1 + datetime.timedelta(days=1)


        time_to_wait = (target_next_action_time - now).total_seconds()
        
        print(f"🕒 Esperando la próxima ventana de operación. Próxima revisión en {int(time_to_wait / 60)} minutos ({target_next_action_time.strftime('%H:%M')} UTC).")
        
        # === MODIFICACIÓN DEL SLEEP PARA MEJORAR LATENCIA ===
        if time_to_wait > 120:  # Si faltan más de 2 minutos, espera 60 segundos
            time.sleep(60)
        elif time_to_wait > 10: # Si faltan entre 10 segundos y 2 minutos, espera 5 segundos
            time.sleep(5) 
        else:                   # Si faltan 10 segundos o menos, espera 1 segundo
            time.sleep(max(1, int(time_to_wait)))
        # === FIN DE MODIFICACIÓN DEL SLEEP ===
