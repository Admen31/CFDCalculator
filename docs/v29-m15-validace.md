# Historické ověření M15 strategie v2.8 (Yahoo Finance 15m, posledních ~60 dní, 2026-11-18 13:31 UTC)

Pravidla jsou pevně v kódu (`cfdcalc.m15`), na těchto datech se nic neladilo. Rozhodnutí v každé uzavřené 15m svíčce jen z dat, která byla v tu chvíli uzavřená. Bez historického filtru zpráv. Plán v2.9: POTVRZENÝ = vstup na close rozhodovací svíčky; PODMÍNĚNÝ = stop / limit pokyn platný 4 svíčky (1 h), vyplní se jen při skutečném dotyku hladiny (gap = horší cena). SL za M15 swingem v rozmezí 1–3× ATR, TP 2R, jen intradenně, SL i TP v jedné svíčce = SL. Spread placen při vstupu, náklady navíc 0,5× spread. Data nejsou ceny CFD Trading 212.

| instrument | část | BUY | SELL | NEUTRAL | NO DATA | plány potvrzené / podmíněné (nevyplněné) | směrová přesnost (1 h) | obchody | TP / SL | výhry (po nákladech) | Ø zisk R | Ø ztráta R | PF hrubě | PF po spreadu | PF po nákladech | součet R po nákladech | max DD R |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| EUR/USD | vývoj 60 % | 716 | 1380 | 871 | 0 | 117 / 1342 (171) | 49% (n=1848) | 116 | 34 / 51 | 42% | 1.42 | -0.99 | 1.33 | 1.14 | 1.05 | 3.4 | 12.4 |
| EUR/USD | test 40 % | 642 | 1070 | 529 | 0 | 116 / 1083 (141) | 52% (n=1576) | 88 | 33 / 33 | 49% | 1.53 | -0.94 | 1.93 | 1.67 | 1.56 | 23.4 | 8.7 |
| GBP/USD | vývoj 60 % | 910 | 1254 | 803 | 0 | 88 / 1419 (156) | 48% (n=2137) | 121 | 33 / 58 | 40% | 1.37 | -0.99 | 1.21 | 1.00 | 0.91 | -6.7 | 17.8 |
| GBP/USD | test 40 % | 801 | 870 | 570 | 0 | 136 / 919 (95) | 50% (n=1643) | 87 | 31 / 39 | 47% | 1.49 | -1.05 | 1.67 | 1.39 | 1.27 | 12.8 | 8.1 |
| USD/JPY | vývoj 60 % | 1172 | 910 | 882 | 0 | 124 / 1405 (147) | 49% (n=2070) | 116 | 23 / 57 | 35% | 1.36 | -0.90 | 0.96 | 0.87 | 0.83 | -11.5 | 26.2 |
| USD/JPY | test 40 % | 980 | 698 | 565 | 0 | 60 / 1200 (93) | 48% (n=1667) | 91 | 17 / 38 | 41% | 1.09 | -0.90 | 1.02 | 0.89 | 0.83 | -8.4 | 12.2 |
| XAU/USD | vývoj 60 % | 729 | 970 | 623 | 0 | 114 / 1189 (105) | 46% (n=1694) | 101 | 14 / 53 | 36% | 1.05 | -0.91 | 0.69 | 0.66 | 0.64 | -21.2 | 21.3 |
| XAU/USD | test 40 % | 389 | 931 | 494 | 0 | 123 / 826 (118) | 52% (n=1310) | 86 | 21 / 40 | 45% | 1.35 | -0.95 | 1.27 | 1.21 | 1.18 | 8.1 | 16.5 |
| WTI/USD | vývoj 60 % | 844 | 857 | 620 | 0 | 115 / 1114 (142) | 50% (n=1679) | 93 | 15 / 46 | 35% | 1.31 | -0.89 | 0.92 | 0.85 | 0.81 | -9.9 | 15.6 |
| WTI/USD | test 40 % | 569 | 754 | 489 | 0 | 63 / 955 (80) | 52% (n=1306) | 65 | 13 / 26 | 43% | 1.17 | -0.88 | 1.13 | 1.05 | 1.01 | 0.3 | 10.2 |
| AAPL | vývoj 60 % | 279 | 94 | 142 | 0 | 36 / 239 (34) | 47% (n=373) | 25 | 2 / 9 | 36% | 0.89 | -0.83 | 0.71 | 0.64 | 0.60 | -5.2 | 6.6 |
| AAPL | test 40 % | 275 | 181 | 144 | 0 | 34 / 294 (42) | 46% (n=454) | 27 | 0 / 7 | 44% | 0.41 | -0.68 | 0.60 | 0.52 | 0.48 | -5.3 | 6.2 |
| NVDA | vývoj 60 % | 221 | 120 | 174 | 0 | 33 / 197 (32) | 48% (n=341) | 20 | 0 / 5 | 35% | 0.74 | -0.55 | 0.83 | 0.75 | 0.72 | -2.0 | 4.6 |
| NVDA | test 40 % | 44 | 411 | 145 | 0 | 44 / 242 (76) | 56% (n=452) | 23 | 2 / 4 | 70% | 0.95 | -0.73 | 3.31 | 3.09 | 2.98 | 10.1 | 2.2 |
| MSFT | vývoj 60 % | 282 | 88 | 145 | 0 | 24 / 235 (32) | 43% (n=370) | 23 | 2 / 4 | 26% | 0.70 | -0.53 | 0.57 | 0.50 | 0.47 | -4.8 | 6.7 |
| MSFT | test 40 % | 122 | 322 | 156 | 0 | 31 / 269 (35) | 48% (n=442) | 28 | 3 / 6 | 46% | 0.81 | -0.60 | 1.37 | 1.24 | 1.18 | 1.6 | 4.0 |
| TSLA | vývoj 60 % | 202 | 132 | 181 | 0 | 20 / 208 (38) | 46% (n=333) | 16 | 0 / 0 | 44% | 0.36 | -0.30 | 1.17 | 1.00 | 0.92 | -0.2 | 1.3 |
| TSLA | test 40 % | 236 | 162 | 202 | 0 | 18 / 254 (24) | 47% (n=397) | 20 | 0 / 2 | 45% | 0.42 | -0.73 | 0.51 | 0.48 | 0.46 | -4.3 | 5.0 |
| SPY | vývoj 60 % | 232 | 125 | 158 | 0 | 13 / 193 (25) | 52% (n=356) | 18 | 0 / 3 | 33% | 0.50 | -0.64 | 0.66 | 0.47 | 0.40 | -4.6 | 5.5 |
| SPY | test 40 % | 146 | 312 | 142 | 0 | 31 / 267 (35) | 53% (n=456) | 28 | 4 / 6 | 57% | 0.92 | -0.77 | 2.02 | 1.72 | 1.59 | 5.4 | 4.3 |
| CELKEM | vývoj 60 % | 5587 | 5930 | 4599 | 0 | 684 / 7541 (882) | 48% (n=11201) | 649 | 123 / 286 | 37% | 1.22 | -0.88 | 0.99 | 0.88 | 0.82 | -62.8 | 75.1 |
| CELKEM | test 40 % (out-of-sample) | 4204 | 5711 | 3436 | 0 | 656 / 6309 (739) | 51% (n=9703) | 543 | 124 / 201 | 47% | 1.19 | -0.89 | 1.40 | 1.24 | 1.17 | 43.8 | 16.5 |
| CELKEM jen potvrzený | vývoj 60 % | 5587 | 5930 | 4599 | 0 | 684 / 7541 (882) | 48% (n=11201) | 98 | 21 / 60 | 30% | 1.53 | -1.04 | 0.78 | 0.67 | 0.62 | -27.2 | 36.9 |
| CELKEM jen potvrzený | test 40 % (out-of-sample) | 4204 | 5711 | 3436 | 0 | 656 / 6309 (739) | 51% (n=9703) | 100 | 35 / 36 | 51% | 1.51 | -0.94 | 2.09 | 1.80 | 1.67 | 30.7 | 8.1 |
| CELKEM jen podmíněný | vývoj 60 % | 5587 | 5930 | 4599 | 0 | 684 / 7541 (882) | 48% (n=11201) | 551 | 102 / 226 | 39% | 1.18 | -0.85 | 1.05 | 0.93 | 0.88 | -35.6 | 47.0 |
| CELKEM jen podmíněný | test 40 % (out-of-sample) | 4204 | 5711 | 3436 | 0 | 656 / 6309 (739) | 51% (n=9703) | 443 | 89 / 165 | 46% | 1.11 | -0.88 | 1.25 | 1.12 | 1.06 | 13.0 | 21.7 |

Data:
* EUR/USD (EURUSD=X): 5642 svíček 26.08.–18.11.2026, výpočet 4 s
* GBP/USD (GBPUSD=X): 5643 svíček 26.08.–18.11.2026, výpočet 4 s
* USD/JPY (JPY=X): 5623 svíček 26.08.–18.11.2026, výpočet 4 s
* XAU/USD (GC=F): 4546 svíček 10.09.–18.11.2026, výpočet 3 s
* WTI/USD (CL=F): 4545 svíček 10.09.–18.11.2026, výpočet 3 s
* AAPL (AAPL): 1561 svíček 25.08.–17.11.2026, výpočet 1 s
* NVDA (NVDA): 1561 svíček 25.08.–17.11.2026, výpočet 1 s
* MSFT (MSFT): 1561 svíček 25.08.–17.11.2026, výpočet 1 s
* TSLA (TSLA): 1561 svíček 25.08.–17.11.2026, výpočet 1 s
* SPY (SPY): 1561 svíček 25.08.–17.11.2026, výpočet 1 s

**Krátký vzorek – výsledky jsou orientační, nejsou důkazem ziskovosti ani její absence.**

## Závěr v2.9

Na vývojové části (60 %) je PF po nákladech **0,82** (potvrzené plány 0,62), na testovací části 1,17 (potvrzené 1,67,
jen 100 obchodů). Výsledek mezi úseky není konzistentní, a proto **statisticky prokázaná výhoda (edge) není**.
Aplikace proto nezobrazuje žádné procento úspěšnosti. Zdroj: běh CI 44313982792, krok m15_validation.
