# Gestão de Drivers

**Mainuan Gestão de Drivers** é uma ferramenta de hardware do projeto Mainuan,
baseado no Kubuntu 26.04 LTS. A versão **0.6 é beta**, ainda não Release Candidate.

A aplicação é integralmente Qt6 Widgets/PyQt6, sem frontend GTK ou XApp. A detecção usa
`ubuntu-drivers-common` e consultas APT, com backend Python independente da GUI.
O planejamento de alterações usa PackageKit via `PyQt6.QtDBus`.
Nesta versão, alterações válidas podem ser aplicadas após confirmação explícita.
PackageKit e o agente PolicyKit do Plasma cuidam da autorização, sem senha
solicitada pelo aplicativo nem execução direta de APT/dpkg.

```bash
mainuan-gestao-drivers
mainuan-gestao-drivers test
mainuan-gestao-drivers --debug
mainuan-gestao-drivers --version
```

Sem instalar no host, execute `./usr/bin/mainuan-gestao-drivers` no checkout.
O modo `test` usa os dispositivos fictícios do backend e **simula todas as
alterações em memória, sem comunicar transações ao PackageKit**.
O launcher Plasma é `org.mainuan.GestaoDrivers.desktop`.
No modo `test`, o seletor de cenários inclui NVIDIA, Secure Boot, DKMS, MOK,
headers e Broadcom. Esses cenários não consultam nem modificam o estado do host.
Também há cenários de terceiros, Live Session, falha do backend, PackageKit
indisponível e nenhum driver adicional. A origem não substitui a recomendação
UDC nem o candidate/pinning APT. Não há gerenciamento próprio de Mesa ou PPAs.
Na Live Session, detecção e prévia funcionam, mas alterações são bloqueadas;
sessão desconhecida também é conservadoramente bloqueada.
No menu Ajuda, os diagnósticos podem ser copiados explicitamente para a área de
transferência. Não há upload automático, senhas, chaves privadas ou identificação
pessoal nesse relatório. Sobre identifica versão e créditos.

## Desenvolvimento

O código fica em `usr/lib/mainuan/mainuan-gestao-drivers/mainuan_drivers/`.
O frontend GTK, seu helper Broadcom e o sudoers legado foram removidos no beta
0.5. Não há fallback GTK, action PolicyKit própria nem helper privilegiado.
A autorização pertence ao PackageKit e ao agente PolicyKit da sessão.

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q usr tests
python3 tests/probe_packagekit_readonly.py
dpkg-buildpackage -us -uc -b
```

Instale o beta apenas em uma VM para validação:

```bash
sudo apt install ./mainuan-gestao-drivers_0.6_all.deb
sudo apt remove mainuan-gestao-drivers
```

Não há scripts para remover dependências, alterar repositórios, módulos ou
Secure Boot durante instalação/remoção do aplicativo.
Consulte [a arquitetura de transações](docs/qt-transactions.md) e o
[roteiro de validação e upgrades 0.4/0.5 para 0.6 na VM](docs/beta-0.6-testing.md).
O upgrade retira o conffile sudoers obsoleto pelo mecanismo Debian apropriado;
modificações locais são preservadas como backup inativo até o purge.
Trocas com remoção e instalação não são atômicas; em caso de falha parcial,
o aplicativo detecta novamente o estado real, sem restaurar drivers automaticamente.
Autoremove e remoção indiscriminada de dependências não são permitidos.
O preflight verifica requisitos de módulo, kernel/headers, Secure Boot e MOK
somente para leitura. DKMS com Secure Boot ativo pode prosseguir quando o
certificado realmente usado pelo DKMS é identificado e sua inscrição MOK é
confirmada. Uma MOK diferente não basta. Estado desconhecido ou inscrição
pendente continuam bloqueados; não há geração de chave nem enrollment próprio. Módulos
pré-compilados compatíveis não recebem o bloqueio DKMS. A Qt não descarrega nem
carrega módulos Broadcom: orienta reiniciar. Pacote instalado não significa driver
ativo; o resultado é reavaliado após a transação. Consulte a
[auditoria upstream](docs/upstream-audit-0.6.md) e a
[política de acompanhamento](docs/upstream-sync-policy.md).

## Origem e Licença

Derivado originalmente de [Linux Mint mintdrivers](https://github.com/linuxmint/mintdrivers),
preservando o código e os créditos upstream, incluindo
**Copyright 2013-2014 Clement Lefebvre** e os demais contribuidores.
Licença: **GPL-2.0-or-later**. As modificações Mainuan usam a mesma licença.
O histórico anterior permanece no Git e em `debian/changelog`.

O contato de empacotamento usado é `Mainuan Packaging <openwebosbr@gmail.com>`,
já registrado no changelog das revisões Mainuan anteriores.
