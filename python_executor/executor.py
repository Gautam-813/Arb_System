# python_executor/executor.py
import MetaTrader5 as mt5
import socket
import concurrent.futures
import psutil
import os
from pathlib import Path

SYMBOL_FILLING_FOK = getattr(mt5, "SYMBOL_FILLING_FOK", 1)
SYMBOL_FILLING_IOC = getattr(mt5, "SYMBOL_FILLING_IOC", 2)
APP_ROOT = Path(__file__).resolve().parents[1]
CORE_PORT_FILE = APP_ROOT / "arb_core_port.txt"
DEFAULT_CORE_PORT = 5555
MAX_CORE_PORT = 5600

def get_open_mt5_terminals():
    terminals = []
    for proc in psutil.process_iter(['pid', 'name', 'exe']):
        if 'terminal64' in proc.info['name'].lower() or 'terminal' in proc.info['name'].lower():
            if 'MetaTrader' in proc.info['exe']:
                terminals.append(proc.info['exe'])
    return list(set(terminals))

def get_core_port():
    try:
        value = CORE_PORT_FILE.read_text(encoding="utf-8").strip()
        port = int(value)
        if 1 <= port <= 65535:
            return port
    except Exception:
        pass
    return DEFAULT_CORE_PORT

def get_core_ports():
    ports = []
    for port in [get_core_port(), DEFAULT_CORE_PORT, *range(DEFAULT_CORE_PORT + 1, MAX_CORE_PORT + 1)]:
        if port not in ports:
            ports.append(port)
    return ports

def connect_core_socket(timeout=5.0):
    last_error = None
    for port in get_core_ports():
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            s.connect(("127.0.0.1", port))
            s.settimeout(None)
            return s, "127.0.0.1", port
        except OSError as e:
            last_error = e
            s.close()
    raise last_error or ConnectionRefusedError("No Rust core port available")

def select_terminals():
    terminals = get_open_mt5_terminals()
    if not terminals:
        print("No MT5 terminals found!")
        exit()

    print("\n=== OPEN MT5 TERMINALS ===")
    for i, t in enumerate(terminals):
        print(f"[{i}] {t}")

    master_idx = int(input("\nSelect MASTER terminal index: "))
    slave_idx = int(input("Select SLAVE terminal index: "))

    return terminals[master_idx], terminals[slave_idx]

def select_min_hold_minutes():
    print("\n=== MIN HOLD TIMER (for exit condition) ===")
    print("Select minimum hold time before exit condition is checked:")
    for i in range(7):
        print(f"[{i}] {i} minutes (0 = disabled)")
    return int(input("Select min hold minutes (0-6): "))

def filling_name(mode):
    if mode == mt5.ORDER_FILLING_FOK:
        return "FOK"
    if mode == mt5.ORDER_FILLING_IOC:
        return "IOC"
    if mode == mt5.ORDER_FILLING_RETURN:
        return "RETURN"
    return str(mode)

def filling_candidates(symbol_info):
    flags = getattr(symbol_info, "filling_mode", 0) if symbol_info else 0
    candidates = []

    def add(mode):
        if mode not in candidates:
            candidates.append(mode)

    if flags & SYMBOL_FILLING_IOC:
        add(mt5.ORDER_FILLING_IOC)
    if flags & SYMBOL_FILLING_FOK:
        add(mt5.ORDER_FILLING_FOK)

    add(mt5.ORDER_FILLING_RETURN)
    add(mt5.ORDER_FILLING_IOC)
    add(mt5.ORDER_FILLING_FOK)
    return candidates

def resolve_filling_mode(symbol_info, request):
    failures = []
    for filling in filling_candidates(symbol_info):
        check_request = dict(request)
        check_request["type_filling"] = filling
        check = mt5.order_check(check_request)

        if order_check_ok(check):
            return filling, check, failures
        if check and check.retcode != 10030:
            return filling, check, failures

        if check:
            failures.append(f"{filling_name(filling)}={check.retcode} {check.comment}")
        else:
            failures.append(f"{filling_name(filling)}=no order_check result")

    return None, None, failures

def order_check_ok(check):
    return check and check.retcode in (0, mt5.TRADE_RETCODE_DONE)

import time
from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime, timedelta

MAX_RETRIES = 3
RETRY_DELAY = 0.1  # 100ms between retries

@dataclass
class TradeState:
    master_order_id: int
    slave_order_id: Optional[int]
    entry_time: datetime
    master_type: int  # ORDER_TYPE_BUY or SELL
    min_hold_minutes: int = 0
    position_closed: bool = False

trade_state: Optional[TradeState] = None

def place_order_with_retry(terminal_path, order_type, symbol="EURUSD", lot=0.1, attempts=MAX_RETRIES):
    last_result = None
    for attempt in range(1, attempts + 1):
        result = place_order(terminal_path, order_type, symbol, lot)
        if result is not None and hasattr(result, 'retcode') and result.retcode == mt5.TRADE_RETCODE_DONE:
            print(f"Order succeeded on attempt {attempt}/{attempts}")
            return result, attempt
        last_result = result
        if attempt < attempts and (result is None or not hasattr(result, 'retcode') or result.retcode not in (10018,)):
            time.sleep(RETRY_DELAY)
    return last_result, attempts

def place_order(terminal_path, order_type, symbol="EURUSD", lot=0.1):
    if not mt5.initialize(path=terminal_path):
        return {"error": "MT5 initialization failed", "retcode": -1}

    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        mt5.shutdown()
        return {"error": f"No tick data for {symbol}", "retcode": -2}

    price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid

    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        mt5.shutdown()
        return {"error": f"Symbol {symbol} not found", "retcode": -3}

    request_base = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": order_type,
"price": price,
        "deviation": 5,
        "magic": 0,
        "comment": "martingale",
        "type_time": mt5.ORDER_TIME_GTC,
    }

    filling, order_check, failures = resolve_filling_mode(symbol_info, request_base)
    if filling is None:
        mt5.shutdown()
        return {
            "error": "No supported filling mode",
            "retcode": 10030,
            "comment": "; ".join(failures),
        }
    if order_check and not order_check_ok(order_check):
        mt5.shutdown()
        return {
            "error": "Order check failed",
            "retcode": order_check.retcode,
            "comment": order_check.comment,
        }

    print(f"Using filling={filling} ({filling_name(filling)}) for {symbol}")
    request = dict(request_base)
    request["type_filling"] = filling
    result = mt5.order_send(request)
    
    if result is None:
        mt5.shutdown()
        return {"error": "Order send returned None (IPC failure)", "retcode": -1000}
    
    mt5.shutdown()
    return result

def close_order(terminal_path, order_type, symbol="EURUSD", lot=0.1):
    """Close an open position by sending opposite order."""
    opposite_type = mt5.ORDER_TYPE_SELL if order_type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
    return place_order_with_retry(terminal_path, opposite_type, symbol, lot, attempts=3)

def get_spread_diff(symbol_a="EURUSD", symbol_b="EURUSD"):
    """Get the spread difference between two symbols."""
    tick_a = mt5.symbol_info_tick(symbol_a)
    tick_b = mt5.symbol_info_tick(symbol_b)
    if tick_a and tick_b:
        return tick_b.bid - tick_a.ask
    return None

def check_exit_condition(threshold=7.0):
    """Check if exit condition (diff < threshold) is met."""
    diff = get_spread_diff()
    return diff is not None and abs(diff) < threshold, diff

def close_position(terminal_path, order_id, symbol="EURUSD"):
    """Close a position by order ID."""
    positions = mt5.positions_get()
    for pos in positions:
        if pos.ticket == order_id:
            opposite_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
            result, _ = place_order_with_retry(terminal_path, opposite_type, symbol, pos.volume)
            return is_order_success((result, 0))
    return False

def get_result_order_id(result):
    res = result[0] if isinstance(result, tuple) else result
    return getattr(res, 'order', None) if hasattr(res, 'order') else None

def is_order_success(result):
    res = result[0] if isinstance(result, tuple) else result
    return res is not None and hasattr(res, 'retcode') and res.retcode == mt5.TRADE_RETCODE_DONE

def listen_and_execute(master_path, slave_path, min_hold_minutes=0):
    global trade_state
    s, host, port = connect_core_socket()
    print(f"Connected to Rust core on {host}:{port}. Waiting for signals...")

    while True:
        try:
            s.settimeout(1.0)
            signal = s.recv(1024).decode().strip()
            print(f"Signal: {signal}")

            if trade_state and not trade_state.position_closed:
                continue

            if signal == "BUY_A_SELL_B":
                master_result, master_attempt = place_order_with_retry(master_path, mt5.ORDER_TYPE_BUY)
                if is_order_success((master_result, master_attempt)):
                    order_id = getattr(master_result, 'order', 'N/A')
                    print(f"Master BUY verified #{order_id}")
                    trade_state = TradeState(
                        master_order_id=order_id,
                        slave_order_id=None,
                        entry_time=datetime.now(),
                        master_type=mt5.ORDER_TYPE_BUY,
                        min_hold_minutes=min_hold_minutes
                    )
                    slave_result, slave_attempt = place_order_with_retry(slave_path, mt5.ORDER_TYPE_SELL)
                    if is_order_success((slave_result, slave_attempt)):
                        slave_id = getattr(slave_result, 'order', 'N/A')
                        print(f"Slave SELL verified #{slave_id}")
                        print("Pair fully open and protected")
                        trade_state.slave_order_id = slave_id
                    else:
                        print(f"Slave FAILED: {slave_result} -> closing master")
                        close_order(master_path, mt5.ORDER_TYPE_BUY)
                        print("Master closed, flat confirmed")
                else:
                    print(f"Master FAILED: {master_result}")

            elif signal == "SELL_A_BUY_B":
                master_result, master_attempt = place_order_with_retry(master_path, mt5.ORDER_TYPE_SELL)
                if is_order_success((master_result, master_attempt)):
                    order_id = getattr(master_result, 'order', 'N/A')
                    print(f"Master SELL verified #{order_id}")
                    trade_state = TradeState(
                        master_order_id=order_id,
                        slave_order_id=None,
                        entry_time=datetime.now(),
                        master_type=mt5.ORDER_TYPE_SELL,
                        min_hold_minutes=min_hold_minutes
                    )
                    slave_result, slave_attempt = place_order_with_retry(slave_path, mt5.ORDER_TYPE_BUY)
                    if is_order_success((slave_result, slave_attempt)):
                        slave_id = getattr(slave_result, 'order', 'N/A')
                        print(f"Slave BUY verified #{slave_id}")
                        print("Pair fully open and protected")
                        trade_state.slave_order_id = slave_id
                    else:
                        print(f"Slave FAILED: {slave_result} -> closing master")
                        close_order(master_path, mt5.ORDER_TYPE_SELL)
                        print("Master closed, flat confirmed")
                else:
                    print(f"Master FAILED: {master_result}")
        except socket.timeout:
            pass

        if trade_state and not trade_state.position_closed:
            if trade_state.min_hold_minutes > 0:
                elapsed = datetime.now() - trade_state.entry_time
                if elapsed >= timedelta(minutes=trade_state.min_hold_minutes):
                    should_exit, diff = check_exit_condition(threshold=7.0)
                    if should_exit:
                        print(f"Exit condition met: diff={diff:.5f} < 7.0 -> closing both")
                        close_position(master_path, trade_state.master_order_id)
                        if trade_state.slave_order_id:
                            close_position(slave_path, trade_state.slave_order_id)
                        trade_state.position_closed = True
                        print("Position closed, flat confirmed")

if __name__ == "__main__":
    master, slave = select_terminals()
    min_hold = select_min_hold_minutes()
    print(f"\nMaster: {master}")
    print(f"Slave:  {slave}")
    print(f"Min hold timer: {min_hold} minutes")
    listen_and_execute(master, slave, min_hold)
