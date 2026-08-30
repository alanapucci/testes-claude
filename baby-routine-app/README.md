# Rotina da Família

App local de rastreamento da rotina diária da família: bebê (mamadas,
sonecas, banho), Rapha de 3 anos (soneca, banho), checklist da casa,
horário de dormir das crianças e rotina pessoal da mãe — tudo comparado
com a rotina-alvo do dia, com alertas contextuais e um contador de dias
seguidos dentro da meta.

Roda inteiramente no seu Mac, sem instalar nada além do Python (que já
vem no macOS) e sem conta/login. Não envia dados a nenhum servidor
externo.

## Sobre "sincronizar via Remote Control"

O Remote Control do Claude Code sincroniza *sessões do Claude Code* entre
dispositivos — não é um mecanismo para sincronizar dados de um app entre
o Mac e o iPhone. Como o pedido era rodar local e sem login, a forma que
efetivamente funciona é: o Mac roda o servidor e guarda os dados; o
iPhone acessa o mesmo servidor pelo navegador, na mesma rede Wi-Fi. Os
dois dispositivos sempre veem os mesmos dados (é o mesmo banco no Mac),
sem precisar copiar nada manualmente.

## Como rodar no Mac

Não precisa instalar dependências — só Python 3 (o macOS Big Sur já tem).

```bash
cd baby-routine-app
python3 server.py
```

Isso mostra algo como:

```
Neste Mac:        http://localhost:8420
No iPhone (mesma rede Wi-Fi): http://192.168.x.x:8420
```

- No Mac: abra `http://localhost:8420` no navegador.
- No iPhone: conecte na **mesma rede Wi-Fi** do Mac e abra o endereço
  `http://192.168.x.x:8420` mostrado no terminal, no Safari. Dica: use
  "Adicionar à Tela de Início" no Safari para abrir como um app, em tela
  cheia.

Deixe o terminal com `server.py` rodando enquanto usa o app. Se fechar o
terminal ou o Mac dormir, o servidor para e o iPhone perde a conexão até
rodar de novo.

Os dados ficam salvos em `baby-routine-app/data.db` (SQLite), no próprio
Mac.

## Abas do app

- **Geral**: visão do dia inteiro — status do bebê, status do Rapha, %
  da casa feita, botão de 1 toque para "todas as crianças na cama até
  21h" (com alerta se passar do horário sem marcar) e para "rotina de
  cuidados pessoais feita", além do contador de streak.
- **Bebê**: registro de peito/mamadeira/banho/soneca, meta x real,
  agenda de trabalho do dia e linha do tempo.
- **Rapha**: registro de banho/soneca (sem mamada), meta x real e linha
  do tempo, com alvo fixo (não segue o cronograma de transição do bebê).
- **Casa**: checklist dos 9 itens do dia (básico, cozinha, 3 quartos, 2
  banheiros, varanda, sala), cada um marcável com 1 toque, com barra de
  progresso.
- **Semana**: contador de dias seguidos dentro da meta (agora
  considerando bebê + Rapha + casa + horário de dormir + rotina pessoal
  juntos) e resumo dos últimos 7 dias, com o que faltou em cada dia.
- **Config**: data de início do cronograma de transição do bebê e
  tabelas de referência dos alvos.

## Primeiro uso

1. Abra a aba **Config** e defina a data de início do "dia 1" do
   cronograma de transição de 10 dias do bebê. Os alvos diários (limite
   da soneca da tarde, início da rotina noturna, meta de dormir) são
   calculados automaticamente a partir dessa data. O Rapha não precisa
   de configuração — o alvo dele é fixo.
2. Nas abas **Bebê** e **Rapha**, use os botões de 1 toque para
   registrar os eventos do dia — sem digitar nada.
3. Na aba **Casa**, toque em cada item conforme for feito.
4. Na aba **Geral**, marque "crianças na cama" e "rotina pessoal" quando
   acontecerem, e acompanhe os alertas e o resumo do dia.
5. Na aba **Semana**, veja o contador de dias seguidos dentro da meta.

## Premissas assumidas na lógica (ajustáveis em `routine.py`)

- O horário-alvo de "acordar de vez" do bebê é sempre 08:00, em todos os
  dias do cronograma de transição.
- A partir do dia 11 do cronograma do bebê, mantém-se o mesmo alvo dos
  dias 9–10 (fase final).
- O Rapha (3 anos) não está em transição: usa alvo fixo diário — fim da
  soneca da tarde até 18:00, banho às 18:00, dormir por volta das 20:30
  — tirado da rotina-alvo do dia inteiro da família.
- "Início da rotina noturna" (bebê) é detectado pelo horário do banho à
  noite; se não houver banho registrado, usa a primeira mamada da noite.
- Soneca da tarde = sessão de sono que termina entre 12h e 21h.
  "Acordar de vez" (bebê) = sessão de sono que termina entre 5h e 11h.
- "Todas as crianças na cama" tem prazo fixo às 21:00 — feito só conta
  como "no horário" se marcado até esse horário; passar das 21h sem
  marcar gera um alerta.
- "Rotina de cuidados pessoais" é um item sim/não simples, sem detalhar
  os passos.
- Um dia só conta para o contador de consistência combinado se: o bebê
  cumpriu os 4 marcos dele dentro de ±15 min, o Rapha cumpriu os 3
  marcos dele dentro de ±15 min, os 9 itens da casa foram todos feitos,
  as crianças foram para a cama até as 21h, e a rotina pessoal foi
  marcada como feita.
- O checklist da casa e a agenda de trabalho não têm data de expiração —
  ficam disponíveis para qualquer dia consultado.

## Estrutura do projeto

```
baby-routine-app/
  server.py     servidor HTTP (biblioteca padrão do Python, sem deps)
  routine.py    cronograma do bebê, alvo do Rapha, casa, flags, streak
  db.py         acesso ao SQLite
  static/       frontend (HTML/CSS/JS puro, sem build)
  data.db       banco de dados local (criado automaticamente, ignorado no git)
```
