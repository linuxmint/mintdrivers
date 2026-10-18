# Politica de acompanhamento upstream

Antes de cada beta:

1. Executar `git fetch upstream` e comparar commits Mint com a base registrada.
2. Registrar versao instalada/candidata de ubuntu-drivers-common.
3. Conferir commits Canonical relevantes e issues/PRs Mint abertas.
4. Classificar UI, regras, NVIDIA, Broadcom, Secure Boot/MOK, packaging,
   traducao e bugfixes; registrar decisao/evidencia em docs/upstream-audit-VERSAO.md.
5. Portar semanticamente apenas regras relevantes, com testes de regressao.
6. Priorizar o contrato do UDC instalado, isolando APIs nao garantidas em adapters.

Nunca fazer merge automatico para sincronizar. Recomendacao/compatibilidade GPU
pertencem ao UDC: nao sobrescrever pins nem interpretar novamente seu JSON OEM.
PR nao merged nao e comportamento validado. Nao alterar master, publicar tags ou
executar mutacoes de driver/MOK durante a auditoria. Preservar creditos/licenca.
