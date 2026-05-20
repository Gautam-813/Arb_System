#!/usr/bin/env python3
"""
Real MT5 order test. Use with caution: this places a small order and then
attempts to close it.
"""
import sys
import time

import MetaTrader5 as mt5

SYMBOL_FILLING_FOK = getattr(mt5, "SYMBOL_FILLING_FOK", 1)
SYMBOL_FILLING_IOC = getattr(mt5, "SYMBOL_FILLING_IOC", 2)


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


def send_checked_order(symbol_info, request_base):
    filling, order_check, failures = resolve_filling_mode(symbol_info, request_base)
    if filling is None:
        return None, "No supported filling mode: " + "; ".join(failures)
    if order_check and not order_check_ok(order_check):
        return None, f"Order check failed: {order_check.retcode} {order_check.comment}"

    request = dict(request_base)
    request["type_filling"] = filling
    print(f"Using filling={filling} ({filling_name(filling)})")
    return mt5.order_send(request), None


def test_real_order(path, symbol="XAUUSD", lot=0.01):
    print(f"\n=== TESTING REAL ORDER: {symbol} {lot} lots ===")
    print("WARNING: This will place a real order.")

    try:
        print("\n1. Initializing MT5...")
        if not mt5.initialize(path=path):
            print("MT5 initialization failed")
            return False

        account_info = mt5.account_info()
        if not account_info:
            print("Cannot get account info")
            mt5.shutdown()
            return False

        print(f"Account: {account_info.login}, Balance: {account_info.balance:.2f}")

        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            print(f"Symbol not found: {symbol}")
            mt5.shutdown()
            return False

        if not symbol_info.visible and not mt5.symbol_select(symbol, True):
            print(f"Cannot select symbol: {symbol}")
            mt5.shutdown()
            return False

        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            print(f"No price data for {symbol}")
            mt5.shutdown()
            return False

        print(f"Current price - Bid: {tick.bid}, Ask: {tick.ask}")
        print("\n2. Placing BUY order...")

        buy_request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(lot),
            "type": mt5.ORDER_TYPE_BUY,
            "price": tick.ask,
            "deviation": 20,
            "magic": 0,
            "comment": "TEST_BUY",
            "type_time": mt5.ORDER_TIME_GTC,
        }

        buy_result, error = send_checked_order(symbol_info, buy_request)
        if error or buy_result is None or buy_result.retcode != mt5.TRADE_RETCODE_DONE:
            print(f"BUY order failed: {error or buy_result}")
            if buy_result:
                print(f"Retcode: {buy_result.retcode}, Comment: {buy_result.comment}")
            mt5.shutdown()
            return False

        buy_ticket = buy_result.order
        print(f"BUY order placed successfully - Ticket: {buy_ticket}")

        time.sleep(2)

        print("\n3. Closing position...")
        positions = mt5.positions_get(ticket=buy_ticket)
        if not positions:
            print("Cannot find position to close")
            mt5.shutdown()
            return False

        close_tick = mt5.symbol_info_tick(symbol)
        close_request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(lot),
            "type": mt5.ORDER_TYPE_SELL,
            "position": buy_ticket,
            "price": close_tick.bid,
            "deviation": 20,
            "magic": 0,
            "comment": "TEST_CLOSE",
            "type_time": mt5.ORDER_TIME_GTC,
        }

        close_result, error = send_checked_order(symbol_info, close_request)
        if error or close_result is None or close_result.retcode != mt5.TRADE_RETCODE_DONE:
            print(f"Close order failed: {error or close_result}")
            if close_result:
                print(f"Retcode: {close_result.retcode}, Comment: {close_result.comment}")
            mt5.shutdown()
            return False

        print("Position closed successfully")
        mt5.shutdown()
        print("\nTest completed successfully.")
        return True

    except Exception as e:
        print(f"Exception: {str(e)}")
        try:
            mt5.shutdown()
        except Exception:
            pass
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_real_order.py <terminal_path> [symbol] [lot]")
        print("WARNING: This will place REAL orders.")
        sys.exit(1)

    path = sys.argv[1]
    symbol = sys.argv[2] if len(sys.argv) > 2 else "XAUUSD"
    lot = float(sys.argv[3]) if len(sys.argv) > 3 else 0.01

    print("THIS WILL PLACE REAL ORDERS.")
    response = input("Type 'yes' to proceed: ")
    if response.lower() != "yes":
        print("Test cancelled.")
        sys.exit(0)

    success = test_real_order(path, symbol, lot)
    print(f"\nResult: {'SUCCESS' if success else 'FAILED'}")
    sys.exit(0 if success else 1)
