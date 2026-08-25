# GPU LLM Gadget

Desktop-Gadget und Monitoring-Tools fuer NVIDIA-GPUs (z.B. RTX 3060) mit optionaler LLM-Statusanzeige (Ollama) und InfluxDB-Export.

## Features

- Desktop-Gadget (`src/gpu_gadget.pyw`, Tkinter): zeigt permanent GPU-Auslastung, VRAM (belegt/gesamt) und Temperatur an
  - Kompakt- und Detailansicht (Doppelklick zum Wechseln)
  - Frei verschiebbar (linke Maustaste), Rechtsklick-Menue (Immer-oben, Beenden)
  - Fensterposition wird in `gpu_gadget_config.json` gespeichert
- InfluxDB-Exporter (`src/influx_exporter.py`): schreibt GPU- und LLM-Metriken periodisch in InfluxDB v2
- Terminal-Monitoring: PowerShell- (`docs/gpu_monitor.ps1`, `docs/gpu_stats.ps1`) und Python-Variante (`src/gpu_terminal.py`)

## Voraussetzungen

- Windows mit `nvidia-smi` im PATH
- Python 3.11+
- Optional: laufender Ollama-Server fuer LLM-Statusanzeige
- Optional: InfluxDB v2 fuer Metrik-Export

## Setup

```bash
pip install -r requirements.txt   # falls vorhanden, sonst: python-dotenv, requests
cp src/.env.example src/.env
# .env mit InfluxDB-URL, Token, Org und Bucket ausfuellen
```

## Nutzung

```bash
# Desktop-Gadget starten
pythonw src/gpu_gadget.pyw

# InfluxDB-Exporter starten
python src/influx_exporter.py

# Terminal-Monitoring
python src/gpu_terminal.py
```

Windows-Batch-Skripte: `docs/gpu_monitor.bat`, `docs/start_gpu_gadget.bat` (falls vorhanden).

Weitere Details siehe:
- `docs/GPU_MONITORING_README.md`
- `docs/README_INFLUX_EXPORTER.md`

## Build (Windows-Exe)

```bash
pyinstaller GPU-Gadget.spec
```

Ausgabe landet in `dist/` bzw. `build/` (nicht versioniert).

## Konfiguration

Secrets liegen ausschliesslich in `src/.env` (per `.gitignore` ausgeschlossen). Vorlage: `src/.env.example`.
