# Probe manual PackageKit / PolicyKit (beta 0.2)

Somente para desenvolvimento na VM, em uma sessao Plasma com agente PolicyKit.
Execute no checkout, como usuario normal. Nao instale drivers incompativeis para
testar o motor. Este script nunca e instalado pelo pacote Debian.

O unico pacote permitido e `hello`. O transporte, os sinais, a resolucao previa,
os resultados, erros e cancelamento sao os de `PackageKitTransaction` da aplicacao.
`HelloPlans` e apenas uma fonte de planos fixos do teste, separada do planner de
drivers: nao cria dispositivos, nao altera o backend e nao implementa D-Bus.
APT e consultado somente para leitura, usando caches novos e o formatador de IDs
do backend. Nao ha chamadas de mutacao a APT/dpkg, senha propria ou helpers root.

## Teste A: cancelar autorizacao

```bash
python3 tests/manual/packagekit_mutation_probe.py install \
  2>&1 | tee -i packagekit-cancel.log
```

Confira candidato e ID; digite `INSTALAR hello`. Cancele o dialogo PolicyKit.
Esperado: `PASS: authorization cancelled`, `PASS: system unchanged`; hello ausente.
Se o sistema ja tiver uma autorizacao PolicyKit em cache, o dialogo pode nao
aparecer: o probe nao forca nem contorna a politica. Nesse caso, prossiga com a
remocao na mesma sessao e repita o teste de cancelamento em uma sessao sem essa
autorizacao. Nunca remova automaticamente um hello preexistente.

## Teste B: autorizar instalacao

```bash
python3 tests/manual/packagekit_mutation_probe.py install \
  2>&1 | tee -i packagekit-install-remove.log
```

Digite `INSTALAR hello`, autorize no PolicyKit e aguarde Finished e a verificacao
APT. Esperado: `PASS: hello installed through PackageKit`.
**Mantenha esse terminal aberto no prompt do Teste C.** Opcionalmente, execute
`hello` em outro terminal, sem privilegios; sua saida nao determina o sucesso.

## Teste C: autorizar remocao na mesma execucao

No prompt ainda aberto do Teste B, digite:

```text
remove
REMOVER hello
```

Autorize no PolicyKit quando solicitado. Esperado:
`PASS: hello removed through PackageKit`. O log do Teste B contem ambos os passos.
A remocao usa `allow_deps=False` e `autoremove=False` do codigo de producao.

Uma nova invocacao `...probe.py remove` e recusada deliberadamente: outro processo
nao pode provar que foi ele quem instalou o pacote. `installed_by_probe` so vive
na memoria desta execucao e so muda para True apos Finished com sucesso.
`full` oferece o mesmo fluxo guiado, com ambas as confirmacoes obrigatorias.
`resolve` executa somente a pre-checagem/resolucao, sem mutacao nem confirmacao.

Durante uma transacao, Ctrl+C usa o cancelamento de producao apenas quando
AllowCancel permite. `tee -i` mantem o log aberto ao receber Ctrl+C. Nao encerre o
terminal durante uma operacao critica. O
timeout defensivo e de 30 minutos por etapa; nao mata nem cancela PackageKit,
nao tenta limpeza automatica e informa o estado observado somente para leitura.
Um estado aparentemente ausente pode ainda mudar depois de um timeout.

Se houver erro, negacao, timeout ou desconexao, o probe nao faz novas tentativas
automaticas. Confira estado e logs; em particular, uma instalacao com resultado
desconhecido nao concede propriedade para remocao. Se o pacote permanecer,
**somente depois de confirmar que PackageKit terminou**, recuperacao manual na VM:

```bash
dpkg-query -W -f='${db:Status-Status}\n' hello
sudo apt remove hello
```

O ultimo comando e contingencia humana, nunca chamado pelo script. Nao ha
persistencia de propriedade entre execucoes. Nenhuma senha ou credencial e lida
ou registrada pelo probe. `--debug` acrescenta traceback aos erros de operacao.
