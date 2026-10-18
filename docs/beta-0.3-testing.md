# Validacao do beta 0.3 na VM

Antes de testar, registrar `ubuntu-drivers devices`, `uname -r`,
`apt-cache policy ubuntu-drivers-common`, `mokutil --sb-state` (se UEFI) e os
pacotes de driver instalados. Ausencia de drivers adicionais nesta VM e valida.
Nao instalar artificialmente drivers NVIDIA/Broadcom incompativeis.

```bash
sudo apt install ./mainuan-gestao-drivers_0.3_all.deb
mainuan-gestao-drivers
mainuan-gestao-drivers test
```

Na execucao real, verificar Wayland, carregamento, estado vazio e fechamento.
No modo ficticio, usar o seletor de cenarios, selecionar a opcao recomendada e
abrir a previa. Percorrer os 13 cenarios de seguranca/NVIDIA/Broadcom e o geral.
Conferir que warnings nao bloqueiam, mas headers ausentes e DKMS com Secure Boot
ativo/desconhecido desabilitam Aplicar e explicam a razao. MOK enrolled tambem
permanece bloqueado: sozinho nao comprova a assinatura do modulo futuro.

Secure Boot + prebuilt deve permitir simulacao; MOK pending deve orientar
MokManager/reboot. Broadcom com Secure Boot desligado e headers presentes deve
simular e indicar reboot. Nenhum cenario ficticio consulta APT/firmware do host
nem envia transacoes D-Bus. Redimensionar janela/dialogos e verificar o scroll.

Com hardware realmente compativel, conferir a lista concreta de pacotes e a
secao Verificacao do sistema antes de confirmar. A autorizacao pertence ao
PackageKit/PolicyKit. Nunca desabilitar Secure Boot para satisfazer este beta.
Depois de qualquer resultado, conferir a nova deteccao; pacote instalado nao e
prova de modulo ativo. Nao ha reboot, enrollment ou rollback automatico.
Codex nao executa esse teste real de mutacao.

O motor PackageKit pode ser testado separadamente com o probe hello, seguindo
`tests/manual/README.md` no checkout. Esse probe nao foi modificado para DKMS e
nao e instalado no pacote. GTK e helper Broadcom permanecem LEGACY ONLY.

Limitacoes: sem validacao criptografica de modulo/binding em hardware; sem fluxo
de enrollment MOK; certificados com configuracao DKMS dinamica retornam UNKNOWN;
headers do kernel em uso sao verificados sem instalacao implicita. Kernel mais
novo disponivel gera aviso; nao se faz upgrade do sistema. Testar em hardware
os provedores prebuilt reais, variantes OEM, Secure Boot e firmware MokManager.

```bash
sudo apt remove mainuan-gestao-drivers
```

Nao ha scripts de remocao agressiva de dependencias ou alteracao de firmware.
