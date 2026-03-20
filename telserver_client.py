#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TelServer 테스트 클라이언트 v3.1

v3.1 변경사항:
  - MSG:ANOTHER_LOGINED 중복 로그인 경고 처리 추가
  - MSG: 일반 서버 메시지 파싱 추가
  - STATUS: 통화/회선 상태 정보 파싱 추가
  - 9필드 파이프 구분 상태 데이터 (sendTAPIEventState) 파싱 추가

프로토콜 (IL 디컴파일 기반 확정):
  인코딩: euc-kr
  메시지 구분자: $ (0x24)
  필드 구분자: | (파이프)
  포맷: COMMAND|param1|param2|...|

파라미터 포맷 (LG070CallEvent IL 분석 결과):
  LIB_CALL_TRANSFER|보내는내선|CID|받는내선|    (callType=2)
  LIB_CALL_REDIRECT|받는내선|CID|보내는내선|    (callType=3)
  LIB_CALL_MAKECALL|내선|전화번호|국선그룹|     (callType=0)
  LIB_CALL_INTERNAL|내선|대상내선|CID|          (callType=1)

  parseData[0] = 첫번째 파라미터
  parseData[1] = 두번째 파라미터
  parseData[2] = 세번째 파라미터

사용법:
  python telserver_client.py
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

    def send_raw(self, message):
        """raw 문자열을 euc-kr로 인코딩하여 전송"""
        if not self.connected or not self.sock:
            self.log("연결되지 않음", C.RED)
            return False
        try:
            raw = message.encode(ENCODING)
            self.sock.sendall(raw)
            self.log(f"송신 >>> {message}", C.CYAN)
            return True
        except Exception as e:
            self.log(f"송신 실패: {e}", C.RED)
            self.connected = False
            return False

    def send_command(self, command, *params):
        """커맨드|파라미터1|파라미터2|...| 형태로 전송"""
        parts = [command] + list(params)
        message = FIELD_SEP.join(parts) + FIELD_SEP
        return self.send_raw(message)

    def login(self):
        """CMD_LOGIN|IP|내선번호|이름|"""
        local_ip = self._get_local_ip()
        return self.send_command("CMD_LOGIN", local_ip, self.telno, self.name)

    # ── 통화 제어 (IL 분석 기반 정확한 파라미터) ──

    def transfer_call(self, from_ext, cid, to_ext):
        """
        돌려주기 (callType=2)
        LIB_CALL_TRANSFER|보내는내선|CID|받는내선|

        LG070CallEvent에서:
          parseData[0] = from_ext → Disconnected 처리
          parseData[1] = cid → 상태정보용
          parseData[2] = to_ext → GetIndexLG070()으로 채널 찾기 & Transfer() 실행
        """
        self.log(f"돌려주기: {from_ext} → {to_ext} (CID:{cid})", C.BOLD + C.YELLOW)
        return self.send_command("LIB_CALL_TRANSFER", from_ext, cid, to_ext)

    def redirect_call(self, to_ext, cid, from_ext):
        """
        리다이렉트 (callType=3)
        LIB_CALL_REDIRECT|받는내선|CID|보내는내선|

        LG070CallEvent에서:
          parseData[0] = to_ext → Offering, Pickup() 실행
          parseData[1] = cid → 상태정보용
          parseData[2] = from_ext → Disconnected 처리
        """
        self.log(f"리다이렉트: {from_ext} → {to_ext} (CID:{cid})", C.BOLD + C.YELLOW)
        return self.send_command("LIB_CALL_REDIRECT", to_ext, cid, from_ext)

    def make_call(self, ext, phone_number, ring_group=""):
        """
        전화 걸기 (callType=0)
        LIB_CALL_MAKECALL|내선|전화번호|국선그룹|

        LG070CallEvent에서:
          parseData[0] = ext → GetIndexLG070()으로 채널 찾기 & Click2Call
          parseData[1] = phone_number → 대상 번호
          parseData[2] = ring_group → 국선그룹
        """
        self.log(f"전화 걸기: {ext} → {phone_number}", C.BOLD + C.YELLOW)
        return self.send_command("LIB_CALL_MAKECALL", ext, phone_number, ring_group)

    def internal_call(self, ext, target_ext):
        """
        내선 전화 (callType=1)
        LIB_CALL_INTERNAL|내선|대상내선|

        LG070CallEvent에서:
          parseData[0] = ext → InnerRingback 상태
          parseData[1] = target_ext → Click2Call
          parseData[2] = (있으면) 추가정보
        """
        self.log(f"내선 전화: {ext} → {target_ext}", C.BOLD + C.YELLOW)
        return self.send_command("LIB_CALL_INTERNAL", ext, target_ext)

    def reset_call(self, ext):
        """
        통화 상태 초기화
        LIB_CALL_RESET|내선|
        """
        self.log(f"통화 초기화: {ext}", C.BOLD + C.YELLOW)
        return self.send_command("LIB_CALL_RESET", ext)

    def absence_check(self, ext):
        """
        부재중 체크
        LIB_ABSENCE_CHECK|내선|
        """
        self.log(f"부재중 체크: {ext}", C.BOLD + C.YELLOW)
        return self.send_command("LIB_ABSENCE_CHECK", ext)

    # ── 수신 처리 ──

    def recv_loop(self):
        buffer = b""
        while self.running and self.connected:
            try:
                data = self.sock.recv(4096)
                if not data:
                    self.log("서버 연결 종료", C.RED)
                    self.connected = False
                    break

                buffer += data

                while True:
                    delim_bytes = DELIMITER.encode(ENCODING)
                    idx = buffer.find(delim_bytes)
                    if idx == -1:
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
        fields = msg.split(FIELD_SEP)
        cmd = fields[0] if fields else ""

        if cmd == "CMD_RECEIVE":
            cid = fields[1] if len(fields) > 1 else "?"
            div = fields[2] if len(fields) > 2 else "?"
            seq = fields[3] if len(fields) > 3 else "?"
            self.log(f"수신 <<< {C.BOLD}전화수신{C.RESET}{C.GREEN}  CID:{cid}  내선:{div}  SEQ:{seq}", C.GREEN)

        elif cmd == "CMD_PICKUP":
            ext = fields[1] if len(fields) > 1 else "?"
            cid = fields[2] if len(fields) > 2 else "?"
            div = fields[3] if len(fields) > 3 else "?"
            extra = fields[4] if len(fields) > 4 else ""
            self.log(f"수신 <<< {C.BOLD}당겨받기{C.RESET}{C.BLUE}  내선:{ext}  CID:{cid}  그룹:{div}  {extra}", C.BLUE)

        elif cmd == "CMD_SEND_NEW_ORDER":
            self.log(f"수신 <<< 신규주문: {msg}", C.YELLOW)

        elif cmd == "TRS_RECEIVE":
            self.log(f"수신 <<< TRS: {msg}", C.DIM)

        # ── #3: MSG:ANOTHER_LOGINED - 중복 로그인 경고 ──
        elif msg.startswith("MSG:ANOTHER_LOGINED"):
            self.log(
                f"수신 <<< {C.BOLD}[중복 로그인 경고]{C.RESET}{C.RED}"
                f"  다른 위치에서 동일 내선({self.telno})으로 로그인됨."
                f" 현재 세션이 비활성화될 수 있습니다.",
                C.RED + C.BOLD,
            )

        # ── #3 확장: MSG: 일반 서버 메시지 처리 ──
        elif msg.startswith("MSG:"):
            body = msg[4:]
            self.log(f"수신 <<< {C.BOLD}서버메시지:{C.RESET}{C.YELLOW}  {body}", C.YELLOW)

        # ── #4: STATUS: 통화/회선 상태 정보 파싱 ──
        elif msg.startswith("STATUS:"):
            status_data = msg[7:]
            self.log(f"수신 <<< {C.BOLD}상태변경:{C.RESET}{C.CYAN}  {status_data}", C.CYAN)

        # ── #6: 9필드 상태 데이터 (sendTAPIEventState 등) ──
        #   형식: {내선}|{CID}|{상태}|{국선}|{시간}|{f5}|{f6}|{f7}|{f8}|
        elif len(fields) >= 8 and not cmd.startswith("CMD_") and not cmd.startswith("LIB_"):
            ext_f   = fields[0] if len(fields) > 0 else "?"
            cid_f   = fields[1] if len(fields) > 1 else "?"
            state_f = fields[2] if len(fields) > 2 else "?"
            line_f  = fields[3] if len(fields) > 3 else "?"
            time_f  = fields[4] if len(fields) > 4 else "?"
            extra   = FIELD_SEP.join(fields[5:]).rstrip(FIELD_SEP)
            self.log(
                f"수신 <<< {C.BOLD}통화상태{C.RESET}{C.CYAN}"
                f"  내선:{ext_f}  CID:{cid_f}  상태:{state_f}"
                f"  국선:{line_f}  시간:{time_f}  기타:{extra}",
                C.CYAN,
            )

        elif "SUCCESS" in msg.upper():
            self.log(f"수신 <<< {C.BOLD}성공: {msg}{C.RESET}", C.GREEN + C.BOLD)

        elif "FAIL" in msg.upper():
            self.log(f"수신 <<< {C.BOLD}실패: {msg}{C.RESET}", C.RED + C.BOLD)

        else:
            self.log(f"수신 <<< {msg}", C.DIM)

    def _get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "192.168.0.100"

    def start(self):
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
    help_text = f"""
{C.BOLD}=== TelServer 테스트 클라이언트 v3.1 ==={C.RESET}
{C.DIM}IL 디컴파일 기반 정확한 파라미터 포맷{C.RESET}

{C.CYAN}통화 제어:{C.RESET}
  {C.BOLD}transfer <보내는내선> <CID> <받는내선>{C.RESET}
      돌려주기. 예: transfer 2785 01012345678 8955
      LIB_CALL_TRANSFER|2785|01012345678|8955|

  {C.BOLD}redirect <받는내선> <CID> <보내는내선>{C.RESET}
      리다이렉트. 예: redirect 8955 01012345678 2785
      LIB_CALL_REDIRECT|8955|01012345678|2785|

  {C.BOLD}call <내선> <전화번호> [국선그룹]{C.RESET}
      전화 걸기. 예: call 2785 01012345678
      LIB_CALL_MAKECALL|2785|01012345678||

  {C.BOLD}internal <내선> <대상내선>{C.RESET}
      내선 전화. 예: internal 2785 8955

  {C.BOLD}reset <내선>{C.RESET}
      통화 상태 초기화. 예: reset 2785

  {C.BOLD}absence <내선>{C.RESET}
      부재중 체크. 예: absence 2785

{C.CYAN}디버깅:{C.RESET}
  {C.BOLD}raw <메시지>{C.RESET}
      직접 raw 전송. 예: raw LIB_CALL_TRANSFER|2785|01012345678|8955|

  {C.BOLD}login{C.RESET}            재로그인

{C.CYAN}기타:{C.RESET}
  {C.BOLD}help{C.RESET}  도움말     {C.BOLD}quit{C.RESET}  종료
"""
    print(help_text)

    while client.running:
        try:
            cmd_input = input(f"\n{C.BOLD}telserver>{C.RESET} ").strip()
            if not cmd_input:
                continue

            parts = cmd_input.split()
            cmd = parts[0].lower()

            if cmd in ("quit", "exit", "q"):
                break

            elif cmd in ("help", "h"):
                print(help_text)

            elif cmd in ("transfer", "t"):
                if len(parts) >= 4:
                    client.transfer_call(parts[1], parts[2], parts[3])
                elif len(parts) == 3:
                    # CID 생략 시 빈값
                    client.transfer_call(parts[1], "", parts[2])
                else:
                    print(f"  사용법: transfer <보내는내선> <CID> <받는내선>")
                    print(f"  예시:   transfer 2785 01012345678 8955")
                    print(f"  CID 생략: transfer 2785 8955")

            elif cmd in ("redirect", "r"):
                if len(parts) >= 4:
                    client.redirect_call(parts[1], parts[2], parts[3])
                elif len(parts) == 3:
                    client.redirect_call(parts[1], "", parts[2])
                else:
                    print(f"  사용법: redirect <받는내선> <CID> <보내는내선>")

            elif cmd in ("call", "c"):
                if len(parts) >= 3:
                    ring_group = parts[3] if len(parts) >= 4 else ""
                    client.make_call(parts[1], parts[2], ring_group)
                else:
                    print(f"  사용법: call <내선> <전화번호> [국선그룹]")

            elif cmd in ("internal", "i"):
                if len(parts) >= 3:
                    client.internal_call(parts[1], parts[2])
                else:
                    print(f"  사용법: internal <내선> <대상내선>")

            elif cmd == "reset":
                ext = parts[1] if len(parts) >= 2 else client.telno
                client.reset_call(ext)

            elif cmd == "absence":
                ext = parts[1] if len(parts) >= 2 else client.telno
                client.absence_check(ext)

            elif cmd == "raw":
                if len(parts) >= 2:
                    raw_msg = " ".join(parts[1:])
                    client.send_raw(raw_msg)
                else:
                    print(f"  사용법: raw <메시지>")
                    print(f"  예시:   raw LIB_CALL_TRANSFER|2785|01012345678|8955|")

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
    parser = argparse.ArgumentParser(description="TelServer 테스트 클라이언트 v3.1")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"TelServer IP (기본: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"포트 (기본: {DEFAULT_PORT})")
    parser.add_argument("--telno", default=DEFAULT_TELNO, help=f"내선번호 (기본: {DEFAULT_TELNO})")
    parser.add_argument("--name", default=DEFAULT_NAME, help=f"클라이언트명 (기본: {DEFAULT_NAME})")
    parser.add_argument("--log", action="store_true", help="파일 로깅 활성화")
    args = parser.parse_args()

    print(f"""
{C.BOLD}╔══════════════════════════════════════════════╗
║   TelServer 테스트 클라이언트 v3.1           ║
║   IL 디컴파일 기반 정확한 파라미터 포맷       ║
╚══════════════════════════════════════════════╝{C.RESET}

  서버:  {args.host}:{args.port}
  내선:  {args.telno}
  이름:  {args.name}

  Transfer 포맷: LIB_CALL_TRANSFER|보내는내선|CID|받는내선|
""")

    client = TelServerClient(args.host, args.port, args.telno, args.name, args.log)

    if client.start():
        interactive_mode(client)

    client.stop()
    print(f"\n{C.DIM}클라이언트 종료{C.RESET}")

if __name__ == "__main__":
    main()
