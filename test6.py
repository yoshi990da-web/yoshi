import os
import re
import subprocess
import threading
from datetime import datetime
import shutil

import requests
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# ================================
# NHK ラジオ講座 site_id 一覧
# ================================
SERIES_DEFS = [
    {"title": "小学生の基礎英語", "site_id": "GGQY3M1929", "corner_site_id": "01"},
    {"title": "基礎英語レベル1 / 中学生の基礎英語レベル1", "site_id": "148W8XX226", "corner_site_id": "01"},
    {"title": "基礎英語レベル2 / 中学生の基礎英語レベル2", "site_id": "83RW6PK3GG", "corner_site_id": "01"},
    {"title": "ラジオビジネス英語", "site_id": "368315KKP8", "corner_site_id": "01"},
    {"title": "ラジオ英会話", "site_id": "PMMJ59J6N2", "corner_site_id": "01"},
    {"title": "英会話タイムトライアル", "site_id": "8Z6XJ6J415", "corner_site_id": "01"},
    {"title": "ニュースで学ぶ「現代英語」", "site_id": "77RQWQX1L6", "corner_site_id": "01"},
    {"title": "エンジョイ・シンプル・イングリッシュ", "site_id": "BR8Z3NX7XM", "corner_site_id": "01"},
]

BASE_URL = "https://www.nhk.or.jp/radio-api/app/v1/web/ondemand/series"


def build_series_url(site_id, corner_site_id):
    return f"{BASE_URL}?site_id={site_id}&corner_site_id={corner_site_id}"


# ================================
# 配信期限 closed_at の解析
# ================================
def parse_closed_at(closed_at_str):
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日.*?(午前|午後)(\d{1,2}):(\d{2})", closed_at_str)
    if not m:
        return None

    year = int(m.group(1))
    month = int(m.group(2))
    day = int(m.group(3))
    ampm = m.group(4)
    hour = int(m.group(5))
    minute = int(m.group(6))

    if ampm == "午後" and hour != 12:
        hour += 12
    if ampm == "午前" and hour == 12:
        hour = 0

    return datetime(year, month, day, hour, minute)


def is_episode_available(ep):
    closed_at_str = ep.get("closed_at")
    if not closed_at_str:
        return True
    dt = parse_closed_at(closed_at_str)
    if dt is None:
        return True
    return dt > datetime.now()


# ================================
# NHK API 取得
# ================================
def fetch_series_data(series_def):
    url = build_series_url(series_def["site_id"], series_def["corner_site_id"])
    r = requests.get(url)
    r.raise_for_status()
    return r.json()


# ================================
# ffmpeg の存在チェック
# ================================
def find_ffmpeg():
    return shutil.which("ffmpeg")


# ================================
# 音声トラック自動検出（情報表示用）
# ================================
def detect_audio_track(stream_url):
    try:
        result = subprocess.run(
            ["ffmpeg", "-i", stream_url],
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True
        )
        info = result.stderr

        tracks = re.findall(r"Stream #0:(\d+).*Audio:", info)
        if not tracks:
            return None, "音声トラックなし"

        tracks = [int(t) for t in tracks]
        return tracks, f"検出された音声トラック: {tracks}"

    except Exception:
        return None, "音声トラック情報の取得に失敗"


# ================================
#  GUI クラス
# ================================
class NHKDownloaderGUI:
    def __init__(self, root):
        self.root = root
        root.title("NHK ラジオ講座 ダウンローダー（完全版）")
        root.geometry("980x560")

        try:
            root.iconbitmap("nhk_radio.ico")
        except:
            pass

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except:
            pass

        self.save_dir = None
        self.ffmpeg_available = False
        self.series_data_list = []
        self.current_episodes = []

        # 表示用：トラックモード（実際の変換では -map は使わない）
        self.track_mode = tk.StringVar(value="auto")

        top_frame = ttk.Frame(root)
        top_frame.grid(row=0, column=0, padx=8, pady=8, sticky="nsew")
        root.grid_rowconfigure(0, weight=1)
        root.grid_columnconfigure(0, weight=1)

        # 左：番組一覧
        left_frame = ttk.Frame(top_frame)
        left_frame.grid(row=0, column=0, sticky="nsw", padx=(0, 8))
        top_frame.grid_columnconfigure(0, weight=1)
        top_frame.grid_columnconfigure(1, weight=2)

        ttk.Label(left_frame, text="番組一覧").pack(anchor="w")

        self.series_listbox = tk.Listbox(left_frame, height=18, width=35)
        self.series_listbox.pack(side="left", fill="both", expand=True)
        self.series_listbox.bind("<<ListboxSelect>>", self.on_series_selected)

        series_scroll = ttk.Scrollbar(left_frame, orient="vertical", command=self.series_listbox.yview)
        series_scroll.pack(side="right", fill="y")
        self.series_listbox.config(yscrollcommand=series_scroll.set)

        # 右：エピソード一覧
        right_frame = ttk.Frame(top_frame)
        right_frame.grid(row=0, column=1, sticky="nsew")
        top_frame.grid_rowconfigure(0, weight=1)

        ttk.Label(right_frame, text="エピソード（配信中のみ）").pack(anchor="w")
        self.episode_listbox = tk.Listbox(right_frame, height=18, selectmode=tk.SINGLE)
        self.episode_listbox.pack(side="left", fill="both", expand=True)
        self.episode_listbox.bind("<<ListboxSelect>>",self.on_episode_selected) 
               

        episode_scroll = ttk.Scrollbar(right_frame, orient="vertical", command=self.episode_listbox.yview)
        episode_scroll.pack(side="right", fill="y")
        self.episode_listbox.config(yscrollcommand=episode_scroll.set)

        # 中段：ボタン
        btn_frame = ttk.Frame(root)
        btn_frame.grid(row=1, column=0, padx=8, pady=4, sticky="ew")

        self.refresh_button = ttk.Button(btn_frame, text="番組一覧を更新", command=self.refresh_series)
        self.refresh_button.grid(row=0, column=0, padx=4, pady=2, sticky="w")

        self.folder_button = ttk.Button(btn_frame, text="保存フォルダを選択", command=self.select_folder)
        self.folder_button.grid(row=0, column=1, padx=4, pady=2, sticky="w")

        self.download_button = ttk.Button(btn_frame, text="選択エピソードをダウンロード", command=self.download_selected)
        self.download_button.grid(row=0, column=2, padx=4, pady=2, sticky="e")

        self.batch_button = ttk.Button(btn_frame, text="番組の全エピソードを一括ダウンロード", command=self.batch_download)
        self.batch_button.grid(row=0, column=3, padx=4, pady=2, sticky="e")

        btn_frame.grid_columnconfigure(0, weight=1)
        btn_frame.grid_columnconfigure(1, weight=1)
        btn_frame.grid_columnconfigure(2, weight=1)
        btn_frame.grid_columnconfigure(3, weight=1)

        # 音声トラック選択（表示用）
        track_frame = ttk.LabelFrame(root, text="音声トラック情報（実際の変換はトラック指定なし）")
        track_frame.grid(row=2, column=0, padx=8, pady=4, sticky="ew")

        ttk.Radiobutton(track_frame, text="自動（実際の変換はトラック指定なし）", variable=self.track_mode, value="auto").pack(anchor="w")

        # プログレス & ステータス
        self.progress = ttk.Progressbar(root, mode="indeterminate")
        self.progress.grid(row=3, column=0, padx=8, pady=4, sticky="ew")

        self.status_var = tk.StringVar(value="準備完了")
        self.status_label = ttk.Label(root, textvariable=self.status_var, anchor="w")
        self.status_label.grid(row=4, column=0, padx=8, pady=(0, 8), sticky="ew")

        self.refresh_series()
        self.check_ffmpeg()

    # ----------------------------
    # UI ヘルパ
    # ----------------------------
    def set_progress(self, running: bool):
        def _do():
            if running:
                self.progress.start(10)
                self.download_button.config(state="disabled")
                self.batch_button.config(state="disabled")
                self.refresh_button.config(state="disabled")
                self.folder_button.config(state="disabled")
            else:
                self.progress.stop()
                self.download_button.config(state="normal")
                self.batch_button.config(state="normal")
                self.refresh_button.config(state="normal")
                self.folder_button.config(state="normal")
        self.root.after(0, _do)

    def set_status(self, text: str):
        self.root.after(0, lambda: self.status_var.set(text))

    # ----------------------------
    # ffmpeg チェック
    # ----------------------------
    def check_ffmpeg(self):
        ffmpeg_path = find_ffmpeg()
        if ffmpeg_path is None:
            self.ffmpeg_available = False
            self.set_status("⚠ ffmpeg が見つかりません。ダウンロード不可。")
            messagebox.showerror(
                "ffmpeg が見つかりません",
                "音声変換に必要な ffmpeg が見つかりません。\n"
                "ffmpeg.exe を PATH に追加してください。"
            )
            self.download_button.config(state="disabled")
            self.batch_button.config(state="disabled")
            return False

        self.ffmpeg_available = True
        self.set_status(f"ffmpeg OK: {ffmpeg_path}")
        return True

    # ----------------------------
    # 保存フォルダ選択
    # ----------------------------
    def select_folder(self):
        path = filedialog.askdirectory()
        if path:
            self.save_dir = path
            self.set_status(f"保存先: {path}")
            messagebox.showinfo("保存フォルダ", f"保存先を設定しました:\n{path}")

    # ----------------------------
    # 番組一覧更新
    # ----------------------------
    def refresh_series(self):
        def worker():
            try:
                self.set_progress(True)
                self.set_status("番組一覧を取得中...")
                self.series_data_list.clear()
                self.series_listbox.delete(0, tk.END)
                self.episode_listbox.delete(0, tk.END)
                self.current_episodes = []

                for sdef in SERIES_DEFS:
                    data = fetch_series_data(sdef)
                    self.series_data_list.append(data)
                    title = data.get("title", sdef["title"])
                    self.series_listbox.insert(tk.END, title)

                self.set_status("番組一覧の取得が完了しました。")
            except Exception as e:
                self.set_status("番組一覧の取得に失敗しました。")
                messagebox.showerror("エラー", f"番組一覧の取得に失敗しました:\n{e}")
            finally:
                self.set_progress(False)

        threading.Thread(target=worker, daemon=True).start()

    # ----------------------------
    # 番組選択 → エピソード一覧
    # ----------------------------
    def on_series_selected(self, event):
        self.series_listbox.focus_set()

        selection = self.series_listbox.curselection()
        if not selection:
            return

        idx = selection[0]
        data = self.series_data_list[idx]

        episodes = data.get("episodes", [])
        available_eps = [ep for ep in episodes if is_episode_available(ep)]
        self.current_episodes = available_eps

        self.episode_listbox.delete(0, tk.END)
        for ep in available_eps:
            title = ep.get("program_title", "No title")
            onair = ep.get("onair_date", "")
            self.episode_listbox.insert(tk.END, f"{title}  /  {onair}")

        self.set_status(f"配信中エピソード: {len(available_eps)} 件")

    # ----------------------------
    # 個別ダウンロード
    # ----------------------------
    def download_selected(self):
        if not self.ffmpeg_available:
            messagebox.showerror("エラー", "ffmpeg が見つからないためダウンロードできません。")
            return

        if not self.save_dir:
            messagebox.showwarning("注意", "先に保存フォルダを選択してください。")
            return

        series_sel = self.series_listbox.curselection()
        ep_sel = self.episode_listbox.curselection()
        if not series_sel or not ep_sel:
            messagebox.showwarning("注意", "番組とエピソードを選択してください。")
            return

        series_idx = series_sel[0]
        ep_idx = ep_sel[0]

        series_data = self.series_data_list[series_idx]
        ep = self.current_episodes[ep_idx]

        series_title = series_data.get("title", "番組")
        ep_title = ep.get("program_title", "エピソード")
        stream_url = ep.get("stream_url")

        if not stream_url:
            messagebox.showerror("エラー", "stream_url が見つかりません。")
            return

        safe_series = re.sub(r'[\\/:*?"<>|]', "_", series_title)
        safe_ep = re.sub(r'[\\/:*?"<>|]', "_", ep_title)
        folder = os.path.join(self.save_dir, safe_series)
        filename = f"{safe_ep}.mp3"

        def worker():
            try:
                self.set_progress(True)
                self.set_status("音声トラック情報を取得中...")

                tracks, info = detect_audio_track(stream_url)
                self.set_status(info)

                path = self.download_with_track(stream_url, folder, filename)

                self.set_status(f"完了: {path}")
                messagebox.showinfo("完了", f"保存しました:\n{path}")

            except Exception as e:
                self.set_status("ダウンロードに失敗しました。")
                messagebox.showerror("エラー", f"ダウンロードに失敗しました:\n{e}")

            finally:
                self.set_progress(False)

        threading.Thread(target=worker, daemon=True).start()

    # ----------------------------
    # 一括ダウンロード
    # ----------------------------
    def batch_download(self):
        if not self.ffmpeg_available:
            messagebox.showerror("エラー", "ffmpeg が見つからないためダウンロードできません。")
            return

        if not self.save_dir:
            messagebox.showwarning("注意", "先に保存フォルダを選択してください。")
            return

        series_sel = self.series_listbox.curselection()
        if not series_sel:
            messagebox.showwarning("注意", "番組を選択してください。")
            return

        series_idx = series_sel[0]
        series_data = self.series_data_list[series_idx]
        series_title = series_data.get("title", "番組")

        episodes = self.current_episodes
        if not episodes:
            messagebox.showwarning("注意", "ダウンロード可能なエピソードがありません。")
            return

        safe_series = re.sub(r'[\\/:*?"<>|]', "_", series_title)
        folder = os.path.join(self.save_dir, safe_series)

        def worker():
            try:
                self.set_progress(True)

                first_ep = episodes[0]
                tracks, info = detect_audio_track(first_ep.get("stream_url"))
                self.set_status(info)

                total = len(episodes)

                for i, ep in enumerate(episodes, start=1):
                    ep_title = ep.get("program_title", "エピソード")
                    stream_url = ep.get("stream_url")
                    if not stream_url:
                        continue

                    safe_ep = re.sub(r'[\\/:*?"<>|]', "_", ep_title)
                    filename = f"{safe_ep}.mp3"

                    self.set_status(f"[{i}/{total}] {ep_title} をダウンロード中...")
                    self.download_with_track(stream_url, folder, filename)

                self.set_status(f"一括ダウンロード完了: {folder}")
                messagebox.showinfo("完了", f"全エピソードを保存しました:\n{folder}")

            except Exception as e:
                self.set_status("一括ダウンロードに失敗しました。")
                messagebox.showerror("エラー", f"一括ダウンロードに失敗しました:\n{e}")

            finally:
                self.set_progress(False)

        threading.Thread(target=worker, daemon=True).start()

    # ----------------------------
    # ★ あなたの成功 ffmpeg 設定をそのまま使うダウンロード処理
    #    → -map は一切使わない
    # ----------------------------
    def download_with_track(self, stream_url, folder, filename, retry=3):
        os.makedirs(folder, exist_ok=True)
        output_path = os.path.join(folder, filename)

        for attempt in range(1, retry + 1):
            cmd = [
                "ffmpeg",
                "-y",
                "-http_seekable", "0",
                "-vn",
                "-i", stream_url,
                "-id3v2_version", "3",
                "-acodec", "libmp3lame",
                "-b:a", "48k",
                "-ar", "24000",
                "-ac", "1",
                "-loglevel", "quiet",
                "-stats",
                output_path,
            ]

            try:
                subprocess.run(cmd, check=True)
            except Exception:
                continue

            if os.path.exists(output_path) and os.path.getsize(output_path) > 100 * 1024:
                return output_path

        raise RuntimeError("ffmpeg 変換に失敗しました（3回再試行済み）")

    def on_episode_selected(self, event):
        sel = self.episode_listbox.curselection()
        self.set_status(f"curselection = {sel}")

# ================================
#  メイン起動
# ================================
if __name__ == "__main__":
    root = tk.Tk()
    app = NHKDownloaderGUI(root)
    root.mainloop()








