# Auditoria upstream - 1.0 RC1

Data: 2026-10-18. Branch: port/kubuntu-26.04.
Base limpa: db53a5ef5bfdbe76e08e35dc68dbc8bdba8e439d (beta 0.6 consolidado).
Baseline: 329 testes, 329 passaram. Sem checkpoint adicional necessario.

## Evidencia atual

Executados git fetch upstream, git log --oneline master..upstream/master e
git diff --stat master..upstream/master: ambos os deltas estao vazios.
Mint upstream/master: **5c8046c00daf1391260093de251a9fffa2e540d7**.
Canonical HEAD consultado com git ls-remote:
**ffb948b95f7c85d5a92275a9aaa53b6d9e2e2453**.
Nenhuma mudanca funcional upstream desde o beta 0.6; nenhum merge realizado.

dpkg-query -W e apt-cache policy ubuntu-drivers-common:
instalado/candidato **1:0.10.9**, Ubuntu resolute/main, prioridade 500.
O RC preserva o adapter/API realmente instalada, sem exigir campos presentes
somente no master Canonical. Recomendacao UDC e candidate/pinning APT continuam
autoridades, independentemente da origem do repositorio.

Fontes primarias:
- https://github.com/linuxmint/mintdrivers/commit/5c8046c00daf1391260093de251a9fffa2e540d7
- https://github.com/canonical/ubuntu-drivers-common/commit/ffb948b95f7c85d5a92275a9aaa53b6d9e2e2453
- https://api.github.com/repos/linuxmint/mintdrivers/issues?state=open&per_page=100

O leitor web nao acessou os endpoints; consulta Git e API HTTPS pelo ambiente
local confirmaram os hashes e a lista de issues/PRs abertas, sem mutacao remota.

## Classificacao e decisao de freeze

UI GTK/XApp, regras/backend, NVIDIA, Broadcom, Secure Boot/MOK, packaging,
traducao e bugfix generico: **sem delta de commits**. Nao portar nova feature.
Issues/PRs continuam como contexto, nao como implementacoes upstream validadas:

| Item Mint | Decisao no RC |
| --- | --- |
| #112 DisplayLink/EVDI | Adiar, fora do escopo e do freeze. |
| #111 535/470/server | Ja coberto por recomendacao UDC/server e regressao. |
| #110 falso offline | Nao aplicavel: nenhum teste archive.ubuntu.com no Qt. |
| #109 PRIME/assinatura | Manter preflight/chave exata; hardware real limitado. |
| #107 WIP aviso Secure Boot | Nao copiar PR nao merged; preflight ja existe. |
| #103 aviso Secure Boot | Ja coberto por estados/avisos/blockers especificos. |
| #100 enrollment MOK | Manter leitura; nenhum enrollment proprio no RC. |
| #99 NVIDIA mais recente | Candidate/pinning APT e recomendacao UDC, nao versao maxima. |
| #96 radeon/amdgpu | Adiar, nenhuma nova classe/regra de hardware. |

Os limites de hardware real continuam declarados. O freeze permite apenas
metadados/documentacao, regressao e correcao de bugs reproduzidos de hardening.
Nenhuma instalacao, remocao, modulo, MOK ou reboot sera executado no host.
