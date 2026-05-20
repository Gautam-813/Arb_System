#!/usr/bin/env python3
import MetaTrader5 as mt5
import sys
import os

def test_filling_mode(terminal_path, symbol):
    print(f"\n=== FILLING MODE TEST: {terminal_path} ===")
    
    if not mt5.initialize(path=terminal_path):
        print("❌ Cannot initialize MT5")
        return
    
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        print(f"❌ No tick for {symbol}")
        mt5.shutdown()
        return
    
    symbol_info = mt5.symbol_info(symbol)
    if not symbol_info:
        print(f"❌ Symbol {symbol} not found")
        mt5.shutdown()
        return
    
    print(f"Symbol: {symbol} | Ask: {tick.ask}")
    print(f"Supported flags: {symbol_info.filling_mode}")
    
    filling_modes = [
        (mt5.ORDER_FILLING_IOC, "IOC"),
        (mt5.ORDER_FILLING_FOK, "FOK"),
        (mt5.ORDER_FILLING_RETURN, "RETURN")
    ]
    
    working_mode = None
    for val, name in filling_modes:
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": 0.01,
            "type": mt5.ORDER_TYPE_BUY,
            "price": tick.ask,
            "type_filling": val
        }
        check = mt5.order_check(req)
        status = "✅ OK" if check and check.retcode == mt5.TRADE_RETCODE_DONE else f"❌ {check.retcode if check else 'None'}"
        print(f"  {name}({val}): {status}")
        if check and check.retcode == mt5.TRADE_RETCODE_DONE:
            working_mode = val
            print(f"  👉 RECOMMENDED: {name}({val})")
    
    if working_mode:
        print(f"\n🎯 BEST MODE for {symbol}: {working_mode} ({'FOK' if working_mode==1 else 'IOC' if working_mode==2 else 'RETURN'})")
    else:
        print(f"\n⚠️  NO working mode found - check symbol/account")
    
    mt5.shutdown()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python terminal_filling_test.py <terminal_path> [symbol=GC_M26]")
        sys.exit(1)
    
    path = sys.argv[1]
    symbol = sys.argv[2] if len(sys.argv) > 2 else "GC_M26"
    
    test_filling_mode(path, symbol)

