"""
report-deck 配色トークン（案B：ネイビー×朱）。

色値をここ以外に直書きしないこと。意味（何に使うか）は SEMANTIC を参照。
旧案（高彩度の原色系ブルー）は古く見えるため、彩度を落とした濃紺系へ変更した。
"""

# --- token ---------------------------------------------------------------
BLUE_DEEP = "#0A2540"     # 章条 / 表頭帯 / 濃色地
BLUE_PRIMARY = "#14508C"  # headline / 強調 / 主系列
BLUE_BRIGHT = "#2E7BC4"   # 系列2
BLUE_MID = "#5B9BD5"      # 系列3
BLUE_LIGHT = "#A8C8E4"    # 系列4
BLUE_PALE = "#D6E6F2"     # 系列5 / 面塗り
CYAN_ACCENT = "#0E7C86"   # 別カテゴリ補助（ティール）
GRAY_PANEL = "#EDF1F5"    # 小見出し帯 / 表の縞
GRAY_DARK = "#3E4C59"     # 次要文字 / 濃灰パネル
GRAY_NOTE = "#6B7684"     # 出所・脚注
GRAY_LINE = "#CBD2D9"     # 罫線・軸
RED_ALERT = "#E8483F"     # ★唯一の強調色（朱）
RED_PURE = "#C0392B"      # 注釈の細線・矢印
ORANGE_AUX = "#E08A2E"    # 第5系列（最後の手段）
WHITE = "#FFFFFF"
BLACK = "#111820"

# --- 系列順（多系列はこの順に使う。色相を跨がない） -------------------------
SERIES = [BLUE_PRIMARY, BLUE_BRIGHT, BLUE_MID, BLUE_LIGHT, BLUE_PALE]
SERIES_EXT = SERIES + [CYAN_ACCENT, ORANGE_AUX]

SEMANTIC = {
    "fact": BLUE_PRIMARY,
    "forecast_other": BLUE_MID,
    "own_estimate": RED_ALERT,
    "attention": RED_ALERT,
    "context": GRAY_DARK,
}


def rgb(hex_str: str) -> str:
    """'#14508C' -> '14508C'（python-pptx の RGBColor.from_string 用）"""
    return hex_str.lstrip("#")
