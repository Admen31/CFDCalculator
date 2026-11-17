# Porovnání pravidel v2.0 a v2.1 (Yahoo Finance, 2026-11-17 09:02 UTC)

Zdroj: GitHub Actions běh 44051699442 (commit 743741c), `python scripts/compare_strategies.py`.

Bez historického filtru zpráv. Rozdělení času 60 % vývoj / 40 % test. Náklady: spread 1× za obchod, modelované náklady navíc 0.5× spread. Krátké období – výsledky jsou orientační, ne důkaz ziskovosti.

## Apple (AAPL, data AAPL (Yahoo), 24.08. – 16.11.2026, spread 0.05)

| pravidla | část | BUY | SELL | WAIT | NO DATA | bez nákladů | se spreadem | spread + náklady |
|---|---|---|---|---|---|---|---|---|
| v2.0 | vývoj | 17 | 1 | 1833 | 806 | 4 obch., 25 % zisk., PF 0.04, ⌀ -0.61 R, Σ -2.4 R, max. pokles 2.6 R | 4 obch., 25 % zisk., PF 0.03, ⌀ -0.64 R, Σ -2.5 R, max. pokles 2.6 R | 4 obch., 25 % zisk., PF 0.02, ⌀ -0.65 R, Σ -2.6 R, max. pokles 2.7 R |
| v2.0 | test | 0 | 8 | 1522 | 242 | 2 obch., 100 % zisk., PF –, ⌀ +0.28 R, Σ +0.6 R, max. pokles 0.0 R | 2 obch., 100 % zisk., PF –, ⌀ +0.26 R, Σ +0.5 R, max. pokles 0.0 R | 2 obch., 100 % zisk., PF –, ⌀ +0.25 R, Σ +0.5 R, max. pokles 0.0 R |
| v2.1 | vývoj | 22 | 1 | 2136 | 498 | 6 obch., 33 % zisk., PF 0.15, ⌀ -0.52 R, Σ -3.1 R, max. pokles 3.7 R | 6 obch., 33 % zisk., PF 0.14, ⌀ -0.55 R, Σ -3.3 R, max. pokles 3.8 R | 6 obch., 33 % zisk., PF 0.13, ⌀ -0.56 R, Σ -3.3 R, max. pokles 3.8 R |
| v2.1 | test | 0 | 8 | 1764 | 0 | 2 obch., 50 % zisk., PF 0.59, ⌀ -0.05 R, Σ -0.1 R, max. pokles 0.3 R | 2 obch., 50 % zisk., PF 0.47, ⌀ -0.07 R, Σ -0.1 R, max. pokles 0.3 R | 2 obch., 50 % zisk., PF 0.42, ⌀ -0.08 R, Σ -0.2 R, max. pokles 0.3 R |

## NVIDIA (NVDA, data NVDA (Yahoo), 24.08. – 16.11.2026, spread 0.05)

| pravidla | část | BUY | SELL | WAIT | NO DATA | bez nákladů | se spreadem | spread + náklady |
|---|---|---|---|---|---|---|---|---|
| v2.0 | vývoj | 6 | 5 | 1840 | 806 | 6 obch., 50 % zisk., PF 1.23, ⌀ +0.09 R, Σ +0.6 R, max. pokles 2.4 R | 6 obch., 50 % zisk., PF 1.14, ⌀ +0.06 R, Σ +0.3 R, max. pokles 2.5 R | 6 obch., 50 % zisk., PF 1.09, ⌀ +0.04 R, Σ +0.2 R, max. pokles 2.6 R |
| v2.0 | test | 0 | 26 | 1504 | 242 | 5 obch., 60 % zisk., PF 0.87, ⌀ -0.05 R, Σ -0.2 R, max. pokles 1.8 R | 5 obch., 60 % zisk., PF 0.82, ⌀ -0.07 R, Σ -0.3 R, max. pokles 1.9 R | 5 obch., 40 % zisk., PF 0.79, ⌀ -0.08 R, Σ -0.4 R, max. pokles 1.9 R |
| v2.1 | vývoj | 10 | 8 | 2141 | 498 | 8 obch., 50 % zisk., PF 1.33, ⌀ +0.15 R, Σ +1.2 R, max. pokles 2.7 R | 8 obch., 50 % zisk., PF 1.24, ⌀ +0.12 R, Σ +0.9 R, max. pokles 2.8 R | 8 obch., 50 % zisk., PF 1.20, ⌀ +0.10 R, Σ +0.8 R, max. pokles 2.9 R |
| v2.1 | test | 0 | 34 | 1738 | 0 | 5 obch., 80 % zisk., PF 3.64, ⌀ +0.53 R, Σ +2.6 R, max. pokles 1.0 R | 5 obch., 80 % zisk., PF 3.50, ⌀ +0.51 R, Σ +2.5 R, max. pokles 1.0 R | 5 obch., 80 % zisk., PF 3.43, ⌀ +0.50 R, Σ +2.5 R, max. pokles 1.0 R |

## Microsoft (MSFT, data MSFT (Yahoo), 24.08. – 16.11.2026, spread 0.05)

| pravidla | část | BUY | SELL | WAIT | NO DATA | bez nákladů | se spreadem | spread + náklady |
|---|---|---|---|---|---|---|---|---|
| v2.0 | vývoj | 15 | 0 | 1836 | 806 | 4 obch., 25 % zisk., PF 0.76, ⌀ -0.12 R, Σ -0.5 R, max. pokles 1.1 R | 4 obch., 25 % zisk., PF 0.73, ⌀ -0.14 R, Σ -0.6 R, max. pokles 1.1 R | 4 obch., 25 % zisk., PF 0.72, ⌀ -0.15 R, Σ -0.6 R, max. pokles 1.1 R |
| v2.0 | test | 3 | 1 | 1526 | 242 | 2 obch., 0 % zisk., PF 0.00, ⌀ -1.00 R, Σ -2.0 R, max. pokles 2.0 R | 2 obch., 0 % zisk., PF 0.00, ⌀ -1.01 R, Σ -2.0 R, max. pokles 2.0 R | 2 obch., 0 % zisk., PF 0.00, ⌀ -1.02 R, Σ -2.0 R, max. pokles 2.0 R |
| v2.1 | vývoj | 21 | 1 | 2137 | 498 | 8 obch., 38 % zisk., PF 0.39, ⌀ -0.38 R, Σ -3.1 R, max. pokles 3.1 R | 8 obch., 38 % zisk., PF 0.37, ⌀ -0.40 R, Σ -3.2 R, max. pokles 3.2 R | 8 obch., 38 % zisk., PF 0.36, ⌀ -0.41 R, Σ -3.3 R, max. pokles 3.3 R |
| v2.1 | test | 3 | 3 | 1766 | 0 | 3 obch., 33 % zisk., PF 0.23, ⌀ -0.51 R, Σ -1.5 R, max. pokles 1.5 R | 3 obch., 33 % zisk., PF 0.22, ⌀ -0.53 R, Σ -1.6 R, max. pokles 1.6 R | 3 obch., 33 % zisk., PF 0.21, ⌀ -0.54 R, Σ -1.6 R, max. pokles 1.6 R |

## Tesla (TSLA, data TSLA (Yahoo), 24.08. – 16.11.2026, spread 0.05)

| pravidla | část | BUY | SELL | WAIT | NO DATA | bez nákladů | se spreadem | spread + náklady |
|---|---|---|---|---|---|---|---|---|
| v2.0 | vývoj | 2 | 2 | 1847 | 806 | 3 obch., 33 % zisk., PF 0.08, ⌀ -0.61 R, Σ -1.8 R, max. pokles 1.8 R | 3 obch., 33 % zisk., PF 0.07, ⌀ -0.63 R, Σ -1.9 R, max. pokles 1.9 R | 3 obch., 33 % zisk., PF 0.07, ⌀ -0.64 R, Σ -1.9 R, max. pokles 1.9 R |
| v2.0 | test | 11 | 5 | 1514 | 242 | 4 obch., 50 % zisk., PF 1.23, ⌀ +0.09 R, Σ +0.4 R, max. pokles 1.5 R | 4 obch., 50 % zisk., PF 1.20, ⌀ +0.08 R, Σ +0.3 R, max. pokles 1.5 R | 4 obch., 50 % zisk., PF 1.19, ⌀ +0.07 R, Σ +0.3 R, max. pokles 1.6 R |
| v2.1 | vývoj | 7 | 4 | 2148 | 498 | 5 obch., 20 % zisk., PF 0.11, ⌀ -0.71 R, Σ -3.6 R, max. pokles 3.6 R | 5 obch., 20 % zisk., PF 0.10, ⌀ -0.73 R, Σ -3.7 R, max. pokles 3.7 R | 5 obch., 20 % zisk., PF 0.10, ⌀ -0.74 R, Σ -3.7 R, max. pokles 3.7 R |
| v2.1 | test | 17 | 5 | 1750 | 0 | 5 obch., 60 % zisk., PF 1.53, ⌀ +0.21 R, Σ +1.1 R, max. pokles 2.0 R | 5 obch., 60 % zisk., PF 1.50, ⌀ +0.20 R, Σ +1.0 R, max. pokles 2.0 R | 5 obch., 60 % zisk., PF 1.48, ⌀ +0.20 R, Σ +1.0 R, max. pokles 2.0 R |

## EUR/USD (EUR/USD, data EURUSD=X (Yahoo), 25.08. – 17.11.2026, spread 8e-05)

| pravidla | část | BUY | SELL | WAIT | NO DATA | bez nákladů | se spreadem | spread + náklady |
|---|---|---|---|---|---|---|---|---|
| v2.0 | vývoj | 12 | 215 | 9169 | 575 | 40 obch., 38 % zisk., PF 1.06, ⌀ +0.03 R, Σ +1.4 R, max. pokles 5.0 R | 40 obch., 38 % zisk., PF 0.91, ⌀ -0.06 R, Σ -2.5 R, max. pokles 5.8 R | 40 obch., 38 % zisk., PF 0.84, ⌀ -0.11 R, Σ -4.5 R, max. pokles 6.2 R |
| v2.0 | test | 63 | 131 | 6397 | 57 | 34 obch., 32 % zisk., PF 0.73, ⌀ -0.18 R, Σ -6.1 R, max. pokles 10.0 R | 34 obch., 29 % zisk., PF 0.62, ⌀ -0.28 R, Σ -9.6 R, max. pokles 11.7 R | 34 obch., 29 % zisk., PF 0.57, ⌀ -0.33 R, Σ -11.3 R, max. pokles 12.5 R |
| v2.1 | vývoj | 12 | 215 | 9169 | 575 | 40 obch., 38 % zisk., PF 1.06, ⌀ +0.03 R, Σ +1.4 R, max. pokles 5.0 R | 40 obch., 38 % zisk., PF 0.91, ⌀ -0.06 R, Σ -2.5 R, max. pokles 5.8 R | 40 obch., 38 % zisk., PF 0.84, ⌀ -0.11 R, Σ -4.5 R, max. pokles 6.2 R |
| v2.1 | test | 63 | 131 | 6397 | 57 | 34 obch., 32 % zisk., PF 0.73, ⌀ -0.18 R, Σ -6.1 R, max. pokles 10.0 R | 34 obch., 29 % zisk., PF 0.62, ⌀ -0.28 R, Σ -9.6 R, max. pokles 11.7 R | 34 obch., 29 % zisk., PF 0.57, ⌀ -0.33 R, Σ -11.3 R, max. pokles 12.5 R |

## GBP/USD (GBP/USD, data GBPUSD=X (Yahoo), 25.08. – 17.11.2026, spread 0.00012)

| pravidla | část | BUY | SELL | WAIT | NO DATA | bez nákladů | se spreadem | spread + náklady |
|---|---|---|---|---|---|---|---|---|
| v2.0 | vývoj | 16 | 115 | 9267 | 575 | 27 obch., 22 % zisk., PF 0.52, ⌀ -0.36 R, Σ -9.8 R, max. pokles 10.8 R | 27 obch., 22 % zisk., PF 0.44, ⌀ -0.48 R, Σ -12.9 R, max. pokles 13.6 R | 27 obch., 22 % zisk., PF 0.40, ⌀ -0.53 R, Σ -14.4 R, max. pokles 15.0 R |
| v2.0 | test | 111 | 80 | 6399 | 59 | 31 obch., 39 % zisk., PF 1.15, ⌀ +0.09 R, Σ +2.7 R, max. pokles 5.7 R | 31 obch., 39 % zisk., PF 0.95, ⌀ -0.03 R, Σ -1.0 R, max. pokles 8.1 R | 31 obch., 39 % zisk., PF 0.86, ⌀ -0.09 R, Σ -2.9 R, max. pokles 9.5 R |
| v2.1 | vývoj | 16 | 115 | 9267 | 575 | 27 obch., 22 % zisk., PF 0.52, ⌀ -0.36 R, Σ -9.8 R, max. pokles 10.8 R | 27 obch., 22 % zisk., PF 0.44, ⌀ -0.48 R, Σ -12.9 R, max. pokles 13.6 R | 27 obch., 22 % zisk., PF 0.40, ⌀ -0.53 R, Σ -14.4 R, max. pokles 15.0 R |
| v2.1 | test | 111 | 80 | 6399 | 59 | 31 obch., 39 % zisk., PF 1.15, ⌀ +0.09 R, Σ +2.7 R, max. pokles 5.7 R | 31 obch., 39 % zisk., PF 0.95, ⌀ -0.03 R, Σ -1.0 R, max. pokles 8.1 R | 31 obch., 39 % zisk., PF 0.86, ⌀ -0.09 R, Σ -2.9 R, max. pokles 9.5 R |

## USD/JPY (USD/JPY, data JPY=X (Yahoo), 25.08. – 17.11.2026, spread 0.012)

| pravidla | část | BUY | SELL | WAIT | NO DATA | bez nákladů | se spreadem | spread + náklady |
|---|---|---|---|---|---|---|---|---|
| v2.0 | vývoj | 195 | 65 | 9096 | 575 | 39 obch., 46 % zisk., PF 1.53, ⌀ +0.27 R, Σ +10.6 R, max. pokles 9.3 R | 39 obch., 46 % zisk., PF 1.36, ⌀ +0.20 R, Σ +7.7 R, max. pokles 10.0 R | 39 obch., 46 % zisk., PF 1.28, ⌀ +0.16 R, Σ +6.2 R, max. pokles 10.4 R |
| v2.0 | test | 98 | 76 | 6392 | 55 | 25 obch., 40 % zisk., PF 1.20, ⌀ +0.11 R, Σ +2.8 R, max. pokles 4.2 R | 25 obch., 40 % zisk., PF 1.03, ⌀ +0.02 R, Σ +0.5 R, max. pokles 5.5 R | 25 obch., 40 % zisk., PF 0.96, ⌀ -0.02 R, Σ -0.6 R, max. pokles 6.1 R |
| v2.1 | vývoj | 195 | 65 | 9096 | 575 | 39 obch., 46 % zisk., PF 1.53, ⌀ +0.27 R, Σ +10.6 R, max. pokles 9.3 R | 39 obch., 46 % zisk., PF 1.36, ⌀ +0.20 R, Σ +7.7 R, max. pokles 10.0 R | 39 obch., 46 % zisk., PF 1.28, ⌀ +0.16 R, Σ +6.2 R, max. pokles 10.4 R |
| v2.1 | test | 98 | 76 | 6392 | 55 | 25 obch., 40 % zisk., PF 1.20, ⌀ +0.11 R, Σ +2.8 R, max. pokles 4.2 R | 25 obch., 40 % zisk., PF 1.03, ⌀ +0.02 R, Σ +0.5 R, max. pokles 5.5 R | 25 obch., 40 % zisk., PF 0.96, ⌀ -0.02 R, Σ -0.6 R, max. pokles 6.1 R |

## Gold (XAU/USD, data GC=F (Yahoo), 09.09. – 17.11.2026, spread 0.35)

| pravidla | část | BUY | SELL | WAIT | NO DATA | bez nákladů | se spreadem | spread + náklady |
|---|---|---|---|---|---|---|---|---|
| v2.0 | vývoj | 25 | 151 | 7025 | 767 | 34 obch., 26 % zisk., PF 0.68, ⌀ -0.23 R, Σ -7.8 R, max. pokles 12.7 R | 34 obch., 26 % zisk., PF 0.65, ⌀ -0.26 R, Σ -8.8 R, max. pokles 13.3 R | 34 obch., 26 % zisk., PF 0.63, ⌀ -0.27 R, Σ -9.3 R, max. pokles 13.6 R |
| v2.0 | test | 17 | 144 | 4962 | 190 | 30 obch., 53 % zisk., PF 2.24, ⌀ +0.52 R, Σ +15.6 R, max. pokles 4.0 R | 30 obch., 53 % zisk., PF 2.13, ⌀ +0.49 R, Σ +14.7 R, max. pokles 4.1 R | 30 obch., 50 % zisk., PF 2.08, ⌀ +0.47 R, Σ +14.2 R, max. pokles 4.2 R |
| v2.1 | vývoj | 25 | 151 | 7025 | 767 | 34 obch., 26 % zisk., PF 0.68, ⌀ -0.23 R, Σ -7.8 R, max. pokles 12.7 R | 34 obch., 26 % zisk., PF 0.65, ⌀ -0.26 R, Σ -8.8 R, max. pokles 13.3 R | 34 obch., 26 % zisk., PF 0.63, ⌀ -0.27 R, Σ -9.3 R, max. pokles 13.6 R |
| v2.1 | test | 17 | 144 | 4962 | 190 | 30 obch., 53 % zisk., PF 2.24, ⌀ +0.52 R, Σ +15.6 R, max. pokles 4.0 R | 30 obch., 53 % zisk., PF 2.13, ⌀ +0.49 R, Σ +14.7 R, max. pokles 4.1 R | 30 obch., 50 % zisk., PF 2.08, ⌀ +0.47 R, Σ +14.2 R, max. pokles 4.2 R |

## Oil (WTI) (WTI/USD, data CL=F (Yahoo), 09.09. – 17.11.2026, spread 0.03)

| pravidla | část | BUY | SELL | WAIT | NO DATA | bez nákladů | se spreadem | spread + náklady |
|---|---|---|---|---|---|---|---|---|
| v2.0 | vývoj | 59 | 73 | 7041 | 793 | 29 obch., 38 % zisk., PF 1.11, ⌀ +0.06 R, Σ +1.8 R, max. pokles 5.7 R | 29 obch., 38 % zisk., PF 1.02, ⌀ +0.01 R, Σ +0.3 R, max. pokles 6.3 R | 29 obch., 38 % zisk., PF 0.98, ⌀ -0.01 R, Σ -0.4 R, max. pokles 6.7 R |
| v2.0 | test | 67 | 80 | 4976 | 189 | 18 obch., 33 % zisk., PF 0.96, ⌀ -0.02 R, Σ -0.4 R, max. pokles 5.0 R | 18 obch., 33 % zisk., PF 0.90, ⌀ -0.07 R, Σ -1.3 R, max. pokles 5.4 R | 18 obch., 33 % zisk., PF 0.86, ⌀ -0.10 R, Σ -1.7 R, max. pokles 5.6 R |
| v2.1 | vývoj | 59 | 73 | 7041 | 793 | 29 obch., 38 % zisk., PF 1.11, ⌀ +0.06 R, Σ +1.8 R, max. pokles 5.7 R | 29 obch., 38 % zisk., PF 1.02, ⌀ +0.01 R, Σ +0.3 R, max. pokles 6.3 R | 29 obch., 38 % zisk., PF 0.98, ⌀ -0.01 R, Σ -0.4 R, max. pokles 6.7 R |
| v2.1 | test | 67 | 80 | 4976 | 189 | 18 obch., 33 % zisk., PF 0.96, ⌀ -0.02 R, Σ -0.4 R, max. pokles 5.0 R | 18 obch., 33 % zisk., PF 0.90, ⌀ -0.07 R, Σ -1.3 R, max. pokles 5.4 R | 18 obch., 33 % zisk., PF 0.86, ⌀ -0.10 R, Σ -1.7 R, max. pokles 5.6 R |

## Souhrn všech instrumentů

| pravidla | část | bez nákladů | se spreadem | spread + náklady |
|---|---|---|---|---|
| v2.0 | vývoj | 186 obch., 35 % zisk., PF 0.93, ⌀ -0.04 R, Σ -8.0 R, max. pokles 15.9 R | 186 obch., 35 % zisk., PF 0.83, ⌀ -0.11 R, Σ -20.9 R, max. pokles 23.1 R | 186 obch., 35 % zisk., PF 0.78, ⌀ -0.15 R, Σ -27.3 R, max. pokles 28.8 R |
| v2.0 | test | 151 obch., 41 % zisk., PF 1.16, ⌀ +0.09 R, Σ +13.2 R, max. pokles 11.8 R | 151 obch., 40 % zisk., PF 1.02, ⌀ +0.01 R, Σ +1.8 R, max. pokles 17.3 R | 151 obch., 39 % zisk., PF 0.96, ⌀ -0.03 R, Σ -4.0 R, max. pokles 21.8 R |
| v2.1 | vývoj | 196 obch., 35 % zisk., PF 0.90, ⌀ -0.06 R, Σ -12.3 R, max. pokles 17.5 R | 196 obch., 35 % zisk., PF 0.80, ⌀ -0.13 R, Σ -25.4 R, max. pokles 28.1 R | 196 obch., 35 % zisk., PF 0.76, ⌀ -0.16 R, Σ -32.0 R, max. pokles 33.9 R |
| v2.1 | test | 153 obch., 42 % zisk., PF 1.20, ⌀ +0.11 R, Σ +16.6 R, max. pokles 11.0 R | 153 obch., 41 % zisk., PF 1.06, ⌀ +0.03 R, Σ +5.1 R, max. pokles 16.3 R | 153 obch., 41 % zisk., PF 0.99, ⌀ -0.00 R, Σ -0.6 R, max. pokles 20.8 R |

## Výsledky vyhodnocení všech svíček

| pravidla | BUY | SELL | WAIT | NO DATA | ERROR |
|---|---|---|---|---|---|
| v2.0 | 717 | 1178 | 84146 | 8027 | 0 |
| v2.1 | 743 | 1194 | 86304 | 5827 | 0 |

## Nejčastější důvody WAIT / NO DATA

**v2.0:** EMA 20/50 nesouhlasí (39810×); nedostatečná shoda (15571×); 1h graf (13757×); rezistence (13215×); 1h: zastaralá data (2917×); support (799×); 15min: zastaralá data (628×); spread (458×)

**v2.1:** Shoda indikátorů (53937×); 1h graf (14087×); rezistence (13347×); přeprodáno (1910×); překoupeno (1516×); 1h: zastaralá data (1117×); support (800×); spread (458×)
