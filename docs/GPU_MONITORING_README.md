# GPU Monitoring mit PowerShell

Dieser Ordner enthaelt alternative Skripte, die GPU und LLM-Daten direkt im Terminal/PowerShell anzeigen anstelle nur InfluxDB zu schreiben.

## Dateien

| Datei | Beschreibung |
|-------|-------------|
| `gpu_monitor.ps1` | Vollstaendiges PowerShell-Skript mit Live-Monitoring, Watch-Modus und detaillierter Ausgabe |
| `gpu_stats.ps1` | Kompakte Ausgabe fuer Dashboards und Logging |
| `gpu_terminal.py` | Python-Version (kompatibel zu influx_exporter.py) |
| `gpu_monitor.bat` | Batch-Wrapper fuer PowerShell auf Windows |

## Installation

1. Stellen Sie sicher, dass PowerShell 5.1+ installiert ist (in Windows 10/11 Standard)
2. Stellen Sie sicher, dass `nvidia-smi` in PATH vorhanden ist
3. Testen: `Get-Command nvidia-smi` sollte funktionieren

## Schnellstart

### Einzeler Statusueberpruefung

```powershell
# PowerShell mit detaillierter Ausgabe
.\gpu_monitor.ps1 status

# PowerShell compact (fuer Dashboard)
.\gpu_stats.ps1 -Format compact

# Batch-Wrapper (auch von CMD aufrufbar)
.\gpu_monitor.bat

# Python-Version
python3 gpu_terminal.py
```

### Live Monitoring

```powershell
# 5 Sekunden Intervall (empfohlen fuer Dashboards)
.\gpu_monitor.ps1 watch -Interval 5

# 10 Minuten Dauer (unbegrenzt mit -Duration -1)
.\gpu_monitor.ps1 watch -Interval 30 -Duration 10
```

### JSON Output fuer Logging/Dashboard

```powershell
.\gpu_stats.ps1 -OutputFormat json
# Oder
python3 gpu_terminal.py --json
```

## Integration mit InfluxDB Skript

Das Python-Skript `influx_exporter.py` kann um Terminal-Ausgabe erweitert werden:

```python
from influx_exporter import query_gpu, query_llm

def display_terminal(gpu_data, llm_data):
    """Terminal-Anzeige ohne InfluxDB-Schreiben"""
    # Formatieren wie in gpu_terminal.py
    pass

# In der main() Funktion von influx_exporter.py:
points_to_write = [...]  # Normalerweise fuer InfluxDB

if os.getenv("DISPLAY_TERMINAL"):  # Terminal-Output aktivieren
    print(display_terminal(gpu_data, llm_data))
else:
    influx_write(points_to_write, ...)  # Nur InfluxDB schreiben
```

## Konfiguration

Um zwischen InfluxDB und Terminal-Output zu wechseln:

**In .env Datei:**
```bash
INFLUXDB_TOKEN=...
DISPLAY_TERMINAL=true      # Wenn true: Zeige Daten im Terminal
# Wenn false (Standard): Nur in InfluxDB schreiben
```

## Beispiel-Output

### PowerShell (detailliert)
```
==============================================================
       GPU STATUS - 2026-08-20 14:35:42                             
==============================================================

Name:    NVIDIA GeForce RTX 3060
Load:    2.5% GPU Utilisation
VRAM:    6973.0MB / 8192.0MB
VRAM%:   85.1% (Hohe Auslastung)
Temp:    62°C°C (Normaler Betrieb)
Power:   4.2W
Fan:     41.8%
Clock:   2850MHz

--------------------------------------------------------------
LLM STATUS
--------------------------------------------------------------
[GPU VRAM] Status: Im VRAM (Aktiv)
Modell:    mllama3.2-vision-11b-bf16-q4_0
VRAM:      7195.0MB von 8192.0MB (87.8%)
TTL:       Keine Entlade-TTL gesetzt (dauerhaft geladen)

==============================================================
                        ZUSAMMENFASSUNG
==============================================================
GPU: NVIDIA_GeForce_RTX_3060
     LLM: mllama3.2-vision-11b-bf16-q4_0
```

### PowerShell (compact)
```
GPU: NVIDIA_GeForce_RTX_3060
  Load:   2.5%
  VRAM:   6973M/8192M
  Temp:   62°C (Normaler Betrieb)
  Power:  4.2W
  Fan:    41.8%

--------------------------------------------------------------
[GPU VRAM] Status: Im VRAM
Modell: mllama3.2-vision-11b-bf16-q4_0
VRAM:   7195MB von 8192MB (87.8%)
TTL:    Keine Entlade-TTL (dauerhaft geladen)
```

### JSON Output
```json
{
  "timestamp": "2026-08-20T14:35:42.123456+00:00",
  "gpu": {
    "name": "NVIDIA GeForce RTX 3060",
    "load_pct": 2.5,
    "vram_used_mb": 6973.0,
    "vram_total_mb": 8192.0,
    "temp_c": 62,
    "power_w": 4.2,
    "fan_pct": 41.8,
    "clock_mhz": 2850.0
  },
  "llm": {
    "model_name": "mllama3.2-vision-11b-bf16-q4_0",
    "vram_mb": 7195.0,
    "vram_pct": 87.8,
    "total_vram_mb": 8192.0,
    "on_gpu": true
  }
}
```

## Verwendung in Dashboards

### Grafana Integration (JSON Output)

Fuer Grafana-Dashboards koennen Sie das JSON-Output Skript verwenden:

```powershell
# Cron-Takt alle 5 Minuten
.\gpu_stats.ps1 -OutputFormat json
```

Oder als PowerShell-Funcition im Script einbinden:

```python
import subprocess
import json

def get_gpu_json():
    """JSON fuer Grafana/Dashboards"""
    result = subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-File", ".\\gpu_stats.ps1", "-OutputFormat", "json"],
        capture_output=True, text=True
    )
    return json.loads(result.stdout)

# In Grafana Prometheus Importer oder anderen Tools
```

## Fehlerbehandlung

Wenn `nvidia-smi` nicht funktioniert:

```powershell
# Manuelle nvidia-smi Pruefung
nvidia-smi --id=0 --query-gpu=name,memory.total --format=csv

# Installation von CUDA Treiber
# https://www.nvidia.de/Download/index.aspx?lang=de
```

## Troubleshooting

| Problem | Loesung |
|---------|---------|
| `nvidia-smi` nicht gefunden | CUDA Treiber installieren |
| PowerShell-Fehler bei Start | `Set-ExecutionPolicy RemoteSigned` in Admin-CMD |
| Ollama API nicht erreichbar | Ollama starten: `ollama serve` |
| JSON-Output leer | nvidia-smi Output ueberpruefen |

## Lizenz

Dieses Skript ist im Rahmen der gpu_gadget-Projekt-Lizenz verwendbar.
