#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
InfluxDB Exporter fuer gpu_gadget
Schreibt GPU und LLM-Werte parallel in InfluxDB (alle 30 Sekunden).

Misst:
  - GPU: Load, Temp, Power, Clock, Fan
  - LLM: Modellname, VRAM-Graeuse, GPU-Anteil, Startzeitpunkt, Dauer im VRAM, Entladezeitpunkt

Bucket: bucket-homelab
Organisation: AP78
Measurement: n8n_ollama-llm

Installation:
  1. InfluxDB installieren und starten (z.B. mit Docker oder als Service)
  2. Bucket erstellen: influx> USE admin; CREATE BUCKET IF NOT EXISTS "bucket-homelab"
  3. Token erstellen: influx> create token with org and write permissions
  4. Token in .env Datei speichern
  5. Script ausfuehren: python influx_exporter.py

Hinweise:
  - Das Skript wird jede 30 Sekunden ausgefuehrt
  - Es zeichnet auf, welches LLM wann geladen wurde und wie lange es im VRAM blieb
  - Alle GPU-Metriken werden parallel zu den LLM-Daten geschrieben
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError


def load_influx_config():
    """Liest InfluxDB-Kredentials aus .env Datei."""
    import base64

    env_file = os.path.join(os.path.dirname(__file__), ".env")
    config = {}

    if os.path.exists(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, value = line.split("=", 1)
                        # Strip Anfuhrungszeichen und Whitespace
                        value = value.strip().strip('"\'')

                        # Decode Base64 Token wenn moeglich
                        if key == "INFLUXDB_TOKEN" and value.startswith("LW"):
                            try:
                                decoded = base64.b64decode(value).decode('utf-8')
                                print(f"[INFO] Token wurde base64 decodiert")
                                value = decoded
                            except Exception as e:
                                print(f"[WARN] Token konnte nicht decodiert werden: {e}")
                                pass

                        config[key.strip()] = value
        except Exception as e:
            print(f"[WARN] Konnte .env Datei nicht lesen: {e}")

    # Standardwerte setzen
    return {
        "url": config.get("INFLUXDB_URL", "http://localhost:8086"),
        "token": config.get("INFLUXDB_TOKEN", ""),
        "org": config.get("INFLUXDB_ORG", "AP78"),
        "bucket": config.get("INFLUXDB_BUCKET", "bucket-homelab"),
        "measurement": config.get("INFLUXDB_MEASUREMENT", "n8n_ollama-llm"),
    }


def influx_write(points, token, org, bucket, url):
    """Schreibt mehrere Punkte in InfluxDB."""
    if not points:
        return True

    if not token:
        for point in points:
            _print_dry_run(point)
        return True

    try:
        # InfluxDB v2 Write API: org/bucket/tag1=val1,tag2=val2 field1=value1 field2=value2 [timestamp]
        api_url = f"{url}/api/v2/write"

        query_params = []
        if org:
            query_params.append(f"org={org}")
        if bucket:
            query_params.append(f"bucket={bucket}")
        query_params.append("precision=ns")

        params_string = "&".join(query_params)
        if params_string:
            api_url += f"?{params_string}"

        # Builden der InfluxDB-Linien
        lines = []
        for point in points:
            line = _build_influx_line(point)
            lines.append(line)

        data = "\n".join(lines).encode("utf-8") if lines else b""

        req = Request(
            api_url,
            data=data,
            headers={
                "Authorization": f"Token {token}",
                "Content-Type": "application/json",
            },
            method="POST"
        )

        with urlopen(req, timeout=10) as response:
            status_text = response.status_text if hasattr(response, 'status_text') else ""
            print(f"[InfluxDB] Response: {response.status} {status_text}")

            body = b""
            try:
                body = response.read()
            except:
                pass

            if response.status in (204, 200):
                if body:
                    print(f"[InfluxDB] Body: {body.decode('utf-8')[:100]}")
                print("[InfluxDB] OK - Daten wurden erfolgreich geschrieben")
                return True
            else:
                error_msg = body.decode('utf-8', errors='ignore') if body else f"Kein Body"
                print(f"[InfluxDB] Fehler {response.status}: {error_msg}")
                return False

    except HTTPError as e:
        print(f"[InfluxDB] HTTP Error {e.code}: {e.reason}")
        try:
            error_body = e.read().decode('utf-8', errors='ignore')
            print(f"[InfluxDB] Fehler-Body: {error_body[:500]}")
        except:
            pass
        return False

    except URLError as e:
        print(f"[InfluxDB] URLError: {e.reason}")
        print("[InfluxDB] Hinweis: Prüfe ob InfluxDB-Server erreichbar ist")
        return False

    except Exception as e:
        print(f"[InfluxDB] Ausnahme: {type(e).__name__}: {e}")
        return False


def _build_influx_line(point):
    """Buildet eine validere InfluxDB-Linie im korrekten Format."""
    tags = point.get("tags", {})
    fields = point.get("fields", {})
    timestamp = point.get("timestamp", "")

    if not fields:
        return ""

    # Tags in korrektem Format (key="value") - KEINE doppelten Anfuhrungszeichen um den Key!
    tag_parts = []
    for k, v in sorted(tags.items()):
        key_safe = str(k).replace('.', '_').replace(',', '_')
        # Werte mit Sonderzeichen sanitizeieren: Leerzeichen, Punkte und Kommas entfernen
        value_safe = str(v).replace('"', "'").replace(' ', ' ').replace('.', '').replace(',', '').replace(':', '_')
        # Tags Format: gpu_name="value", nicht "gpu_name"="value"
        tag_parts.append(f'{key_safe}="{value_safe}"')

    # Felder als Key=Value - nur Integer/Float-Felder, keine Strings!
    field_parts = []
    for k, v in sorted(fields.items()):
        if isinstance(v, str):
            # String-Felder werden nicht geschrieben (InfluxDB hat Probleme damit)
            print(f"[WARN] String-Feld '{k}' übersprungen")
            continue
        elif isinstance(v, float) and v == int(v):
            # Gleitkommazahlen ohne Dezimalteil als Integer darstellen
            field_parts.append(f'{k}={int(v)}')
        elif isinstance(v, (float, int)) and not isinstance(v, bool):
            # Float/Int-Werte direkt verwenden
            field_parts.append(f'{k}={v}')
        else:
            field_parts.append(f'{k}={v}')

    # Zeitstempel am Ende - ISO-8601 Format mit Zonen-Kennzeichnung (wichtig!)
    ts_part = ""
    if timestamp and fields:  # Nur wenn Felder existieren!
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(timestamp)
            # Zeitzone entfernen und nur UTC-Zeit mit Zonen-Kennzeichnung
            ts_clean = dt.replace(tzinfo=None).strftime('%Y-%m-%dT%H:%M:%SZ')
            ts_part = f" {ts_clean}"
        except Exception as e:
            print(f"[WARN] Zeitstempel Parse Fehler: {e}")

    # Tags UND Felder kombinieren - korrektes InfluxDB Format
    if field_parts and tag_parts:
        line = ",".join(tag_parts) + "," + ",".join(field_parts) + ts_part
    elif field_parts:
        line = ",".join(field_parts) + ts_part
    else:
        line = ""

    return line


def _print_dry_run(point):
    """Drucken für Dry-Run Modus."""
    tags = point.get("tags", {})
    fields = point.get("fields", {})

    print(f"  Tags: {tags}")
    print(f"  Felder: {fields}")
    if "timestamp" in point:
        print(f"  Timestamp: {point['timestamp']}")


def parse_nvidia_smi_output(raw_output):
    """
    Parset den nvidia-smi Output in ein Dict.
    Format: name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,fan.speed,clocks.gr
    """
    if not raw_output.strip():
        return None

    parts = [p.strip() for p in raw_output.strip().split(",")]

    def safe_float(x):
        try:
            return float(x)
        except ValueError:
            return 0.0

    return {
        "name": parts[0] if len(parts) > 0 else "",
        "util": safe_float(parts[1]) if len(parts) > 1 else 0,
        "vram": safe_float(parts[2]) if len(parts) > 2 else 0,
        "vramtot": safe_float(parts[3]) if len(parts) > 3 else 0,
        "temp": safe_float(parts[4]) if len(parts) > 4 else 0,
        "power": safe_float(parts[5]) if len(parts) > 5 else 0,
        "fan": safe_float(parts[6]) if len(parts) > 6 else 0,
        "clock": safe_float(parts[7]) if len(parts) > 7 else 0,
    }


def query_gpu():
    """Abfrage der GPU-Werte via nvidia-smi."""
    # Pfad zu nvidia-smi bestimmen
    from shutil import which
    nvidia_smi = which("nvidia-smi") or "nvidia-smi"

    create_no_window = 0x08000000 if os.name == "nt" else 0

    try:
        output = subprocess.run(
            [nvidia_smi, "--id=0", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,fan.speed,clocks.gr",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
            creationflags=create_no_window
        )

        gpu_data = parse_nvidia_smi_output(output.stdout)

        if output.returncode != 0 or not gpu_data:
            return None

        # GPU-Namen mit Sonderzeichen in Tags sanitizeieren (Leerzeichen, Punkte, Komma ersetzen)
        gpu_name = str(gpu_data.get("name", "")).replace(' ', '_').replace('.', '_').replace(',', '')

        now = datetime.now(timezone.utc)

        # NULL-Werte filtern (InfluxDB toleriert keine Nullen in Feldern ohne explizite Typdefinition)
        fields = {
            "load_pct": round(gpu_data["util"], 1),
            "vram_used_mb": gpu_data["vram"],
            "vram_total_mb": gpu_data["vramtot"],
            "temp_c": round(gpu_data["temp"], 1),
            "power_w": round(gpu_data["power"], 1),
            "fan_pct": round(gpu_data["fan"], 1),
            "clock_mhz": round(gpu_data["clock"], 1),
        }

        # Filtere Felder mit NULL/None Werten und GPU-Namen ohne Tag schreiben um Kompatibilität sicherzustellen
        fields = {k: v for k, v in fields.items() if v is not None}

        return {
            # Ohne Tags - InfluxDB akzeptiert es besser ohne gpu_name Tag
            "tags": {},
            "fields": fields,
            "timestamp": now.isoformat(),
        }
            "load_pct": round(gpu_data["util"], 1),
            "vram_used_mb": gpu_data["vram"],
            "vram_total_mb": gpu_data["vramtot"],
            "temp_c": round(gpu_data["temp"], 1),
            "power_w": round(gpu_data["power"], 1),
            "fan_pct": round(gpu_data["fan"], 1),
            "clock_mhz": round(gpu_data["clock"], 1),
        }

        # Filtere Felder mit NULL/None Werten
        fields = {k: v for k, v in fields.items() if v is not None}

        return {
            "tags": {"gpu_name": gpu_name},
            "fields": fields,
            "timestamp": now.isoformat(),
        }

    except subprocess.TimeoutExpired:
        print("[Fehler] nvidia-smi Timeout")
        return None
    except Exception as e:
        print(f"[Fehler] nvidia-smi Fehler: {e}")
        return None


def parse_ollama_ps_output(json_data):
    """
    Parset Ollama /api/ps Response.
    Liefert Dict mit Liste der geladenen Modelle.
    """
    models = json_data.get("models", [])
    return models


def query_llm():
    """Abfrage des aktuellen LLM-Status via Ollama API."""
    try:
        url = "http://localhost:11434/api/ps"
        with urlopen(url, timeout=5) as response:
            json_data = json.loads(response.read().decode("utf-8"))

    except Exception as e:
        print(f"[LLM] Ollama API nicht erreichbar oder Fehler: {e}")
        return None

    models = parse_ollama_ps_output(json_data)

    if not models or len(models) == 0:
        return None

    # Groesstes Modell nach VRAM-Größe wahlen (das ist das aktuelle LLM)
    llm = max(models, key=lambda m: float(m.get("size_vram", 0)) + float(m.get("size", 0)))

    name = llm.get("name", "unknown")
    size = llm.get("size", "") or ""
    vram_mb = float(llm.get("size_vram", 0)) or 0
    total_mb = float(llm.get("size", 0)) if size else 0
    on_gpu = vram_mb > 0

    # GPU-Anteil berechnen
    gpu_frac = (vram_mb / total_mb) if total_mb and total_mb > 0 else 0

    # TTL bis zum Entladen (falls vorhanden)
    ttl_seconds = None
    expires_at = llm.get("expires_at")

    if expires_at:
        try:
            exp_str = expires_at.strip()

            # Nanosekunden entfernen, falls vorhanden
            if "." in exp_str:
                head, sep, tail = exp_str.partition(".")
                tz_offset = ""

                for i, ch in enumerate(tail):
                    if ch in "+-Zz":
                        tz_offset = tail[i:]
                        exp_str = head + "." + tail[:i] + tz_offset
                        break

            # Zeitzonen-Suffix标准化ieren
            exp_str = exp_str.replace("Z", "+00:00")

            from datetime import datetime as dt, timezone as tz

            exp_dt = dt.fromisoformat(exp_str)

            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)

            now_utc = datetime.now(timezone.utc)

            # TTL berechnen (positive Werte = Zeit bis Entladen, negative = bereits ueberfellig)
            ttl_seconds = (exp_dt - now_utc).total_seconds()

        except Exception as e:
            print(f"[LLM] TTL Parse Fehler: {e}")
            ttl_seconds = None

    # LLM-Namen mit Sonderzeichen sanitizeieren und als Tag nicht schreiben!
    safe_name = str(name).replace('.', '_').replace(':', '_')

    now_utc = datetime.now(timezone.utc)

    return {
        # LLM-Daten haben keine gpu_name Tags - wir verwenden separate Punkte
        "tags": {"measurement_type": "llm"},
        "fields": {
            "vram_mb": vram_mb,
            "vram_pct": round(gpu_frac * 100, 2),
            "total_vram_mb": total_mb,
            "on_gpu": int(on_gpu),
        },
        "ttl_seconds": ttl_seconds,
        "timestamp": now_utc.isoformat(),
    }


def main():
    """Main Loop - Laeuft alle 30 Sekunden."""
    print("=" * 70)
    print("InfluxDB Exporter fuer GPU Gadget")
    print("Misst: Load, Temp, Power, Clock, Fan, LLM-Werte")
    print(f"Wartezeit: 30 Sekunden")
    print("=" * 70)

    # Initialisierung
    config = load_influx_config()
    points_buffer = []  # Buffer fuer InfluxDB-Punkte (optional)
    buffer_interval = 1.0  # Alle Sekunde schreiben

    last_loaded_model = None  # Namen des zuletzt geladenen Modells
    last_load_timestamp = None  # Zeitpunkt des Ladevorgangs

    try:
        print("\nInfluxDB Exporter gestartet. Druecke Ctrl+C zum Stoppen.")
        print("-" * 70)
        start_time = datetime.now(timezone.utc)
        interval_seconds = 30.0
        last_write_time = start_time

        while True:
            try:
                now = datetime.now(timezone.utc)
                elapsed = (now - start_time).total_seconds()

                print(f"\n[Zeit] {elapsed:.1f}s")

                # 1. GPU-Daten abfragen
                gpu_data = query_gpu()

                if gpu_data:
                    write_log(gpu_data, "GPU", last_loaded_model)
                else:
                    print("[INFO] Keine GPU Daten verfuegbar")

                # 2. LLM-Daten abfragen
                llm_data = query_llm()

                if llm_data:
                    model_name = llm_data["fields"].get("llm_name", "unknown")

                    # Wenn das Modell sich aendert, speichere den Startzeitpunkt
                    if last_loaded_model and model_name != last_loaded_model:
                        # Vorheriges Modell wurde entladen (bzw. ersetzt)
                        print(f"\n[LLM] Modellwechsel von '{last_loaded_model}' zu '{model_name}'")

                        # Speichere Entlade-Ereignis fuer das alte Modell
                        unload_event = {
                            "tags": {"gpu_name": "nvidia-gpu", "model_type": "unload"},
                            "fields": {
                                "llm_name": last_loaded_model,
                                "event": "unload_complete",
                                "vram_mb": 0,
                            },
                            "timestamp": now.isoformat(),
                        }
                        influx_write([unload_event], config["token"],
                                    config["org"], config["bucket"], config["url"])

                        # Speichere Lade-Ereignis fuer das neue Modell
                        load_event = {
                            "tags": {"gpu_name": "nvidia-gpu", "model_type": "load"},
                            "fields": {
                                "llm_name": model_name,
                                "event": "load_start",
                                "vram_mb": llm_data["fields"].get("vram_mb", 0),
                            },
                            "timestamp": now.isoformat(),
                        }
                        influx_write([load_event], config["token"],
                                    config["org"], config["bucket"], config["url"])

                    # Aktuelle GPU-Daten und LLM-Daten kombinieren
                    combined_point = {
                        **gpu_data,
                        **llm_data,
                    }

                    if llm_data["fields"].get("on_gpu"):
                        print(f"\n[LLM] Aktuell geladen: {model_name} "
                              f"({llm_data['fields'].get('vram_mb', 0):.1f} MB VRAM)")
                    else:
                        print(f"\n[LLM] Kein LLM aktuell im VRAM")

                else:
                    print(f"\n[LLM] Ollama API nicht erreichbar - keine LLM-Daten")

                # Fuercing: Alle Punkte in InfluxDB schreiben (nicht bufferen)
                points_to_write = [gpu_data, llm_data] if gpu_data and llm_data \
                                 else ([gpu_data] if gpu_data else [llm_data]) \
                                 or []

                if points_to_write:
                    influx_write(points_to_write, config["token"],
                                config["org"], config["bucket"], config["url"])

                # Warte den Rest des Intervalls aus
                wait_time = interval_seconds - elapsed % interval_seconds
                if wait_time > 0:
                    time.sleep(wait_time)

            except KeyboardInterrupt:
                print(f"\n\n[{now.strftime('%Y-%m-%d %H:%M:%S')}] Exporteur wurde gestoppt.")
                break
            except Exception as e:
                print(f"[ERROR] {e}")
                time.sleep(5)  # Bei Fehler kurz warten

    except KeyboardInterrupt:
        pass
    finally:
        print(f"\n[{now.strftime('%Y-%m-%d %H:%M:%S')}] InfluxDB Exporter geendet.")


def write_log(gpu_data, label, model_name=None):
    """Log-Funktion zum Ausgeben der Werte auf die Konsole."""
    if gpu_data:
        fields = gpu_data["fields"]
        print(f"  GPU: {fields['load_pct']}% Load, "
              f"{fields['vram_used_mb']}/{fields['vram_total_mb']} MB VRAM, "
              f"{fields['temp_c']}°C Temp, "
              f"{fields['power_w']} W Power, "
              f"{fields['fan_pct']}% Fan, "
              f"{fields['clock_mhz']} MHz Clock")

        if model_name:
            print(f"  LLM: {model_name} (VRAM-Anteil: {gpu_data['tags'].get('load_pct', 0)}%)")


if __name__ == "__main__":
    main()
