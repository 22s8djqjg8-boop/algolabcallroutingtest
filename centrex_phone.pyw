#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LGU+ Centrex 전화 제어 프로그램
- ActiveX COM 객체를 Python에서 직접 호출
- IE 불필요, ActiveX(OCX)만 등록되어 있으면 동작
- 로그인 / 전화걸기 / 전화받기 / 전화끊기 / 돌려주기
"""

import sys
import os
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

# ── COM 라이브러리 임포트 ──
try:
    import win32com.client
    import pythoncom
    HAS_COM = True
except ImportError:
    HAS_COM = False


class CentrexCOM:
    """ActiveX COM 객체를 래핑하는 클래스"""

    CLSID = "{86019F2F-2899-4C4C-A6FE-24CFF7CD6D4C}"
    PROGID = "LGUBASEOPENAPILib.LGUBaseOpenApi"

    def __init__(self, on_event=None):
        self.ocx = None
        self.on_event = on_event
        self.connected = False
        self.user_exten = ""
        self._event_thread = None
        self._stop_events = False

    def create(self):
        """COM 객체 생성"""
        pythoncom.CoInitialize()
        try:
            # ProgID로 시도
            self.ocx = win32com.client.DispatchWithEvents(
                self.PROGID, LGUBaseEvents
            )
        except Exception:
            try:
                # CLSID로 시도
                self.ocx = win32com.client.DispatchWithEvents(
                    self.CLSID, LGUBaseEvents
                )
            except Exception as e:
                raise RuntimeError(
                    f"ActiveX를 찾을 수 없습니다.\n"
                    f"register_activex.bat를 관리자 권한으로 먼저 실행해주세요.\n\n{e}"
                )
        # 이벤트 콜백 연결
        LGUBaseEvents._callback = self.on_event
        return True

    def login(self, login_id, password, server_ip=""):
        """로그인"""
        self.ocx.SetAutoReconnect(20)
        self.ocx.SetSeedEncryption()
        self.ocx.LoginServer(login_id, password, server_ip)

    def disconnect(self):
        """연결 종료"""
        if self.ocx:
            try:
                self.ocx.DisconnectServer()
            except:
                pass
        self.connected = False

    def click2call(self, phone_num, cid="", context=""):
        self.ocx.Click2Call(phone_num, cid, context)

    def answer(self):
        self.ocx.Answer()

    def hangup(self):
        self.ocx.HangUp()

    def hangup_dst(self):
        self.ocx.HangUpDst()

    def transfer(self, exten):
        self.ocx.Transfer(exten)

    def atxfer(self, exten):
        self.ocx.AtXfer(exten)

    def hold(self):
        self.ocx.Hold()

    def unhold(self):
        self.ocx.Unhold()

    def pickup(self, exten=""):
        self.ocx.Pickup(exten)

    def pump_events(self):
        """COM 이벤트 펌핑 (메인 스레드에서 주기적 호출 필요)"""
        pythoncom.PumpWaitingMessages()


class LGUBaseEvents:
    """COM 이벤트 싱크 클래스 - ActiveX에서 발생하는 이벤트 수신"""
    _callback = None

    def OnSendLoginResultEvent(self, bstrLoginResult):
        if self._callback:
            self._callback("LOGINRESULT", bstrLoginResult)

    def OnSendRingEvent(self, bstrRingEvent):
        if self._callback:
            self._callback("RINGEVENT", bstrRingEvent)

    def OnSendChannelListEvent(self, bstrChannelList):
        if self._callback:
            self._callback("CHANNELLIST", bstrChannelList)

    def OnSendChannelOutEvent(self, bstrChannelOut):
        if self._callback:
            self._callback("CHANNELOUT", bstrChannelOut)

    def OnSendNetworkErrorEvent(self):
        if self._callback:
            self._callback("NETWORKERROR", "네트워크 연결 오류")

    def OnSendCommandResultEvent(self, bstrResult):
        if self._callback:
            self._callback("CMDRESULT", bstrResult)

    def OnSendCmdErrorEvent(self, strCmd, strEventValue):
        if self._callback:
            self._callback("CMDERROR", f"{strCmd}|{strEventValue}")

    def OnSendEtcEvent(self, strEventName, strEventValue):
        if self._callback:
            self._callback("ETC", f"{strEventName}|{strEventValue}")

    def OnSendPeerMsgEvent(self, strEventValue):
        if self._callback:
            self._callback("PEERMSG", strEventValue)

    def OnSendSMSEvent(self, strEventValue):
        if self._callback:
            self._callback("SMS", strEventValue)


# ══════════════════════════════════════════
# GUI
# ══════════════════════════════════════════

class PhoneApp:
    def __init__(self):
        self.com = None
        self.logged_in = False
        self._build_ui()

    def _build_ui(self):
        self.root = tk.Tk()
        self.root.title("Centrex 전화")
        self.root.geometry("460x620")
        self.root.resizable(False, False)
        self.root.configure(bg="#f0f2f5")

        # ── 스타일 ──
        style = ttk.Style()
        style.theme_use("clam")

        pad = dict(padx=10, pady=5)
        BG = "#f0f2f5"

        # ── 상태바 ──
        self.status_frame = tk.Frame(self.root, bg="#e0e0e0", height=40)
        self.status_frame.pack(fill="x", padx=10, pady=(10, 5))
        self.lbl_status = tk.Label(
            self.status_frame, text="  연결 안됨 - 로그인하세요",
            font=("맑은 고딕", 11, "bold"), fg="#999", bg="#f5f5f5",
            anchor="w", padx=12, pady=8
        )
        self.lbl_status.pack(fill="both", expand=True)

        # ── 착신 정보 ──
        self.lbl_caller = tk.Label(
            self.root, text="", font=("맑은 고딕", 16, "bold"),
            fg="#e65100", bg=BG
        )

        # ══════════════════════════════════
        # 1) 로그인
        # ══════════════════════════════════
        f_login = ttk.LabelFrame(self.root, text="  로그인  ", padding=10)
        f_login.pack(fill="x", **pad)

        row1 = ttk.Frame(f_login)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="ID (070번호):", width=12).pack(side="left")
        self.ent_id = ttk.Entry(row1, width=18)
        self.ent_id.pack(side="left", padx=4)
        ttk.Label(row1, text="PW:").pack(side="left", padx=(8, 0))
        self.ent_pwd = ttk.Entry(row1, width=10, show="*")
        self.ent_pwd.pack(side="left", padx=4)

        row_btn_login = ttk.Frame(f_login)
        row_btn_login.pack(fill="x", pady=(6, 0))
        self.btn_login = tk.Button(
            row_btn_login, text="로그인", font=("맑은 고딕", 11, "bold"),
            bg="#4a90d9", fg="white", relief="flat", padx=20, pady=6,
            command=self._do_login, cursor="hand2"
        )
        self.btn_login.pack(side="left", padx=4)
        self.btn_logout = tk.Button(
            row_btn_login, text="로그아웃", font=("맑은 고딕", 10),
            bg="#e0e0e0", fg="#333", relief="flat", padx=16, pady=6,
            command=self._do_logout, cursor="hand2", state="disabled"
        )
        self.btn_logout.pack(side="left", padx=4)

        # ══════════════════════════════════
        # 2) 전화
        # ══════════════════════════════════
        f_call = ttk.LabelFrame(self.root, text="  전화  ", padding=10)
        f_call.pack(fill="x", **pad)

        self.ent_phone = tk.Entry(
            f_call, font=("맑은 고딕", 18), justify="center",
            relief="solid", bd=1
        )
        self.ent_phone.pack(fill="x", pady=(0, 8), ipady=6)
        self.ent_phone.bind("<Return>", lambda e: self._do_call())

        self.btn_call = tk.Button(
            f_call, text="전화 걸기", font=("맑은 고딕", 13, "bold"),
            bg="#43a047", fg="white", relief="flat", pady=8,
            command=self._do_call, cursor="hand2", state="disabled"
        )
        self.btn_call.pack(fill="x", pady=(0, 6))

        btn_row = tk.Frame(f_call, bg="#fff")
        btn_row.pack(fill="x")

        self.btn_answer = tk.Button(
            btn_row, text="전화 받기", font=("맑은 고딕", 11, "bold"),
            bg="#2196f3", fg="white", relief="flat", pady=6,
            command=self._do_answer, cursor="hand2", state="disabled"
        )
        self.btn_answer.pack(side="left", expand=True, fill="x", padx=(0, 3))

        self.btn_hangup = tk.Button(
            btn_row, text="전화 끊기", font=("맑은 고딕", 11, "bold"),
            bg="#e53935", fg="white", relief="flat", pady=6,
            command=self._do_hangup, cursor="hand2", state="disabled"
        )
        self.btn_hangup.pack(side="left", expand=True, fill="x", padx=(3, 0))

        # ══════════════════════════════════
        # 3) 돌려주기
        # ══════════════════════════════════
        f_trans = ttk.LabelFrame(self.root, text="  돌려주기  ", padding=10)
        f_trans.pack(fill="x", **pad)

        self.ent_transfer = ttk.Entry(f_trans, font=("맑은 고딕", 12), justify="center")
        self.ent_transfer.pack(fill="x", pady=(0, 6), ipady=4)

        tr_row = tk.Frame(f_trans)
        tr_row.pack(fill="x")
        self.btn_transfer = tk.Button(
            tr_row, text="바로 전환", font=("맑은 고딕", 10, "bold"),
            bg="#ff9800", fg="white", relief="flat", pady=5,
            command=self._do_transfer, cursor="hand2", state="disabled"
        )
        self.btn_transfer.pack(side="left", expand=True, fill="x", padx=(0, 3))
        self.btn_atxfer = tk.Button(
            tr_row, text="통화후 전환", font=("맑은 고딕", 10, "bold"),
            bg="#7b1fa2", fg="white", relief="flat", pady=5,
            command=self._do_atxfer, cursor="hand2", state="disabled"
        )
        self.btn_atxfer.pack(side="left", expand=True, fill="x", padx=(3, 0))

        # ══════════════════════════════════
        # 4) 로그
        # ══════════════════════════════════
        f_log = ttk.LabelFrame(self.root, text="  이벤트 로그  ", padding=4)
        f_log.pack(fill="both", expand=True, **pad)
        self.txt_log = scrolledtext.ScrolledText(
            f_log, height=7, font=("Consolas", 9), wrap="word", bg="#fafafa"
        )
        self.txt_log.pack(fill="both", expand=True)

    # ── 이벤트 처리 ──────────────────────

    def _on_event(self, event_type, data):
        """COM 이벤트 콜백 (COM 스레드에서 호출됨)"""
        self.root.after(0, self._handle_event, event_type, data)

    def _handle_event(self, event_type, data):
        self._log(f"[{event_type}] {data}")

        if event_type == "LOGINRESULT":
            info = self._parse(data)
            if info.get("STATUS") == "1":
                self.logged_in = True
                exten = info.get("EXTEN", "")
                self._set_status(f"  로그인 성공! 대기 중 (내선: {exten})", "#2e7d32", "#e8f5e9")
                self._set_buttons(True)
                self.btn_login.config(state="disabled")
                self.btn_logout.config(state="normal")
            else:
                msg = info.get("MSG", "알 수 없는 오류")
                self._set_status("  로그인 실패", "#c62828", "#ffebee")
                messagebox.showerror("로그인 실패", msg)
                if self.com:
                    self.com.disconnect()

        elif event_type == "RINGEVENT":
            info = self._parse(data)
            caller = info.get("CALLERID", "알 수 없음")
            self._set_status(f"  전화 수신 중!  {caller}", "#e65100", "#fff3e0")
            self.lbl_caller.config(text=f"수신: {caller}")
            self.lbl_caller.pack(pady=4)

        elif event_type == "CHANNELLIST":
            self._set_status("  통화 중", "#1565c0", "#e3f2fd")

        elif event_type == "CHANNELOUT":
            self._set_status("  대기 중", "#2e7d32", "#e8f5e9")
            self.lbl_caller.pack_forget()

        elif event_type == "NETWORKERROR":
            self.logged_in = False
            self._set_status("  연결 끊김 - 다시 로그인하세요", "#c62828", "#ffebee")
            self._set_buttons(False)
            self.btn_login.config(state="normal")
            self.btn_logout.config(state="disabled")

    def _parse(self, msg):
        result = {}
        parts = msg.split("|")
        if parts:
            result["EVENT"] = parts[0]
        for p in parts[1:]:
            if ":" in p:
                k, v = p.split(":", 1)
                result[k] = v
        return result

    # ── 버튼 액션 ────────────────────────

    def _do_login(self):
        if not HAS_COM:
            messagebox.showerror(
                "pywin32 필요",
                "이 프로그램을 사용하려면 pywin32가 필요합니다.\n\n"
                "명령 프롬프트에서 다음을 실행하세요:\n"
                "pip install pywin32"
            )
            return

        login_id = self.ent_id.get().strip()
        pwd = self.ent_pwd.get().strip()
        if not login_id:
            messagebox.showwarning("입력 필요", "로그인 ID를 입력하세요")
            return

        self._set_status("  연결 중...", "#f57f17", "#fff8e1")
        self._log("COM 객체 생성 중...")

        try:
            self.com = CentrexCOM(on_event=self._on_event)
            self.com.create()
            self._log("ActiveX 로드 성공")
            self.com.login(login_id, pwd, "")
            self._log(f"로그인 시도: {login_id}")
            # COM 이벤트 펌핑 시작
            self._start_event_pump()
        except Exception as e:
            self._set_status("  ActiveX 오류", "#c62828", "#ffebee")
            messagebox.showerror("오류", str(e))

    def _do_logout(self):
        if self.com:
            self.com.disconnect()
        self.logged_in = False
        self._set_status("  연결 안됨", "#999", "#f5f5f5")
        self._set_buttons(False)
        self.btn_login.config(state="normal")
        self.btn_logout.config(state="disabled")
        self._log("로그아웃 완료")

    def _do_call(self):
        if not self._check():
            return
        num = self.ent_phone.get().strip().replace("-", "").replace(" ", "")
        if not num:
            messagebox.showwarning("입력 필요", "전화번호를 입력하세요")
            return
        self.com.click2call(num)
        self._log(f"전화 걸기: {num}")

    def _do_answer(self):
        if not self._check():
            return
        self.com.answer()
        self._log("전화 받기")

    def _do_hangup(self):
        if not self._check():
            return
        self.com.hangup()
        self._log("전화 끊기")
        self.lbl_caller.pack_forget()

    def _do_transfer(self):
        if not self._check():
            return
        num = self.ent_transfer.get().strip()
        if not num:
            messagebox.showwarning("입력 필요", "전환할 번호를 입력하세요")
            return
        self.com.transfer(num)
        self._log(f"바로 전환: {num}")

    def _do_atxfer(self):
        if not self._check():
            return
        num = self.ent_transfer.get().strip()
        if not num:
            messagebox.showwarning("입력 필요", "전환할 번호를 입력하세요")
            return
        self.com.atxfer(num)
        self._log(f"통화후 전환: {num}")

    # ── 유틸 ─────────────────────────────

    def _check(self):
        if not self.com or not self.logged_in:
            messagebox.showwarning("미연결", "먼저 로그인하세요")
            return False
        return True

    def _set_status(self, text, fg, bg):
        self.lbl_status.config(text=text, fg=fg, bg=bg)
        self.status_frame.config(bg=bg)

    def _set_buttons(self, enabled):
        st = "normal" if enabled else "disabled"
        for btn in [self.btn_call, self.btn_answer, self.btn_hangup,
                    self.btn_transfer, self.btn_atxfer]:
            btn.config(state=st)

    def _log(self, msg):
        ts = time.strftime("%H:%M:%S")
        self.txt_log.insert("end", f"[{ts}] {msg}\n")
        self.txt_log.see("end")

    def _start_event_pump(self):
        """COM 이벤트를 주기적으로 펌핑"""
        if self.com and self.com.ocx:
            try:
                self.com.pump_events()
            except:
                pass
        self.root.after(100, self._start_event_pump)

    def run(self):
        self.root.mainloop()
        if self.com:
            self.com.disconnect()


# ══════════════════════════════════════════
# 메인
# ══════════════════════════════════════════
if __name__ == "__main__":
    app = PhoneApp()
    app.run()
