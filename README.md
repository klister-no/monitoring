# 📦 Packaging Regulation Monitor v2

Automatisk daglig overvåkning av emballasjeregulering med AI-analyse.

**→ Se rapporten: `https://DITT-BRUKERNAVN.github.io/packaging-monitor/`**

---

## Hva gjør den?

- **Scanner 9 kilder daglig kl 06:00** for nyheter om PPWR, SUP-direktivet og emballasjeregulering
- **Claude AI analyserer** de viktigste artiklene og vurderer innvirkning på frukt/grønt, drikke og blomster
- **Publiserer rapport** automatisk til GitHub Pages
- **Sender e-postvarsling** med daglig sammendrag
- **Merker tydelig** om kilder er åpne eller lukkede/bak betalingsmur

## Kilder

| Kilde | Type | Tilgang |
|-------|------|---------|
| EUR-Lex | EU/Regulering | 🔓 Åpen |
| EU Environment | EU/Regulering | 🔓 Åpen |
| FreshPlaza | Fagmedia | 🔓/🔒 Delvis åpen |
| Packaging Europe | Fagmedia | 🔒 Delvis lukket |
| Packaging World | Fagmedia | 🔓/🔒 Delvis åpen |
| Regjeringen.no | Norsk lovdata | 🔓 Åpen |
| Miljødirektoratet | Norsk lovdata | 🔓 Åpen |
| EUROPEN | Bransjeorg. | 🔓/🔒 Delvis åpen |
| CEFLEX | Bransjeorg. | 🔓 Åpen |

---

## Oppsett – steg for steg

### 1. Opprett GitHub-repository
1. Gå til [github.com/new](https://github.com/new)
2. Navn: `packaging-monitor`
3. Velg **Public**
4. Klikk **Create repository**

### 2. Last opp filene
Pakk ut zip-filen, åpne Terminal:
```bash
cd ~/Downloads/packaging-monitor-v2
git init
git add .
git commit -m "Packaging Monitor v2"
git branch -M main
git remote add origin https://github.com/DITT-BRUKERNAVN/packaging-monitor.git
git push -u origin main
```

### 3. Legg til Anthropic API-nøkkel (for AI-analyse)
1. Gå til [console.anthropic.com](https://console.anthropic.com) og opprett en API-nøkkel
2. I GitHub: gå til ditt repo → **Settings** → **Secrets and variables** → **Actions**
3. Klikk **New repository secret**
4. Navn: `ANTHROPIC_API_KEY`, Verdi: din API-nøkkel
5. Klikk **Add secret**

> 💡 Uten API-nøkkel fungerer alt bortsett fra AI-analyse – du får fortsatt rapporter med regelbasert vurdering.

### 4. Sett opp e-postvarsling (valgfritt)
Legg til disse secrets i Settings → Secrets → Actions:

| Secret | Eksempel | Beskrivelse |
|--------|----------|-------------|
| `SMTP_SERVER` | `smtp.gmail.com` | E-postserver |
| `SMTP_PORT` | `587` | Port (vanligvis 587 for TLS) |
| `SMTP_USERNAME` | `din@gmail.com` | Brukernavn |
| `SMTP_PASSWORD` | `xxxx xxxx xxxx xxxx` | App-passord (ikke vanlig passord!) |
| `EMAIL_TO` | `deg@firma.no` | Mottaker(e), kommaseparert |
| `EMAIL_FROM` | `Emballasje Monitor <din@gmail.com>` | Avsender |

**For Gmail:** Bruk et [App-passord](https://myaccount.google.com/apppasswords), ikke vanlig passord.

> 💡 E-post er valgfritt. Uten disse secrets kjøres skanning og rapport normalt, e-poststeget hoppes over.

### 5. Aktiver GitHub Pages
1. Gå til repo → **Settings** → **Pages**
2. Source: **Deploy from a branch**
3. Branch: **main**, mappe: **/docs**
4. Klikk **Save**

### 6. Ferdig!
- Rapporten publiseres på `https://DITT-BRUKERNAVN.github.io/packaging-monitor/`
- Oppdateres automatisk daglig kl ~06:00 norsk tid
- Du kan kjøre manuelt: **Actions** → **Daglig Emballasje-skanning** → **Run workflow**

---

## Hva er med i rapporten?

- **Kildetabell** med tilgangsstatus (åpen/lukket) for hver kilde
- **AI daglig sammendrag** – Claude oppsummerer dagens viktigste funn
- **Artikkelliste** sortert etter relevans (0-100)
- **AI-analyse** av enkeltartikler (sammendrag + innvirkningsvurdering)
- **Tilgangsmerking** per artikkel (🔓 åpen / 🔒 betalingsmur / 🚫 utilgjengelig)
- **Kategorisering** (frukt/grønt, drikke, blomster)

## Kostnader

- **GitHub Actions**: Gratis (2000 min/mnd på gratis-plan, kjøring tar ~2-3 min)
- **Claude API**: Ca. $0.05-0.15 per kjøring (avhengig av antall artikler)
- **E-post**: Gratis via Gmail
- **GitHub Pages**: Gratis

---

## Filstruktur

```
packaging-monitor/
├── packaging_monitor.py          # Hovedscript
├── requirements.txt              # Python-avhengigheter
├── README.md                     # Denne filen
├── .gitignore
├── .github/workflows/scan.yml    # GitHub Actions
└── docs/                         # Genereres automatisk
    ├── index.html                # Rapporten
    ├── data.json                 # Strukturert data
    ├── email.html                # E-postinnhold
    └── last_updated.txt          # Tidsstempel
```
