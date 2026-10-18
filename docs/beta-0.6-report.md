# Relatorio do beta 0.6

## Base e resultado

1. Branch: `port/kubuntu-26.04`.
2. Base real: `954796f65a7956343ff102414a27b18cbd90403a`, checkpoint Qt-only
   0.5 consolidado pelo usuario. Arvore inicialmente limpa, 279 testes passando.
   Nao foi necessario criar outro checkpoint; alteracoes 0.6 ficam para revisao.
3. Versao: **0.6**, ainda beta, nao RC.
4. Artefato: `/home/daigo/Github/mainuan-gestao-drivers_0.6_all.deb`.
5. Mint: `5c8046c00daf1391260093de251a9fffa2e540d7`.
6. Canonical UDC: `ffb948b95f7c85d5a92275a9aaa53b6d9e2e2453`.
   UDC instalado/candidato `1:0.10.9`. Sem delta funcional upstream desde 0.5,
   sem merge ou nova politica NVIDIA. Evidencias em upstream-audit-0.6.md.

## Origens e politica de pacotes

7. Third-party explicitamente suportado como metadado, sem politica de favorecer
   Ubuntu nem PPA. Nao ha nomes de PPAs codificados.
8. `DriverSource`: DISTRIBUTION, THIRD_PARTY, UNKNOWN em DriverOption. Preferir
   source textual quando fornecido; fallback estrito ao from_distro bool da API
   local. `AptOrigin` preserva origin, label, archive e site da candidate APT.
9. `candidate_version` separado de version (que pode ser a instalada). Nenhuma
   selecao numerica da maior versao; PackageKit IDs continuam gerados no backend.
10. Pinning: o cache APT escolhe candidate; versoes mais novas nao candidatas
    nao substituem essa escolha. Testes cobrem distro e terceiros favorecidos.
11. NVIDIA de terceiros pode ser recomendado ou alternativa, conforme UDC.
    Recommended/open/closed/server/custom pin permanecem autoridade UDC.
12. Third-party nao implica DKMS. Dependencias/plano real continuam avaliados.
    Compatibilidade prebuilt confiavel para o kernel e separada de confianca de
    assinatura no firmware. Com SB ativo/desconhecido, prebuilt third-party sem
    evidencia de assinatura adequada recebe blocker especifico. Confianca APT
    nao comprova assinatura Secure Boot; nao ha bloqueio generico de PPAs.
13. Mesa nao foi adicionado ao escopo. Cache contendo Mesa sem dispositivo UDC
    nao gera driver; nao ha parser sources.list nem gestao propria de repositorios.

## UX e seguranca de sessao

14. Estado vazio explicito: sistema usando drivers adequados, nenhum adicional
    disponivel/necessario. Nao e tratado como falha.
15. Loading precede resultado e desabilita controles; nenhuma tela vazia falsa
    antes da deteccao. APT/backend continuam em QThread, widgets na thread Qt.
16. BACKEND_ERROR e BACKEND_UNAVAILABLE distintos; mensagem amigavel e Tentar
    novamente. Sem traceback na UI; log registra operacao/tipo da excecao,
    nao valores arbitrarios que possam conter credenciais de repositorio.
17. PackageKit indisponivel preserva deteccao/listagem e bloqueia Aplicar.
18. Sem teste proprio de Internet. OFFLINE somente apos NO_NETWORK explicito
    do PackageKit; download failed/file not found nao provam ausencia de rede.
    Deteccao local funciona sem consulta a um servidor de conectividade.
19. Live permite deteccao, selecao/previa e simulacao test; nao mutacao real.
    UNKNOWN tambem bloqueia conservadoramente. Motivo visivel na interface.
20. `SystemSessionProbe` somente le /proc/cmdline e /proc/self/mountinfo.
    boot=casper/boot=live ou raiz overlay com upperdir/workdir /cow => Live;
    raiz persistente conhecida em bloco, sem boot Live/desconhecido => instalado;
    falha/ambiguidade/overlay desconhecido => UNKNOWN. Sem username/hostname.
    Controlador revalida a sessao antes de Resolve/confirmacao e de cada etapa
    modificadora, nao depende apenas do estado de um botao.
21. Nomes/descricoes acessiveis para radios, comandos, progresso e mensagens.
    Recomendado, instalado, fonte e ativacao nao dependem exclusivamente de cor.
22. Testados Space, Tab, Shift+Tab, Enter e Esc; Cancelar e default na confirmacao.
    Sem atalhos Plasma proprios. Teste com leitor de tela humano ainda pendente.
23. Qt nativo Wayland validado a 100/125/150/200%, sem alterar backend QPA.
24. Janela reduzida: comandos em grade 2x2, mensagens/dispositivos em scroll;
    verificado inclusive 560x343 logicos a 200%.
25. Labels e badges com quebra de linha; metadados de repositorio como texto
    simples/tooltip escapado. Testes de textos longos e rolagem.
26. Instalado, recomendado e ativo separados. Status geral nao chama um pacote
    selecionado de driver ativo; ativacao continua vindo do sysfs/preflight.
27. Previa/confirmacao lista instalar/remover, terceiros, reboot, MOK e blockers;
    Cancelar permanece default. Resultado prioriza reinicio quando necessario,
    mas nao reinicia nem carrega/descarrega modulos.

## Diagnostico e ciclo de instalacao

28. Logging por modulos backend/preflight/planner/execution/packagekit/ui,
    WARNING normalmente; eventos de transacao INFO e detalhes DEBUG sob demanda.
    Nao ha senhas/tokens/chaves em logs novos; excecoes externas sao categorizadas.
29. `--debug` aumenta detalhamento, sem mudar a politica ou executar operacoes.
30. Ajuda > Copiar informacoes de diagnostico: JSON por allowlist, somente na
    acao explicita do usuario. Versoes, kernel, SB/MOK/signing, sessao, candidatos,
    origens e PackageKit. Sem sysfs paths, IDs de hardware, usuario/hostname,
    certificados/chaves privadas, ambiente ou upload. Site reduzido ao hostname,
    removendo credenciais/path/query. Nenhum arquivo de log de usuario criado.
31. Ajuda > Sobre e `--version` identificam Gestao de Drivers 0.6, Mainuan,
    GPL-2.0-or-later e origem Linux Mint/Clement Lefebvre/contribuidores.
32. Upgrade 0.4 -> 0.6: preservado `rm_conffile ... 0.5~` em .maintscript;
    limite compara versao anterior e cobre quem pulou 0.5. Hooks gerados
    preinst/postinst/prerm/postrm inspecionados pelo gate do pacote.
33. Upgrade 0.5 -> 0.6: mesmo mecanismo mantido; nao reinstala artefatos GTK.
    Ambos upgrades documentados, mas NAO executados no host; requerem VM.
34. Purge usa hooks Debian para conffile/backups obsoletos, nao apaga preferencias
    pessoais nem dependencias. Roteiro em beta-0.6-testing.md; nao executado no host.

## Validacao

35. 28 cenarios ficticios: 22 preservados + third-party recommended, third-party
    DKMS, Live, PackageKit indisponivel, backend error, no drivers. Sem I/O de
    hardware/transacoes reais nesses fixtures. Probe hello preservado e excluido
    do pacote, assim como o novo probe visual Qt de desenvolvimento.
36. 50 testes adicionais para source/candidate/pinning/origens, DKMS/prebuilt de
    terceiros, Live/UNKNOWN/revalidacao, estados UX, privacidade, acessibilidade,
    teclado, textos longos, diagnostico e CLI. Nenhum teste anterior apagado.
37. Suite completa: **329 total, 329 passed, 0 skipped, 0 failed**.
38. `python3 -m compileall -q usr tests`: OK. POT regenerado a partir do codigo
    ativo; pt_BR com 199 mensagens traduzidas, msgfmt --check OK; demais catalogos
    preservados. Somente dominio mainuan-gestao-drivers instalado.
39. Probe PackageKit real read-only: Introspect, CreateTransaction, Resolve,
    PropertiesChanged/Package/Finished; sucesso, mutation_observed=False,
    nenhum import GTK/GI. Pacote consultado intel-microcode, sem instalar/remover.
40. Launchers real e test: 0.6, Wayland, titulo correto, 0 dispositivos reais e
    2 ficticios no default; fechamento normal. Probe visual percorreu 28 cenarios
    a 100% e 9 criticos a 125/150/200%; assertions de Apply/bloqueio e imports.
    Screenshots inspecionados para terceiros, Live, erro, previa e estado vazio.
    Warning conhecido de portal no checkout sem desktop ID instalado no host;
    desktop correto consta no .deb. Sem novo warning QSettings.
41. `dpkg-buildpackage -us -uc -b`: OK, pacote 0.6/all.
42. Lintian: sem erros/warnings no pacote final. Quebra de linha nova do
    changelog corrigida durante a validacao, sem mudar entradas historicas.
43. desktop-file-validate: OK, org.mainuan.GestaoDrivers.desktop preservado.
44. dpkg-deb -I/-c e tests/inspect_deb.py: OK; Package/Version/Architecture
    corretos, um launcher, um desktop, uma manpage. Sem GTK/XApp/GI/
    PackageKitGlib, sudoers, helper, setuid, action Polkit propria ou probes/tests.
45. Depends final: python3 (>= 3.7), python3-pyqt6, python3-apt,
    ubuntu-drivers-common, packagekit. Recommends: mokutil, openssl, kmod.
    Suggests: nenhum. Dependencias e debhelper compat13 inalterados desde 0.5.
46. Auditoria de privilegios: runtime apenas mokutil --sb-state/--test-key/
    --list-new, modinfo/openssl leitura e consultas dpkg-query ja existentes.
    sudo no README manual do probe e instrucao de recuperacao para VM, nao
    executada; sudoers nas migracoes Debian e testes negativos, nao payload.
    Mencoes GTK em changelog/creditos/negativos/documentacao sao historicas.
    Sem novos sudo/pkexec/modprobe/rmmod/insmod/enrollment ou helper root.
    `git diff --check` limpo; sem push, merge, tag, release ou commit desta fase.
47. **Nenhuma mutacao real de pacote, driver, modulo, MOK, firmware, repositorio
    ou reboot executada pelo Codex.** Apenas leitura, fixtures, build e testes.
48. Limitacoes: upgrades/purge/ISO Live reais ainda precisam da VM; host BIOS
    sem hardware adicional nao valida GPU/SB/MOK reais. Leitor de tela e temas
    alternativos precisam de revisao humana. Se UDC capturar internamente uma
    falha e devolver vazio, a API nao permite distingui-la de lista legitimamente
    vazia. Assinatura prebuilt de terceiros sem evidencia permanece bloqueada
    com SB; nao ha enrollment proprio. Diagnostico nao inclui traceback bruto.
49. Prontidao RC: boa cobertura automatizada, mas **nao declarar RC** antes de
    validar roteiros de instalacao/upgrade/purge/Live, PPAs configurados reais e
    hardware elegivel com autorizacao do usuario. Nao forcar driver na VM vazia.
    Proxima etapa deve focar validacao/manual e correcoes, nao nova arquitetura.

## Arquivos

Criados: backend/session.py, backend/diagnostics.py, qt/state.py,
tests/test_third_party.py, tests/test_session_ux.py, tests/manual/qt_ux_probe.py
e os tres documentos beta-0.6/upstream-audit-0.6.
Alterados: modelos/drivers/preflight/planner/execution, widgets/main_window/
application Qt, identidade VERSION, README/manpage, changelog/docs/makepot/POT/
pt_BR e expectativas de identidade/fixtures/packaging nos testes anteriores.
Nenhum arquivo runtime removido; nenhuma nova dependencia.
