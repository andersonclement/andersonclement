//+------------------------------------------------------------------+
//|                   SmartTrader_7CAS.mq5                          |
//|   Bot 7 CAS : Or + Argent + Pétrole — Exness MT5               |
//|   CAS 1:Tendance | CAS2:Scalp | CAS3:Range | CAS4:Cassure      |
//|   CAS5:SMC | CAS6:Retournement | CAS7:Fibonacci                 |
//+------------------------------------------------------------------+
#property copyright "SmartTrader 7CAS v1.1"
#property version   "1.10"
#property strict
#property description "Bot 7 CAS auto-adaptatif : Or, Argent, Petrole"

#include <Trade\Trade.mqh>
CTrade trade;

//+------------------------------------------------------------------+
//| PARAMETRES                                                       |
//+------------------------------------------------------------------+
input group "=== RISQUE ==="
input double RiskPercent      = 2.5;
input double MaxDrawdownPct   = 20.0;
input double MartingaleMulti  = 1.3;
input int    MaxMartingale    = 3;
input int    MaxSimultaneous  = 2;

input group "=== EMA ==="
input int    EMA_Fast   = 9;
input int    EMA_Slow   = 21;
input int    EMA_Mid    = 50;
input int    EMA_Long   = 200;

input group "=== RSI / STOCHRSI ==="
input int    RSI_Period     = 14;
input int    StochRSI_Per   = 14;
input double StochRSI_OB    = 0.80;
input double StochRSI_OS    = 0.20;
input double StochRSI_Block = 0.95;

input group "=== MACD / BB / ATR ==="
input int    MACD_Fast  = 12;
input int    MACD_Slow  = 26;
input int    MACD_Sig   = 9;
input int    BB_Period  = 20;
input double BB_Dev     = 2.0;
input int    ATR_Period = 14;

input group "=== ADX ==="
input int    ADX_Period = 14;
input double ADX_Trend  = 25.0;
input double ADX_Range  = 20.0;

input group "=== SMC ==="
input int    OB_Lookback  = 30;
input int    BOS_Lookback = 15;
input double FVG_MinSize  = 0.5;
input int    LZ_Lookback  = 50;
input int    SH_Lookback  = 20;
input double SH_WickRatio = 0.7;

input group "=== CAS SL/TP ==="
input double CAS1_SL = 1.5;  input double CAS1_TP = 2.5;
input double CAS2_SL = 0.8;  input double CAS2_TP = 1.2;
input double CAS3_SL = 1.0;  input double CAS3_TP = 1.5;
input double CAS4_SL = 1.5;  input double CAS4_TP = 3.0;
input double CAS5_SL = 1.5;  input double CAS5_TP = 2.5;
input double CAS6_SL = 1.0;  input double CAS6_TP = 2.0;
input double CAS7_SL = 1.5;  input double CAS7_TP = 2.5;

input group "=== HEURES GMT ==="
input int StartHour     = 8;
input int EndHour       = 22;
input int NewsBufferMin = 30;

input group "=== ACTIFS ==="
input bool TradeGold    = true;
input bool TradeSilver  = true;
input bool TradeOil     = true;

input group "=== DASHBOARD ==="
input string JsonFileName   = "smarttrader_data.json";
input string StateFileName  = "smarttrader_state.bin";
input int    PriceHistBars  = 40;

//+------------------------------------------------------------------+
//| VARIABLES GLOBALES                                               |
//+------------------------------------------------------------------+
string symbols[] = {"XAUUSDm","XAGUSDm","USOILm"};
bool   flags[]   = {true,true,true};
int    magics[]  = {111111,222222,333333};
int    TOTAL     = 3;

// Handles M15
int hEmaF[3],hEmaS[3],hEmaM[3],hEmaL[3];
int hATR[3],hRSI[3],hMACD[3],hBB[3],hADX[3];
// Handles H1
int hEmaFH1[3],hEmaSH1[3],hEmaLH1[3];
// Handles H4
int hEmaFH4[3],hEmaSH4[3];
// Handles D1
int hEmaLD1[3];
// Handles M5
int hEmaFM5[3],hEmaSM5[3],hATRM5[3];
// Handles M1
int hEmaFM1[3],hEmaSM1[3];
// StochRSI handles — cached to avoid per-tick allocation
int hStochRSI_M15[3], hStochRSI_M5[3];

double initialBalance    = 0;
int    consecutiveLosses = 0;
int    totalTrades       = 0;
int    winTrades         = 0;
int    lossTrades        = 0;
datetime lastDayReset    = 0;
datetime lastBarM15[3];
datetime lastBarH1[3];
datetime lastBarM5[3];
datetime lastBarM1[3];
bool   botActive         = true;
string lastReason        = "En attente de signal...";
string lastAction        = "";
string lastSignalType    = "ATTENTE";
string lastSignalAsset   = "—";
double lastSignalScore   = 0;
string lastCAS           = "—";
string logBuffer         = "";

// Cached regime per tick to avoid double computation
string cachedRegime[3];
bool   regimeCached[3];

// Peak equity for true drawdown
double peakEquity = 0;

// Fibonacci
double FIBO_LEVELS[] = {0.236,0.382,0.500,0.618,0.786};

//+------------------------------------------------------------------+
//| INIT                                                             |
//+------------------------------------------------------------------+
int OnInit()
{
   initialBalance=AccountInfoDouble(ACCOUNT_BALANCE);
   peakEquity=MathMax(initialBalance,AccountInfoDouble(ACCOUNT_EQUITY));
   lastDayReset=TimeCurrent();
   flags[0]=TradeGold; flags[1]=TradeSilver; flags[2]=TradeOil;

   for(int i=0;i<TOTAL;i++)
   {
      lastBarM15[i]=0; lastBarH1[i]=0; lastBarM5[i]=0; lastBarM1[i]=0;
      cachedRegime[i]="INCONNU"; regimeCached[i]=false;
      hStochRSI_M15[i]=INVALID_HANDLE; hStochRSI_M5[i]=INVALID_HANDLE;
      if(!flags[i]) continue;

      // M15
      hEmaF[i]  =iMA(symbols[i],PERIOD_M15,EMA_Fast,0,MODE_EMA,PRICE_CLOSE);
      hEmaS[i]  =iMA(symbols[i],PERIOD_M15,EMA_Slow,0,MODE_EMA,PRICE_CLOSE);
      hEmaM[i]  =iMA(symbols[i],PERIOD_M15,EMA_Mid, 0,MODE_EMA,PRICE_CLOSE);
      hEmaL[i]  =iMA(symbols[i],PERIOD_M15,EMA_Long,0,MODE_EMA,PRICE_CLOSE);
      hATR[i]   =iATR(symbols[i],PERIOD_M15,ATR_Period);
      hRSI[i]   =iRSI(symbols[i],PERIOD_M15,RSI_Period,PRICE_CLOSE);
      hMACD[i]  =iMACD(symbols[i],PERIOD_M15,MACD_Fast,MACD_Slow,MACD_Sig,PRICE_CLOSE);
      hBB[i]    =iBands(symbols[i],PERIOD_M15,BB_Period,0,BB_Dev,PRICE_CLOSE);
      hADX[i]   =iADX(symbols[i],PERIOD_M15,ADX_Period);
      // StochRSI handles — allocated once
      hStochRSI_M15[i]=iRSI(symbols[i],PERIOD_M15,StochRSI_Per,PRICE_CLOSE);
      hStochRSI_M5[i] =iRSI(symbols[i],PERIOD_M5,StochRSI_Per,PRICE_CLOSE);
      // H1
      hEmaFH1[i]=iMA(symbols[i],PERIOD_H1,EMA_Fast,0,MODE_EMA,PRICE_CLOSE);
      hEmaSH1[i]=iMA(symbols[i],PERIOD_H1,EMA_Slow,0,MODE_EMA,PRICE_CLOSE);
      hEmaLH1[i]=iMA(symbols[i],PERIOD_H1,EMA_Long,0,MODE_EMA,PRICE_CLOSE);
      // H4
      hEmaFH4[i]=iMA(symbols[i],PERIOD_H4,EMA_Fast,0,MODE_EMA,PRICE_CLOSE);
      hEmaSH4[i]=iMA(symbols[i],PERIOD_H4,EMA_Slow,0,MODE_EMA,PRICE_CLOSE);
      // D1
      hEmaLD1[i]=iMA(symbols[i],PERIOD_D1,EMA_Long,0,MODE_EMA,PRICE_CLOSE);
      // M5
      hEmaFM5[i]=iMA(symbols[i],PERIOD_M5,EMA_Fast,0,MODE_EMA,PRICE_CLOSE);
      hEmaSM5[i]=iMA(symbols[i],PERIOD_M5,EMA_Slow,0,MODE_EMA,PRICE_CLOSE);
      hATRM5[i] =iATR(symbols[i],PERIOD_M5,ATR_Period);
      // M1
      hEmaFM1[i]=iMA(symbols[i],PERIOD_M1,3,0,MODE_EMA,PRICE_CLOSE);
      hEmaSM1[i]=iMA(symbols[i],PERIOD_M1,8,0,MODE_EMA,PRICE_CLOSE);

      if(hEmaF[i]==INVALID_HANDLE||hEmaS[i]==INVALID_HANDLE||
         hEmaM[i]==INVALID_HANDLE||hEmaL[i]==INVALID_HANDLE||
         hATR[i]==INVALID_HANDLE ||hRSI[i]==INVALID_HANDLE ||
         hMACD[i]==INVALID_HANDLE||hBB[i]==INVALID_HANDLE  ||
         hADX[i]==INVALID_HANDLE ||
         hStochRSI_M15[i]==INVALID_HANDLE||hStochRSI_M5[i]==INVALID_HANDLE||
         hEmaFH1[i]==INVALID_HANDLE||hEmaSH1[i]==INVALID_HANDLE||
         hEmaFH4[i]==INVALID_HANDLE||hEmaSH4[i]==INVALID_HANDLE||
         hEmaLD1[i]==INVALID_HANDLE)
      { Print("Erreur indicateurs : ",symbols[i]); return INIT_FAILED; }
   }

   trade.SetDeviationInPoints(20);
   LoadState();
   AddLog("INFO","SmartTrader 7CAS v1.1 initialise");
   AddLog("INFO","Capital: $"+DoubleToString(initialBalance,2));
   AddLog("INFO","Actifs: XAUUSDm | XAGUSDm | USOILm");
   if(consecutiveLosses>0)
      AddLog("INFO","Etat restaure: "+IntegerToString(consecutiveLosses)+" pertes consecutives");
   WriteJSON();
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| PERSISTENCE — saves/loads consecutiveLosses across restarts      |
//+------------------------------------------------------------------+
void SaveState()
{
   int fh=FileOpen(StateFileName,FILE_WRITE|FILE_BIN|FILE_COMMON);
   if(fh==INVALID_HANDLE) return;
   FileWriteInteger(fh,consecutiveLosses);
   FileWriteInteger(fh,totalTrades);
   FileWriteInteger(fh,winTrades);
   FileWriteInteger(fh,lossTrades);
   FileWriteDouble(fh,peakEquity);
   FileClose(fh);
}

void LoadState()
{
   if(!FileIsExist(StateFileName,FILE_COMMON)) return;
   int fh=FileOpen(StateFileName,FILE_READ|FILE_BIN|FILE_COMMON);
   if(fh==INVALID_HANDLE) return;
   if(!FileIsEnding(fh)) consecutiveLosses=FileReadInteger(fh);
   if(!FileIsEnding(fh)) totalTrades=FileReadInteger(fh);
   if(!FileIsEnding(fh)) winTrades=FileReadInteger(fh);
   if(!FileIsEnding(fh)) lossTrades=FileReadInteger(fh);
   if(!FileIsEnding(fh)) peakEquity=FileReadDouble(fh);
   FileClose(fh);
   if(peakEquity<initialBalance) peakEquity=initialBalance;
}

//+------------------------------------------------------------------+
//| STOCH RSI — uses cached handles                                  |
//+------------------------------------------------------------------+
double GetStochRSI_K(int i,ENUM_TIMEFRAMES tf)
{
   int rsiH=(tf==PERIOD_M5)?hStochRSI_M5[i]:hStochRSI_M15[i];
   if(rsiH==INVALID_HANDLE) return 0.5;

   double rsiMain[];
   ArraySetAsSeries(rsiMain,true);
   if(CopyBuffer(rsiH,0,0,StochRSI_Per+1,rsiMain)<StochRSI_Per+1) return 0.5;

   double hi=rsiMain[0],lo=rsiMain[0];
   for(int k=1;k<StochRSI_Per;k++)
   {
      if(rsiMain[k]>hi) hi=rsiMain[k];
      if(rsiMain[k]<lo) lo=rsiMain[k];
   }
   if(hi==lo) return 0.5;
   return (rsiMain[0]-lo)/(hi-lo);
}

//+------------------------------------------------------------------+
//| DETECTION DU REGIME DE MARCHE (cached per tick)                  |
//+------------------------------------------------------------------+
string DetectRegime(int i)
{
   if(regimeCached[i]) return cachedRegime[i];

   double adxBuf[3]; ArraySetAsSeries(adxBuf,true);
   if(CopyBuffer(hADX[i],0,0,3,adxBuf)<3){ cachedRegime[i]="INCONNU"; regimeCached[i]=true; return cachedRegime[i]; }
   double adx=adxBuf[1];

   double ef[3],es[3],em[3],el[3];
   ArraySetAsSeries(ef,true); ArraySetAsSeries(es,true);
   ArraySetAsSeries(em,true); ArraySetAsSeries(el,true);
   if(CopyBuffer(hEmaF[i],0,0,3,ef)<3||
      CopyBuffer(hEmaS[i],0,0,3,es)<3||
      CopyBuffer(hEmaM[i],0,0,3,em)<3||
      CopyBuffer(hEmaL[i],0,0,3,el)<3)
   { cachedRegime[i]="INCONNU"; regimeCached[i]=true; return cachedRegime[i]; }

   double bbu[3],bbl[3],bbm[3];
   ArraySetAsSeries(bbu,true); ArraySetAsSeries(bbl,true); ArraySetAsSeries(bbm,true);
   if(CopyBuffer(hBB[i],1,0,3,bbu)<3||
      CopyBuffer(hBB[i],2,0,3,bbl)<3||
      CopyBuffer(hBB[i],0,0,3,bbm)<3)
   { cachedRegime[i]="INCONNU"; regimeCached[i]=true; return cachedRegime[i]; }

   double bbWidth=(bbu[1]-bbl[1])/bbm[1]*100;

   bool trendUp  = ef[1]>es[1] && es[1]>em[1] && em[1]>el[1] && adx>=ADX_Trend;
   bool trendDn  = ef[1]<es[1] && es[1]<em[1] && em[1]<el[1] && adx>=ADX_Trend;
   bool range    = adx<=ADX_Range && bbWidth<1.5;
   bool breakout = IsBullishBOS(i,PERIOD_M15)||IsBearishBOS(i,PERIOD_M15);
   bool smcSetup = IsBullishOB(i,PERIOD_M15)||IsBearishOB(i,PERIOD_M15)||
                   IsBullishCHoCH(i,PERIOD_M15)||IsBearishCHoCH(i,PERIOD_M15);
   bool reversal = GetStochRSI_K(i,PERIOD_M15)>StochRSI_Block ||
                   GetStochRSI_K(i,PERIOD_M15)<(1-StochRSI_Block);
   bool fiboZone = IsOnBullishFiboLevel(i)||IsOnBearishFiboLevel(i);

   string result;
   if(trendUp||trendDn)       result="CAS1_TENDANCE";
   else if(range)             result="CAS3_RANGE";
   else if(smcSetup)          result="CAS5_SMC";
   else if(breakout)          result="CAS4_CASSURE";
   else if(reversal)          result="CAS6_RETOURNEMENT";
   else if(fiboZone)          result="CAS7_FIBONACCI";
   else                       result="CAS2_SCALPING";

   cachedRegime[i]=result;
   regimeCached[i]=true;
   return result;
}

//+------------------------------------------------------------------+
//| TICK PRINCIPAL                                                   |
//+------------------------------------------------------------------+
void OnTick()
{
   // Invalidate regime cache each tick
   for(int i=0;i<TOTAL;i++) regimeCached[i]=false;

   // Update peak equity for true drawdown
   double eq=AccountInfoDouble(ACCOUNT_EQUITY);
   if(eq>peakEquity) peakEquity=eq;

   ResetDailyStats();
   if(!botActive){ WriteJSON(); return; }
   if(!CheckDrawdown()){ WriteJSON(); return; }
   if(!IsWithinTradingHours()){ WriteJSON(); return; }
   if(IsNewsTime()){ WriteJSON(); return; }

   for(int i=0;i<TOTAL;i++)
   { if(!flags[i]) continue; if(HasOpenPosition(i)) ManageTrailingStop(i); }

   if(CountOpenPositions()>=MaxSimultaneous){ WriteJSON(); return; }

   int    bestIdx=-1, bestSig=0;
   double bestScore=0;
   string bestCAS="—";

   for(int i=0;i<TOTAL;i++)
   {
      if(!flags[i]) continue;
      if(HasOpenPosition(i)) continue;

      string regime=DetectRegime(i);

      datetime bt=iTime(symbols[i],PERIOD_M15,0);
      if(bt==lastBarM15[i]) continue;
      lastBarM15[i]=bt;

      int sig=0; double score=0; string cas=regime;

      if(regime=="CAS1_TENDANCE")         { sig=GetCAS1(i); score=GetCAS1Score(i,sig); }
      else if(regime=="CAS2_SCALPING")    { sig=GetCAS2(i); score=55; }
      else if(regime=="CAS3_RANGE")       { sig=GetCAS3(i); score=60; }
      else if(regime=="CAS4_CASSURE")     { sig=GetCAS4(i); score=70; }
      else if(regime=="CAS5_SMC")         { sig=GetCAS5(i); score=80; }
      else if(regime=="CAS6_RETOURNEMENT"){ sig=GetCAS6(i); score=65; }
      else if(regime=="CAS7_FIBONACCI")   { sig=GetCAS7(i); score=75; }

      if(sig==0) continue;
      if(score>bestScore){ bestScore=score; bestIdx=i; bestSig=sig; bestCAS=cas; }
   }

   if(bestIdx>=0 && bestSig!=0)
   {
      lastCAS=bestCAS;
      ExecuteTrade(bestIdx,bestSig,bestCAS,bestScore);
   }

   if(bestIdx<0)
   {
      for(int i=0;i<TOTAL;i++)
      {
         if(!flags[i]) continue;
         if(HasOpenPosition(i)) continue;
         if(CountOpenPositions()>=MaxSimultaneous) break;
         datetime bt=iTime(symbols[i],PERIOD_M5,0);
         if(bt==lastBarM5[i]) continue;
         lastBarM5[i]=bt;
         int sig=GetCAS2_M5(i);
         if(sig!=0){ ExecuteTrade(i,sig,"CAS2_SCALPING_M5",55); }
      }
   }

   WriteJSON();
}

//+------------------------------------------------------------------+
//| CAS 1 : TENDANCE FORTE                                          |
//+------------------------------------------------------------------+
int GetCAS1(int i)
{
   double ef[3],es[3],em[3],el[3],mm[3],ms[3];
   ArraySetAsSeries(ef,true); ArraySetAsSeries(es,true);
   ArraySetAsSeries(em,true); ArraySetAsSeries(el,true);
   ArraySetAsSeries(mm,true); ArraySetAsSeries(ms,true);
   if(CopyBuffer(hEmaF[i],0,0,3,ef)<3) return 0;
   if(CopyBuffer(hEmaS[i],0,0,3,es)<3) return 0;
   if(CopyBuffer(hEmaM[i],0,0,3,em)<3) return 0;
   if(CopyBuffer(hEmaL[i],0,0,3,el)<3) return 0;
   if(CopyBuffer(hMACD[i],0,0,3,mm)<3) return 0;
   if(CopyBuffer(hMACD[i],1,0,3,ms)<3) return 0;

   double efh1[3],esh1[3]; ArraySetAsSeries(efh1,true); ArraySetAsSeries(esh1,true);
   if(CopyBuffer(hEmaFH1[i],0,0,3,efh1)<3) return 0;
   if(CopyBuffer(hEmaSH1[i],0,0,3,esh1)<3) return 0;

   double stochK=GetStochRSI_K(i,PERIOD_M15);
   bool pullbackBuy  = stochK<=StochRSI_OS;
   bool pullbackSell = stochK>=StochRSI_OB;

   bool tUp=ef[1]>es[1]&&es[1]>em[1]&&em[1]>el[1]&&efh1[1]>esh1[1];
   bool tDn=ef[1]<es[1]&&es[1]<em[1]&&em[1]<el[1]&&efh1[1]<esh1[1];
   bool macdBull=mm[1]>ms[1]; bool macdBear=mm[1]<ms[1];
   bool paBull=IsBullishPA(symbols[i],PERIOD_M15);
   bool paBear=IsBearishPA(symbols[i],PERIOD_M15);

   if(tUp&&pullbackBuy&&macdBull&&paBull)
   {
      lastReason="true|CAS1 : Tendance haussiere forte (EMA alignees)|"+
                 "true|ADX>25 confirme tendance|"+
                 "true|StochRSI survendu - timing BUY|"+
                 "true|MACD haussier|true|Price Action haussiere|"+
                 "true|H1 tendance haussiere confirmee";
      AddLog("BUY","CAS1 TENDANCE BUY "+symbols[i]);
      return 1;
   }
   if(tDn&&pullbackSell&&macdBear&&paBear)
   {
      lastReason="true|CAS1 : Tendance baissiere forte (EMA alignees)|"+
                 "true|ADX>25 confirme tendance|"+
                 "true|StochRSI surachete - timing SELL|"+
                 "true|MACD baissier|true|Price Action baissiere|"+
                 "true|H1 tendance baissiere confirmee";
      AddLog("SELL","CAS1 TENDANCE SELL "+symbols[i]);
      return -1;
   }
   return 0;
}

double GetCAS1Score(int i, int sig)
{
   double adxBuf[3]; ArraySetAsSeries(adxBuf,true);
   if(CopyBuffer(hADX[i],0,0,3,adxBuf)<3) return 60;
   return MathMin(40+adxBuf[1],100);
}

//+------------------------------------------------------------------+
//| CAS 2 : SCALPING RAPIDE                                         |
//+------------------------------------------------------------------+
int GetCAS2(int i)
{
   double sf[3],ss[3]; ArraySetAsSeries(sf,true); ArraySetAsSeries(ss,true);
   if(CopyBuffer(hEmaFM5[i],0,0,3,sf)<3) return 0;
   if(CopyBuffer(hEmaSM5[i],0,0,3,ss)<3) return 0;
   double efh1[3],esh1[3]; ArraySetAsSeries(efh1,true); ArraySetAsSeries(esh1,true);
   if(CopyBuffer(hEmaFH1[i],0,0,3,efh1)<3) return 0;
   if(CopyBuffer(hEmaSH1[i],0,0,3,esh1)<3) return 0;

   bool tUp=efh1[1]>esh1[1], tDn=efh1[1]<esh1[1];
   bool xUp=sf[2]<=ss[2]&&sf[1]>ss[1];
   bool xDn=sf[2]>=ss[2]&&sf[1]<ss[1];
   double stochK=GetStochRSI_K(i,PERIOD_M5);
   bool paBull=IsBullishPA(symbols[i],PERIOD_M5);
   bool paBear=IsBearishPA(symbols[i],PERIOD_M5);
   bool sh_b=IsBullishSH(i,PERIOD_M5), sh_s=IsBearishSH(i,PERIOD_M5);

   if(tUp&&xUp&&stochK<=StochRSI_OS&&paBull)
   {
      lastReason="true|CAS2 : Scalping M5 BUY|"+
                 "true|EMA croisement haussier M5|"+
                 "true|StochRSI survendu ("+DoubleToString(stochK,2)+")|"+
                 "true|Tendance H1 haussiere|"+
                 (sh_b?"true":"false")+"|Stop Hunt haussier detecte|"+
                 "true|Price Action haussiere M5";
      AddLog("BUY","CAS2 SCALP BUY "+symbols[i]);
      return 1;
   }
   if(tDn&&xDn&&stochK>=StochRSI_OB&&paBear)
   {
      lastReason="true|CAS2 : Scalping M5 SELL|"+
                 "true|EMA croisement baissier M5|"+
                 "true|StochRSI surachete ("+DoubleToString(stochK,2)+")|"+
                 "true|Tendance H1 baissiere|"+
                 (sh_s?"true":"false")+"|Stop Hunt baissier detecte|"+
                 "true|Price Action baissiere M5";
      AddLog("SELL","CAS2 SCALP SELL "+symbols[i]);
      return -1;
   }
   return 0;
}

int GetCAS2_M5(int i)
{
   double sf[3],ss[3]; ArraySetAsSeries(sf,true); ArraySetAsSeries(ss,true);
   if(CopyBuffer(hEmaFM5[i],0,0,3,sf)<3) return 0;
   if(CopyBuffer(hEmaSM5[i],0,0,3,ss)<3) return 0;
   double efh1[3],esh1[3]; ArraySetAsSeries(efh1,true); ArraySetAsSeries(esh1,true);
   if(CopyBuffer(hEmaFH1[i],0,0,3,efh1)<3) return 0;
   if(CopyBuffer(hEmaSH1[i],0,0,3,esh1)<3) return 0;
   bool tUp=efh1[1]>esh1[1], tDn=efh1[1]<esh1[1];
   bool xUp=sf[2]<=ss[2]&&sf[1]>ss[1];
   bool xDn=sf[2]>=ss[2]&&sf[1]<ss[1];
   double stochK=GetStochRSI_K(i,PERIOD_M5);
   if(tUp&&xUp&&stochK<=StochRSI_OS){ AddLog("BUY","CAS2 M5 BUY "+symbols[i]); return 1; }
   if(tDn&&xDn&&stochK>=StochRSI_OB){ AddLog("SELL","CAS2 M5 SELL "+symbols[i]); return -1; }
   return 0;
}

//+------------------------------------------------------------------+
//| CAS 3 : RANGE / CONSOLIDATION                                   |
//+------------------------------------------------------------------+
int GetCAS3(int i)
{
   double bbu[3],bbl[3],bbm[3];
   ArraySetAsSeries(bbu,true); ArraySetAsSeries(bbl,true); ArraySetAsSeries(bbm,true);
   if(CopyBuffer(hBB[i],1,0,3,bbu)<3) return 0;
   if(CopyBuffer(hBB[i],2,0,3,bbl)<3) return 0;
   if(CopyBuffer(hBB[i],0,0,3,bbm)<3) return 0;

   double ab[3]; ArraySetAsSeries(ab,true);
   if(CopyBuffer(hATR[i],0,0,3,ab)<3) return 0;

   double bid=SymbolInfoDouble(symbols[i],SYMBOL_BID);
   double stochK=GetStochRSI_K(i,PERIOD_M15);

   bool buyRange  = MathAbs(bid-bbl[1])<=ab[1]*0.8 && stochK<=StochRSI_OS;
   bool sellRange = MathAbs(bid-bbu[1])<=ab[1]*0.8 && stochK>=StochRSI_OB;

   if(buyRange)
   {
      lastReason="true|CAS3 : Range - Prix sur BB bas|"+
                 "true|ADX<20 marche consolide|"+
                 "true|StochRSI survendu ("+DoubleToString(stochK,2)+")|"+
                 "true|Achat bas du range|true|TP = milieu du range";
      AddLog("BUY","CAS3 RANGE BUY "+symbols[i]);
      return 1;
   }
   if(sellRange)
   {
      lastReason="true|CAS3 : Range - Prix sur BB haut|"+
                 "true|ADX<20 marche consolide|"+
                 "true|StochRSI surachete ("+DoubleToString(stochK,2)+")|"+
                 "true|Vente haut du range|true|TP = milieu du range";
      AddLog("SELL","CAS3 RANGE SELL "+symbols[i]);
      return -1;
   }
   return 0;
}

//+------------------------------------------------------------------+
//| CAS 4 : CASSURE DIRECTE                                         |
//+------------------------------------------------------------------+
int GetCAS4(int i)
{
   double ab[3]; ArraySetAsSeries(ab,true);
   if(CopyBuffer(hATR[i],0,0,3,ab)<3) return 0;

   double c1=iClose(symbols[i],PERIOD_M15,1);
   double o1=iOpen(symbols[i],PERIOD_M15,1);
   double bodySize=MathAbs(c1-o1);
   bool bigCandle=bodySize>ab[1]*1.5;

   bool bosBull=IsBullishBOS(i,PERIOD_M15);
   bool bosBear=IsBearishBOS(i,PERIOD_M15);

   double efh1[3],esh1[3]; ArraySetAsSeries(efh1,true); ArraySetAsSeries(esh1,true);
   if(CopyBuffer(hEmaFH1[i],0,0,3,efh1)<3) return 0;
   if(CopyBuffer(hEmaSH1[i],0,0,3,esh1)<3) return 0;
   bool h1Bull=efh1[1]>esh1[1], h1Bear=efh1[1]<esh1[1];

   if(bosBull&&bigCandle&&c1>o1&&h1Bull)
   {
      lastReason="true|CAS4 : Cassure directe haussiere|"+
                 "true|Break of Structure (BOS) confirme|"+
                 "true|Grande bougie de cassure (ATR x1.5)|"+
                 "true|H1 tendance haussiere|"+
                 "true|Entree sur momentum de cassure";
      AddLog("BUY","CAS4 CASSURE BUY "+symbols[i]);
      return 1;
   }
   if(bosBear&&bigCandle&&c1<o1&&h1Bear)
   {
      lastReason="true|CAS4 : Cassure directe baissiere|"+
                 "true|Break of Structure (BOS) confirme|"+
                 "true|Grande bougie de cassure (ATR x1.5)|"+
                 "true|H1 tendance baissiere|"+
                 "true|Entree sur momentum de cassure";
      AddLog("SELL","CAS4 CASSURE SELL "+symbols[i]);
      return -1;
   }
   return 0;
}

//+------------------------------------------------------------------+
//| CAS 5 : CASSURE INDIRECTE / SMC                                 |
//+------------------------------------------------------------------+
int GetCAS5(int i)
{
   bool ob_b=IsBullishOB(i,PERIOD_M15), ob_s=IsBearishOB(i,PERIOD_M15);
   bool choch_b=IsBullishCHoCH(i,PERIOD_M15), choch_s=IsBearishCHoCH(i,PERIOD_M15);
   bool fvg_b=IsBullishFVG(i,PERIOD_M15), fvg_s=IsBearishFVG(i,PERIOD_M15);
   bool lz_b=IsNearBullishLZ(i,PERIOD_M15), lz_s=IsNearBearishLZ(i,PERIOD_M15);
   bool sh_b=IsBullishSH(i,PERIOD_M15), sh_s=IsBearishSH(i,PERIOD_M15);
   bool paBull=IsBullishPA(symbols[i],PERIOD_M15);
   bool paBear=IsBearishPA(symbols[i],PERIOD_M15);

   double stochK=GetStochRSI_K(i,PERIOD_M15);
   double efh1[3],esh1[3]; ArraySetAsSeries(efh1,true); ArraySetAsSeries(esh1,true);
   if(CopyBuffer(hEmaFH1[i],0,0,3,efh1)<3) return 0;
   if(CopyBuffer(hEmaSH1[i],0,0,3,esh1)<3) return 0;
   bool h1Bull=efh1[1]>esh1[1], h1Bear=efh1[1]<esh1[1];

   int smcBull=(ob_b?2:0)+(choch_b?3:0)+(fvg_b?1:0)+(lz_b?2:0)+(sh_b?3:0);
   int smcBear=(ob_s?2:0)+(choch_s?3:0)+(fvg_s?1:0)+(lz_s?2:0)+(sh_s?3:0);

   if(smcBull>=3&&h1Bull&&stochK<=StochRSI_OS&&paBull)
   {
      lastReason="true|CAS5 : SMC - Cassure indirecte haussiere|"+
                 (ob_b?"true":"false")+"|Order Block haussier detecte|"+
                 (choch_b?"true":"false")+"|CHoCH haussier confirme|"+
                 (fvg_b?"true":"false")+"|Fair Value Gap present|"+
                 (lz_b?"true":"false")+"|Zone de liquidite proche|"+
                 (sh_b?"true":"false")+"|Stop Hunt haussier detecte|"+
                 "true|StochRSI survendu - timing precis|"+
                 "true|H1 confirme direction";
      AddLog("BUY","CAS5 SMC BUY "+symbols[i]+" score="+IntegerToString(smcBull));
      return 1;
   }
   if(smcBear>=3&&h1Bear&&stochK>=StochRSI_OB&&paBear)
   {
      lastReason="true|CAS5 : SMC - Cassure indirecte baissiere|"+
                 (ob_s?"true":"false")+"|Order Block baissier detecte|"+
                 (choch_s?"true":"false")+"|CHoCH baissier confirme|"+
                 (fvg_s?"true":"false")+"|Fair Value Gap present|"+
                 (lz_s?"true":"false")+"|Zone de liquidite proche|"+
                 (sh_s?"true":"false")+"|Stop Hunt baissier detecte|"+
                 "true|StochRSI surachete - timing precis|"+
                 "true|H1 confirme direction";
      AddLog("SELL","CAS5 SMC SELL "+symbols[i]+" score="+IntegerToString(smcBear));
      return -1;
   }
   return 0;
}

//+------------------------------------------------------------------+
//| CAS 6 : RETOURNEMENT                                            |
//+------------------------------------------------------------------+
int GetCAS6(int i)
{
   double stochK=GetStochRSI_K(i,PERIOD_M15);
   bool sh_b=IsBullishSH(i,PERIOD_M15), sh_s=IsBearishSH(i,PERIOD_M15);
   bool paBull=IsBullishPA(symbols[i],PERIOD_M15);
   bool paBear=IsBearishPA(symbols[i],PERIOD_M15);

   double rsi[3]; ArraySetAsSeries(rsi,true);
   if(CopyBuffer(hRSI[i],0,0,3,rsi)<3) return 0;

   bool revBull = stochK<0.10 && sh_b && rsi[1]<35 && paBull;
   bool revBear = stochK>0.90 && sh_s && rsi[1]>65 && paBear;

   if(revBull)
   {
      lastReason="true|CAS6 : Retournement haussier|"+
                 "true|StochRSI bloque bas ("+DoubleToString(stochK,2)+")|"+
                 "true|Stop Hunt haussier - piege retourne|"+
                 "true|RSI survendu ("+DoubleToString(rsi[1],1)+")|"+
                 "true|Price Action retournement confirme|"+
                 "true|Counter-trend apres piege institutionnel";
      AddLog("BUY","CAS6 RETOURNEMENT BUY "+symbols[i]);
      return 1;
   }
   if(revBear)
   {
      lastReason="true|CAS6 : Retournement baissier|"+
                 "true|StochRSI bloque haut ("+DoubleToString(stochK,2)+")|"+
                 "true|Stop Hunt baissier - piege retourne|"+
                 "true|RSI surachete ("+DoubleToString(rsi[1],1)+")|"+
                 "true|Price Action retournement confirme|"+
                 "true|Counter-trend apres piege institutionnel";
      AddLog("SELL","CAS6 RETOURNEMENT SELL "+symbols[i]);
      return -1;
   }
   return 0;
}

//+------------------------------------------------------------------+
//| CAS 7 : FIBONACCI CONFLUENCE                                    |
//+------------------------------------------------------------------+
int GetCAS7(int i)
{
   bool fibo_b=IsOnBullishFiboLevel(i);
   bool fibo_s=IsOnBearishFiboLevel(i);
   bool ob_b=IsBullishOB(i,PERIOD_M15), ob_s=IsBearishOB(i,PERIOD_M15);
   bool paBull=IsBullishPA(symbols[i],PERIOD_M15);
   bool paBear=IsBearishPA(symbols[i],PERIOD_M15);
   double stochK=GetStochRSI_K(i,PERIOD_M15);

   double efh1[3],esh1[3]; ArraySetAsSeries(efh1,true); ArraySetAsSeries(esh1,true);
   if(CopyBuffer(hEmaFH1[i],0,0,3,efh1)<3) return 0;
   if(CopyBuffer(hEmaSH1[i],0,0,3,esh1)<3) return 0;
   bool h1Bull=efh1[1]>esh1[1], h1Bear=efh1[1]<esh1[1];

   if(fibo_b&&ob_b&&stochK<=StochRSI_OS&&paBull&&h1Bull)
   {
      lastReason="true|CAS7 : Fibonacci confluence haussiere|"+
                 "true|Prix sur niveau Fibo cle (38.2/50/61.8%)|"+
                 "true|Order Block haussier sur zone Fibo|"+
                 "true|StochRSI survendu - timing optimal|"+
                 "true|Price Action confirme|"+
                 "true|H1 tendance haussiere - confluence maximale";
      AddLog("BUY","CAS7 FIBONACCI BUY "+symbols[i]);
      return 1;
   }
   if(fibo_s&&ob_s&&stochK>=StochRSI_OB&&paBear&&h1Bear)
   {
      lastReason="true|CAS7 : Fibonacci confluence baissiere|"+
                 "true|Prix sur niveau Fibo cle (38.2/50/61.8%)|"+
                 "true|Order Block baissier sur zone Fibo|"+
                 "true|StochRSI surachete - timing optimal|"+
                 "true|Price Action confirme|"+
                 "true|H1 tendance baissiere - confluence maximale";
      AddLog("SELL","CAS7 FIBONACCI SELL "+symbols[i]);
      return -1;
   }
   return 0;
}

//+------------------------------------------------------------------+
//| SMC FUNCTIONS                                                   |
//+------------------------------------------------------------------+
bool IsBullishOB(int i,ENUM_TIMEFRAMES tf){
   double c1=iClose(symbols[i],tf,1);
   for(int k=2;k<=OB_Lookback;k++){
      double o=iOpen(symbols[i],tf,k),c=iClose(symbols[i],tf,k);
      if(c<o){double nc=iClose(symbols[i],tf,k-1),no=iOpen(symbols[i],tf,k-1);
         if(nc>no&&(nc-no)>(o-c)*1.5&&c1>=c&&c1<=o) return true;}
   } return false;
}
bool IsBearishOB(int i,ENUM_TIMEFRAMES tf){
   double c1=iClose(symbols[i],tf,1);
   for(int k=2;k<=OB_Lookback;k++){
      double o=iOpen(symbols[i],tf,k),c=iClose(symbols[i],tf,k);
      if(c>o){double nc=iClose(symbols[i],tf,k-1),no=iOpen(symbols[i],tf,k-1);
         if(nc<no&&(no-nc)>(c-o)*1.5&&c1<=c&&c1>=o) return true;}
   } return false;
}
bool IsBullishBOS(int i,ENUM_TIMEFRAMES tf){
   double hMax=0;
   for(int k=2;k<=BOS_Lookback;k++) hMax=MathMax(hMax,iHigh(symbols[i],tf,k));
   return iClose(symbols[i],tf,1)>hMax;
}
bool IsBearishBOS(int i,ENUM_TIMEFRAMES tf){
   double lMin=DBL_MAX;
   for(int k=2;k<=BOS_Lookback;k++) lMin=MathMin(lMin,iLow(symbols[i],tf,k));
   return iClose(symbols[i],tf,1)<lMin;
}
bool IsBullishCHoCH(int i,ENUM_TIMEFRAMES tf){
   int llCount=0; double prevLow=iLow(symbols[i],tf,BOS_Lookback);
   for(int k=BOS_Lookback-1;k>=3;k--){
      double cl=iLow(symbols[i],tf,k);
      if(cl<prevLow) llCount++;
      prevLow=cl;
   }
   if(llCount<2) return false;
   double rh=0; for(int k=3;k<=BOS_Lookback/2;k++) rh=MathMax(rh,iHigh(symbols[i],tf,k));
   return iClose(symbols[i],tf,1)>rh;
}
bool IsBearishCHoCH(int i,ENUM_TIMEFRAMES tf){
   int hhCount=0; double prevHigh=iHigh(symbols[i],tf,BOS_Lookback);
   for(int k=BOS_Lookback-1;k>=3;k--){
      double ch=iHigh(symbols[i],tf,k);
      if(ch>prevHigh) hhCount++;
      prevHigh=ch;
   }
   if(hhCount<2) return false;
   double rl=DBL_MAX; for(int k=3;k<=BOS_Lookback/2;k++) rl=MathMin(rl,iLow(symbols[i],tf,k));
   return iClose(symbols[i],tf,1)<rl;
}
bool IsBullishFVG(int i,ENUM_TIMEFRAMES tf){
   double ab[3]; ArraySetAsSeries(ab,true);
   if(CopyBuffer(hATR[i],0,0,3,ab)<3) return false;
   double c1=iClose(symbols[i],tf,1);
   for(int k=3;k<=15;k++){
      double h1=iHigh(symbols[i],tf,k),l3=iLow(symbols[i],tf,k-2);
      if(l3-h1>ab[1]*FVG_MinSize&&c1>h1&&c1<l3) return true;
   } return false;
}
bool IsBearishFVG(int i,ENUM_TIMEFRAMES tf){
   double ab[3]; ArraySetAsSeries(ab,true);
   if(CopyBuffer(hATR[i],0,0,3,ab)<3) return false;
   double c1=iClose(symbols[i],tf,1);
   for(int k=3;k<=15;k++){
      double l1=iLow(symbols[i],tf,k),h3=iHigh(symbols[i],tf,k-2);
      if(l1-h3>ab[1]*FVG_MinSize&&c1<l1&&c1>h3) return true;
   } return false;
}
bool IsNearBullishLZ(int i,ENUM_TIMEFRAMES tf){
   double ab[3]; ArraySetAsSeries(ab,true);
   if(CopyBuffer(hATR[i],0,0,3,ab)<3) return false;
   double atr=ab[1],bid=SymbolInfoDouble(symbols[i],SYMBOL_BID);
   for(int k=2;k<=LZ_Lookback-2;k++){
      double low1=iLow(symbols[i],tf,k); int t=0;
      for(int j=k+1;j<=LZ_Lookback;j++) if(MathAbs(low1-iLow(symbols[i],tf,j))<atr*0.5) t++;
      if(t>=2&&MathAbs(bid-low1)<atr*1.5) return true;
   } return false;
}
bool IsNearBearishLZ(int i,ENUM_TIMEFRAMES tf){
   double ab[3]; ArraySetAsSeries(ab,true);
   if(CopyBuffer(hATR[i],0,0,3,ab)<3) return false;
   double atr=ab[1],bid=SymbolInfoDouble(symbols[i],SYMBOL_BID);
   for(int k=2;k<=LZ_Lookback-2;k++){
      double h1=iHigh(symbols[i],tf,k); int t=0;
      for(int j=k+1;j<=LZ_Lookback;j++) if(MathAbs(h1-iHigh(symbols[i],tf,j))<atr*0.5) t++;
      if(t>=2&&MathAbs(bid-h1)<atr*1.5) return true;
   } return false;
}
bool IsBullishSH(int i,ENUM_TIMEFRAMES tf){
   for(int k=1;k<=SH_Lookback;k++){
      double o=iOpen(symbols[i],tf,k),c=iClose(symbols[i],tf,k);
      double h=iHigh(symbols[i],tf,k),l=iLow(symbols[i],tf,k);
      if(h==l) continue;
      if((MathMin(o,c)-l)/(h-l)>SH_WickRatio&&c>o&&iClose(symbols[i],tf,1)>c) return true;
   } return false;
}
bool IsBearishSH(int i,ENUM_TIMEFRAMES tf){
   for(int k=1;k<=SH_Lookback;k++){
      double o=iOpen(symbols[i],tf,k),c=iClose(symbols[i],tf,k);
      double h=iHigh(symbols[i],tf,k),l=iLow(symbols[i],tf,k);
      if(h==l) continue;
      if((h-MathMax(o,c))/(h-l)>SH_WickRatio&&c<o&&iClose(symbols[i],tf,1)<c) return true;
   } return false;
}
bool IsBullishPA(string sym,ENUM_TIMEFRAMES tf){
   double o=iOpen(sym,tf,1),c=iClose(sym,tf,1),h=iHigh(sym,tf,1),l=iLow(sym,tf,1);
   double body=MathAbs(c-o),lw=MathMin(o,c)-l,uw=h-MathMax(o,c);
   return (c>o&&body>uw*1.5)||(lw>body*2&&c>o);
}
bool IsBearishPA(string sym,ENUM_TIMEFRAMES tf){
   double o=iOpen(sym,tf,1),c=iClose(sym,tf,1),h=iHigh(sym,tf,1),l=iLow(sym,tf,1);
   double body=MathAbs(c-o),uw=h-MathMax(o,c),lw=MathMin(o,c)-l;
   return (c<o&&body>lw*1.5)||(uw>body*2&&c<o);
}

//+------------------------------------------------------------------+
//| FIBONACCI                                                       |
//+------------------------------------------------------------------+
bool IsOnBullishFiboLevel(int i){
   double sH=0,sL=DBL_MAX;
   for(int k=1;k<=50;k++){ sH=MathMax(sH,iHigh(symbols[i],PERIOD_H1,k)); sL=MathMin(sL,iLow(symbols[i],PERIOD_H1,k)); }
   if(sH<=sL) return false;
   double bid=SymbolInfoDouble(symbols[i],SYMBOL_BID), range=sH-sL;
   double ab[3]; ArraySetAsSeries(ab,true);
   if(CopyBuffer(hATR[i],0,0,3,ab)<3) return false;
   for(int k=1;k<=3;k++){
      double lvl=sL+range*(1-FIBO_LEVELS[k]);
      if(MathAbs(bid-lvl)<=ab[1]*0.5) return true;
   } return false;
}
bool IsOnBearishFiboLevel(int i){
   double sH=0,sL=DBL_MAX;
   for(int k=1;k<=50;k++){ sH=MathMax(sH,iHigh(symbols[i],PERIOD_H1,k)); sL=MathMin(sL,iLow(symbols[i],PERIOD_H1,k)); }
   if(sH<=sL) return false;
   double bid=SymbolInfoDouble(symbols[i],SYMBOL_BID), range=sH-sL;
   double ab[3]; ArraySetAsSeries(ab,true);
   if(CopyBuffer(hATR[i],0,0,3,ab)<3) return false;
   for(int k=1;k<=3;k++){
      double lvl=sL+range*FIBO_LEVELS[k];
      if(MathAbs(bid-lvl)<=ab[1]*0.5) return true;
   } return false;
}

//+------------------------------------------------------------------+
//| EXECUTION                                                       |
//+------------------------------------------------------------------+
void ExecuteTrade(int i,int sig,string cas,double score)
{
   double ab[3]; ArraySetAsSeries(ab,true);
   if(CopyBuffer(hATR[i],0,0,3,ab)<3) return;
   double atr=ab[1];
   int dg=(int)SymbolInfoInteger(symbols[i],SYMBOL_DIGITS);
   trade.SetExpertMagicNumber(magics[i]);

   double slM=CAS1_SL, tpM=CAS1_TP;
   if(StringFind(cas,"CAS1")>=0){ slM=CAS1_SL; tpM=CAS1_TP; }
   else if(StringFind(cas,"CAS2")>=0){ slM=CAS2_SL; tpM=CAS2_TP; }
   else if(StringFind(cas,"CAS3")>=0){ slM=CAS3_SL; tpM=CAS3_TP; }
   else if(StringFind(cas,"CAS4")>=0){ slM=CAS4_SL; tpM=CAS4_TP; }
   else if(StringFind(cas,"CAS5")>=0){ slM=CAS5_SL; tpM=CAS5_TP; }
   else if(StringFind(cas,"CAS6")>=0){ slM=CAS6_SL; tpM=CAS6_TP; }
   else if(StringFind(cas,"CAS7")>=0){ slM=CAS7_SL; tpM=CAS7_TP; }

   double bal=AccountInfoDouble(ACCOUNT_BALANCE);
   double risk=bal*(RiskPercent/100.0);
   if(consecutiveLosses>0&&consecutiveLosses<=MaxMartingale)
      risk*=MathPow(MartingaleMulti,consecutiveLosses);

   if(sig==1){
      double ask=SymbolInfoDouble(symbols[i],SYMBOL_ASK);
      double sl=NormalizeDouble(ask-atr*slM,dg);
      double tp=NormalizeDouble(ask+atr*tpM,dg);
      double tv=SymbolInfoDouble(symbols[i],SYMBOL_TRADE_TICK_VALUE);
      double ts=SymbolInfoDouble(symbols[i],SYMBOL_TRADE_TICK_SIZE);
      double pv=(ts>0)?tv/ts:tv;
      double lot=risk/((ask-sl)*pv);
      double mn=SymbolInfoDouble(symbols[i],SYMBOL_VOLUME_MIN);
      double mx=SymbolInfoDouble(symbols[i],SYMBOL_VOLUME_MAX);
      double st=SymbolInfoDouble(symbols[i],SYMBOL_VOLUME_STEP);
      lot=MathMax(mn,MathMin(mx,MathRound(lot/st)*st));
      if(trade.Buy(lot,symbols[i],ask,sl,tp,cas+" BUY")){
         totalTrades++;
         lastSignalType="BUY"; lastSignalAsset=symbols[i]; lastSignalScore=score;
         lastAction="OUVERT BUY "+cas+" "+symbols[i]+
                    " lot="+DoubleToString(lot,2)+
                    " SL="+DoubleToString(sl,dg)+" TP="+DoubleToString(tp,dg)+
                    "\nScore: "+DoubleToString(score,0)+"/100";
         AddLog("BUY",lastAction);
         SaveState();
      }
   } else {
      double bid=SymbolInfoDouble(symbols[i],SYMBOL_BID);
      double sl=NormalizeDouble(bid+atr*slM,dg);
      double tp=NormalizeDouble(bid-atr*tpM,dg);
      double tv=SymbolInfoDouble(symbols[i],SYMBOL_TRADE_TICK_VALUE);
      double ts=SymbolInfoDouble(symbols[i],SYMBOL_TRADE_TICK_SIZE);
      double pv=(ts>0)?tv/ts:tv;
      double lot=risk/((sl-bid)*pv);
      double mn=SymbolInfoDouble(symbols[i],SYMBOL_VOLUME_MIN);
      double mx=SymbolInfoDouble(symbols[i],SYMBOL_VOLUME_MAX);
      double st=SymbolInfoDouble(symbols[i],SYMBOL_VOLUME_STEP);
      lot=MathMax(mn,MathMin(mx,MathRound(lot/st)*st));
      if(trade.Sell(lot,symbols[i],bid,sl,tp,cas+" SELL")){
         totalTrades++;
         lastSignalType="SELL"; lastSignalAsset=symbols[i]; lastSignalScore=score;
         lastAction="OUVERT SELL "+cas+" "+symbols[i]+
                    " lot="+DoubleToString(lot,2)+
                    " SL="+DoubleToString(sl,dg)+" TP="+DoubleToString(tp,dg)+
                    "\nScore: "+DoubleToString(score,0)+"/100";
         AddLog("SELL",lastAction);
         SaveState();
      }
   }
}

void ManageTrailingStop(int i){
   double ab[3]; ArraySetAsSeries(ab,true);
   if(CopyBuffer(hATR[i],0,0,3,ab)<3) return;
   double trail=ab[1]*CAS1_SL;
   int dg=(int)SymbolInfoInteger(symbols[i],SYMBOL_DIGITS);
   double pt=SymbolInfoDouble(symbols[i],SYMBOL_POINT);
   trade.SetExpertMagicNumber(magics[i]);
   for(int j=PositionsTotal()-1;j>=0;j--){
      ulong tk=PositionGetTicket(j);
      if(!PositionSelectByTicket(tk)) continue;
      if(PositionGetString(POSITION_SYMBOL)!=symbols[i]) continue;
      if(PositionGetInteger(POSITION_MAGIC)!=magics[i])  continue;
      double sl=PositionGetDouble(POSITION_SL),tp=PositionGetDouble(POSITION_TP);
      if(PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY){
         double nsl=NormalizeDouble(SymbolInfoDouble(symbols[i],SYMBOL_BID)-trail,dg);
         if(nsl>sl+pt*10) trade.PositionModify(tk,nsl,tp);
      } else {
         double nsl=NormalizeDouble(SymbolInfoDouble(symbols[i],SYMBOL_ASK)+trail,dg);
         if(sl==0||nsl<sl-pt*10) trade.PositionModify(tk,nsl,tp);
      }
   }
}

//+------------------------------------------------------------------+
//| UTILITAIRES                                                     |
//+------------------------------------------------------------------+
int CountOpenPositions(){
   int count=0;
   for(int j=PositionsTotal()-1;j>=0;j--){
      ulong tk=PositionGetTicket(j);
      if(!PositionSelectByTicket(tk)) continue;
      for(int i=0;i<TOTAL;i++){
         if(PositionGetString(POSITION_SYMBOL)==symbols[i]&&
            PositionGetInteger(POSITION_MAGIC)==magics[i]){ count++; break; }
      }
   }
   return count;
}
bool HasOpenPosition(int i){
   for(int j=PositionsTotal()-1;j>=0;j--){
      ulong tk=PositionGetTicket(j);
      if(PositionSelectByTicket(tk))
         if(PositionGetString(POSITION_SYMBOL)==symbols[i]&&
            PositionGetInteger(POSITION_MAGIC)==magics[i]) return true;
   } return false;
}
bool CheckDrawdown(){
   double eq=AccountInfoDouble(ACCOUNT_EQUITY);
   if(peakEquity<=0) return true;
   double dd=((peakEquity-eq)/peakEquity)*100;
   if(dd>=MaxDrawdownPct){botActive=false;AddLog("WARN","DRAWDOWN MAX (equity)");SaveState();return false;}
   return true;
}
bool IsWithinTradingHours(){MqlDateTime t;TimeToStruct(TimeGMT(),t);return(t.hour>=StartHour&&t.hour<EndHour);}
bool IsNewsTime(){
   MqlDateTime t;TimeToStruct(TimeGMT(),t);
   int m=t.hour*60+t.min,nt[]={510,720,840};
   for(int i=0;i<3;i++) if(MathAbs(m-nt[i])<=NewsBufferMin) return true;
   return false;
}
void ResetDailyStats(){
   MqlDateTime td,ld; TimeToStruct(TimeCurrent(),td); TimeToStruct(lastDayReset,ld);
   if(td.day!=ld.day){totalTrades=0;winTrades=0;lossTrades=0;lastDayReset=TimeCurrent();SaveState();}
}
void AddLog(string type,string msg){
   MqlDateTime t; TimeToStruct(TimeCurrent(),t);
   logBuffer+=StringFormat("%02d:%02d:%02d",t.hour,t.min,t.sec)+"|"+type+"|"+msg+"\n";
   Print("["+type+"] "+msg);
}

//+------------------------------------------------------------------+
//| JSON DASHBOARD — includes real price history + initialBalance    |
//+------------------------------------------------------------------+
string EscapeJSON(string s)
{
   StringReplace(s,"\\","\\\\");
   StringReplace(s,"\"","\\\"");
   StringReplace(s,"\n","\\n");
   StringReplace(s,"\r","");
   StringReplace(s,"\t","\\t");
   return s;
}

void WriteJSON(){
   double bal=AccountInfoDouble(ACCOUNT_BALANCE);
   double eq=AccountInfoDouble(ACCOUNT_EQUITY);
   if(eq>peakEquity) peakEquity=eq;
   double dd=MathMax(0,((peakEquity-eq)/peakEquity)*100);
   double gr=((bal-initialBalance)/initialBalance)*100;
   double wr=(winTrades+lossTrades)>0?(double)winTrades/(winTrades+lossTrades)*100:0;
   string status=!botActive?"ARRETE":IsNewsTime()?"PAUSE":
                 !IsWithinTradingHours()?"HORS HEURES":"ACTIF";
   string marti=consecutiveLosses>0?
      "x"+DoubleToString(MathPow(MartingaleMulti,consecutiveLosses),2):"Normal";

   // Prix + historique
   string pj="";
   for(int i=0;i<TOTAL;i++){
      if(!flags[i]) continue;
      double bid=SymbolInfoDouble(symbols[i],SYMBOL_BID);
      int dg=(int)SymbolInfoInteger(symbols[i],SYMBOL_DIGITS);
      pj+="\""+symbols[i]+"\":{\"price\":"+DoubleToString(bid,dg)+
          ",\"change\":"+DoubleToString(bid-iOpen(symbols[i],PERIOD_D1,0),2)+
          ",\"cas\":\""+DetectRegime(i)+"\",\"history\":[";
      int bars=MathMin(PriceHistBars,(int)iBars(symbols[i],PERIOD_M5));
      for(int k=bars-1;k>=0;k--){
         if(k<bars-1) pj+=",";
         double cp=iClose(symbols[i],PERIOD_M5,k);
         pj+=DoubleToString(cp,dg);
      }
      pj+="]},";
   }
   if(StringLen(pj)>0) pj=StringSubstr(pj,0,StringLen(pj)-1);

   // Positions
   string posj="["; bool fp=true;
   for(int i=0;i<TOTAL;i++){
      for(int j=PositionsTotal()-1;j>=0;j--){
         ulong tk=PositionGetTicket(j);
         if(!PositionSelectByTicket(tk)) continue;
         if(PositionGetString(POSITION_SYMBOL)!=symbols[i]) continue;
         if(PositionGetInteger(POSITION_MAGIC)!=magics[i])  continue;
         if(!fp) posj+=",";
         int dg=(int)SymbolInfoInteger(symbols[i],SYMBOL_DIGITS);
         posj+="{\"asset\":\""+symbols[i]+"\","+
               "\"dir\":"+(PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY?"\"BUY\"":"\"SELL\"")+","+
               "\"type\":\""+EscapeJSON(PositionGetString(POSITION_COMMENT))+"\","+
               "\"lot\":"+DoubleToString(PositionGetDouble(POSITION_VOLUME),2)+","+
               "\"entry\":"+DoubleToString(PositionGetDouble(POSITION_PRICE_OPEN),dg)+","+
               "\"sl\":"+DoubleToString(PositionGetDouble(POSITION_SL),dg)+","+
               "\"tp\":"+DoubleToString(PositionGetDouble(POSITION_TP),dg)+","+
               "\"pl\":"+DoubleToString(PositionGetDouble(POSITION_PROFIT),2)+"}";
         fp=false;
      }
   }
   posj+="]";

   // Raisons
   string rj="["; string parts[]; int n=StringSplit(lastReason,'|',parts);
   bool fr=true;
   for(int k=0;k+1<n;k+=2){
      if(!fr) rj+=",";
      rj+="{\"ok\":"+(parts[k]=="true"?"true":"false")+",\"text\":\""+EscapeJSON(parts[k+1])+"\"}";
      fr=false;
   }
   rj+="]";

   // Log
   string lj="["; string lines[]; int nl=StringSplit(logBuffer,'\n',lines);
   int start=MathMax(0,nl-10); bool fl=true;
   for(int k=start;k<nl;k++){
      string p2[]; int n2=StringSplit(lines[k],'|',p2);
      if(n2<3) continue;
      if(!fl) lj+=",";
      lj+="{\"time\":\""+p2[0]+"\",\"type\":\""+p2[1]+"\",\"msg\":\""+EscapeJSON(p2[2])+"\"}";
      fl=false;
   }
   lj+="]";

   string json="{"+
      "\"status\":\""+status+"\",\"balance\":"+DoubleToString(bal,2)+","+
      "\"equity\":"+DoubleToString(eq,2)+",\"openPL\":"+DoubleToString(eq-bal,2)+","+
      "\"growth\":"+DoubleToString(gr,2)+",\"drawdown\":"+DoubleToString(dd,2)+","+
      "\"trades\":"+IntegerToString(totalTrades)+",\"winRate\":"+DoubleToString(wr,1)+","+
      "\"winTrades\":"+IntegerToString(winTrades)+",\"lossTrades\":"+IntegerToString(lossTrades)+","+
      "\"martingale\":\""+marti+"\",\"losses\":"+IntegerToString(consecutiveLosses)+","+
      "\"currentCAS\":\""+lastCAS+"\","+
      "\"initialBalance\":"+DoubleToString(initialBalance,2)+","+
      "\"peakEquity\":"+DoubleToString(peakEquity,2)+","+
      "\"prices\":{"+pj+"},"+
      "\"signal\":{\"asset\":\""+lastSignalAsset+"\",\"type\":\""+lastSignalType+"\","+
      "\"score\":"+DoubleToString(lastSignalScore,0)+",\"cas\":\""+lastCAS+"\","+
      "\"reasons\":"+rj+"},"+
      "\"lastAction\":\""+EscapeJSON(lastAction)+"\",\"positions\":"+posj+",\"log\":"+lj+"}";

   int fh=FileOpen(JsonFileName,FILE_WRITE|FILE_TXT|FILE_COMMON);
   if(fh!=INVALID_HANDLE){ FileWriteString(fh,json); FileClose(fh); }

   Comment("SmartTrader 7CAS v1.1\n"+
           "Statut: "+status+" | $"+DoubleToString(bal,2)+"\n"+
           "CAS actif: "+lastCAS+" | DD: "+DoubleToString(dd,1)+"%\n"+
           "Trades: "+IntegerToString(totalTrades)+" | WR: "+DoubleToString(wr,1)+"%");
}

void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &req,const MqlTradeResult &res){
   if(trans.type!=TRADE_TRANSACTION_DEAL_ADD) return;
   if(!HistoryDealSelect(trans.deal)) return;
   if(HistoryDealGetInteger(trans.deal,DEAL_ENTRY)!=DEAL_ENTRY_OUT) return;
   double pp=HistoryDealGetDouble(trans.deal,DEAL_PROFIT);
   string sym=HistoryDealGetString(trans.deal,DEAL_SYMBOL);
   if(pp<0){consecutiveLosses++;lossTrades++;
      lastAction="FERME PERTE "+sym+" $"+DoubleToString(pp,2)+" | SL atteint";
      AddLog("WARN","PERTE "+sym+" $"+DoubleToString(pp,2));
   } else {consecutiveLosses=0;winTrades++;
      lastAction="FERME PROFIT "+sym+" $"+DoubleToString(pp,2)+" | TP atteint";
      AddLog("INFO","PROFIT "+sym+" $"+DoubleToString(pp,2));
   }
   SaveState();
}

void OnDeinit(const int reason){
   for(int i=0;i<TOTAL;i++){
      if(!flags[i]) continue;
      IndicatorRelease(hEmaF[i]);  IndicatorRelease(hEmaS[i]);
      IndicatorRelease(hEmaM[i]);  IndicatorRelease(hEmaL[i]);
      IndicatorRelease(hATR[i]);   IndicatorRelease(hRSI[i]);
      IndicatorRelease(hMACD[i]);  IndicatorRelease(hBB[i]);
      IndicatorRelease(hADX[i]);
      IndicatorRelease(hStochRSI_M15[i]); IndicatorRelease(hStochRSI_M5[i]);
      IndicatorRelease(hEmaFH1[i]);IndicatorRelease(hEmaSH1[i]);
      IndicatorRelease(hEmaLH1[i]);
      IndicatorRelease(hEmaFH4[i]);IndicatorRelease(hEmaSH4[i]);
      IndicatorRelease(hEmaLD1[i]);
      IndicatorRelease(hEmaFM5[i]);IndicatorRelease(hEmaSM5[i]);
      IndicatorRelease(hATRM5[i]);
      IndicatorRelease(hEmaFM1[i]);IndicatorRelease(hEmaSM1[i]);
   }
   Comment(""); AddLog("INFO","Bot arrete."); SaveState(); WriteJSON();
}
//+------------------------------------------------------------------+
