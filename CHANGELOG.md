# Changelog

## 2.5.0 – široké pokrytí trhů a oprava NO DATA (větev `v2.5-multi-provider-market-coverage`)

* **Audit pokrytí** (`scripts/coverage_audit.py`, samostatný job v CI) ověřuje přes veřejné endpointy Twelve Data
  (`symbol_search?show_plan=true`) a Coinbase symbol, burzu, měnu, typ a potřebný tarif **každého** zdroje katalogu.
* **Katalog 37 → 167 instrumentů**: 43 forexových párů, 67 amerických akcií, 14 evropských akcií, 18 ETF,
  12 kryptoměn, 7 komodit, 6 indexů. Na tarifu Basic: 141 plná analýza, 9 jen směr, 17 vyžaduje vyšší tarif.
* **Zdroje dat u instrumentu** (`instruments.Source`): přesné, nebo referenční s popisem. Pořadí lze měnit
  v katalogu. Všechny rámce vždy z jednoho zdroje.
* **Coinbase Exchange** jako nový poskytovatel (krypto, bez klíče), Twelve Data jako záloha.
* **Tarif Twelve Data** v Nastavení: symboly mimo tarif se nestahují a hned se ukáže důvod.
* **Referenční data** dávají jen směr: žádný vstup, SL, TP, Risk ani zápis do deníku. Ve výsledku je jasný štítek.
* **Limity API**: Retry-After, místní denní limit 800, kredity z hlaviček odpovědí, cache rozlišuje burzy.
* **NO DATA**: víkend = zavřený trh (WAIT), nové kategorie (zastaralá data, málo svíček, nenamapováno).
  Týdenní kalendář zpráv platí až 24 h. Bias a WATCH se spočítají i bez kalendáře.
* **Stránka Dostupnost tržních dat** a **přidání instrumentu z adresáře symbolů** s kontrolou identity a obchodních
  hodin burzy.
* **Výzkum**: předem stanovený test pravidla „0 indikátorů proti“ (varianta ≤ 1 proti) se stejnými náklady,
  walk-forward a holdoutem, Bonferroni ×4.


## 2.4.0 – Risk management: velikost CFD pozice podle rizika účtu (větev `v2.4-risk-position-sizing`)

* **Můj účet** (Risk ▸ → Účet…): hodnota účtu, měna (CZK, EUR, USD, GBP, PLN, CHF), riziko na obchod (výchozí 2 %,
  rychlé volby 0,5 / 1 / 1,5 / 2 %), volitelný limit nominální hodnoty pozice v % účtu a volitelná volná marže.
  Ukládá se jen lokálně, nic se nečte z Trading 212.
* **Specifikace instrumentu** (Risk ▸ → Specifikace…): velikost kontraktu, minimální množství, krok, maximální
  množství, maržový požadavek. Vyplňuje je uživatel podle Trading 212. Aplikace žádnou hodnotu nedoplňuje, takže
  bez nich ukáže NELZE SPOČÍTAT.
* **Výpočet** (`risk.py`, Decimal): rizikový rozpočet = equity × riziko %, riziko na jednotku =
  (|vstup − SL| + spread) × kontrakt × kurz, množství = rozpočet / riziko na jednotku, zaokrouhlené dolů na krok.
  Platí zároveň limit expozice, volná marže a maximální množství. Riziko, nominální hodnota a marže jsou
  oddělené veličiny.
* Je-li i minimální množství nad limitem, výsledek je „POZICE JE PŘÍLIŠ RIZIKOVÁ – NEOTVÍRAT PODLE TOHOTO PLÁNU“
  (nebo NEDOSTATEČNÁ MARŽE / PŘEKROČEN LIMIT EXPOZICE). Větší riziko se nikdy nenavrhuje.
* **Kurz** měny kotace → měna účtu: Twelve Data `/exchange_rate` (na pozadí, jen když je to poslední chybějící údaj,
  platný 1 h), nebo ruční kurz (platný 24 h). Bez kurzu se množství nespočítá.
* **Napojení na analýzu**: potvrzený BUY/SELL předá vstup, SL a TP a souhrnná karta ukáže „max N ks“. Výzkumné
  nastavení a ručně upravená čísla dávají jen ORIENTAČNÍ scénář. U WAIT, WATCH, NO DATA a ERROR se nic
  nepředvyplní. Data starší než 15 min a změna instrumentu množství zablokují.
* Barvy: zelená = v rámci limitu, žlutá = orientační nebo chybí údaje, červená = překročený limit nebo neplatný SL.
  Každý stav má i ikonu a slovo.
* Upozornění na skluz a gapy je přímo na stránce. Nic se neobchoduje.


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
