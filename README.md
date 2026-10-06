# Dashboard de chegadas internacionais — sarampo (BSB · Rio · SP)

Painel HTML autocontido com as chegadas internacionais de passageiros em Brasília, Rio de Janeiro e São Paulo,
a partir da programação prevista da ANAC (SIROS `/voos`). `atualizar.py` baixa, filtra e regenera o HTML.

## Rodar localmente

```bash
pip install -r requirements.txt
python atualizar.py                    # de hoje até 31/12 do ano corrente -> site/index.html
python atualizar.py --fim 2027-03-27   # outro fim de período
python atualizar.py --offline          # reprocessa só o cache em dados_brutos/
```

Leva ~5 min por 90 dias: a ANAC bloqueia requisições paralelas, então o script baixa dia a dia, com pausa de 3 s e
novas tentativas. Dias passados ficam em cache (`dados_brutos/`); hoje e o futuro são rebaixados a cada execução.
Se algum dia vier inválido, o script falha em vez de publicar dados incompletos.

## Publicar no GitHub Pages (uma vez)

1. Suba esta pasta para um repositório (branch `main`).
2. Em **Settings → Pages → Build and deployment → Source**, escolha **GitHub Actions**.
3. Em **Actions → Atualizar dashboard → Run workflow** para a primeira publicação.

Depois disso o workflow roda todo dia às 06:17 (Brasília) e a cada alteração em `atualizar.py`/`template.html`.
O HTML não é commitado; é publicado como artefato do Pages.

## Ajustes comuns (em `atualizar.py`)

- Países marcados por padrão: `INTERESSE_PADRAO` (códigos ISO-2).
- Nomes de companhias: `CIAS`; nomes de cidades: `CIDADE_PT`.
- Aeroportos de destino: `ALVOS`.

## Limites

- É programação prevista: atrasos, cancelamentos e voos extras não aparecem.
- A ANAC pode recusar IPs dos runners do GitHub. Se o workflow falhar com "sem resposta válida da ANAC",
  rode o `atualizar.py` em outra máquina (ou agende em um servidor próprio).
- A API diária só cobre o horizonte que a ANAC já publicou; datas mais distantes voltam vazias e o script acusa erro.
  O arquivo SSIM (`/api/ssimfile?ds_temporada=W26`) cobre até 27/03/2027 e pode ser usado para estender o período.
