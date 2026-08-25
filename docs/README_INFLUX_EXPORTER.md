# InfluxDB Exporter fuer gpu_gadget

Dieses Skript schreibt GPU und LLM-Werte parallel in eine InfluxDB.

## Features

- **Intervall**: Alle 30 Sekunden
- **Bucket**: `bucket-homelab`
- **Organisation**: `AP78`
- **Measurement**: `n8n_ollama-llm`

### Gemessene Werte:

#### GPU-Metriken (via nvidia-smi):
| Feld | Beschreibung | Einheit |
|------|-------------|---------|
| `load_pct` | GPU-Auslastung | % |
| `vram_used_mb` | Belegter VRAM | MB |
| `vram_total_mb` | Gesamte VRAM-Kapazität | MB |
| `temp_c` | GPU-Temperatur | °C |
| `power_w` | Power Consumption | Watt |
| `fan_pct` | Lüfterdrehzahl | % |
| `clock_mhz` | Clock Speed | MHz |

#### LLM-Metriken (via Ollama API):
| Feld | Beschreibung | Einheit |
|------|-------------|---------|
| `llm_name` | Name des aktuell geladenen Modells | String |
| `vram_mb` | Größe des Modells im VRAM | MB |
| `vram_pct` | GPU-Anteil des Modells | % |
| `on_gpu` | Ist das Modell auf GPU oder CPU? | 0/1 |
| `ttl_seconds` | Zeit bis zum automatischen Entladen | Sekunden |

#### Event-Ereignisse:
- `load_start`: LLM wurde geladen (Startzeitpunkt)
- `load_complete`: LLM vollständig im VRAM
- `unload_start`: LLM wurde entladen
- `unload_complete`: LLM komplett aus dem VRAM entfernt

## Installation

### 1. InfluxDB installieren

**Option A: Docker**
```bash
docker run -d \
  --name influxdb \
  -p 8086:8086 \
  -v ~/.influxdb2:/var/lib/influxdb2 \
  influxdb:latest
```

**Option B: Windows-Service (via Chocolatey)**
```powershell
choco install influxdb
influxd.exe set http-bind-address=0.0.0.0:8086
```

### 2. Bucket und Token erstellen

```bash
# InfluxDB CLI starten
influxd config --show-config > config.toml

# Organisation erstellen
influx org create name="AP78" dry-run=true

# Bucket erstellen
influx bucket create name=bucket-homelab org=AP78

# Token erstellen (mit WRITE permission)
influx token create org=AP78 \
  --name=gpu-gadget-token \
  --write=true --read=true --query=true \
  --dry-run | grep -oP 'token:"\K[^"]+'
```

### 3. `.env` Datei konfigurieren

Öffne `gpu-llm-gadget/.env` und füge deine Werte ein:

```env
INFLUXDB_URL=http://localhost:8086
INFLUXDB_TOKEN=dein-token-hier
INFLUXDB_ORG=AP78
INFLUXDB_BUCKET=bucket-homelab
INFLUXDB_MEASUREMENT=n8n_ollama-llm
```

**Wichtig:** Ersetze `your-token-here` mit deinem echten Token!

### 4. gp g gadget.py starten

Zuerst musst du das gpu_gadget-Skript starten, damit es die GPU und Ollama-Werte abfragt:

```bash
python gpu_gadget.pyw
# oder
py gpu_gadget.pyw
```

### 5. InfluxDB Exporter starten

```bash
cd gpu-llm-gadget
python influx_exporter.py
```

## Datenfluss

```
┌─────────────────┐
│  GPU Hardware    │
│   (nvidia-smi)   │
└────────┬────────┘
         │ 30 Sek
         ▼
┌─────────────────┐
│   query_gpu()   │
└────────┬────────┘
         │ Load, Temp, Power, Clock, Fan
         ▼
┌──────────────────────┐
│    InfluxDB Write    │
│  Measurement: n8n_ollama-llm │
│  Bucket: bucket-homelab  │
└──────────────────────┘

┌─────────────────┐      ┌─────────────────┐
│   gpu_gadget    │      │  Ollama API     │
│   (query_llm)   │      │  (http://127.0.0.1:11434/api/ps) │
└────────┬────────┘      └────────┬────────┘
         │ Modellname, Größe          │
         ▼                          ▼
┌──────────────────────┐          ┌─────────────────┐
│    InfluxDB Write    │◄─────────┤   query_llm()   │
└──────────────────────┘          └────────┬────────┘
                                             │
                                       Modellwechsel?
                                          /\
                                         /  \
                                        /    \
                                     Ja/Nein
                                      /      \
                                     v        v
                          ├────────────────┐  ├────────────────┐
                          │load_start/load_│  │  Modelname,     │
                          │complete event  │  │ TTL bis Entladen│
                          └────────────────┘  └─────────────────┘
```

## InfluxDB Abfrage-Beispiele

### Alle aktuellen GPU-Metriken:
```influxql
from(bucket:"bucket-homelab")
  |> range(start: -1h)
  |> filter(fn: (r) => r["_measurement"] == "n8n_ollama-llm")
  |> filter(fn: (r) => r["gpu_name"] == "NVIDIA GPU")
  |> summary(every: 1m, functions: ["mean", "max"])
  |> yield(name: "gpu_metrics")
```

### Welche LLMs wurden wann geladen?
```influxql
from(bucket:"bucket-homelab")
  |> range(start: -24h)
  |> filter(fn: (r) => r["_measurement"] == "n8n_ollama-llm")
  |> filter(fn: (r) => r["model_type"] == "load")
  |> sort(columns: ["_time"], desc: true)
  |> yield()
```

### LLM-Dauer im VRAM:
```influxql
from(bucket:"bucket-homelab")
  |> range(start: -24h)
  |> filter(fn: (r) => r["_measurement"] == "n8n_ollama-llm" 
                       and (r["model_type"] == "load" or r["model_type"] == "unload"))
  |> pivot(rowKey:["_time"], columnKey: ["model_type"], valueColumn: "vram_mb")
  |> map(fn: (r) => ({
      with: {
        model_name: r._value,
        duration_s: r.load_time - r.unload_time if r.unload_time else "pinned",
      }
    }))
```

### GPU-Temperatur-Historik:
```influxql
from(bucket:"bucket-homelab")
  |> range(start: -1d)
  |> filter(fn: (r) => r["_measurement"] == "n8n_ollama-llm")
  |> group()
  |> every(N: 5s)
  |> aggregateWindow(every: 1m, fn: mean, columns: ["temp_c"])
  |> yield(name: "gpu_temp_over_time")
```

## Fehlerbehebung

### Verbindungsaufnahme fehlschlagen:
- InfluxDB-Server erreichbar? (`ping influxdb-host`)
- Port 8086 offen? (`netstat -an | findstr 8086`)
- Token gültig und berechtigt?

### Ollama nicht erreichbar:
- `http://localhost:11434/api/ps` funktioniert?
- Ollama läuft? (`docker ps | grep ollama` oder `ollama serve`)

### GPU Daten nicht verfügbar:
- NVIDIA-Treiber installiert?
- `nvidia-smi` ausführbar? (`where nvidia-smi`)

## Lizenz

MIT - beliebig verwenden für persönliche und kommerzielle Projekte.
