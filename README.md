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
2. Otevřete **Trading 212** (desktopovou aplikaci, nebo web v prohlížeči jako aktivní záložku) a zvolte instrument.
3. Zadejte **spread z T212** (rozdíl BUY − SELL v cenových jednotkách). Předvyplněná hodnota je jen hrubý odhad.
4. **START** (kliknutí do kruhu). Analyzuje se vždy jen potvrzený instrument (viz níže).

### Ukazatel 1–100 % a plynulé rozhraní (verze 2.1)

* Analýza má 20 skutečných kroků: instrument, 3× stažení a 3× ověření dat (5m, 15m, 1h), kalendář zpráv,
  8 modulů, trend 1h, spread, časový limit a rozhodnutí. Procento je `hotové kroky / 20`, kruh se k němu plynule
  dotáčí.
* Při čekání na Twelve Data se kolem kruhu točí krátký segment s textem „čekám na Twelve Data…“. Je to jen
  znamení, že se čeká; nejde o smyšlená procenta.
* **Kliknutím na kruh běžící analýzu zrušíte.** Analýza má navíc celkový časový limit 75 s a každý síťový dotaz
  15 s. Výsledek zrušené analýzy se nikdy nezobrazí.
* Okno má pevnou velikost a při změnách neposkakuje. Barvy START/BUY/SELL/WAIT/NO DATA a dlaždice indikátorů se
  mění plynulým přechodem. Překresluje se jen to, co se opravdu změnilo.
* OCR model se načítá na pozadí hned po zobrazení okna. START použije čtení Trading 212, které právě běží,
  místo aby čekal ve frontě. Čtení, které visí déle než 8 s, START neblokuje.
* Při zavření okna se pracovní vlákna bezpečně ukončí.

## Automatické rozpoznávání Trading 212 (od verze 2.0)

Nastavení stačí udělat **jednou**:

1. Přepněte nahoře na **AUTO**.
2. Klikněte na **▭** a myší označte v okně Trading 212 **jen název aktivního instrumentu** (např. „NVIDIA“,
   „EUR/USD“). Neoznačujte lištu s více instrumenty (záložky, watchlist), protože to je nejednoznačné.
3. Hotovo. Oblast se uloží **relativně k oknu Trading 212**. Funguje i po přesunutí okna, změně velikosti, na jiném
   monitoru a při měřítku Windows 100/125/150 %.

Jak to funguje:

* Aplikace najde okno podle titulku „Trading 212“. U prohlížeče to je titulek aktivní záložky, takže se čte jen
  zobrazená záložka.
* Snímá se pouze označená oblast okna, ne celá plocha. Okno se vykreslí do paměti, takže to funguje i tehdy, když
  ho kalkulačka (vždy navrchu) částečně zakrývá. Když obsah nejde bezpečně získat (okno je minimalizované,
  zakryté, zavřené nebo menší než oblast), OCR se neprovádí a stav to ukáže.
* S volbou **Průběžně sledovat** (Nastavení, interval 2–3 s) se čte opakovaně. OCR běží mimo grafické
  rozhraní, takže okno nezamrzá. Změna instrumentu se potvrdí až po **dvou shodných čteních** po sobě.
* **⟳** načte instrument z Trading 212 jednorázově, i v režimu RUČNĚ.
* Řádek stavu: zelená = vidím instrument, oranžová = nejisté nebo nečitelné, červená = okno nenalezeno.
* **RUČNĚ**: instrument vyberete vyhledávacím polem (název, ticker nebo alias, např. „nvda“, „Germany 40“),
  tlačítky oblíbených (★) a naposledy použitých instrumentů. Ruční volba přepne do RUČNĚ, aby ji AUTO nepřepsal.

Pravidla bezpečnosti:

* START v režimu AUTO **vždy nejdřív znovu přečte Trading 212** a analyzuje jen jednoznačně rozpoznaný
  instrument.
* Při nízké jistotě, více instrumentech v oblasti nebo nečitelném okně aplikace nic neanalyzuje. Ukáže důvod
  a kandidáty k potvrzení. Potvrzený text si zapamatuje.
* Když se instrument změní, předchozí výsledek se označí jako **HISTORICKÝ** (šedě, i u indikátorů). To platí
  i při změně během běžící analýzy; takový signál se nezapíše do demo deníku.
* U výsledku je čas analýzy a použitý symbol.
* Rozpoznání nikdy nespouští analýzu ani obchod samo. Aplikace nepoužívá žádné API Trading 212 a nezadává obchody.

### Testovací postup na vašem počítači

Automatické testy (GitHub Actions, Windows) ověřují skutečné hledání okna, snímání a OCR na **zkušebním okně**
s titulkem „Trading 212“. Se skutečným Trading 212 jsem to ověřit nemohl. Prosím projděte:

1. Trading 212 v prohlížeči (Chrome/Edge), instrument NVIDIA → AUTO → ▭ označit název → stav ukáže
   „Vidím NVIDIA“.
2. Přepněte v Trading 212 na EUR/USD → do ~5 s se nahoře objeví EUR/USD. Případný předchozí výsledek je
   HISTORICKÝ.
3. Kalkulačku posuňte přes okno Trading 212 (ne přes označený název) → rozpoznávání dál funguje.
4. Přesuňte nebo zvětšete okno prohlížeče, případně ho přesuňte na druhý monitor → funguje bez nového
   označení. Pokud se název v Trading 212 při změně šířky posune jinam, označte oblast znovu.
5. Windows → Nastavení → Obrazovka → Měřítko 125 % a 150 % → funguje bez nového označení.
6. Otevřete v prohlížeči jinou záložku → stav „Okno Trading 212 nenalezeno“. Minimalizujte okno → stav
   „minimalizované“. V obou případech START nic neanalyzuje bez vašeho potvrzení.
7. Spusťte START a během analýzy přepněte instrument → výsledek bude HISTORICKÝ.
8. Kalkulačku zakryjte přes označený název → buď rozpozná správně, nebo hlásí „nelze bezpečně přečíst“,
   nikdy jiný instrument.

Pokud něco nesedí, pošlete text ze stavového řádku a snímek okna.

## Výsledky analýzy (verze 2.1)

| Výsledek | Význam |
|---|---|
| **BUY / SELL** | Indikátory profilu souhlasí s trendem 1h a **všechny** bezpečnostní filtry prošly. Jen tehdy se zobrazí SL a TP. |
| **WAIT** | Legitimní „neobchodovat“: bez trendu, indikátory si odporují nebo některý filtr blokuje. Důvod je vždy vypsaný. |
| **NO DATA** | Analýza nemá dost spolehlivých informací: chybějící nebo zastaralá data, výpadek API, nedostupný kalendář zpráv, nedostupný povinný indikátor, neověřené mapování symbolu, zrušená analýza. |
| **ERROR** | Technická chyba (výjimka v programu nebo v indikátoru). Nikdy nevede k obchodnímu signálu. |

Panel výsledku ukazuje:

* přesný důvod rozhodnutí;
* počet indikátorů **pro / proti / neutrální / nedostupné / nepoužito**;
* stav 10 bezpečnostních filtrů (✓ prošel, ✗ blokuje, – nehodnoceno);
* instrument, profil trhu, čas posledních dat a čas analýzy.

Tlačítko **Detail analýzy** ukáže všechny důvody, každý indikátor s hodnotou a rolí a detail každého filtru.
Každá dlaždice indikátoru ukazuje svou roli v rozhodnutí: pro, proti, neutrální, nedostupné (chybí data),
nepoužito (v profilu trhu se nepoužívá) nebo chyba.

## Pravidla signálu (verze 2.1)

**Profily trhů**

| Profil | Hlasující indikátory | Večerní limit (výchozí) | Obchodní hodiny |
|---|---|---|---|
| Akcie CFD | EMA 20/50, RSI, MACD, VWAP, Volume | 21:45 | NYSE/NASDAQ 9:30–16:00 New York |
| Indexy | jako akcie (indexy se zatím neanalyzují, chybí ověřené mapování) | 21:45 | – |
| Forex | EMA 20/50, RSI, MACD (VWAP a Volume se nepoužívají: zdroj nemá objemy) | 21:00 | 24 h v pracovní dny |
| Komodity | EMA 20/50, RSI, MACD (bez objemů) | 21:00 | 24 h v pracovní dny |

Večerní limit je v místním čase a v Nastavení ho lze změnit pro každý trh zvlášť. U akcií platí dřívější
z limitu a uzavření burzy. Mimo obchodní hodiny vrátí aplikace WAIT („trh je zavřený“) a API vůbec nevolá.

**Pravidla**

| Část | Pravidlo |
|---|---|
| Data | Jen **uzavřené** svíčky. Poslední smí být stará nejvýš 1 interval + 3 min; u akcií se doba, kdy byla burza zavřená, nezapočítává. Kontroluje se také počet svíček (250), pořadí a platnost OHLC. Selhání znamená NO DATA. |
| Trend 1h | EMA20 > EMA50 a close > EMA50 znamená rostoucí trend, opačně klesající. Jinak WAIT („bez jasného trendu“). |
| Hlasy | EMA 20/50, RSI (50–70 býčí, 30–50 medvědí), MACD (histogram), VWAP, Volume. Výpočty jsou stejné jako ve v2.0. |
| Shoda | EMA 20/50 musí jít se směrem trendu. Pro signál je potřeba aspoň **max(2, 60 % použitelných hlasů)** pro a **žádný** proti. Nepoužitý nebo nedostupný indikátor se nikdy nepočítá jako hlas proti. Jsou-li použitelné méně než 3 hlasy, výsledek je NO DATA. |
| RSI extrém | RSI ≥ 70 blokuje BUY, RSI ≤ 30 blokuje SELL. |
| Volatilita | ATR 5m pod 0,5× nebo nad 2,5× svého průměru blokuje. |
| Prostor k cíli | Protilehlá swingová úroveň 15m blíž než cíl (2R) blokuje. |
| Zprávy | High-impact zpráva měn instrumentu 60 min před až 30 min po vydání blokuje. Bez kalendáře NO DATA. |
| Spread | Musí být > 0 a ≤ 15 % vzdálenosti SL. |
| Časový limit | Do konce obchodování musí zbývat aspoň nastavený počet minut (výchozí 60). |
| Úrovně | SL = 1,5 × ATR(15m), TP = 2R, v `Decimal`. SL se zaokrouhluje **od ceny**, TP k vstupu. |

**Proč verze 2.0 tak často vracela WAIT** (podle kódu; četnosti z reálných dat viz níže):

1. Chybějící nebo zastaralá data, výpadek kalendáře a neověřený symbol vedly na WAIT. Ve 2.1 je to NO DATA,
   takže je vidět, že nejde o tržní situaci.
2. Jeden večerní limit 21:00 pro všechny trhy. U amerických akcií (otevírají 15:30 našeho času) při
   požadovaných 60 min rezervy zbývalo jen 15:30–20:00.
3. Forex a komodity nemají objemy, takže VWAP a Volume chyběly. Pravidlo „3 souhlasné hlasy“ pak znamenalo
   jednomyslnost všech tří zbylých indikátorů, zatímco akcie potřebovaly 3 z 5.
4. U akcií byla data v první hodině po otevření burzy „zastaralá“, protože poslední hodinová svíčka byla
   z předchozího dne.

Prahy filtrů (RSI, ATR, prostor 2R, spread 15 %, zprávy) zůstaly beze změny. Pravidla v2.0 jsou zmrazená
v `src/cfdcalc/legacy.py` kvůli porovnání.

Ceny Twelve Data se mohou lišit od cen CFD v Trading 212 (spot vs. futures, přirážka brokera). Proto aplikace
u SL/TP ukazuje i vzdálenost od vstupu, kterou přenesete k ceně v T212.

## Backtest, porovnání pravidel a demo režim

* **Backtest** v aplikaci porovná pravidla **v2.0 a v2.1** na stejných datech Twelve Data. Bere až 5000 svíček
  5m (zhruba 17 dní) a potřebuje 3 API dotazy. Ukáže:
  * počty BUY/SELL/WAIT/NO DATA;
  * počet obchodů, podíl vítězných obchodů, profit factor, průměrný výsledek v R a maximální pokles;
  * výsledky bez nákladů, se spreadem a se spreadem a modelovanými náklady (dalších 0,5× spread);
  * nejčastější důvody WAIT.

  Období se dělí **60 % vývoj / 40 % následný test**. Signál v každém okamžiku vidí jen tehdy uzavřené svíčky
  (bez budoucích informací, ověřeno testem). Pozice je vždy jen jedna. Když SL i TP padnou do jedné svíčky,
  počítá se SL. Obchody se zavírají na časovém limitu trhu. **Bez historického filtru zpráv.**
* **Skript** `python scripts/compare_strategies.py` dělá totéž pro 9 instrumentů na veřejných datech Yahoo
  Finance (5m/15m za 60 dní, 1h za rok). S `--source twelvedata` a klíčem v `TWELVEDATA_API_KEY` použije
  Twelve Data. Spouští se v CI a výsledek je v artefaktu `strategy-comparison`.
* **Demo deník:** každý živý BUY/SELL (ne NO DATA ani ERROR) se zapíše do
  `%APPDATA%\CFDSignalCalculator\journal.csv`. Tlačítko „Ověřit výsledky podle dat“ dohledá, zda signál dosáhl
  SL, TP nebo časového limitu.
* **Offline demo** (Nastavení): syntetická data bez API klíče, jen pro vyzkoušení aplikace. Je označené v patičce
  a výsledkem „DEMO“ a do deníku se nezapisuje.

**Vyšší počet signálů sám o sobě neznamená lepší strategii.** O tom rozhodují výsledky v testovací části po
nákladech, a i ty jsou na krátkém období jen orientační.

## Předpoklady a omezení (neověřeno proti živému API)

Vývojové prostředí nemělo přístup k api.twelvedata.com. Proti skutečnému API se tedy neověřovalo následující:

* Formát `GET /time_series` (`values[]` s `datetime/open/high/low/close/volume`, `status: error`
  a `message`), parametry `timezone=UTC` a `order=asc` a hlavička `Authorization: apikey …`. Pokud API
  odpoví jinak, je výsledek chyba dat a WAIT.
* **Mapování symbolů** (ověřeno 16. 11. 2026 proti veřejnému vyhledávání symbolů Twelve Data,
  `scripts/verify_symbols.py`, běží v CI):
  * Forex (11 párů), zlato `XAU/USD`, stříbro `XAG/USD`, ropa `WTI/USD` a Brent `XBR/USD` odpovídají.
  * Akcie mají pevně nastavenou americkou burzu (NASDAQ/NYSE). Stejné tickery jsou i jinde, např. `BA` je také
    Bangkok Airways a `DIS` také Distil Plc. Když Twelve Data vrátí data z jiné burzy, výsledek je WAIT.
  * **Indexy (US 500, US 100, US 30, Germany 40, UK 100) a zemní plyn se neanalyzují.** Twelve Data pod
    `SPX`, `NDX`, `DAX` a `FTSE` uvádí ETF nebo jiné firmy (např. SpaceX, Nordex), `DJI` a `NG/USD` neexistují.
    Aplikace je rozpozná, ale vždy vrátí WAIT s vysvětlením a API nevolá.
* Dostupnost jednotlivých symbolů ve vašem tarifu. Nedostupný symbol se projeví jako chyba API a WAIT.
* Bezplatný tarif má limit 8 dotazů za minutu. Analýza spotřebuje 3 dotazy, backtest také 3.
* Data akcií mohou být zpožděná nebo mimo obchodní hodiny staré. Taková data se zamítnou jako zastaralá a výsledek
  je WAIT.
* Ekonomický kalendář je neoficiální týdenní feed Forex Factory (`nfs.faireconomy.media`), uložený
  v mezipaměti na 1 h a důvěryhodný nejvýš 6 h. Earnings jednotlivých akcií se nesledují.
* OCR a snímání okna byly ověřeny na zkušebním okně ve Windows (GitHub Actions), ne na skutečném Trading 212.
  Detekce okna předpokládá, že titulek obsahuje „Trading 212“. Pokud rozpoznání selže, zúžte oblast jen na
  název instrumentu.
* Mapování symbolů na Twelve Data kontroluje `python scripts/verify_symbols.py` (v CI informativně).
* API klíč se ukládá nešifrovaně do `%APPDATA%\CFDSignalCalculator\app.ini`, případně ho nastavte proměnnou
  prostředí.

## Testy

```bat
set QT_QPA_PLATFORM=offscreen
python -m pytest -q
```

Testy nevolají síť (socket je zablokovaný) a používají syntetická data. Výsledky na syntetických datech
nejsou důkazem ziskovosti.
