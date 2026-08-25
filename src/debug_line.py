#!/usr/bin/env python3
"""Debug-Skript um InfluxDB-Linien zu debuggen"""

import influx_exporter as ie

# GPU-Daten abfragen
gpu_data = ie.query_gpu()

# LLM-Daten abfragen
llm_data = ie.query_llm()

print("=== GPU Data ===")
print(gpu_data)
print("\nTags:", gpu_data.get("tags"))
print("Fields:", list(gpu_data.get("fields", {}).keys()))

print("\n=== LLM Data ===")
print(llm_data)
print("\nTags:", llm_data.get("tags"))
print("Fields:", list(llm_data.get("fields", {}).keys()))

# Linie generieren
print("\n=== Generierte Linien ===")
line_gpu = ie._build_influx_line(gpu_data)
print("GPU-Linie:")
print(line_gpu)

line_llm = ie._build_influx_line(llm_data)
print("\nLLM-Linie:")
print(line_llm)
