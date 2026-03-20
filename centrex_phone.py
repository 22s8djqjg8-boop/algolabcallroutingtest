#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LGU+ Centrex 전화 제어 프로그램
- 로그인, 전화걸기, 전화끊기, 돌려주기(Transfer) 기능
- ActiveX 없이 TCP 소켓으로 직접 통신
"""

import socket
import struct
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import time

# ──────────────────────────────────────────
# 프로토콜 상수
# ──────────────────────────────────────────
DEFAULT_PORT = 8086
HEADER_TYPE_CMD = 1    # Command
HEADER_TYPE_EVENT = 2  # Event (서버→클라이언트)


class CentrexClient:
    """LGUBaseOpenAPI 서버와 TCP 소켓 통신하는 클라이언트"""

    def __init__(self, on_event=None, on_disconnect=None):
        self.sock = None
        self.connected = False
        self.on_event = on_event          # 이벤트 수신 콜백
        self.on_disconnect = on_disconnect
        self._recv_thread = None
        self._stop = False
        self.agent_exten = ""
        self.caller_id = ""

    # ── 패킷 송수신 ──────────────────────────

    def _pack_msg(self, body: str) -> bytes:
        """Header(short) + BodyLen(short) + Body 형태로 패킹"""
        body_bytes = body.encode("utf-8")
        # Header Type = 1 (CMD), Body Length, Body
        header = struct.pack("!HH", HEADER_TYPE_CMD, len(body_bytes))
        return header + body_bytes

    def _recv_loop(self):
        """서버에서 오는 이벤트를 계속 수신"""
        buf = b""
        while not self._stop and self.connected:
            try:
                data = self.sock.recv(4096)
                if not data:
                    break
                buf += data
                # 패킷 파싱: 4바이트 헤더 + body
                while len(buf) >= 4:
                    header_type, body_len = struct.unpack("!HH", buf[:4])
                    if len(buf) < 4 + body_len:
                        break  # 아직 body가 덜 왔음
                    body = buf[4:4 + body_len].decode("utf-8", errors="replace")
                    buf = buf[4 + body_len:]
                    if self.on_event:
                        self.on_event(body)
            except socket.timeout:
                continue
            except Exception as e:
                if not self._stop:
                    if self.on_event:
                        self.on_event(f"[ERROR] 수신 오류: {e}")
                break

        self.connected = False
        if self.on_disconnect and not self._stop:
            self.on_disconnect()

    # ── 공개 API ─────────────────────────────

    def connect_and_login(self, login_id: str, password: str, server_ip: str = "", port: int = DEFAULT_PORT):
        """서버 연결 + 로그인"""
        if self.connected:
            self.disconnect()

        # 고급형 Centrex의 경우 LoginServer가 내부적으로 서버를 찾아 ConnectServer를 호출
        # 여기서는 직접 ConnectServer 방식으로 접속
        # server_ip가 비어있으면 LoginServer 방식 (서버가 알아서 찾음)

        if server_ip:
            target_ip = server_ip
        else:
            # 기본: LoginServer 방식 - OAM 서버를 통해 접속
            # 실제로는 HTTPS POST로 서버 주소를 조회하지만,
            # 여기서는 직접 IP를 입력받는 방식 사용
            raise ValueError("서버 IP를 입력해주세요")

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(5)
        self.sock.connect((target_ip, port))
        self.sock.settimeout(2)
        self.connected = True
        self._stop = False

        # 수신 스레드 시작
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()

        # 로그인 명령 전송
        # 포맷: CMD|LOGIN|ID=xxx|PWD=xxx
        cmd = f"CMD|LOGIN|ID={login_id}|PWD={password}"
        self._send(cmd)

    def _send(self, cmd: str):
        """명령 전송"""
        if not self.connected or not self.sock:
            raise ConnectionError("서버에 연결되어 있지 않습니다")
        packet = self._pack_msg(cmd)
        self.sock.sendall(packet)

    def click2call(self, phone_num: str, cid: str = "", context: str = ""):
        """전화 걸기"""
        # CMD|CLICKCALL|EXTEN=전화번호|CID=발신번호|CONTEXT=컨텍스트
        parts = [f"CMD|CLICKCALL|EXTEN={phone_num}"]
        if cid:
            parts[0] += f"|CID={cid}"
        if context:
            parts[0] += f"|CONTEXT={context}"
        self._send(parts[0])

    def hangup(self):
        """전화 끊기 (내 채널)"""
        self._send("CMD|HANGUP")

    def hangup_dst(self):
        """상대방 채널 끊기"""
        self._send("CMD|HANGUPDST")

    def answer(self):
        """전화 받기"""
        self._send("CMD|ANSWER")

    def transfer(self, exten: str):
        """돌려주기 (전환)"""
        self._send(f"CMD|TRANSFER|EXTEN={exten}")

    def atxfer(self, exten: str):
        """전화돌려주기 (지정통화전환 - Attended Transfer)"""
        self._send(f"CMD|ATXFER|EXTEN={exten}")

    def hold(self):
        """통화 보류"""
        self._send("CMD|HOLD")

    def unhold(self):
        """보류 해제"""
        self._send("CMD|UNHOLD")

    def disconnect(self):
        """연결 종료"""
        self._stop = True
        self.connected = False
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None


# ──────────────────────────────────────────
# GUI
# ──────────────────────────────────────────

class PhoneApp:
    def __init__(self):
        self.client = CentrexClient(
            on_event=self._on_event,
            on_disconnect=self._on_disconnect
        )
        self.logged_in = False
        self._build_ui()

    def _build_ui(self):
        self.root = tk.Tk()
        self.root.title("Centrex 전화 제어")
        self.root.geometry("480x600")
        self.root.resizable(False, False)

        # ── 스타일 ──
        style = ttk.Style()
        style.configure("Big.TButton", font=("맑은 고딕", 11), padding=6)
        style.configure("Call.TButton", font=("맑은 고딕", 12, "bold"), padding=8)
        style.configure("Hangup.TButton", font=("맑은 고딕", 12, "bold"), padding=8)

        pad = dict(padx=8, pady=4)

        # ══════════════════════════════════
        # 1) 로그인 영역
        # ══════════════════════════════════
        frame_login = ttk.LabelFrame(self.root, text="  로그인  ", padding=10)
        frame_login.pack(fill="x", **pad)

        row = ttk.Frame(frame_login)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="서버 IP:", width=10).pack(side="left")
        self.ent_ip = ttk.Entry(row, width=20)
        self.ent_ip.pack(side="left", padx=4)
        ttk.Label(row, text="포트:").pack(side="left")
        self.ent_port = ttk.Entry(row, width=6)
        self.ent_port.insert(0, "8086")
        self.ent_port.pack(side="left", padx=4)

        row2 = ttk.Frame(frame_login)
        row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="ID:", width=10).pack(side="left")
        self.ent_id = ttk.Entry(row2, width=16)
        self.ent_id.pack(side="left", padx=4)
        ttk.Label(row2, text="비밀번호:").pack(side="left")
        self.ent_pwd = ttk.Entry(row2, width=12, show="*")
        self.ent_pwd.pack(side="left", padx=4)

        row3 = ttk.Frame(frame_login)
        row3.pack(fill="x", pady=4)
        self.btn_login = ttk.Button(row3, text="로그인", style="Big.TButton", command=self._do_login)
        self.btn_login.pack(side="left", padx=4)
        self.btn_logout = ttk.Button(row3, text="로그아웃", style="Big.TButton", command=self._do_logout, state="disabled")
        self.btn_logout.pack(side="left", padx=4)
        self.lbl_status = ttk.Label(row3, text="● 미연결", foreground="gray", font=("맑은 고딕", 10, "bold"))
        self.lbl_status.pack(side="right", padx=8)

        # ══════════════════════════════════
        # 2) 전화 걸기 영역
        # ══════════════════════════════════
        frame_call = ttk.LabelFrame(self.root, text="  전화 걸기  ", padding=10)
        frame_call.pack(fill="x", **pad)

        row_call = ttk.Frame(frame_call)
        row_call.pack(fill="x", pady=2)
        ttk.Label(row_call, text="전화번호:", width=10).pack(side="left")
        self.ent_phone = ttk.Entry(row_call, width=20, font=("맑은 고딕", 12))
        self.ent_phone.pack(side="left", padx=4)

        row_call_btn = ttk.Frame(frame_call)
        row_call_btn.pack(fill="x", pady=4)
        self.btn_call = ttk.Button(row_call_btn, text="📞 전화걸기", style="Call.TButton", command=self._do_call)
        self.btn_call.pack(side="left", padx=4)
        self.btn_answer = ttk.Button(row_call_btn, text="📲 전화받기", style="Big.TButton", command=self._do_answer)
        self.btn_answer.pack(side="left", padx=4)
        self.btn_hangup = ttk.Button(row_call_btn, text="📴 전화끊기", style="Hangup.TButton", command=self._do_hangup)
        self.btn_hangup.pack(side="left", padx=4)

        # ══════════════════════════════════
        # 3) 돌려주기 영역
        # ══════════════════════════════════
        frame_transfer = ttk.LabelFrame(self.root, text="  돌려주기 (Transfer)  ", padding=10)
        frame_transfer.pack(fill="x", **pad)

        row_tr = ttk.Frame(frame_transfer)
        row_tr.pack(fill="x", pady=2)
        ttk.Label(row_tr, text="전환번호:", width=10).pack(side="left")
        self.ent_transfer = ttk.Entry(row_tr, width=20, font=("맑은 고딕", 12))
        self.ent_transfer.pack(side="left", padx=4)

        row_tr_btn = ttk.Frame(frame_transfer)
        row_tr_btn.pack(fill="x", pady=4)
        self.btn_transfer = ttk.Button(row_tr_btn, text="돌려주기 (바로전환)", style="Big.TButton", command=self._do_transfer)
        self.btn_transfer.pack(side="left", padx=4)
        self.btn_atxfer = ttk.Button(row_tr_btn, text="돌려주기 (통화후전환)", style="Big.TButton", command=self._do_atxfer)
        self.btn_atxfer.pack(side="left", padx=4)

        # ══════════════════════════════════
        # 4) 이벤트 로그
        # ══════════════════════════════════
        frame_log = ttk.LabelFrame(self.root, text="  이벤트 로그  ", padding=4)
        frame_log.pack(fill="both", expand=True, **pad)

        self.txt_log = scrolledtext.ScrolledText(frame_log, height=10, font=("Consolas", 9), wrap="word")
        self.txt_log.pack(fill="both", expand=True)

        btn_clear = ttk.Button(frame_log, text="로그 지우기", command=lambda: self.txt_log.delete("1.0", "end"))
        btn_clear.pack(anchor="e", pady=2)

    # ── 이벤트 핸들러 ────────────────────────

    def _on_event(self, msg: str):
        """서버에서 이벤트 수신 시"""
        self.root.after(0, self._handle_event, msg)

    def _handle_event(self, msg: str):
        self._log(msg)

        # 로그인 결과 파싱
        if msg.startswith("LOGINRESULT"):
            parts = self._parse_event(msg)
            status = parts.get("STATUS", "0")
            if status == "1":
                self.logged_in = True
                exten = parts.get("EXTEN", "")
                callerid = parts.get("CALLERID", "")
                self.lbl_status.config(text=f"● 로그인 OK  내선:{exten}", foreground="green")
                self.btn_login.config(state="disabled")
                self.btn_logout.config(state="normal")
            else:
                err_msg = parts.get("MSG", "알 수 없는 오류")
                self.lbl_status.config(text="● 로그인 실패", foreground="red")
                messagebox.showerror("로그인 실패", f"로그인에 실패했습니다.\n{err_msg}")
                self.client.disconnect()

        # 링 이벤트 (착신)
        elif msg.startswith("RINGEVENT"):
            parts = self._parse_event(msg)
            caller = parts.get("CALLERID", "알 수 없음")
            self._log(f"★ 전화 수신: {caller}")

        # 통화 연결
        elif msg.startswith("CHANNELLIST"):
            self._log("★ 통화 연결됨")

        # 통화 종료
        elif msg.startswith("CHANNELOUT"):
            self._log("★ 통화 종료됨")

    def _parse_event(self, msg: str) -> dict:
        """이벤트 메시지를 파싱하여 딕셔너리로 반환
        형식: EVENTNAME|KEY1:VAL1|KEY2:VAL2  또는  EVENTNAME|KEY1=VAL1
        """
        result = {}
        parts = msg.split("|")
        if parts:
            result["EVENT"] = parts[0]
        for part in parts[1:]:
            if ":" in part:
                k, v = part.split(":", 1)
                result[k] = v
            elif "=" in part:
                k, v = part.split("=", 1)
                result[k] = v
        return result

    def _on_disconnect(self):
        self.root.after(0, self._handle_disconnect)

    def _handle_disconnect(self):
        self.logged_in = False
        self.lbl_status.config(text="● 연결 끊김", foreground="red")
        self.btn_login.config(state="normal")
        self.btn_logout.config(state="disabled")
        self._log("[연결 끊김]")

    # ── 버튼 액션 ────────────────────────────

    def _do_login(self):
        ip = self.ent_ip.get().strip()
        port_str = self.ent_port.get().strip()
        login_id = self.ent_id.get().strip()
        pwd = self.ent_pwd.get().strip()

        if not ip:
            messagebox.showwarning("입력 필요", "서버 IP를 입력하세요")
            return
        if not login_id:
            messagebox.showwarning("입력 필요", "로그인 ID를 입력하세요")
            return

        port = int(port_str) if port_str else DEFAULT_PORT
        self.lbl_status.config(text="● 연결 중...", foreground="orange")
        self._log(f"서버 연결 시도: {ip}:{port}")

        try:
            self.client.connect_and_login(login_id, pwd, ip, port)
            self._log("로그인 명령 전송 완료, 응답 대기 중...")
        except Exception as e:
            self.lbl_status.config(text="● 연결 실패", foreground="red")
            messagebox.showerror("연결 실패", str(e))

    def _do_logout(self):
        self.client.disconnect()
        self.logged_in = False
        self.lbl_status.config(text="● 미연결", foreground="gray")
        self.btn_login.config(state="normal")
        self.btn_logout.config(state="disabled")
        self._log("로그아웃 완료")

    def _do_call(self):
        if not self._check_login():
            return
        num = self.ent_phone.get().strip()
        if not num:
            messagebox.showwarning("입력 필요", "전화번호를 입력하세요")
            return
        try:
            self.client.click2call(num)
            self._log(f"전화 걸기: {num}")
        except Exception as e:
            messagebox.showerror("오류", str(e))

    def _do_answer(self):
        if not self._check_login():
            return
        try:
            self.client.answer()
            self._log("전화 받기")
        except Exception as e:
            messagebox.showerror("오류", str(e))

    def _do_hangup(self):
        if not self._check_login():
            return
        try:
            self.client.hangup()
            self._log("전화 끊기")
        except Exception as e:
            messagebox.showerror("오류", str(e))

    def _do_transfer(self):
        if not self._check_login():
            return
        num = self.ent_transfer.get().strip()
        if not num:
            messagebox.showwarning("입력 필요", "전환할 번호를 입력하세요")
            return
        try:
            self.client.transfer(num)
            self._log(f"돌려주기 (바로전환): {num}")
        except Exception as e:
            messagebox.showerror("오류", str(e))

    def _do_atxfer(self):
        if not self._check_login():
            return
        num = self.ent_transfer.get().strip()
        if not num:
            messagebox.showwarning("입력 필요", "전환할 번호를 입력하세요")
            return
        try:
            self.client.atxfer(num)
            self._log(f"돌려주기 (통화후전환): {num}")
        except Exception as e:
            messagebox.showerror("오류", str(e))

    # ── 유틸 ─────────────────────────────────

    def _check_login(self) -> bool:
        if not self.client.connected:
            messagebox.showwarning("미연결", "먼저 로그인하세요")
            return False
        return True

    def _log(self, msg: str):
        timestamp = time.strftime("%H:%M:%S")
        self.txt_log.insert("end", f"[{timestamp}] {msg}\n")
        self.txt_log.see("end")

    def run(self):
        self.root.mainloop()
        # 종료 시 정리
        self.client.disconnect()


# ──────────────────────────────────────────
# 메인
# ──────────────────────────────────────────
if __name__ == "__main__":
    app = PhoneApp()
    app.run()
