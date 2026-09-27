import re
from pathlib import Path


def clean_title(filename: str | None) -> str:
    """'UoL,-,Your,University,2025,(Undergraduate,A5),Online.pdf'
    -> 'UoL - Your University 2025 (Undergraduate A5) Online'"""
    stem = Path(filename or "untitled").stem
    t = re.sub(r"[,_]+", " ", stem)           # commas/underscores used as spaces
    t = re.sub(r"\s*-\s*", " - ", t)
    t = re.sub(r"\s+", " ", t).strip(" -")
    return t or "Untitled"
