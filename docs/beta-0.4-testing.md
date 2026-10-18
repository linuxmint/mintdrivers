# Validacao manual do beta 0.4

## Preparacao

Use snapshot da VM. Nao instale drivers incompativeis para produzir um teste:
uma VM sem hardware elegivel pode legitimamente nao oferecer driver adicional.
O modo ficticio e o probe hello atendem a esses dois casos distintos.

```bash
ubuntu-drivers devices
dpkg-query -W ubuntu-drivers-common dkms shim-signed mokutil
sudo apt install ./mainuan-gestao-drivers_0.4_all.deb
mainuan-gestao-drivers 2>&1 | tee mainuan-0.4.log
```

Confira Qt/Wayland, titulo, deteccao sem traceback e estado vazio valido.
Sem hardware elegivel, nao force instalacao de NVIDIA/Broadcom.

## Cenarios ficticios

```bash
mainuan-gestao-drivers test
```

Todas as alteracoes sao simuladas. No seletor, confira os 22 cenarios:
os 14 anteriores mais MOK diferente, enrollment correspondente pendente,
assinatura desconhecida, driver ativo, reboot, MOK necessaria, ativacao nao
confirmada e driver antigo associado. Os cenarios de ativacao ja iniciam com
um pacote ficticio instalado; nao precisam aplicar para mostrar o estado.

- Secure Boot + DKMS + enrolled MOK: selecione recomendado; Aplicar habilitado
  se headers verificados. Confirmacao mostra assinatura configurada e MOK do
  certificado inscrita. Aplicar continua apenas simulacao nesse modo.
- MOK ausente, diferente ou desconhecida: Aplicar bloqueado, previa acessivel.
- Enrollment correspondente pendente: bloqueado com orientacao MokManager.
- Prebuilt compativel: nao recebe bloqueio DKMS.
- Headers ausentes: bloqueado mesmo com assinatura pronta.
- Ativo/reboot/MOK/unverified: textos concisos, sem confundir pacote com modulo.
- Redimensione, confira scroll, preview e fechamento normal.

## Leitura real e hardware elegivel

```bash
mokutil --sb-state
python3 tests/probe_packagekit_readonly.py
```

Em BIOS, mokutil pode retornar erro por EFI indisponivel: nao e falha do driver.
Nunca use --list-enrolled para concluir que a chave DKMS esta pronta. O programa
le configuracao estatica e testa especificamente o certificado publico escolhido.
Nao abra chaves privadas. Defaults de outras versoes DKMS/configuracoes dinamicas
precisam de auditoria; ausencia de prova mantem bloqueio.

Somente em hardware real compativel, com backup/snapshot e autorizacao manual,
selecione o driver oferecido pelo UDC, revise pacotes e preflight e confirme.
Observe PolicyKit/progresso. Depois compare `ubuntu-drivers devices`, estado dos
pacotes e `/sys/.../driver` (somente leitura). Novo binding nvidia/wl e evidencia
da familia, nao prova da versao ou variante open/closed. Se o mesmo modulo ficou
ligado durante troca, reinicie manualmente quando orientado e abra novamente.
Nenhum reboot, reload ou enrollment e automatizado pelo aplicativo.

Uma chave pendente continua exigindo fluxo externo apropriado: este beta nao
promete que PackageKit conduza enrollment. Nao gere/importe MOK para testar.

O probe hello permanece separado e nao instalado no deb:
consulte `tests/manual/README.md`. Nao o adapte para DKMS.

## Regressao e remocao do aplicativo

```bash
python3 -m compileall -q usr tests
python3 -m unittest discover -s tests -v
desktop-file-validate usr/share/applications/org.mainuan.GestaoDrivers.desktop
sudo apt remove mainuan-gestao-drivers
```

Nao ha scripts de remocao agressiva de dependencias. GTK ainda e referencia
temporaria por `mainuan-gestao-drivers-gtk-legacy`, sem launcher oficial.
