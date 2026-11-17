# Changelog

## 2.3.0 – chytřejší signály, WATCH a barevné rozhraní (větev `v2.3-smart-signals-color-ui`)

### Rozhodování
* **MARKET BIAS** (BULLISH / BEARISH / NEUTRAL) se vyhodnotí vždy, když jsou platná data. Je to popis směru trhu,
  ne pokyn k obchodu. Skóre −4 až +4: trend 1h (váha 2), struktura EMA 15m (1), momentum 5m (1).
* **Tři obchodní nastavení**: TREND PULLBACK, BREAKOUT, MEAN REVERSION (`strategies.py`). Každé vrací stav
  `watch` / `trigger` / `invalid`, a k tomu co přesně chybí, vstup, SL, TP a poměr R:R.
* **WATCH** zobrazí blížící se příležitost: směr, strategii, co chybí a konkrétní cenovou nebo indikátorovou
  podmínku.
* **Potvrzený signál**: BUY/SELL vydávají dál pravidla v2.1 („SHODA TRENDU (v2.1)“), nezměněná. Nová strategie
  smí vydat BUY/SELL jen tehdy, když projde předem stanoveným testem mimo vzorek (`strategies.VALIDATED`).
  Do té doby se splněné nastavení zobrazuje jako „SETUP SPLNĚN · VÝZKUM“, nikdy jako signál.
* I splněné nastavení blokují stejné bezpečnostní filtry: spread, časový limit, zprávy, volatilita a platný SL.

### Výzkum
* `diagnostics.py`: diagnostika WAIT. Podíly BUY/SELL/WAIT/NO DATA/ERROR, první i všechny blokující podmínky,
  „jediná blokující podmínka“ s hypotetickým výsledkem obchodu po nákladech, situace s jasným směrem, rozdíly podle
  typu trhu a režimu, a přesnost biasu ex post.
* `validation.strategy_study` / `promotion`: každá strategie zvlášť proti v2.1 a náhodným vstupům, se stejnými
  náklady a časovým rozdělením 50/25/25, 6 walk-forward úseky, bootstrap a Bonferroni ×3.
* `scripts/strategy_lab.py`: celý postup na veřejných datech Yahoo. Běží v CI a výsledek nahraje jako artefakt
  `strategy-lab`.
* `engine.windows()` je sdílená iterace rozhodovacích okamžiků pro backtest i diagnostiku.

### Rychlost a API
* Tři časové rámce se stahují **současně** (výsledky se kontrolují v pevném pořadí 5m → 15m → 1h).
* **Cache svíček** (`CachedProvider`) pro celou relaci. Bez dotazu, dokud nemohla vzniknout nová uzavřená svíčka.
  Jinak se stáhnou jen nejnovější svíčky a sloučí se. Chyby se nikdy nezakryjí daty z cache.
* **Ochrana limitu Twelve Data** (výchozí 8 dotazů za minutu, nastavitelné). Krátce počká na volný slot, jinak
  vrátí srozumitelné „překročen limit“ dřív, než by dotaz odmítl server.
* Měření doby OCR, stahování jednotlivých rámců, kalendáře a výpočtu je vidět v „Detail analýzy“.
* Animace nikdy nezdržují výsledek. Panel se vyplní hned, jak výsledek dorazí.

### Rozhraní
* Paleta: zelená `#22C55E` (BUY / BULLISH / OK), červená `#EF4444` (SELL / BEARISH / zamítnuto / ERROR),
  žlutá `#FACC15` (WAIT / WATCH / upozornění).
* Každý stav má ikonu a slovo (▲ BUY, ▼ SELL, ■ WAIT, ◆ WATCH, ○ NO DATA, ⚠ ERROR), takže je čitelný i bez barvy.
  ERROR má navíc čárkovaný rámeček i kruh, aby si ho nikdo nespletl se SELL.
* Nový výsledkový panel: instrument, štítek BIAS, štítek PŘÍLEŽITOST (WATCH), POTVRZENÝ SIGNÁL, strategie,
  důvod, „Čeká se na“ (nebo vstup/SL/TP/R:R u platného signálu), filtry a čas dat.
* Karta se jemně podbarví barvou výsledku. Dlaždice indikátorů jsou podbarvené zeleně, červeně nebo žlutě podle role.
* **Omezit animace**: nastavení (výchozí hodnota podle Windows „Zobrazovat animace“). Při zapnutí se barvy
  i procenta mění okamžitě a točící se segment se nahradí statickým tečkovaným kruhem.

### Zachováno
OCR a automatické přepínání Trading 212, Twelve Data včetně diagnostiky XAG/USD, 8 modulů, backtest, demo deník,
stavy NO DATA/ERROR, uživatelská nastavení (nové klíče `reduced_motion`, `td_per_minute`) a Windows EXE.

## 2.2.1 a starší
Viz README: diagnostika XAG/USD (2.2.1), výzkumný backtest (2.2), plynulé rozhraní (2.1), automatické
rozpoznávání Trading 212 (2.0).
