@echo off
setlocal
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0FORMIQ_Backup_Windows.ps1"
if errorlevel 1 (
  echo BACKUP OR RESTORE NOT CONFIRMED.
) else (
  echo Completed selected local operation.
)
pause
