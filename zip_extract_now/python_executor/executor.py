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
        "comment": "",
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
    mt5.shutdown()
    return result

def listen_and_execute(master_path, slave_path):
    s, host, port = connect_core_socket()
    print(f"Connected to Rust core on {host}:{port}. Waiting for signals...")

    while True:
        signal = s.recv(1024).decode().strip()
        print(f"Signal: {signal}")

        if signal == "BUY_A_SELL_B":
            with concurrent.futures.ThreadPoolExecutor() as ex:
                ex.submit(place_order, master_path, mt5.ORDER_TYPE_BUY)
                ex.submit(place_order, slave_path, mt5.ORDER_TYPE_SELL)

        elif signal == "SELL_A_BUY_B":
            with concurrent.futures.ThreadPoolExecutor() as ex:
                ex.submit(place_order, master_path, mt5.ORDER_TYPE_SELL)
                ex.submit(place_order, slave_path, mt5.ORDER_TYPE_BUY)

if __name__ == "__main__":
    master, slave = select_terminals()
    print(f"\nMaster: {master}")
    print(f"Slave:  {slave}")
    listen_and_execute(master, slave)
