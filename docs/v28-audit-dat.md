# Audit datové vrstvy v2.8 – „nedostatečné API“ a chybějící data

Stav k 18. 11. 2026. Audit vychází z kódu (`data.py`, `analysis.py`, `instruments.py`), z logů GitHub Actions
a z veřejných odpovědí Twelve Data (ověřeno v CI bez klíče). **Účet Twelve Data uživatele ani jeho tarif nebyly
dostupné**: v GitHub Actions není nastaven secret `TWELVEDATA_API_KEY`. Žádná verze se proto nikdy neověřila
proti skutečnému tarifu (log kroku `td_probe`: „kontrola dat s klíčem PŘESKOČENA“). Konkrétní příčinu na počítači
uživatele ukáže nová stránka **Podrobnosti → Signál M15 → Diagnostika dat**.

| Možná příčina | Zjištění | Stav v2.8 |
|---|---|---|
| **Vyčerpaný limit / rate limit** | **Strukturální příčina.** Od v2.6.1 si každé kliknutí na START vynutilo nová 5m data a k tomu 15m a 1h, když jim vypršela platnost: 1 až 3 požadavky na klik. Tarif Basic má 8 požadavků za minutu a 800 denně (plus kurzy měn pro výpočet pozice). Při klikání každých pár sekund místní ochrana nebo Twelve Data (HTTP 429) brzy odmítne další požadavek a analýza skončí NO DATA „Překročen limit dotazů API“. | **Opraveno**: signál potřebuje jediný požadavek (15min), opakované kliknutí do 60 s žádný. Na pozadí se stahuje 1× po uzavření nové 15m svíčky (max. 4/h). Limit tarifu se nadále respektuje, nic se neobchází. |
| **Omezení tarifu** | Podle auditu katalogu (`symbol_search?show_plan=true`) jsou XAG/USD, WTI/USD, XBR/USD, XPT/USD, XPD/USD, NG/USD a evropské akcie dostupné až od tarifu Grow (NESN, NOVN od Pro). Na tarifu Basic proto NO DATA. | **Nejde opravit zdarma.** Aplikace se na ně vůbec nedotazuje a přesně řekne, jaký tarif je potřeba. Pro stříbro, ropu a plyn umí referenční ETF (SLV, USO, UNG). Ten dává jen směr, nikdy VSTUP/TP/SL ani pozici. |
| **Nepodporovaný symbol / mapování** | Indexy (US 500, US 100, US 30, Germany 40, UK 100, Russell 2000) nemají v Twelve Data ověřený přesný symbol CFD indexu. Používají se jen referenční ETF (SPY, QQQ, DIA, IWM, …). | Beze změny. Index = jen směr z ETF s jasným štítkem „REFERENČNÍ TRŽNÍ DATA“. |
| **Nepodporovaný interval** | Twelve Data i Coinbase interval 15min podporují pro všechny zdroje katalogu (test `test_catalog_instruments_all_have_15min_capable_sources`). | v2.8 používá jen 15min. |
| **Chybějící / neplatný klíč** | Bez klíče aplikace hlásila jen chybu Twelve Data. | Diagnostika ukáže „Klíč Twelve Data: CHYBÍ“. Krypto jde dál přes Coinbase bez klíče. Neplatný klíč (HTTP 401) se rozpozná a hlásí jako „API klíč byl odmítnut“. |
| **Nedostatečný počet svíček** | v2.6 potřebovala 250 uzavřených svíček na **každém** ze 3 rámců. U 1h to u akcií znamená zhruba 38 obchodních dní historie. | M15 potřebuje 260 svíček M15 (EMA 200 + rozběh) z jednoho požadavku na 400 svíček. U Coinbase je strop 300 svíček, i to stačí. |
| **Zastaralá cache** | Cache v2.6 hlídala 3 rámce zvlášť. Klik vynucoval jen 5m. | Jedna řada M15. Stáří ceny max. 60 s, jinak 1 malý požadavek. Signál z uzavřených svíček, které byly při stažení už finální. |
| **Chyba sekundárního poskytovatele** | Coinbase (krypto) má jako zálohu Twelve Data. | Zachováno a otestováno (`test_crypto_uses_coinbase_first_and_falls_back_to_twelve_data`). |
| **Síťová chyba / timeout** | Každý požadavek měl timeout 15 s, celá analýza 75 s. | Hlavní tlačítko má limit 25 s. Pak NO DATA s důvodem a jde kliknout znovu. Chyba se nikdy neskrývá za stará data. |

## Fallback mezi zdroji

* **Twelve Data** (klíč uživatele) – forex, kovy, energie, akcie, ETF. Respektuje se nastavený tarif.
* **Coinbase Exchange** (veřejné API bez klíče, podmínky umožňují čtení tržních dat) – kryptoměny, první volba.
* **Yahoo Finance a Dukascopy** se v aplikaci **nepoužívají**. Jejich podmínky výslovně nepovolují automatizované
  použití v aplikaci. Slouží jen k historickému výzkumu v CI (osobní analýza, data se nepublikují).

## Co je potřeba změnit pro plné pokrytí

* Stříbro, ropa, Brent, platina, palladium, plyn a evropské akcie s VSTUP/TP/SL: **tarif Twelve Data Grow**
  (švýcarské akcie Pro). Tarif nastavíte v ⚙ Nastavení.
* Indexy s přesnou cenou CFD: žádný ze zdrojů aplikace ji nemá. Podkladová ani referenční cena se **nerovná** ceně
  CFD v Trading 212.
* Aby šlo data ověřovat i v CI s vaším tarifem: nastavit secret `TWELVEDATA_API_KEY` (GitHub → Settings → Secrets
  and variables → Actions). Bez něj CI ověřuje jen veřejné odpovědi.
