//+------------------------------------------------------------------+
//|                                           final_filling_test.mq5 |
//+------------------------------------------------------------------+
void OnStart()
  {
   Print("=== SIMPLE FILLING TEST: ", Symbol());
   
   double ask = SymbolInfoDouble(Symbol(), SYMBOL_ASK);
   
   for(int mode = 0; mode <= 2; mode++)
     {
      MqlTradeRequest req;
      MqlTradeResult result;
      
      ZeroMemory(req);
      ZeroMemory(result);
      
      req.action = TRADE_ACTION_DEAL;
      req.symbol = Symbol();
      req.volume = 0.01;
      req.type = ORDER_TYPE_BUY;
      req.price = ask;
      req.deviation = 20;
      req.type_filling = (ENUM_ORDER_TYPE_FILLING)mode;
      
      if(OrderCheck(req,result))
         Print("MODE ", mode, " OK: code=", result.retcode);
      else
         Print("MODE ", mode, " FAIL: code=", result.retcode, " ", result.comment);
     }
  }

