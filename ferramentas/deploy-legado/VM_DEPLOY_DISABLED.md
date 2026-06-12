# ⚠️ Deploy para VM DESABILITADO

## Status
O deploy automático/manual para a VM AWS (56.125.163.194) foi **DESABILITADO**.

## Arquivos Desabilitados
Os seguintes arquivos foram renomeados com extensão `.disabled`:

### Configurações principais:
- `docker-compose.vm.yml` → `docker-compose.vm.yml.disabled`
- `.deploy/nginx-host/pli-hazardtrack` → `.deploy/nginx-host/pli-hazardtrack.disabled`

### Scripts de deploy:
- `.deploy/bootstrap_vm.sh` → `.deploy/bootstrap_vm.sh.disabled`
- `.deploy/deploy_vm.sh` → `.deploy/deploy_vm.sh.disabled`
- `.deploy/install_sigma_path.sh` → `.deploy/install_sigma_path.sh.disabled`
- `.deploy/setup_env_vm.sh` → `.deploy/setup_env_vm.sh.disabled`
- `.deploy/update_vm.sh` → `.deploy/update_vm.sh.disabled`
- `scripts/deploy-vm.bat` → `scripts/deploy-vm.bat.disabled`

## Motivo
Por solicitação, o sistema não deve mais enviar atualizações para a VM AWS. O repositório Git está configurado apenas para o GitHub.

## Configuração Git Atual
```bash
# Remotes configurados:
origin  https://github.com/vpcapanema/PLI-HazardTrack.git (fetch)
origin  https://github.com/vpcapanema/PLI-HazardTrack.git (push)

# NÃO há remotes apontando para a VM
```

## Se precisar reabilitar temporariamente:
1. Renomeie os arquivos `.disabled` removendo a extensão
2. Execute os scripts manualmente conforme necessário
3. Após o deploy, desabilite novamente renomeando para `.disabled`

## Containers na VM (após limpeza):
- ✅ Todos containers Sigma preservados
- ❌ Container `pli_hazardtrack_app` removido
- ❌ Container `sra-app` removido
- ❌ Container `sra-postgres` removido
- ✅ Repositórios Git do SRA removidos da VM