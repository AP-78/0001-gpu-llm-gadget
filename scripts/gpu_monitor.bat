@echo off
REM ============================================================================
REM GPU Monitor Batch Script fuer Windows - Simple CLI Interface
REM Misst GPU und LLM-Daten und zeigt sie direkt im PowerShell-Terminal an
REM ============================================================================

REM Ermueglicht PowerShell 5.1+ ohne Prompt-Modus
powershell -ExecutionPolicy Bypass -File "%~dp0gpu_monitor.ps1" %*
