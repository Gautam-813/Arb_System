//+------------------------------------------------------------------+
//|                                                 test_filling.mq5 |
//|                                  Copyright 2024, BLACKBOXAI     |
//|                                             https://www.mql5.com |
//+------------------------------------------------------------------+
#property copyright "BLACKBOXAI"
#property link      "https://www.mql5.com"
#property version   "1.00"

#property strict

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
  {
   Print("=== FILLING MODE TEST for ", Symbol());
   
   // Get symbol info
   MqlSymbolInfo info;
   if(!SymbolInfoSymbol(Symbol(),info))
     {
      Print("ERROR: Cannot get symbol info");
      return INIT_FAILED;
     }
   
   Print("SYMBOL: ", info.name);
   Print("FILLING_MODE: ", info.filling_mode);
   Print("  SYMBOL_FILLING_FOK  = 1 (", (info.filling_mode & SYMBOL_FILLING_FOK ? "SUPPORTED" : "NOT"));
   Print("  SYMBOL_FILLING_IOC = 2 (", (info.filling_mode & SYMBOL_FILLING_IOC ? "SUPPORTED" : "NOT"));
   Print("  SYMBOL_FILLING_RETURN = 0 (", (info.filling_mode & 0 ? "SUPPORTED" : "NOT"));  // Usually 0 for RETURN
   
   // Test actual order_check for each mode
   MqlTradeRequest test_req = {};
   test_req.action = TRADE_ACTION_DEAL;
   test_req.symbol = Symbol();
   test_req.volume = 0.01;
   test_req.type = ORDER_TYPE_BUY;
   test_req.price = SymbolInfoDouble(Symbol(), SYMBOL_ASK);
   test_req.deviation = 20;
   test_req.magic = 12345;
   test_req.comment = "FILL_TEST";
   test_req.type_filling = ORDER_FILLING_FOK;  // 0=RETURN, 1=FOK, 2=IOC
   
   Print("\n=== ORDER_CHECK TEST ===");
   
   // Test FOK (1)
   test_req.type_filling = ORDER_FILLING_FOK;
   MqlTradeResult result;
   if(OrderCheck(test_req, result))
     {
      Print("FOK(1): OK - retcode=", result.retcode);
     }
   else
     {
      Print("FOK(1): FAILED - retcode=", result.retcode, " comment=", result.comment);
     }
   
   // Test IOC (2)
   test_req.type_filling = ORDER_FILLING_IOC;
   if(OrderCheck(test_req, result))
     {
      Print("IOC(2): OK - retcode=", result.retcode);
     }
   else
     {
      Print("IOC(2): FAILED - retcode=", result.retcode, " comment=", result.comment);
     }
   
   // Test RETURN (0)
   test_req.type_filling = ORDER_FILLING_RETURN;
   if(OrderCheck(test_req, result))
     {
      Print("RETURN(0): OK - retcode=", result.retcode);
     }
   else
     {
      Print("RETURN(0): FAILED - retcode=", result.retcode, " comment=", result.comment);
     }
   
   Print("\nATTACH TO GC_M26 CHART → Copy ALL output → Paste to me!");
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
//| Expert deinitialization function                                |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   Print("EA removed. reason=", reason);
  }

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
  {
   // Silent after init
  }

