# Historické ověření M15 strategie v2.8 (Yahoo Finance 15m, posledních ~60 dní, 2026-11-18 09:38 UTC)


Pravidla jsou pevně v kódu (`cfdcalc.m15`), na těchto datech se nic neladilo. Rozhodnutí v každé uzavřené 15m svíčce jen z dat, která byla v tu chvíli uzavřená. Bez historického filtru zpráv. Obchod: vstup na close rozhodovací svíčky se zaplaceným spreadem, SL 1,5× ATR, TP 2R, jen intradenně, SL i TP v jedné svíčce = SL. Náklady navíc 0,5× spread. Data nejsou ceny CFD Trading 212.


| instrument | část | BUY | SELL | NEUTRAL | NO DATA | potvrzené vstupy | směrová přesnost (1 h) | obchody | TP / SL | výhry (po nákladech) | Ø zisk R | Ø ztráta R | PF hrubě | PF po spreadu | PF po nákladech | součet R po nákladech | max DD R |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| EUR/USD | vývoj 60 % | 715 | 1380 | 862 | 0 | 97 | 49% (n=1847) | 33 | 7 / 23 | 27% | 1.53 | -1.14 | 0.64 | 0.54 | 0.50 | -13.6 | 14.3 |
| EUR/USD | test 40 % | 643 | 1054 | 538 | 0 | 81 | 52% (n=1561) | 27 | 9 / 13 | 48% | 1.53 | -1.09 | 1.65 | 1.41 | 1.31 | 4.7 | 7.4 |
| GBP/USD | vývoj 60 % | 904 | 1254 | 800 | 0 | 70 | 48% (n=2131) | 27 | 8 / 13 | 48% | 1.30 | -1.10 | 1.46 | 1.21 | 1.10 | 1.5 | 7.0 |
| GBP/USD | test 40 % | 807 | 854 | 573 | 0 | 84 | 51% (n=1633) | 25 | 6 / 14 | 32% | 1.59 | -1.04 | 0.97 | 0.79 | 0.72 | -5.0 | 9.3 |
| USD/JPY | vývoj 60 % | 1170 | 905 | 880 | 0 | 113 | 49% (n=2064) | 36 | 6 / 23 | 28% | 1.43 | -1.02 | 0.64 | 0.57 | 0.54 | -12.1 | 15.4 |
| USD/JPY | test 40 % | 978 | 697 | 561 | 0 | 61 | 49% (n=1663) | 25 | 6 / 17 | 32% | 1.52 | -1.13 | 0.78 | 0.68 | 0.63 | -7.1 | 10.2 |
| XAU/USD | vývoj 60 % | 727 | 969 | 617 | 0 | 101 | 46% (n=1690) | 35 | 4 / 28 | 17% | 1.39 | -1.02 | 0.31 | 0.29 | 0.28 | -21.3 | 23.2 |
| XAU/USD | test 40 % | 390 | 913 | 504 | 0 | 88 | 52% (n=1295) | 24 | 10 / 7 | 58% | 1.59 | -0.84 | 2.85 | 2.71 | 2.64 | 13.8 | 3.1 |
| WTI/USD | vývoj 60 % | 844 | 841 | 626 | 0 | 96 | 50% (n=1667) | 37 | 10 / 25 | 27% | 1.89 | -1.03 | 0.77 | 0.71 | 0.68 | -8.8 | 14.6 |
| WTI/USD | test 40 % | 569 | 747 | 490 | 0 | 61 | 53% (n=1301) | 23 | 9 / 13 | 43% | 1.69 | -1.09 | 1.37 | 1.25 | 1.20 | 2.8 | 6.2 |
| AAPL | vývoj 60 % | 279 | 94 | 142 | 0 | 31 | 47% (n=373) | 9 | 2 / 6 | 33% | 1.82 | -1.09 | 0.96 | 0.87 | 0.84 | -1.1 | 3.3 |
| AAPL | test 40 % | 275 | 181 | 144 | 0 | 32 | 46% (n=454) | 7 | 0 / 2 | 57% | 0.41 | -0.84 | 0.86 | 0.71 | 0.64 | -0.9 | 1.5 |
| NVDA | vývoj 60 % | 221 | 120 | 174 | 0 | 34 | 48% (n=341) | 8 | 0 / 2 | 12% | 0.42 | -0.68 | 0.12 | 0.10 | 0.09 | -4.3 | 4.3 |
| NVDA | test 40 % | 44 | 411 | 145 | 0 | 44 | 56% (n=452) | 9 | 2 / 0 | 89% | 1.23 | -0.15 | 78.12 | 67.75 | 63.42 | 9.7 | 0.2 |
| MSFT | vývoj 60 % | 282 | 88 | 145 | 0 | 25 | 43% (n=370) | 8 | 0 / 2 | 25% | 0.18 | -0.59 | 0.19 | 0.13 | 0.10 | -3.2 | 3.2 |
| MSFT | test 40 % | 122 | 322 | 156 | 0 | 25 | 48% (n=442) | 8 | 2 / 3 | 50% | 1.23 | -0.93 | 1.50 | 1.38 | 1.33 | 1.2 | 3.2 |
| TSLA | vývoj 60 % | 202 | 132 | 181 | 0 | 21 | 46% (n=333) | 7 | 0 / 1 | 57% | 0.77 | -0.46 | 2.78 | 2.40 | 2.24 | 1.7 | 1.2 |
| TSLA | test 40 % | 236 | 162 | 202 | 0 | 17 | 47% (n=397) | 5 | 1 / 1 | 60% | 0.75 | -0.89 | 1.40 | 1.31 | 1.26 | 0.5 | 1.5 |
| SPY | vývoj 60 % | 232 | 125 | 158 | 0 | 2 | 52% (n=356) | 2 | 0 / 1 | 0% | – | -0.63 | 0.03 | 0.00 | 0.00 | -1.3 | 1.3 |
| SPY | test 40 % | 146 | 312 | 142 | 0 | 26 | 53% (n=456) | 5 | 0 / 2 | 40% | 0.75 | -1.05 | 0.65 | 0.53 | 0.48 | -1.7 | 2.3 |
| CELKEM | vývoj 60 % | 5576 | 5908 | 4585 | 0 | 590 | 48% (n=11172) | 202 | 37 / 124 | 29% | 1.41 | -1.00 | 0.68 | 0.60 | 0.57 | -62.5 | 63.6 |
| CELKEM | test 40 % (out-of-sample) | 4210 | 5653 | 3455 | 0 | 519 | 51% (n=9654) | 158 | 45 / 72 | 47% | 1.41 | -1.02 | 1.46 | 1.29 | 1.21 | 18.0 | 15.1 |


Data:
* EUR/USD (EURUSD=X): 5626 svíček 26.08.–18.11.2026, výpočet 5 s
* GBP/USD (GBPUSD=X): 5627 svíček 26.08.–18.11.2026, výpočet 5 s
* USD/JPY (JPY=X): 5607 svíček 26.08.–18.11.2026, výpočet 5 s
* XAU/USD (GC=F): 4530 svíček 10.09.–18.11.2026, výpočet 4 s
* WTI/USD (CL=F): 4529 svíček 10.09.–18.11.2026, výpočet 4 s
* AAPL (AAPL): 1561 svíček 25.08.–17.11.2026, výpočet 1 s
* NVDA (NVDA): 1561 svíček 25.08.–17.11.2026, výpočet 1 s
* MSFT (MSFT): 1561 svíček 25.08.–17.11.2026, výpočet 1 s
* TSLA (TSLA): 1561 svíček 25.08.–17.11.2026, výpočet 1 s
* SPY (SPY): 1561 svíček 25.08.–17.11.2026, výpočet 1 s


**Krátký vzorek – výsledky jsou orientační, nejsou důkazem ziskovosti ani její absence.**

## Interpretace (napsáno až po výsledcích, pravidla se podle nich neměnila)

* **Směr M15 nemá prokázanou předpovědní hodnotu.** BUY/SELL souhlasí se směrem ceny o hodinu později v 48 %
  (vývoj) a 51 % (test) případů, tedy na úrovni náhody. BUY/SELL je **popis převažujícího stavu trhu**, ne
  předpověď.
* **Potvrzené vstupy** (SL 1,5× ATR, TP 2R): vývojová část 202 obchodů, PF po nákladech 0,57, −62,5 R.
  Out-of-sample 158 obchodů, PF 1,21, +18,0 R. Dohromady 360 obchodů a **−44,5 R po nákladech**. Rozdíl mezi
  částmi je větší než jakýkoli stabilní efekt. Jde o šum krátkého období (60 dní), **ziskovost není prokázaná**.
* Většina obchodů končí stop-lossem nebo časem (večerní limit, 8 h), TP 2R se zasáhne v 82 ze 360 obchodů.
* Spread a náklady sníží PF zhruba o 0,1–0,2. U akcií je spread jen odhad (0,03 % ceny).
* NO DATA je 0, protože historická data jsou vždy kompletní. V aplikaci NO DATA vzniká z chybějících a
  zastaralých dat, tarifu nebo limitu API.
* Data nejsou ceny CFD Trading 212 (zlato = futures GC=F, ropa = CL=F), chybí filtr zpráv a skluz je jen
  modelovaný.

**Závěr:** M15 signál je technicky spolehlivý (jeden rámec, jeden požadavek, žádný look-ahead, stejný kód v
aplikaci i v testu), ale **neprokazuje obchodní výhodu**. Používejte ho jako strukturovaný popis trhu a disciplínu
rizika (SL, velikost pozice), ne jako záruku zisku.
