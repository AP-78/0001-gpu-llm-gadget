#!/usr/bin/env python3
"""Test-Skript um InfluxDB Exporter zu testen (eine Iteration)"""

import influx_exporter as ie

def main():
    print("=" * 70)
    print("InfluxDB Exporter TEST - Eine Iteration")
    print("=" * 70)

    # Konfiguration laden
    config = ie.load_influx_config()
    print(f"\nVerbindung: {config['url']}")
    print(f"Org: {config['org']}, Bucket: {config['bucket']}")

    # GPU-Daten abfragen
    gpu_data = ie.query_gpu()
    print(f"\n1. GPU-Daten: {gpu_data is not None}")

    # LLM-Daten abfragen
    llm_data = ie.query_llm()
    print(f"2. LLM-Daten: {llm_data is not None}")

    # InfluxDB schreiben
    points_to_write = [gpu_data, llm_data] if gpu_data and llm_data \
                     else ([gpu_data] if gpu_data else [llm_data]) \
                     or []

    print(f"\n3. Punkte zu schreiben: {len(points_to_write)}")

    if points_to_write:
        result = ie.influx_write(points_to_write,
                                config["token"],
                                config["org"], config["bucket"], config["url"])
        print(f"Ergebnis: {result}")

if __name__ == "__main__":
    main()
