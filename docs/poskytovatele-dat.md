# Poskytovatelé tržních dat – porovnání a doporučení (17. 11. 2026)

Aplikace potřebuje svíčky 5m, 15m a 1h (aspoň 250 uzavřených svíček na rámec), téměř v reálném čase, pro instrumenty
odpovídající CFD v Trading 212. Data se používají jen lokálně pro osobní analýzu. Nic se nekupuje automaticky.

## Co bylo ověřeno přímo (CI, veřejné endpointy bez klíče)

`scripts/coverage_audit.py` volá Twelve Data `GET /symbol_search?show_plan=true` pro **každý** zdroj z katalogu
(symbol, burza, měna, typ a nejlevnější tarif, který symbol obsahuje) a Coinbase `GET /products/{X-USD}/candles`.
Výsledek je v artefaktu `coverage-audit` každého běhu CI.

| Trh | Twelve Data – nejlevnější tarif | Poznámka |
|---|---|---|
| Forex (43 párů včetně CZK, PLN, HUF, TRY…) | **Basic (zdarma)** | |
| Americké akcie (NASDAQ, NYSE) a ADR | **Basic** | burza musí být pevně daná, jinak TD vrací např. argentinské CEDEAR |
| Americká ETF (SPY, QQQ, GLD, SLV, USO…) | **Basic** | |
| Kryptoměny (BTC, ETH, SOL, XRP, …) | **Basic** | |
| Zlato XAU/USD | **Basic** | |
| Stříbro XAG/USD, ropa WTI a Brent, platina, palladium | **Grow** | **odtud HTTP 404 u stříbra ve verzi 2.2.1** |
| Zemní plyn (NG/USD), měď | není v katalogu | |
| Akciové indexy (SPX, NDX, DJI, DAX, FTSE, RUT…) | pod těmito symboly TD vrací jiné firmy nebo ETF | index jako takový v adresáři nenalezen |
| Německé, francouzské, britské akcie (XETR, Euronext, LSE) | **Grow** | Volkswagen Vz (VOW3) dokonce Basic |
| Švýcarské akcie (SIX) | **Pro** | |
| Coinbase Exchange – 12 kryptoměn | **zdarma, bez klíče** | 350 svíček pro 5m, 15m i 1h v jednom dotazu |

## Porovnání poskytovatelů

| Poskytovatel | Pokrytí | 5m / 15m / 1h | Cena a limity | Zpoždění | Objem | Použití v aplikaci |
|---|---|---|---|---|---|---|
| **Twelve Data** | forex, US akcie/ETF, krypto, kovy; EU burzy a komodity od Grow | ano | Basic zdarma: 8 kreditů/min, 800/den. Grow cca 29–79 USD/měs. (377 kreditů/min, bez denního limitu). Pro cca 99–229 USD/měs. | podle tarifu a trhu; aplikace kontroluje stáří každé svíčky | akcie ano, forex ne | **hlavní zdroj** (beze změny klíče) |
| **Coinbase Exchange** (veřejné API) | spot krypto vůči USD | ano (300/900/3600 s) | zdarma, bez klíče, omezení podle IP | reálný čas | ano (burzovní) | **nový zdroj pro krypto**, Twelve Data jako záloha |
| Massive (dříve Polygon.io) | US akcie/ETF | Basic zdarma: jen denní data (5 dotazů/min) | Starter 29 USD/měs. = 15min zpoždění | 15 min (Starter) | ano | **nepřidán**: zpožděná data nejsou použitelná pro 5min signál, reálný čas až v tarifu Advanced (~199 USD/měs.) |
| Alpha Vantage | akcie, forex | ano | zdarma ~25 dotazů/den | | | **nepřidán**: jedna analýza = 3 dotazy |
| Finnhub | akcie | svíčky jen v placených tarifech (dle dostupných zdrojů) | zdarma 60/min | | | **nepřidán**: intradenní svíčky nejsou zdarma |
| OANDA v20 API | forex, kovy a CFD indexy/komodity podle divize účtu | ano | API klíč z (i demo) účtu OANDA | reálný čas | ne | **kandidát** pro indexy a komodity jako CFD-like ceny. Vyžaduje váš účet a ověření podmínek, nepřidán bez vašeho souhlasu. |
| Yahoo Finance | široké | ano (60 dní) | neoficiální, bez smlouvy | | | **jen ve výzkumu**, nikdy v aplikaci |
| Dukascopy (historický feed) | forex, kovy, CFD | historie | zdarma, omezuje servery | | tick objem | **jen výzkum** (lokálně) |
| Trading 212 | – | – | – | – | – | **nepoužívá se**: žádné neoficiální API ani scraping |

Ceny jsou z veřejných ceníků a recenzí a liší se podle měsíčního a ročního placení. Před nákupem je ověřte na
twelvedata.com/pricing a massive.com/pricing.

## Doporučení

1. **Zdarma (Basic) dnes funguje plná analýza pro 141 ze 167 instrumentů katalogu:** forex, US akcie, ETF, krypto
   a zlato.
2. **Twelve Data Grow** je jediná placená změna s velkým přínosem. Přidá stříbro, ropu WTI/Brent, platinu,
   palladium, akcie z XETR, Euronextu a LSE a zruší denní limit 800 dotazů. Po zakoupení stačí přepnout
   ⚙ Nastavení → Tarif Twelve Data na „Grow“ a stříbro se bude analyzovat z přesných dat místo z referenčního ETF.
3. **Indexy**: pro přesná data indexu je potřeba jiný zdroj (např. OANDA v20 s vaším účtem). Do té doby aplikace
   používá referenční ETF (SPY, QQQ, DIA, IWM, Global X DAX, EWU). Výsledek dává **jen směr**, bez vstupu, SL a TP.
4. Nic se nekupuje automaticky a žádný klíč se neposílá jinam než příslušnému poskytovateli.
