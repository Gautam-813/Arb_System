#!/usr/bin/env python3
import MetaTrader5 as mt5
import sys
import os

SYMBOL_FILLING_FOK = getattr(mt5, "SYMBOL_FILLING_FOK", 1)
SYMBOL_FILLING_IOC = getattr(mt5, "SYMBOL_FILLING_IOC", 2)

def order_check_ok(check):
    return check and check.retcode in (0, mt5.TRADE_RETCODE_DONE)

def test_mt5(path, symbol="EURUSD"):
    print(f"\n=== Testing MT5: {path} ===")

    try:
        print("1. Initializing MT5...")
        if not mt5.initialize(path=path):
            print("- MT5 initialization failed")
            return False

        print("2. Checking terminal info...")
        terminal_info = mt5.terminal_info()
        if not terminal_info:
            print("- Cannot get terminal info")
            mt5.shutdown()
            return False

        print(f"   Connected: {terminal_info.connected}")
        print(f"   Company: {terminal_info.company}")
        print(f"   Name: {terminal_info.name}")

        print("3. Checking account info...")
        account_info = mt5.account_info()
        if not account_info:
            print("- Cannot get account info")
            mt5.shutdown()
            return False

        print(f"   Login: {account_info.login}")
        print(f"   Balance: {account_info.balance}")
        print(f"   Trade allowed: {account_info.trade_allowed}")
        print(f"   Margin free: {account_info.margin_free}")

        print(f"4. Checking symbol {symbol}...")
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            print(f"- Symbol {symbol} not found")
            print("  Available symbols (first 10):")
            symbols = mt5.symbols_get()
            if symbols:
                for i, s in enumerate(symbols[:10]):
                    print(f"    {i+1}. {s.name}")
            mt5.shutdown()
            return False

        print(f"   Visible: {symbol_info.visible}")
        print(f"   Select: {symbol_info.select}")

        if not symbol_info.select:
            print("   Trying to select symbol...")
            if not mt5.symbol_select(symbol, True):
                print(f"- Cannot select symbol {symbol}")
                mt5.shutdown()
                return False

        print("5. Getting tick data...")
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            print(f"- No tick data for {symbol}")
            mt5.shutdown()
            return False

        print(f"   Ask: {tick.ask}, Bid: {tick.bid}")

        print("6. Checking filling modes...")
        symbol_info = mt5.symbol_info(symbol)
        filling_modes = symbol_info.filling_mode
        print(f"   Supported filling modes: {filling_modes}")

        # Test different filling modes
        filling_modes_to_test = [
            (mt5.ORDER_FILLING_IOC, "IOC", SYMBOL_FILLING_IOC),
            (mt5.ORDER_FILLING_FOK, "FOK", SYMBOL_FILLING_FOK),
            (mt5.ORDER_FILLING_RETURN, "RETURN", None)
        ]

        working_filling = None
        for filling_code, filling_name, symbol_flag in filling_modes_to_test:
            if symbol_flag is not None and not (filling_modes & symbol_flag):
                print(f"   Skipping {filling_name}: symbol flag not advertised")
                continue

            print(f"   Testing {filling_name}...")
            margin_check = mt5.order_check({
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": 0.01,
                "type": mt5.ORDER_TYPE_BUY,
                "price": tick.ask,
                "type_filling": filling_code,
            })

            if order_check_ok(margin_check):
                print(f"   + {filling_name} works!")
                working_filling = filling_code
                break
            elif margin_check and margin_check.retcode != 10030:
                print(f"   + {filling_name} is supported, but order check failed: {margin_check.comment} (code: {margin_check.retcode})")
                working_filling = filling_code
                break
            else:
                print(f"   - {filling_name} failed: {margin_check.comment if margin_check else 'None'}")

        if working_filling is None:
            print("   - No working filling mode found")
        else:
            print(f"   + Using filling mode: {working_filling}")

        mt5.shutdown()
        print("+ All basic checks passed")
        return True

    except Exception as e:
        print(f"- Exception: {str(e)}")
        try:
            mt5.shutdown()
        except:
            pass
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_mt5.py <terminal_path> [symbol]")
        sys.exit(1)

    path = sys.argv[1]
    symbol = sys.argv[2] if len(sys.argv) > 2 else "EURUSD"

    if not os.path.exists(path):
        print(f"❌ Terminal path does not exist: {path}")
        sys.exit(1)

    success = test_mt5(path, symbol)
    sys.exit(0 if success else 1)
