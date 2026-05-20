//+------------------------------------------------------------------+
//|                                        simple_filling_test.mq5 |
//+------------------------------------------------------------------+
void OnStart()
  {
   Print("FILLING TEST ", Symbol());
   
   for(int mode=0; mode<=2; mode++)
     {
      MqlTradeRequest r={};
      MqlTradeResult res={};
      
      r.action = TRADE_ACTION_DEAL;
      r.symbol = Symbol();
      r.volume = 0.01;
      r.type = ORDER_TYPE_BUY;
      r.price = Ask;
      r.deviation = 10;
      r.type_filling = (ENUM_ORDER_TYPE_FILLING)mode;
      
      OrderCheck(r,res);
      Print("Mode ", mode, ": code=", res.retcode, " '", res.comment, "'");
     }
  }

