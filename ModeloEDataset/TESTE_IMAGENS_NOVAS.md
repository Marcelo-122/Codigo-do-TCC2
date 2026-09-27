# Teste com imagens novas (nunca usadas no treino)

Teste com 4 imagens da pasta `Imagens_2/Imagens_teste_2/`, adicionadas depois
do treino e **nunca usadas** em nenhuma etapa — nem no dataset Kaggle, nem no Dryad, nem no
fine-tuning de domínio. São fotos limpas de hidrômetros chineses (marca/modelo/fonte de
dígito completamente diferente dos medidores russos/Cirílicos do Kaggle/Dryad e das fotos
de domínio usadas antes) — um teste de generalização pra um estilo de medidor nunca visto.

Gerado por `testar_imagens_novas.py`, reaproveitando `modelo_digito.tflite` já treinado
(sem re-treinar nada). `Imagens_2/` original tem ~150 fotos (pasta local do usuário, não
versionada por completo) — só as 4 imagens realmente usadas neste teste ficam
no repositório, em `Imagens_2/Imagens_teste_2/`.

> **Sobre a pasta `Imagens_2/Imagens_teste_2_ESP32/`** (fotos reais tiradas pela ESP32CAM,
> de um monitor exibindo essas mesmas imagens de hidrômetro): tentei calibrar caixas de
> recorte pra 2 delas, mas a rotação da janela de dígitos nessas fotos específicas exigiria
> bem mais tempo de calibração manual pra ficar confiável — descartei essas amostras em vez
> de arriscar um recorte mal alinhado (mesmo critério usado no resto do projeto). Fica como
> próximo passo.
>
> Uma sexta imagem de referência (`20221221_00283.jpg`, "00764") também foi descartada
> pelo mesmo motivo: a janela de dígitos segue uma leve curva ao longo do mostrador que o
> recorte retangular + fatiamento em largura igual não consegue alinhar direito (cada
> célula pega pedaço de dois dígitos vizinhos) — o número que sairia dali mediria erro de
> recorte, não erro do modelo.

## Resumo

| Métrica | Valor |
|---|---|
| Fotos com leitura 100% correta | 2/4 (50%) |
| Dígitos individuais corretos | 20/22 (91%) |

## Resultado por imagem

| Arquivo | Categoria | Real | Previsto | Leitura | Dígitos certos | Imagem |
|---|---|---|---|---|---|---|
| 20220515025423_T1iyhTBjCi1RCvBVdK-000-00282.1296.jpg | referencia_limpa | 00282 | 00282 | ✅ | 5/5 | [ver](dataset/teste_imagens_novas/ref_00282_predicao.png) |
| 20221126_01576.jpg | referencia_limpa | 00399 | 00399 | ✅ | 5/5 | [ver](dataset/teste_imagens_novas/ref_00399_predicao.png) |
| 20221221_01143.jpg | referencia_limpa | 027535 | 027532 | ❌ | 5/6 | [ver](dataset/teste_imagens_novas/ref_027535_predicao.png) |
| 20221221_01471.jpg | referencia_limpa | 021235 | 021234 | ❌ | 5/6 | [ver](dataset/teste_imagens_novas/ref_021235_predicao.png) |

## Metodologia e limitações

- As caixas de recorte da janela de dígitos foram calibradas **manualmente** por imagem
  (mesma técnica usada no resto do projeto — sem máscara de segmentação automática
  disponível pra essas fotos novas), depois divididas em N fatias de largura igual.
- Amostra pequena e escolhida a dedo entre as imagens mais legíveis disponíveis em
  `Imagens_2/` (que tem ~150 fotos no total) — não é uma amostra aleatória nem exaustiva,
  então a taxa de acerto aqui não deve ser lida como "a" acurácia do modelo, só como mais
  um ponto de evidência, complementar ao [RESULTADOS.md](RESULTADOS.md).
- Esta amostra cobre só condição limpa/frontal — não inclui a degradação real da câmera
  ESP32CAM (isso já foi testado separadamente em [RESULTADOS.md](RESULTADOS.md) e
  [verificar_predicoes_dominio.py](verificar_predicoes_dominio.py), mas com medidores que
  entraram no fine-tuning, não com estes daqui).
