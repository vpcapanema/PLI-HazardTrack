@echo off
REM Commit no Controle de Codigo; sync-vm.bat faz push + deploy na VM.
REM A VM tambem atualiza sozinha a cada 2 min apos push (systemd timer).
echo.
echo  1. Controle de Codigo: Commit das alteracoes
echo  2. Task Deploy ou sync-vm.bat: push + atualiza VM ^(origin/main^)
echo  3. VM automatica: detecta push em ate 2 min ^(pli-hazardtrack-watch.timer^)
echo.
call "%~dp0sync-vm.bat"
