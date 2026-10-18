# Gestão de Drivers

**Mainuan Gestão de Drivers** é uma ferramenta de hardware do projeto Mainuan,
baseado no Kubuntu 26.04 LTS. A versão **0.3 é beta**.

A interface oficial usa Qt6 Widgets/PyQt6. A detecção usa
`ubuntu-drivers-common` e consultas APT, com backend Python independente da GUI.
O planejamento de alterações usa PackageKit via `PyQt6.QtDBus`.
Nesta versão, alterações válidas podem ser aplicadas após confirmação explícita.
PackageKit e o agente PolicyKit do Plasma cuidam da autorização, sem senha
solicitada pelo aplicativo nem execução direta de APT/dpkg.

```bash
mainuan-gestao-drivers
mainuan-gestao-drivers test
```

Sem instalar no host, execute `./usr/bin/mainuan-gestao-drivers` no checkout.
O modo `test` usa os dispositivos fictícios do backend e **simula todas as
alterações em memória, sem comunicar transações ao PackageKit**.
O launcher Plasma é `org.mainuan.GestaoDrivers.desktop`.
No modo `test`, o seletor de cenários inclui NVIDIA, Secure Boot, DKMS, MOK,
headers e Broadcom. Esses cenários não consultam nem modificam o estado do host.

## Desenvolvimento

O código fica em `usr/lib/mainuan/mainuan-gestao-drivers/mainuan_drivers/`.
O entry point temporário `mainuan-gestao-drivers-gtk-legacy` mantém a GTK como
referência de desenvolvimento, sem launcher no menu nem fallback automático.
As dependências GTK e o helper Broadcom herdado permanecem apenas por ela;
a Qt não importa GTK, XApp, GLib, Gio ou PackageKitGlib.

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q usr tests
python3 tests/probe_packagekit_readonly.py
dpkg-buildpackage -us -uc -b
```

Instale o beta apenas em uma VM para validação:

```bash
sudo apt install ./mainuan-gestao-drivers_0.3_all.deb
sudo apt remove mainuan-gestao-drivers
```

Não há scripts para remover dependências, alterar repositórios, módulos ou
Secure Boot durante instalação/remoção do aplicativo.
Consulte [a arquitetura de transações](docs/qt-transactions.md) e o
[roteiro de validação na VM](docs/beta-0.3-testing.md).
Trocas com remoção e instalação não são atômicas; em caso de falha parcial,
o aplicativo detecta novamente o estado real, sem restaurar drivers automaticamente.
Autoremove e remoção indiscriminada de dependências não são permitidos.
O preflight verifica requisitos de módulo, kernel/headers, Secure Boot e MOK
somente para leitura. DKMS com Secure Boot ativo/desconhecido permanece bloqueado
quando a assinatura não pode ser garantida, mesmo com MOK inscrita. Módulos
pré-compilados compatíveis não recebem o bloqueio DKMS. A Qt não descarrega nem
carrega módulos Broadcom: orienta reiniciar. Pacote instalado não significa driver
ativo; o resultado é reavaliado após a transação. Consulte a
[auditoria upstream](docs/upstream-audit-0.3.md) e a
[política de acompanhamento](docs/upstream-sync-policy.md).

## Origem e Licença

Derivado originalmente de [Linux Mint mintdrivers](https://github.com/linuxmint/mintdrivers),
preservando o código e os créditos upstream, incluindo
**Copyright 2013-2014 Clement Lefebvre** e os demais contribuidores.
Licença: **GPL-2.0-or-later**. As modificações Mainuan usam a mesma licença.
O histórico anterior permanece no Git e em `debian/changelog`.

O contato de empacotamento usado é `Mainuan Packaging <openwebosbr@gmail.com>`,
já registrado no changelog das revisões Mainuan anteriores.
