# Job Radar

Remote (US) SDET / QA Automation / AI testing ilanlarini toplayan kisisel bot.

- `radar.py`  : kaynaklari tarar, filtreler, `docs/jobs.json` dosyasina yazar
- `config.yaml` : anahtar kelimeler, sirket listesi (gunluk degisen tek dosya)
- `docs/index.html` : arayuz (GitHub Pages ile yayinlanir)
- `.github/workflows/radar.yml` : GitHub Actions uzerinde 15 dakikada bir calistirir

## Kurulum
1. Bu dosyalari public bir GitHub reposuna koy.
2. Settings > Pages > Source: "Deploy from a branch", Branch: `main`, klasor `/docs`.
3. Actions sekmesinden "Job Radar" > "Run workflow" ile ilk taramayi baslat.
4. (Istege bagli) Telegram bildirimi icin Settings > Secrets and variables > Actions altina
   `TELEGRAM_TOKEN` ve `TELEGRAM_CHAT_ID` ekle.

## Yerelde deneme
    pip install -r requirements.txt
    python radar.py --dry-run
    python tests/test_offline.py
