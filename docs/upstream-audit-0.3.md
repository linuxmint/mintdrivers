# Auditoria upstream antes do beta 0.3

Auditoria concluida em 2026-10-18, antes de alterar codigo do beta 0.3.
Base local: `d35d878faba7cfacc94d31ecb921c894d312412d`, checkpoint
`beta: establish 0.2 transaction baseline` (inclui o probe hello).
Branch: `port/kubuntu-26.04`. A arvore estava limpa apos o checkpoint.
Os 124 testes anteriores passaram em `unittest discover -s tests -v`.
Uma primeira execucao com `-q` terminou em SIGSEGV Qt; repetir/monitorar durante
a regressao, sem esconder essa ocorrencia nem eliminar testes.

## Linux Mint

Executados `git fetch upstream`, `git log --oneline master..upstream/master`
e `git diff --stat master..upstream/master`. Os dois ultimos nao tiveram saida.
`master` e `upstream/master` continuam em
`5c8046c00daf1391260093de251a9fffa2e540d7`.
[Repositorio original](https://github.com/linuxmint/mintdrivers).

Nao ha novos commits para classificar/portar: UI GTK/XApp, backend, NVIDIA,
Broadcom, Secure Boot/MOK, packaging, traducao e bugfix generico: **sem delta**.
Nenhum merge ou codigo de PR nao integrada sera importado. A GTK e seus
creditos permanecem; o helper Broadcom sera identificado como legado apenas.

Issues/PRs abertas conferidas tambem pela API GitHub (nao apenas indice de busca):

| Item | Decisao para 0.3 |
| --- | --- |
| [#109 PRIME/assinatura](https://github.com/linuxmint/mintdrivers/issues/109) | Incorporar a protecao contra falsa prontidao; adiar enrollment e validacao PRIME em hardware. O relato sobre Ubuntu nao prova que PackageKit conduz o mesmo fluxo. |
| [PR #107 WIP](https://github.com/linuxmint/mintdrivers/pull/107) | Incorporar semanticamente avisos contextuais e curtos; nao copiar a implementacao GTK nem recomendar desabilitar Secure Boot. Ainda aberta/nao merged. |
| [#103 aviso Secure Boot](https://github.com/linuxmint/mintdrivers/issues/103) | Incorporar preflight/estado, nao um dialogo generico bloqueando toda inicializacao. |
| [#100 regressao MOK](https://github.com/linuxmint/mintdrivers/issues/100) | Incorporar deteccao somente leitura; adiar enrollment. Nao classificar como resolvida pelo Ubuntu sem demonstracao no nosso transporte. |
| [#111 470/535/server](https://github.com/linuxmint/mintdrivers/issues/111) | Incorporar preservacao de server recomendado/instalado e oferta quando e a unica variante; nao criar tabela propria de GPUs/branches. UDC decide compatibilidade. |
| [#99 versao NVIDIA](https://github.com/linuxmint/mintdrivers/issues/99) | Disponibilidade e recomendacao delegadas aos repositorios/UDC; nao adicionar repositorios nem pacotes externos. |
| [#110 offline urllib](https://github.com/linuxmint/mintdrivers/issues/110) | Nao aplicavel a Qt: ela nao usa a verificacao urllib legada para autorizar uma transacao. |
| [#96 radeon/amdgpu](https://github.com/linuxmint/mintdrivers/issues/96) | Adiar: troca de modulos builtin nao e operacao PackageKit equivalente. |
| [#112 DisplayLink/EVDI](https://github.com/linuxmint/mintdrivers/issues/112) | Adiar explicitamente, fora do escopo e sem backend oficial integrado. |

Nao havia outra PR aberta alem de #107; nenhum novo patch Broadcom/DKMS merged
no Mint. Problemas de compilacao de pacotes continuam responsabilidade dos
pacotes Ubuntu: o preflight nao pode certificar compatibilidade de fontes DKMS.

## ubuntu-drivers-common

Comandos locais `apt-cache policy ubuntu-drivers-common` e
`dpkg-query -W ubuntu-drivers-common`: instalado/candidato **`1:0.10.9`**,
Ubuntu `resolute/main`. `mokutil` instalado/candidato **`0.7.2-2`**.
Upstream clonado para auditoria fora do repositorio, HEAD
`ffb948b95f7c85d5a92275a9aaa53b6d9e2e2453`.
[Upstream Canonical](https://github.com/canonical/ubuntu-drivers-common).
Changelog upstream mais recente: **`1:0.10.13`**, nao a versao instalada.

Auditado [03142a7](https://github.com/canonical/ubuntu-drivers-common/commit/03142a781218c7e8ed76f8e29eae94948438877a):
prioridade de configuracao custom/OEM, preservacao da serie recomendada,
variantes open, normalizacao da serie em point releases e runtimepm.
O 0.10.9 local usa `/etc/custom_supported_gpus.json` mas nao tem o novo lookup
OEM nem todos os ajustes de prioridade. **Nao fazer backport dessa logica no
Mainuan**: respeitar os flags devolvidos pelo UDC realmente instalado.
Nao ler custom_supported_gpus.json, nao inferir pin por versao de pacote,
nao escrever markers runtimepm. Regressao com fixtures dos resultados antigos
e novos, sem depender da versao numerica do UDC.

UDC local e upstream possuem `KernelDetection.is_running_kernel_outdated()`
retornando `(outdated, running, latest, requires_dkms)`. Kernel fora do formato
Ubuntu sinaliza necessidade de DKMS; metapacote atualizavel gera aviso, nao
atualizacao automatica. Usar somente esse metodo de leitura, com adapter pequeno,
validacao de retorno e fallback UNKNOWN. Nao chamar `get_kernel_update_warning`
(politica/saida CLI) nem metodos de instalacao. `--include-dkms` e opt-in da CLI,
nao prova de que a nossa GUI oferece enrollment MOK.

`system_device_drivers()` ja expoe recomendacao; o sorting desktop prefere
nao-server, mas isso nao justifica apagar server explicitamente recomendado.
Politica Mainuan prevista: flags UDC intocados; preservar variantes open/closed
e pacotes instalados; ocultar apenas server nao recomendado/nao instalado quando
existir alternativa desktop. Sem heuristica `>=560` e sem transferencia de flags.

`broadcom-sta-dkms` consta da allowlist UDC (LP #2013236); `bcmwl` e pacotes
transicionais devem ser classificados por dependencias APT, nao hardware proprio.
Qt nao usara o helper que descarrega/carrega modulos; informar reboot.

## Evidencia local DKMS/MOK e decisao de seguranca

Inspecionados `/usr/sbin/dkms`, `/etc/dkms/framework.conf`,
`/usr/lib/dkms/common.postinst` e `/usr/sbin/update-secureboot-policy` **sem executar
esses scripts**. DKMS aceita configuracoes shell em framework.conf e conf.d;
o default Ubuntu pode selecionar `/var/lib/shim-signed/mok/MOK.der`, enquanto
outras configuracoes usam `/var/lib/dkms/mok.pub`. Portanto nao assumir um
certificado fixo nem executar/sourcear configuracao shell para encontra-lo.
No beta, enrollment adequado so pode ser afirmado quando o certificado usado
for identificado inequivocamente e `mokutil --test-key` confirmar a inscricao;
caso contrario retornar UNKNOWN. Uma chave qualquer em `--list-enrolled` nao
prova que seja a chave de assinatura efetivamente usada pelo DKMS.

Operacoes planejadas de mokutil: `--sb-state`, `--list-new`, `--test-key` apenas
com certificado explicitamente verificado. Sem importacao, senha, geracao ou
alteracao de firmware. Ausencia/erro/saida inesperada => UNKNOWN (BIOS =>
UNSUPPORTED). A falta de mokutil deve ser tratada sem traceback; Recommends e
apropriado porque deteccao/prebuilt/BIOS continuam uteis sem ele.

Preflight deve distinguir dependencias reais DKMS, alternativas ambiguas e
prebuilt compativel com kernel, sem equiparar NVIDIA a DKMS. Verificar headers
para kernel relevante sem instala-los implicitamente. Secure Boot ativo ou
desconhecido + DKMS requerido/possivel sem cadeia de assinatura demonstrada =>
bloquear antes de qualquer remocao da troca. Mesmo MOK enrolled nao certifica
sozinho chave privada, assinatura ou modulo futuro: manter conservador se essas
garantias faltarem. Prebuilt so dispensa DKMS se o plano realmente nao o exigir.

Apos PackageKit Finished, nova deteccao e preflight devem separar pacote
instalado de modulo ativo. Reboot/MOK pendente e incerteza precisam aparecer;
nenhuma promessa de ativacao ou rollback atomico. BIOS e UEFI distintos.
Testes reais de mutacao/MOK e hardware NVIDIA/Broadcom ficam para a VM/hardware
do usuario, nao para a execucao Codex.

## Conclusao antes da implementacao

Auditoria concluida: nao ha codigo Mint novo a importar. Incorporar autoridade
da recomendacao UDC e adapter da API de kernel existente no pacote local; adiar
backport custom OEM, enrollment MOK e DisplayLink. Implementar protecoes e testes
somente agora, mantendo transacoes PackageKit, GTK legada e probe hello.

## Evidencias adicionais durante a implementacao

Consultas APT somente leitura confirmaram `broadcom-sta-dkms
6.30.223.271-29ubuntu1` com dependencia de dkms. `nvidia-driver-580` depende de
`nvidia-dkms-580`, mas pacotes linux-modules-nvidia podem fornecer esse nome com
Provides versionado: analisar apenas o nome da dependencia geraria falsos DKMS.
O preflight precisa considerar esses provedores e os efeitos resolvidos pelo
PackageKit, nao apenas disponibilidade de uma alternativa.

Nos modulos locais publicados pelo Ubuntu, `source_name` corresponde a
linux-restricted-modules e `origins` a Ubuntu confiavel. A implementacao exige
essas evidencias e o release exato do kernel; nao as confunde com validacao
criptografica de um modulo carregado. Headers locais incluem Makefile e
include/config/kernel.release; o segundo deve corresponder ao kernel em uso.
