@echo off
plink -ssh -batch -i "D:\REPOSITORIOS\PLI-HazardTrack\SRV-SISTEMA-30001480.ppk" [email protected] "echo OK; uname -a; whoami"
