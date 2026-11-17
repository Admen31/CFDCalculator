# v2.3 – diagnostika WAIT a test strategií (2026-11-17 20:05 UTC)

Data Yahoo Finance (veřejná, ne ceny Trading 212; zlato/stříbro/ropa = futures jako výzkumná náhrada). Náklady: spread z katalogu T212 jednou za obchod + skluz 0,1× spreadu na tržních plněních. Bez historického kalendáře – filtr zpráv NETESTOVÁN. Parametry pevné, rozdělení 50/25/25, 6 úseků.

| instrument | zdroj | svíček 5m | období | spread | opravených svíček |
|---|---|---|---|---|---|
| EUR/USD | EURUSD=X (spot) | 16999 | 25.08.2026 – 17.11.2026 | 8e-05 | 0 |
| GBP/USD | GBPUSD=X (spot) | 17003 | 25.08.2026 – 17.11.2026 | 0.00012 | 0 |
| USD/JPY | JPY=X (spot) | 16933 | 25.08.2026 – 17.11.2026 | 0.012 | 0 |
| XAU/USD | GC=F (futures) | 13673 | 09.09.2026 – 17.11.2026 | 0.35 | 0 |
| XAG/USD | SI=F (futures) | 13660 | 09.09.2026 – 17.11.2026 | 0.03 | 0 |
| WTI/USD | CL=F (futures) | 13675 | 09.09.2026 – 17.11.2026 | 0.03 | 0 |
| AAPL | AAPL (stock) | 4667 | 25.08.2026 – 17.11.2026 | 0 | 0 |
| NVDA | NVDA (stock) | 4667 | 25.08.2026 – 17.11.2026 | 0 | 0 |
| MSFT | MSFT (stock) | 4667 | 25.08.2026 – 17.11.2026 | 0 | 0 |
| TSLA | TSLA (stock) | 4667 | 25.08.2026 – 17.11.2026 | 0 | 0 |

## 1. Proč v2.1 tak často vrací WAIT

### EUR/USD (EUR/USD) – 16749 rozhodnutí
| BUY | SELL | WAIT | NO DATA | ERROR |
|---|---|---|---|---|
| 75 (0.4 %) | 350 (2.1 %) | 15690 (93.7 %) | 634 (3.8 %) | 0 (0.0 %) |

Nejčastější první důvod WAIT/NO DATA: Shoda indikátorů 9634×; rezistence 2650×; 1h graf 2265×; 15min 526×; přeprodáno 520×; support 227×

| podmínka | blokuje (podíl WAIT) | jediná blokující | hypotetický obchod, když blokovala jen ona: počet, ⌀ R po nákladech |
|---|---|---|---|
| Trend 1h | 2265 (14.4 %) | 1508 | 0, – |
| Shoda indikátorů | 9634 (61.4 %) | 719 | 718, -0.203 |
| RSI extrém | 813 (5.2 %) | 255 | 254, -0.427 |
| Volatilita (ATR) | 60 (0.4 %) | 1 | 1, -1.010 |
| Prostor k cíli | 11625 (74.1 %) | 1379 | 1378, -0.069 |
| Spread | 4979 (31.7 %) | 153 | 153, -0.047 |
| Časový limit | 2616 (16.7 %) | 40 | 3, -0.108 |
| *signály v2.1 (pro srovnání)* | | | 425, -0.164 |

Jasný směr (bias se všemi třemi částmi ve shodě): 3893 rozhodnutí, z toho WAIT 3486 (89.5 %), BUY/SELL 407. Blokovalo: Prostor k cíli 2919×; Spread 1392×; RSI extrém 689×; Časový limit 524×
Bias ex post (cena o hodinu později ve směru biasu): BEARISH 3625/7558 (48.0 %); BULLISH 1397/3345 (41.8 %)
Nové stavy: WATCH v 35.8 % rozhodnutí, splněný setup v 3.6 %; podle strategie: breakout: watch 803, trigger 128, zaniklý 1; meanrev: watch 575, trigger 50, zaniklý 30; pullback: watch 4742, trigger 445, zaniklý 1710

| trh / režim | BUY | SELL | WAIT | NO DATA | ERROR |
|---|---|---|---|---|---|
| Forex / bez trendu | 0.5 % | 0.5 % | 98.9 % | 0.0 % | 0.0 % |
| Forex / trend | 0.4 % | 3.9 % | 95.7 % | 0.0 % | 0.0 % |

### GBP/USD (GBP/USD) – 16753 rozhodnutí
| BUY | SELL | WAIT | NO DATA | ERROR |
|---|---|---|---|---|
| 125 (0.7 %) | 195 (1.2 %) | 15797 (94.3 %) | 636 (3.8 %) | 0 (0.0 %) |

Nejčastější první důvod WAIT/NO DATA: Shoda indikátorů 9651×; rezistence 2794×; 1h graf 2259×; 15min 528×; přeprodáno 348×; spread 266×

| podmínka | blokuje (podíl WAIT) | jediná blokující | hypotetický obchod, když blokovala jen ona: počet, ⌀ R po nákladech |
|---|---|---|---|
| Trend 1h | 2259 (14.3 %) | 1085 | 0, – |
| Shoda indikátorů | 9651 (61.1 %) | 514 | 514, -0.190 |
| RSI extrém | 673 (4.3 %) | 220 | 220, -0.561 |
| Volatilita (ATR) | 4 (0.0 %) | 1 | 1, -1.273 |
| Prostor k cíli | 11711 (74.1 %) | 964 | 964, -0.153 |
| Spread | 9111 (57.7 %) | 247 | 247, +0.073 |
| Časový limit | 2618 (16.6 %) | 52 | 20, -0.078 |
| *signály v2.1 (pro srovnání)* | | | 320, -0.301 |

Jasný směr (bias se všemi třemi částmi ve shodě): 3885 rozhodnutí, z toho WAIT 3565 (91.8 %), BUY/SELL 320. Blokovalo: Prostor k cíli 2862×; Spread 2247×; RSI extrém 569×; Časový limit 447×
Bias ex post (cena o hodinu později ve směru biasu): BEARISH 3196/6551 (48.8 %); BULLISH 2137/4469 (47.8 %)
Nové stavy: WATCH v 37.3 % rozhodnutí, splněný setup v 4.8 %; podle strategie: breakout: watch 737, trigger 117, zaniklý 3; meanrev: watch 512, trigger 53, zaniklý 41; pullback: watch 5077, trigger 630, zaniklý 1786

| trh / režim | BUY | SELL | WAIT | NO DATA | ERROR |
|---|---|---|---|---|---|
| Forex / bez trendu | 0.3 % | 0.5 % | 99.1 % | 0.0 % | 0.0 % |
| Forex / trend | 1.2 % | 1.9 % | 96.9 % | 0.0 % | 0.0 % |

### USD/JPY (USD/JPY) – 16683 rozhodnutí
| BUY | SELL | WAIT | NO DATA | ERROR |
|---|---|---|---|---|
| 295 (1.8 %) | 145 (0.9 %) | 15611 (93.6 %) | 632 (3.8 %) | 0 (0.0 %) |

Nejčastější první důvod WAIT/NO DATA: Shoda indikátorů 9665×; rezistence 2624×; 1h graf 2545×; 15min 524×; překoupeno 424×; přeprodáno 241×

| podmínka | blokuje (podíl WAIT) | jediná blokující | hypotetický obchod, když blokovala jen ona: počet, ⌀ R po nákladech |
|---|---|---|---|
| Trend 1h | 2545 (16.3 %) | 2240 | 0, – |
| Shoda indikátorů | 9665 (61.9 %) | 845 | 845, -0.236 |
| RSI extrém | 786 (5.0 %) | 376 | 376, +0.159 |
| Volatilita (ATR) | 28 (0.2 %) | 2 | 2, +0.685 |
| Prostor k cíli | 11612 (74.4 %) | 2221 | 2221, -0.099 |
| Spread | 300 (1.9 %) | 28 | 28, -0.519 |
| Časový limit | 2549 (16.3 %) | 9 | 5, -0.150 |
| *signály v2.1 (pro srovnání)* | | | 440, -0.121 |

Jasný směr (bias se všemi třemi částmi ve shodě): 3603 rozhodnutí, z toho WAIT 3163 (87.8 %), BUY/SELL 440. Blokovalo: Prostor k cíli 2709×; RSI extrém 663×; Časový limit 479×; Spread 77×
Bias ex post (cena o hodinu později ve směru biasu): BEARISH 1847/4102 (45.0 %); BULLISH 3320/6527 (50.9 %)
Nové stavy: WATCH v 38.5 % rozhodnutí, splněný setup v 3.8 %; podle strategie: breakout: watch 1061, trigger 130, zaniklý 6; meanrev: watch 756, trigger 82, zaniklý 51; pullback: watch 4884, trigger 432, zaniklý 1846

| trh / režim | BUY | SELL | WAIT | NO DATA | ERROR |
|---|---|---|---|---|---|
| Forex / bez trendu | 1.1 % | 0.7 % | 98.2 % | 0.0 % | 0.0 % |
| Forex / trend | 3.0 % | 1.3 % | 95.7 % | 0.0 % | 0.0 % |

### Gold (XAU/USD) – 13423 rozhodnutí
| BUY | SELL | WAIT | NO DATA | ERROR |
|---|---|---|---|---|
| 42 (0.3 %) | 295 (2.2 %) | 12128 (90.4 %) | 958 (7.1 %) | 0 (0.0 %) |

Nejčastější první důvod WAIT/NO DATA: Shoda indikátorů 7278×; 1h graf 2168×; rezistence 2049×; 15min 572×; 1h 386×; přeprodáno 306×

| podmínka | blokuje (podíl WAIT) | jediná blokující | hypotetický obchod, když blokovala jen ona: počet, ⌀ R po nákladech |
|---|---|---|---|
| Trend 1h | 2168 (17.9 %) | 1903 | 0, – |
| Shoda indikátorů | 7278 (60.0 %) | 677 | 677, -0.036 |
| RSI extrém | 603 (5.0 %) | 225 | 225, +0.287 |
| Volatilita (ATR) | 15 (0.1 %) | 3 | 3, +0.729 |
| Prostor k cíli | 8825 (72.8 %) | 1889 | 1886, -0.146 |
| Časový limit | 1615 (13.3 %) | 23 | 4, +0.201 |
| *signály v2.1 (pro srovnání)* | | | 337, -0.063 |

Jasný směr (bias se všemi třemi částmi ve shodě): 2814 rozhodnutí, z toho WAIT 2482 (88.2 %), BUY/SELL 332. Blokovalo: Prostor k cíli 2217×; RSI extrém 456×; Časový limit 346×; Shoda indikátorů 34×
Bias ex post (cena o hodinu později ve směru biasu): BEARISH 2835/5693 (49.8 %); BULLISH 1121/2486 (45.1 %)
Nové stavy: WATCH v 37.2 % rozhodnutí, splněný setup v 4.2 %; podle strategie: breakout: watch 679, trigger 93, zaniklý 6; meanrev: watch 514, trigger 79, zaniklý 50; pullback: watch 3794, trigger 368, zaniklý 1394

| trh / režim | BUY | SELL | WAIT | NO DATA | ERROR |
|---|---|---|---|---|---|
| Komodity / bez trendu | 0.3 % | 1.6 % | 98.1 % | 0.0 % | 0.0 % |
| Komodity / trend | 0.4 % | 3.7 % | 95.9 % | 0.0 % | 0.0 % |

### Silver (XAG/USD) – 13410 rozhodnutí
| BUY | SELL | WAIT | NO DATA | ERROR |
|---|---|---|---|---|
| 76 (0.6 %) | 298 (2.2 %) | 12054 (89.9 %) | 982 (7.3 %) | 0 (0.0 %) |

Nejčastější první důvod WAIT/NO DATA: Shoda indikátorů 7315×; 1h graf 2120×; rezistence 1998×; 15min 569×; 1h 413×; přeprodáno 339×

| podmínka | blokuje (podíl WAIT) | jediná blokující | hypotetický obchod, když blokovala jen ona: počet, ⌀ R po nákladech |
|---|---|---|---|
| Trend 1h | 2120 (17.6 %) | 1637 | 0, – |
| Shoda indikátorů | 7315 (60.7 %) | 658 | 658, +0.033 |
| RSI extrém | 535 (4.4 %) | 223 | 223, +0.270 |
| Volatilita (ATR) | 14 (0.1 %) | 0 | 0, – |
| Prostor k cíli | 8866 (73.6 %) | 1637 | 1637, -0.148 |
| Spread | 1055 (8.8 %) | 4 | 4, -0.365 |
| Časový limit | 1612 (13.4 %) | 32 | 3, -0.333 |
| *signály v2.1 (pro srovnání)* | | | 374, +0.068 |

Jasný směr (bias se všemi třemi částmi ve shodě): 2791 rozhodnutí, z toho WAIT 2427 (87.0 %), BUY/SELL 364. Blokovalo: Prostor k cíli 2148×; RSI extrém 433×; Časový limit 385×; Spread 225×
Bias ex post (cena o hodinu později ve směru biasu): BEARISH 2984/5783 (51.6 %); BULLISH 1050/2393 (43.9 %)
Nové stavy: WATCH v 37.5 % rozhodnutí, splněný setup v 3.9 %; podle strategie: breakout: watch 762, trigger 98, zaniklý 3; meanrev: watch 565, trigger 51, zaniklý 53; pullback: watch 3685, trigger 360, zaniklý 1332

| trh / režim | BUY | SELL | WAIT | NO DATA | ERROR |
|---|---|---|---|---|---|
| Komodity / bez trendu | 0.3 % | 0.9 % | 98.8 % | 0.0 % | 0.0 % |
| Komodity / trend | 1.0 % | 4.1 % | 94.9 % | 0.0 % | 0.0 % |

### Oil (WTI) (WTI/USD) – 13425 rozhodnutí
| BUY | SELL | WAIT | NO DATA | ERROR |
|---|---|---|---|---|
| 124 (0.9 %) | 153 (1.1 %) | 12162 (90.6 %) | 986 (7.3 %) | 0 (0.0 %) |

Nejčastější první důvod WAIT/NO DATA: Shoda indikátorů 7344×; 1h graf 2197×; rezistence 1906×; 15min 572×; 1h 414×; přeprodáno 291×

| podmínka | blokuje (podíl WAIT) | jediná blokující | hypotetický obchod, když blokovala jen ona: počet, ⌀ R po nákladech |
|---|---|---|---|
| Trend 1h | 2197 (18.1 %) | 1949 | 0, – |
| Shoda indikátorů | 7344 (60.4 %) | 521 | 521, -0.278 |
| RSI extrém | 692 (5.7 %) | 228 | 228, -0.333 |
| Volatilita (ATR) | 87 (0.7 %) | 0 | 0, – |
| Prostor k cíli | 9007 (74.1 %) | 1775 | 1774, +0.102 |
| Časový limit | 1614 (13.3 %) | 48 | 15, -0.113 |
| *signály v2.1 (pro srovnání)* | | | 277, -0.027 |

Jasný směr (bias se všemi třemi částmi ve shodě): 2728 rozhodnutí, z toho WAIT 2458 (90.1 %), BUY/SELL 270. Blokovalo: Prostor k cíli 2156×; RSI extrém 575×; Časový limit 300×; Shoda indikátorů 19×
Bias ex post (cena o hodinu později ve směru biasu): BEARISH 1974/3894 (50.7 %); BULLISH 1928/4018 (48.0 %)
Nové stavy: WATCH v 36.2 % rozhodnutí, splněný setup v 3.5 %; podle strategie: breakout: watch 656, trigger 82, zaniklý 0; meanrev: watch 497, trigger 72, zaniklý 47; pullback: watch 3612, trigger 291, zaniklý 1397

| trh / režim | BUY | SELL | WAIT | NO DATA | ERROR |
|---|---|---|---|---|---|
| Komodity / bez trendu | 0.9 % | 0.7 % | 98.4 % | 0.0 % | 0.0 % |
| Komodity / trend | 1.2 % | 2.1 % | 96.7 % | 0.0 % | 0.0 % |

### Apple (AAPL) – 4417 rozhodnutí
| BUY | SELL | WAIT | NO DATA | ERROR |
|---|---|---|---|---|
| 0 (0.0 %) | 0 (0.0 %) | 3917 (88.7 %) | 500 (11.3 %) | 0 (0.0 %) |

Nejčastější první důvod WAIT/NO DATA: Shoda indikátorů 2783×; 1h graf 653×; 15min 500×; rezistence 326×; překoupeno 90×; spread 41×

| podmínka | blokuje (podíl WAIT) | jediná blokující | hypotetický obchod, když blokovala jen ona: počet, ⌀ R po nákladech |
|---|---|---|---|
| Trend 1h | 653 (16.7 %) | 0 | 0, – |
| Shoda indikátorů | 2783 (71.0 %) | 0 | 0, – |
| RSI extrém | 186 (4.7 %) | 0 | 0, – |
| Volatilita (ATR) | 10 (0.3 %) | 0 | 0, – |
| Prostor k cíli | 2967 (75.7 %) | 0 | 0, – |
| Spread | 3917 (100.0 %) | 31 | 31, -0.519 |
| Časový limit | 736 (18.8 %) | 0 | 0, – |
| *signály v2.1 (pro srovnání)* | | | 0, – |

Jasný směr (bias se všemi třemi částmi ve shodě): 702 rozhodnutí, z toho WAIT 702 (100.0 %), BUY/SELL 0. Blokovalo: Spread 702×; Prostor k cíli 564×; Shoda indikátorů 251×; Časový limit 160×
Bias ex post (cena o hodinu později ve směru biasu): BEARISH 211/546 (38.6 %); BULLISH 936/1988 (47.1 %)
Nové stavy: WATCH v 38.4 % rozhodnutí, splněný setup v 3.0 %; podle strategie: breakout: watch 338, trigger 27, zaniklý 0; meanrev: watch 191, trigger 20, zaniklý 16; pullback: watch 1110, trigger 81, zaniklý 468

| trh / režim | BUY | SELL | WAIT | NO DATA | ERROR |
|---|---|---|---|---|---|
| Akcie CFD / bez trendu | 0.0 % | 0.0 % | 100.0 % | 0.0 % | 0.0 % |
| Akcie CFD / trend | 0.0 % | 0.0 % | 100.0 % | 0.0 % | 0.0 % |

### NVIDIA (NVDA) – 4417 rozhodnutí
| BUY | SELL | WAIT | NO DATA | ERROR |
|---|---|---|---|---|
| 0 (0.0 %) | 0 (0.0 %) | 3917 (88.7 %) | 500 (11.3 %) | 0 (0.0 %) |

Nejčastější první důvod WAIT/NO DATA: Shoda indikátorů 2820×; 15min 500×; 1h graf 450×; rezistence 343×; přeprodáno 123×; překoupeno 67×

| podmínka | blokuje (podíl WAIT) | jediná blokující | hypotetický obchod, když blokovala jen ona: počet, ⌀ R po nákladech |
|---|---|---|---|
| Trend 1h | 450 (11.5 %) | 0 | 0, – |
| Shoda indikátorů | 2820 (72.0 %) | 0 | 0, – |
| RSI extrém | 308 (7.9 %) | 0 | 0, – |
| Volatilita (ATR) | 14 (0.4 %) | 0 | 0, – |
| Prostor k cíli | 2661 (67.9 %) | 0 | 0, – |
| Spread | 3917 (100.0 %) | 57 | 57, +0.021 |
| Časový limit | 736 (18.8 %) | 0 | 0, – |
| *signály v2.1 (pro srovnání)* | | | 0, – |

Jasný směr (bias se všemi třemi částmi ve shodě): 888 rozhodnutí, z toho WAIT 888 (100.0 %), BUY/SELL 0. Blokovalo: Spread 888×; Prostor k cíli 614×; Shoda indikátorů 298×; RSI extrém 241×
Bias ex post (cena o hodinu později ve směru biasu): BEARISH 1097/1967 (55.8 %); BULLISH 403/857 (47.0 %)
Nové stavy: WATCH v 37.3 % rozhodnutí, splněný setup v 3.1 %; podle strategie: breakout: watch 328, trigger 27, zaniklý 6; meanrev: watch 49, trigger 5, zaniklý 4; pullback: watch 1182, trigger 93, zaniklý 341

| trh / režim | BUY | SELL | WAIT | NO DATA | ERROR |
|---|---|---|---|---|---|
| Akcie CFD / bez trendu | 0.0 % | 0.0 % | 100.0 % | 0.0 % | 0.0 % |
| Akcie CFD / trend | 0.0 % | 0.0 % | 100.0 % | 0.0 % | 0.0 % |

### Microsoft (MSFT) – 4417 rozhodnutí
| BUY | SELL | WAIT | NO DATA | ERROR |
|---|---|---|---|---|
| 0 (0.0 %) | 0 (0.0 %) | 3917 (88.7 %) | 500 (11.3 %) | 0 (0.0 %) |

Nejčastější první důvod WAIT/NO DATA: Shoda indikátorů 2695×; 1h graf 660×; 15min 500×; rezistence 395×; přeprodáno 65×; překoupeno 54×

| podmínka | blokuje (podíl WAIT) | jediná blokující | hypotetický obchod, když blokovala jen ona: počet, ⌀ R po nákladech |
|---|---|---|---|
| Trend 1h | 660 (16.8 %) | 0 | 0, – |
| Shoda indikátorů | 2695 (68.8 %) | 0 | 0, – |
| RSI extrém | 192 (4.9 %) | 0 | 0, – |
| Volatilita (ATR) | 14 (0.4 %) | 0 | 0, – |
| Prostor k cíli | 2909 (74.3 %) | 0 | 0, – |
| Spread | 3917 (100.0 %) | 28 | 28, -0.394 |
| Časový limit | 736 (18.8 %) | 0 | 0, – |
| *signály v2.1 (pro srovnání)* | | | 0, – |

Jasný směr (bias se všemi třemi částmi ve shodě): 776 rozhodnutí, z toho WAIT 776 (100.0 %), BUY/SELL 0. Blokovalo: Spread 776×; Prostor k cíli 615×; Shoda indikátorů 284×; Časový limit 219×
Bias ex post (cena o hodinu později ve směru biasu): BEARISH 593/1194 (49.7 %); BULLISH 652/1375 (47.4 %)
Nové stavy: WATCH v 36.8 % rozhodnutí, splněný setup v 3.4 %; podle strategie: breakout: watch 321, trigger 22, zaniklý 1; meanrev: watch 194, trigger 15, zaniklý 16; pullback: watch 1060, trigger 99, zaniklý 576

| trh / režim | BUY | SELL | WAIT | NO DATA | ERROR |
|---|---|---|---|---|---|
| Akcie CFD / bez trendu | 0.0 % | 0.0 % | 100.0 % | 0.0 % | 0.0 % |
| Akcie CFD / trend | 0.0 % | 0.0 % | 100.0 % | 0.0 % | 0.0 % |

### Tesla (TSLA) – 4417 rozhodnutí
| BUY | SELL | WAIT | NO DATA | ERROR |
|---|---|---|---|---|
| 0 (0.0 %) | 0 (0.0 %) | 3917 (88.7 %) | 500 (11.3 %) | 0 (0.0 %) |

Nejčastější první důvod WAIT/NO DATA: Shoda indikátorů 2581×; 1h graf 894×; 15min 500×; rezistence 297×; překoupeno 53×; spread 38×

| podmínka | blokuje (podíl WAIT) | jediná blokující | hypotetický obchod, když blokovala jen ona: počet, ⌀ R po nákladech |
|---|---|---|---|
| Trend 1h | 894 (22.8 %) | 0 | 0, – |
| Shoda indikátorů | 2581 (65.9 %) | 0 | 0, – |
| RSI extrém | 155 (4.0 %) | 0 | 0, – |
| Volatilita (ATR) | 15 (0.4 %) | 0 | 0, – |
| Prostor k cíli | 2634 (67.2 %) | 0 | 0, – |
| Spread | 3917 (100.0 %) | 33 | 33, +0.020 |
| Časový limit | 736 (18.8 %) | 0 | 0, – |
| *signály v2.1 (pro srovnání)* | | | 0, – |

Jasný směr (bias se všemi třemi částmi ve shodě): 621 rozhodnutí, z toho WAIT 621 (100.0 %), BUY/SELL 0. Blokovalo: Spread 621×; Prostor k cíli 491×; Shoda indikátorů 229×; Časový limit 145×
Bias ex post (cena o hodinu později ve směru biasu): BEARISH 428/856 (50.0 %); BULLISH 697/1573 (44.3 %)
Nové stavy: WATCH v 38.1 % rozhodnutí, splněný setup v 3.7 %; podle strategie: breakout: watch 378, trigger 25, zaniklý 1; meanrev: watch 127, trigger 19, zaniklý 12; pullback: watch 1106, trigger 104, zaniklý 394

| trh / režim | BUY | SELL | WAIT | NO DATA | ERROR |
|---|---|---|---|---|---|
| Akcie CFD / bez trendu | 0.0 % | 0.0 % | 100.0 % | 0.0 % | 0.0 % |
| Akcie CFD / trend | 0.0 % | 0.0 % | 100.0 % | 0.0 % | 0.0 % |

### všechny instrumenty (CELKEM) – 108111 rozhodnutí
| BUY | SELL | WAIT | NO DATA | ERROR |
|---|---|---|---|---|
| 737 (0.7 %) | 1436 (1.3 %) | 99110 (91.7 %) | 6828 (6.3 %) | 0 (0.0 %) |

Nejčastější první důvod WAIT/NO DATA: Shoda indikátorů 61766×; 1h graf 16211×; rezistence 15382×; 15min 5291×; přeprodáno 2291×; překoupeno 1617×

| podmínka | blokuje (podíl WAIT) | jediná blokující | hypotetický obchod, když blokovala jen ona: počet, ⌀ R po nákladech |
|---|---|---|---|
| Trend 1h | 16211 (16.4 %) | 10322 | 0, – |
| Shoda indikátorů | 61766 (62.3 %) | 3934 | 3933, -0.150 |
| RSI extrém | 4943 (5.0 %) | 1527 | 1526, -0.081 |
| Volatilita (ATR) | 261 (0.3 %) | 7 | 7, +0.182 |
| Prostor k cíli | 72817 (73.5 %) | 9865 | 9860, -0.081 |
| Spread | 31113 (31.4 %) | 581 | 581, -0.052 |
| Časový limit | 15568 (15.7 %) | 204 | 50, -0.090 |
| *signály v2.1 (pro srovnání)* | | | 2173, -0.102 |

Jasný směr (bias se všemi třemi částmi ve shodě): 22701 rozhodnutí, z toho WAIT 20568 (90.6 %), BUY/SELL 2133. Blokovalo: Prostor k cíli 17295×; Spread 6928×; RSI extrém 4007×; Časový limit 3163×
Bias ex post (cena o hodinu později ve směru biasu): BEARISH 18790/38144 (49.3 %); BULLISH 13641/29031 (47.0 %)
Nové stavy: WATCH v 37.2 % rozhodnutí, splněný setup v 3.9 %; podle strategie: breakout: watch 6063, trigger 749, zaniklý 27; meanrev: watch 3980, trigger 446, zaniklý 320; pullback: watch 30252, trigger 2903, zaniklý 11244

| trh / režim | BUY | SELL | WAIT | NO DATA | ERROR |
|---|---|---|---|---|---|
| Akcie CFD / bez trendu | 0.0 % | 0.0 % | 100.0 % | 0.0 % | 0.0 % |
| Akcie CFD / trend | 0.0 % | 0.0 % | 100.0 % | 0.0 % | 0.0 % |
| Forex / bez trendu | 0.7 % | 0.6 % | 98.7 % | 0.0 % | 0.0 % |
| Forex / trend | 1.4 % | 2.4 % | 96.1 % | 0.0 % | 0.0 % |
| Komodity / bez trendu | 0.5 % | 1.1 % | 98.4 % | 0.0 % | 0.0 % |
| Komodity / trend | 0.9 % | 3.4 % | 95.7 % | 0.0 % | 0.0 % |


## 2. Strategie – souhrnně přes instrumenty

Pravidlo pro ověření (stanoveno předem): souhrnně přes instrumenty na závěrečném testu: ≥ 100 obchodů, dolní mez 95% intervalu ⌀ R po nákladech > 0, p × 4 < 0,05, ⌀ R na validaci > 0, ≥ 4 ze 6 walk-forward úseků s ⌀ R > 0 a lepší než náhodné vstupy.

| strategie | vývoj | validace | závěrečný test | 95% interval ⌀ R (test) | p × 4 | kladné úseky | stav |
|---|---|---|---|---|---|---|---|
| v2.1 | 177 obch., 31 % zisk., PF 0.76, ⌀ -0.160 R, Σ -28.2 R, max. pokles 34.2 R | 101 obch., 38 % zisk., PF 1.01, ⌀ +0.009 R, Σ +0.9 R, max. pokles 10.0 R | 103 obch., 39 % zisk., PF 1.03, ⌀ +0.017 R, Σ +1.7 R, max. pokles 14.6 R | -0.232 … +0.287 | 1.000 | 2/6 | srovnání |
| TREND PULLBACK | 293 obch., 32 % zisk., PF 0.75, ⌀ -0.170 R, Σ -49.8 R, max. pokles 60.1 R | 149 obch., 32 % zisk., PF 0.73, ⌀ -0.185 R, Σ -27.5 R, max. pokles 37.2 R | 168 obch., 33 % zisk., PF 0.78, ⌀ -0.148 R, Σ -24.9 R, max. pokles 33.2 R | -0.334 … +0.049 | 1.000 | 0/6 | VÝZKUM |
| BREAKOUT | 142 obch., 42 % zisk., PF 1.14, ⌀ +0.082 R, Σ +11.6 R, max. pokles 14.9 R | 76 obch., 32 % zisk., PF 0.77, ⌀ -0.150 R, Σ -11.4 R, max. pokles 21.2 R | 84 obch., 36 % zisk., PF 0.93, ⌀ -0.045 R, Σ -3.8 R, max. pokles 13.9 R | -0.331 … +0.246 | 1.000 | 3/6 | VÝZKUM |
| MEAN REVERSION | 94 obch., 36 % zisk., PF 0.80, ⌀ -0.130 R, Σ -12.2 R, max. pokles 16.4 R | 46 obch., 37 % zisk., PF 0.75, ⌀ -0.162 R, Σ -7.5 R, max. pokles 13.1 R | 35 obch., 29 % zisk., PF 0.53, ⌀ -0.328 R, Σ -11.5 R, max. pokles 12.6 R | -0.664 … +0.036 | 1.000 | 1/6 | VÝZKUM |
| v2.1 s ≤ 1 indikátorem proti | 206 obch., 33 % zisk., PF 0.77, ⌀ -0.147 R, Σ -30.2 R, max. pokles 33.0 R | 117 obch., 38 % zisk., PF 1.02, ⌀ +0.011 R, Σ +1.3 R, max. pokles 12.5 R | 120 obch., 42 % zisk., PF 1.18, ⌀ +0.098 R, Σ +11.7 R, max. pokles 12.7 R | -0.136 … +0.333 | 0.848 | 4/6 | VÝZKUM |
| náhodný | 139 obch., 29 % zisk., PF 0.61, ⌀ -0.274 R, Σ -38.1 R, max. pokles 39.4 R | 65 obch., 32 % zisk., PF 0.69, ⌀ -0.199 R, Σ -12.9 R, max. pokles 18.3 R | 64 obch., 22 % zisk., PF 0.53, ⌀ -0.342 R, Σ -21.9 R, max. pokles 27.0 R | -0.609 … -0.043 | 1.000 | 0/6 | srovnání |

**TREND PULLBACK** – kontroly: ✓ ≥ 100 obchodů v testu; ✗ dolní mez intervalu > 0; ✗ p × 4 < 0,05; ✗ validace ⌀ R > 0; ✗ ≥ 4/6 úseků kladných; ✓ lepší než náhodné vstupy

**BREAKOUT** – kontroly: ✗ ≥ 100 obchodů v testu; ✗ dolní mez intervalu > 0; ✗ p × 4 < 0,05; ✗ validace ⌀ R > 0; ✗ ≥ 4/6 úseků kladných; ✓ lepší než náhodné vstupy

**MEAN REVERSION** – kontroly: ✗ ≥ 100 obchodů v testu; ✗ dolní mez intervalu > 0; ✗ p × 4 < 0,05; ✗ validace ⌀ R > 0; ✗ ≥ 4/6 úseků kladných; ✓ lepší než náhodné vstupy

**v2.1 s ≤ 1 indikátorem proti** – kontroly: ✓ ≥ 100 obchodů v testu; ✗ dolní mez intervalu > 0; ✗ p × 4 < 0,05; ✓ validace ⌀ R > 0; ✓ ≥ 4/6 úseků kladných; ✓ lepší než náhodné vstupy

## 3. Závěrečný test podle instrumentů

| instrument | v2.1 | TREND PULLBACK | BREAKOUT | MEAN REVERSION | v2.1 s ≤ 1 indikátorem proti |
|---|---|---|---|---|---|
| EUR/USD | 26 obch., 31 % zisk., PF 0.48, ⌀ -0.368 R, Σ -9.6 R, max. pokles 10.2 R | 32 obch., 34 % zisk., PF 0.84, ⌀ -0.107 R, Σ -3.4 R, max. pokles 7.5 R | 24 obch., 33 % zisk., PF 0.82, ⌀ -0.114 R, Σ -2.7 R, max. pokles 5.3 R | 4 obch., 50 % zisk., PF 0.85, ⌀ -0.078 R, Σ -0.3 R, max. pokles 2.0 R | 29 obch., 31 % zisk., PF 0.58, ⌀ -0.298 R, Σ -8.6 R, max. pokles 10.1 R |
| GBP/USD | 20 obch., 30 % zisk., PF 0.82, ⌀ -0.119 R, Σ -2.4 R, max. pokles 4.1 R | 27 obch., 30 % zisk., PF 0.64, ⌀ -0.237 R, Σ -6.4 R, max. pokles 6.4 R | 11 obch., 27 % zisk., PF 0.40, ⌀ -0.436 R, Σ -4.8 R, max. pokles 5.0 R | 1 obch., 0 % zisk., PF 0.00, ⌀ -1.012 R, Σ -1.0 R, max. pokles 1.0 R | 26 obch., 35 % zisk., PF 1.01, ⌀ +0.007 R, Σ +0.2 R, max. pokles 5.1 R |
| USD/JPY | 11 obch., 45 % zisk., PF 1.21, ⌀ +0.116 R, Σ +1.3 R, max. pokles 4.0 R | 33 obch., 33 % zisk., PF 0.67, ⌀ -0.216 R, Σ -7.1 R, max. pokles 11.4 R | 15 obch., 40 % zisk., PF 1.21, ⌀ +0.128 R, Σ +1.9 R, max. pokles 3.0 R | 11 obch., 27 % zisk., PF 0.42, ⌀ -0.424 R, Σ -4.7 R, max. pokles 7.2 R | 15 obch., 47 % zisk., PF 1.37, ⌀ +0.198 R, Σ +3.0 R, max. pokles 5.0 R |
| XAU/USD | 18 obch., 61 % zisk., PF 3.17, ⌀ +0.669 R, Σ +12.0 R, max. pokles 2.0 R | 25 obch., 36 % zisk., PF 1.00, ⌀ +0.000 R, Σ +0.0 R, max. pokles 6.2 R | 13 obch., 38 % zisk., PF 0.96, ⌀ -0.034 R, Σ -0.4 R, max. pokles 5.1 R | 6 obch., 33 % zisk., PF 0.97, ⌀ -0.023 R, Σ -0.1 R, max. pokles 2.0 R | 19 obch., 63 % zisk., PF 3.73, ⌀ +0.798 R, Σ +15.2 R, max. pokles 2.0 R |
| XAG/USD | 18 obch., 39 % zisk., PF 1.19, ⌀ +0.106 R, Σ +1.9 R, max. pokles 4.8 R | 23 obch., 30 % zisk., PF 0.69, ⌀ -0.222 R, Σ -5.1 R, max. pokles 6.3 R | 11 obch., 18 % zisk., PF 0.42, ⌀ -0.482 R, Σ -5.3 R, max. pokles 6.2 R | 5 obch., 0 % zisk., PF 0.00, ⌀ -1.012 R, Σ -5.1 R, max. pokles 5.1 R | 19 obch., 53 % zisk., PF 1.47, ⌀ +0.216 R, Σ +4.1 R, max. pokles 3.0 R |
| WTI/USD | 10 obch., 30 % zisk., PF 0.78, ⌀ -0.157 R, Σ -1.6 R, max. pokles 5.2 R | 28 obch., 32 % zisk., PF 0.85, ⌀ -0.100 R, Σ -2.8 R, max. pokles 9.9 R | 10 obch., 60 % zisk., PF 3.05, ⌀ +0.754 R, Σ +7.5 R, max. pokles 2.0 R | 8 obch., 38 % zisk., PF 0.93, ⌀ -0.037 R, Σ -0.3 R, max. pokles 3.1 R | 12 obch., 25 % zisk., PF 0.73, ⌀ -0.171 R, Σ -2.0 R, max. pokles 6.3 R |
| AAPL | 0 obchodů | 0 obchodů | 0 obchodů | 0 obchodů | 0 obchodů |
| NVDA | 0 obchodů | 0 obchodů | 0 obchodů | 0 obchodů | 0 obchodů |
| MSFT | 0 obchodů | 0 obchodů | 0 obchodů | 0 obchodů | 0 obchodů |
| TSLA | 0 obchodů | 0 obchodů | 0 obchodů | 0 obchodů | 0 obchodů |

## 4. Podle tržního režimu (celé období, všechny instrumenty)

**v2.1**: bez trendu / volatilita nízká: 7 obch., 57 % zisk., PF 2.45, ⌀ +0.625 R, Σ +4.4 R, max. pokles 2.0 R; bez trendu / volatilita střední: 76 obch., 33 % zisk., PF 0.87, ⌀ -0.088 R, Σ -6.7 R, max. pokles 12.3 R; bez trendu / volatilita vysoká: 60 obch., 27 % zisk., PF 0.52, ⌀ -0.334 R, Σ -20.0 R, max. pokles 25.8 R; trend / volatilita nízká: 19 obch., 53 % zisk., PF 1.87, ⌀ +0.417 R, Σ +7.9 R, max. pokles 4.1 R; trend / volatilita střední: 150 obch., 33 % zisk., PF 0.85, ⌀ -0.095 R, Σ -14.3 R, max. pokles 23.6 R; trend / volatilita vysoká: 69 obch., 42 % zisk., PF 1.08, ⌀ +0.044 R, Σ +3.0 R, max. pokles 7.7 R

**TREND PULLBACK**: bez trendu / volatilita nízká: 57 obch., 37 % zisk., PF 1.09, ⌀ +0.060 R, Σ +3.4 R, max. pokles 8.0 R; bez trendu / volatilita střední: 203 obch., 33 % zisk., PF 0.78, ⌀ -0.151 R, Σ -30.6 R, max. pokles 46.3 R; bez trendu / volatilita vysoká: 55 obch., 42 % zisk., PF 0.98, ⌀ -0.012 R, Σ -0.7 R, max. pokles 11.8 R; trend / volatilita nízká: 64 obch., 25 % zisk., PF 0.59, ⌀ -0.311 R, Σ -19.9 R, max. pokles 19.9 R; trend / volatilita střední: 188 obch., 26 % zisk., PF 0.56, ⌀ -0.323 R, Σ -60.7 R, max. pokles 65.0 R; trend / volatilita vysoká: 43 obch., 49 % zisk., PF 1.29, ⌀ +0.145 R, Σ +6.2 R, max. pokles 5.1 R

**BREAKOUT**: bez trendu / volatilita nízká: 50 obch., 48 % zisk., PF 1.50, ⌀ +0.288 R, Σ +14.4 R, max. pokles 5.8 R; bez trendu / volatilita střední: 112 obch., 29 % zisk., PF 0.70, ⌀ -0.207 R, Σ -23.2 R, max. pokles 29.8 R; bez trendu / volatilita vysoká: 26 obch., 54 % zisk., PF 1.52, ⌀ +0.232 R, Σ +6.0 R, max. pokles 3.2 R; trend / volatilita nízká: 23 obch., 61 % zisk., PF 2.88, ⌀ +0.754 R, Σ +17.3 R, max. pokles 4.0 R; trend / volatilita střední: 76 obch., 29 % zisk., PF 0.69, ⌀ -0.221 R, Σ -16.8 R, max. pokles 21.0 R; trend / volatilita vysoká: 15 obch., 47 % zisk., PF 0.80, ⌀ -0.097 R, Σ -1.5 R, max. pokles 4.8 R

**MEAN REVERSION**: bez trendu / volatilita nízká: 23 obch., 22 % zisk., PF 0.31, ⌀ -0.552 R, Σ -12.7 R, max. pokles 14.8 R; bez trendu / volatilita střední: 98 obch., 35 % zisk., PF 0.78, ⌀ -0.143 R, Σ -14.0 R, max. pokles 19.7 R; bez trendu / volatilita vysoká: 54 obch., 41 % zisk., PF 0.86, ⌀ -0.082 R, Σ -4.5 R, max. pokles 7.4 R

**v2.1 s ≤ 1 indikátorem proti**: bez trendu / volatilita nízká: 9 obch., 44 % zisk., PF 1.47, ⌀ +0.262 R, Σ +2.4 R, max. pokles 3.0 R; bez trendu / volatilita střední: 94 obch., 35 % zisk., PF 0.88, ⌀ -0.080 R, Σ -7.5 R, max. pokles 14.4 R; bez trendu / volatilita vysoká: 81 obch., 30 % zisk., PF 0.64, ⌀ -0.229 R, Σ -18.6 R, max. pokles 24.9 R; trend / volatilita nízká: 18 obch., 56 % zisk., PF 2.12, ⌀ +0.502 R, Σ +9.0 R, max. pokles 3.0 R; trend / volatilita střední: 165 obch., 33 % zisk., PF 0.88, ⌀ -0.078 R, Σ -12.9 R, max. pokles 24.0 R; trend / volatilita vysoká: 76 obch., 49 % zisk., PF 1.28, ⌀ +0.137 R, Σ +10.4 R, max. pokles 8.0 R

## 5. Stabilita – walk-forward úseky (souhrnně)

| strategie | úsek 1 | úsek 2 | úsek 3 | úsek 4 | úsek 5 | úsek 6 |
|---|---|---|---|---|---|---|
| v2.1 | 43 / +0.32 R | 68 / -0.28 R | 66 / -0.34 R | 62 / +0.12 R | 81 / -0.04 R | 61 / -0.03 R |
| TREND PULLBACK | 80 / -0.06 R | 99 / -0.15 R | 115 / -0.27 R | 90 / -0.33 R | 111 / -0.11 R | 115 / -0.09 R |
| BREAKOUT | 39 / +0.02 R | 53 / +0.25 R | 50 / -0.06 R | 43 / -0.17 R | 56 / -0.17 R | 61 / +0.03 R |
| MEAN REVERSION | 18 / -0.24 R | 39 / -0.14 R | 38 / -0.09 R | 31 / +0.02 R | 25 / -0.35 R | 24 / -0.42 R |
| v2.1 s ≤ 1 indikátorem proti | 53 / +0.29 R | 77 / -0.24 R | 76 / -0.36 R | 73 / +0.09 R | 89 / +0.02 R | 75 / +0.06 R |
| náhodný | 35 / -0.39 R | 53 / -0.30 R | 51 / -0.17 R | 47 / -0.29 R | 42 / -0.33 R | 40 / -0.18 R |

## 6. v2.6 MARKET DIRECTION – historické ověření

Pravidlo výběru prahu (stanoveno předem): práh |skóre| se vybírá jen na vývojovém období: nejvyšší podíl správných směrů na horizontu 1 h mezi prahy, které dávají BUY/SELL aspoň v 25 % rozhodnutí; při shodě nižší práh. Váhy jsou pevné. **Zvolený práh: 0.10** (= převaha 10/100). Směr používá stejnou funkci jako aplikace; budoucí pohyb ceny slouží jen k hodnocení. Instrumenty: 10.

**Práh v aplikaci: 0.25** (stanoven předem). Pokud žádný práh na vývojovém období nepřekoná 50 %, výběr podle predikce nemá oporu a aplikace drží předem zvolený popisný práh.

### Rozložení výsledků před a po (stejný vzorek, práh aplikace)

| část | vrstva | BUY | SELL | NEUTRAL | WAIT | NO DATA | ERROR |
|---|---|---|---|---|---|---|---|
| vývoj | před (v2.1) | 0.6 % | 1.2 % | 0.0 % | 87.4 % | 10.9 % | 0.0 % |
| vývoj | směr v2.6 | 32.0 % | 39.3 % | 28.4 % | 0.0 % | 0.3 % | 0.0 % |
| vývoj | vstup v2.6 | 0.6 % | 1.2 % | 0.0 % | 87.4 % | 10.9 % | 0.0 % |
| validace | před (v2.1) | 0.9 % | 1.3 % | 0.0 % | 96.0 % | 1.8 % | 0.0 % |
| validace | směr v2.6 | 35.2 % | 37.5 % | 27.0 % | 0.0 % | 0.3 % | 0.0 % |
| validace | vstup v2.6 | 0.9 % | 1.3 % | 0.0 % | 96.0 % | 1.8 % | 0.0 % |
| test | před (v2.1) | 0.8 % | 1.5 % | 0.0 % | 96.0 % | 1.7 % | 0.0 % |
| test | směr v2.6 | 30.5 % | 42.7 % | 26.6 % | 0.0 % | 0.3 % | 0.0 % |
| test | vstup v2.6 | 0.8 % | 1.5 % | 0.0 % | 96.0 % | 1.7 % | 0.0 % |
| celkem | před (v2.1) | 0.7 % | 1.3 % | 0.0 % | 91.7 % | 6.3 % | 0.0 % |
| celkem | směr v2.6 | 32.4 % | 39.7 % | 27.6 % | 0.0 % | 0.3 % | 0.0 % |
| celkem | vstup v2.6 | 0.7 % | 1.3 % | 0.0 % | 91.7 % | 6.3 % | 0.0 % |

Příčiny NO DATA (okno dat): 15min: málo uzavřených svíček 4993×; 1h: zastaralá data – poslední u 1537×; 15min: zastaralá data – poslední u 298×

### Kvalita směru podle prahu (podíl správného směru = cena se pohnula naznačeným směrem)

| práh | část | pokrytí BUY/SELL | 5 m | 15 m | 1 h | 1 h po spreadu | ⌀ pohyb 1 h v ATR (hrubě / po spreadu) |
|---|---|---|---|---|---|---|---|
| 0.10 ✓ | vývoj | 78.9 % | 49.4 % | 49.0 % | 48.8 % | 44.5 % | +0.002 / -0.128 |
| 0.10 ✓ | validace | 87.9 % | 49.2 % | 49.6 % | 49.8 % | 45.6 % | +0.004 / -0.126 |
| 0.10 ✓ | test | 87.2 % | 49.6 % | 49.8 % | 51.2 % | 47.4 % | +0.066 / -0.052 |
| 0.20 | vývoj | 68.9 % | 49.2 % | 48.8 % | 48.6 % | 44.4 % | +0.003 / -0.127 |
| 0.20 | validace | 77.4 % | 48.9 % | 49.4 % | 49.4 % | 45.2 % | -0.008 / -0.139 |
| 0.20 | test | 77.0 % | 49.9 % | 50.2 % | 51.5 % | 47.7 % | +0.069 / -0.049 |
| 0.25 | vývoj | 65.0 % | 49.2 % | 48.8 % | 48.5 % | 44.3 % | +0.001 / -0.129 |
| 0.25 | validace | 72.9 % | 48.8 % | 49.4 % | 49.3 % | 45.1 % | -0.008 / -0.139 |
| 0.25 | test | 73.1 % | 49.7 % | 50.1 % | 51.4 % | 47.6 % | +0.067 / -0.052 |
| 0.30 | vývoj | 59.7 % | 49.0 % | 48.7 % | 48.5 % | 44.3 % | +0.005 / -0.125 |
| 0.30 | validace | 67.3 % | 48.7 % | 49.3 % | 49.1 % | 44.8 % | -0.014 / -0.145 |
| 0.30 | test | 67.9 % | 49.9 % | 50.2 % | 51.4 % | 47.6 % | +0.068 / -0.050 |
| 0.40 | vývoj | 49.2 % | 48.8 % | 48.5 % | 48.6 % | 44.4 % | +0.007 / -0.126 |
| 0.40 | validace | 55.4 % | 48.4 % | 48.9 % | 48.5 % | 44.2 % | -0.021 / -0.156 |
| 0.40 | test | 56.6 % | 49.7 % | 50.1 % | 51.0 % | 47.3 % | +0.073 / -0.046 |
| 0.50 | vývoj | 38.1 % | 48.7 % | 48.2 % | 48.7 % | 44.6 % | +0.013 / -0.119 |
| 0.50 | validace | 43.0 % | 48.1 % | 48.9 % | 48.2 % | 44.0 % | -0.033 / -0.170 |
| 0.50 | test | 45.0 % | 49.6 % | 49.9 % | 50.3 % | 46.8 % | +0.079 / -0.040 |

### Nedotčený test (zvolený práh)

* horizont 5m: správný směr 49.6 % z 23599 signálů (95% interval po dnech 48.9 % – 50.3 %); naivní momentum (směr poslední hodiny) 48.8 %
* horizont 15m: správný směr 49.8 % z 23582 signálů (95% interval po dnech 48.9 % – 50.8 %); naivní momentum (směr poslední hodiny) 48.6 %
* horizont 1h: správný směr 51.2 % z 23503 signálů (95% interval po dnech 49.6 % – 52.9 %); naivní momentum (směr poslední hodiny) 48.3 %
* práh aplikace 0.25, horizont 5m: správný směr 49.7 % z 19776 (95% interval 49.0 % – 50.5 %)
* práh aplikace 0.25, horizont 15m: správný směr 50.1 % z 19764 (95% interval 49.0 % – 51.1 %)
* práh aplikace 0.25, horizont 1h: správný směr 51.4 % z 19707 (95% interval 49.6 % – 53.1 %)
* citlivost na náklady (horizont 1 h, ⌀ pohyb v ATR po odečtení násobku spreadu): 0× spread +0.066; 1× spread -0.052; 2× spread -0.170; 3× spread -0.287
* Výkonnost potvrzených vstupů (vrstva TRADE CONFIRMATION, plné náklady): viz řádek v2.1 v kapitole 2 – od v2.6 se vstup proti MARKET DIRECTION nepotvrdí.
