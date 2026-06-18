@echo off
REM Legado: use Controle de Codigo para commit/push e sync-vm.bat para a VM.
REM A VM tambem atualiza sozinha a cada 2 min apos push (systemd timer).
echo.
echo  Commit e push: painel Controle de Codigo (Source Control) do Cursor.
echo  VM automatica: detecta push em ate 2 min (pli-hazardtrack-watch.timer).
echo  VM manual:     rode sync-vm.bat ou a task "Deploy: atualizar VM agora".
echo.
call "%~dp0sync-vm.bat"
