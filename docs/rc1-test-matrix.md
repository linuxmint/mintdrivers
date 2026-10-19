# Matriz de validacao - 1.0 RC1

Data: 2026-10-18. Base db53a5ef5bfdbe76e08e35dc68dbc8bdba8e439d.
Ambiente disponivel: Mainuan/Kubuntu resolute, Plasma/Wayland, kernel
7.0.0-38-generic, UDC 1:0.10.9, BIOS sem EFI e sem driver adicional elegivel.
Nao confundir evidencias fake e read-only com instalacao real de driver.

| Teste | Automatizado/Manual | Ambiente | Resultado | Bloqueia 1.0? |
| --- | --- | --- | --- | --- |
| Unit tests completos | Automatizado | Python/PyQt6 offscreen, caches/DBus fakes | 341 passed, 0 skipped, 0 failed; 329 anteriores preservados | Sim, se houver regressao |
| Planos e inputs adulterados | Automatizado | Fakes, inclusive Install/Remove | Rejeitados antes de qualquer chamada D-Bus | Sim |
| PackageKit read-only | Probe real automatizado | System bus do host | Introspect/CreateTransaction/Resolve/Package/Finished OK, nenhuma mutacao | Sim |
| Install/Remove/Cancel/AllowCancel/RequireRestart | Automatizado | Transporte e workflow fakes | OK, inclusive perda do daemon, erro e falha parcial | Sim |
| PackageKit mutation probe hello | Manual | VM, usuario normal e agente PolicyKit | NAO EXECUTADO pelo Codex; roteiro preservado, testes fake OK | Sim, precisa validar motor real na VM |
| Instalacao limpa do aplicativo | Manual | Snapshot VM limpo | PENDENTE; metadados/payload inspecionados apenas | Sim |
| Upgrade 0.4 -> RC1 | Manual + gate automatizado | Snapshot VM com conffile historico | PENDENTE VM; limite 0.5~ e hooks verificados | Sim |
| Upgrade 0.5 -> RC1 | Manual + gate automatizado | Snapshot VM 0.5 | PENDENTE VM; migracao preservada | Sim |
| Upgrade 0.6 -> RC1 | Manual + gate automatizado | Snapshot VM 0.6 | PENDENTE VM; ordenacao Debian testada | Sim |
| Purge apos instalacao/upgrades | Manual + auditoria | Snapshots VM | PENDENTE VM; sem script proprio agressivo | Sim |
| Qt/Wayland real e test | Smoke automatizado + imagens | Sessao Plasma/Wayland disponivel | OK; estado vazio real e 28 fixtures; sem GTK/GI | Sim, se regressao |
| HiDPI/janela pequena | Smoke/imagens | Qt scale 100/125/150/200% | OK no RC, inclusive 560x343 logicos a 200%; comandos visiveis e scroll | Sim, se comandos inacessiveis |
| Acessibilidade/teclado | Qt automatizado + manual | Offscreen/Wayland | Nomes/descricoes, Tab/ShiftTab/Space/Enter/Esc OK; leitor de tela humano PENDENTE | Sim para bloqueio de uso |
| PPAs/source/candidate/pinning | Automatizado | Cache APT e UDC fakes | OK, recomendado terceiros preservado, maior versao ignorada se nao candidata | Sim |
| PPAs realmente configurados | Manual read-only | VM com hardware/pacotes detectados | PENDENTE, nao alterar repositorios; host sem hardware elegivel | Nao pela ausencia de hardware; declarar limite |
| Live/UNKNOWN | Automatizado | Proc/mountinfo ficticios e controlador | Deteccao/previa/test permitidos; mutacao bloqueada/revalidada | Sim |
| ISO Live real | Manual | ISO Mainuan/Kubuntu de teste | PENDENTE; sem montagem/alteracao de sistema alvo | Sim para validacao da protecao real |
| Secure Boot prebuilt/DKMS | Automatizado + leitura real limitada | Mocks e host BIOS | Matriz OK; host corretamente UNSUPPORTED, nao teste SB enabled real | Falha logica sim; hardware indisponivel declarado |
| MOK correspondente/diferente/ausente/pendente | Automatizado | mokutil/config/certificados fakes | OK, somente a chave correta permite READY; nenhum enrollment | Falha logica sim; hardware indisponivel declarado |
| NVIDIA open/closed/server/pin/installed/active/reboot | Automatizado | Fixtures UDC/APT/sysfs | OK, recomendacao UDC nao reescrita | Falha logica sim; hardware real limitado |
| Broadcom DKMS/wl/reboot | Automatizado | Fixtures e sysfs temporario | OK, nenhum helper/modprobe | Falha logica sim; hardware real limitado |
| Hardware real adicional | Manual | Hardware elegivel indisponivel | COBERTURA LIMITADA, nao testado/falsificado | Revisao explicita do risco antes de final |
| Privilegios/subprocess/privacy | Auditoria + testes | Codigo runtime | Sem shell=True, helpers, senha ou mutacao MOK; allowlist diagnostico endurecida | Sim |
| Version/About/diagnostico/changelog | Automatizado | Python/Qt/dpkg | 1.0~rc1 coerente; 1.0~rc1 < 1.0 retorna 0 | Sim |
| Compileall/gettext | Automatizado | Arvore fonte | OK; pt_BR 199 traduzidas, sem mensagens ativas pendentes | Sim |
| Build/Lintian/desktop/conteudo Debian | Automatizado | debhelper13, pacote all | OK, 1.0~rc1/all; Lintian sem erros/warnings, gate Qt-only/migracao aprovado | Sim |

## Evidencias e observacoes

Logs de desenvolvimento locais: /tmp/mainuan-rc1-baseline.log,
/tmp/mainuan-rc1-tests-final.log, /tmp/mainuan-rc1-packagekit.log,
/tmp/mainuan-rc1-qt-100.log. Nao sao instalados nem enviados automaticamente.
Probe visual bloqueia metodos D-Bus modificadores. Erro RuntimeError no cenario
backend-error e intencional, nao traceback da execucao real.

O portal pode avisar no checkout porque org.mainuan.GestaoDrivers.desktop nao
esta instalado no host. Validar registro/menu na VM instalada; nao instalar
o pacote no host so para ocultar esse aviso. Nao reapareceu warning QSettings.

Resultado dos passos manuais NAO pode ser inferido de unit tests ou do sucesso
do build. Para registrar nova evidencia, anotar versao/ambiente/data e atualizar
a linha correspondente. Criterios finais em 1.0-release-criteria.md; comandos
em 1.0-rc1-testing.md. Esta matriz nao autoriza 1.0 final, tag ou publicacao.
