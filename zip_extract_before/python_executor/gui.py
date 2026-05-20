import tkinter as tk
from tkinter import ttk
import MetaTrader5 as mt5
import psutil
import socket
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
import subprocess
import os
import sys

SYMBOL_FILLING_FOK = getattr(mt5, "SYMBOL_FILLING_FOK", 1)
SYMBOL_FILLING_IOC = getattr(mt5, "SYMBOL_FILLING_IOC", 2)
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
CORE_PORT_FILE = APP_DIR / "arb_core_port.txt"
DEFAULT_CORE_PORT = 5555
MAX_CORE_PORT = 5600

# ── Globals ──────────────────────────────────────────
master_path = ""
slave_path  = ""
running     = False
master_ticket = None
slave_ticket  = None
PAIR_MAGIC_BASE = 86000000

# ── Colors ───────────────────────────────────────────
BG      = "#0a0e1a"
BG2     = "#0f1425"
BG3     = "#151c30"
CARD    = "#111827"
BORDER  = "#1e2d45"
ACCENT  = "#00d4ff"
ACCENT2 = "#0099cc"
GREEN   = "#00ff88"
RED     = "#ff3366"
YELLOW  = "#ffcc00"
TEXT    = "#e2e8f0"
TEXT2   = "#8899aa"
TEXT3   = "#4a5568"

# ── Helpers ───────────────────────────────────────────
def get_terminals():
    terminals = []
    for proc in psutil.process_iter(['name', 'exe']):
        try:
            if 'terminal64' in proc.info['name'].lower():
                if proc.info['exe'] and ('MetaTrader' in proc.info['exe'] or 'MT' in proc.info['exe']):
                    terminals.append(proc.info['exe'])
        except:
            pass
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

def connect_core_socket(connect_timeout=5.0, read_timeout=None):
    last_error = None
    for port in get_core_ports():
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(connect_timeout)
        try:
            s.connect(("127.0.0.1", port))
            if read_timeout is not None:
                s.settimeout(read_timeout)
            return s, "127.0.0.1", port
        except OSError as e:
            last_error = e
            s.close()
    raise last_error or ConnectionRefusedError("No Rust core port available")

def get_symbols(path):
    try:
        mt5.initialize(path=path)
        symbols = [s.name for s in mt5.symbols_get() if s.visible]
        mt5.shutdown()
        return sorted(symbols)
    except:
        mt5.shutdown()
        return []

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

    # The symbol flags and order filling enum values are different things.
    # Try modes advertised by the broker first, then probe safe fallbacks.
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

def get_filling_mode(path, symbol):
    try:
        mt5.initialize(path=path)
        info = mt5.symbol_info(symbol)
        mt5.shutdown()
        candidates = filling_candidates(info)
        return candidates[0] if candidates else mt5.ORDER_FILLING_IOC
    except:
        mt5.shutdown()
        return mt5.ORDER_FILLING_IOC

def get_spread(path, symbol):
    try:
        mt5.initialize(path=path)
        tick = mt5.symbol_info_tick(symbol)
        info = mt5.symbol_info(symbol)
        spread = round((tick.ask - tick.bid) / info.point)
        mt5.shutdown()
        return spread
    except:
        mt5.shutdown()
        return 9999

def is_position_open(path, ticket):
    try:
        mt5.initialize(path=path)
        positions = mt5.positions_get()
        tickets = [p.ticket for p in positions] if positions else []
        mt5.shutdown()
        return ticket in tickets
    except:
        mt5.shutdown()
        return False

def current_position_ticket(symbol, ticket=None, magic=None, comment=None):
    if ticket:
        positions = mt5.positions_get(ticket=ticket)
        if positions:
            return positions[0].ticket

    positions = mt5.positions_get(symbol=symbol)
    if not positions:
        return None

    matches = []
    for position in positions:
        if magic is not None and getattr(position, "magic", None) != magic:
            continue
        if comment and not str(getattr(position, "comment", "")).startswith(comment):
            continue
        matches.append(position)

    if matches:
        return matches[-1].ticket
    return None

def wait_for_position_ticket(symbol, ticket=None, magic=None, comment=None, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        position_ticket = current_position_ticket(symbol, ticket=ticket, magic=magic, comment=comment)
        if position_ticket:
            return position_ticket
        time.sleep(0.2)
    return current_position_ticket(symbol, ticket=ticket, magic=magic, comment=comment)

def current_position_is_open(ticket):
    positions = mt5.positions_get(ticket=ticket)
    return bool(positions)

def wait_until_position_closed(ticket, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not current_position_is_open(ticket):
            return True
        time.sleep(0.2)
    return not current_position_is_open(ticket)

def place_order(path, symbol, order_type, lot, magic=0, comment=""):
    try:
        # Initialize MT5
        if not mt5.initialize(path=path):
            return {"error": "MT5 initialization failed", "retcode": -1, "comment": "Cannot connect to terminal"}

        # Check if terminal is connected
        terminal_info = mt5.terminal_info()
        if not terminal_info or not terminal_info.connected:
            mt5.shutdown()
            return {"error": "Terminal not connected", "retcode": -2, "comment": "No connection to broker"}

        # Check account info
        account_info = mt5.account_info()
        if not account_info:
            mt5.shutdown()
            return {"error": "No account info", "retcode": -3, "comment": "Cannot get account information"}

        # Check if trading is allowed
        if not account_info.trade_allowed:
            mt5.shutdown()
            return {"error": "Trading not allowed", "retcode": -4, "comment": "Trading disabled on account"}

        if not account_info.trade_expert:
            mt5.shutdown()
            return {"error": "Expert trading not allowed", "retcode": -5, "comment": "Automated trading disabled on account"}

        # Get symbol info
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            mt5.shutdown()
            return {"error": "No symbol data", "retcode": -5, "comment": f"No tick data for {symbol}"}

        # Check if symbol is tradable
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info or not symbol_info.visible:
            mt5.shutdown()
            return {"error": "Symbol not available", "retcode": -6, "comment": f"{symbol} not visible"}

        # Check if symbol supports market orders
        if symbol_info.trade_mode == mt5.SYMBOL_TRADE_MODE_DISABLED:
            mt5.shutdown()
            return {"error": "Symbol trading disabled", "retcode": -8, "comment": f"{symbol} trading is disabled"}

        if not symbol_info.select:
            select_result = mt5.symbol_select(symbol, True)
            if not select_result:
                mt5.shutdown()
                return {"error": "Cannot select symbol", "retcode": -7, "comment": f"Cannot select {symbol}"}
        
        # Verify symbol is selected
        symbol_info_verify = mt5.symbol_info(symbol)
        if not symbol_info_verify or not symbol_info_verify.select:
            mt5.shutdown()
            return {"error": "Symbol not selected", "retcode": -7, "comment": f"{symbol} not selected for trading"}

        price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid
        check_base = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(lot),
            "type": order_type,
            "price": price,
            "deviation": 20,
            "magic": magic,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
        }
        filling, test_margin_check, filling_failures = resolve_filling_mode(symbol_info, check_base)
        
        if filling is None:
            contract_size = symbol_info.trade_contract_size
            margin_required = (price * contract_size * float(lot)) / account_info.leverage

            if margin_required > account_info.margin_free:
                mt5.shutdown()
                return {"error": "Insufficient margin", "retcode": -100, "comment": f"Need ${margin_required:.2f}, have ${account_info.margin_free:.2f}"}
            mt5.shutdown()
            return {
                "error": "No supported filling mode",
                "retcode": 10030,
                "comment": "; ".join(filling_failures) or "order_check rejected all filling modes",
            }

        if test_margin_check and not order_check_ok(test_margin_check):
            mt5.shutdown()
            return {
                "error": "Order check failed",
                "retcode": test_margin_check.retcode,
                "comment": test_margin_check.comment,
            }

        # Log filling mode for debugging (remove after testing)
        broker_name = path.split('\\')[-2] if '\\' in path else 'Unknown'
        print(f"DEBUG [{broker_name}]: Using filling={filling} ({filling_name(filling)}) for {symbol}")

        request = dict(check_base)
        request["type_filling"] = filling

        result = mt5.order_send(request)
        if result is None:
            last_error = mt5.last_error()
            mt5.shutdown()
            return {"error": f"Order send failed - last error: {last_error}", "retcode": -1000, "comment": "API returned None"}

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            mt5.shutdown()
            return {
                "error": "Order send failed",
                "retcode": result.retcode,
                "comment": result.comment,
                "order": getattr(result, "order", None),
                "deal": getattr(result, "deal", None),
            }

        position_ticket = wait_for_position_ticket(
            symbol,
            ticket=getattr(result, "order", None),
            magic=magic if magic else None,
            comment=comment if comment else None,
        )
        mt5.shutdown()

        if not position_ticket:
            return {
                "error": "Order sent but position not verified",
                "retcode": result.retcode,
                "comment": f"No open {symbol} position found for magic={magic}",
                "order": getattr(result, "order", None),
                "deal": getattr(result, "deal", None),
            }

        return {
            "ok": True,
            "retcode": result.retcode,
            "comment": result.comment,
            "order": getattr(result, "order", None),
            "deal": getattr(result, "deal", None),
            "ticket": position_ticket,
            "filling": filling,
        }

    except Exception as e:
        mt5.shutdown()
        return {"error": f"Exception: {str(e)}", "retcode": -999, "comment": "Unexpected error"}

def close_order(path, ticket, symbol, order_type, lot, magic=0, comment="arb_close"):
    try:
        if not mt5.initialize(path=path):
            return {"error": "MT5 initialization failed", "retcode": -1, "comment": "Cannot connect to terminal"}

        if not current_position_is_open(ticket):
            mt5.shutdown()
            return {"ok": True, "retcode": 0, "comment": "Already flat", "ticket": ticket}

        tick       = mt5.symbol_info_tick(symbol)
        symbol_info = mt5.symbol_info(symbol)
        if not tick or not symbol_info:
            mt5.shutdown()
            return {"error": "No symbol data", "retcode": -5, "comment": f"No tick/symbol data for {symbol}"}
            
        close_type = mt5.ORDER_TYPE_SELL if order_type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        price      = tick.bid if order_type == mt5.ORDER_TYPE_BUY else tick.ask
        request_base = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
            "volume":       float(lot),
            "type":         close_type,
            "position":     ticket,
            "price":        price,
            "deviation":    20,
            "magic":        magic,
            "comment":      comment,
            "type_time":    mt5.ORDER_TIME_GTC,
        }
        filling, close_check, failures = resolve_filling_mode(symbol_info, request_base)
        if filling is None:
            mt5.shutdown()
            return {"error": "No supported filling mode", "retcode": 10030, "comment": "; ".join(failures)}
        if close_check and not order_check_ok(close_check):
            mt5.shutdown()
            return {"error": "Close check failed", "retcode": close_check.retcode, "comment": close_check.comment}

        request = dict(request_base)
        request["type_filling"] = filling
        result = mt5.order_send(request)
        if result is None:
            last_error = mt5.last_error()
            mt5.shutdown()
            return {"error": f"Close send failed - last error: {last_error}", "retcode": -1000, "comment": "API returned None"}
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            mt5.shutdown()
            return {
                "error": "Close send failed",
                "retcode": result.retcode,
                "comment": result.comment,
                "order": getattr(result, "order", None),
                "deal": getattr(result, "deal", None),
                "ticket": ticket,
            }

        closed = wait_until_position_closed(ticket)
        mt5.shutdown()
        if not closed:
            return {
                "error": "Close sent but position still open",
                "retcode": result.retcode,
                "comment": result.comment,
                "order": getattr(result, "order", None),
                "deal": getattr(result, "deal", None),
                "ticket": ticket,
            }

        return {
            "ok": True,
            "retcode": result.retcode,
            "comment": result.comment,
            "order": getattr(result, "order", None),
            "deal": getattr(result, "deal", None),
            "ticket": ticket,
            "filling": filling,
        }
    except Exception as e:
        mt5.shutdown()
        return {"error": f"Exception: {str(e)}", "retcode": -999, "comment": "Unexpected close error", "ticket": ticket}

def trade_result_ok(result):
    if isinstance(result, dict):
        return bool(result.get("ok"))
    return hasattr(result, "retcode") and result.retcode == mt5.TRADE_RETCODE_DONE and hasattr(result, "order")

def trade_result_ticket(result):
    if isinstance(result, dict):
        return result.get("ticket") or result.get("order")
    return getattr(result, "order", None)

def trade_result_message(result):
    if isinstance(result, dict):
        error = result.get("error", "Order failed")
        retcode = result.get("retcode")
        comment = result.get("comment", "Unknown error")
        if result.get("ok"):
            ticket = result.get("ticket") or result.get("order")
            return f"OK code={retcode} | {comment} ticket={ticket}"
        return f"{error} code={retcode} | {comment}"
    if hasattr(result, "retcode") and hasattr(result, "comment"):
        return f"code={result.retcode} | {result.comment}"
    return f"Unknown error - {type(result)} - {result}"

def check_terminal_status(path, symbol, name):
    """Check if terminal is ready for trading"""
    issues = []

    try:
        if not mt5.initialize(path=path):
            issues.append(f"{name}: Cannot initialize MT5")
            return issues

        terminal_info = mt5.terminal_info()
        if not terminal_info:
            issues.append(f"{name}: Cannot get terminal info")
        elif not terminal_info.connected:
            issues.append(f"{name}: Not connected to broker")

        account_info = mt5.account_info()
        if not account_info:
            issues.append(f"{name}: Cannot get account info")
        else:
            if not account_info.trade_allowed:
                issues.append(f"{name}: Trading disabled on account")
            if account_info.margin_free < 100:  # Basic check
                issues.append(f"{name}: Low margin (${account_info.margin_free:.2f})")

        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            issues.append(f"{name}: Symbol {symbol} not found")
        elif not symbol_info.visible:
            issues.append(f"{name}: Symbol {symbol} not visible")
        elif not symbol_info.select:
            # Try to select it
            if not mt5.symbol_select(symbol, True):
                issues.append(f"{name}: Cannot select symbol {symbol}")

        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            issues.append(f"{name}: No tick data for {symbol}")

        mt5.shutdown()

    except Exception as e:
        issues.append(f"{name}: Exception during check - {str(e)}")
        try:
            mt5.shutdown()
        except:
            pass

    return issues

# ── App ───────────────────────────────────────────────
class ArbApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ARB SYSTEM")
        self.root.configure(bg=BG)
        self.root.geometry("980x860")
        self.root.resizable(False, False)

        self.terminals = get_terminals()

        self.master_var        = tk.StringVar()
        self.slave_var         = tk.StringVar()
        self.master_sym_var    = tk.StringVar()
        self.slave_sym_var     = tk.StringVar()
        self.master_dir_var    = tk.StringVar(value="BUY")
        self.slave_dir_var     = tk.StringVar(value="SELL")
        self.lot_var           = tk.StringVar(value="0.01")
        self.entry_diff_var    = tk.StringVar(value="10.00")
        self.exit_diff_var     = tk.StringVar(value="5.00")
        self.master_spread_var = tk.StringVar(value="500")
        self.slave_spread_var  = tk.StringVar(value="500")
        self.min_hold_var      = tk.StringVar(value="0")

        self.status_var = tk.StringVar(value="IDLE")
        self.diff_var   = tk.StringVar(value="—")
        self.m_spd_var  = tk.StringVar(value="—")
        self.s_spd_var  = tk.StringVar(value="—")
        self.m_price_var = tk.StringVar(value="—")
        self.s_price_var = tk.StringVar(value="—")

        self.live = {}
        self.active_pair = None
        self.pair_seq = 0
        self.state_lock = threading.RLock()
        self.rust_proc = None

        self._setup_style()
        self._build_ui()
        self._refresh_live()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # Start Rust core in background
        try:
            rust_path = str(APP_DIR / "arb_core.exe")
            env = os.environ.copy()
            env["ARB_CORE_PORT_FILE"] = str(CORE_PORT_FILE)
            self.rust_proc = subprocess.Popen([rust_path], cwd=str(APP_DIR), env=env, creationflags=subprocess.CREATE_NO_WINDOW)
            self.log("Started arb_core.exe in background")
        except Exception as e:
            self.log(f"Failed to start arb_core.exe: {e}")

    def _setup_style(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("Dark.TCombobox",
            fieldbackground=BG3, background=BG2,
            foreground=TEXT, bordercolor=BORDER,
            arrowcolor=ACCENT,
            selectbackground=ACCENT2,
            selectforeground="#ffffff")
        style.map("Dark.TCombobox",
            fieldbackground=[("readonly", BG3)],
            foreground=[("readonly", TEXT)],
            selectbackground=[("readonly", ACCENT2)],
            selectforeground=[("readonly", "#ffffff")])

    def _entry(self, parent, var, width=12):
        return tk.Entry(parent, textvariable=var, width=width,
                        bg=BG3, fg=TEXT, insertbackground=ACCENT,
                        relief="flat", font=("Consolas", 10),
                        highlightthickness=1,
                        highlightbackground=BORDER,
                        highlightcolor=ACCENT)

    def _combo(self, parent, values, var, width=26, cmd=None):
        c = ttk.Combobox(parent, values=values, textvariable=var,
                         width=width, style="Dark.TCombobox",
                         font=("Consolas", 9), state="readonly")
        if cmd:
            c.bind("<<ComboboxSelected>>", cmd)
        return c

    def _card(self, parent, title):
        outer = tk.Frame(parent, bg=BORDER, padx=1, pady=1)
        inner = tk.Frame(outer, bg=CARD, padx=14, pady=12)
        inner.pack(fill="both", expand=True)
        tk.Label(inner, text=title, bg=CARD, fg=ACCENT,
                 font=("Consolas", 8, "bold")).pack(anchor="w", pady=(0, 8))
        return outer, inner

    def _row(self, parent, label, var, hint=""):
        f = tk.Frame(parent, bg=CARD)
        f.pack(fill="x", pady=3)
        tk.Label(f, text=label, bg=CARD, fg=TEXT2,
                 font=("Consolas", 8), width=24, anchor="w").pack(side="left")
        self._entry(f, var, width=11).pack(side="left")
        if hint:
            tk.Label(f, text=hint, bg=CARD, fg=ACCENT,
                     font=("Consolas", 9, "bold")).pack(side="left", padx=5)

    def _build_ui(self):
        tk.Frame(self.root, bg=ACCENT, height=2).pack(fill="x")

        hf = tk.Frame(self.root, bg=BG, pady=10, padx=22)
        hf.pack(fill="x")
        tk.Label(hf, text="◈ ARB", bg=BG, fg=ACCENT,
                 font=("Consolas", 20, "bold")).pack(side="left")
        tk.Label(hf, text=" SYSTEM", bg=BG, fg=TEXT,
                 font=("Consolas", 20, "bold")).pack(side="left")
        tk.Label(hf, text="  v2.0  HEDGE ARBITRAGE ENGINE", bg=BG, fg=TEXT3,
                 font=("Consolas", 8)).pack(side="left", padx=8, pady=4)

        sb = tk.Frame(self.root, bg=BG2, pady=5, padx=22)
        sb.pack(fill="x")

        def stat(label, var, color):
            f = tk.Frame(sb, bg=BG2, padx=12)
            f.pack(side="left")
            tk.Label(f, text=label, bg=BG2, fg=TEXT3,
                     font=("Consolas", 8)).pack(side="left")
            tk.Label(f, textvariable=var, bg=BG2, fg=color,
                     font=("Consolas", 9, "bold")).pack(side="left", padx=3)

        stat("STATUS:", self.status_var, YELLOW)
        tk.Frame(sb, bg=BORDER, width=1, height=18).pack(side="left", padx=2)
        stat("PRICE DIFF:", self.diff_var, ACCENT)
        tk.Frame(sb, bg=BORDER, width=1, height=18).pack(side="left", padx=2)
        stat("M.SPREAD:", self.m_spd_var, GREEN)
        tk.Frame(sb, bg=BORDER, width=1, height=18).pack(side="left", padx=2)
        stat("S.SPREAD:", self.s_spd_var, GREEN)
        tk.Frame(sb, bg=BORDER, width=1, height=18).pack(side="left", padx=2)
        stat("M.PRICE:", self.m_price_var, ACCENT)
        tk.Frame(sb, bg=BORDER, width=1, height=18).pack(side="left", padx=2)
        stat("S.PRICE:", self.s_price_var, ACCENT)

        body = tk.Frame(self.root, bg=BG, padx=14, pady=8)
        body.pack(fill="both", expand=True)
        left  = tk.Frame(body, bg=BG)
        right = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="both", expand=True, padx=(0, 7))
        right.pack(side="left", fill="both", expand=True, padx=(7, 0))

        # 01 Terminal
        o, i = self._card(left, "01 / TERMINAL SELECTION")
        o.pack(fill="x", pady=(0, 7))
        names = [t.split("\\")[-2] + " > " + t.split("\\")[-1] for t in self.terminals]
        tk.Label(i, text="MASTER TERMINAL", bg=CARD, fg=TEXT2,
                 font=("Consolas", 8)).pack(anchor="w")
        self._combo(i, names, self.master_var, cmd=self._on_master).pack(anchor="w", pady=(2, 8))
        tk.Label(i, text="SLAVE TERMINAL", bg=CARD, fg=TEXT2,
                 font=("Consolas", 8)).pack(anchor="w")
        self._combo(i, names, self.slave_var, cmd=self._on_slave).pack(anchor="w", pady=(2, 0))

        # 02 Symbol
        o, i = self._card(left, "02 / SYMBOL SELECTION")
        o.pack(fill="x", pady=(0, 7))
        tk.Label(i, text="MASTER SYMBOL", bg=CARD, fg=TEXT2,
                 font=("Consolas", 8)).pack(anchor="w")
        self.master_sym_combo = self._combo(i, [], self.master_sym_var)
        self.master_sym_combo.pack(anchor="w", pady=(2, 8))
        tk.Label(i, text="SLAVE SYMBOL", bg=CARD, fg=TEXT2,
                 font=("Consolas", 8)).pack(anchor="w")
        self.slave_sym_combo = self._combo(i, [], self.slave_sym_var)
        self.slave_sym_combo.pack(anchor="w", pady=(2, 0))

        # 03 Trade Rules
        o, i = self._card(left, "03 / TRADE RULES")
        o.pack(fill="x", pady=(0, 7))

        self._row(i, "LOT SIZE", self.lot_var)

        # Direction selector
        df = tk.Frame(i, bg=CARD)
        df.pack(fill="x", pady=4)
        tk.Label(df, text="MASTER DIR", bg=CARD, fg=TEXT2,
                 font=("Consolas", 8), width=12, anchor="w").pack(side="left")
        self._combo(df, ["BUY", "SELL"], self.master_dir_var, width=6).pack(side="left")
        tk.Label(df, text="   SLAVE DIR", bg=CARD, fg=TEXT2,
                 font=("Consolas", 8)).pack(side="left", padx=(6, 2))
        self._combo(df, ["BUY", "SELL"], self.slave_dir_var, width=6).pack(side="left")

        self._row(i, "ENTRY DIFF  ( > )", self.entry_diff_var, hint="OPEN")
        self._row(i, "EXIT  DIFF  ( < )", self.exit_diff_var,  hint="CLOSE")
        self._row(i, "MIN HOLD (min)", self.min_hold_var, hint="0=off")

        tk.Button(i, text="⟳  APPLY SETTINGS", bg=ACCENT2, fg="#000000",
                  font=("Consolas", 8, "bold"), relief="flat",
                  padx=10, pady=4, cursor="hand2",
                  activebackground=ACCENT,
                  command=self._apply_settings).pack(anchor="w", pady=(10, 0))

        # 04 Spread
        o, i = self._card(right, "04 / SPREAD FILTER")
        o.pack(fill="x", pady=(0, 7))

        def sp_row(parent, label, var):
            f = tk.Frame(parent, bg=CARD)
            f.pack(fill="x", pady=3)
            tk.Label(f, text=label, bg=CARD, fg=TEXT2,
                     font=("Consolas", 8), width=22, anchor="w").pack(side="left")
            self._entry(f, var, width=9).pack(side="left")
            tk.Label(f, text=" pts", bg=CARD, fg=TEXT3,
                     font=("Consolas", 8)).pack(side="left")

        sp_row(i, "MASTER MAX SPREAD", self.master_spread_var)
        sp_row(i, "SLAVE  MAX SPREAD", self.slave_spread_var)
        tk.Label(i, text="⚠  Both spreads checked before entry",
                 bg=CARD, fg=TEXT3, font=("Consolas", 7)).pack(anchor="w", pady=(6, 0))

        # 05 Controls
        o, i = self._card(right, "05 / CONTROLS")
        o.pack(fill="x", pady=(0, 7))
        bf = tk.Frame(i, bg=CARD)
        bf.pack(fill="x")
        self.start_btn = tk.Button(bf, text="▶  START",
            bg=GREEN, fg="#000000", font=("Consolas", 10, "bold"),
            relief="flat", padx=18, pady=7, cursor="hand2",
            activebackground="#00cc66", command=self._start)
        self.start_btn.pack(side="left", padx=(0, 8))
        self.stop_btn = tk.Button(bf, text="■  STOP",
            bg=BG3, fg=RED, font=("Consolas", 10, "bold"),
            relief="flat", padx=18, pady=7, cursor="hand2",
            activebackground=BG2, state="disabled", command=self._stop)
        self.stop_btn.pack(side="left", padx=(0, 8))
        self.emergency_btn = tk.Button(bf, text="!! CLOSE BOTH",
            bg=RED, fg="#ffffff", font=("Consolas", 9, "bold"),
            relief="flat", padx=12, pady=7, cursor="hand2",
            activebackground="#cc224f", command=self._emergency_close_both)
        self.emergency_btn.pack(side="left")

        # 06 Log
        o, i = self._card(right, "06 / SYSTEM LOG")
        o.pack(fill="both", expand=True)
        self.log_box = tk.Text(i, bg=BG, fg=GREEN,
                               font=("Consolas", 8), relief="flat",
                               state="disabled", height=14,
                               highlightthickness=0)
        self.log_box.pack(fill="both", expand=True)
        scr = tk.Scrollbar(i, command=self.log_box.yview, bg=BG3)
        self.log_box.configure(yscrollcommand=scr.set)

    def _on_master(self, event=None):
        names = [t.split("\\")[-2] + " > " + t.split("\\")[-1] for t in self.terminals]
        if self.master_var.get() in names:
            global master_path
            master_path = self.terminals[names.index(self.master_var.get())]
            self.master_sym_combo["values"] = get_symbols(master_path)
            self.log(f"Master: {master_path.split(chr(92))[-2]}")

    def _on_slave(self, event=None):
        names = [t.split("\\")[-2] + " > " + t.split("\\")[-1] for t in self.terminals]
        if self.slave_var.get() in names:
            global slave_path
            slave_path = self.terminals[names.index(self.slave_var.get())]
            self.slave_sym_combo["values"] = get_symbols(slave_path)
            self.log(f"Slave: {slave_path.split(chr(92))[-2]}")

    def _apply_settings(self):
        try:
            self.live = {
                "msym":     self.master_sym_var.get(),
                "ssym":     self.slave_sym_var.get(),
                "lot":      float(self.lot_var.get()),
                "entry_th": float(self.entry_diff_var.get()),
                "exit_th":  float(self.exit_diff_var.get()),
                "m_spd":    int(self.master_spread_var.get()),
                "s_spd":    int(self.slave_spread_var.get()),
                "min_hold": int(self.min_hold_var.get()),
                "m_dir":    mt5.ORDER_TYPE_BUY if self.master_dir_var.get() == "BUY" else mt5.ORDER_TYPE_SELL,
                "s_dir":    mt5.ORDER_TYPE_BUY if self.slave_dir_var.get()  == "BUY" else mt5.ORDER_TYPE_SELL,
            }
            self.log(f"Settings applied | Entry>{self.live['entry_th']} Exit<{self.live['exit_th']} Lot={self.live['lot']} MinHold={self.live['min_hold']}min")
        except Exception as e:
            self.log(f"Settings error: {e}")

    def log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{ts}] {msg}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _dir_name(self, order_type):
        return "BUY" if order_type == mt5.ORDER_TYPE_BUY else "SELL"

    def _next_pair_id(self):
        with self.state_lock:
            self.pair_seq += 1
            return self.pair_seq

    def _build_pair(self, cfg):
        pair_id = self._next_pair_id()
        magic = PAIR_MAGIC_BASE + pair_id
        return {
            "id": pair_id,
            "magic": magic,
            "status": "OPENING",
            "opened_at": datetime.now().isoformat(timespec="seconds"),
            "entry_time": datetime.now(),
            "master": {
                "path": master_path,
                "symbol": cfg["msym"],
                "dir": cfg["m_dir"],
                "lot": cfg["lot"],
                "ticket": None,
                "label": "Master",
            },
            "slave": {
                "path": slave_path,
                "symbol": cfg["ssym"],
                "dir": cfg["s_dir"],
                "lot": cfg["lot"],
                "ticket": None,
                "label": "Slave",
            },
            "min_hold": cfg.get("min_hold", 0),
        }

    def _set_active_pair(self, pair):
        with self.state_lock:
            self.active_pair = pair

    def _get_active_pair(self):
        with self.state_lock:
            return self.active_pair

    def _clear_active_pair_if(self, pair):
        with self.state_lock:
            if self.active_pair is pair:
                self.active_pair = None

    def _leg_is_open(self, leg):
        ticket = leg.get("ticket")
        return bool(ticket and is_position_open(leg["path"], ticket))

    def _pair_is_flat(self, pair):
        return not self._leg_is_open(pair["master"]) and not self._leg_is_open(pair["slave"])

    def _close_leg_verified(self, pair, leg_key, reason, attempts=3):
        leg = pair[leg_key]
        ticket = leg.get("ticket")
        if not ticket:
            return True

        if not self._leg_is_open(leg):
            self.log(f"Pair {pair['id']} {leg['label']} already flat")
            return True

        for attempt in range(1, attempts + 1):
            self.log(f"Pair {pair['id']} closing {leg['label']} #{ticket} ({reason}) attempt {attempt}/{attempts}")
            result = close_order(
                leg["path"],
                ticket,
                leg["symbol"],
                leg["dir"],
                leg["lot"],
                magic=pair["magic"],
                comment="martingale_close",
            )

            if trade_result_ok(result) and not self._leg_is_open(leg):
                self.log(f"Pair {pair['id']} {leg['label']} close verified #{ticket}")
                return True

            self.log(f"Pair {pair['id']} {leg['label']} close not confirmed: {trade_result_message(result)}")
            time.sleep(0.7)

        return not self._leg_is_open(leg)

    def _close_pair_verified(self, pair, reason, clear_on_success=True):
        if not pair:
            return True

        with self.state_lock:
            pair["status"] = "CLOSING"

        self.status_var.set("CLOSING")
        master_ok = self._close_leg_verified(pair, "master", reason)
        slave_ok = self._close_leg_verified(pair, "slave", reason)
        flat = master_ok and slave_ok and self._pair_is_flat(pair)

        if flat:
            self.log(f"Pair {pair['id']} flat confirmed")
            with self.state_lock:
                pair["status"] = "CLOSED"
            if clear_on_success:
                self._clear_active_pair_if(pair)
                if running:
                    self.status_var.set("RUNNING")
                else:
                    self.status_var.set("STOPPED")
            return True

        with self.state_lock:
            pair["status"] = "CLOSE_FAILED"
        self.status_var.set("CLOSE FAILED")
        self.log(f"Pair {pair['id']} close FAILED - new entries blocked until both sides are flat")
        return False

    def _emergency_close_both(self):
        pair = self._get_active_pair()
        if not pair:
            self.log("Emergency close: no active pair recorded")
            return

        def worker():
            global running
            self.log(f"EMERGENCY CLOSE pair {pair['id']}")
            running = False
            self.stop_btn.config(state="disabled")
            self.start_btn.config(state="disabled")
            self._close_pair_verified(pair, "emergency", clear_on_success=True)
            self.start_btn.config(state="normal")

        threading.Thread(target=worker, daemon=True).start()

    def _monitor_active_pair(self, pair, diff, cfg):
        if pair.get("status") == "CLOSE_FAILED":
            if self._pair_is_flat(pair):
                self.log(f"Pair {pair['id']} recovered flat")
                self._clear_active_pair_if(pair)
                self.status_var.set("RUNNING")
            else:
                self.status_var.set("CLOSE FAILED")
            return

        m_open = self._leg_is_open(pair["master"])
        s_open = self._leg_is_open(pair["slave"])

        if not m_open and not s_open:
            self.log(f"Pair {pair['id']} both sides flat")
            self._clear_active_pair_if(pair)
            self.status_var.set("RUNNING")
            return

        if not m_open and s_open:
            self.log(f"Pair {pair['id']} master closed externally -> closing slave")
            self._close_pair_verified(pair, "master closed externally")
            return

        if not s_open and m_open:
            self.log(f"Pair {pair['id']} slave closed externally -> closing master")
            self._close_pair_verified(pair, "slave closed externally")
            return

        # Check min_hold timer before exit condition
        min_hold = pair.get("min_hold", 0)
        exit_allowed = True
        if min_hold > 0:
            elapsed = datetime.now() - pair.get("entry_time", datetime.now())
            if elapsed < timedelta(minutes=min_hold):
                exit_allowed = False
                remaining = timedelta(minutes=min_hold) - elapsed
                self.log(f"Pair {pair['id']} min_hold active - {remaining.seconds//60}s remaining")

        if exit_allowed and diff < cfg["exit_th"]:
            self.log(f"Pair {pair['id']} EXIT diff={diff:.5f} < {cfg['exit_th']} -> closing both")
            self._close_pair_verified(pair, "exit threshold")
            return

        with self.state_lock:
            pair["status"] = "OPEN"
        self.status_var.set("IN TRADE")

    def _open_pair(self, cfg, diff, master_spread, slave_spread):
        pair = self._build_pair(cfg)
        self._set_active_pair(pair)
        self.status_var.set("OPENING")
        self.log(f"Pair {pair['id']} ENTRY diff={diff:.5f} M.Spd={master_spread} S.Spd={slave_spread}")

        master_comment = "martingale"
        slave_comment = "martingale"

        m = pair["master"]
        m_result = place_order(
            m["path"],
            m["symbol"],
            m["dir"],
            m["lot"],
            magic=pair["magic"],
            comment=master_comment,
        )

        if not trade_result_ok(m_result):
            self.log(f"Pair {pair['id']} Master FAILED: {trade_result_message(m_result)}")
            self._clear_active_pair_if(pair)
            self.status_var.set("RUNNING")
            time.sleep(1.0)
            return

        m["ticket"] = trade_result_ticket(m_result)
        self.log(f"Pair {pair['id']} Master {self._dir_name(m['dir'])} verified #{m['ticket']}")

        s = pair["slave"]
        s_result = place_order(
            s["path"],
            s["symbol"],
            s["dir"],
            s["lot"],
            magic=pair["magic"],
            comment=slave_comment,
        )

        if not trade_result_ok(s_result):
            self.log(f"Pair {pair['id']} Slave FAILED: {trade_result_message(s_result)} -> closing master")
            self._close_pair_verified(pair, "slave open failed")
            time.sleep(1.0)
            return

        s["ticket"] = trade_result_ticket(s_result)
        pair["entry_time"] = datetime.now()
        with self.state_lock:
            pair["status"] = "OPEN"
        self.log(f"Pair {pair['id']} Slave {self._dir_name(s['dir'])} verified #{s['ticket']}")
        self.log(f"Pair {pair['id']} fully open and protected")
        self.status_var.set("IN TRADE")

    def _refresh_live(self):
        if master_path and slave_path:
            try:
                ms = self.master_sym_var.get()
                ss = self.slave_sym_var.get()
                if ms and ss:
                    mt5.initialize(path=master_path)
                    mt = mt5.symbol_info_tick(ms)
                    mt5.shutdown()
                    mt5.initialize(path=slave_path)
                    st = mt5.symbol_info_tick(ss)
                    mt5.shutdown()
                    if mt and st:
                        self.diff_var.set(f"{abs(mt.ask - st.bid):.5f}")
                        self.m_price_var.set(f"{mt.ask:.5f}")
                        self.s_price_var.set(f"{st.ask:.5f}")
                    else:
                        self.m_price_var.set("—")
                        self.s_price_var.set("—")
                    self.m_spd_var.set(str(get_spread(master_path, ms)))
                    self.s_spd_var.set(str(get_spread(slave_path, ss)))
            except:
                pass
        self.root.after(1000, self._refresh_live)

    def on_close(self):
        if self.rust_proc:
            self.rust_proc.terminate()
            self.rust_proc.wait()
            self.log("Terminated arb_core.exe")
        self.root.destroy()

    def _start(self):
        global running
        pair = self._get_active_pair()
        if pair and not self._pair_is_flat(pair):
            self.log(f"ERROR: Pair {pair['id']} still active - new entries blocked until flat")
            self.status_var.set(pair.get("status", "IN TRADE"))
            return
        if pair and self._pair_is_flat(pair):
            self._clear_active_pair_if(pair)

        if not master_path or not slave_path:
            self.log("ERROR: Select both terminals!")
            return
        if not self.master_sym_var.get() or not self.slave_sym_var.get():
            self.log("ERROR: Select both symbols!")
            return

        # Pre-flight checks
        self.log("Running pre-flight checks...")
        master_issues = check_terminal_status(master_path, self.master_sym_var.get(), "Master")
        slave_issues = check_terminal_status(slave_path, self.slave_sym_var.get(), "Slave")

        if master_issues:
            for issue in master_issues:
                self.log(f"PRE-CHECK: {issue}")
        if slave_issues:
            for issue in slave_issues:
                self.log(f"PRE-CHECK: {issue}")

        if master_issues or slave_issues:
            self.log("WARNING: Issues detected. Trading may fail. Check logs above.")
            # Continue anyway, but user can see the warnings

        self._apply_settings()
        running = True
        self.status_var.set("RUNNING")
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.log("Engine started.")
        threading.Thread(target=self._arb_loop, daemon=True).start()

    def _stop(self):
        global running
        pair = self._get_active_pair()
        if pair and not self._pair_is_flat(pair):
            self.log(f"STOP blocked: pair {pair['id']} is active. Use !! CLOSE BOTH to flatten first.")
            self.status_var.set("IN TRADE")
            return
        running = False
        self.status_var.set("STOPPED")
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.log("Engine stopped.")

    def _arb_loop_protected(self):
        cfg = dict(self.live)

        try:
            s, core_host, core_port = connect_core_socket(connect_timeout=5.0, read_timeout=1.0)
            self.log(f"Connected to Rust core on {core_host}:{core_port}.")
        except socket.timeout:
            self.log("ERROR: Rust core connection timeout (5s) - is it running?")
            self._stop()
            return
        except ConnectionRefusedError:
            self.log(f"ERROR: Rust core connection refused on ports {DEFAULT_CORE_PORT}-{MAX_CORE_PORT} - is it running?")
            self._stop()
            return
        except Exception as e:
            self.log(f"ERROR: Cannot connect to Rust core - {str(e)}")
            self._stop()
            return

        while running:
            if self.live:
                cfg = dict(self.live)

            try:
                try:
                    signal = s.recv(1024).decode().strip()
                except socket.timeout:
                    signal = "WATCHDOG"
                if not signal and not self._get_active_pair():
                    continue

                mt5.initialize(path=master_path)
                m_tick = mt5.symbol_info_tick(cfg["msym"])
                mt5.shutdown()
                mt5.initialize(path=slave_path)
                s_tick = mt5.symbol_info_tick(cfg["ssym"])
                mt5.shutdown()

                if not m_tick or not s_tick:
                    continue

                diff = abs(m_tick.ask - s_tick.bid)
                pair = self._get_active_pair()

                if pair:
                    self._monitor_active_pair(pair, diff, cfg)
                    continue

                if diff > cfg["entry_th"]:
                    ms = get_spread(master_path, cfg["msym"])
                    ss = get_spread(slave_path, cfg["ssym"])

                    if ms > cfg["m_spd"]:
                        self.log(f"M.Spread {ms} > {cfg['m_spd']} -> skip")
                        continue
                    if ss > cfg["s_spd"]:
                        self.log(f"S.Spread {ss} > {cfg['s_spd']} -> skip")
                        continue

                    time.sleep(0.5)
                    self._open_pair(cfg, diff, ms, ss)

            except Exception as e:
                self.log(f"ERROR: {e}")
                time.sleep(0.3)

        s.close()

    def _arb_loop(self):
        self._arb_loop_protected()

if __name__ == "__main__":
    root = tk.Tk()
    app  = ArbApp(root)
    root.mainloop()
