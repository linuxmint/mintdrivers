# Relatorio do beta 0.4

## Base e escopo

1. Branch: `port/kubuntu-26.04`.
2. Commit-base: `b57f5a47e6e72ac492ded90ff8675c0e60d75889` (beta 0.3).
   Arvore inicialmente limpa; nao foi necessario outro checkpoint.
3. Versao: **0.4**. Identidade Qt, App ID e launcher Mainuan preservados.
4. Artefato: `/home/daigo/Github/mainuan-gestao-drivers_0.4_all.deb`.
   Nao instalado no host. Nenhum push, merge, tag, release ou commit do 0.4.
   SHA256: `87ca9a3010d1cf75155a1285122864e55b442218e1418b47bd962965d59b59af`.

## Auditoria e API Ubuntu

5. Mint remoto, apos fetch: `5c8046c00daf1391260093de251a9fffa2e540d7`.
6. Canonical remoto, ls-remote e clone independente:
   `ffb948b95f7c85d5a92275a9aaa53b6d9e2e2453`.
7. UDC local instalado/candidato: `1:0.10.9`, Ubuntu resolute/main.
8. Nenhum delta remoto desde 0.3; nada Mint para portar/mergear. Issues abertas
   reconferidas. Evidencias, links primarios e classificacao em
   [upstream-audit-0.4.md](upstream-audit-0.4.md).
9. API local/HEAD: sysfs path implicito na chave do dispositivo; open_preferred
   disponivel. Nao oferecem packages/gpgpu_packages por opcao nessa API.
10. Adapter preserva packages **somente** se vier um conjunto explicito por
    opcao, validado como nomes Debian. Planner inclui os acompanhantes no plano
    e na confirmacao. Shapes desconhecidos falham; ausencia usa fallback antigo.
    Nao interpretar mapa global/GPGPU como pacotes de um driver desktop.

## Assinatura DKMS

11. Novo `backend/signing.py`: `DkmsSigningProbe`, `DkmsDefaultsAdapter`,
    `SigningEvidence` e `SigningReadiness`, sem Qt/GLib/APT no import.
12. Ordem: framework.conf, dropins *.conf ordenados, contrato local auditado
    do DKMS e selecao efetiva do par de caminhos. No Ubuntu sem chave explicita,
    o DKMS sobrescreve certificado isolado com o par shim-signed. Com chave
    explicita, usa certificado explicito ou default DKMS. Contratos desconhecidos
    nao sao adivinhados.
13. Caminhos: `/etc/dkms/framework.conf`, `/etc/dkms/framework.conf.d/`,
    defaults `/var/lib/shim-signed/mok/MOK.der` e `/var/lib/dkms/mok.pub`.
    Auditoria: DKMS `3.2.2-1ubuntu1`, shim-signed `1.59+15.8-0ubuntu2`.
    Parser estatico, sem shell/source/eval. Ferramenta de assinatura e
    CONFIG_MODULE_SIG_HASH do kernel verificados; signer/arvore customizados,
    PKCS11 e expansoes nao comprovadas degradam para UNKNOWN.
14. Chave privada: **conteudo nunca aberto, lido, copiado ou passado a comandos**.
    Apenas metadados/existencia; alias por symlink/hardlink com certificado e
    rejeitado. Caminho privado nao aparece em SigningEvidence nem logs.
15. `mokutil --test-key` verifica exatamente o certificado selecionado. No host
    BIOS, retornou codigo 1, `EFI variables are not supported on this system`;
    nao houve enrollment comprovado real. Os casos positivos foram mockados.
16. Estados: NOT_REQUIRED, READY_ENROLLED, CERTIFICATE_NOT_ENROLLED,
    PENDING_ENROLLMENT, CERTIFICATE_NOT_FOUND, MOKUTIL_UNAVAILABLE, UNSUPPORTED,
    UNKNOWN. MokState legado refere-se agora ao certificado de assinatura,
    nao a uma MOK qualquer.
17. ENABLED + DKMS conhecido + READY_ENROLLED + demais requisitos validos:
    **permitir**. Headers ausentes/incompativeis continuam bloqueando.
18. Certificado nao inscrito, ausente ou UNKNOWN: bloquear. MOK A inscrita nao
    libera certificado B. Secure Boot UNKNOWN e requisitos de modulo UNKNOWN
    continuam conservadoramente bloqueados mesmo com uma chave conhecida.
19. Pending exige fingerprint completo do **mesmo certificado**, obtido por
    openssl x509 e comparado com `mokutil --list-new`. Pending correspondente
    continua bloqueado: nao comprovamos o fluxo PackageKit sem interacao extra.
    A UI orienta completar MokManager externamente, sem prometer ativacao.
20. Nao ha geracao/enrollment/import/password MOK nem mudanca de firmware.
    As unicas operacoes mokutil sao --sb-state, --test-key e --list-new,
    com argv separado, LC_ALL=C, timeout e tratamento de erro/ausencia.

## Ativacao

21. `DeviceInfo.sys_path` preserva campo explicito ou chave sysfs do UDC;
    plugins sem caminho retornam None. Sem PCI database ou deteccao propria.
22. Novo `backend/activation.py`: `DriverActivationProbe`, `DeviceBinding` e
    classificacao independente da GUI. Executado no worker dos snapshots.
23. Somente leitura de `<sys_path>/driver` e `driver/module`; caminhos resolvidos
    devem permanecer sob sysfs. Links ausentes/quebrados, permissao e caminho
    inexistente degradam sem traceback. Driver/module antes vao no contexto
    `ExecutionResult.bindings_before`; depois sao coletados novamente.
24. modinfo apenas para modulo conhecido pelo sysfs, sem shell. Le filename,
    signer, sig_key e sig_hashalgo. DKMS com Secure Boot exige adicionalmente
    sig_key correspondente ao Subject Key Identifier do certificado inscrito.
    Signer preenchido sozinho nao comprova confianca. Sao evidencias de binding
    e do arquivo de modulo disponivel, nao atestacao criptografica da memoria.
25. Estados: ACTIVE_CONFIRMED, INSTALLED_REBOOT_REQUIRED, INSTALLED_MOK_REQUIRED,
    INSTALLED_ACTIVATION_UNVERIFIED, INSTALLED_NOT_ACTIVE, FAILED, UNKNOWN.
    ACTIVE antigo e apenas alias de compatibilidade. PackageKit success ou
    pacote instalado, sozinhos, nunca produzem ACTIVE_CONFIRMED.
26. NVIDIA ligado a nvidia confirma a familia, nao branch/open/closed. Troca com
    mesmo modulo ainda associado requer reboot; sem evidencia anterior suficiente
    fica unverified. Recomendacao/pin UDC nao foi recalculada.
27. Broadcom ligado a wl e evidencia adicional. Sem helper novo ou reload de
    rede; a orientacao de reboot da transacao continua. Helper antigo/sudoers
    permanecem **LEGACY ONLY**, exclusivamente pela GTK.
28. Ao reabrir, nova deteccao/preflight/binding, sem persistir falsa ativacao em
    QSettings. Estado de pacote completamente instalado e checado tambem na
    abertura, nao apenas depois da transacao. Pacote parcialmente configurado
    nao e apresentado como instalado/ativo pelo novo verificador.

## UI, testes e verificacoes

29. Modo test: **22 cenarios** (14 anteriores + oito novos): MOK diferente,
    pending correspondente, assinatura desconhecida, ativo, reboot, MOK
    necessaria, ativacao nao confirmada e driver antigo associado. O cenario
    enrolled anterior agora representa assinatura realmente pronta.
    Todos usam fixtures e simulacao em memoria, sem probes do host.
30. Novos testes em test_signing.py, test_activation.py, test_udc_metadata.py e
    test_preflight_workflow.py; cobertura anterior preservada com ajustes
    semanticos. Matriz MOK A/B, parser, overrides, falhas de ferramentas/locale,
    chave nunca lida, links sysfs temporarios, assinatura divergente, prebuilt,
    variantes, trust perdido antes de confirmar e dados startup parcialmente
    configurados. Testes hello/probe PackageKit existentes preservados.
31. **259 testes passaram**, incluindo os 187 anteriores: 72 testes adicionados.
32. `python3 -m compileall -q usr tests`: passou. POT e pt_BR atualizados;
    msgfmt --check: 190 mensagens traduzidas, uma fuzzy GTK herdada, sem erro.
33. Probe real somente leitura: Introspect, CreateTransaction, Resolve,
    PropertiesChanged, Package e Finished recebidos; exit sucesso, nenhuma
    mutacao. Resolve intel-microcode `3.20260210.1ubuntu2`, amd64. Sem imports
    gi/Gtk/Gdk/GdkPixbuf/XApp/GLib/Gio/PackageKitGlib.
34. Verificacoes reais somente leitura: UEFI ausente, Secure Boot UNSUPPORTED,
    kernel `7.0.0-38-generic`, headers PRESENT. DKMS defaults reconhecidos;
    mokutil --sb-state/--test-key/--list-new retornam EFI indisponivel. Sysfs e
    modinfo reais confirmaram amostras ahci/intel_lpss_pci, com campos de
    assinatura legiveis. Isso nao e teste de instalacao NVIDIA/Broadcom.
35. `dpkg-buildpackage -us -uc -b`: sucesso, pacote all 0.4. Avisos do build
    sobre debhelper compat 9 sao herdados; nao houve migracao fora de escopo.
36. Lintian: exit 0, nenhuma mensagem/novo warning.
37. desktop-file-validate: exit 0. Qt nativo Wayland real e modo test abriram,
    detectaram e fecharam; todos os 22 cenarios e confirmacoes foram capturados,
    com redimensionamento, scroll e inspeccao visual representativa. Nenhum
    import GTK proibido. Warning de portal no checkout: desktop Mainuan ainda
    nao instalado no host; arquivo correto incluido no deb. Nenhum warning
    QSettings Empty key.
38. dpkg-deb -I/-c: Package mainuan-gestao-drivers, Version 0.4, Architecture all;
    signing/activation presentes, Qt oficial, GTK legada e gettext preservados.
    Probe hello/tests nao instalados; sem pycache/pyc/pyo. Recommends acrescenta
    openssl e kmod da distribuicao: ausencia degrada provas opcionais; mokutil
    permanece Recommends. Nenhuma dependencia PyPI ou helper root novo.
39. git diff --check: sem erros; alteracoes 0.4 separadas da base consolidada.
40. Auditoria de privilegios em usr/tests: mokutil somente leitura em signing e
    preflight; testes usam mocks. sudo/modprobe somente no GTK/helper legado
    preexistente, e referencia manual de recuperacao hello em tests/manual/README.
    A mensagem do probe proibe sudo/root. Nenhuma ocorrencia nova executavel de
    enrollment, update-secureboot-policy, apt-get ou live-media no frontend Qt.
    Referencias a update-secureboot-policy nesta auditoria sao documentais.
41. **Codex nao executou nenhuma instalacao/remocao real de driver/pacote,
    DKMS, geracao/enrollment MOK, manipulacao de modulo ou reinicializacao.**
    Apenas mocks, fixtures, simulacoes e probes read-only. Pacote nao instalado
    no host. Nenhuma chave privada lida.

## Limites e proximo beta

42. Validacao positiva real de Secure Boot/MOK e hardware NVIDIA/Broadcom fica
    pendente para equipamento elegivel do usuario. Adapter de defaults cobre
    a versao DKMS auditada; outras exigem auditoria, nao fallback otimista.
    Configuracoes dinamicas, signer customizado e PKCS11 nao suportados.
    Pending continua bloqueado. Sem rollback atomico ou reload automatico.
    Binding confirma familia; nao prova versao do modulo carregado. openssl
    ausente/certificado sem SKI degrada ativacao, nao inventa confianca.
43. Recomenda-se remover GTK no beta seguinte **somente apos** validar 0.4 em
    hardware elegivel e equivalencia funcional. Essa remocao deve incluir helper
    Broadcom, sudoers e dependencias GTK de maneira conjunta, nao nesta tarefa.
    Nao foi iniciado beta 0.5. Roteiro seguro em
    [beta-0.4-testing.md](beta-0.4-testing.md); VM sem hardware nao precisa de
    driver artificial/incompativel.

## Arquivos

Criados: signing.py, activation.py, tres arquivos test_* correspondentes,
upstream-audit-0.4.md, beta-0.4-testing.md e este relatorio.
Alterados: identidade/version, backend models/drivers/preflight/test_scenarios,
transactions models/planner/execution, Qt main_window/widgets, tres testes
anteriores (identity/preflight/workflow), README, changelog/control/docs,
makepot/POT/pt_BR e manpage. Nada GTK, desktop, launcher ou probe hello alterado.
