# Changelog

## 2.9.0 – stabilita a obchodní plán (větev `v2.9-stability-and-trade-plan`)

**Příčiny závad v2.8 (v kódu) a opravy**
1. *EUR/USD nerozpoznán, i když je vidět* a 2. *nejednoznačnost kvůli záložkám*: `recognize.match()` bralo každý
   nalezený název jako rovnocenného kandidáta. `locate()` vybíralo jen podle velikosti písma, a otevřené záložky
   Silver / NVIDIA / Gold / EUR/USD mají písmo stejné. Při START (`ui_instrument._start_after`) se pak vždy
   otevřel dialog. **Oprava** je hierarchie aktivního instrumentu: 1) název u tlačítek SELL/BUY, 2) samostatný
   název grafu, výrazně větší než záložky, 3) vizuálně odlišená aktivní záložka (jiné pozadí nebo jas textu),
   4) ostatní záložky a watchlist jen jako nabídka pro ruční výběr. Výška písma, poloha a vzhled se měří na
   inkoustu textu, ne na volném OCR boxu. Totéž platí uvnitř vybrané oblasti ▭.
3. *SELL a čtyři pomlčky*: `m15._confirm()` ukázalo ceny jen při splnění všech 10 podmínek. Nedostupný
   ekonomický kalendář (`events=None`) podmínku vždy shodil. **Oprava**: dvě vrstvy, A. SMĚR TRHU a
   B. OBCHODNÍ PLÁN se stavem **POTVRZENÝ** (vstup nyní), **PODMÍNĚNÝ** (stop pokyn po průrazu M15 rozsahu,
   limit při návratu k EMA 20, až po zprávě, bez zadaného spreadu) nebo **NEPLATNÝ** (s důvodem). Nedostupný
   kalendář plán neskryje, jen se vypíše varování.
4. *Pozice prakticky nedostupná*: POZICE se počítala jen u plně potvrzeného vstupu a specifikace byla schovaná
   v dialogu. **Oprava**: POZICE i pro podmíněný plán. Specifikace CFD aktuálního instrumentu se zadává přímo
   v záložce Portfolio a riziko, včetně návodu, jak jednotku množství Trading 212 ověřit. Množství se zobrazuje
   jako „(množství T212)“, nikdy jako loty bez ověření.
5. *API klíč*: nastavení je od v1 v `%APPDATA%\CFDSignalCalculator\app.ini` (nezávisí na složce s EXE). Kód,
   který by klíč mazal, nalezen nebyl. Klíč ale byl uložen nešifrovaně a aplikace neukazovala, kde ho hledá.
   **Oprava**: šifrování Windows DPAPI (jen pro daného uživatele), automatická migrace starého klíče, v Nastavení
   je vidět, kde klíč je, a je tam tlačítko „Otestovat připojení“ (jeden dotaz `api_usage`).
6. *Instrumenty bez dat*: omezení tarifu Twelve Data a indexy jen s referenčními ETF. Zdarma to opravit nejde,
   viz `docs/v28-audit-dat.md`.

**Obchodní plán (M15)**: SL za posledním M15 swingem + 0,2× ATR + spread, v rozmezí 1–3× ATR14. TP = 2R.
Ceny zaokrouhlené na tick (SL od ceny, TP k ceně) a pořadí kontrolované testy. Referenční data plán nikdy nemají.

**Ověření zabalené aplikace**: `CFD Signal Calculator.exe --selftest <složka>` spustí v CI na skutečné ploše
Windows GUI s přibaleným OCR proti nakreslenému oknu „Trading 212“ se záložkami a projde scénáře A–H a J.
`--selftest-verify` v novém procesu ověří, že se nastavení a klíč zachovaly (scénář I). Report a screenshoty jsou
přiložené k vydání.

## 2.8.0 – M15 trading ready (větev `v2.8-m15-trading-ready`)

**OCR rozpoznání Trading 212 (regrese a opravy)**
* **Příčina falešné nejednoznačnosti**: `recognize.score()` skládalo slova víceslovného názvu z *libovolných* řádků
  oblasti. Pravidlo bylo v kódu od první verze, ale s katalogem 167 instrumentů (v2.5) a širší oblastí začalo
  škodit: „Euro / **US** Dollar“ + „Leverage 1:**30**“ daly index „US 30“, takže EUR/USD skončilo jako
  „nejednoznačné“ a START se ptal na ruční výběr. Teď se smí spojit jen **dva sousední** řádky.
* Ceny, množství, marže, procenta a slova obchodního panelu (BUY, SELL, Quantity, Margin, Leverage, …, i česky)
  se před porovnáním odstraní. Nikdy se tak nepřečtou jako instrument.
* Typické záměny OCR v měnových párech se opraví jen na existující pár z katalogu: „EURIUSD“, „EUR|USD“,
  „XAU/USO“ → EUR/USD, XAU/USD.
* **Záložní čtení celého okna**: když oblast ▭ chybí, nebo neukazuje rozpoznatelný instrument (Trading 212 po
  změně šířky okna posune rozložení, v oblasti je cena), přečte se celé okno a vezme se instrument napsaný
  **největším písmem** (nadpis). Dva různé instrumenty stejně velkým písmem → „Instrument nerozpoznán“, nic se
  nehádá. Při průběžném sledování nejvýš jednou za 10 s, START a ⟳ vždy.
* Stav „Instrument nerozpoznán“ s nabídkou ručního výběru. Ruční výběr má vždy přednost.

**Data a „nedostatečné API“** (podrobně `docs/v28-audit-dat.md`)
* Hlavní signál potřebuje **jediný požadavek** na 15min svíčky místo tří (5m + 15m + 1h). Opakované kliknutí do
  60 s nedělá žádný požadavek. Na pozadí se stahuje jen po uzavření nové 15m svíčky (nejvýš 4× za hodinu).
* Další požadavky stahují jen nejnovější svíčky a slučují je s cache. Dva souběžné požadavky na stejnou řadu se
  nikdy nespustí, druhý použije výsledek prvního.
* Chybějící klíč, tarif, limit, mapování, počet svíček, stáří cache a poslední chyba poskytovatele jsou vidět
  v **Podrobnosti → Signál M15 → Diagnostika dat**.

**Signál jen z M15** (`m15.py`)
* Směr BUY / SELL / NEUTRAL / NO DATA jen z **uzavřených 15m svíček**: EMA 20/50/200, sklon EMA 50, MACD, RSI 14,
  struktura swingů. Žádná data 5m ani 1h, žádné čekání na H1.
* VSTUP / TP / SL jen pro **potvrzený vstup**: trend (EMA 200, EMA 20/50), RSI není extrémní, cena do 1× ATR od
  EMA 20, prostor ≥ 1R k nejbližšímu swingu, spread ≤ 15 % SL, ATR ≥ 3 ticky, čas do večerního limitu,
  ekonomický kalendář, přesná (ne referenční) data. SL = 1,5× ATR14(M15), TP = 2R.
* Jinak BUY/SELL jen jako **převažující směr** bez cen („jen směr – vstup nepotvrzen“), nebo NEUTRAL / NO DATA.
* Pod hodnotami je skutečný čas dat: uzavřená M15 svíčka a čas ceny.

**Portfolio a riziko**
* Záložka **Portfolio a riziko**: hodnota portfolia, měna (CZK, EUR, USD, …), riziko na obchod (2 %), riziko už
  otevřených pozic, max. celkové otevřené riziko, rezerva na skluz, volná marže, specifikace CFD. Ukládá se
  lokálně.
* **POZICE** na hlavní obrazovce z výpočtu v2.4 (`risk.size`, žádný druhý výpočet). Ten je rozšířený o celkové
  otevřené riziko, rezervu na skluz a kontrolu ztráty po zaokrouhlení dolů na krok. Chybí-li údaj: „NELZE
  SPOČÍTAT“, minimální množství nad limitem: „PŘÍLIŠ RIZIKOVÉ“.

**Rozhraní**: hlavní obrazovka obsahuje jen START → BUY/SELL, VSTUP, TP, SL, POZICE a jeden řádek s časem dat.
Podrobnosti mají záložky **Signál M15** a **Historický režim 5m/15m/1h**. Historický režim hlavní obrazovku ani
výpočet pozice neovlivňuje.

## 2.6.1 – opakovaný START a minimalistická hlavní obrazovka (větev `v2.6.1-repeatable-start-minimal-ui`)

* **Příčina „druhý START nefunguje“**: druhé a další kliknutí analýzu spustilo, ale mezipaměť svíček vrátila stejná
  data (do konce 5min periody žádný nový dotaz), výsledek se přepočítal za ~30 ms beze změny a VSTUP byla cena
  poslední *uzavřené* svíčky. Uživatel tedy neviděl žádnou změnu ani průběh.
* **Oprava**: každá analýza si vynutí nová 5m data (1 dotaz; 15m/1h z mezipaměti jen podle pravidel aktuálnosti).
  VSTUP je poslední dostupná cena (aktuální 5m svíčka) a TP/SL se pokaždé přepočítají. Tlačítko během výpočtu
  ukazuje „ANALYZUJI…“. Kliknutí během běžící analýzy se ignoruje (žádný duplicitní výpočet). Po chybě, NO DATA
  i timeoutu jde analýzu jedním kliknutím zopakovat.
* **Hlavní obrazovka**: jen velké tlačítko START → BUY (zelené) / SELL (červené) / NEUTRAL / NO DATA / ERROR
  a pod ním VSTUP, TP, SL. Výběr instrumentu zůstává nahoře. Vše ostatní (kruh průběhu, indikátory, vysvětlení,
  Risk, Detail, spread, Backtest, Deník, Trhy) je beze změny na stránce **Podrobnosti ▸**.
* **VSTUP / TP / SL** (`analysis.trade_levels`): SL = vstup ∓ 1,5 × ATR(15m), TP = 2R. Zaokrouhlení na tick
  (SL od ceny, TP k ceně), kontrola minimální vzdálenosti (≥ 3 ticky), spreadu (≤ 15 % vzdálenosti SL), platnosti
  a stran. Co nejde spočítat bezpečně, ukáže „–“. U referenčních dat se ceny nezobrazují.
* Průběžné obnovování je nově ve výchozím stavu vypnuté (šetří limit Twelve Data); lze ho zapnout v Nastavení.
* Testy: START → BUY → SELL → BUY, chyba API → opakování, změna instrumentu bez starých cen, opakované kliknutí
  během výpočtu, timeout → opakování, obsah hlavní obrazovky.


## 2.6.0 – okamžitý směr trhu (větev `v2.6-instant-market-direction`)

* **MARKET DIRECTION** (`direction.py`): transparentní vážené hlasování (EMA, sklon, cena vs EMA na 5m/15m/1h, RSI,
  MACD a momentum, struktura 15m, VWAP a objem). Výsledek BUY/SELL/NEUTRAL, převaha 0–100, poměr argumentů,
  kvalita dat a tři hlavní důvody.
* **TRADE CONFIRMATION** zůstává samostatná vrstva s filtry v2.1. Vstup se nepotvrdí proti opačnému směru trhu.
  Filtry nikdy neskryjí směr.
* **Částečná data**: když chybí jeden rámec, směr se spočítá s nižší kvalitou dat. Vstup v takovém případě NO DATA.
* **Nová hlavní obrazovka**: velký barevný směr, kruh s převahou, poměrový pruh BUY/SELL, trend, kvalita dat,
  čip obchodního vstupu, důvod nepotvrzení, tři důvody. Tlačítko START/REFRESH/ZRUŠIT.
* **Rychlost**: předchozí výsledek se zobrazí okamžitě a je označený; průběžné obnovování každou minutu. Odezva
  se měří (medián a p95 pro cache hit/miss, krok v CI).
* **Historické ověření** v laboratoři (kapitola 6): rozložení před/po, příčiny NO DATA, přesnost směru na 5m/15m/1h,
  vývoj/validace/nedotčený test, interval spolehlivosti po dnech, citlivost na spread, srovnání s naivním momentem.
  Výsledek: **žádná prediktivní výhoda směru**, převaha je popis, ne pravděpodobnost.


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
