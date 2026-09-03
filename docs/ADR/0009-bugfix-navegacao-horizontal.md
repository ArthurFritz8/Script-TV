# ADR 0009: Navegação Horizontal Ancorada (Anti-Truncamento e Resets)

## Objetivo
Solucionar o bug de re-clique (loop infinito) no algoritmo de navegação horizontal (carrosséis) do `robo_extrator.py`. O objetivo é impedir que o robô seja enganado por nomes truncados na interface (ex: `The Mortuary Assist...`) ou por resets silenciosos da interface (carrossel rebobinando após o botão Voltar).

## Contexto
O método anterior lia os cards visíveis na UI do Android e perguntava ao _Ledger_ de visitados se aquele nome exato já tinha sido processado. Contudo:
1. Nomes extensos são cortados graficamente com reticências pelo próprio Android (`TextView ellipsize="end"`).
2. O catálogo armazenava, corretamente, o nome completo extraído lá dentro da página de detalhes.
3. Quando o robô voltava para a lista, ele lia "Nome Truncado..." e não o achava na base (pois a base tinha o Nome Completo). Resultado: clicava de novo na mesma obra iterativamente.
Adicionalmente, se o carrossel movesse sorrateiramente para o início ao sofrer _resume_ da tela principal, o motor perdia a referência posicional.

## Solução
1. **Identidade Primária pelo `pHash`:** Modificamos a estrutura da chave de visitados para incorporar o _fingerprint_ gráfico do card (via `pHash` extraído de um screenshot obrigatório e em cache dinâmico da fileira inteira).
2. **Anti-Truncamento:** Adotamos a remoção literal de reticências antes de checagens secundárias.
3. **Monotonicidade com Âncora (`_ancoras_horizontais`):** Foi injetada uma âncora posicional que memoriza o Centro X (`cx`) do último card processado numa respectiva coordenada Y (a fileira). Sob hipótese alguma, o robô poderá eleger um novo alvo que possua um `cx` menor ou igual ao da âncora (salvo detecção afirmativa de reset).
4. **Detecção Geométrica de Reset:** Antes de travar, o código agora procura a âncora antiga via pHash na tela atual. Se a encontrar posicionada atrás de onde costumava estar, ele força sucessivos _swipes_ geométricos exatos até retomar ao ponto de interrupção, blindando completamente a estabilidade do scroll.

## Prevenção
- Nunca inferir estado horizontal estrito baseado em coordenadas fixas no pós-retorno de qualquer Activity; a UI do Android não provê garantias de preservação de estado da posição de ScrollView.
- A função de `foi_visitado` em cenários visuais precisará sempre honrar primeiramente a assinatura criptográfica/visual (`pHash`) ante a leitura estrita do nó XML nativo de texto.
