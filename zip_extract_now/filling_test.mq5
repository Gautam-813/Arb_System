//+------------------------------------------------------------------+
//|                                                  filling_test.mq5 |
//|                                  Copyright 2024, BLACKBOXAI     |
//+------------------------------------------------------------------+
#property copyright "BLACKBOXAI"
#property version   "1.00"

int filling_modes[] = {1, 2, 0}; // FOK, IOC, RETURN
string mode_names[] = {"FOK", "IOC", "RETURN"};

int OnInit()
  {
   Print("=== FILLING MODE TEST: ", _Symbol);
   
   Print("\nsymbol filling_mode: ", (int)SymbolInfoInteger(_Symbol, SYMBOL_FILLING_MODE));
   
   Print("\nORDER_CHECK:");
   
   for(int i = 0; i < ArraySize(filling_modes); i++)
     {
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
      req.magic = 123456;
      req.comment = "test";
      req.type_filling = filling_modes[i];
      
      bool check_ok = OrderCheck(req, res);
      Print(mode_names[i], "(", filling_modes[i], "): check_ok=", check_ok, 
            " retcode=", res.retcode, " comment='", res.comment, "'");
     }
   
   Print("\nAttach to GC_M26 → Copy ALL → Paste!");
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason) {}
void OnTick() {}

