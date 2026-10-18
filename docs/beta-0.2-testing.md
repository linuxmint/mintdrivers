# Validação manual do beta 0.2 na VM

Use uma VM de desenvolvimento com snapshot recuperável, não um sistema de
produção. Os testes automatizados e o probe não instalam nem removem drivers.
Os passos abaixo validam manualmente as mutações reais e o agente PolicyKit.

## Registrar o Estado Anterior

No terminal da VM, no diretório contendo o pacote:

```bash
ubuntu-drivers devices | tee drivers-before.txt
dpkg -l | grep -E 'nvidia|broadcom|microcode' | tee packages-before.txt
sudo apt install ./mainuan-gestao-drivers_0.2_all.deb
mainuan-gestao-drivers test 2>&1 | tee drivers-test.log
```

Confira a indicação de dados fictícios, múltiplos dispositivos, recomendado,
alternativas, builtin, instalado, código aberto/proprietário e microcode.
Selecione uma alternativa, confira a prévia, clique em Aplicar alterações e
confira os pacotes no diálogo beta. Confirme Aplicar: somente uma simulação
visual ocorre, sem PolicyKit nem alteração real. Confira progresso, rolagem,
redimensionamento, resultado e seleção atualizada após a detecção fictícia.

## Testar uma Alteração Real Compatível

```bash
mainuan-gestao-drivers 2>&1 | tee drivers-0.2.log
```

1. Aguarde a detecção. Nenhum driver adicional numa VM é normal: valide a tela
   vazia e encerre. Não invente hardware, não instale driver incompatível e não
   use dados fictícios para forçar uma operação real.
2. Se houver opção compatível oferecida pelo backend, selecione apenas essa
   opção. Confira a prévia de instalações e remoções.
3. Clique em Aplicar alterações. O backend é consultado novamente, IDs são
   resolvidos e dependências simuladas. Confira a lista completa no diálogo beta.
   Se o plano mudar após confirmar, revise a nova confirmação.
4. Confirme Aplicar. A autorização deve vir do agente PolicyKit do Plasma quando
   a política exigir. O aplicativo não solicita senha. A autorização pode estar
   em cache; não é garantido um diálogo a cada operação.
5. Observe estado, pacote atual e progresso; percentual desconhecido é
   indeterminado. Seleção, Atualizar e Aplicar ficam bloqueados. Cancelar só é
   oferecido quando permitido. Não mate processos ou o daemon.
6. Aguarde o resultado e a nova detecção. Confira o estado real. Se a remoção
   terminar e a instalação falhar, registre a falha parcial: não há rollback
   automático nem outras etapas ocultas.
7. Registre o requisito de reinício e decida manualmente quando reiniciar.
   Não há reinício ou carregamento de módulos automático.

Confira novamente:

```bash
ubuntu-drivers devices | tee drivers-after.txt
dpkg -l | grep -E 'nvidia|broadcom|microcode' | tee packages-after.txt
diff -u packages-before.txt packages-after.txt
journalctl -b -u packagekit.service --no-pager > packagekit-0.2.log
```

Compare os pacotes da confirmação com os instalados/removidos. Os registros
`/var/log/apt/history.log` e `/var/log/apt/term.log` ajudam no diagnóstico.
Revise informações privadas antes de compartilhar logs.

## Cenários Adicionais

- Negue/cancele autorização: confira mensagem específica, interface utilizável
  e nova detecção. Autorização negada não significa falha do driver.
- Cancele apenas numa fase permitida e aguarde o resultado. Tente fechar numa
  fase crítica: a janela deve impedir abandono da operação.
- Falha de rede/dependência deve informar erro e redetectar o estado real,
  sem autoremove, fallback APT direto ou restauração sem confirmação.
- Secure Boot habilitado/indeterminado com DKMS/MOK não suportado deve bloquear
  a operação. Drivers comprovadamente sem DKMS continuam elegíveis.
- Broadcom pode exigir reinício; o helper GTK não é usado pela Qt.

Não provoque falha parcial deliberadamente no host. Para validar esse caso com
pacotes reais, use somente VM recuperável e configuração compatível, com
planejamento específico; os testes unitários já simulam essa condição.

Para remover apenas o aplicativo:

```bash
sudo apt remove mainuan-gestao-drivers
```

Isso não desfaz alterações de drivers e não solicita remoção das dependências
do aplicativo. Não execute autoremove neste roteiro. Não é necessário remover
`mintdrivers`: os caminhos Mainuan foram separados no beta 0.1.
