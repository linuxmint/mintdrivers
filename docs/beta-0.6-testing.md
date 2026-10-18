# Testes do beta 0.6 na VM

Use snapshots independentes para instalacao limpa, upgrade de 0.4, upgrade de
0.5 e purge. Nao execute estes procedimentos no host de desenvolvimento.
Nao e necessario instalar um driver incompativel se a VM nao oferece hardware
com driver adicional. Lista vazia e um resultado normal e esperado.

## Instalacao limpa

No diretorio que contem o pacote:

```bash
sudo apt install ./mainuan-gestao-drivers_0.6_all.deb
mainuan-gestao-drivers --version
command -v mainuan-gestao-drivers
command -v mainuan-gestao-drivers-gtk-legacy || true
dpkg -L mainuan-gestao-drivers
dpkg-query -W -f='${Depends}\n${Recommends}\n${Suggests}\n' mainuan-gestao-drivers
mainuan-gestao-drivers
```

Esperado: versao 0.6, somente Qt, loading antes do resultado; sem hardware
elegivel, mensagem de que nenhum driver adicional e necessario. Nao deve haver
GTK, XApp, PackageKitGlib, helper Broadcom, action Polkit propria nem payload
em /etc/sudoers.d. Dependencias transitivas de outros componentes do sistema
nao sao responsabilidade deste pacote.

No menu Ajuda, verificar Sobre (Mainuan, 0.6, origem Mint e GPL) e Copiar
informacoes de diagnostico. Colar localmente para inspecionar; nada e enviado
automaticamente. O diagnostico omite usuario, hostname, sysfs path e chaves.

```bash
mainuan-gestao-drivers --debug 2>&1 | tee mainuan-drivers-debug.log
mainuan-gestao-drivers test
```

O debug aumenta somente o logging. O modo test permanece nao destrutivo.
Percorrer os 28 cenarios, incluindo terceiros recomendado/DKMS, Live, PackageKit
indisponivel, erro de backend e nenhum driver; os 22 cenarios anteriores continuam.
Conferir recomendado, instalado e ativo como informacoes distintas. Selecionar
uma alternativa e abrir previa; terceiros deve aparecer tambem na confirmacao.
No modo ficticio, Aplicar executa somente a simulacao existente.

## APT e repositorios adicionais: somente leitura

Nao adicionar/remover PPA, alterar sources, executar upgrade nem forcar drivers.

```bash
ubuntu-drivers devices
dpkg-query -W ubuntu-drivers-common
```

Somente se a consulta acima listar um pacote NVIDIA, consultar aquele nome exato:

```bash
apt-cache policy NOME_DO_PACOTE_NVIDIA_REALMENTE_DETECTADO
```

Comparar Candidate e prioridades/origens com a versao candidata e metadados do
tooltip/diagnostico do aplicativo. Se o pacote ja estiver instalado, a versao
instalada pode diferir da candidata. O aplicativo nao escolhe a maior versao:
candidate/pinning sao do APT, recommended e do UDC. Um recomendado third-party
continua recomendado. Fonte nao determina DKMS: preflight analisa dependencias
reais, kernel e assinatura. Com Secure Boot, confianca APT nao prova confianca
da assinatura do modulo. Mesa nao possui gerenciamento separado neste beta.

## Live Session

Inicializar uma ISO Mainuan/Kubuntu 26.04 em uma VM separada. Disponibilizar o
aplicativo na imagem de teste conforme o fluxo de desenvolvimento da distribuicao;
nao montar nem alterar uma instalacao alvo a partir da Live.

Verificar somente leitura:

```bash
cat /proc/cmdline
findmnt -n -o FSTYPE,OPTIONS /
mainuan-gestao-drivers
```

Deteccao e visualizacao funcionam. Aplicar deve ficar desabilitado com explicacao
para instalar o Mainuan. Se houver opcoes, previa permanece disponivel; nenhum
InstallPackages/RemovePackages pode ser chamado. UNKNOWN tambem bloqueia mutacao.
O probe usa boot=casper/boot=live ou raiz overlay com /cow, nao usuario/hostname.
`mainuan-gestao-drivers test` permite simulacoes, nunca altera o host; o cenario
ficticio Live reproduz o bloqueio visual.

## Teclado, escala e erros

Testar Tab/Shift+Tab para navegacao, Space para selecionar, Enter para ativar o
controle focado e Esc para fechar dialogos. Na confirmacao, Cancelar e o default.
Confirmar nomes acessiveis com o leitor de tela disponivel no Plasma; os testes
automatizados verificam propriedades Qt, nao substituem teste com leitor real.
Reduzir a janela; mensagens e dispositivos devem rolar, comandos ficam visiveis.
Verificar textos longos, tema claro/escuro e escala Plasma 100/125/150/200%.
Nao forcar X11; Qt escolhe Wayland na sessao correspondente.

Na arvore fonte e apenas para teste visual read-only:

```bash
QT_SCALE_FACTOR=1 python3 tests/manual/qt_ux_probe.py --output /tmp/mainuan-qt-100
QT_SCALE_FACTOR=1.25 python3 tests/manual/qt_ux_probe.py --compact --output /tmp/mainuan-qt-125
QT_SCALE_FACTOR=1.5 python3 tests/manual/qt_ux_probe.py --compact --output /tmp/mainuan-qt-150
QT_SCALE_FACTOR=2 python3 tests/manual/qt_ux_probe.py --compact --output /tmp/mainuan-qt-200
python3 tests/probe_packagekit_readonly.py
```

Esse probe visual proibe metodos D-Bus modificadores. Nao e instalado no .deb.
Os cenarios PackageKit indisponivel e erro de backend nao exigem parar servicos
reais. Erro oferece Tentar novamente, nao traceback. Lista vazia nao e erro.
Nao existe teste proprio de Internet; falha explicita NO_NETWORK do PackageKit
gera estado offline, falha de download ou arquivo ausente nao prova offline.
Deteccao local pode funcionar sem rede. O probe manual hello continua separado
e nao e chamado por estes testes; seu roteiro esta na documentacao do beta 0.2.

## Upgrade direto 0.4 para 0.6

Em snapshot com 0.4 instalado, registrar antes:

```bash
dpkg -s mainuan-gestao-drivers
dpkg-query -W -f='${Conffiles}\n' mainuan-gestao-drivers
ls -l /etc/sudoers.d/
sudo apt install ./mainuan-gestao-drivers_0.6_all.deb
```

Verificar:

```bash
mainuan-gestao-drivers --version
test ! -e /etc/sudoers.d/mainuan-gestao-drivers-gtk-legacy
test ! -L /etc/sudoers.d/mainuan-gestao-drivers-gtk-legacy
test ! -e /usr/bin/mainuan-gestao-drivers-gtk-legacy
test ! -e /usr/lib/mainuan/mainuan-gestao-drivers/gtk_legacy.py
test ! -e /usr/lib/mainuan/mainuan-gestao-drivers/load-broadcom-modules
test ! -e /usr/share/mainuan/mainuan-gestao-drivers/gtk-legacy.ui
test ! -e /usr/share/man/man1/mainuan-gestao-drivers-gtk-legacy.1.gz
dpkg -L mainuan-gestao-drivers
mainuan-gestao-drivers
```

O rm_conffile preservado usa limite 0.5~ comparado com a versao ANTIGA;
portanto cobre 0.4 -> 0.6. Se o administrador modificou o conffile, o mecanismo
Debian pode preservar backup .dpkg-bak (nao ativo no sudo). Nao editar arquivos
privilegiados para simular isso no host. Testar esse caso apenas em snapshot VM.

## Upgrade 0.5 para 0.6

Repetir em snapshot separado com 0.5 instalado. Registrar dpkg -s e Conffiles;
instalar o mesmo 0.6 e repetir todas as verificacoes de ausencia acima. O 0.5
ja deveria ter migrado o sudoers; 0.6 nao o reinstala nem cria outro frontend.
Nao remover GTK, KDE ou dependencias do sistema manualmente para este teste.

## Purge

Em cada snapshot de upgrade e na instalacao limpa:

```bash
sudo apt purge mainuan-gestao-drivers
test ! -e /usr/bin/mainuan-gestao-drivers
test ! -e /usr/share/applications/org.mainuan.GestaoDrivers.desktop
test ! -e /etc/sudoers.d/mainuan-gestao-drivers-gtk-legacy
test ! -L /etc/sudoers.d/mainuan-gestao-drivers-gtk-legacy
test ! -e /etc/sudoers.d/mainuan-gestao-drivers-gtk-legacy.dpkg-bak
test ! -e /etc/sudoers.d/mainuan-gestao-drivers-gtk-legacy.dpkg-remove
test ! -e /usr/lib/mainuan/mainuan-gestao-drivers/mainuan_drivers/qt/application.py
```

Nao executar autoremove para validar o purge. O pacote nao remove explicitamente
PackageKit, PyQt6, UDC, KDE nem preferencias pessoais. Backups/conffiles obsoletos
sao tratados pelos hooks Debian; confirmar seu comportamento na VM antes de RC.
Se um comando falhar, guardar o estado dpkg, versao de origem e logs sem executar
limpeza privilegiada improvisada.
