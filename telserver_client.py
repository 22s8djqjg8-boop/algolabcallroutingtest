#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TelServer 테스트 클라이언트
- TelServer.exe에 TCP 소켓으로 접속하여 CMD_RECEIVE/CMD_PICKUP 브로드캐스트를 수신
- 프로토콜: TelServer v1.0.1.13 (InsungData Inc.)

사용법:
  python3 telserver_client.py                          # 기본값으로 실행
  python3 telserver_client.py --host 211.180.158.71   # 서버 IP 지정
  python3 telserver_client.py --port 14430            # 포트 지정
  python3 telserver_client.py --telno 3566            # 내선번호 지정
  python3 telserver_client.py --name 테스트PC         # 클라이언트 이름
  python3 telserver_client.py --log                   # 파일 로깅 활성화
"""

import socket
import threading
import time
import sys
import os
import argparse
from datetime import datetime


# ============================================================
#  설정
# ============================================================
DEFAULT_HOST = "211.180.158.74"   # TelServer IP
DEFAULT_PORT = 4232           # TelServer 소켓 포트 
DEFAULT_TELNO = "9999"           # 테스트용 내선번호 기존 내선과 겹치지 않게
DEFAULT_NAME = "TEST_CLIENT"     # 클라이언트 식별 이름
ENCODING = "euc-kr"              # TelServer는 euc-kr 인코딩 사용
BUFFER_SIZE = 4096
RECONNECT_DELAY = 20         # 재접속 대기 시간(초)
PING_INTERVAL = 30               # 핑 전송 간격(초)


# ============================================================
#  색상 출력 (Windows/Linux 호환)
# ============================================================
class Colors:
    """ANSI 색상 코드"""
    RESET = "\033[0m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    BOLD = "\033[1m"


def enable_windows_ansi():
    """Windows 콘솔에서 ANSI 색상 활성화"""
    if os.name == 'nt':
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass


# ============================================================
#  프로토콜 파서
# ============================================================
class TelServerProtocol:
    """
    TelServer 프로토콜 파서

    검증된 프로토콜 형식 (TelServer.exe 바이너리 분석 기반):

    1. CMD_LOGIN|{IP}|{내선번호}|{프로그램명}|
       - 접속 시 클라이언트가 서버로 전송
       - 예: CMD_LOGIN|192.168.0.101|3566|Q_알고퀵19(신버전)|

    2. CMD_RECEIVE|{CID}|{DivNum}|{SeqNo}$
       - 전화 수신 시 서버가 모든 클라이언트에 브로드캐스트
       - $ 로 끝남
       - 예: CMD_RECEIVE|01087045485|7673|319844806$
       - 탭 구분 확장 데이터 포함 가능:
         시퀀스\t타임스탬프\tDivNum\tCID\t거래처그룹\t거래처명\t구분\t부서\t담당자\t주소\t메모\t$

    3. CMD_PICKUP|{응답내선}|{수신DivNum}|{CID}|{SeqNo}$
       - 전화 응답 시 브로드캐스트
       - 예: CMD_PICKUP|3566|7673|01087045485|319844806$

    4. CMD_MAKECALL - 발신 요청
    5. CMD_NEW_ORDER - 신규 주문 알림
    6. CMD_SEND_NEW_ORDER|{data}$ - 신규 주문 전송
    7. CMD_ADD / CMD_DEL - 클라이언트 추가/삭제
    8. TRS_RECEIVE|PHONE|{data}$ - TRS 전화 수신
    9. MSG:ANOTHER_LOGINED - 중복 로그인 알림
    10. #IO|{0}|{1}|{2}$ - I/O 정보
    """

    @staticmethod
    def make_login_packet(client_ip, telno, client_name):
        """CMD_LOGIN 패킷 생성"""
        # TelServer 로그 형식: CMD_LOGIN|IP|내선번호|프로그램명|
        packet = f"CMD_LOGIN|{client_ip}|{telno}|Q_{client_name}|"
        return packet.encode(ENCODING)

    @staticmethod
    def parse_message(raw_data):
        """수신된 원시 데이터를 파싱하여 메시지 리스트 반환"""
        messages = []
        try:
            text = raw_data.decode(ENCODING, errors='replace')
        except Exception:
            text = raw_data.decode('utf-8', errors='replace')

        # $ 구분자로 여러 메시지가 올 수 있음
        # 단, CMD_LOGIN 응답은 $ 없이 올 수도 있음
        parts = text.split('$')
        for part in parts:
            part = part.strip()
            if not part:
                continue

            msg = {"raw": part, "type": "UNKNOWN"}

            if part.startswith("CMD_RECEIVE"):
                msg["type"] = "CMD_RECEIVE"
                msg.update(TelServerProtocol._parse_receive(part))
            elif part.startswith("CMD_PICKUP"):
                msg["type"] = "CMD_PICKUP"
                msg.update(TelServerProtocol._parse_pickup(part))
            elif part.startswith("CMD_MAKECALL"):
                msg["type"] = "CMD_MAKECALL"
            elif part.startswith("CMD_NEW_ORDER") or part.startswith("CMD_SEND_NEW_ORDER"):
                msg["type"] = "CMD_NEW_ORDER"
            elif part.startswith("CMD_ADD"):
                msg["type"] = "CMD_ADD"
            elif part.startswith("CMD_DEL"):
                msg["type"] = "CMD_DEL"
            elif part.startswith("TRS_RECEIVE"):
                msg["type"] = "TRS_RECEIVE"
            elif part.startswith("MSG:"):
                msg["type"] = "MSG"
                msg["message"] = part[4:]
            elif part.startswith("#IO"):
                msg["type"] = "IO"
            elif part.startswith("LIB_"):
                msg["type"] = "LIB_CMD"
            else:
                msg["type"] = "OTHER"

            messages.append(msg)

        return messages

    @staticmethod
    def _parse_receive(text):
        """CMD_RECEIVE 파싱"""
        result = {
            "cid": "",
            "div_num": "",
            "seq_no": "",
            "timestamp": "",
            "customer_group": "",
            "customer_name": "",
            "department": "",
            "contact": "",
            "address": "",
            "memo": ""
        }

        try:
            # 기본 형식: CMD_RECEIVE|CID|DivNum|SeqNo
            # 확장 형식: CMD_RECEIVE|CID|DivNum|SeqNo\tTimestamp\tDivNum\tCID\tGroup\tName\t...\t
            pipe_parts = text.split('|')
            if len(pipe_parts) >= 4:
                result["cid"] = pipe_parts[1]
                result["div_num"] = pipe_parts[2]

                # 3번째 필드에 탭 구분 데이터가 포함될 수 있음
                rest = pipe_parts[3]
                tab_parts = rest.split('\t')
                result["seq_no"] = tab_parts[0]

                if len(tab_parts) >= 4:
                    result["timestamp"] = tab_parts[1]
                    # tab_parts[2] = DivNum (중복)
                    # tab_parts[3] = CID (중복)
                if len(tab_parts) >= 6:
                    result["customer_group"] = tab_parts[4]
                    result["customer_name"] = tab_parts[5]
                if len(tab_parts) >= 8:
                    result["department"] = tab_parts[7]
                if len(tab_parts) >= 9:
                    result["contact"] = tab_parts[8]
                if len(tab_parts) >= 10:
                    result["address"] = tab_parts[9]
                if len(tab_parts) >= 11:
                    result["memo"] = tab_parts[10]
        except Exception as e:
            result["parse_error"] = str(e)

        return result

    @staticmethod
    def _parse_pickup(text):
        """CMD_PICKUP 파싱"""
        result = {
            "answer_telno": "",
            "div_num": "",
            "cid": "",
            "seq_no": ""
        }

        try:
            # CMD_PICKUP|응답내선|DivNum|CID|SeqNo
            parts = text.split('|')
            if len(parts) >= 5:
                result["answer_telno"] = parts[1]
                result["div_num"] = parts[2]
                result["cid"] = parts[3]
                result["seq_no"] = parts[4]
            elif len(parts) >= 4:
                result["answer_telno"] = parts[1]
                result["div_num"] = parts[2]
                result["cid"] = parts[3]
        except Exception as e:
            result["parse_error"] = str(e)

        return result


# ============================================================
#  메인 클라이언트
# ============================================================
class TelServerClient:
    """TelServer TCP 소켓 클라이언트"""

    def __init__(self, host, port, telno, name, log_to_file=False):
        self.host = host
        self.port = port
        self.telno = telno
        self.name = name
        self.log_to_file = log_to_file
        self.sock = None
        self.connected = False
        self.running = True
        self.recv_count = 0
        self.pickup_count = 0
        self.start_time = None
        self.log_file = None

        if self.log_to_file:
            log_dir = "telserver_logs"
            os.makedirs(log_dir, exist_ok=True)
            log_filename = os.path.join(
                log_dir,
                f"telserver_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            )
            self.log_file = open(log_filename, 'w', encoding='utf-8')
            self.log(f"로그 파일: {log_filename}")

    def log(self, message, color=""):
        """콘솔 및 파일에 로그 출력"""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = f"[{timestamp}] {message}"

        if color:
            print(f"{color}{line}{Colors.RESET}")
        else:
            print(line)

        if self.log_file:
            self.log_file.write(line + "\n")
            self.log_file.flush()

    def get_local_ip(self):
        """로컬 IP 주소 가져오기"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((self.host, self.port))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def connect(self):
        """TelServer에 접속"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(10)
            self.log(f"접속 시도: {self.host}:{self.port} ...", Colors.YELLOW)
            self.sock.connect((self.host, self.port))
            self.sock.settimeout(None)  # 수신 대기 시 블로킹
            self.connected = True
            self.start_time = datetime.now()

            local_ip = self.get_local_ip()
            self.log(f"접속 성공! (로컬: {local_ip})", Colors.GREEN)

            # CMD_LOGIN 전송
            login_packet = TelServerProtocol.make_login_packet(
                local_ip, self.telno, self.name
            )
            self.sock.sendall(login_packet)
            self.log(f"로그인 전송: {login_packet.decode(ENCODING)}", Colors.CYAN)

            return True

        except socket.timeout:
            self.log(f"접속 시간 초과: {self.host}:{self.port}", Colors.RED)
            return False
        except ConnectionRefusedError:
            self.log(f"접속 거부됨: {self.host}:{self.port}", Colors.RED)
            return False
        except Exception as e:
            self.log(f"접속 실패: {e}", Colors.RED)
            return False

    def disconnect(self):
        """연결 종료"""
        self.connected = False
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def receive_loop(self):
        """수신 루프 - 별도 스레드에서 실행"""
        buffer = b""

        while self.running and self.connected:
            try:
                data = self.sock.recv(BUFFER_SIZE)
                if not data:
                    self.log("서버 연결 끊김", Colors.RED)
                    self.connected = False
                    break

                buffer += data

                # $ 구분자 또는 줄바꿈으로 메시지 완성 여부 확인
                # 안전을 위해 일정 크기 이상이면 처리
                if b'$' in buffer or b'\n' in buffer or len(buffer) > BUFFER_SIZE:
                    messages = TelServerProtocol.parse_message(buffer)
                    buffer = b""

                    for msg in messages:
                        self._handle_message(msg)

            except socket.timeout:
                continue
            except ConnectionResetError:
                self.log("서버에 의해 연결이 리셋됨", Colors.RED)
                self.connected = False
                break
            except OSError as e:
                if self.running:
                    self.log(f"수신 오류: {e}", Colors.RED)
                self.connected = False
                break

        # 남은 버퍼 처리
        if buffer:
            messages = TelServerProtocol.parse_message(buffer)
            for msg in messages:
                self._handle_message(msg)

    def _handle_message(self, msg):
        """수신된 메시지 처리 및 표시"""
        msg_type = msg["type"]

        if msg_type == "CMD_RECEIVE":
            self.recv_count += 1
            cid = msg.get("cid", "?")
            div_num = msg.get("div_num", "?")
            seq_no = msg.get("seq_no", "?")
            cust_name = msg.get("customer_name", "")
            contact = msg.get("contact", "")
            address = msg.get("address", "")

            self.log(
                f"{'='*60}\n"
                f"         전화 수신 #{self.recv_count}\n"
                f"         발신번호 : {cid}\n"
                f"         회선(DivNum) : {div_num}\n"
                f"         시퀀스 : {seq_no}"
                + (f"\n         거래처 : {cust_name}" if cust_name else "")
                + (f"\n         담당자 : {contact}" if contact else "")
                + (f"\n         주소 : {address}" if address else "")
                + f"\n{'='*60}",
                Colors.GREEN + Colors.BOLD
            )

        elif msg_type == "CMD_PICKUP":
            self.pickup_count += 1
            answer = msg.get("answer_telno", "?")
            cid = msg.get("cid", "?")
            div_num = msg.get("div_num", "?")

            self.log(
                f"  >> 전화 응답: 내선 {answer}이(가) {cid} 전화를 받음 "
                f"(회선:{div_num})",
                Colors.CYAN
            )

        elif msg_type == "CMD_NEW_ORDER":
            self.log(f"  [신규주문] {msg['raw']}", Colors.MAGENTA)

        elif msg_type == "TRS_RECEIVE":
            self.log(f"  [TRS수신] {msg['raw']}", Colors.YELLOW)

        elif msg_type == "MSG":
            message = msg.get("message", "")
            if message == "ANOTHER_LOGINED":
                self.log("  !! 다른 곳에서 동일 내선으로 로그인됨!", Colors.RED)
            else:
                self.log(f"  [메시지] {message}", Colors.YELLOW)

        elif msg_type == "CMD_ADD":
            self.log(f"  [클라이언트 추가] {msg['raw']}", Colors.BLUE)

        elif msg_type == "CMD_DEL":
            self.log(f"  [클라이언트 삭제] {msg['raw']}", Colors.BLUE)

        elif msg_type == "LIB_CMD":
            self.log(f"  [LIB] {msg['raw']}", Colors.BLUE)

        else:
            self.log(f"  [기타] {msg['raw']}", Colors.WHITE)

    def print_status(self):
        """현재 상태 출력"""
        if self.start_time:
            elapsed = datetime.now() - self.start_time
            hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
            minutes, seconds = divmod(remainder, 60)
            elapsed_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            elapsed_str = "00:00:00"

        self.log(
            f"\n--- 상태 ---\n"
            f"  서버: {self.host}:{self.port}\n"
            f"  내선: {self.telno}\n"
            f"  접속: {'연결됨' if self.connected else '끊김'}\n"
            f"  경과: {elapsed_str}\n"
            f"  수신전화: {self.recv_count}건\n"
            f"  응답전화: {self.pickup_count}건\n"
            f"------------",
            Colors.YELLOW
        )

    def run(self):
        """메인 실행 루프"""
        enable_windows_ansi()

        print(f"""
{Colors.CYAN}{'='*60}
  TelServer 테스트 클라이언트
  서버: {self.host}:{self.port}
  내선: {self.telno}
  이름: Q_{self.name}
{'='*60}{Colors.RESET}

  명령어 (입력 후 Enter):
    s  = 상태 확인
    q  = 종료
    r  = 재접속
    p  = 포트 변경 (14430 ↔ 14440)

  Ctrl+C 로도 종료 가능
""")

        # 키 입력을 별도 스레드에서 처리 (macOS/Linux 호환)
        input_thread = threading.Thread(target=self._input_loop, daemon=True)
        input_thread.start()

        while self.running:
            # 접속 시도
            if not self.connected:
                if self.connect():
                    # 수신 스레드 시작
                    recv_thread = threading.Thread(
                        target=self.receive_loop, daemon=True
                    )
                    recv_thread.start()
                else:
                    self.log(
                        f"{RECONNECT_DELAY}초 후 재접속 시도...",
                        Colors.YELLOW
                    )
                    for _ in range(RECONNECT_DELAY * 10):
                        if not self.running:
                            break
                        time.sleep(0.1)
                    continue

            try:
                time.sleep(0.2)
            except KeyboardInterrupt:
                self.log("\n종료합니다...", Colors.YELLOW)
                self.running = False

        self.disconnect()
        if self.log_file:
            self.log_file.close()
        self.log("클라이언트 종료", Colors.YELLOW)

    def _input_loop(self):
        """키 입력 처리 (별도 스레드)"""
        while self.running:
            try:
                line = input().strip().lower()
                if line:
                    self._handle_key(line[0])
            except (KeyboardInterrupt, EOFError):
                self.running = False
                break

    def _handle_key(self, key):
        """키 입력 처리"""
        if key == 'q':
            self.log("종료합니다...", Colors.YELLOW)
            self.running = False
        elif key == 's':
            self.print_status()
        elif key == 'r':
            self.log("재접속 중...", Colors.YELLOW)
            self.disconnect()
        elif key == 'p':
            new_port = 14440 if self.port == 14430 else 14430
            self.log(f"포트 변경: {self.port} → {new_port}", Colors.YELLOW)
            self.port = new_port
            self.disconnect()


# ============================================================
#  실행
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="TelServer 테스트 클라이언트 - CTI 브로드캐스트 수신"
    )
    parser.add_argument(
        "--host", default=DEFAULT_HOST,
        help=f"TelServer IP (기본: {DEFAULT_HOST})"
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT,
        help=f"TelServer 포트 (기본: {DEFAULT_PORT})"
    )
    parser.add_argument(
        "--telno", default=DEFAULT_TELNO,
        help=f"내선번호 (기본: {DEFAULT_TELNO})"
    )
    parser.add_argument(
        "--name", default=DEFAULT_NAME,
        help=f"클라이언트 이름 (기본: {DEFAULT_NAME})"
    )
    parser.add_argument(
        "--log", action="store_true",
        help="파일 로깅 활성화"
    )

    args = parser.parse_args()

    client = TelServerClient(
        host=args.host,
        port=args.port,
        telno=args.telno,
        name=args.name,
        log_to_file=args.log
    )

    client.run()


if __name__ == "__main__":
    main()
