"""
reconstrutor.py
Lê a serial do Heltec, descriptografa o LoRaWAN, remonta a imagem JPEG e REGISTRA a medição
(PDR, tempo de rádio, latência) em medicoes/. Veja registro.py para o que é gravado.

Dois modos:

  Só receptor (padrão)  Escuta o Heltec. Você manda CAPTURE no transmissor por outro terminal.
                        A leitura é identificada pelo id que vem no cabeçalho de cada chunk. A
                        latência conta a partir do primeiro chunk (subestima: falta o tempo de
                        captura) e os "blocos enviados" vêm da contagem de FCnt.
  --tx                  O PC também controla o nó (TX_SERIAL_PORT): manda CAPTURE, lê o log do
                        nó e repete --envios vezes. Latência a partir do disparo e blocos
                        enviados/tempo de rádio vindos do log do nó. Use este modo nas
                        medições da issue.

Cada leitura vira uma linha em medicoes/transmissao.csv e a imagem (completa ou parcial) vai
para medicoes/imagens/. Chunks que não chegarem: mande RESEND:<índices> no transmissor
(só no modo sem --tx) enquanto este script está rodando. O RESEND reenvia a MESMA foto; não
use CAPTURE para completar, porque ele tira outra foto e abre outra leitura.

Fluxo OCR na borda (Rede/transmissor_ocr_esp32cam): a leitura inteira vai em um único uplink na
FPort 2, sem blocos nem JPEG. Qualquer modo recebe os dois fluxos: FPort 1 vira imagem
(transmissao.csv), FPort 2 vira uma linha em medicoes/transmissao_ocr.csv. A opção --fluxo ocr só
muda o que acontece com o nó ligado (--tx): o PC manda LER no lugar de CAPTURE e espera o uplink.
Sem --tx, com o nó em AUTO, a latência fica vazia (não há disparo nem primeiro chunk como
referência); o PDR do enlace vem da contagem de FCnt.

Exemplos:
    python reconstrutor.py                                   # só escuta
    python reconstrutor.py --tx --envios 30 --distancia 50   # mede 30 envios a 50 m
    python reconstrutor.py --tx --fluxo ocr --envios 30      # 30 leituras OCR (manda LER ao nó)

Requisitos:  pip install pyserial pycryptodome   (portas e chaves no .env, veja .env.example)
"""

import argparse
import sys
import time

import serial

import config
import registro


def _argumentos():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tx", action="store_true",
                   help="controla o nó (TX_SERIAL_PORT): manda CAPTURE e lê o log dele")
    p.add_argument("--envios", type=int, default=None,
                   help="para depois de N leituras (com --tx o padrão é 1; sem --tx, sem limite)")
    p.add_argument("--distancia", type=float, default=None, metavar="M",
                   help="distância entre nó e receptor em metros (vai no CSV)")
    p.add_argument("--rotulo", default="", help="texto livre (ambiente, antena...) que vai no CSV")
    p.add_argument("--pausa-s", type=float, default=10.0,
                   help="com --tx: espera entre um envio e o próximo (padrão 10)")
    p.add_argument("--grace-s", type=float, default=3.0,
                   help="com --tx: espera pelo fim do envio do nó depois da imagem completa (padrão 3)")
    p.add_argument("--timeout-inatividade-s", type=float, default=300.0,
                   help="sem --tx: fecha a leitura sem frames novos por este tempo (padrão 300)")
    p.add_argument("--timeout-leitura-s", type=float, default=900.0,
                   help="com --tx: tempo máximo de uma leitura (padrão 900)")
    p.add_argument("--fluxo", choices=["imagem", "ocr"], default="imagem",
                   help="com --tx: qual firmware está no nó. imagem manda CAPTURE; ocr manda LER "
                        "(transmissor_ocr_esp32cam). Sem --tx os dois fluxos são aceitos")
    p.add_argument("--timeout-foto-s", type=float, default=None,
                   help="com --tx: tempo máximo para o nó responder ao disparo "
                        "(padrão 30 no fluxo imagem, 90 no ocr: a inferência leva ~18 s)")
    p.add_argument("--sem-imagens", action="store_true", help="não grava as imagens em medicoes/imagens/")
    p.add_argument("--pasta-medicoes", default=str(registro.PASTA_MEDICOES), help=argparse.SUPPRESS)
    return p.parse_args()


def main():
    args = _argumentos()
    app_skey = config.require_hex("LORA_APP_SKEY", 16)
    dev_addr_hex = config.get("LORA_DEV_ADDR")
    # Se LORA_DEV_ADDR estiver no .env, ignora frames de outros dispositivos
    dev_addr = bytes.fromhex(dev_addr_hex) if dev_addr_hex else None

    portas = {"rx": config.require("RX_SERIAL_PORT")}
    if args.tx:
        portas["tx"] = config.require("TX_SERIAL_PORT")
        if args.distancia is None:
            print("[aviso] sem --distancia: a coluna distancia_m do CSV ficará vazia.")
    envios = args.envios if args.envios is not None else (1 if args.tx else 0)
    timeout_foto_s = args.timeout_foto_s if args.timeout_foto_s is not None \
        else (90.0 if args.fluxo == "ocr" else 30.0)
    comando = b"LER\n" if args.fluxo == "ocr" else b"CAPTURE\n"

    ex = registro.Execucao(
        modo="tx_controlado" if args.tx else "so_receptor", rotulo=args.rotulo,
        distancia_m=args.distancia, pasta_medicoes=args.pasta_medicoes,
        extras={"portas": portas, "envios_pedidos": envios or None, "fluxo": args.fluxo,
                "grace_s": args.grace_s if args.tx else 0.0,
                "timeout_inatividade_s": args.timeout_inatividade_s,
                "timeout_leitura_s": args.timeout_leitura_s})
    sessao = registro.Sessao(
        ex, app_skey, dev_addr, grace_s=args.grace_s if args.tx else 0.0,
        timeout_inatividade_s=args.timeout_inatividade_s, timeout_leitura_s=args.timeout_leitura_s,
        timeout_foto_s=timeout_foto_s, salvar_imagens=not args.sem_imagens, fluxo=args.fluxo)

    seriais, leitores = {}, {}

    def abrir(nome):
        seriais[nome] = registro.abrir_serial(portas[nome])
        leitores[nome] = registro.LinhasSerial(seriais[nome])

    def reabrir(nome, erro):
        """A USB caiu: tenta reabrir por ~20 s. Os frames desse intervalo ficam perdidos e isso
        aparece no log (evento serial_erro) e na lacuna de FCnt."""
        ex.contadores["serial_erros"] += 1
        ex.evento("serial_erro", canal=nome, erro=str(erro))
        print(f"[!] Serial {nome} ({portas[nome]}) falhou: {erro}. Reabrindo...")
        try:
            seriais[nome].close()
        except (serial.SerialException, OSError):
            pass
        for _ in range(20):
            time.sleep(1)
            try:
                abrir(nome)
                ex.evento("serial_reaberta", canal=nome)
                print(f"[ok] Serial {nome} reaberta.")
                return
            except (serial.SerialException, OSError):
                continue
        raise RuntimeError(f"não foi possível reabrir a serial {nome} ({portas[nome]})")

    def passo():
        """Uma volta: lê as seriais, alimenta a sessão, aplica timeouts."""
        for nome in list(leitores):
            try:
                linhas = leitores[nome].ler()
            except (serial.SerialException, OSError) as e:
                reabrir(nome, e)
                continue
            for t, texto in linhas:
                if nome == "tx":
                    print(f"  [esp32-cam] {texto}")
                    sessao.linha_tx(texto, t)
                elif sessao.linha_rx(texto, t) is None:
                    print(texto)            # log normal do ESP32 receptor (boot, debug)
        sessao.verificar(time.perf_counter())
        time.sleep(0.005)

    motivo_fim = "fim_da_execucao"
    erro = None
    try:
        for nome in portas:
            print(f"Abrindo {nome.upper()} {portas[nome]} @ 115200...")
            abrir(nome)
        print(f"Registro desta execução: {ex.pasta}")
        time.sleep(1)                       # deixa o que já estava no buffer chegar e ser descartado
        for leitor in leitores.values():
            leitor.ler()

        if args.tx:
            for i in range(1, envios + 1):
                print(f"\n=== Envio {i}/{envios} ===")
                t0 = time.perf_counter()
                sessao.disparar(t0)
                seriais["tx"].write(comando)
                ex.evento("capture_enviado", t0, n=i, comando=comando.decode().strip())
                while sessao.atual is not None:
                    passo()
                if i < envios:
                    fim_pausa = time.perf_counter() + args.pausa_s
                    while time.perf_counter() < fim_pausa:
                        passo()             # ainda registra o que sobrar da leitura anterior
        else:
            print(">>> Mande CAPTURE (imagem) ou LER (OCR) no transmissor, ou deixe o nó em AUTO "
                  "(Ctrl+C encerra e mostra o resumo). <<<")
            print("Se faltar algum chunk de imagem, mande RESEND:<índices base 0> SEM fechar este script.\n")
            while not envios or sessao.n_leituras < envios:
                passo()
    except KeyboardInterrupt:
        motivo_fim = "interrompido"
        print("\nInterrompido pelo usuário.")
    except (RuntimeError, serial.SerialException, OSError) as e:
        motivo_fim = "erro_serial"
        erro = str(e)
        print(f"\n[ERRO] {e}")
    finally:
        sessao.encerrar(motivo_fim, time.perf_counter())
        print()
        if sessao.resumos or not sessao.resumos_ocr:
            for linha in registro.estatisticas(sessao.resumos):
                print(linha)
        if sessao.resumos_ocr:
            for linha in registro.estatisticas_ocr(sessao.resumos_ocr):
                print(linha)
        print(f"\nLogs em {ex.pasta}")
        if sessao.resumos or not sessao.resumos_ocr:
            print(f"CSV acumulado em {ex.arquivo_transmissao}")
        if sessao.resumos_ocr:
            print(f"CSV das leituras OCR em {ex.arquivo_ocr}")
        ex.fechar(motivo_fim=motivo_fim, erro=erro, leituras=sessao.n_leituras)
        for s in seriais.values():
            try:
                s.close()
            except (serial.SerialException, OSError):
                pass
    if erro:
        sys.exit(1)


if __name__ == "__main__":
    main()
