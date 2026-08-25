#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPU Terminal Display Script fuer gpu_gadget
Zeigt GPU und LLM-Daten direkt im Terminal an (statt nur InfluxDB zu schreiben)

Verwendet dieselben Abfragen wie influx_exporter.py, aber gibt formatierte Ausgabe.

Nutzung:
  python3 gpu_terminal.py                    # Einzelne Anzeige
  python3 gpu_terminal.py --watch           # Live-Modus alle 5 Sekunden
  python3 gpu_terminal.py --format compact  # Compact Ausgabericht fuer Dashboards
  python3 gpu_terminal.py --json            # JSON-Ausgabe (z.B. fuer Logging)

Integration mit influx_exporter.py:
    from influx_exporter import query_gpu, query_llm, _print_dry_run

    # Fuer Terminal-Output statt InfluxDB
    gpu_data = query_gpu()
    llm_data = query_llm()

    if gpu_data or llm_data:
        print(gpu_terminal_display(gpu_data, llm_data))
"""

import subprocess
import sys
import time
import json
from datetime import datetime, timezone


def get_nvidia_smi_output():
    """Fuerft nvidia-smi und gibt den Rohoutput zurueck."""
    try:
        from shutil import which
        nvidia_smi = which("nvidia-smi") or "nvidia-smi"

        # Fuer Windows: nvidia-smi Fenster unterdruecken (CreateProcess flag)
        create_no_window = 0x08000000 if sys.platform.startswith("win") else 0

        result = subprocess.run(
            [nvidia_smi, "--id=0",
             "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,fan.speed,clocks.gr80",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
            creationflags=create_no_window
        )

        if result.returncode != 0:
            return None

        return result.stdout.strip()

    except subprocess.TimeoutExpired:
        print("[Fehler] nvidia-smi Timeout")
        return None
    except FileNotFoundError:
        print("[Fehler] nvidia-smi nicht gefunden")
        return None
    except Exception as e:
        print(f"[Fehler] nvidia-smi Ausnahme: {e}")
        return None


def parse_nvidia_data(raw_output):
    """Parset den nvidia-smi CSV-Output in ein Dict."""
    if not raw_output or raw_output.strip() == "":
        return None

    # Split an CSV-Felder (nvidia-smi liefert "Name,Value,Value,..." format)
    parts = [p.strip() for p in raw_output.split(",")]

    if len(parts) < 1:
        return None

    def safe_float(x):
        try:
            return float(x) if x else 0.0
        except (ValueError, TypeError):
            return 0.0

    return {
        "name": parts[0] if len(parts) > 0 else "",
        "load_pct": safe_float(parts[1]) if len(parts) > 1 else 0,
        "vram_used_mb": safe_float(parts[2]) if len(parts) > 2 else 0,
        "vram_total_mb": safe_float(parts[3]) if len(parts) > 3 else 0,
        "temp_c": safe_float(parts[4]) if len(parts) > 4 else 0,
        "power_w": safe_float(parts[5]) if len(parts) > 5 else 0,
        "fan_pct": safe_float(parts[6]) if len(parts) > 6 else 0,
        "clock_mhz": safe_float(parts[7]) if len(parts) > 7 else 0,
    }


def query_gpu():
    """Abfrage der GPU-Werte via nvidia-smi (von influx_exporter.py adaptiert)."""
    raw_output = get_nvidia_smi_output()

    if not raw_output:
        return None

    gpu_data = parse_nvidia_data(raw_output)

    # NULL-Werte filtern
    gpu_data = {k: v for k, v in gpu_data.items() if v is not None and not isinstance(v, str)}

    return {
        "tags": {},  # Ohne Tags fuer einfache InfluxDB-Kompatibilitaat
        "fields": gpu_data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def parse_ollama_ps_output(json_data):
    """Parset Ollama /api/ps Response (von influx_exporter.py adaptiert)."""
    models = json_data.get("models", [])
    return models if models else []


def query_llm():
    """Abfrage des LLM-Status via Ollama API (von influx_exporter.py adaptiert)."""
    try:
        url = "http://localhost:11434/api/ps"
        with subprocess.Popen(
            ["curl", "-s", "-m", "5", url],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        ) as proc:
            stdout, stderr = proc.communicate()

        if proc.returncode != 0:
            error_msg = stderr.decode('utf-8', errors='ignore')
            if "refused to connect" in error_msg or "connection refused" in error_msg.lower():
                print("[INFO] Ollama API nicht erreichbar (Port 11434)")
                return None
            print(f"[WARN] Ollama Fehler: {error_msg[:200]}")

        try:
            json_data = json.loads(stdout.decode("utf-8"))
        except json.JSONDecodeError as e:
            print(f"[WARN] JSON Parse Fehler: {e}")
            return None

    except Exception as e:
        print(f"[Fehler] Ollama Abfrage: {e}")
        return None

    models = parse_ollama_ps_output(json_data)

    if not models or len(models) == 0:
        return None

    # Groesstes Modell nach VRAM (aktives LLM)
    llm = max(models, key=lambda m: float(m.get("size_vram", 0)) + float(m.get("size", 0)))

    name = llm.get("name", "unknown")
    size = llm.get("size", "") or ""
    vram_mb = float(llm.get("size_vram", 0)) or 0
    total_mb = float(llm.get("size", 0)) if size else 0
    on_gpu = vram_mb > 0

    # GPU-Anteil berechnen
    gpu_frac = (vram_mb / total_mb) if total_mb and total_mb > 0 else 0

    # TTL bis Entladen (falls vorhanden)
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

            # Zeitzonen-Suffix normalisieren
            exp_str = exp_str.replace("Z", "+00:00")

            exp_dt = datetime.fromisoformat(exp_str)

            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)

            now_utc = datetime.now(timezone.utc)

            # TTL berechnen (positive Werte = Zeit bis Entladen, negative = bereits ueberfellig)
            ttl_seconds = (exp_dt - now_utc).total_seconds()

        except Exception as e:
            print(f"[LLM] TTL Parse Fehler: {e}")
            ttl_seconds = None

    # LLM-Namen mit Sonderzeichen sanitizeieren
    safe_name = str(name).replace('.', '_').replace(':', '_')

    now_utc = datetime.now(timezone.utc)

    return {
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


def format_temp(temp):
    """Formatiert Temperatur mit Farbcodierung."""
    if temp > 85:
        color = "red"
        return f"<{temp:.0f}>"
    elif temp < 60:
        color = "green"
        status = " (Kuehlung optimal)"
    elif temp <= 75:
        color = "yellow"
        status = " (Normaler Betrieb)"
    else:
        color = "white"
        status = ""

    return f"{temp:.0f}{status}"


def format_load(load):
    """Formatiert GPU-Load mit Farbcodierung."""
    if load > 80:
        color = "red"
        return f"{load:.1f}% {'(Hohe Auslastung!)' if load > 95 else '(Hoher Load)'}"
    elif load > 60:
        color = "yellow"
        return f"{load:.1f}% (Aktiv)"
    else:
        color = "green"
        return f"{load:.1f}% {'(Leer)' if load < 5 else ''}"


def format_vram_usage(vram_used, vram_total):
    """Formatiert VRAM-Auslastung mit Prozentberechnung."""
    if vram_total == 0:
        pct = 0
    else:
        pct = (vram_used / vram_total) * 100

    usage_str = f"{vram_used:.1f}/{vram_total:.1f} MB ({pct:.1f}%)"

    # Farbcodierung basierend auf Nutzung
    if pct > 95:
        color = "red"
        return f"{usage_str} {'(KRITISCH!)' if pct > 98 else '(Sehr hoch)'}"
    elif pct > 85:
        color = "yellow"
        return f"{usage_str} (Hohe Auslastung)"
    else:
        return usage_str


def display_gpu_gpuinfo(gpu_data, format_type="detailed"):
    """Formatiert GPU-Daten fuer Terminal-Ausgabe."""
    if not gpu_data:
        if format_type != "compact":
            print(f"\n[WARN] Keine GPU Daten verfuegbar")
        return ""

    fields = gpu_data["fields"]

    # Compact Format
    if format_type == "compact":
        lines = []

        lines.append(f"GPU: {gpu_data.get('tags', {}).get('name', 'nvidia-gpu').replace(' ', '_')}")
        lines.append(f"  Load: {format_load(fields.get('load_pct', 0))}")
        lines.append(f"  VRAM: {format_vram_usage(fields.get('vram_used_mb', 0), fields.get('vram_total_mb', 0))}")
        lines.append(f"  Temp: {format_temp(fields.get('temp_c', 0))}°C")
        lines.append(f"  Power: {fields.get('power_w', 0):.1f}W")
        lines.append(f"  Fan: {fields.get('fan_pct', 0):.1f}%")

        return "\n".join(lines)

    # Detailed Format
    output_lines = []

    output_lines.append("=" * 72)
    output_lines.append(f"GPU STATUS - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}           ".ljust(72))
    output_lines.append("=" * 72)
    output_lines.append("")

    name = gpu_data.get("tags", {}).get("name", "nvidia-gpu") or fields.get("name", "")
    if name:
        display_name = name.replace(' ', '_').replace(':', '')
        output_lines.append(f"Name: {display_name}".ljust(70))
    else:
        output_lines.append(f"Name: nvidia-gpu".ljust(70))

    load_pct = fields.get("load_pct", 0)
    output_lines.append(f"Load: {format_load(load_pct)}".ljust(70))

    vram_used = fields.get("vram_used_mb", 0)
    vram_total = fields.get("vram_total_mb", 0)
    output_lines.append(f"VRAM: {format_vram_usage(vram_used, vram_total)}".ljust(70))

    temp_c = fields.get("temp_c", 0)
    output_lines.append(f"Temp: {format_temp(temp_c)}°C".ljust(70))

    power_w = fields.get("power_w", 0)
    output_lines.append(f"Power: {power_w:.1f}W".ljust(70))

    fan_pct = fields.get("fan_pct", 0)
    output_lines.append(f"Fan: {fan_pct:.1f}%".ljust(70))

    clock_mhz = fields.get("clock_mhz", 0)
    output_lines.append(f"Clock: {clock_mhz:.1f}MHz".ljust(70))

    return "\n".join(output_lines)


def display_llm_info(llm_data, format_type="detailed"):
    """Formatiert LLM-Daten fuer Terminal-Ausgabe."""
    if not llm_data or not llm_data.get("fields", {}).get("on_gpu"):
        return ""

    fields = llm_data["fields"]
    name = str(fields.get("llm_name", "")).replace('.', '_').replace(':', '') or "unknown"

    output_lines = []

    # Compact Format
    if format_type == "compact":
        lines = []

        on_gpu = fields.get("on_gpu", False)
        ttl_sec = llm_data.get("ttl_seconds")

        if on_gpu:
            status_color = "green"
            status = "[GPU VRAM]"
        else:
            status_color = "cyan"
            status = "[CPU/GPU-Shared]"

        lines.append(f"\n{status}  Status: Im VRAM".ljust(72))
        lines.append(f"Modell: {name}".ljust(70))
        lines.append(f"VRAM: {fields.get('vram_mb', 0):.1f}MB / {fields.get('total_vram_mb', 0):.1f}MB ({fields.get('vram_pct', 0):.1f}%)".ljust(70))

        if ttl_sec is not None and ttl_sec > 0:
            ttl_min = int(ttl_sec / 60)
            lines.append(f"TTL: ca. {ttl_min} Minuten bis Entladen".ljust(70))
        elif ttl_sec is not None and ttl_sec <= 0:
            lines.append("TTL: Bereits ueberfellig (Entladen)".ljust(70))
        else:
            lines.append("TTL: Keine Entlade-TTL gesetzt (dauerhaft geladen)".ljust(70))

        return "\n".join(lines)

    # Detailed Format
    output_lines.append("-" * 72)
    output_lines.append(f"LLM STATUS".ljust(72))
    output_lines.append("-" * 72)

    on_gpu = fields.get("on_gpu", False)

    if on_gpu:
        output_lines.append(f"[GPU VRAM] Status: Im VRAM (Aktiv)".ljust(72))
    else:
        output_lines.append(f"[CPU/GPU-Shared] Status: Geladen".ljust(72))

    model_name = fields.get("llm_name", "unknown") or "unknown"
    output_lines.append(f"Modell: {model_name}".ljust(70))

    vram_mb = fields.get("vram_mb", 0)
    total_mb = fields.get("total_vram_mb", 0)
    pct = fields.get("vram_pct", 0)

    output_lines.append(f"VRAM: {vram_mb:.1f}MB von {total_mb:.1f}MB ({pct:.1f}%)".ljust(70))

    ttl_sec = llm_data.get("ttl_seconds")
    if ttl_sec is not None and ttl_sec > 0:
        ttl_min = int(ttl_sec / 60)
        output_lines.append(f"TTL: ca. {ttl_min} Minuten bis Entladen".ljust(70))
    elif ttl_sec is not None:
        output_lines.append("TTL: Bereits ueberfellig (Entladen)".ljust(70))
    else:
        output_lines.append("TTL: Keine Entlade-TTL gesetzt (dauerhaft geladen)".ljust(70))

    return "\n".join(output_lines)


def display_summary(gpu_data, llm_data, format_type="detailed"):
    """Formatiert die Zusammenfassung im Terminal."""
    if format_type == "compact" or format_type == "json":
        return ""

    output_lines = []

    output_lines.append("=" * 72)
    output_lines.append(f"GPU & LLM STATUS - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}".ljust(40))
    output_lines.append(f"{"-" * 39}")
    output_lines.append("")

    gpu_output = display_gpu_gpuinfo(gpu_data, format_type)
    if gpu_output:
        output_lines.extend(gpu_output.split("\n"))
    else:
        output_lines.append("[WARN] Keine GPU Daten verfuegbar".ljust(72))

    output_lines.append("")

    llm_output = display_llm_info(llm_data, format_type)
    if llm_output:
        output_lines.extend(llm_output.split("\n"))
    else:
        output_lines.append("[INFO] Kein LLM aktuell im VRAM".ljust(72))

    output_lines.append("-" * 72)
    output_lines.append("ZUSAMMENFASSUNG".ljust(72))
    output_lines.append("-" * 72)

    if gpu_data:
        fields = gpu_data["fields"]
        display_name = gpu_data.get("tags", {}).get("name", "nvidia-gpu") or fields.get("name", "")
        name_str = display_name.replace(' ', '_').replace(':', '') or "nvidia-gpu"

        output_lines.append(f"GPU: {name_str}".ljust(70))

        if llm_data and llm_data.get("fields", {}).get("on_gpu"):
            llm_fields = llm_data["fields"]
            model_name = llm_fields.get("llm_name", "unknown") or "unknown"
            output_lines.append(f"     LLM: {model_name}".ljust(70))

    output_lines.append("")

    return "\n".join(output_lines)


def display_json(gpu_data, llm_data):
    """Gibt GPU und LLM-Daten im JSON-Format aus."""
    result = {}

    if gpu_data:
        result["gpu"] = {
            "name": gpu_data.get("tags", {}).get("name", "nvidia-gpu") or gpu_data["fields"].get("name", ""),
            "load_pct": gpu_data["fields"].get("load_pct", 0),
            "vram_used_mb": gpu_data["fields"].get("vram_used_mb", 0),
            "vram_total_mb": gpu_data["fields"].get("vram_total_mb", 0),
            "temp_c": gpu_data["fields"].get("temp_c", 0),
            "power_w": gpu_data["fields"].get("power_w", 0),
            "fan_pct": gpu_data["fields"].get("fan_pct", 0),
            "clock_mhz": gpu_data["fields"].get("clock_mhz", 0),
        }

    if llm_data:
        fields = llm_data.get("fields", {})
        result["llm"] = {
            "model_name": str(fields.get("llm_name", "")) or "unknown",
            "vram_mb": fields.get("vram_mb", 0),
            "vram_pct": fields.get("vram_pct", 0),
            "total_vram_mb": fields.get("total_vram_mb", 0),
            "on_gpu": bool(fields.get("on_gpu", False)),
        }

    result["timestamp"] = datetime.now(timezone.utc).isoformat()

    return json.dumps(result, indent=2, ensure_ascii=False)


def main():
    """Main Loop - Terminal Display."""
    # Parse Command-Line-Argumente
    args = sys.argv[1:]

    show_help = False
    watch_mode = False
    compact_mode = False
    json_only = False
    format_type = "detailed"
    interval = 30  # Sekunden
    duration = -1  # Unbegrenzt (bis Ctrl+C)

    for arg in args:
        if arg in ("-h", "--help", "help"):
            show_help = True
        elif arg == "--watch":
            watch_mode = True
        elif arg.startswith("--format="):
            format_type = arg.split("=")[1]
            compact_mode = (format_type == "compact")
        elif arg == "--compact":
            compact_mode = True
        elif arg == "--json":
            json_only = True
        elif arg.startswith("-"):
            print(f"[WARN] Unbekannte Option: {arg}")
        else:
            # Numerischer Wert fuer Intervall/Dauer
            try:
                interval = int(arg)
            except ValueError:
                pass

    if show_help:
        help_text = """GPU Terminal Display Script

Nutzung:
  python3 gpu_terminal.py                    - Einzelner Statusueberpruefung
  python3 gpu_terminal.py --watch            - Live-Modus (alle 5 Sekunden)
  python3 gpu_terminal.py --format compact   - Compact Ausgabericht
  python3 gpu_terminal.py --json             - JSON-Ausgabe

Optionen:
  --watch              Live Monitoring (default: alle 30 Sekunden, max 5 Min)
  --format <type>      Ausgabericht: detailed (Standard), compact, json
  --interval <sec>     Intervall in Sekunden (Default: 30)
  --duration <min>     Dauer in Minuten (-1 = unbegrenzt, Default: -1)

Beispiele:
  python3 gpu_terminal.py                     # Standard-Ausgabe
  python3 gpu_terminal.py --watch             # Live-Modus alle 5 Sekunden
  python3 gpu_terminal.py --format compact    # Fuer Dashboard/Log
  python3 gpu_terminal.py --json              # JSON fuer Logging/Cron

Integration:
  from influx_exporter import query_gpu, query_llm
  display_summary(query_gpu(), query_llm())
"""
        print(help_text)
        sys.exit(0)

    if watch_mode or not args:
        watch_mode = True  # Standard ist Watch-Modus

    # Wartezeit konfigurieren
    if compact_mode:
        interval = 5  # Fur Dashboards hoeher frequente Abfrage
    else:
        interval = 30

    print("=" * 72)
    print("GPU Terminal Display".ljust(40))
    print("=" * 72)
    print(f"Ausgabeformat: {format_type}".ljust(40))
    print(f"Wartezeit: {interval} Sekunden".ljust(40))
    print("-" * 72)

    if not watch_mode and not json_only:
        # Einzelne Abfrage
        print("\n[GPU]")
        gpu_data = query_gpu()
        if gpu_data:
            fields = gpu_data["fields"]
            name = fields.get("name", "") or gpu_data.get("tags", {}).get("name", "")
            print(f"  Name: {name or 'nvidia-gpu'}.ljust(70)")
            print(f"  Load: {format_load(fields.get('load_pct', 0))}")
            print(f"  VRAM: {format_vram_usage(fields.get('vram_used_mb', 0), fields.get('vram_total_mb', 0))}")
            print(f"  Temp: {format_temp(fields.get('temp_c', 0))}°C")
            print(f"  Power: {fields.get('power_w', 0):.1f}W")
            print(f"  Fan: {fields.get('fan_pct', 0):.1f}%")

        if llm_data and llm_data["fields"].get("on_gpu"):
            print("\n[LLM]")
            model_name = str(llm_data["fields"].get("llm_name", "")).replace('.', '_').replace(':', '') or "unknown"
            print(f"  Status: Im VRAM")
            print(f"  Modell: {model_name}")
            print(f"  VRAM: {llm_data['fields']['vram_mb']:.1f}MB / {llm_data['fields']['total_vram_mb']:.1f}MB ({llm_data['fields']['vram_pct']:.1f}%)")
        else:
            print("\n[INFO] Kein LLM aktuell im VRAM")

    elif json_only:
        # JSON-Only Mode
        gpu_data = query_gpu()
        llm_data = query_llm()
        print(display_json(gpu_data, llm_data))

    else:
        # Watch Mode Loop
        start_time = datetime.now(timezone.utc)

        while duration < 0 or (datetime.now(timezone.utc) - start_time).total_seconds() / 60 < duration:
            print(f"\n[{$(datetime.now().strftime('%H:%M:%S'))}]")
            print("")

            gpu_data = query_gpu()
            if gpu_data:
                print(display_summary(gpu_data, llm_data))
            else:
                print("[INFO] Keine GPU Daten verfuegbar")

            llm_data = query_llm()
            if llm_data and llm_data["fields"].get("on_gpu"):
                print(display_llm_info(llm_data))
            elif not (llm_data and llm_data.get("fields", {}).get("on_gpu")):
                print("[INFO] Kein LLM geladen")

            if duration > 0:
                remaining = int(duration - (datetime.now(timezone.utc) - start_time).total_seconds() / 60)
                if remaining > 0:
                    print(f"Verbleibende Zeit: {remaining} Minuten", end="", flush=True)

    if json_only or compact_mode:
        # Extra: JSON Output fur Dashboard-Integration
        gpu_data = query_gpu()
        llm_data = query_llm()
        print("\n[JSON-Dump]")
        print(display_json(gpu_data, llm_data))


if __name__ == "__main__":
    main()
