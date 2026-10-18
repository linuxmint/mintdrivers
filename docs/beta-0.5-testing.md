# Validacao do beta 0.5 na VM

Nao executar upgrade, purge ou mutacoes de driver no host de desenvolvimento.
Use snapshots independentes para instalacao limpa, upgrade normal e upgrade com
conffile modificado. Nao instale driver incompativel numa VM sem hardware elegivel.

## Instalacao limpa

Com o deb 0.5 no diretorio atual, registre o estado e instale somente o aplicativo:

```bash
ubuntu-drivers devices
sudo apt install ./mainuan-gestao-drivers_0.5_all.deb
command -v mainuan-gestao-drivers
command -v mainuan-gestao-drivers-gtk-legacy || true
dpkg -L mainuan-gestao-drivers
mainuan-gestao-drivers 2>&1 | tee mainuan-0.5-real.log
mainuan-gestao-drivers test 2>&1 | tee mainuan-0.5-test.log
```

Esperado: somente o frontend Qt, titulo/App ID preservados, loading e deteccao
terminam, ausencia de drivers adicionais e valida. Respeitar tema/fonte/Wayland.
O modo test mantem os 22 cenarios de 0.4; selecao, preview e Aplicar sao apenas
simulacao. Verifique READY/MOK diferente/pending, ativo/reboot/unverified,
scroll, redimensionamento e fechamento. Nenhuma alteracao real necessaria.
Outros aplicativos podem legitimamente manter GTK/GI instalados na VM: nao os
remova para provar a independencia deste cliente Qt.

## Upgrade obrigatorio 0.4 para 0.5

Em snapshot com beta 0.4 instalado (ou instale o deb 0.4 nessa VM):

```bash
sudo apt install ./mainuan-gestao-drivers_0.4_all.deb
dpkg -s mainuan-gestao-drivers
dpkg-query -W -f='${Conffiles}\n' mainuan-gestao-drivers
ls -l /etc/sudoers.d/
ls -l /etc/sudoers.d/mainuan-gestao-drivers-gtk-legacy
sudo apt install ./mainuan-gestao-drivers_0.5_all.deb
dpkg -s mainuan-gestao-drivers
test ! -e /etc/sudoers.d/mainuan-gestao-drivers-gtk-legacy
test ! -L /etc/sudoers.d/mainuan-gestao-drivers-gtk-legacy
test ! -e /usr/bin/mainuan-gestao-drivers-gtk-legacy
test ! -L /usr/bin/mainuan-gestao-drivers-gtk-legacy
test ! -e /usr/lib/mainuan/mainuan-gestao-drivers/gtk_legacy.py
test ! -e /usr/lib/mainuan/mainuan-gestao-drivers/load-broadcom-modules
test ! -e /usr/share/mainuan/mainuan-gestao-drivers/gtk-legacy.ui
test ! -e /usr/share/man/man1/mainuan-gestao-drivers-gtk-legacy.1.gz
command -v mainuan-gestao-drivers-gtk-legacy || true
dpkg -L mainuan-gestao-drivers
mainuan-gestao-drivers
```

Todos os `test !` devem retornar zero. O sudoers original nao modificado deve
desaparecer sem backup. O helper nao e chamado durante o upgrade.
Nao e necessario instalar, remover ou trocar qualquer driver.

### Conffile modificado pelo administrador

Em outro snapshot, com 0.4 instalado, use `sudoedit` no sudoers legado para
acrescentar **somente um comentario**, sem ampliar privilegios. Repita o upgrade.
O caminho ativo deve desaparecer, mas dpkg-maintscript-helper preserva a edicao
em `mainuan-gestao-drivers-gtk-legacy.dpkg-bak`. Nomes com ponto nao sao regras
ativas do includedir sudoers padrao. Confira essa politica na VM se ela tiver
configuracao sudo customizada. Nao remova a edicao do administrador a forca.
Um upgrade abortado deve poder restaurar o conffile pelo helper Debian.

## Purge

```bash
sudo apt purge mainuan-gestao-drivers
test ! -e /etc/sudoers.d/mainuan-gestao-drivers-gtk-legacy
test ! -e /etc/sudoers.d/mainuan-gestao-drivers-gtk-legacy.dpkg-bak
test ! -e /etc/sudoers.d/mainuan-gestao-drivers-gtk-legacy.dpkg-backup
test ! -e /etc/sudoers.d/mainuan-gestao-drivers-gtk-legacy.dpkg-remove
command -v mainuan-gestao-drivers || true
```

O helper Debian remove o backup do conffile no purge. Nao ha scripts para
remover dependencias, componentes KDE, dados arbitrarios do usuario ou drivers.
Nao execute autoremove para este teste. O estado de dependencias orfas pertence
a politica normal do APT, nao ao aplicativo.

## Regressao e inspecao sem instalar o pacote

```bash
python3 -m compileall -q usr tests
python3 -m unittest discover -s tests -v
python3 tests/probe_packagekit_readonly.py
dpkg-buildpackage -us -uc -b
python3 tests/inspect_deb.py ../mainuan-gestao-drivers_0.5_all.deb
dpkg-deb -I ../mainuan-gestao-drivers_0.5_all.deb
dpkg-deb -c ../mainuan-gestao-drivers_0.5_all.deb
lintian ../mainuan-gestao-drivers_0.5_all.deb
desktop-file-validate usr/share/applications/org.mainuan.GestaoDrivers.desktop
git diff --check
```

O gate de pacote falha com qualquer payload sudoers/GTK/helper, testes/probe,
bytecode, setuid/setgid, action PolicyKit propria ou migracao ausente.
Referencias historicas em copyright/docs e a referencia necessaria ao caminho
obsoleto nos scripts de controle nao sao arquivos GTK/sudoers instalados.

O probe hello permanece apenas em tests/manual, separado e nao instalado.
Seu teste de mutacao e manual, opcional e exclusivo da VM: veja
`tests/manual/README.md`. Nao adaptar para DKMS.
