# ADR 0004: Operação Desassistida (Modo Noturno) e Isolamento de Input

## Status
Aceito

## Contexto
O robô roda num PC Windows utilizando o LDPlayer. Sessões de varredura (extração) demoram horas, e o usuário relatou que o emulador "roubava o cursor" do mouse físico durante os cliques automáticos, impossibilitando o uso da máquina para outras tarefas simultâneas, forçando a captura a ser estritamente "noturna". Além disso, o usuário assumia que não poderia minimizar a janela, sob risco de quebrar a raspagem.

## Alternativas Consideradas e Veto
1. **WSL2 (Subsistema Linux):** Considerou-se mover todo o ambiente Python para o WSL para tentar gerar um isolamento do ambiente (janela fantasma X11/Wayland).
   - **Veto Arquitetural:** Adicionar WSL causaria enorme fricção, precisando expor a porta do daemon do ADB do Windows para o Linux via ponte TCP, bagunçando os diretórios dos arquivos M3U (C:\ vs /mnt/c/). Além disso, o WSL **não resolve o problema real**, pois a janela do emulador no Windows é quem dita o _lifecycle_ da renderização.
2. **Bibliotecas de Mouse (PyAutoGUI):** Rejeitado. O robô já utiliza ADB 100% nativo.

## Decisão e Constatação Técnica

### 1. Correção do Mito do Isolamento (ADB Input)
O comando `adb shell input tap x y` **não tem relação nenhuma** com o mouse físico do Windows. Ele injeta eventos sintéticos direto no kernel do Android virtualizado.
- **Causa Raiz do Roubo de Cursor:** O LDPlayer possui uma feature de usabilidade chamada "Mouse Passthrough" (ou sincronização de cursor), que força o mouse físico do Windows a pular para o ponto onde toques virtuais acontecem, tentando unificar a UX de jogos.
- **Solução (Zero Code):** Basta desmarcar/desligar essa opção nas engrenagens da barra lateral do LDPlayer. O script ADB continua a clicar perfeitamente enquanto o mouse do Windows fica 100% livre nas mãos do usuário.

### 2. O Mito de Minimizar
Acreditava-se que minimizar a janela quebraria a captura porque o ADB precisaria de uma tela "visível". Na verdade, o ADB lê a SurfaceFlinger virtual (independente de estar no monitor). A quebra só ocorre se o SO hospedeiro (Windows) congelar o processo do LDPlayer para poupar bateria, ou se o ciclo de vida do próprio Android pausar o Player do filme ao não se sentir "em primeiro plano".
- **O Teste:** O usuário testou iniciar um playback no "Every Cine" e minimizar o LDPlayer para a barra de tarefas.
- **O Resultado:** O áudio **continuou tocando perfeitamente**, o que prova que a Activity do Player não faz _pause_ em background e o LDPlayer não congela _threads_ nativas.
- **Conclusão:** O usuário **PODE minimizar** a janela do LDPlayer na barra de tarefas do Windows. A extração vai fluir de forma 100% invisível (fantasma) e limpa. (O uso de Desktops Virtuais foi catalogado apenas como super-fallback).

## Consequências Code-base
Para fechar o pacote de UX noturna:
- Foi criada a flag CLI `--modo-noturno`. Quando ativada, ela contrai o relatório gigantesco no terminal para apenas 2 linhas compactas, permitindo checagem matinal limpa, sem varrer o console inteiro.
- Um sensor de timeout (`_TIMEOUTS_AUDIO_SEGUIDOS`) foi adicionado a `aguardar_audio_iniciar`. Se por alguma peculiaridade obscura o minimizar do LDPlayer congelar o app no futuro (gerando múltiplos timeouts de som seguidos), o log avisará proativamente o usuário.

*Aprovado na rodada v7.2*
