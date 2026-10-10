"""
theme.py
Bảng màu và cấu hình Plotly theme dùng chung cho toàn bộ dashboard D2 Logistics Decision Twin.
Thiết kế theo chuẩn Executive Dashboard: Navy (#0B192C) chủ đạo, Royal Blue (#1D4ED8) cho charts, Amber (#F59E0B) điểm nhấn.
"""

import plotly.graph_objects as go

# ─────────────────────────────────────────────
# BẢNG MÀU CHÍNH — D2 Executive Palette
# ─────────────────────────────────────────────

COLORS = {
    # Dark Navy Header & Brand
    "header_bg":       "#0B192C",
    "header_text":     "#FFFFFF",

    # Primary Blue & Accent
    "primary":         "#1D4ED8",   # Royal Deep Blue
    "primary_light":   "#3B82F6",   # Bright Blue
    "primary_lighter": "#EFF6FF",   # Ice Blue

    # Accent Gold / Amber
    "accent":          "#F59E0B",   # Amber / Gold
    "accent_light":    "#FBBF24",   # Soft Gold

    # Status Indicators
    "success":         "#16A34A",   # Emerald Green
    "warning":         "#EF4444",   # Red

    # Neutral Surface & Text
    "bg_card":         "#FFFFFF",
    "bg_surface":      "#F8FAFC",   # Slate 50
    "bg_sidebar":      "#F1F5F9",   # Slate 100
    "text_primary":    "#0F172A",   # Slate 900
    "text_secondary":  "#334155",   # Slate 700
    "text_muted":      "#64748B",   # Slate 500

    # Gridlines & Borders
    "grid":            "#E2E8F0",   # Slate 200
}

# Dãy màu rời rạc cho charts
COLOR_SEQUENCE = [
    "#1D4ED8",   # Royal Blue
    "#2563EB",   # Medium Blue
    "#3B82F6",   # Bright Blue
    "#F59E0B",   # Amber / Gold
    "#10B981",   # Emerald Green
    "#8B5CF6",   # Purple
    "#0EA5E9",   # Sky Blue
    "#EC4899",   # Pink
    "#64748B",   # Slate Gray
]

# Color scale liên tục cho Choropleth Map và Heatmap (Blue Gradient)
CONTINUOUS_SCALE = [
    [0.0,  "#EFF6FF"],
    [0.25, "#BFDBFE"],
    [0.5,  "#3B82F6"],
    [0.75, "#1D4ED8"],
    [1.0,  "#1E3A8A"],
]

# Diverging scale
DIVERGING_SCALE = [
    [0.0,  "#1D4ED8"],
    [0.5,  "#FFFFFF"],
    [1.0,  "#F59E0B"],
]

# Bảng màu ánh xạ đồng bộ cho phân khúc giá (Giá từ thấp đến cao hoặc cao đến đậm)
CUSTOM_COLOR_MAP = {
    "<4 tỷ": "#10B981",       # Xanh ngọc (Phân khúc thấp nhất)
    "4-6 tỷ": "#3B82F6",      # Xanh dương sáng
    "6-8 tỷ": "#2563EB",      # Xanh dương trung bình
    "8-10 tỷ": "#8B5CF6",     # Tím / Điểm nhấn trung cao
    ">10 tỷ": "#1D4ED8",      # Xanh hoàng gia đậm (Phân khúc cao cấp nhất)
}
# ─────────────────────────────────────────────
# FONT & LAYOUT
# ─────────────────────────────────────────────

FONT_FAMILY = "'Plus Jakarta Sans', 'Inter', 'Segoe UI', sans-serif"
FONT_SIZE_BASE = 12.5
FONT_SIZE_TITLE = 14.5


def get_layout_template() -> dict:
    """
    Trả về dict cấu hình layout dùng chung cho mọi biểu đồ Plotly.
    """
    return dict(
        font=dict(family=FONT_FAMILY, size=FONT_SIZE_BASE, color=COLORS["text_primary"]),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=15, t=40, b=10),
        legend=dict(
            bgcolor="rgba(255,255,255,0.9)",
            bordercolor=COLORS["grid"],
            borderwidth=1,
            font=dict(size=11.5, color=COLORS["text_primary"]),
        ),
        xaxis=dict(
            gridcolor=COLORS["grid"],
            zerolinecolor=COLORS["grid"],
            tickfont=dict(size=11.5, color=COLORS["text_secondary"]),
        ),
        yaxis=dict(
            gridcolor=COLORS["grid"],
            zerolinecolor=COLORS["grid"],
            tickfont=dict(size=11.5, color=COLORS["text_secondary"]),
        ),
        hoverlabel=dict(
            bgcolor="#0F172A",
            bordercolor="#0F172A",
            font=dict(size=12, family=FONT_FAMILY, color="#FFFFFF"),
        ),
    )


def apply_theme(fig: go.Figure, title: str = "") -> go.Figure:
    """
    Áp dụng theme chuẩn vào một Figure Plotly.
    """
    layout_kwargs = get_layout_template()
    if title:
        layout_kwargs["title"] = dict(
            text=f"<b>{title}</b>",
            font=dict(size=FONT_SIZE_TITLE, color=COLORS["text_primary"], family=FONT_FAMILY),
            x=0,
            xanchor="left",
            pad=dict(l=5),
        )
    fig.update_layout(**layout_kwargs)
    return fig


# ─────────────────────────────────────────────
# CSS EXECUTIVE DASHBOARD (GLOBAL & SIDEBAR)
# ─────────────────────────────────────────────

KPI_CARD_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Inter:wght@400;500;600;700&display=swap');

/* Nền chính toàn bộ app & tab content panels (Luôn là màu sáng F8FAFC) */
.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stMain"],
div[data-testid="stTabs"],
div[data-baseweb="tab-panel"] {
    background-color: #F8FAFC !important;
    font-family: 'Plus Jakarta Sans', 'Inter', sans-serif !important;
}

[data-testid="stHeader"] {
    background-color: transparent !important;
    z-index: 9999 !important;
    pointer-events: none !important;
}
[data-testid="stHeader"] * {
    pointer-events: auto !important;
}
/* Hide default Streamlit deploy button and main options menu */
.stAppDeployButton,
#MainMenu,
[data-testid="stHeaderOptionsMenu"] {
    display: none !important;
}

/* Sidebar phong cách D2 clean light slate */
[data-testid="stSidebar"] {
    background-color: #F1F5F9 !important;
    border-right: 1px solid #E2E8F0 !important;
}
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] div,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
    color: #1E293B;
    font-family: 'Plus Jakarta Sans', 'Inter', sans-serif;
}

[data-testid="stSidebar"] h2 {
    color: #0F172A !important;
    font-weight: 700 !important;
    font-size: 1.15rem !important;
}
[data-testid="stSidebar"] label {
    color: #475569 !important;
    font-weight: 600 !important;
    font-size: 0.85rem !important;
}
[data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"] > div,
[data-testid="stSidebar"] .stMultiSelect div[data-baseweb="select"] > div {
    background-color: #FFFFFF !important;
    border: 1px solid #CBD5E1 !important;
    border-radius: 8px !important;
    color: #0F172A !important;
}
[data-testid="stSidebar"] hr {
    border-color: #E2E8F0 !important;
}

/* Style cho tag trong multiselect input */
span[data-baseweb="tag"] {
    background-color: #1D4ED8 !important;
    border-radius: 6px !important;
}
span[data-baseweb="tag"] * {
    color: #FFFFFF !important;
}

/* D2 Dark Navy Header Banner */
.d2-header {
    background: linear-gradient(135deg, #0B192C 0%, #1E293B 100%);
    border-radius: 14px;
    padding: 16px 24px;
    margin-bottom: 16px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    box-shadow: 0 10px 25px -5px rgba(11, 25, 44, 0.25);
}
.d2-brand {
    display: flex;
    align-items: center;
    gap: 14px;
}
.d2-logo {
    width: 44px;
    height: 44px;
    background: linear-gradient(135deg, #1D4ED8 0%, #3B82F6 100%);
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: white;
    font-weight: 800;
    font-size: 22px;
    box-shadow: 0 4px 12px rgba(29, 78, 216, 0.4);
}
.d2-title {
    color: #FFFFFF !important;
    font-weight: 800 !important;
    font-size: 1.25rem !important;
    letter-spacing: 0.5px !important;
    line-height: 1.2 !important;
    margin: 0 !important;
}
.d2-subtitle {
    color: #CBD5E1 !important;
    font-size: 0.75rem !important;
    font-weight: 600 !important;
    letter-spacing: 1.2px !important;
    text-transform: uppercase !important;
    margin: 3px 0 0 0 !important;
}

.block-container,
div[data-testid="stAppViewBlockContainer"] {
    padding-top: 0px !important;
}
div[data-baseweb="tab-list"],
div[data-testid="stTabs"] > div[role="tablist"],
div[data-testid="stTabs"] > div:first-child {
    position: sticky !important;
    top: 0px !important;
    z-index: 99999 !important;
    background-color: #1E3A8A !important;
    padding: 0px 24px !important;
    border-bottom: 1px solid #1D4ED8 !important;
    border-radius: 0px !important;
    gap: 16px !important;
    height: 70px !important;
    display: flex !important;
    align-items: center !important;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1) !important;
}

/* Shift tabs to the right when sidebar is collapsed to prevent overlapping the expand button */
div[data-testid="stAppViewContainer"]:has(button[data-testid="collapsedSidebar"]) div[data-baseweb="tab-list"],
div[data-testid="stAppViewContainer"]:has(button[data-testid="collapsedSidebar"]) div[data-testid="stTabs"] > div[role="tablist"] {
    padding-left: 80px !important;
}

/* Add Dashboard Title to the far right of the navigation bar */
div[data-baseweb="tab-list"]::after,
div[data-testid="stTabs"] > div[role="tablist"]::after {
    content: "D2 LOGISTICS DECISION TWIN" !important;
    color: #FFFFFF !important;
    font-weight: 800 !important;
    font-size: 0.9rem !important;
    margin-left: auto !important;
    padding-right: 20px !important;
    font-family: 'Plus Jakarta Sans', 'Inter', sans-serif !important;
    letter-spacing: 0.5px !important;
    text-transform: uppercase !important;
}

@media (max-width: 1200px) {
    div[data-baseweb="tab-list"]::after,
    div[data-testid="stTabs"] > div[role="tablist"]::after {
        display: none !important;
    }
}
button[data-baseweb="tab"],
button[data-testid="stTab"] {
    background-color: transparent !important;
    border: none !important;
    color: #E2E8F0 !important;
    font-weight: 600 !important;
    font-size: 0.9rem !important;
    padding: 8px 16px !important;
    border-radius: 8px !important;
    transition: all 0.2s ease !important;
    display: flex !important;
    align-items: center !important;
}
button[data-baseweb="tab"]:hover,
button[data-testid="stTab"]:hover {
    color: #FFFFFF !important;
    background-color: rgba(255, 255, 255, 0.08) !important;
}
button[aria-selected="true"] {
    color: #1E3A8A !important;
    background-color: #FFFFFF !important;
    font-weight: 700 !important;
    border-bottom: none !important;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15) !important;
}

/* Inject Tab SVG Masks using currentColor to inherit text colors dynamically */
button[data-baseweb="tab"]::before,
button[data-testid="stTab"]::before {
    content: "" !important;
    display: inline-block !important;
    width: 18px !important;
    height: 18px !important;
    margin-right: 8px !important;
    background-color: currentColor !important;
    -webkit-mask-size: contain !important;
    mask-size: contain !important;
    -webkit-mask-position: center !important;
    mask-position: center !important;
    -webkit-mask-repeat: no-repeat !important;
    mask-repeat: no-repeat !important;
}

button[data-baseweb="tab"]:nth-of-type(1)::before,
button[data-testid="stTab"]:nth-of-type(1)::before {
    -webkit-mask-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z'></path><polyline points='9 22 9 12 15 12 15 22'></polyline></svg>") !important;
    mask-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z'></path><polyline points='9 22 9 12 15 12 15 22'></polyline></svg>") !important;
}

button[data-baseweb="tab"]:nth-of-type(2)::before,
button[data-testid="stTab"]:nth-of-type(2)::before {
    -webkit-mask-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z'></path><circle cx='12' cy='10' r='3'></circle></svg>") !important;
    mask-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z'></path><circle cx='12' cy='10' r='3'></circle></svg>") !important;
}

button[data-baseweb="tab"]:nth-of-type(3)::before,
button[data-testid="stTab"]:nth-of-type(3)::before {
    -webkit-mask-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polyline points='23 6 13.5 15.5 8.5 10.5 1 18'></polyline><polyline points='17 6 23 6 23 12'></polyline></svg>") !important;
    mask-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polyline points='23 6 13.5 15.5 8.5 10.5 1 18'></polyline><polyline points='17 6 23 6 23 12'></polyline></svg>") !important;
}

button[data-baseweb="tab"]:nth-of-type(4)::before,
button[data-testid="stTab"]:nth-of-type(4)::before {
    -webkit-mask-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M21.21 15.89A10 10 0 1 1 8 2.83'></path><path d='M22 12A10 10 0 0 0 12 2v10z'></path></svg>") !important;
    mask-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M21.21 15.89A10 10 0 1 1 8 2.83'></path><path d='M22 12A10 10 0 0 0 12 2v10z'></path></svg>") !important;
}

/* Floating AI Assistant Button at bottom-right corner */
div[data-testid="stMarkdownContainer"]:has(span#btn-ai-popup-marker) { display: none !important; }
div[data-testid="stElementContainer"]:has(span#btn-ai-popup-marker) { display: none !important; }

div[data-testid="stElementContainer"]:has(span#btn-ai-popup-marker) + div[data-testid="stElementContainer"] {
    position: fixed !important;
    bottom: 50px !important;
    right: 24px !important;
    z-index: 999999 !important;
    width: auto !important;
}

div[data-testid="stElementContainer"]:has(span#btn-ai-popup-marker) + div[data-testid="stElementContainer"] button {
    position: fixed !important;
    bottom: 50px !important;
    right: 24px !important;
    z-index: 999999 !important;
    width: 64px !important;
    height: 64px !important;
    border-radius: 50% !important;
    background: linear-gradient(135deg, #0B192C 0%, #1D4ED8 100%) !important;
    color: #FFFFFF !important;
    box-shadow: 0 8px 24px rgba(11, 25, 44, 0.45) !important;
    font-size: 1.75rem !important;
    padding: 0 !important;
    display: flex !important;
    justify-content: center !important;
    align-items: center !important;
    border: 2px solid rgba(255, 255, 255, 0.3) !important;
    transition: all 0.3s ease !important;
    cursor: pointer !important;
}

div[data-testid="stElementContainer"]:has(span#btn-ai-popup-marker) + div[data-testid="stElementContainer"] button:hover {
    transform: translateY(-4px) scale(1.05) !important;
    box-shadow: 0 14px 32px rgba(29, 78, 216, 0.6) !important;
    background: linear-gradient(135deg, #1D4ED8 0%, #3B82F6 100%) !important;
}

/* Thẻ KPI chuẩn Executive D2 */
.kpi-card {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 12px;
    padding: 14px 16px;
    box-shadow: 0 4px 12px rgba(15, 23, 42, 0.03);
    margin-bottom: 12px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
}
.kpi-header {
    display: flex;
    align-items: center;
    gap: 12px;
}
.kpi-icon-box {
    width: 38px;
    height: 38px;
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 18px;
    flex-shrink: 0;
}
.kpi-label {
    font-size: 0.8rem;
    font-weight: 600;
    color: #64748B;
    line-height: 1.2;
}
.kpi-value {
    font-size: 1.5rem;
    font-weight: 800;
    color: #0F172A;
    line-height: 1.2;
    margin-top: 4px;
}
.kpi-trend {
    font-size: 0.76rem;
    font-weight: 600;
    color: #16A34A;
    margin-top: 4px;
    display: flex;
    align-items: center;
    gap: 4px;
}
.kpi-sub {
    font-size: 0.76rem;
    color: #94A3B8;
    margin-top: 2px;
}

/* Insight text bar */
.insight-text {
    font-size: 12.5px;
    color: #0F172A;
    font-weight: 500;
    background: #EFF6FF;
    border-left: 4px solid #1D4ED8;
    border-radius: 0 8px 8px 0;
    padding: 8px 14px;
    margin: 8px 0 16px 0;
    font-family: 'Plus Jakarta Sans', 'Inter', sans-serif;
}
</style>
"""

AI_POPUP_CSS = """
<style>
/* Style for the Dialog Popup */
div[data-testid="stDialog"] > div[role="dialog"] {
    background-color: #F8FAFC !important;
    border-radius: 16px !important;
    border: 1px solid #E2E8F0 !important;
    box-shadow: 0 25px 50px -12px rgba(11, 25, 44, 0.3) !important;
    font-family: 'Plus Jakarta Sans', 'Inter', sans-serif !important;
}

div[data-testid="stDialog"] header {
    background: linear-gradient(135deg, #0B192C 0%, #1E293B 100%) !important;
    border-radius: 16px 16px 0 0 !important;
    padding: 20px 24px !important;
    border-bottom: 3px solid #1D4ED8 !important;
}

div[data-testid="stDialog"] header h2 {
    color: #FFFFFF !important;
    font-weight: 800 !important;
    font-size: 1.35rem !important;
    letter-spacing: 0.5px !important;
}

/* Close button inside dialog header */
div[data-testid="stDialog"] header button svg {
    fill: #FFFFFF !important;
}
div[data-testid="stDialog"] header button:hover {
    background-color: rgba(255, 255, 255, 0.1) !important;
}

/* Chat messages inside dialog */
div[data-testid="stChatMessage"] {
    background-color: transparent !important;
    border: none !important;
    padding: 8px 0 !important;
    margin-bottom: 8px !important;
    box-shadow: none !important;
}

/* Chat messages inside dialog */
div[data-testid="stChatMessage"] {
    background-color: transparent !important;
    border: none !important;
    padding: 6px 0 !important;
    margin-bottom: 4px !important;
    box-shadow: none !important;
    display: flex !important;
    align-items: flex-start !important;
    gap: 10px !important;
}

/* ══ USER bubble — phải, xanh dương ══ */
/* Streamlit có thể dùng nhiều data-testid khác nhau theo version */
div[data-testid="stChatMessage"][data-role="user"],
div[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]),
div[data-testid="stChatMessage"]:has([data-testid="user-avatar"]) {
    flex-direction: row-reverse !important;
    justify-content: flex-start !important;
}

div[data-testid="stChatMessage"][data-role="user"] [data-testid="stChatMessageContent"],
div[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) [data-testid="stChatMessageContent"],
div[data-testid="stChatMessage"]:has([data-testid="user-avatar"]) [data-testid="stChatMessageContent"] {
    background: linear-gradient(135deg, #1D4ED8, #2563EB) !important;
    color: #FFFFFF !important;
    border-radius: 18px 18px 0 18px !important;
    padding: 10px 14px !important;
    max-width: 78% !important;
    width: fit-content !important;
    flex: 0 1 auto !important;
    box-shadow: 0 2px 8px rgba(29,78,216,0.25) !important;
}

div[data-testid="stChatMessage"][data-role="user"] [data-testid="stChatMessageContent"] *,
div[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) [data-testid="stChatMessageContent"] *,
div[data-testid="stChatMessage"]:has([data-testid="user-avatar"]) [data-testid="stChatMessageContent"] * {
    color: #FFFFFF !important;
}

/* Avatar user — cam, bên phải */
div[data-testid="stChatMessage"][data-role="user"] [data-testid="chatAvatarIcon-user"],
div[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) [data-testid="chatAvatarIcon-user"],
div[data-testid="stChatMessage"]:has([data-testid="user-avatar"]) [data-testid="user-avatar"] {
    background-color: #F97316 !important;
    border-radius: 50% !important;
    flex-shrink: 0 !important;
    margin-left: 0 !important;
    margin-right: 0 !important;
}

/* ══ ASSISTANT bubble — trái, tím ══ */
div[data-testid="stChatMessage"][data-role="assistant"],
div[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]),
div[data-testid="stChatMessage"]:has([data-testid="assistant-avatar"]) {
    flex-direction: row !important;
    justify-content: flex-start !important;
}

div[data-testid="stChatMessage"][data-role="assistant"] [data-testid="stChatMessageContent"],
div[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) [data-testid="stChatMessageContent"],
div[data-testid="stChatMessage"]:has([data-testid="assistant-avatar"]) [data-testid="stChatMessageContent"] {
    background: linear-gradient(135deg, #7C3AED, #8B5CF6) !important;
    color: #FFFFFF !important;
    border-radius: 18px 18px 18px 0 !important;
    padding: 10px 14px !important;
    max-width: 88% !important;
    width: fit-content !important;
    flex: 0 1 auto !important;
    box-shadow: 0 2px 8px rgba(124,58,237,0.2) !important;
}

div[data-testid="stChatMessage"][data-role="assistant"] [data-testid="stChatMessageContent"] *,
div[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) [data-testid="stChatMessageContent"] *,
div[data-testid="stChatMessage"]:has([data-testid="assistant-avatar"]) [data-testid="stChatMessageContent"] * {
    color: #FFFFFF !important;
}

/* Avatar assistant — xanh lá, bên trái */
div[data-testid="stChatMessage"][data-role="assistant"] [data-testid="chatAvatarIcon-assistant"],
div[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) [data-testid="chatAvatarIcon-assistant"],
div[data-testid="stChatMessage"]:has([data-testid="assistant-avatar"]) [data-testid="assistant-avatar"] {
    background-color: #22C55E !important;
    border-radius: 50% !important;
    flex-shrink: 0 !important;
}

/* Text area */
div[data-testid="stTextArea"] textarea {
    border-radius: 10px !important;
    border: 1px solid #CBD5E1 !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 0.95rem !important;
}
div[data-testid="stTextArea"] textarea:focus {
    border-color: #1D4ED8 !important;
    box-shadow: 0 0 0 2px rgba(29, 78, 216, 0.2) !important;
}

/* Hide markers */
div[data-testid="stMarkdownContainer"]:has(span[id$="-marker"]) { display: none !important; }
div[data-testid="stElementContainer"]:has(span[id$="-marker"]) { display: none !important; margin: 0 !important; padding: 0 !important; height: 0 !important; }

/* Specific Action Buttons in Popup using adjacent sibling combinators */
div[data-testid="stElementContainer"]:has(span#btn-approve-marker) + div[data-testid="stElementContainer"] button {
    background-color: #16A34A !important;
    color: #FFFFFF !important;
    font-weight: 700 !important;
    border-radius: 8px !important;
    border: none !important;
    transition: all 0.2s ease !important;
}
div[data-testid="stElementContainer"]:has(span#btn-approve-marker) + div[data-testid="stElementContainer"] button:hover {
    background-color: #15803D !important;
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(22, 163, 74, 0.3) !important;
}

div[data-testid="stElementContainer"]:has(span#btn-reject-marker) + div[data-testid="stElementContainer"] button {
    background-color: #EF4444 !important;
    color: #FFFFFF !important;
    font-weight: 700 !important;
    border-radius: 8px !important;
    border: none !important;
    transition: all 0.2s ease !important;
}
div[data-testid="stElementContainer"]:has(span#btn-reject-marker) + div[data-testid="stElementContainer"] button:hover {
    background-color: #DC2626 !important;
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(239, 68, 68, 0.3) !important;
}

div[data-testid="stElementContainer"]:has(span#btn-reset-marker) + div[data-testid="stElementContainer"] button {
    background-color: #F8FAFC !important;
    color: #475569 !important;
    font-weight: 600 !important;
    border-radius: 8px !important;
    border: 1px solid #CBD5E1 !important;
    transition: all 0.2s ease !important;
}
div[data-testid="stElementContainer"]:has(span#btn-reset-marker) + div[data-testid="stElementContainer"] button:hover {
    background-color: #F1F5F9 !important;
    color: #0F172A !important;
    border-color: #94A3B8 !important;
}

div[data-testid="stElementContainer"]:has(span#btn-generate-marker) + div[data-testid="stElementContainer"] button {
    background: linear-gradient(135deg, #1D4ED8 0%, #3B82F6 100%) !important;
    color: #FFFFFF !important;
    font-weight: 700 !important;
    border-radius: 8px !important;
    border: none !important;
}
div[data-testid="stElementContainer"]:has(span#btn-generate-marker) + div[data-testid="stElementContainer"] button:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 16px rgba(29, 78, 216, 0.4) !important;
}

/* Chat user/assistant messages text */
div[data-testid="stChatMessageContent"] {
    color: #0F172A !important;
    font-size: 0.95rem !important;
}
</style>
"""


def render_kpi_card(
    label: str,
    value: str,
    icon: str = "🏢",
    icon_bg: str = "#EFF6FF",
    icon_color: str = "#1D4ED8",
) -> str:
    """Tạo HTML cho 1 D2 KPI card chỉ hiển thị tiêu đề và giá trị cốt lõi."""
    return f"""
    <div class="kpi-card">
        <div class="kpi-header">
            <div class="kpi-icon-box" style="background: {icon_bg}; color: {icon_color};">
                {icon}
            </div>
            <div>
                <div class="kpi-label">{label}</div>
                <div class="kpi-value">{value}</div>
            </div>
        </div>
    </div>
    """


def render_insight(text: str) -> str:
    """Tạo HTML cho 1 dòng insight text dưới biểu đồ."""
    return f'<div class="insight-text">💡 {text}</div>'


# Streamlit integration for the multipage D2 app.
# Native widgets use .streamlit/config.toml; CSS supplies the executive styling.
DASHBOARD_CSS = """
<style>
.block-container, div[data-testid="stAppViewBlockContainer"] {
    padding-top: 2.5rem !important;
    padding-bottom: 3rem !important;
    max-width: 1600px;
}
[data-testid="stMain"] h1, [data-testid="stMain"] h2,
[data-testid="stMain"] h3 { color: #0F172A; letter-spacing: -0.025em; }
[data-testid="stMain"] h2 { font-size: 1.35rem; }
.d2-header { border-top: 3px solid #F59E0B; gap: 16px; }
.d2-header h1 { color: #FFFFFF !important; }
.d2-header .d2-page-label {
    color: #FBBF24; font-size: .75rem; font-weight: 700;
    letter-spacing: .08em; text-transform: uppercase; text-align: right;
}
[data-testid="stSidebarNav"] a { border-radius: 8px; margin: 3px 8px; }
[data-testid="stSidebarNav"] a[aria-current="page"] {
    background: #EFF6FF; border-left: 3px solid #1D4ED8;
}
[data-testid="stSidebar"] [data-testid="stForm"] {
    background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 12px;
}
[data-testid="stMetric"], [data-testid="stPlotlyChart"],
[data-testid="stVerticalBlockBorderWrapper"] > div {
    background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 12px;
    box-shadow: 0 4px 12px rgba(15,23,42,.03);
}
[data-testid="stMetric"] { padding: 14px 16px; }
[data-testid="stMetricLabel"] { color: #64748B; font-weight: 600; }
[data-testid="stMetricValue"] { color: #0F172A; font-weight: 800; }
[data-testid="stPlotlyChart"] { padding: 12px; overflow: hidden; }
[data-testid="stDataFrame"] { border: 1px solid #E2E8F0; border-radius: 12px; overflow: hidden; }
[data-testid="stButton"] button, [data-testid="stFormSubmitButton"] button {
    border-radius: 8px; font-weight: 600; min-height: 40px;
}
button[kind="primary"], [data-testid="stSidebar"] button[kind="primary"] * {
    background-color: #1D4ED8; color: #FFFFFF !important;
}
button[kind="primary"]:hover { background-color: #2563EB; border-color: #2563EB; }
button:focus-visible, a:focus-visible { outline: 3px solid #F59E0B !important; outline-offset: 3px; }
[data-testid="stPageLink"] a {
    background: #FFFFFF; border: 1px solid #E2E8F0;
    border-radius: 12px; padding: 14px 18px; margin-bottom: 8px;
    font-weight: 600; color: #1D4ED8;
}
[data-testid="stPageLink"] a:hover { border-color: #1D4ED8; background: #EFF6FF; }
@media (max-width: 640px) {
    .d2-header { padding: 18px; align-items: flex-start; flex-direction: column; }
    .d2-header .d2-page-label { text-align: left; }
    .d2-title { font-size: 1.05rem !important; }
    .block-container { padding-left: 1rem; padding-right: 1rem; }
}
</style>
"""


def initialize_theme(title: str):
    """Apply the supplied palette, chart defaults and D2 banner to every page."""
    from html import escape
    import plotly.express as px
    import plotly.io as pio
    import streamlit as st

    pio.templates["d2_executive"] = go.layout.Template(
        layout={**get_layout_template(), "colorway": COLOR_SEQUENCE,
                "colorscale": {"sequential": CONTINUOUS_SCALE, "diverging": DIVERGING_SCALE}}
    )
    px.defaults.template = "d2_executive"
    px.defaults.color_discrete_sequence = COLOR_SEQUENCE
    px.defaults.color_continuous_scale = CONTINUOUS_SCALE
    st.markdown(KPI_CARD_CSS + DASHBOARD_CSS, unsafe_allow_html=True)
    st.markdown(
        '<div class="d2-header"><div class="d2-brand">'
        '<div class="d2-logo" aria-hidden="true">D2</div><div>'
        f'<h1 class="d2-title">{escape(title)}</h1>'
        '<p class="d2-subtitle">Logistics Decision Twin · LINE_A</p></div></div>'
        '<span class="d2-page-label">Forecast · Simulate · Decide</span></div>',
        unsafe_allow_html=True,
    )


def plotly_chart(fig: go.Figure):
    """Keep the reference chart style instead of Streamlit's default override."""
    import streamlit as st
    apply_theme(fig, fig.layout.title.text or "")
    st.plotly_chart(fig, use_container_width=True, theme=None)
