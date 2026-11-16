# CFD Signal Calculator

Malá desktopová aplikace pro Windows, kterou lze nechat nad Trading 212. Rozpozná zvolený instrument
z vybrané oblasti obrazovky, stáhne svíčky z Twelve Data a vrátí **BUY / SELL / WAIT** s vysvětlením
a návrhem stop-lossu a take-profitu.

**Aplikace nikdy nezadává obchody.** Neobsahuje žádné napojení na broker, obchod zadáváte ručně.
Výsledky nejsou investiční doporučení a ziskovost strategie není ověřena.

## Instalace a spuštění (vývojově)

```bat
python -m venv .venv && .venv\Scripts\activate
pip install -e ".[dev]"
python -m cfdcalc
```

Požadavky: Windows 10/11, Python ≥ 3.12. OCR (RapidOCR) běží offline, nic dalšího se neinstaluje.

## Windows EXE

* Lokálně: `build_exe.bat` – vytvoří venv, spustí testy (při selhání EXE nevznikne) a PyInstallerem
  sestaví `dist\CFD Signal Calculator\CFD Signal Calculator.exe`. Ke sdílení zabalte celou složku do ZIP.
* V CI: workflow `.github/workflows/build.yml` na `windows-latest` spustí testy, sestaví EXE
  a nahraje jej jako artefakt `cfd-signal-calculator-windows`.
* Složka má kolem 300–450 MB (Qt, OpenCV a ONNX Runtime pro OCR). Volíme sestavení do složky, ne `--onefile`,
  protože jinak by se při každém startu rozbalovaly stovky MB.

## Ovládání

1. **⚙ Nastavení** – API klíč Twelve Data (zdarma na twelvedata.com), případně proměnná prostředí
   `TWELVEDATA_API_KEY`, která má přednost. Dále večerní limit (výchozí 21:00 místního času) a minimální počet minut
   do limitu (výchozí 60).
2. **▭ Oblast** – myší označte v Trading 212 místo, kde je název instrumentu (např. „EUR/USD“, „US 500“,
   „Gold“). Oblast se uloží.
3. Zadejte **spread z T212** (rozdíl BUY − SELL v cenových jednotkách). Předvyplněná hodnota je jen hrubý odhad.
4. **START** (kliknutí do kruhu). Aplikace nejdřív rozpozná instrument. Při nejisté shodě nabídne ruční výběr,
   který je k dispozici i přes tlačítko s názvem instrumentu.

### Ukazatel 1–100 %

Analýza má 20 skutečných kroků: instrument, 3× stažení a 3× ověření dat (5m, 15m, 1h), kalendář zpráv,
8 modulů, trend 1h, spread, večerní limit a rozhodnutí. Procento je `hotové kroky / 20`. Když krok selže
(API chyba, zastaralá data), analýza skončí s **WAIT** a ukazatel zůstane na dosaženém procentu
s poznámkou „přerušeno“.

## Pravidla signálu

| Část | Pravidlo |
|---|---|
| Data | Používají se jen **uzavřené** svíčky. Poslední uzavřená svíčka smí být stará nejvýš 1 interval + 3 min. Dále se kontroluje počet svíček (250), jejich pořadí a platnost OHLC. Když kterákoli kontrola selže, výsledek je WAIT. |
| Trend 1h | EMA20 > EMA50 a close > EMA50 znamená rostoucí trend, opačně klesající. Jinak bez trendu a WAIT. |
| EMA 20/50 | 15m EMA20 vs EMA50 a 5m close vs EMA20. Musí souhlasit s trendem 1h. |
| RSI(14) 5m | 50–70 je hlas pro BUY, 30–50 hlas pro SELL. Nad 70 blokuje BUY, pod 30 blokuje SELL. |
| MACD(12,26,9) 5m | Histogram > 0 je hlas pro BUY, < 0 hlas pro SELL. |
| VWAP 5m | Close vs VWAP dne (UTC). Bez objemů (forex, část komodit) modul nehlasuje. |
| Volume 5m | Objem ≥ průměr 20 svíček na rostoucí/klesající svíčce je hlas. Bez objemů nehlasuje. |
| ATR(14) | ATR 15m určuje SL. Když je ATR 5m pod 0,5× nebo nad 2,5× svého průměru, signál se blokuje. |
| Support/Resistance | Swingy 15m: když je protilehlá úroveň blíž než cíl (2R), směr se blokuje. |
| Fundamenty | High-impact zprávy měn instrumentu 60 min před až 30 min po vydání blokují signál. **Bez dat kalendáře = WAIT.** |
| Spread | Musí být > 0 a ≤ 15 % vzdálenosti SL. |
| Večerní limit | Do limitu musí zbývat aspoň nastavený počet minut. |
| Rozhodnutí | Pro BUY/SELL je potřeba aspoň 3 souhlasných hlasů, žádný hlas proti a žádný blokující filtr. |
| Úrovně | SL = 1,5 × ATR(15m), TP = 2R. Počítá se v `Decimal`, SL se zaokrouhluje **od ceny**, TP k vstupu. |

Ceny Twelve Data se mohou lišit od cen CFD v Trading 212 (spot vs. futures, přirážka brokera). Proto aplikace
u SL/TP ukazuje i vzdálenost od vstupu, kterou přenesete k ceně v T212.

## Backtest a demo režim

* **Backtest** – stejná funkce `evaluate()` jako živá analýza, na posledních až 5000 svíčkách 5m (zhruba
  17 obchodních dní, 3 API dotazy). Pozice je vždy jen jedna. Vstup je za close, spread se odečítá. Když SL i TP
  padnou do jedné svíčky, počítá se SL. Otevřené obchody se zavírají na večerním limitu. **Backtest nepoužívá
  historický filtr zpráv** a krátká historie není statistický důkaz.
* **Demo deník** – každý živý BUY/SELL se zapíše do `%APPDATA%\CFDSignalCalculator\journal.csv`. Tlačítko
  „Ověřit výsledky podle dat“ dohledá, zda signál dosáhl SL, TP nebo večerního limitu (výsledek v R).
* **Offline demo** (Nastavení) – syntetická data bez API klíče, jen pro vyzkoušení aplikace. Je jasně označené
  bannerem a výsledkem „DEMO“ a do deníku se nezapisuje.

## Předpoklady a omezení (neověřeno proti živému API)

Vývojové prostředí nemělo přístup k api.twelvedata.com. Proti skutečnému API se tedy neověřovalo následující:

* Formát `GET /time_series` (`values[]` s `datetime/open/high/low/close/volume`, `status: error`
  a `message`), parametry `timezone=UTC` a `order=asc` a hlavička `Authorization: apikey …`. Pokud API
  odpoví jinak, je výsledek chyba dat a WAIT.
* Symboly indexů a komodit (`SPX`, `NDX`, `DJI`, `DAX`, `FTSE`, `WTI/USD`, `XBR/USD`, `NG/USD`) a jejich
  dostupnost ve vašem tarifu. Nedostupný symbol se projeví jako chyba API a WAIT.
* Bezplatný tarif má limit 8 dotazů za minutu. Analýza spotřebuje 3 dotazy, backtest také 3.
* Data akcií mohou být zpožděná nebo mimo obchodní hodiny staré. Taková data se zamítnou jako zastaralá a výsledek
  je WAIT.
* Ekonomický kalendář je neoficiální týdenní feed Forex Factory (`nfs.faireconomy.media`), uložený
  v mezipaměti na 1 h a důvěryhodný nejvýš 6 h. Earnings jednotlivých akcií se nesledují.
* OCR bylo ověřeno na vykresleném textu, ne na skutečném snímku Trading 212. Pokud rozpoznání selže, zúžte
  oblast jen na název instrumentu.
* API klíč se ukládá nešifrovaně do `%APPDATA%\CFDSignalCalculator\app.ini`, případně ho nastavte proměnnou
  prostředí.

## Testy

```bat
set QT_QPA_PLATFORM=offscreen
python -m pytest -q
```

Testy nevolají síť (socket je zablokovaný) a používají syntetická data. Výsledky na syntetických datech
nejsou důkazem ziskovosti.
