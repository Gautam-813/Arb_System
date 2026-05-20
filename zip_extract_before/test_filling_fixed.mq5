//+------------------------------------------------------------------+
//|                                            test_filling_fixed.mq5 |
//|                                  Copyright 2024, BLACKBOXAI     |
//|                                             https://www.mql5.com |
//+------------------------------------------------------------------+
#property copyright "BLACKBOXAI"
#property version   "1.00"

int OnInit()
  {
   Print("=== FILLING MODE TEST for ", _Symbol);
   
   // Test all filling modes with order_check
   MqlTradeRequest req={};
   MqlTradeResult result={};
   
   req.action = TRADE_ACTION_DEAL;
   req.symbol = _Symbol;
   req.volume = 0.01;
   req.type = ORDER_TYPE_BUY;
   req.price = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   req.deviation = 20;
   req.magic = 12345;
   req.comment = "TEST";
   
   Print("\n=== ORDER_CHECK RESULTS ===");
   
   // FOK (1)
   req.type_filling = ORDER_FILLING_FOK;
   if(OrderCheck(req,result))
      Print("FOK(1): OK - code=", result.retcode);
   else
      Print("FOK(1): FAIL - code=", result.retcode, " ", result.comment);
   
   // IOC (2)
   req.type_filling = ORDER_FILLING_IOC;
   if(OrderCheck(req,result))
      Print("IOC(2): OK - code=", result.retcode);
   else
      Print("IOC(2): FAIL - code=", result.retcode, " ", result.comment);
   
   // RETURN (0)
   req.type_filling = ORDER_FILLING_RETURN;
   if(OrderCheck(req,result))
      Print("RETURN(0): OK - code=", result.retcode);
   else
      Print("RETURN(0): FAIL - code=", result.retcode, " ", result.comment);
   
   Print("\nSymbol filling_mode: ", (int)SymbolInfoInteger(_Symbol,SYMBOL_FILLING_MODE));
   Print("Attach to GC_M26 → Copy EXPERT tab → Paste!");
   
   return(INIT_SUCCEEDED);
  }

void OnTick() {}

