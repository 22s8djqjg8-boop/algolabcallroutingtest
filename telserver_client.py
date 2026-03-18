#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TelServer 테스트 클라이언트 v2.0
- CMD_LOGIN: TelServer 로그인
- CMD_RECEIVE/CMD_PICKUP 브로드캐스트 수신
- LIB_CALL_TRANSFER: 돌려주기(전환) 요청
- LIB_CALL_REDIRECT: 리다이렉트 요청
- LIB_CALL_MAKECALL: 전화 걸기 요청
- LIB_CALL_INTERNAL: 내선 전화 요청
- LIB_CALL_RESET: 통화 상태 초기화
- LIB_ABSENCE_CHECK: 부재중 체크

프로토콜:
  인코딩: euc-kr (Korean)
  메시지 구분자: $ (0x24)
  필드 구분자: | (파이프)
  포맷: COMMAND|param1|param2|...|$

사용법:
  python telserver_client.py                    # 기본 (수신 모니터링)
  python telserver_client.py --host 211.180.158.71 --port 4232
  python telserver_client.py --telno 3566 --name "테스트PC"
"""

import socket
import threading
import argparse
import sys
import time
import os
from datetime import datetime

# ============================================================
# 설정
# ============================================================
DEFAULT_HOST = "211.180.158.71"
DEFAULT_PORT = 4232
DEFAULT_TELNO = "3566"
DEFAULT_NAME = "TEST_CLIENT"
ENCODING = "euc-kr"
DELIMITER = "$"
FIELD_SEP = "|"
RECONNECT_DELAY = 5
LOG_DIR = "telserver_logs"

# ANSI 색상
class C:
    RESET  = "\033[0m"
    RED    = "\033[91m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    BLUE   = "\033[94m"
    CYAN   = "\033[96m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"

# ============================================================
# TelServer Client
# ============================================================
class TelServerClient:
    def __init__(self, host, port, telno, name, log_to_file=False):
        self.host = host
        self.port = port
        self.telno = telno
        self.name = name
        self.log_to_file = log_to_file
        self.sock = None
        self.connected = False
        self.running = True
        self.recv_thread = None
        self.log_file = None

    def log(self, msg, color=""):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = f"[{ts}] {msg}"
        print(f"{color}{line}{C.RESET}")
        if self.log_file:
            self.log_file.write(f"{line}\n")
            self.log_file.flush()

    def connect(self):
        """TelServer에 TCP 소켓 연결"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(10)
            self.log(f"연결 시도: {self.host}:{self.port}", C.YELLOW)
            self.sock.connect((self.host, self.port))
            self.sock.settimeout(None)
            self.connected = True
            self.log(f"연결 성공!", C.GREEN)
            return True
        except Exception as e:
            self.log(f"연결 실패: {e}", C.RED)
            self.connected = False
            return False

    def send_message(self, command, *params):
        """
        TelServer에 메시지 전송
        포맷: COMMAND|param1|param2|...|$
        """
        if not self.connected or not self.sock:
            self.log("연결되지 않음. 먼저 connect() 필요", C.RED)
            return False

        # 메시지 조립
        parts = [command] + list(params)
        message = FIELD_SEP.join(parts) + FIELD_SEP

        try:
            raw = message.encode(ENCODING)
            self.sock.sendall(raw)
            self.log(f"송신 >>> {message}", C.CYAN)
            return True
        except Exception as e:
            self.log(f"송신 실패: {e}", C.RED)
            self.connected = False
            return False

    def login(self):
        """CMD_LOGIN 전송"""
        # 포맷: CMD_LOGIN|IP|내선번호|사용자명|
        local_ip = self._get_local_ip()
        return self.send_message("CMD_LOGIN", local_ip, self.telno, self.name)

    def transfer_call(self, from_ext, to_ext):
        """
        LIB_CALL_TRANSFER: 돌려주기(전환) 요청
        현재 from_ext에 연결된 통화를 to_ext로 전환
        """
        self.log(f"돌려주기 요청: {from_ext} → {to_ext}", C.BOLD + C.YELLOW)
        return self.send_message("LIB_CALL_TRANSFER", from_ext, to_ext)

    def redirect_call(self, from_ext, to_ext):
        """
        LIB_CALL_REDIRECT: 리다이렉트 요청
        링 중인 콜을 다른 내선으로 리다이렉트
        """
        self.log(f"리다이렉트 요청: {from_ext} → {to_ext}", C.BOLD + C.YELLOW)
        return self.send_message("LIB_CALL_REDIRECT", from_ext, to_ext)

    def make_call(self, phone_number, ring_group=""):
        """
        LIB_CALL_MAKECALL: PBX를 통해 전화 걸기
        또는 CMD_MAKECALL|전화번호 (국선그룹)|
        """
        if ring_group:
            self.log(f"전화 걸기: {phone_number} (그룹: {ring_group})", C.BOLD + C.YELLOW)
            return self.send_message("LIB_CALL_MAKECALL", self.telno, phone_number, ring_group)
        else:
            self.log(f"전화 걸기: {phone_number}", C.BOLD + C.YELLOW)
            return self.send_message("LIB_CALL_MAKECALL", self.telno, phone_number)

    def internal_call(self, target_ext):
        """
        LIB_CALL_INTERNAL: 내선 전화
        """
        self.log(f"내선 전화: → {target_ext}", C.BOLD + C.YELLOW)
        return self.send_message("LIB_CALL_INTERNAL", self.telno, target_ext)

    def reset_call(self):
        """
        LIB_CALL_RESET: 통화 상태 초기화
        """
        self.log(f"통화 상태 초기화 요청", C.BOLD + C.YELLOW)
        return self.send_message("LIB_CALL_RESET", self.telno)

    def absence_check(self):
        """
        LIB_ABSENCE_CHECK: 부재중 체크
        """
        self.log(f"부재중 체크 요청", C.BOLD + C.YELLOW)
        return self.send_message("LIB_ABSENCE_CHECK", self.telno)

    def recv_loop(self):
        """수신 루프 - TelServer 브로드캐스트 메시지 수신"""
        buffer = b""
        while self.running and self.connected:
            try:
                data = self.sock.recv(4096)
                if not data:
                    self.log("서버 연결 종료", C.RED)
                    self.connected = False
                    break

                buffer += data

                # $ 구분자로 메시지 분리
                while True:
                    delim_bytes = DELIMITER.encode(ENCODING)
                    idx = buffer.find(delim_bytes)
                    if idx == -1:
                        # \n 구분자도 체크 (일부 메시지)
                        idx = buffer.find(b'\n')
                        if idx == -1:
                            break

                    msg_bytes = buffer[:idx]
                    buffer = buffer[idx + 1:]

                    try:
                        msg = msg_bytes.decode(ENCODING, errors='replace').strip()
                    except:
                        msg = msg_bytes.decode('utf-8', errors='replace').strip()

                    if msg:
                        self._handle_message(msg)

            except socket.timeout:
                continue
            except ConnectionResetError:
                self.log("서버에 의해 연결 리셋됨", C.RED)
                self.connected = False
                break
            except Exception as e:
                if self.running:
                    self.log(f"수신 오류: {e}", C.RED)
                    self.connected = False
                break

    def _handle_message(self, msg):
        """수신 메시지 처리 및 표시"""
        fields = msg.split(FIELD_SEP)
        cmd = fields[0] if fields else ""

        if cmd == "CMD_RECEIVE":
            # 전화 수신 브로드캐스트
            cid = fields[1] if len(fields) > 1 else "?"
            div = fields[2] if len(fields) > 2 else "?"
            seq = fields[3] if len(fields) > 3 else "?"
            self.log(f"수신 <<< {C.BOLD}전화수신{C.RESET}{C.GREEN}  CID:{cid}  내선:{div}  SEQ:{seq}", C.GREEN)

        elif cmd == "CMD_PICKUP":
            # 당겨받기 브로드캐스트
            ext = fields[1] if len(fields) > 1 else "?"
            cid = fields[2] if len(fields) > 2 else "?"
            div = fields[3] if len(fields) > 3 else "?"
            extra = fields[4] if len(fields) > 4 else ""
            self.log(f"수신 <<< {C.BOLD}당겨받기{C.RESET}{C.BLUE}  내선:{ext}  CID:{cid}  그룹:{div}  {extra}", C.BLUE)

        elif cmd == "CMD_SEND_NEW_ORDER":
            self.log(f"수신 <<< 신규주문: {msg}", C.YELLOW)

        elif cmd == "TRS_RECEIVE":
            self.log(f"수신 <<< TRS: {msg}", C.DIM)

        elif "SVR_LOGIN_SUCCESS" in msg or "SUCCESS" in msg:
            self.log(f"수신 <<< 로그인 성공: {msg}", C.GREEN + C.BOLD)

        elif "SVR_LOGIN_FAIL" in msg or "FAIL" in msg:
            self.log(f"수신 <<< 로그인 실패: {msg}", C.RED + C.BOLD)

        else:
            self.log(f"수신 <<< {msg}", C.DIM)

    def _get_local_ip(self):
        """로컬 IP 주소 획득"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "192.168.0.100"

    def start(self):
        """연결 및 수신 루프 시작"""
        if self.log_to_file:
            os.makedirs(LOG_DIR, exist_ok=True)
            fname = f"{LOG_DIR}/telserver_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            self.log_file = open(fname, 'w', encoding='utf-8')
            self.log(f"로그 파일: {fname}")

        while self.running:
            if self.connect():
                self.login()
                self.recv_thread = threading.Thread(target=self.recv_loop, daemon=True)
                self.recv_thread.start()
                return True
            else:
                self.log(f"{RECONNECT_DELAY}초 후 재접속...", C.YELLOW)
                time.sleep(RECONNECT_DELAY)
        return False

    def stop(self):
        """클라이언트 종료"""
        self.running = False
        self.connected = False
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
        if self.log_file:
            self.log_file.close()

# ============================================================
# 인터랙티브 모드
# ============================================================
def interactive_mode(client):
    """대화형 명령 모드"""
    help_text = f"""
{C.BOLD}=== TelServer 테스트 클라이언트 명령어 ==={C.RESET}

{C.CYAN}모니터링:{C.RESET}
  (수신 메시지는 자동 표시됩니다)

{C.CYAN}통화 제어:{C.RESET}
  {C.BOLD}transfer <from> <to>{C.RESET}  돌려주기 (예: transfer 3566 3567)
  {C.BOLD}redirect <from> <to>{C.RESET}  리다이렉트 (예: redirect 3566 3565)
  {C.BOLD}call <번호>{C.RESET}           전화 걸기 (예: call 01012345678)
  {C.BOLD}internal <내선>{C.RESET}       내선 전화 (예: internal 3567)
  {C.BOLD}reset{C.RESET}                통화 상태 초기화
  {C.BOLD}absence{C.RESET}              부재중 체크

{C.CYAN}디버깅:{C.RESET}
  {C.BOLD}raw <메시지>{C.RESET}          직접 메시지 전송 (예: raw LIB_CALL_TRANSFER|3566|3567|)
  {C.BOLD}login{C.RESET}               재로그인

{C.CYAN}기타:{C.RESET}
  {C.BOLD}help{C.RESET}                이 도움말
  {C.BOLD}quit{C.RESET}                종료
"""
    print(help_text)

    while client.running:
        try:
            cmd_input = input(f"\n{C.BOLD}telserver>{C.RESET} ").strip()
            if not cmd_input:
                continue

            parts = cmd_input.split()
            cmd = parts[0].lower()

            if cmd == "quit" or cmd == "exit" or cmd == "q":
                break

            elif cmd == "help" or cmd == "h":
                print(help_text)

            elif cmd == "transfer" or cmd == "t":
                if len(parts) >= 3:
                    client.transfer_call(parts[1], parts[2])
                else:
                    print(f"  사용법: transfer <보내는내선> <받는내선>")
                    print(f"  예시:   transfer 3566 3567")

            elif cmd == "redirect" or cmd == "r":
                if len(parts) >= 3:
                    client.redirect_call(parts[1], parts[2])
                else:
                    print(f"  사용법: redirect <현재내선> <대상내선>")

            elif cmd == "call" or cmd == "c":
                if len(parts) >= 2:
                    ring_group = parts[2] if len(parts) >= 3 else ""
                    client.make_call(parts[1], ring_group)
                else:
                    print(f"  사용법: call <전화번호> [국선그룹]")

            elif cmd == "internal" or cmd == "i":
                if len(parts) >= 2:
                    client.internal_call(parts[1])
                else:
                    print(f"  사용법: internal <대상내선>")

            elif cmd == "reset":
                client.reset_call()

            elif cmd == "absence":
                client.absence_check()

            elif cmd == "raw":
                if len(parts) >= 2:
                    raw_msg = " ".join(parts[1:])
                    try:
                        raw_bytes = raw_msg.encode(ENCODING)
                        client.sock.sendall(raw_bytes)
                        client.log(f"RAW 송신 >>> {raw_msg}", C.CYAN)
                    except Exception as e:
                        client.log(f"RAW 송신 실패: {e}", C.RED)
                else:
                    print(f"  사용법: raw <메시지내용>")
                    print(f"  예시:   raw LIB_CALL_TRANSFER|3566|3567|")

            elif cmd == "login":
                client.login()

            else:
                print(f"  알 수 없는 명령: {cmd} (help로 도움말 확인)")

        except EOFError:
            break
        except KeyboardInterrupt:
            print()
            break

# ============================================================
# Main
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="TelServer 테스트 클라이언트")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"TelServer IP (기본: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"TelServer 포트 (기본: {DEFAULT_PORT})")
    parser.add_argument("--telno", default=DEFAULT_TELNO, help=f"내선번호 (기본: {DEFAULT_TELNO})")
    parser.add_argument("--name", default=DEFAULT_NAME, help=f"클라이언트명 (기본: {DEFAULT_NAME})")
    parser.add_argument("--log", action="store_true", help="파일 로깅 활성화")
    args = parser.parse_args()

    print(f"""
{C.BOLD}╔══════════════════════════════════════════╗
║   TelServer 테스트 클라이언트 v2.0       ║
║   돌려주기/전환/모니터링                   ║
╚══════════════════════════════════════════╝{C.RESET}

  서버:    {args.host}:{args.port}
  내선:    {args.telno}
  이름:    {args.name}
""")

    client = TelServerClient(args.host, args.port, args.telno, args.name, args.log)

    if client.start():
        interactive_mode(client)

    client.stop()
    print(f"\n{C.DIM}클라이언트 종료{C.RESET}")

if __name__ == "__main__":
    main()
