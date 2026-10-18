# Relatório do beta 0.2

## Entrega

1. **Commit-base:** `00b5fbffb8e7c0c0795c83801a5aed308bd6caf3`.
   O beta 0.1 estava sem commit sobre `698b2de`. Após validar seus 60 testes,
   foi criado o checkpoint local `release: checkpoint Mainuan driver manager beta 0.1`.
   O checkpoint não contém bytecode; `.gitignore` protege os caches Python.
   As alterações 0.2 ficaram separadas e sem commit.
2. **Branch:** `port/kubuntu-26.04`. Sem alteração de master, push, merge, tag
   ou release. O pacote não foi instalado no host.
3. **Arquivos criados:** os sete arquivos listados na seção correspondente abaixo.
4. **Arquivos alterados:** os dezoito arquivos listados abaixo. GTK, helper
   Broadcom, sudoers legado e licença não foram alterados nesta fase.
5. **Versão:** `0.2`; entrada nova em `debian/changelog`, com todo o histórico preservado.
6. **Pacote:** `/home/daigo/Github/mainuan-gestao-drivers_0.2_all.deb`.
   SHA256: `58aded529166486206a8a6aa20398aaf7cd54f13c3d2b7a812661b526162c475`.

## Execução

7. **Aplicar alterações:** habilitado apenas para plano válido com operações de
   pacote, PackageKit disponível, detecção encerrada, sem outra operação ou
   confirmação aberta. O coordenador bloqueia imediatamente chamadas concorrentes.
8. **Confirmação:** diálogo explícito com Instalar, Remover, dependências adicionais,
   aviso beta, reinício possível e Cancelar/Aplicar; Cancelar é a ação padrão.
   Prévia continua somente leitura. Nomes repetidos incluem arquitetura.
9. **Revalidação:** snapshots novos em QThread antes da confirmação e depois dela,
   reconstrução das escolhas pelo backend, validação de IDs, Resolve e simulações
   PackageKit. Alterações do plano ou efeitos calculados exigem nova confirmação.
   IDs inconsistentes/indisponíveis interrompem o fluxo e solicitam nova detecção.
10. **Sequência:** resolver e simular antes de confirmar; repetir preflight após
    confirmar; executar remoção, simular novamente a instalação e então instalar.
    Cada operação real também resolve seus IDs relevantes antes de iniciar.
11. **Ordem:** remoção antes de instalação preserva o comportamento upstream.
    São transações separadas: não há atomicidade, lock abrangendo todo o fluxo
    nem rollback garantido. `allow_deps=false` e `autoremove=false` permanecem fixos.
12. **Falha parcial:** registra etapas concluídas, interrompe as demais,
    informa `PARTIAL_FAILURE` e solicita nova detecção. Não restaura drivers
    automaticamente. Eventos de mutação e perda do daemon podem indicar resultado
    incerto mesmo sem uma etapa concluída.
13. **Sucesso:** mensagem clara, descarte das seleções anteriores e nova chamada
    a `DriverBackend().get_devices()` por um backend novo na thread de detecção.
14. **Falha/cancelamento:** mensagem estruturada e nova detecção, sem marcar a
    opção desejada como instalada por suposição. Autorização negada tem mensagem
    específica; rede/dependências são diferenciadas. A interface volta a ser utilizável.
15. **PolicyKit:** somente PackageKit, via system bus/PyQt6.QtDBus, com autorização
    interativa nas operações reais. O agente da sessão cuida da senha. Recusas
    numéricas e D-Bus, inclusive `RefusedByPolicy`, são reconhecidas.
16. **Cancelamento:** somente quando permitido por AllowCancel; solicitação e
    resultado são distintos. Não mata daemon, processos ou threads de APT.
17. **Fechamento:** bloqueado enquanto uma operação estiver ativa; oferece pedido
    seguro de cancelamento quando permitido. Timeout do reconhecimento D-Bus
    de uma mutação não encerra o acompanhamento: aguarda Finished/Destroy ou
    perda do serviço. Detecção pendente termina antes de destruir a janela.
18. **Progresso:** sinais Qt semânticos derivados do PackageKit, pacote atual e
    percentual real. `None` usa barra indeterminada. Widgets só são atualizados
    na thread principal Qt; APT é usado nas threads de trabalho, sem compartilhar caches.
19. **Reinício:** combina RequireRestart e `/var/run/reboot-required` após etapas
    reais bem-sucedidas. Preserva sessão/sistema/aplicação e o aviso de possibilidade
    do plano após etapas concluídas. Não chama reboot, shutdown ou systemctl.
20. **NVIDIA:** regras de seleção e enumeração de dependências continuam no backend.
    Remoções são deduplicadas pelo planner e os IDs precisam estar instalados.
    Simulações bloqueiam remoções fora do plano; identidades de efeitos incluem
    nome/versão/arquitetura, preservando dependências multiarch.
21. **Broadcom:** não usa o helper GTK, sudo ou carregamento de módulos pela Qt.
    A ativação pode depender de reinício, indicado após instalação bem-sucedida.
22. **Secure Boot/MOK:** leitura não invasiva de SecureBoot/SetupMode em efivarfs.
    Estado habilitado/indeterminado bloqueia dependência DKMS necessária ou não
    verificável; simulações também verificam DKMS adicional. Metadados comprovadamente
    sem DKMS são permitidos. É uma proteção conservadora, não uma implementação
    definitiva de MOK, validação de certificados ou ativação de hardware.
23. **Modo test:** sempre usa `SimulatedTransaction`, mesmo com factory real injetada.
    Não constrói transporte D-Bus; altera apenas um overlay de fixtures em memória.
    Janela e confirmação identificam que nenhuma alteração será aplicada ao sistema.

## Validação

24. **Testes:** 102 testes passaram, incluindo os 60 anteriores e os 14 testes
    originais do backend. Nenhum teste anterior foi removido.
25. **Cenários novos:** instalação/remoção/troca, confirmação, revalidação e plano
    adulterado; falhas antes/depois da remoção e durante instalação; falha parcial
    sem rollback; autorização negada/cancelada, download/dependências, erros PackageKit,
    desaparecimento do daemon, timeout aguardando resultado, cancelamento e fase
    não cancelável; duplo clique, fechamento, refresh em todos os resultados,
    restart, percentual desconhecido, Secure Boot/DKMS, dependências multiarch,
    IDs alterados e recusa de remoções/downgrades/pacotes não confiáveis fora do plano.
26. **compileall:** `python3 -m compileall -q usr tests` passou.
27. **Probe real:** Introspect, CreateTransaction, GetAll, SetHints, Resolve e sinais
    PropertiesChanged/Package/Finished; resultado FINISHED, exit 1, com ID real
    de intel-microcode. Nenhum import proibido. O probe proíbe InstallPackages e
    RemovePackages, inclusive com SIMULATE.
28. **Nenhuma mutação real pelo Codex:** nenhum driver instalado/removido,
    nenhum módulo alterado, nenhuma alteração de Secure Boot/MOK ou reinício.
    A Qt oficial não executa sudo/pkexec/APT/dpkg diretamente, nem helper root próprio.
29. **Build:** `dpkg-buildpackage -us -uc -b` passou e produziu o nome esperado.
    Warnings herdados: nível de compatibilidade debhelper 9 obsoleto.
30. **Lint:** Lintian e desktop-file-validate terminaram com código 0 e sem saída.
    Testes offscreen podem emitir `propagateSizeHints`, limitação do plugin de teste.
31. **dpkg-deb -I:** Package `mainuan-gestao-drivers`, Version `0.2`, Architecture
    `all`; dependências PyQt6/PackageKit e GTK legado preservadas.
32. **dpkg-deb -c:** executável oficial Qt e GTK legado, módulos execution/safety,
    backend, desktop, ícones, traduções e manpages presentes. Sem bytecode nem
    executáveis públicos mintdrivers/mintdrivers-qt. Módulos Python do arquivo
    foram comparados byte a byte com o checkout.
33. **Git:** diff --check sem erros; árvore contém somente alterações desta fase
    para revisão. Artefatos de build e identidade desktop temporária foram limpos.
34. **GUI/limitações:** verificação nativa Plasma/Wayland, título/app ID corretos,
    Noto Sans do sistema, loading, zero dispositivos, redimensionamento e fechamento
    normais. Modo fictício validou seleção, confirmação, duas etapas simuladas,
    progresso, scroll e seleção atualizada; transporte D-Bus foi bloqueado nesse teste.
    Sem imports Gtk/Gdk/GdkPixbuf/XApp/PackageKitGlib/GLib/Gio e sem warnings de
    QSettings/portal nas verificações finais. Para testar o checkout sem instalar
    no host, a identidade desktop foi registrada temporariamente com NoDisplay
    e depois removida. O pacote já traz o launcher oficial visível.
    Hardware real e autorização mutante do Plasma precisam de teste manual na VM.
    MOK definitivo, ativação Broadcom e proteção contra encerramento forçado da
    sessão/processo continuam pendentes. Simulação não elimina corridas com operações
    externas de pacotes nem garante rollback. Casos que exigem remoções adicionais
    ou dependências não verificáveis são recusados conservadoramente.
35. **Roteiro completo da VM:** [beta-0.2-testing.md](beta-0.2-testing.md), incluindo
    estado anterior/posterior, instalação do aplicativo, modo fictício, seleção
    compatível, confirmação, PolicyKit, progresso, cancelamento, logs e remoção.
    Não é necessário instalar um driver incompatível para testar uma VM sem hardware.

## Arquivos Criados

```text
docs/beta-0.2-report.md
docs/beta-0.2-testing.md
tests/test_driver_execution.py
tests/test_driver_execution_ui.py
tests/test_driver_safety.py
usr/lib/mainuan/mainuan-gestao-drivers/mainuan_drivers/backend/transactions/execution.py
usr/lib/mainuan/mainuan-gestao-drivers/mainuan_drivers/backend/transactions/safety.py
```

## Arquivos Alterados

```text
README.md
debian/changelog
debian/control
debian/docs
docs/qt-transactions.md
mainuan-gestao-drivers.pot
makepot
po/mainuan-gestao-drivers-pt_BR.po
tests/test_mainuan_identity.py
tests/test_packagekit_transactions.py
usr/lib/mainuan/mainuan-gestao-drivers/mainuan_drivers/__init__.py
usr/lib/mainuan/mainuan-gestao-drivers/mainuan_drivers/backend/drivers.py
usr/lib/mainuan/mainuan-gestao-drivers/mainuan_drivers/backend/transactions/models.py
usr/lib/mainuan/mainuan-gestao-drivers/mainuan_drivers/backend/transactions/packagekit.py
usr/lib/mainuan/mainuan-gestao-drivers/mainuan_drivers/backend/transactions/planner.py
usr/lib/mainuan/mainuan-gestao-drivers/mainuan_drivers/qt/application.py
usr/lib/mainuan/mainuan-gestao-drivers/mainuan_drivers/qt/main_window.py
usr/share/man/man1/mainuan-gestao-drivers.1
```

O relatório é documentação de revisão no checkout; os módulos e o roteiro da VM
estão no pacote. O domínio gettext permanece mainuan-gestao-drivers; POT e pt_BR
foram atualizados, preservando os demais catálogos. GPL-2.0-or-later, copyrights
e créditos do Linux Mint permanecem intactos. A única ocorrência operacionalmente
inativa de live media observada é uma entrada histórica do changelog.
