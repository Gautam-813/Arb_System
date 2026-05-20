//+------------------------------------------------------------------+
//|                                               gc_m26_filling.mq5 |
//|                                  Copyright 2024, BLACKBOXAI     |
//+------------------------------------------------------------------+
#property copyright "BLACKBOXAI"
#property version   "1.00"

void OnInit()
  {
   Print("=== GC_M26 FILLING TEST ===");
   
   int filling = (int)SymbolInfoInteger(_Symbol, SYMBOL_FILLING_MODE);
   Print("SYMBOL_FILLING_MODE: ", filling);
   
   // Test FOK=1
   Print("Testing FOK(1)...");
   MqlTradeRequest req;
   MqlTradeResult res;
   ZeroMemory(req);
   ZeroMemory(res);
   req.action = TRADE_ACTION_DEAL;
   req.symbol = _Symbol;
   req.volume = 0.01;
   req.type = ORDER_TYPE_BUY;
   req.price = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   req.deviation = 20;
   req.magic = 234567;
   req.type_filling = (ENUM_ORDER_TYPE_FILLING)1;  // FOK
   
   bool ok = OrderCheck(req, res);
   Print("FOK(1): ok=", ok, " retcode=", res.retcode, " '", res.comment, "'");
   
   // Test IOC=2
   req.type_filling = (ENUM_ORDER_TYPE_FILLING)2;  // IOC
   ok = OrderCheck(req, res);
   Print("IOC(2): ok=", ok, " retcode=", res.retcode, " '", res.comment, "'");
   
   // Test RETURN=0
   req.type_filling = (ENUM_ORDER_TYPE_FILLING)0;  // RETURN
   ok = OrderCheck(req, res);
   Print("RETURN(0): ok=", ok, " retcode=", res.retcode, " '", res.comment, "'");
   
   Print("\nCopy EXPERT tab → Paste to AI!");
  }

void OnTick() {}
void OnDeinit(const int r) { Print("Removed"); }

