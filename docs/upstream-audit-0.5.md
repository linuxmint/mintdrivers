# Auditoria upstream e inventario antes do beta 0.5

2026-10-18. Branch `port/kubuntu-26.04`, base limpa
`e0ea935533a5b63409e237ed27f1f1b12ae4137c`. Beta 0.4 consolidado;
nenhum checkpoint adicional necessario. Baseline: 259 testes.

## Upstreams

Executados `git fetch upstream`, `git log --oneline master..upstream/master`,
`git diff --stat master..upstream/master`. Sem delta Mint; HEAD permanece
`5c8046c00daf1391260093de251a9fffa2e540d7`.
[Mint upstream](https://github.com/linuxmint/mintdrivers).
`git ls-remote https://github.com/canonical/ubuntu-drivers-common.git HEAD`:
`ffb948b95f7c85d5a92275a9aaa53b6d9e2e2453`, igual ao auditado no 0.4.
[Canonical upstream](https://github.com/canonical/ubuntu-drivers-common).
UDC local instalado/candidato `1:0.10.9`, Ubuntu resolute/main.

**Nenhuma mudanca funcional upstream** em UI, regras, NVIDIA, Broadcom,
Secure Boot/MOK, packaging, traducao ou bugfix a portar desde a auditoria 0.4.
Issues abertas consultadas pela API GitHub: #100, #103, #107 WIP, #109, #111,
#112, alem de #96/#99/#110. Mantidas decisoes do 0.4: sem copiar PR nao merged,
sem novos drivers/DisplayLink/EVDI/enrollment e sem alterar recomendacao UDC.
Nao houve merge. Esta fase remove apenas infraestrutura Mainuan obsoleta.

## Inventario antes de apagar

Pesquisa completa solicitada realizada antes de editar:
`rg -n 'Gtk|Gdk|GdkPixbuf|XApp|PackageKitGlib|GLib|Gio|python3-gi|gir1.2-xapp|gtk_legacy|gtk-legacy' .`.
Cada grupo de ocorrencias tem a classificacao abaixo; referencias repetidas dos
catalogos sao classificadas pelo mesmo caminho/proposito, nao como imports.

| Ocorrencias/caminhos | Classificacao | Destino |
| --- | --- | --- |
| gtk_legacy.py e symlink usr/bin/*gtk-legacy | CODIGO LEGADO | Remover |
| load-broadcom-modules, etc/sudoers.d/*gtk-legacy | CODIGO/DEPENDENCIA LEGADA privilegiada | Remover com migracao do conffile |
| gtk-legacy.ui, manpage GTK | RECURSO LEGADO | Remover |
| offline-symbolic.svg, referenciado somente pela UI GTK | RECURSO LEGADO | Remover |
| debian/control python3-gi, XApp/GIR PackageKit | DEPENDENCIA LEGADA | Remover |
| makepot referencias Python GTK/Glade | RECURSO LEGADO de build | Remover |
| backend.count_installed_proprietary_drivers | CODIGO LEGADO: unico consumidor GTK | Remover apenas esse metodo |
| README/manpage atual falando em frontend legado instalado | ERRO apos a limpeza | Atualizar para 0.5 |
| testes de presenca do launcher legado | TESTE de contrato antigo | Converter para ausencia, nao apagar teste |
| testes de imports proibidos | TESTE NEGATIVO | Preservar/expandir |
| docs/beta-0.[1-4]*, auditorias anteriores, changelog historico | DOCUMENTACAO HISTORICA | Preservar |
| po/*.po referencias extraidas GTK e strings herdadas | DOCUMENTACAO HISTORICA de traducao | msgmerge, preservar traducoes obsoletas |
| README origem, copyright, GPL, comentarios de origem | CREDITO UPSTREAM | Preservar |

Sete SVG semanticos sao usados pelo fallback Qt: amd, ati, broadcom, generic,
intel, nvidia, virtualbox. Preservar todos, alem dos dois icones da aplicacao.
make_test_device e get_installed_nvidia_dependency_ids continuam compartilhados
com fixtures/planner/testes: nao remover. psutil so aparece no changelog antigo;
nao existe import atual nem dependencia atual a remover.

## Empacotamento e conffile

Inspecionado o control archive do deb 0.4: `conffiles` registra exatamente
`/etc/sudoers.d/mainuan-gestao-drivers-gtk-legacy`.
Usar `debian/mainuan-gestao-drivers.maintscript` com rm_conffile e limite
`0.5~`. dh_installdeb gera hooks coordenados de upgrade, abort e purge.
Arquivo modificado pelo administrador vira .dpkg-bak (inativo para sudoers,
nome com ponto); nao apagar alteracoes locais com rm improvisado. Purge pelo
helper remove esse backup. Nao executar upgrade/purge no host Codex.
[dh_installdeb](https://manpages.debian.org/testing/debhelper/dh_installdeb.1.en.html),
[dpkg-maintscript-helper](https://manpages.debian.org/testing/dpkg/dpkg-maintscript-helper.1.en.html).

debhelper instalado/candidato `13.31ubuntu1`; seu Provides inclui
`debhelper-compat (= 13)` (apt-cache policy do virtual nao tem candidato proprio).
Migrar compat 9 para Build-Depends debhelper-compat (= 13), remover debian/compat.
Manter exclusoes de bytecode em dh_install: ainda necessarias para builds apos
compileall. debian/install passa a somente usr; nao instalar /etc vazio.
Declarar Rules-Requires-Root: no; build nao precisa modificar o host.

Dependencias restantes: Python, python3-pyqt6 (inclui QtDBus), python3-apt
(APT/apt_pkg usados diretamente pelo backend), ubuntu-drivers-common (deteccao)
e packagekit (servico). Recommends mokutil/openssl/kmod preservados para probes
read-only com degradacao segura. Nenhuma dependencia KF6/PyPI adicionada.
Auditoria concluida antes da remocao.
