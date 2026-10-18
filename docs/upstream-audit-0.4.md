# Auditoria upstream antes do beta 0.4

Concluida antes da implementacao em 2026-10-18. Branch
`port/kubuntu-26.04`, base limpa `b57f5a47e6e72ac492ded90ff8675c0e60d75889`.
Checkpoint adicional desnecessario. Baseline: 187 testes passando.

## Mint e Ubuntu

Executados `git fetch upstream`, `git log --oneline master..upstream/master`
e `git diff --stat master..upstream/master`: sem delta. Mint permanece em
`5c8046c00daf1391260093de251a9fffa2e540d7`. Nenhum patch GTK/XApp, backend,
NVIDIA, Broadcom, Secure Boot/MOK, packaging, traducao ou bugfix a incorporar.
Nenhum merge realizado. [Mint upstream](https://github.com/linuxmint/mintdrivers).

Canonical foi consultado por `git ls-remote` e clone separado: HEAD
`ffb948b95f7c85d5a92275a9aaa53b6d9e2e2453`, igual a auditoria 0.3.
O ultimo commit e documental, nao altera runtime.
[Commit](https://github.com/canonical/ubuntu-drivers-common/commit/ffb948b95f7c85d5a92275a9aaa53b6d9e2e2453).
`dpkg-query -W` e `apt-cache policy` locais: UDC instalado/candidato
`1:0.10.9`, Ubuntu resolute/main, contra changelog upstream `1:0.10.13`.
As regras custom/OEM e recomendacoes continuam delegadas ao UDC instalado;
nao duplicar JSON, open/closed/server ou heuristica por numero de branch.

API auditada no detect.py local e remoto: `system_device_drivers()` usa o
sysfs path como chave para dispositivos modalias; plugins usam nome simples.
Preservar essa chave como `sys_path` quando estiver sob /sys, ou campo explicito
quando disponivel. `open_preferred` existe; nao substitui `recommended`.
Nao existe campo por-opcao `packages` nem `gpgpu_packages` nesta API, local ou
HEAD remoto. O identificador Python `packages` em funcoes internas nao e esse
contrato. Suporte opcional somente a metadados explicitos validos, sem chamar
CLI de instalacao ou copiar o resolvedor privado do UDC. Ausencia usa fallback
Mainuan + simulacao/resolucao PackageKit ja testados.

Revisitadas as issues [#109](https://github.com/linuxmint/mintdrivers/issues/109)
e [#100](https://github.com/linuxmint/mintdrivers/issues/100): incorporar apenas
evidencia especifica da assinatura e evitar falsa ativacao; enrollment continua
adiado. As decisoes 0.3 para #103/#107 (avisos contextuais), #111 (preservar
server recomendado), #112 (DisplayLink/EVDI fora do escopo) permanecem; nenhum
codigo de PR nao merged importado. GTK nao implementara recursos novos.

A API GitHub `issues?state=open&per_page=100` confirmou novamente #100, #103,
#107 (PR WIP), #109, #111 e #112 abertas; #99, #110 e #96 tambem continuam
abertas, com as mesmas decisoes documentadas no 0.3.

## DKMS e shim realmente instalados

`dkms 3.2.2-1ubuntu1`, `shim-signed 1.59+15.8-0ubuntu2`, `mokutil 0.7.2-2`,
`kmod 34.2-2ubuntu2`, `openssl 3.5.5-1ubuntu3.7`.
Lidos, nunca executados para descoberta, `/usr/sbin/dkms`,
`/usr/sbin/update-secureboot-policy`, `/etc/dkms/framework.conf`.

DKMS le framework.conf e depois conf.d/*.conf em ordem. Variaveis signing
aceitas: `sign_file mok_signing_key mok_certificate`. Configuracoes shell
dinamicas e sign_tool customizado nao podem ser comprovados pelo nosso parser:
retornar UNKNOWN. Parser somente de atribuicoes literais, sem source/eval.

`prepare_mok()` na versao auditada: sem mok_signing_key, distribuicao ubuntu*
usa `/var/lib/shim-signed/mok/MOK.priv` e `MOK.der`, sobrescrevendo inclusive
mok_certificate isolado. Com chave explicita, certificado explicito prevalece;
sem certificado, `/var/lib/dkms/mok.pub`. Outras distribuicoes conhecidas usam
`/var/lib/dkms/mok.key` e `mok.pub`. Nao assumir que ID_LIKE contendo ubuntu em
qualquer posicao equivale a ubuntu: reproduzir somente a selecao auditada do
identificador de distribuicao. Defaults ficam isolados em adapter restrito ao
comportamento local auditado; versoes/configuracoes desconhecidas degradam.

Chave privada: somente existencia/metadados, nunca abrir conteudo, passar a
comandos ou registrar caminho nos resultados/logs. Exigir chave e certificado
distintos, arquivos regulares, e ferramenta de assinatura padrao disponivel;
custom sign_file/sign_tool ou PKCS11 nao validados => UNKNOWN. Se faltar chave,
DKMS pode gerar outra e invalidar a prova do certificado: nao declarar READY.
Verificar tambem CONFIG_MODULE_SIG_HASH no auto.conf (ou .config) dos headers,
como faz prepare_signing(). Arvore de modulos customizada nao comprovada bloqueia.

Somente `mokutil --test-key <certificado-publico>` pode confirmar a MOK usada.
`--list-new` so indica pending correspondente se fingerprint SHA256 ou SHA1
completo coincidir com o certificado publico, calculado por openssl x509
somente leitura. Alguma MOK inscrita/pendente nao e prova. Stderr, erros,
comando ausente e saida desconhecida nao sao sucesso.

## Decisoes de seguranca 0.4

ENABLED + DKMS + certificado correto READY_ENROLLED + headers verificados:
permitir. UNKNOWN Secure Boot continua bloqueado; a confianca no firmware nao
foi estabelecida. Certificado ausente/nao inscrito/desconhecido: bloquear.
Pending correspondente continua bloqueado: nao demonstrado que o fluxo
PackageKit consegue construir/assinar sem interacao adicional. Mostrar aviso
MokManager, nao automatizar boot/enrollment. MOK nao e gerada nem importada.

Sysfs binding confirma familia de driver (nvidia/wl), nao versao de modulo ou
open/closed. Mudanca entre pacotes com o mesmo modulo requer reboot conservador;
nao declarar nova variante ativa pelo nome do modulo. Modinfo fornece evidencia
adicional de assinatura, nunca prova isolada de confianca. Genericos sem
relacao de modulo conhecida: ativacao nao verificada. Nova abertura apos reboot
le estado atual, sem conclusoes persistidas em QSettings.
Para DKMS com Secure Boot, comparar sig_key do modulo com Subject Key Identifier
do certificado publico (openssl x509 somente leitura). Ausencia/divergencia
degrada a ativacao a UNVERIFIED, sem invalidar a prova anterior de enrollment
necessaria para permitir a instalacao.

Recommends de openssl e kmod e apropriado: ausencia degrada a verificacao sem
impedir deteccao/prebuilt. Nenhuma dependencia PyPI ou helper privilegiado.
Auditoria concluida; implementar agora, sem mutacoes reais no host.
