# Relatorio do beta 0.3

Data de referencia: 2026-10-18. Nenhuma instalacao/remocao de driver ou pacote,
DKMS, MOK, modprobe ou reboot foi executada pelo Codex.

1. Branch: `port/kubuntu-26.04`.
2. Base real: `d35d878faba7cfacc94d31ecb921c894d312412d`.
3. Checkpoint necessario: `beta: establish 0.2 transaction baseline`, mesmo hash.
   Consolidou beta 0.2 e probe hello; arvore limpa antes da auditoria/codigo 0.3.
   Sem push, merge, rebase, tag de produto ou release. Master nao foi alterada.
4. Versao: `0.3`, historico do changelog preservado.
5. Artefato: `/home/daigo/Github/mainuan-gestao-drivers_0.3_all.deb`.
6. UDC instalado/candidato: `1:0.10.9`, resolute/main. mokutil: `0.7.2-2`.
7. Mint remoto: `5c8046c00daf1391260093de251a9fffa2e540d7`; fetch e comparacoes
   master..upstream/master executados, sem delta.
8. UDC upstream: `ffb948b95f7c85d5a92275a9aaa53b6d9e2e2453`, release mais recente
   registrada no changelog `1:0.10.13`.
9. Mudanca principal: commit `03142a781218c7e8ed76f8e29eae94948438877a`, prioridade
   custom/OEM, open/runtimepm/point releases. Ver docs/upstream-audit-0.3.md para
   fontes e classificacao individual das issues/PRs #109/#107/#103/#100/#111 etc.
10. Mint incorporado: nenhuma mudanca nova merged; contexto de avisos/MOK e
    server foi portado semanticamente, nao por merge de codigo GTK.
11. Mint nao incorporado: PR #107 WIP, GUI GTK/XApp, enrollment manual, helper
    Broadcom e DisplayLink/EVDI. Razoes e categorias constam da auditoria.
12. UDC incorporado: autoridade dos flags retornados e adapter da API local de
    kernel. Nao copiar interpretador custom JSON nem APIs exclusivas do master.
13. Politica NVIDIA anterior: ocultar server e filtrar open/closed pelo limiar 560,
    inclusive transferindo uma recomendacao open para closed em branches antigos.
14. Politica 0.3: recomendacao explicita intocada, sem heuristica de branch/versao
    nem filtro adicional de origem sobre o flag UDC. Compatibilidade e GPU pin
    continuam responsabilidade do pacote realmente instalado.
15. Custom GPU pin: preservar o resultado do UDC; nunca abrir custom_supported_gpus.json.
16. Open/closed: manter ambas as alternativas aplicaveis e seus flags originais,
    inclusive a opcao instalada, branches anteriores a 560 e point releases.
17. Server: manter recomendado, instalado ou unica variante disponivel; ocultar
    apenas server nao recomendado/nao instalado quando existir desktop utilizavel.
18. Secure Boot: ENABLED, DISABLED, UNSUPPORTED e UNKNOWN; UEFI e campo separado.
    BIOS desta VM foi corretamente classificado UNSUPPORTED, nao erro.
19. DKMS: NO_DKMS, DKMS_REQUIRED, DKMS_POSSIBLE e UNKNOWN. Dependencias APT reais,
    alternativas, Provides versionados e efeitos PackageKit; NVIDIA nao implica DKMS.
    Prova prebuilt exige relacao com o driver, kernel exato e origem Ubuntu confiavel.
20. KernelDetection: adapter pequeno para is_running_kernel_outdated(); retorno
    inesperado/API indisponivel => UNKNOWN. Nenhum metodo CLI instalador e chamado.
21. Headers: Makefile e include/config/kernel.release devem corresponder ao kernel
    em uso. Ausentes/nao verificados bloqueiam DKMS. Nao sao adicionados implicitamente.
22. Kernel outdated: warning, sem upgrade automatico; hint de kernel fora do fluxo
    prebuilt e preservado sem transformar toda GPU NVIDIA em DKMS.
23. MOK: ENROLLED, NOT_ENROLLED, PENDING, UNKNOWN. Certificado somente quando
    configuracao estatica e arquivo real podem ser identificados; defaults/dinamismo
    nao sao adivinhados. Uma inscricao generica nao prova assinatura de modulo futuro.
24. mokutil implementado: --sb-state, --list-new, --test-key com certificado validado.
    Argumentos em lista, LC_ALL=C, timeout de 10s, comandos ausentes/erros tratados.
    Em BIOS nenhum comando mokutil e necessario. Recommends mantem uso sem a ferramenta.
25. Nao existem importacao MOK, senha propria, geracao de chave, alteracao de firmware,
    chamada de update-secureboot-policy nem reboot nesta implementacao Qt.
26. Secure Boot ativo/desconhecido + DKMS sem assinatura garantida: blocker antes
    de qualquer remocao/instalacao, inclusive com MOK enrolled. Prebuilt compativel
    sem DKMS nao recebe esse bloqueio; headers e outras evidencias ainda sao verificadas.
27. Broadcom: fixture broadcom-sta-dkms e teste bcmwl transicional/dependencia DKMS,
    deteccao/plano, Secure Boot e simulacao pos-instalacao com reboot requerido.
28. Helper Broadcom e sudoers marcados LEGACY ONLY; Qt nao chama sudo/modprobe/helper.
    A GTK, suas dependencias e entry point legado permanecem.
29. Pos-transacao: nova instancia backend, estado configurado apt_pkg, ID/versao
    instalada e preflight novos antes da mensagem final. Estados installed/reboot,
    installed/MOK, installed/not verified, failed, unknown; ACTIVE e reservado e
    nunca deduzido de PackageKit Finished ou apenas da presenca do pacote.
30. UI: Verificacao do sistema em preview/confirmacao, avisos separados de bloqueios,
    Apply desabilitado para blockers, validacao repetida pelo controller, mensagens
    de ativacao apos re-deteccao. POT/pt_BR e manpage 0.3 atualizados.
31. Modo test: geral + 13 cenarios: Secure Boot/prebuilt, DKMS enrolled/missing,
    disabled/unknown, Broadcom, pin NVIDIA closed, open, closed, server recomendado,
    kernel outdated, headers missing, MOK pending. Somente memoria, sem APT/firmware
    ou CPU do host, e sem construir transporte PackageKit para executar alteracoes.
32. Novos testes: 63, em test_preflight.py, test_preflight_workflow.py e
    test_upstream_nvidia.py. Matrizes usam subTests adicionais; nenhum teste anterior
    foi removido. Assercoes antigas de politica NVIDIA/BIOS foram atualizadas para
    o contrato auditado, mantendo cobertura equivalente e expandida.
33. Total final: 187 testes passando (124 anteriores + 63 novos). Regressao tambem
    executada com -q/FAULTHANDLER; nenhum SIGSEGV nas execucoes finais. O baseline
    teve um SIGSEGV transiente inicial, registrado na auditoria, nao reproduzido.
34. compileall usr/tests: sucesso. msgfmt --check --check-format pt_BR: sucesso.
35. Probe PackageKit real somente leitura: introspection/CreateTransaction/Resolve,
    Package/PropertiesChanged/Finished recebidos para intel-microcode; exit 1 de
    sucesso PackageKit, processo exit 0, sem imports proibidos. Probe hello intacto.
36. dpkg-buildpackage -us -uc -b: sucesso. Avisos herdados debhelper compat 9.
    Inspecao detectou caches gerados por testes concorrentes ao build; corrigido
    com exclusao explicita __pycache__/.pyc/.pyo em dh_install, sem instalar bytecode.
37. Lintian: exit 0, sem mensagens.
38. desktop-file-validate: exit 0. Launcher/ID continuam org.mainuan.GestaoDrivers.
39. dpkg-deb -I/-c: Package mainuan-gestao-drivers, Version 0.3, Architecture all;
    preflight e cenarios presentes, GTK/backend preservados. Sem tests/manual,
    probe hello, bytecode ou ferramentas de auditoria instalados.
40. git diff --check: sem erros. Alteracoes 0.3 ficam para revisao, separadas do
    checkpoint 0.2; nenhum commit 0.3/push/tag/release criado automaticamente.
41. Auditoria de privilegios rg usr/tests: novas chamadas mokutil sao somente leitura;
    sudo/modprobe executaveis existem apenas no GTK/helper legado. No probe ha
    mensagem proibindo root/sudo; sudo apt remove hello e apenas contingencia
    documentada, nunca executada. Testes mokutil usam mocks; nao ha novo helper.
42. Nenhuma mutacao real pelo Codex. Teste nativo Wayland real sem drivers e todos
    os perfis ficticios passou, inclusive pt_BR, redimensionamento, scroll e botoes.
    Sem GTK/Gdk/GdkPixbuf/XApp/GLib/Gio/PackageKitGlib no processo oficial. Capturas
    e logs em /tmp/mainuan-0.3-visual e /tmp/mainuan-0.3-*.log.
43. Limitacoes: sem enrollment/assinatura garantida; sem prova criptografica ou
    binding de modulo em hardware; nao promete ACTIVE/rollback; headers checados
    para kernel em uso, nao todos os kernels instalados. Validar provedores reais,
    PRIME e Broadcom em hardware compativel. No checkout nao instalado houve aviso
    de portal desktop ID ausente no host; o .desktop correto esta no pacote.
    Sem warning QSettings na execucao com argv/identidade oficial correta.
44. Candidatos ao 0.4, NAO implementados: validacao hardware/prebuilt, evidencias
    de assinatura/binding, coordenacao de enrollment com ferramentas da distribuicao,
    multiplos kernels/headers e futura retirada conjunta GTK/helper legado.

## Arquivos desta fase

Criados: backend/preflight.py, backend/test_scenarios.py, tres suites novas,
docs/upstream-audit-0.3.md, docs/upstream-sync-policy.md,
docs/beta-0.3-testing.md e este relatorio (somente checkout).

Alterados: backend/drivers.py; transactions/execution.py, models.py, safety.py;
qt/main_window.py; identidade VERSION; testes backend/safety/identity existentes;
debian/changelog, control, docs, rules; README, arquitetura, makepot, POT, pt_BR e manpage;
apenas comentarios LEGACY ONLY no helper/sudoers herdados. Sem remocoes.

O ambiente de teste nao recebeu instalacao do .deb. Para validacao humana na VM,
seguir docs/beta-0.3-testing.md; nao instalar driver incompativel artificialmente.
