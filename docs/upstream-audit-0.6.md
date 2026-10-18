# Auditoria antes do beta 0.6

2026-10-18. Branch port/kubuntu-26.04. Base limpa
`954796f65a7956343ff102414a27b18cbd90403a`, checkpoint local do Qt-only 0.5.
Baseline: 279 testes, todos passaram. Nao houve push/merge/tag/release.

## Upstreams

git fetch upstream, git log master..upstream/master e git diff --stat executados:
sem delta Mint, HEAD `5c8046c00daf1391260093de251a9fffa2e540d7`.
Canonical consultado por ls-remote: HEAD
`ffb948b95f7c85d5a92275a9aaa53b6d9e2e2453`, igual ao 0.5.
**Nenhuma mudanca funcional upstream** a portar. UI/regras/NVIDIA/Broadcom/
Secure Boot/MOK/packaging/traducoes/bugfix: sem delta desde a ultima auditoria.
[Mint](https://github.com/linuxmint/mintdrivers),
[Canonical](https://github.com/canonical/ubuntu-drivers-common/commit/ffb948b95f7c85d5a92275a9aaa53b6d9e2e2453).
As decisoes anteriores para issues Mint permanecem; nao copiar PR nao merged,
nao adicionar DisplayLink/EVDI, enrollment ou politica GPU propria.

UDC instalado/candidato: `1:0.10.9`, Ubuntu resolute/main. API local fornece
from_distro booleano por opcao, nao source textual. Preservar source se aparecer
em outra capability, com fallback from_distro; ausencia/desconhecido = UNKNOWN.
recommended continua independente da origem. APT candidate determina versao e
origins; nao ordenar versions nem ler sources.list para adivinhar repositorios.
Pacote instalado e candidato sao dados distintos. Nao hardcode PPAs.

## Prebuilt e fontes de terceiros

Trust do repositorio APT e confianca de assinatura de modulo no firmware sao
coisas diferentes. Permitir candidates third-party confiaveis no PackageKit
(ONLY_TRUSTED ja aceita repositorios configurados e autenticados). Nao relaxar
Secure Boot por haver um PPA nem classificar third-party como DKMS.
Compatibilidade prebuilt (kernel/pacote APT conhecido) sera separada da evidencia
de assinatura prebuilt Ubuntu ja auditada. Prebuilt third-party pode funcionar
com Secure Boot desligado; com firmware ativo/desconhecido e assinatura nao
comprovada, mostrar blocker especifico, nao declarar todo PPA inseguro.

## Live Session: evidencia Ubuntu local

Nao havia deteccao Live no cliente Qt. Casper nao esta instalado no host;
apt-cache policy oferece **26.04.2**. Para auditar o pacote realmente disponivel,
foi baixado do arquivo Ubuntu, conferido o SHA256 do APT e extraido somente em
/tmp, sem instalar/executar scripts. SHA256:
`66596b928acefe05d33a144a27df71df51c631559ec8cfb672a174618f5514d8`.
[Pacote Ubuntu](https://archive.ubuntu.com/ubuntu/pool/main/c/casper/casper_26.04.2_amd64.deb).
O endpoint de source Launchpad nao respondeu ao leitor web; evidencia principal
e o pacote de distribuicao com checksum conferido.

scripts/casper monta raiz overlay com upperdir/workdir /cow; casper-bottom/12fstab
declara overlay como raiz. boot=casper identifica o fluxo de initramfs Live,
inclusive persistencia. Nao usar usuario/hostname nem mera instalacao do casper.
Probe read-only: /proc/cmdline + /proc/self/mountinfo; boot=casper/boot=live ou
raiz overlay com evidencia /cow => LIVE_SESSION. Raiz persistente conhecida e
ausencia de boot Live => INSTALLED_SYSTEM. Falha, formato desconhecido ou overlay
sem evidencia conclusiva => UNKNOWN, conservadoramente sem mutacao de drivers.
No host: raiz ext4 em bloco e boot normal, logo sistema instalado.
Nenhuma particao sera montada ou sistema alvo alterado.

## Migracao e escopo

Manter rm_conffile com limite 0.5~: o limite compara a versao antiga, portanto
upgrade direto 0.4 -> 0.6 continua coberto; 0.5 ja removeu o conffile. Nao
reintroduzir payload sudoers, helper ou action Polkit. Upgrade/purge somente VM.
Melhorias restritas a modelos de origem, sessao/UX, acessibilidade, logging e
diagnostico local opt-in. Sem teste proprio de Internet; o teste Mint contra
archive.ubuntu.com/socket/443 ja saiu com GTK e nao sera restaurado.
