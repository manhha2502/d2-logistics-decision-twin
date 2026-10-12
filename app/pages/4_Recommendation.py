import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.Home import bootstrap, render_recommendation

result, config = bootstrap("Đề xuất hành động")
render_recommendation(result, config)
