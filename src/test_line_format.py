#!/usr/bin/env python3
"""Test das korrekte InfluxDB-Linie Format"""

# Beispiel: Was wir haben
tags = {'gpu_name': 'NVIDIA GeForce RTX 3060'}
fields = {'load_pct': 2.0, 'vram_used_mb': 11846.0}

# Verschiedene Formate testen
print("=== Format Vorschläge ===")

# Format 1: key="value",field=val
line1 = f'"{list(tags.keys())[0]}"="{tags[list(tags.keys())[0]]}",load_pct=2,vram_used_mb=11846'
print(f"Format 1: {line1}")

# Format 2: key="value field=val (ohne Komma zwischen)
line2 = f'{list(tags.keys())[0]}="{tags[list(tags.keys())[0]]}" load_pct=2 vram_used_mb=11846'
print(f"Format 2: {line2}")

# Format 3: mit Leerzeichen nach Tag
line3 = f'"{list(tags.keys())[0]}"="{tags[list(tags.keys())[0]]}" load_pct=2 vram_used_mb=11846'
print(f"Format 3: {line3}")
