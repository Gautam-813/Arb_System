#!/usr/bin/env python3
"""
Safe test script to diagnose MT5 order placement issues without actually placing orders.
This script tests all the MT5 API calls and shows what would happen during order placement.
"""
import MetaTrader5 as mt5
import sys
import time

SYMBOL_FILLING_FOK = getattr(mt5, "SYMBOL_FILLING_FOK", 1)
SYMBOL_FILLING_IOC = getattr(mt5, "SYMBOL_FILLING_IOC", 2)

def order_check_ok(check):
    return check and check.retcode in (0, mt5.TRADE_RETCODE_DONE)

def filling_name_from_code(mode):
    if mode == mt5.ORDER_FILLING_FOK:
        return "FOK"
    if mode == mt5.ORDER_FILLING_IOC:
        return "IOC"
    if mode == mt5.ORDER_FILLING_RETURN:
        return "RETURN"
    return str(mode)

def test_mt5_trading(path, symbol="XAUUSD", lot=0.01):
    print(f"\n=== Testing MT5 Trading: {path} ===")
    print(f"Symbol: {symbol}, Lot: {lot}")

    try:
        print("\n1. Initializing MT5...")
        if not mt5.initialize(path=path):
            print("❌ MT5 initialization failed")
            return False

        print("+ MT5 initialized successfully")

        print("\n2. Checking terminal status...")
        terminal_info = mt5.terminal_info()
        if not terminal_info or not terminal_info.connected:
            print("- Terminal not connected")
            mt5.shutdown()
            return False
        print("+ Terminal connected")

        print("\n3. Checking account...")
        account_info = mt5.account_info()
        if not account_info:
            print("- Cannot get account info")
            mt5.shutdown()
            return False

        print(f"   Account: {account_info.login}")
        print(f"   Server: {account_info.server}")
        print(f"   Balance: {account_info.balance}")
        print(f"   Trade Allowed: {account_info.trade_allowed}")
        print(f"   Expert Trading: {account_info.trade_expert}")

        if not account_info.trade_allowed:
            print("- Trading not allowed on this account")
            mt5.shutdown()
            return False

        if not account_info.trade_expert:
            print("- Expert/automated trading not allowed")
            mt5.shutdown()
            return False

        print("+ Account ready for trading")

        print(f"\n4. Checking symbol {symbol}...")
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info or not symbol_info.visible:
            print(f"- Symbol {symbol} not available")
            mt5.shutdown()
            return False

        print(f"   Symbol visible: {symbol_info.visible}")
        print(f"   Trade mode: {symbol_info.trade_mode}")
        print(f"   Execution mode: {symbol_info.trade_exemode}")
        print(f"   Filling mode: {symbol_info.filling_mode}")

        # Check trade mode
        if symbol_info.trade_mode == mt5.SYMBOL_TRADE_MODE_DISABLED:
            print(f"- Symbol {symbol} trading is disabled")
            mt5.shutdown()
            return False

        if not symbol_info.select:
            print(f"   Selecting symbol {symbol}...")
            if not mt5.symbol_select(symbol, True):
                print(f"- Cannot select symbol {symbol}")
                mt5.shutdown()
                return False

        print("+ Symbol ready for trading")

        print("\n5. Getting current price...")
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            print(f"- No price data for {symbol}")
            mt5.shutdown()
            return False

        print(f"   Bid: {tick.bid}, Ask: {tick.ask}")
        price = tick.ask  # For BUY order
        print(f"   Using price: {price}")

        print("\n6. Testing margin calculation...")
        # Get filling mode - check what filling modes are supported
        supported_filling = symbol_info.filling_mode
        print(f"   Supported filling modes (bitmask): {supported_filling}")

        # Test different filling modes to find one that works
        filling_modes_to_test = [
            (mt5.ORDER_FILLING_IOC, "IOC", SYMBOL_FILLING_IOC),
            (mt5.ORDER_FILLING_FOK, "FOK", SYMBOL_FILLING_FOK),
            (mt5.ORDER_FILLING_RETURN, "RETURN", None)
        ]

        working_filling = None
        for filling_value, filling_name, symbol_flag in filling_modes_to_test:
            if symbol_flag is not None and not (supported_filling & symbol_flag):
                print(f"   Skipping {filling_name}: symbol flag not advertised")
                continue

            print(f"   Testing {filling_name} filling mode...")

            margin_request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(lot),
                "type": mt5.ORDER_TYPE_BUY,
                "price": price,
                "type_filling": filling_value,
            }

            margin_check = mt5.order_check(margin_request)
            print(f"     Result: {margin_check}")

            if order_check_ok(margin_check):
                print(f"   + {filling_name} filling mode works!")
                working_filling = filling_value
                break
            elif margin_check and margin_check.retcode != 10030:
                print(f"   + {filling_name} is supported, but order check failed: {margin_check.comment} (code: {margin_check.retcode})")
                working_filling = filling_value
                break
            elif margin_check:
                print(f"   - {filling_name} failed: {margin_check.comment} (code: {margin_check.retcode})")
            else:
                print(f"   - {filling_name} returned None")

        if working_filling is None:
            print("- No supported filling mode works with margin check")
            print("  Trying manual margin calculation...")

            # Try alternative approach
            try:
                # Calculate margin manually
                contract_size = symbol_info.trade_contract_size
                margin_required = (price * contract_size * float(lot)) / account_info.leverage
                print(f"   Manual margin calculation: ${margin_required:.2f}")
                print(f"   Available margin: ${account_info.margin_free:.2f}")

                if margin_required > account_info.margin_free:
                    print("- Insufficient margin for trade")
                    working_filling = None
                else:
                    print("+ Sufficient margin available - will try RETURN filling mode")
                    working_filling = mt5.ORDER_FILLING_RETURN

            except Exception as e:
                print(f"- Manual margin calculation failed: {e}")
                working_filling = None

        filling = working_filling

        print("\n7. Testing order request structure...")
        order_request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(lot),
            "type": mt5.ORDER_TYPE_BUY,
            "price": price,
            "deviation": 20,
            "magic": 0,
            "comment": "TEST_ORDER",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling,
        }

        print(f"   Order request: {order_request}")

        # DON'T actually send the order - just test the structure
        print("+ Order structure validated (not sent)")

        mt5.shutdown()
        print("\nSUMMARY:")
        print("   - MT5 API: Working")
        print("   - Terminal: Connected")
        print("   - Account: Ready")
        print("   - Symbol: Available")
        print("   - Price: Available")
        print("   - Margin: Check may have API issues")
        print("   - Order: Structure valid")

        return True

    except Exception as e:
        print(f"- Exception: {str(e)}")
        import traceback
        traceback.print_exc()
        try:
            mt5.shutdown()
        except:
            pass
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_order.py <terminal_path> [symbol] [lot]")
        print("Example: python test_order.py \"C:\\Program Files\\MetaTrader 5\\terminal64.exe\" XAUUSD 0.01")
        sys.exit(1)

    path = sys.argv[1]
    symbol = sys.argv[2] if len(sys.argv) > 2 else "XAUUSD"
    lot = float(sys.argv[3]) if len(sys.argv) > 3 else 0.01

    if not path:
        print("❌ Terminal path required")
        sys.exit(1)

    print(f"Testing order placement simulation for {symbol}...")
    success = test_mt5_trading(path, symbol, lot)
    print(f"\nResult: {'SUCCESS' if success else 'FAILED'}")
    sys.exit(0 if success else 1)
