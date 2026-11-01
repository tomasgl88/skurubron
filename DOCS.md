# Skurubron-appen – teknisk dokumentation

En liten app som visar antal passager och betald broavgift för Skurubron
(väg 222, Nacka) per månad, med historik sedan avgiften infördes 1 oktober 2023.

Live: https://tomasgl88.github.io/skurubron/
Repo: https://github.com/tomasgl88/skurubron
Lokalt: `~/.milton/workspace/skurubron/` (eget git-repo, helt skilt från Milton-arbetet)

---

## 1. Översikt / arkitektur

```
Transportstyrelsen (HTML-tabeller)
        │   scrape.py (Python, körs i GitHub Actions)
        ▼
   docs/data.json   ← den enda datafilen appen läser
        │   GitHub Pages serverar docs/
        ▼
   PWA i Safari (index.html + sw.js)  →  "Lägg till på hemskärmen"
```

- **Datamotor:** `scrape.py` hämtar och tolkar Transportstyrelsens statistik och
  skriver `docs/data.json`.
- **App:** en statisk PWA i `docs/` (ingen server, ingen native-kod, ingen Mac).
- **Automation:** GitHub Actions kör scrapern dagligen; Pages publicerar om.

---

## 2. Datakälla

Transportstyrelsen, infrastrukturavgift Skurubron:
https://www.transportstyrelsen.se/sv/om-oss/statistik-och-analys/statistik-inom-vagtrafik/infrastrukturavgift-statistik/skurubron/

- Det finns **inget öppet API** – datan ligger som HTML-tabeller, en sida per år
  (`statistik-2023/`, `statistik-2024/`, `statistik-2025/` …).
- **Innevarande års** månader publiceras löpande på **landningssidan** innan en
  egen årssida finns.
- Tre tabeller per år: passager, avgiftsbeslut svenska fordon, avgiftsbeslut
  utländska fordon.
- **Eftersläpning:** passagedata kommer ~1 månad efter månadens slut;
  avgiftsbeslut släpar ytterligare en månad efter passagerna.
- Avgiften infördes **1 oktober 2023** (4 kr/passage). Månader före dess har inga
  avgifter och tas bort ur datasetet.

### Byggkostnad / finansiering (kontext, inte ett mål i appen)
- Nya bron ~1 miljard kr (prisnivå 2016); 1/3 statligt, 2/3 broavgift.
- Avgift tas ut tills lånet är återbetalt, beräknat ~22 år.
- Det totala belopp som ska drivas in via avgiften publiceras **inte** som en
  enskild siffra (ränta + administration tillkommer). Appen visar därför faktiskt
  inbetalt belopp, inte andel av ett slutmål.

---

## 3. Scrapern (`scrape.py`)

Körs med `uv` (beroenden deklareras inline i filen, PEP 723).

```bash
uv run --quiet --script scrape.py            # hämtar bara om det behövs
uv run --quiet --script scrape.py --force    # bygg om oavsett
```

Skriver:
- `docs/data.json` – det appen läser (år, månad, passager, avgiftsbelopp SE/utl/total).
- `data/skurubron.sqlite` – lokal build-artefakt (gitignorerad).

### "Hämta bara vid behov" – två grindar
- **Gate 1 (lokal, noll nätanrop):** den nyaste månad som rimligen kan vara
  publicerad är *innevarande månad minus 1* (data släpar minst en månad). Har vi
  redan den (eller nyare) → stopp, inget anrop. Nyckeln är **senaste DATA vi har**,
  inte när vi senast kollade – därför missas aldrig en publicering mitt i månaden.
- **Gate 2 (ett anrop):** när Gate 1 släpper igenom hämtas landningssidan en gång;
  är senaste publicerade månad inte nyare än vad vi har → stopp innan årssidorna
  hämtas. Annars hämtas årssidorna och allt byggs om.

### Dataprecision
- Saknad avgift lagras som `null` (inte `0`) – "ej publicerat än" och "noll" hålls
  isär i graf, tabell och KPI:er.

---

## 4. Appen (`docs/`)

Statisk PWA. Filer:
- `index.html` – all UI och logik (KPI-kort, två Chart.js-grafer, tabell, faktaruta).
- `sw.js` – service worker.
- `manifest.webmanifest` – PWA-manifest (ikon, namn, helskärm).
- `icon-192.png`, `icon-512.png` – app-ikon (bromotiv).
- `data.json` – datan.

### UI-beslut
- Passager-graf: en serie, horisontellt scrollbar, **nyast till vänster**.
- Avgifts-graf: bara månader med publicerad avgift (ingen linje ner till 0),
  **nyast till vänster** – enhetligt med passager-grafen.
- Tabell: **nyast överst**; saknad avgift visas som "–".
- KPI: "Passager totalt (sedan okt 2023)" och
  "Betalt totalt (okt 2023 – [senaste avgiftsmånad], dynamiskt)".
  Snitt/månad räknas bara på månader med avgiftsdata.

### Datacache i appen
- Senaste dataset sparas i `localStorage` (`skurubron.data`).
- Appen hämtar bara ny `data.json` när en nyare månad rimligen kan finnas
  (samma resonemang som scraperns Gate 1), men **ersätter cachen så fort hämtad
  data skiljer sig** från den sparade – inte bara när månaden är nyare. (Det var
  buggen bakom "september ritas som 0" tidigt: värdet ändrades 0→null utan att
  månaden ändrades, och den gamla cachen behölls.)

### Service worker
- **Sidan (index.html): network-first** → UI-ändringar slår igenom direkt vid
  nästa öppning. Fallback till cache offline.
- **Appskal (ikoner, Chart.js): cache-first** → snabb start och offline.
- **data.json: network-first** med cache-fallback.
- Vid ändring av appkoden: **höj `VERSION`** i `sw.js` (t.ex. v6 → v7) så gamla
  cacher rensas.

---

## 5. Automatisk uppdatering (GitHub Actions)

`.github/workflows/update-data.yml`:
- Kör **dagligen 05:17 UTC** (+ manuell "Run workflow").
- Kör scrapern; de flesta dagar en billig no-op tack vare grindarna.
- Committar `docs/data.json` **endast om den ändrats**, pushar, Pages publicerar om.
- Ingen dator behövs.

**Engångsinställning i repot:** Settings → Actions → General →
Workflow permissions → **Read and write permissions** (annars kan workflowen inte
pusha tillbaka).

---

## 6. Felsökning

- **Mobilen visar gammal version:** vanligtvis service worker-cachen. Sedan
  network-first infördes för sidan räcker det att öppna appen igen (ev. två gånger
  så den nya service workern hinner ta över). Höj `VERSION` i `sw.js` vid
  kodändringar.
- **Graf dyker till 0:** en månad har passager men ännu ingen avgift. Avsett –
  avgifts-grafen ska bara rita månader med publicerad avgift.
- **Actions pushar inte:** kontrollera "Read and write permissions" (se avsnitt 5).
- **Tvinga om-hämtning lokalt:** `uv run --quiet --script scrape.py --force`.

---

## 7. Viktiga filer

```
scrape.py                         # datamotor
docs/index.html                   # appen
docs/sw.js                        # service worker (höj VERSION vid kodändring)
docs/manifest.webmanifest
docs/data.json                    # datan appen läser
.github/workflows/update-data.yml # daglig auto-uppdatering
README.md                         # kort översikt
DOCS.md                           # denna fil
```
