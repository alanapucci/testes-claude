# Rotina do Bebê

App local de rastreamento de rotina (mamadas, sonecas, banho) que compara
o que está sendo registrado com a rotina-alvo e o cronograma de transição
de 10 dias, com alertas contextuais, visão da agenda de trabalho do dia e
um contador de dias seguidos dentro da margem de 15 minutos.

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

## Primeiro uso

1. Abra a aba **Config** e defina a data de início do "dia 1" do
   cronograma de transição de 10 dias. Os alvos diários (limite da
   soneca da tarde, início da rotina noturna, meta de dormir) são
   calculados automaticamente a partir dessa data.
2. Na aba **Hoje**, use os botões de 1 toque para registrar peito,
   mamadeira, banho e início/fim de soneca — sem digitar nada.
3. Acompanhe a tabela "Meta x Real" e os alertas que aparecem quando algo
   sai do esperado.
4. Adicione os compromissos de trabalho do dia (só horário + título) para
   ver se colidem com os horários de sono reais.
5. Na aba **Semana**, veja o contador de dias seguidos dentro da margem
   de 15 minutos e o resumo dos últimos 7 dias.

## Premissas assumidas na lógica (ajustáveis em `routine.py`)

- O horário-alvo de "acordar de vez" é sempre 08:00, em todos os dias do
  cronograma (a tabela de transição fornecida não varia esse horário).
- A partir do dia 11, mantém-se o mesmo alvo dos dias 9–10 (fase final
  do cronograma de 10 dias).
- "Início da rotina noturna" real é detectado pelo horário do banho à
  noite; se não houver banho registrado, usa a primeira mamada da noite.
- Soneca da tarde = sessão de sono que termina entre 12h e 19h.
  "Acordar de vez" = sessão de sono que termina entre 5h e 11h.
- Um dia só conta para o contador de consistência se os 4 marcos
  (acordar, fim da soneca da tarde, início da rotina noturna, dormir)
  tiverem sido registrados e todos dentro de ±15 min do alvo.

## Estrutura do projeto

```
baby-routine-app/
  server.py     servidor HTTP (biblioteca padrão do Python, sem deps)
  routine.py    cronograma de transição, alertas, comparação, streak
  db.py         acesso ao SQLite
  static/       frontend (HTML/CSS/JS puro, sem build)
  data.db       banco de dados local (criado automaticamente, ignorado no git)
```
