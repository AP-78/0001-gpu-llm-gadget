# ============================================================================
# GPU Monitor PowerShell Skript fuer gpu_gadget
# Misst GPU und LLM-Daten und zeigt sie direkt im Terminal an
# Anstelle von InfluxDB
# ============================================================================

# Requires: PowerShell 5.1+
# Dependencies: nvidia-smi, Ollama API

function global:Get-GpuInfo {
    <#
    .SYNOPSIS
        Fuegt GPU-Informationen aus nvidia-smi ab

    .DESCRIPTION
        Laeset den nvidia-smi Output und extrahiert GPU-Daten wie Load, VRAM,
        Temperatur, Power, Fan Speed und Clock. Die Daten werden formatiert im Terminal ausgegeben.

    .EXAMPLE
        Get-GpuInfo
        Ausgibt alle GPU-Informationen

    .OUTPUTS
        System.Collections.Hashtable mit GPU-Daten
    #>

    try {
        $nvidiaSmiPath = Get-Command nvidia-smi | Select-Object -ExpandProperty Source
        if (-not $nvidiaSmiPath) {
            Write-Host "[Fehler] nvidia-smi nicht gefunden. Fuer Windows: 'nvidia-smi' in PATH pruefen." -ForegroundColor Red
            return $null
        }

        # nvidia-smi ohne Fenster laeuft ab
        $processInfo = Start-Process -FilePath $nvidiaSmiPath -ArgumentList `
            "--id=0", `
            "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,fan.speed,clocks.gr", `
            "--format=csv,noheader,nounits" `
            -RedirectStandardOutput "gpu_smi_output.txt" -PassThru

        if ($processInfo.ExitCode -ne 0) {
            $content = Get-Content -Path "gpu_smi_output.txt" -Raw
            Write-Host "[Fehler] nvidia-smi Fehler: $content" -ForegroundColor Red
            Remove-Item -Path "gpu_smi_output.txt" -ErrorAction SilentlyContinue
            return $null
        }

        $rawOutput = Get-Content -Path "gpu_smi_output.txt" -Raw
        Remove-Item -Path "gpu_smi_output.txt" -Force

        # CSV Parsen (nvidia-smi liefert CSV)
        if ($rawOutput.Trim() -eq "") {
            Write-Host "[WARN] Keine GPU Daten gefunden" -ForegroundColor Yellow
            return $null
        }

        # CSV Zeilen in Objekte umwandeln
        $parts = $rawOutput.Trim().Split([Environment]::NewLine)

        $gpuData = [ordered]@{
            GpuName = $parts[0]
            LoadPct = if ($parts.Count -gt 1) { [int]$parts[1] } else { 0 }
            VRAMUsedMB = if ($parts.Count -gt 2) { [int]$parts[2] } else { 0 }
            VRAMTotalMB = if ($parts.Count -gt 3) { [int]$parts[3] } else { 0 }
            TempC = if ($parts.Count -gt 4) { [int]$parts[4] } else { 0 }
            PowerW = if ($parts.Count -gt 5) { [int]$parts[5] } else { 0 }
            FanPct = if ($parts.Count -gt 6) { [int]$parts[6] } else { 0 }
            ClockMHz = if ($parts.Count -gt 7) { [float]$parts[7] } else { 0 }
        }

        return $gpuData

    } catch {
        Write-Host "[Fehler] ${$_}" -ForegroundColor Red
        return $null
    }
}

function global:Get-LlmInfo {
    <#
    .SYNOPSIS
        Fuegt aktuelle LLM-Daten von Ollama ab

    .DESCRIPTION
        Fuerft eine Abfrage an die Ollama API (/api/ps) und gibt Information
        ueber das aktuell geladene Modell, VRAM-Nutzung und Entlade-TTL aus.

    .EXAMPLE
        Get-LlmInfo
        Ausgibt LLM-Informationen

    .OUTPUTS
        System.Collections.Hashtable mit LLM-Daten oder $null wenn keine Modelle geladen
    #>

    try {
        $ollamaUrl = "http://localhost:11434/api/ps"
        $response = Invoke-RestMethod -Uri $ollamaUrl -Method Get -TimeoutSec 5 -ErrorAction Stop

        $models = $response.models

        if (-not $models -or $models.Count -eq 0) {
            Write-Host "[INFO] Kein LLM aktuell im VRAM" -ForegroundColor Cyan
            return $null
        }

        # Groesstes Modell nach VRAM-Wahl (aktives LLM)
        $activeModel = [System.Linq.Enumerable]::Max($models | Where-Object { $_.size_vram })

        $llmData = [ordered]@{
            ModelName = $activeModel.name -replace '\.', '_'-replace ':', ''
            VRAMMB = [int]$activeModel.size_vram
            VRAMTotalMB = [int]$activeModel.size
            VRAMPct = if ($activeModel.size -gt 0) {
                ([math]::Round((($activeModel.size_vram / $activeModel.size) * 100), 2))
            } else { 0 }
            OnGpu = $true
        }

        # TTL bis Entladen (falls vorhanden)
        if ($activeModel.expires_at) {
            $expiresStr = $activeModel.expires_at.Trim()

            # Nanosekunden entfernen
            if ($expiresStr -match '\.') {
                $split = $expiresStr.Split('.')
                $tzPart = $split[1]
                $tzMatch = [regex]::Match($tzPart, '(?=\+[0-9]|[+-]\d{2}:\d{2}|Z)', [System.Text.RegularExpressions]::RegexOptions.IgnoreCase)
                if ($tzMatch) {
                    $expiresStr = ${split}[0].Substring(0, ${split}[0].Length - (${tzMatch.Index} + ${tzMatch.Value.Length}))
                }
            }

            # Zeitzonen-Suffix normalisieren
            $expiresStr = $expiresStr.Replace('Z', '+00:00')

            try {
                $expDateTime = [DateTimeOffset]::Parse($expiresStr).DateTime

                $now = [DateTimeOffset]::UtcNow.DateTime

                $ttlSeconds = ($expDateTime - $now).TotalSeconds

                if ($ttlSeconds -gt 0) {
                    $llmData.TTLSeconds = [int]$ttlSeconds
                    $llmData.ExpiresAt = $expiresStr
                }
            } catch {
                Write-Host "[WARN] TTL Parse Fehler: $_" -ForegroundColor Yellow
                $llmData.TTLSeconds = $null
            }
        }

        return $llmData

    } catch {
        if ($_.Exception.Message -like "*refused to connect*" -or $_.Exception.Message -like "*connection refused*") {
            Write-Host "[INFO] Ollama API nicht erreichbar (Port 11434)" -ForegroundColor Yellow
        } else {
            Write-Host "[Fehler] Ollama API Fehler: $_" -ForegroundColor Red
        }
        return $null
    }
}

function global:Get-GpuSummary {
    <#
    .SYNOPSIS
        Fuegt zusammengefasste GPU- und LLM-Daten mit Zeitstempel aus

    .DESCRIPTION
        Kombiniert Get-GpuInfo und Get-LlmInfo und gibt die Daten formatiert im Terminal aus.

    .EXAMPLE
        Get-GpuSummary
        Fuerft eine komplette Statusueberpruefung und zeigt formatierten Output

    .OUTPUTS
        Keine - Ausgabe rein im Terminal
    #>

    $now = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

    Write-Host "==============================================================" -ForegroundColor Cyan
    Write-Host "       GPU & LLM STATUS -$now                          " -ForegroundColor Cyan
    Write-Host "==============================================================" -ForegroundColor Cyan
    Write-Host ""

    # GPU-Daten abfragen
    $gpuData = Get-GpuInfo

    if ($gpuData) {
        Write-Host "[GPU]" -ForegroundColor Yellow
        Write-Host "  Name: $($gpuData.GpuName)" -ForegroundColor White
        Write-Host "  Load: $($gpuData.LoadPct)% GPU-Load" -ForegroundColor White
        Write-Host "  VRAM: $($gpuData.VRAMUsedMB) / $($gpuData.VRAMTotalMB) MB ($([math]::Round((($gpuData.VRAMUsedMB/$gpuData.VRAMTotalMB)*100),1))%)" -ForegroundColor White
        Write-Host "  Temp: $(if ($gpuData.TempC -gt 85) { "<$([math]::Round($gpuData.TempC,0)>"} else { $gpuData.TempC }) C" -ForegroundColor White
        if ($gpuData.TempC -lt 60) {
            Write-Host "  Temp: OK (Kuehlung ausreichend)" -ForegroundColor Green
        } elseif ($gpuData.TempC -le 75) {
            Write-Host "  Temp: Normaler Betrieb" -ForegroundColor Yellow
        } elseif ($gpuData.TempC -lt 85) {
            Write-Host "  Temp: Warm, Achten Sie darauf!" -ForegroundColor Red
        } else {
            Write-Host "  Temp: Kuehlung ueberpruefen!" -ForegroundColor DarkRed
        }
        Write-Host "  Power: $($gpuData.PowerW) W" -ForegroundColor White
        Write-Host "  Fan:  $($gpuData.FanPct)%" -ForegroundColor White
        Write-Host "  Clock: $(if ($gpuData.ClockMHz -gt 0) { [math]::Round($gpuData.ClockMHz,1)} else { 0 }) MHz" -ForegroundColor White
        Write-Host ""
    } else {
        Write-Host "[GPU] Keine GPU Daten verfuegbar" -ForegroundColor DarkGray
        Write-Host ""
    }

    # LLM-Daten abfragen
    $llmData = Get-LlmInfo

    if ($llmData) {
        Write-Host "[LLM]" -ForegroundColor Green
        Write-Host "  Modell: $($llmData.ModelName)" -ForegroundColor White
        Write-Host "  VRAM:   $($llmData.VRAMMB) MB von $($llmData.VRAMTotalMB) MB ($($llmData.VRAMPct)%)" -ForegroundColor White
        Write-Host "  Status: Im VRAM" -ForegroundColor Green
        if ($llmData.TTLSeconds -gt 0) {
            $ttlMin = [math]::Floor($llmData.TTLSeconds / 60)
            Write-Host "  TTL:    ca. $ttlMin Minuten bis Entladen" -ForegroundColor Cyan
        } elseif (-not $llmData.TTLSeconds) {
            Write-Host "  TTL:    Keine Entlade-TTL gesetzt (dauerhaft geladen)" -ForegroundColor Yellow
        }
        Write-Host ""
    } else {
        Write-Host "[LLM] Kein LLM aktuell im VRAM" -ForegroundColor DarkGray
        Write-Host ""
    }

    # Gesamtuebersicht
    Write-Host "==============================================================" -ForegroundColor Cyan
    Write-Host "                       ZUSAMMENFASSUNG                        " -ForegroundColor Cyan
    Write-Host "==============================================================" -ForegroundColor Cyan

    $gpuCount = 1
    if ($gpuData) {
        Write-Host "GPU #$gpuCount: $($gpuData.GpuName)" -ForegroundColor White
        if ($llmData -and $llmData.OnGpu) {
            Write-Host "              > LLM: $($llmData.ModelName)" -ForegroundColor Cyan
        } elseif (-not $llmData) {
            Write-Host "              > Leer (keins geladen)" -ForegroundColor DarkGray
        } else {
            Write-Host "              > Load: $($gpuData.LoadPct)%" -ForegroundColor Yellow
        }
    }

    Write-Host ""
    Write-Host "Generiert mit GPU Monitor PowerShell Skript" -ForegroundColor Gray

    return @{ Gpu = $gpuData; Llm = $llmData }
}

function global:Watch-Gpu {
    <#
    .SYNOPSIS
        Fuerft Watchdog fuer GPU-Monitoring

    .DESCRIPTION
        Fuerft das Monitoring mit konfigurierbarem Intervall und Live-Ausgabe.

    .PARAMETER Interval
        Intervall in Sekunden zwischen den Abfragen (Standard: 30)

    .PARAMETER Duration
        Dauer des Monitoring in Minuten (-1 fuer unbegrenzt, Standard: -1)

    .EXAMPLE
        Watch-Gpu
        Fuerft Monitoring alle 30 Sekunden bis manuell gestoppt

    .EXAMPLE
        Watch-Gpu -Interval 5 -Duration 10
        Fuerft Monitoring alle 5 Sekunden fuer 10 Minuten
    #>

    param(
        [int]$Interval = 30,
        [int]$Duration = -1
    )

    $startTime = Get-Date
    $endTime = if ($Duration -lt 0) {
        $null
    } else {
        (Get-Date).AddMinutes($Duration)
    }

    Write-Host "GPU Monitoring gestartet." -ForegroundColor Green
    Write-Host "Intervall: $($Interval) Sekunden" -ForegroundColor Gray
    if ($Duration -ge 0) {
        Write-Host "Dauer: $($Duration) Minuten" -ForegroundColor Gray
    }
    Write-Host "Druecken Sie Ctrl+C zum Stoppen." -ForegroundColor Cyan
    Write-Host ""

    $iteration = 0

    while (1) {
        try {
            $now = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

            # Fuer Dauerbegrenzung: Wenn Ablaufzeit erreicht, brechen aus
            if ($endTime -and $now -ge $endTime) {
                Write-Host "" -NoNewline
                Write-Host "Monitoring-Ablaufzeit erfulled. Script wird gestoppt." -ForegroundColor Yellow
                break
            }

            # Ausfuehren des Status-Checks
            Get-GpuSummary > $null

        } catch {
            Write-Host "[Fehler] $_" -ForegroundColor Red
        }

        $iteration++

        if ($Duration -gt 0) {
            $remaining = ([int]$((($endTime - $now).TotalSeconds)))
            if ($remaining -le 0) {
                break
            }
            Write-Host "Verbleibende Zeit: $remaining Sekunden" -NoNewline -ForegroundColor Gray
        }

        Start-Sleep -Seconds $Interval
    }

    return @{ Iterations = $iteration; Duration = (Get-Date).AddMinutes($Duration -if ($Duration -lt 0) { [int]60} else { $Duration }) }
}

# ============================================================================
# Main Loop fuer Interaktive Befehlszeile (ohne Parameter)
# ============================================================================

if (-not $args) {
    Write-Host ""
    Write-Host "GPU Monitor - Optionen:" -ForegroundColor Cyan
    Write-Host "  Get-GpuSummary      - Einzelner Statusueberpruefung"
    Write-Host "  Watch-Gpu           - Laufendes Monitoring"
    Write-Host "  Get-GpuInfo         - Nur GPU-Daten abfragen"
    Write-Host "  Get-LlmInfo         - Nur LLM-Daten abfragen"
    Write-Host ""

    $choice = Read-Host "Bitte waehlen Sie eine Option (q=Exit):"

    switch ($choice.ToLower()) {
        "-h","--help","help","?" {
            Write-Host "Hilfe anzeigen" -ForegroundColor Cyan
            Get-GpuSummary
        }

        "w","watch" {
            Watch-Gpu
        }

        "s","single","status" {
            Get-GpuSummary
        }

        "g","gpu" {
            $data = Get-GpuInfo
            if ($data) {
                $data | Format-Table -AutoSize
            }
        }

        "l","llm" {
            $data = Get-LlmInfo
            if ($data) {
                $data | Format-Table -AutoSize
            }
        }

        "q","quit","exit" {
            Write-Host "Programm wurde beendet." -ForegroundColor Yellow
            break
        }

        Default {
            # Standard: Status ausgeben
            Get-GpuSummary
        }
    }
}
