import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.Home import bootstrap, render_recommendation

result, config = bootstrap("Recommendation")
render_recommendation(result, config)
