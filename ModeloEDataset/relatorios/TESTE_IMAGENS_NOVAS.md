# Teste com imagens novas (nunca usadas no treino)

Teste com 6 imagens de `Imagens_2/`, adicionadas depois do treino e **nunca
usadas** em nenhuma etapa — nem no dataset Kaggle, nem no Dryad, nem no fine-tuning de
domínio. Duas categorias:

- **referencia_limpa** (4 imagens): fotos limpas de hidrômetros chineses, com marca/fonte de
  dígito diferente dos medidores russos do Kaggle. O Dryad também é de medidores chineses
  (Hangzhou), então não foi verificado se o estilo destas fotos aparece nele.
- **esp32cam_real** (2 imagens): fotos tiradas pela própria ESP32-CAM (de um monitor exibindo
  imagens de hidrômetro), testando a câmera/lente/compressão reais numa condição mais
  difícil que a categoria acima.

Gerado por `testar_imagens_novas.py`, reaproveitando `modelo_digito.tflite` já treinado
(sem re-treinar nada). A pasta `Imagens_2/` local tem ~135 fotos no total — só as
6 realmente usadas neste teste ficam versionadas no repositório.

> **Sobre cobertura parcial:** mesmo depois de reenquadrar as fotos da ESP32-CAM
> para ficarem mais retas, cada uma ainda precisa de uma caixa de recorte calibrada **à mão**
> — inclusive fotos consecutivas do mesmo medidor (`144`/`145` aqui) têm um leve jitter de
> enquadramento entre uma captura e outra que impede reaproveitar a mesma caixa sem ajuste
> fino. Calibrar as ~135 fotos disponíveis (ou mesmo metade) exigiria uma ferramenta de
> recorte assistido ou detecção automática da janela de dígitos — fora do escopo de tempo
> desta rodada. Prioridade foi cobrir pelo menos 1-2 exemplos de cada categoria/medidor
> disponível com confiança, em vez de arriscar recortes malfeitos só para aumentar a
> contagem (mesmo critério usado no resto do projeto: descartar em vez de adivinhar).
>
> `20221221_00283.jpg` ("00764") foi descartada pelo mesmo motivo: a janela de dígitos
> segue uma leve curva ao longo do mostrador que o recorte retangular + fatiamento em
> largura igual não consegue alinhar direito (cada célula pega pedaço de dois dígitos
> vizinhos) — o número que sairia dali mediria erro de recorte, não erro do modelo.

## Resumo

| Métrica | Valor |
|---|---|
| Fotos com leitura 100% correta | 4/6 (67%) |
| Dígitos individuais corretos | 29/32 (91%) |

## Resultado por imagem

| Arquivo | Categoria | Real | Previsto | Leitura | Dígitos certos | Imagem |
|---|---|---|---|---|---|---|
| 20220515025423_T1iyhTBjCi1RCvBVdK-000-00282.1296.jpg | referencia_limpa | 00282 | 00282 | ✅ | 5/5 | [ver](../dataset/teste_imagens_novas/ref_00282_predicao.png) |
| 20221126_01576.jpg | referencia_limpa | 00399 | 00399 | ✅ | 5/5 | [ver](../dataset/teste_imagens_novas/ref_00399_predicao.png) |
| 20221221_01143.jpg | referencia_limpa | 027535 | 027535 | ✅ | 6/6 | [ver](../dataset/teste_imagens_novas/ref_027535_predicao.png) |
| 20221221_01471.jpg | referencia_limpa | 021235 | 021200 | ❌ | 4/6 | [ver](../dataset/teste_imagens_novas/ref_021235_predicao.png) |
| imagem_capturada_144.jpg | esp32cam_real | 01613 | 00613 | ❌ | 4/5 | [ver](../dataset/teste_imagens_novas/esp32_144_predicao.png) |
| imagem_capturada_145.jpg | esp32cam_real | 01613 | 01613 | ✅ | 5/5 | [ver](../dataset/teste_imagens_novas/esp32_145_predicao.png) |

## Metodologia e limitações

- As caixas de recorte da janela de dígitos foram calibradas **manualmente** por imagem
  (mesma técnica usada no resto do projeto — sem máscara de segmentação automática
  disponível para essas fotos novas), depois divididas em N fatias de largura igual.
- Amostra pequena e escolhida a dedo entre as imagens mais fáceis de calibrar disponíveis em
  `Imagens_2/` (que tem ~135 fotos no total) — não é uma amostra aleatória nem exaustiva,
  então a taxa de acerto aqui não deve ser lida como "a" acurácia do modelo, só como mais
  um ponto de evidência, complementar ao [RESULTADOS.md](RESULTADOS.md).
- As 2 fotos "esp32cam_real" (mesmo medidor, leituras consecutivas) tiveram 1/2
  leituras e 9/10 dígitos certos. É uma amostra mínima (2 fotos, 1 medidor):
  não dá para tirar daí o efeito da câmera real na acurácia.
