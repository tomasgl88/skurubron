# Skurubron – passager & broavgift

En liten PWA som visar antal passager och betald broavgift för Skurubron
(väg 222, Nacka) per månad, med historik från att avgiften infördes 1 oktober 2023.

Data kommer från Transportstyrelsens offentliga statistik för infrastrukturavgiften.

## Delar

- `scrape.py` – hämtar och normaliserar Transportstyrelsens månadsstatistik och
  skriver `docs/data.json`. Hämtar bara när nyare data rimligen kan finnas
  (se grind-logiken i filens docstring). `--force` bygger om oavsett.
- `docs/` – den publicerade webbappen (GitHub Pages serveras härifrån):
  - `index.html`, `sw.js`, `manifest.webmanifest`, ikoner
  - `data.json` – datafilen appen läser.

## Uppdatering av data (automatisk)

En GitHub Actions-workflow (`.github/workflows/update-data.yml`) kör scrapern i
molnet dagligen (05:17 UTC). Scrapern gör bara ett verkligt hämtningsjobb när en
nyare månad rimligen kan finnas; övriga dagar är det en billig no-op. När
`docs/data.json` ändras committas och pushas den automatiskt, och GitHub Pages
publicerar om. Ingen dator behövs.

Du kan även köra den manuellt: Actions-fliken → "Update Skurubron data" →
"Run workflow".

### Köra lokalt (vid behov)

```bash
uv run --quiet --script scrape.py            # hämtar bara om det finns nytt
uv run --quiet --script scrape.py --force    # bygg om oavsett
```

## Publicering (GitHub Pages)

Repo-inställningar → Pages → Source: "Deploy from a branch",
branch `main`, mapp `/docs`. Appen nås sedan på
`https://<användare>.github.io/<repo>/`.

## Datakälla & förbehåll

Transportstyrelsen, infrastrukturavgift Skurubron. Belopp avser avgiftsbeslut
(svenska + utländska fordon). Det totala belopp som ska drivas in via broavgiften
publiceras inte som en enskild siffra – utöver byggkostnadsandelen tillkommer ränta
och administrativa kostnader. Appen visar därför faktiskt inbetalt belopp, inte
andel av ett slutmål.
