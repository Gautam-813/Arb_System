#!/usr/bin/env python3
import argparse
import socket
import sys
import time

import MetaTrader5 as mt5


def connect_socket(host, port):
    while True:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            sock.connect((host, port))
            sock.settimeout(2.0)
            return sock
        except OSError:
            time.sleep(0.5)


def position_pnl():
    positions = mt5.positions_get()
    if not positions:
        return 0.0
    return sum(getattr(position, "profit", 0.0) for position in positions)


def run_worker(args):
    role = args.role.upper()
    last_pnl_at = 0.0
    pnl = 0.0
    sock = None

    while True:
        if not mt5.initialize(path=args.path):
            print(f"{role}: MT5 initialize failed", file=sys.stderr, flush=True)
            time.sleep(1.0)
            continue

        try:
            mt5.symbol_select(args.symbol, True)
            info = mt5.symbol_info(args.symbol)
            point = getattr(info, "point", 0.0) if info else 0.0

            while True:
                tick = mt5.symbol_info_tick(args.symbol)
                if not tick:
                    time.sleep(args.interval)
                    continue

                now = time.time()
                if now - last_pnl_at >= args.pnl_interval:
                    pnl = position_pnl()
                    last_pnl_at = now

                spread = 9999.0
                if point:
                    spread = round((tick.ask - tick.bid) / point)

                if sock is None:
                    sock = connect_socket(args.host, args.port)

                msg = f"TICK {role} {tick.ask:.5f} {tick.bid:.5f} {spread:.0f} {pnl:.2f}\n"
                try:
                    sock.sendall(msg.encode())
                    sock.recv(128)
                except OSError:
                    try:
                        sock.close()
                    except OSError:
                        pass
                    sock = None

                time.sleep(args.interval)
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
                sock = None
            mt5.shutdown()


def parse_args():
    parser = argparse.ArgumentParser(description="Persistent MT5 tick feed worker")
    parser.add_argument("--role", choices=["MASTER", "SLAVE"], required=True)
    parser.add_argument("--path", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5555)
    parser.add_argument("--interval", type=float, default=0.02)
    parser.add_argument("--pnl-interval", type=float, default=0.25)
    return parser.parse_args()


if __name__ == "__main__":
    run_worker(parse_args())
