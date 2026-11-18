# Sessão de 2026-11-17 (posição antiga da câmera)

7 quadros do hidrômetro físico `fisico_1`, leitura `000024`, capturados antes de a câmera se mexer. A ROI desta
posição foi sobrescrita no `roi_fisico_1.json`; ela era:

- caixa `4,27,160,54`, `n` = 6, orientação `vflip=1`, `hmirror=0`;
- q_0001 a q_0004 com a iluminação inicial; q_0005 a q_0007 com a luz lateral (sem o reflexo abaixo dos dígitos).

Leitura com essa caixa (`ocr/pipeline_nuvem.py`, fluxo borda): sem pré-processamento, `000000` nos 7; com face
14-74 % e realce, `000024` nos 3 com a luz lateral e `000006` nos 4 com a luz inicial.
