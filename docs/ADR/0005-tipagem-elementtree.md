# ADR 0005: Tipagem Segura e Falsy Elements em xml.etree

## Objetivo
Estabelecer um padrão seguro e definitivo de verificação de nil/null para nós da árvore de UI lidos pelo `xml.etree.ElementTree`, prevenindo falhas silenciosas de navegação no robô extrator.

## Contexto
Durante o Teste de Resiliência de Campo, a navegação primária falhou ao tentar localizar abas nativas (ex: "Filmes", "Séries") na tela Inicial. A causa raiz rastreada não foi uma falha do ADB, mas sim uma armadilha sintática do Python 3.9+ com a biblioteca `xml.etree.ElementTree`. 
Objetos `Element` no Python sobrescrevem o método `__bool__` (ou `__len__`). Consequentemente, um nó XML válido que **não possua nós filhos** (uma folha, como o botão da aba no UI dump) é avaliado sintaticamente como `False` em expressões booleanas (`if node:`). O código antigo utilizava `if n:` e `if not n`, o que fazia o robô tratar botões vazios encontrados como se não tivessem sido encontrados, acionando blocos nulos e pulando as abas.

## Solução
Foi executado um patch mínimo e cirúrgico em todas as avaliações de nós `Element` expostas na evidência do erro (como `_abrir_aba_por_texto`, `rodar_filmes`, `rodar_series`, etc.). 
- Troca de `if n:` para `if n is not None:`
- Troca de `if not n:` para `if n is None:`
- O mesmo para as variáveis `root`.

## Prevenção
A partir desta ADR, é estritamente **proibido** utilizar checagem de "truthiness" implícita (`if node:`, `if not node:`) para variáveis que armazenem referências a `ElementTree.Element`.
Toda verificação de existência na manipulação de DOM/XML deste projeto deve obrigatoriamente comparar contra a identidade `None` de forma explícita (`is None` / `is not None`).
