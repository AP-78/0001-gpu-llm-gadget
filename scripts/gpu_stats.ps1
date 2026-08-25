# ============================================================================
# GPU Stats PowerShell Skript
# Fuerht nvidia-smi und Ollama Abfragen und zeigt Daten im Terminal an
# Kann mit Python-Skript integriert werden
# ============================================================================

param(
    [string]$OutputFormat = "detailed",  # 'detailed', 'compact', 'json'
    [switch]$JsonOnly,
    [switch]$RawData,
    [int]$RefreshInterval = 30
)

function global:Export-GpuStats {
    <#
    .SYNOPSIS
        Fuerft GPU- und LLM-Daten und gibt sie im gewuenschten Format aus

    .PARAMETER OutputFormat
        Ausgabericht: 'detailed', 'compact', 'json'

    .EXAMPLE
        Export-GpuStats
        Fuerht detaillierte Ausgabe

    .EXAMPLE
        Export-GpuStats -JsonOnly
        Gibt nur JSON-Ausgabe
    #>

    $now = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

    if ($OutputFormat -eq 'json' -or $JsonOnly) {
        # JSON Format mit nvidia-smi und Ollama
        $gpuInfo = Get-GpuDataObject
        $llmInfo = Get-LlmDataObject

        $jsonOutput = @{
            timestamp = $now.ToUniversalTime()
            gpu = if ($gpuInfo) { [PSCustomObject]@{
                    name = $gpuInfo.name
                    load_pct = $gpuInfo.load
                    vram_used_mb = $gpuInfo.vram
                    vram_total_mb = $gpuInfo.vramtot
                    temp_c = $gpuInfo.temp
                    power_w = $gpuInfo.power
                    fan_pct = $gpuInfo.fan
                    clock_mhz = [float]$gpuInfo.clock
                } } else { @{} }

            llm = if ($llmInfo) { [PSCustomObject]@{
                    model_name = $llmInfo.model_name
                    vram_mb = $llmInfo.vram_mb
                    vram_pct = $llmInfo.vram_pct
                    total_vram_mb = $llmInfo.total_vram_mb
                    on_gpu = $llmInfo.on_gpu
                    ttl_seconds = if ($llmInfo.ttl) { [int]$llmInfo.ttl } else { $null }
                } } else { @{} }

            raw_gpu = if ($gpuInfo) { Get-NvidiaSmiRaw | Select-Object -First 1 } else { '' }
        }

        return $jsonOutput | ConvertTo-Json -Depth 10

    } elseif ($OutputFormat -eq 'compact') {
        # Compact Format fuer Dashboards
        $gpuInfo = Get-GpuDataObject
        $llmInfo = Get-LlmDataObject

        Write-Host ""
        Write-Host "GPU: $($gpuInfo.name -replace '[^a-zA-Z0-9_-]', '')" -ForegroundColor White -NoNewline
        Write-Host " | Load:" -NoNewline
        Write-Host $([math]::Round($gpuInfo.load, 1))% -ForegroundColor Green -NoNewline
        Write-Host " | VRAM:" -NoNewline
        Write-Host "$($gpuInfo.vram)M/$($gpuInfo.vramtot)M" -ForegroundColor White -NoNewline
        Write-Host " | Temp:" -NoNewline
        Write-Host $(if ($gpuInfo.temp -gt 85) { "<$([math]::Round($gpuInfo.temp,0)>">"} else { $([math]::Round($gpuInfo.temp,0)) })C" -ForegroundColor ($(if ($gpuInfo.temp -gt 75) { 'Red' } elseif ($gpuInfo.temp -lt 60) { 'Green' } else { 'White' })) -NoNewline
        if ($llmInfo -and $llmInfo.on_gpu) {
            Write-Host " | LLM: $($llmInfo.model_name)" -ForegroundColor Cyan
        }

    } else {
        # Detailed Format (Standard)
        Write-Host ""
        Write-Host "==============================================================" -ForegroundColor Cyan
        Write-Host "       GPU STATUS -$now                             " -ForegroundColor Cyan
        Write-Host "==============================================================" -ForegroundColor Cyan
        Write-Host ""

        $gpuInfo = Get-GpuDataObject

        if ($gpuInfo) {
            Write-Host "  Name:    $($gpuInfo.name)" -ForegroundColor White
            Write-Host "  Load:    $(if ($gpuInfo.load -gt 0) { [math]::Round($gpuInfo.load, 1)} else { 0 })% GPU Utilisation" -ForegroundColor White
            Write-Host "  VRAM:    $([math]::Round($gpuInfo.vram,2))MB / $([math]::Round($gpuInfo.vramtot,2))MB" -ForegroundColor White

            $vramUsage = if ($gpuInfo.vramtot -gt 0) { ([math]::Round(($gpuInfo.vram / $gpuInfo.vramtot) * 100, 1)) } else { 0 }
            Write-Host "  VRAM%:   $vramUsage%" -ForegroundColor $(if ($vramUsage -gt 90) { 'Red' } elseif ($vramUsage -gt 80) { 'Yellow' } else { 'Green' })

            Write-Host "  Temp:    $(if ($gpuInfo.temp -gt 85) { "<$([math]::Round($gpuInfo.temp,0)>">"} else { $([math]::Round($gpuInfo.temp,0)) })°C" -ForegroundColor $(if ($gpuInfo.temp -gt 85) { 'Red' } elseif ($gpuInfo.temp -lt 60) { 'Green' } else { 'White' })

            if ($gpuInfo.temp -lt 60) {
                Write-Host "           Kühlungsstatus: OPTIMAL (Unter 60°C)" -ForegroundColor Green
            } elseif ($gpuInfo.temp -le 75) {
                Write-Host "           Kühlungsstatus: NORMAL (Normaler Betrieb)" -ForegroundColor Yellow
            } elseif ($gpuInfo.temp -lt 85) {
                Write-Host "           Kühlungsstatus: WARME (Achten Sie darauf!)" -ForegroundColor Red
            } else {
                Write-Host "           Kühlungsstatus: KRITISCH (Kühlung überprüfen!)" -ForegroundColor DarkRed
            }

            Write-Host "  Power:   $(if ($gpuInfo.power -gt 0) { [math]::Round($gpuInfo.power,1)} else { 0 })W" -ForegroundColor White
            Write-Host "  Fan:     $([math]::Round($gpuInfo.fan,1))%" -ForegroundColor White
            Write-Host "  Clock:   $(if ($gpuInfo.clock -gt 0) { [math]::Round($gpuInfo.clock,1)} else { 0 })MHz" -ForegroundColor White

        } else {
            Write-Host "  Name:    NICHT ERKENNBAR (Keine GPU verbunden?)" -ForegroundColor DarkRed
            Write-Host "           Falsch installiert?" -ForegroundColor Yellow
        }

        # LLM Status
        Write-Host ""
        Write-Host "--------------------------------------------------------------" -ForegroundColor Cyan

        $llmInfo = Get-LlmDataObject

        if ($llmInfo) {
            if ($llmInfo.on_gpu) {
                Write-Host "  STATUS: Im VRAM (GPU)" -ForegroundColor Green
                Write-Host "  Modell:  $($llmInfo.model_name)" -ForegroundColor White
                Write-Host "  VRAM:    $([math]::Round($llmInfo.vram_mb,2))MB / $([math]::Round($llmInfo.total_vram_mb,2))MB" -ForegroundColor White
                Write-Host "           ($($llmInfo.vram_pct)%)" -ForegroundColor $(if ($llmInfo.vram_pct -gt 80) { 'Yellow' } else { 'White' })

                if ($llmInfo.ttl) {
                    $ttlMin = [int]($llmInfo.ttl / 60)
                    Write-Host "  TTL:     ca. $ttlMin Min bis Entladen" -ForegroundColor Cyan
                } elseif (-not $llmInfo.ttl) {
                    Write-Host "  TTL:     Keine Entlade-TTL (dauerhaft geladen)" -ForegroundColor Yellow
                }
            } else {
                Write-Host "  STATUS: Im VRAM (CPU/GPU-Shared)" -ForegroundColor Cyan
                Write-Host "  Modell:  $($llmInfo.model_name)" -ForegroundColor White
                Write-Host "  VRAM:    $([math]::Round($llmInfo.vram_mb,2))MB" -ForegroundColor White
                Write-Host "           ($($llmInfo.vram_pct)%)" -ForegroundColor White
            }

        } else {
            Write-Host "  STATUS: KEIN LLM geladen" -ForegroundColor DarkGray
        }

        Write-Host "--------------------------------------------------------------" -ForegroundColor Gray

        # Zusammenfassung
        Write-Host ""
        Write-Host "==============================================================" -ForegroundColor Cyan
        Write-Host "                        ZUSAMMENFASSUNG                         " -ForegroundColor Cyan
        Write-Host "==============================================================" -ForegroundColor Cyan

        $summaryLines = @()

        if ($gpuInfo) {
            $summaryLines += "GPU: $($gpuInfo.name)"
            $summaryLines += "     Load: $([math]::Round($gpuInfo.load,1))%, Temp: $(if ($gpuInfo.temp -gt 85) { "<$([math]::Round($gpuInfo.temp,0)>">"} else { $([math]::Round($gpuInfo.temp,0)) })°C"
            if ($llmInfo -and $llmInfo.on_gpu) {
                $summaryLines += "     LLM: $($llmInfo.model_name) - VRAM: $(if ($llmInfo.vram_pct -gt 80) { ">$(if ($llmInfo.vram_mb,2))MB" } else { $([math]::Round($llmInfo.vram_mb,2)))MB"
            }
        }

        $summaryLines | ForEach-Object { Write-Host " $_" -ForegroundColor White }

        Write-Host ""
    }

    if (-not $RawData) {
        return @{ Timestamp = $now; Gpu = $gpuInfo; Llm = $llmInfo }
    }
}

function global:Get-GpuDataObject {
    <#
    .SYNOPSIS
        Fuerft GPU-Daten mit nvidia-smi und gibt ein Objekt aus

    .OUTPUTS
        PSCustomObject mit GPU-Daten oder $null wenn keine GPU erkannt
    #>

    try {
        $nvidiaCmd = Get-Command nvidia-smi -ErrorAction Stop

        # nvidia-smi Output in einem Temp-File, da Start-Process mit -RedirectStandardOutput Probleme auf Windows haben kann
        $tempFile = Join-Path $TempPath "gpu_data.txt"

        # Verhindert Anzeige des Fensters bei Windows
        $processInfo = Start-Process `
            $nvidiaCmd.Path `
            -ArgumentList "--id=0", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,fan.speed,clocks.gr80", "--format=csv,noheader,nounits" `
            -RedirectStandardOutput $tempFile `
            -PassThru

        if ($processInfo.ExitCode -ne 0) {
            $content = Get-Content -Path $tempFile -Raw -ErrorAction SilentlyContinue
            Remove-Item -Path $tempFile -Force
            Write-Host "[Fehler] nvidia-smi Fehlercode: $($processInfo.ExitCode), Output: $content" -ForegroundColor Red
            return $null
        }

        $rawOutput = Get-Content -Path $tempFile -Raw
        Remove-Item -Path $tempFile -Force

        # Falls keine Daten
        if ([string]::IsNullOrWhiteSpace($rawOutput.Trim())) {
            Write-Host "[WARN] nvidia-smi Output leer" -ForegroundColor Yellow
            return $null
        }

        # CSV parsen (nvidia-smi liefert: name,util,memory.used,memory.total,temp,power,fan,clock)
        $lines = $rawOutput.Trim().Split([Environment]::NewLine)
        if (-not $lines[0]) { return $null }

        # Ersten GPU-Wert auslesen
        $line = $lines[0].Trim()

        # CSV Felder extrahieren (nvidia-smi: "Name,Value,Value,Value,Value,Value,Value,Value")
        $parts = $line.Split(',')

        [PSCustomObject]@{
            name    = if ($parts[0]) { $parts[0] } else { '' }
            load    = if ($parts.Count -gt 1 -and [string]::IsNullOrWhiteSpace($parts[1])) { 0 } else { [int]$parts[1] }
            vram    = if ($parts.Count -gt 2 -and [string]::IsNullOrWhiteSpace($parts[2])) { 0 } else { [int]$parts[2] }
            vramtot = if ($parts.Count -gt 3 -and [string]::IsNullOrWhiteSpace($parts[3])) { 0 } else { [int]$parts[3] }
            temp    = if ($parts.Count -gt 4 -and [string]::IsNullOrWhiteSpace($parts[4])) { 0 } else { [float]$parts[4] }
            power   = if ($parts.Count -gt 5 -and [string]::IsNullOrWhiteSpace($parts[5])) { 0 } else { [int]$parts[5] }
            fan     = if ($parts.Count -gt 6 -and [string]::IsNullOrWhiteSpace($parts[6])) { 0 } else { [float]$parts[6] }
            clock   = if ($parts.Count -gt 7 -and [string]::IsNullOrWhiteSpace($parts[7])) { 0 } else { [float]$parts[7] }
        }

    } catch {
        Write-Host "[Fehler] ${$_}" -ForegroundColor Red
        return $null
    }
}

function global:Get-LlmDataObject {
    <#
    .SYNOPSIS
        Fuerft LLM-Daten von Ollama API /api/ps

    .OUTPUTS
        PSCustomObject mit LLM-Daten oder $null wenn keine Modelle geladen
    #>

    try {
        $ollamaUrl = "http://localhost:11434/api/ps"

        $response = Invoke-RestMethod -Uri $ollamaUrl -Method Get -TimeoutSec 5 -ErrorAction Stop

        if (-not $response.models -or $response.models.Count -eq 0) {
            Write-Host "[INFO] Kein LLM geladen" -ForegroundColor Cyan
            return $null
        }

        # Groesstes Modell (meist aktives LLM) nach VRAM auswaehlen
        $activeModel = ($response.models | Where-Object { $_.size_vram -gt 0 })[0]

        if (-not $activeModel) {
            # Falls kein Modell mit size_vram, nimm groesstes nach size
            $activeModel = ($response.models | Sort-Object { [float]$_.size } -Descending)[0]
        }

        [PSCustomObject]@{
            model_name  = $activeModel.name -replace '[^\w\-]', '_'
            vram_mb     = if ([string]::IsNullOrWhiteSpace($activeModel.size_vram)) { 0 } else { [float]$activeModel.size_vram }
            total_vram_mb = if ([string]::IsNullOrWhiteSpace($activeModel.size)) { 0 } else { [float]$activeModel.size }
            vram_pct    = if ($activeModel.total -gt 0) { [math]::Round((($activeModel.size_vram / $activeModel.total) * 100), 2) } else { 0 }
            on_gpu      = $true

            # TTL berechnen wenn vorhanden
            ttl_seconds = if ($activeModel.expires_at) {
                try {
                    $expiresStr = $activeModel.expires_at.Trim()

                    # Nanosekunden entfernen (falls vorhanden)
                    if ($expiresStr -match '\.') {
                        $idx = $expiresStr.IndexOf('.')
                        $tzStart = $idx + 1

                        # Zeitzone-Offset finden
                        for ($i = $tzStart; $i -lt $expiresStr.Length; $i++) {
                            if ($expiresStr.Substring($i, 1) -match '^\+|\-|Z$') {
                                break
                            }
                        }

                        # Nur bis zum Offset-Suffix nehmen
                        if ($idx -gt 0) {
                            $expiresStr = $expiresStr.Substring(0, $idx) + substr($expiresStr, $tzStart, 1)
                        }

                        # 'Z' zu '+00:00' umwandeln
                        $expiresStr = $expiresStr.Replace('Z', '+00:00')

                        # DateTimeOffset parsen
                        $offset = [DateTimeOffset]::Parse($expiresStr, [System.Globalization.CultureInfo]::InvariantCulture)

                        # UTC Zeit
                        $nowUTC = [DateTimeOffset]::UtcNow

                        if ($offset.Utc -ge $nowUTC) {
                            ([math]::Round(($offset.Utc - $nowUTC).TotalSeconds))
                        } else {
                            $null  # Bereits ueberfellig entladen
                        }
                    } else {
                        $null
                    }
                } catch {
                    Write-Host "[WARN] TTL Parse: $_" -ForegroundColor Yellow
                    $null
                }
            } else {
                $null
            }

        } else {
            [PSCustomObject]@{
                model_name = ""
                vram_mb = 0
                total_vram_mb = 0
                vram_pct = 0
                on_gpu = $false
                ttl_seconds = $null
            }
        }

    } catch {
        if ($_.Exception -and $_.Exception.Message -like "*refused to connect*" -or $_.Exception.Message -like "*connection refused*") {
            Write-Host "[INFO] Ollama nicht erreichbar (normal, falls nicht genutzt)" -ForegroundColor Yellow
        } else {
            Write-Host "[Fehler] LLM Abfrage: $_" -ForegroundColor Red
        }
        return $null
    }
}

# ============================================================================
# Main Loop (wenn Script ohne Parameter aufgerufen wird)
# ============================================================================

if (-not $args) {

    # Wenn keine spezifischen Optionen, dann kontinuierliches Monitoring fuer 5 Min oder bis Ctrl+C
    Write-Host ""
    Write-Host "GPU Monitor - Live-Modus" -ForegroundColor Cyan
    Write-Host "(Druecken Sie Ctrl+C um zu stoppen)" -ForegroundColor Gray
    Write-Host ""

    $startTime = Get-Date
    $endTime = (Get-Date).AddMinutes(5)  # Default 5 Minuten

    while (($now = Get-Date) -lt $endTime) {
        try {
            # Fuer jeden Zyklus: Status ausgeben
            $result = Export-GpuStats -OutputFormat detailed

            Write-Host "`n[$($now.ToLocalTime())] Neu abgefragt" -ForegroundColor DarkGray

        } catch {
            Write-Host "[Fehler] $_" -ForegroundColor Red
        }

        # Intervall
        Start-Sleep -Seconds $RefreshInterval
    }
}
