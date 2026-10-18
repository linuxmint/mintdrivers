# Relatorio do beta 0.5

## Base e auditoria

1. Branch: `port/kubuntu-26.04`.
2. Commit-base real: `e0ea935533a5b63409e237ed27f1f1b12ae4137c`, beta 0.4
   consolidado. Arvore inicialmente limpa, diff --check limpo; nenhum checkpoint
   adicional necessario. Sem push, merge, tag, release ou commit do 0.5.
3. Versao: **0.5**, Source/Package mainuan-gestao-drivers, Architecture all.
   Changelog novo em UNRELEASED, pois o beta local ainda esta em revisao. A data
   historica do 0.4 (16:00 de 18/10) era posterior ao horario desta preparacao;
   nao foi reescrita, nem foi inventado horario futuro para silenciar Lintian.
   A entrada nova usa data real. Historico inteiro preservado.
4. Deb: `/home/daigo/Github/mainuan-gestao-drivers_0.5_all.deb`, 162066 bytes,
   contra 165396 bytes do 0.4. SHA256:
   `27fa0a45c095ae70ebb63940fe3913799d385dbde0ddd4e0e32331c3c6f71135`.
5. Mint apos fetch: `5c8046c00daf1391260093de251a9fffa2e540d7`.
6. Canonical UDC remoto: `ffb948b95f7c85d5a92275a9aaa53b6d9e2e2453`.
   UDC local instalado/candidato `1:0.10.9`. Nenhuma mudanca funcional upstream
   desde o 0.4; nenhuma alteracao de politica NVIDIA foi necessaria. Issues
   abertas rechecadas e classificadas; DisplayLink/EVDI/enrollment fora do escopo.
   [Auditoria e inventario antes da remocao](upstream-audit-0.5.md).

## Legado removido e upgrade

7. Codigo GTK removido: `usr/lib/mainuan/mainuan-gestao-drivers/gtk_legacy.py`.
8. Executavel/symlink removido: `usr/bin/mainuan-gestao-drivers-gtk-legacy`.
9. UI removida: `usr/share/mainuan/mainuan-gestao-drivers/gtk-legacy.ui`.
10. Manpage removida: `usr/share/man/man1/mainuan-gestao-drivers-gtk-legacy.1`.
11. Helper removido: `usr/lib/mainuan/mainuan-gestao-drivers/load-broadcom-modules`.
    Nenhum substituto, modprobe ou reload automatico introduzido.
12. Sudoers removido da fonte/payload:
    `/etc/sudoers.d/mainuan-gestao-drivers-gtk-legacy`.
13. O control archive do deb **0.4 foi inspecionado**: esse caminho estava
    registrado como conffile. Apenas retirar o payload nao bastaria.
14. Novo `debian/mainuan-gestao-drivers.maintscript`:

    ```text
    rm_conffile /etc/sudoers.d/mainuan-gestao-drivers-gtk-legacy 0.5~ mainuan-gestao-drivers
    ```

    dh_installdeb gera preinst/postinst/prerm/postrm coordenados. Os quatro
    hooks do deb foram inspecionados: contem apenas set -e e a chamada padrao
    dpkg-maintscript-helper com argumentos encaminhados. Nenhum rm improvisado.
    Limite 0.5~ cobre 0.4 e revisoes locais anteriores. Sem edicao local, o
    conffile desaparece; modificado, vira .dpkg-bak inativo no sudoers padrao.
    Abort-upgrade restaura o arquivo, purge remove o backup pelo helper Debian.
    Nao executar esses hooks manualmente no host. Upgrade real reservado a VM.

## Dependencias e build Debian

15. Removidas de Depends: python3-gi, gir1.2-xapp-1.0,
    gir1.2-packagekitglib-1.0, usadas exclusivamente pelo frontend retirado.
    Acrescentada python3-apt como dependencia direta ja utilizada pelo backend.
16. python3-gi: nenhum import/consumidor instalado, dependencia removida.
17. XApp: nenhum consumidor instalado, binding/dependencia removidos.
18. PackageKitGlib: removido; PackageKit via PyQt6.QtDBus preservado.
19. python3-psutil: ja nao constava de Depends no 0.4; so ha mencoes no
    changelog historico. Nenhum import ou dependencia atual a remover.
20. Depends final do deb:
    `python3 (>= 3.7), python3-pyqt6, python3-apt, ubuntu-drivers-common, packagekit`.
    Python executa o aplicativo; PyQt6 inclui QtDBus (propriedade confirmada por
    dpkg-query -S); python-apt fornece apt/apt_pkg; UDC detecta/recomenda drivers;
    PackageKit fornece o servico que medeia mutacoes. Nenhuma biblioteca KDE nova.
21. Recommends final: `mokutil, openssl, kmod`, todos read-only nos probes.
    Ausencia continua degradando graciosamente, conforme cobertura de 0.4.
22. Debhelper anterior: compat 9 em debian/compat, Build-Depends debhelper >= 9.
23. Agora: `debhelper-compat (= 13)`, sem debian/compat. Instalado/candidato
    debhelper 13.31ubuntu1 fornece o virtual compat 13. Rules-Requires-Root: no.
    Nenhum warning de compat 9 no build novo.
24. debian/rules foi revisado e preservado: sequencia dh convencional,
    exclusoes -X__pycache__/-X.pyc/-X.pyo ainda necessarias para build apos
    compileall. Nenhum hack exclusivo de compat 9 encontrado. debian/install
    passa a apenas usr: nenhum diretorio /etc e instalado.

## Recursos, traducoes e runtime

25. makepot agora extrai apenas Python ativo, sem GTK/Glade. POT e pt_BR
    sincronizados com gettext, versao 0.5. msgfmt --check: 165 mensagens
    traduzidas, sem fuzzy/erro no pt_BR. Traducoes antigas tornadas obsoletas
    foram preservadas; demais catalogos conservados, inclusive comentarios
    historicos de extracao. Apenas dominio mainuan-gestao-drivers instalado.
26. Recurso adicional removido: offline-symbolic.svg, cujo unico consumidor
    era a UI GTK. Removido tambem count_installed_proprietary_drivers do backend:
    pesquisa de consumidores comprovou uso exclusivo pela GTK. Nenhuma outra
    limpeza estetica/regra de drivers foi feita.
27. Preservados sete icones SVG: amd, ati, broadcom, generic, intel, nvidia,
    virtualbox; icones da aplicacao PNG/SVG; desktop/App ID
    org.mainuan.GestaoDrivers; manpage oficial. Copyright GPL-2.0-or-later,
    Clement Lefebvre, Linux Mint/mintdrivers e contribuidores preservados.
28. Teste subprocesso inicializa frontend oficial e percorre todos os snapshots
    ficticios, verificando ausencia de gi/Gtk/Gdk/GdkPixbuf/XApp/PackageKitGlib/
    GLib/Gio em sys.modules. AST verifica imports ativos; probe real e smoke
    Wayland confirmam a ausencia tambem fora do teste unitario.
29. Cliente agora **Qt puro**, sem outro frontend instalado. O servico externo
    PackageKit pode usar bibliotecas GLib internamente; isso nao representa
    binding GTK/GI ou frontend legado dentro do processo Python Mainuan.

## Testes e artefato

30. Adicionados `tests/test_qt_only_packaging.py` e `tests/inspect_deb.py`:
    fonte/payload sem GTK, unico launcher/manual, dependencia correta, nenhum
    sudoers (nem diretorio vazio), helper, setuid/setgid, action Polkit propria,
    teste/probe/bytecode ou dominio antigo. Gate exige migracao coordenada e
    entende o escaping shell gerado pelo debhelper. Vinte testes novos, incluindo
    runtime subprocesso sem GI; testes antigos nao apagados. Apenas expectativa
    de presenca GTK e versao foram atualizadas no teste de identidade.
31. Suite: **279 total, 279 passed, 0 skipped, 0 failed**. Todos os 259 testes
    anteriores continuam presentes. A mensagem de pacote NVIDIA indisponivel
    vem do fixture de regressao preexistente, nao e falha real do backend.
32. `python3 -m compileall -q usr tests`: passou.
33. Probe PackageKit real read-only passou: Introspect, CreateTransaction,
    Resolve e sinais PropertiesChanged/Package/Finished; intel-microcode
    3.20260210.1ubuntu2 amd64 resolvido, mutation_observed=False, sem imports GI.
34. Modo test e seus 22 cenarios preservados; verificacao visual e automatizada
    de selecao/preview/blockers/ativacao/redimensionamento, somente simulacao.
35. Smoke nativo Plasma/Wayland do launcher real e ficticio passou: versao 0.5,
    titulo correto, loading/deteccao/finalizacao, zero dispositivos adicionais
    como estado valido; preflight Secure Boot UNSUPPORTED no host BIOS. Sem
    GTK carregada e sem warning novo QSettings. Warning portal do checkout
    permanece pois o desktop nao foi instalado no host; desktop correto no deb.
36. `dpkg-buildpackage -us -uc -b`: passou, sem warnings novos. Duas builds
    consecutivas produziram o mesmo SHA256, verificacao local de reprodutibilidade
    (nao substitui reproducao em ambientes independentes).
37. Lintian final: exit 0, nenhuma mensagem. Primeiro build revelou cronologia
    anterior a entrada 0.4; corrigido usando UNRELEASED/data real, preservando
    historico. Nenhum override Lintian criado.
38. desktop-file-validate: exit 0, arquivo oficial inalterado.
39. dpkg-deb -I: Package mainuan-gestao-drivers, Version 0.5, Architecture all;
    Depends/Recommends conforme itens 20/21, sem conffile payload novo.
40. dpkg-deb -c e `python3 tests/inspect_deb.py ../mainuan-gestao-drivers_0.5_all.deb`:
    aprovados. Somente usr/bin/mainuan-gestao-drivers como frontend executavel;
    nenhum arquivo/diretorio sudoers ou runtime GTK/XApp/helper. Meta-scripts
    referenciam o caminho antigo exclusivamente para remove-lo em upgrade.
41. git diff --check final: limpo. Mudancas prontas para revisao, nao commitadas.

## Auditoria final e limites

42. Todas as ocorrencias restantes da pesquisa GTK se enquadram em:
    README/manpage/documentacao atual de migracao; docs/changelog historicos;
    creditos/catalogos com comentarios historicos; testes/gate negativos;
    duas docstrings arquiteturais dizendo que nao ha GLib; referencia necessaria
    ao conffile obsoleto em debian/*.maintscript. Durante build, hooks gerados
    repetem essa referencia e sao removidos da arvore pelo clean. **Nenhum import,
    dependencia, launcher ou recurso GTK funcional instalado**. Inventario
    completo por grupos/caminhos em upstream-audit-0.5.md.
43. Privilegios: zero ocorrencias funcionais sudo/pkexec/modprobe/rmmod/insmod/
    setuid em usr. debian contem somente migracao declarativa do sudoers e
    mencoes de changelog. tests contem asserts negativos, proibicao sudo/root
    no probe manual e comando de contingencia manual em tests/manual/README.
    Nao existe novo mecanismo de mutacao privilegiada proprio.
44. Nenhum sudoers no novo deb, inclusive nenhum diretorio /etc/sudoers.d.
45. Nenhum root helper, setuid/setgid, daemon root ou action PolicyKit propria.
    Autorizacao continua PackageKit/PolicyKit, sem solicitar senha no aplicativo.
46. Probe hello preservado sem modificacoes, seus testes passam, nao instalado.
    Ferramenta de inspecao e testes novos tambem ficam fora do pacote.
47. **Nenhuma mutacao real foi executada pelo Codex**: nao instalou/purgou o
    aplicativo no host, nao alterou drivers/DKMS/MOK/modulos, nao reiniciou,
    nao executou hooks de upgrade. Apenas build, mocks, fixtures e read-only.
48. [Instalacao limpa na VM](beta-0.5-testing.md#instalacao-limpa): comandos
    completos para instalar 0.5, conferir unico executavel e abrir Qt real/test.
49. [Upgrade 0.4 para 0.5](beta-0.5-testing.md#upgrade-obrigatorio-04-para-05):
    registrar dpkg/conffiles/sudoers antes, instalar 0.5 sobre 0.4 e testar
    ausencia de cada artefato obsoleto. Inclui conffile modificado e backup.
50. [Purge na VM](beta-0.5-testing.md#purge): verificar ausencia do caminho
    ativo e backups dpkg, sem apagar dados arbitrarios ou remover dependencias.
51. Upgrade/purge reais e validacao de hardware elegivel continuam pendentes
    na VM do usuario. Nenhuma instalacao artificial de driver e necessaria numa
    VM sem hardware suportado. Limites funcionais de Secure Boot/MOK/ativacao
    permanecem exatamente os do 0.4: pending e desconhecidos conservadores,
    sem enrollment/reload/reboot automatico e sem rollback atomico.
52. Proximo beta: priorizar evidencias de upgrade/purge em VM e validacao em
    hardware compativel antes de novas features. Nao foi iniciado beta 0.6.

## Arquivos desta fase

Criados: debian/mainuan-gestao-drivers.maintscript, tests/inspect_deb.py,
tests/test_qt_only_packaging.py e tres documentos do beta 0.5.
Removidos: sete arquivos GTK/helper/sudoers/recurso descritos acima e debian/compat.
Alterados: README, debian control/changelog/install/docs, makepot/POT/pt_BR,
identidade de versao, backend/drivers (somente metodo morto), teste de identidade
e manpage oficial. Codigo Qt, preflight, signing, activation, planner,
transactions e probe hello permanecem identicos ao commit-base.
