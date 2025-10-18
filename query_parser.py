# query_parser.py
from __future__ import annotations
from typing import Dict, Any, Tuple, List
import re

from lark import Lark, Transformer, v_args

# --------------------------------------------------------------------
# Grammar
# - Earley + explicit RANGE separator to avoid reduce/reduce conflicts
# - Keep tokens simple; push specifics to transformer where needed
# --------------------------------------------------------------------
GRAMMAR = r"""
?start: query
?query: piece+

?piece: article_range
      | page_range
      | article
      | clause
      | table
      | annex
      | appendix
      | cohort
      | program
      | date
      | WORD      -> kw

# ----- Ranges (explicit separator required) -----
article_range: ART RANGE ART                     -> article_range
page_range   : (P|PAGE) INT (RANGE INT)?         -> page_range

# ----- Singles -----
article : ART                                    -> article
clause  : INT "항" (("및" | "·" | ",") INT "항")*  -> clause
table   : /(표|table)/i                          -> table
annex   : /(부칙)/i                              -> annex
appendix: /(별표|별지)/i                          -> appendix
cohort  : /(20\d{2})\s*학?번?\b|\b\d{2}\s*학?번?\b/i -> cohort
program : /(IME|석사|박사|학부|대학원|MS|PHD|UG)/i -> program
date    : /(시행일|기준일|effective|since|after|이후|부터)\s*(\d{4}-\d{2}-\d{2})/i -> date

# ----- Tokens -----
RANGE: /(~|–|-)+/
ART  : /제?\s*\d{1,3}\s*조(?:\s*의\s*\d{1,2})?/
P    : /p\./i
PAGE : /페이지/i
WORD : /[^\s]+/

%import common.INT
%import common.WS
%ignore WS
"""

# 표준 프로그램 코드 매핑 (대문자/언더스코어 정규형)
PROG_MAP = {
    "IME": "IME_MS",
    "MS": "MS",
    "석사": "MS",
    "박사": "PHD",
    "PHD": "PHD",
    "학부": "UG",
    "UG": "UG",
    "대학원": "GRAD",
}


@v_args(inline=True)
class QTransform(Transformer):
    """
    Transformer that builds two dicts:
      - meta: articleNumber, clauseNumber, page, program, cohort, contentType(=table) ...
      - hints: wants_table/annex/appendix, refDate, articleRanges, pageRanges, keywords ...
    """
    def __init__(self):
        self.meta: Dict[str, Any] = {}
        self.hints: Dict[str, Any] = {}
        self.keywords: List[str] = []

    # -------- helpers --------
    def _parse_art(self, text: str):
        # e.g., "제15조", "제15조의2", "15조", "제 7 조 의 3"
        m = re.search(r"\d{1,3}", text)
        if m:
            self.meta["articleNumber"] = int(m.group(0))
        m2 = re.search(r"의\s*(\d{1,2})", text)
        if m2:
            # "제15조의2" → clause-like subindex
            self.meta["clauseNumber"] = int(m2.group(1))

    # -------- nodes --------
    def article(self, tok):
        self._parse_art(str(tok))
        return None

    def clause(self, *items):
        # "2항", "2항 및 3항"
        ints = [int(x) for x in items if hasattr(x, "type") and x.type == "INT"]
        if ints:
            self.meta["clauseNumbers"] = sorted(set(ints))
            # 대표 항 하나를 clauseNumber로
            self.meta.setdefault("clauseNumber", ints[0])
        return None

    def article_range(self, a1, _sep, a2):
        # "제15조 ~ 제17조", "제15조의2 - 제17조의1"
        def _to_num(s: str) -> int:
            m = re.search(r"\d{1,3}", s)
            return int(m.group(0)) if m else None
        left = _to_num(str(a1))
        right = _to_num(str(a2))
        if left is not None and right is not None:
            self.hints.setdefault("articleRanges", []).append((left, right))
            # 검색 필터의 기본 anchor로 left를 채워주면 recall이 좋아짐
            self.meta.setdefault("articleNumber", left)
        return None

    def page_range(self, ptoken, first, maybe_range_int=None):
        # "p. 12", "페이지 3 - 5"
        a = int(first)
        if maybe_range_int is None:
            self.meta["page"] = a
        else:
            # maybe_range_int는 ("---", INT) 형태로 들어옴 → 마지막 토큰이 INT
            if hasattr(maybe_range_int, "type") and maybe_range_int.type == "INT":
                b = int(maybe_range_int)
            else:
                # Earley 구성상 tuple처럼 들어오는 경우 방어
                s = str(maybe_range_int)
                m = re.search(r"\d+", s)
                b = int(m.group(0)) if m else a
            self.hints.setdefault("pageRanges", []).append((a, b))
        return None

    def table(self, *_):
        self.meta["contentType"] = "table"
        self.hints["wants_table"] = True
        return None

    def annex(self, *_):
        self.hints["wants_annex"] = True
        return None

    def appendix(self, *_):
        self.hints["wants_appendix"] = True
        return None

    def cohort(self, tok):
        s = str(tok)
        # 2023학번 / 23학번
        m4 = re.search(r"(20\d{2})", s)
        m2 = re.search(r"\b(\d{2})\b", s) if not m4 else None
        year = None
        if m4:
            year = m4.group(1)
        elif m2:
            year = f"20{int(m2.group(1)):02d}"
        if year:
            self.meta["cohort"] = f"Cohort_{year}"
        return None

    def program(self, tok):
        s = str(tok).upper()
        for k, v in PROG_MAP.items():
            if k in s or s == k:
                self.meta["program"] = v
                break
        return None

    def date(self, tok):
        s = str(tok)
        m = re.search(r"(\d{4}-\d{2}-\d{2})", s)
        if m:
            self.hints["refDate"] = m.group(1)
        return None

    def kw(self, tok):
        self.keywords.append(str(tok))
        return None

    def query(self, _):
        # 후처리: clauseNumbers만 있고 대표가 없으면 하나 세워주기
        if "clauseNumbers" in self.meta and "clauseNumber" not in self.meta:
            self.meta["clauseNumber"] = self.meta["clauseNumbers"][0]
        self.hints["keywords"] = self.keywords
        return {"meta": self.meta, "hints": self.hints}


# Earley는 모호성에 강함. dynamic_complete로 토큰화-파싱 유연성↑
_parser = Lark(GRAMMAR, parser="earley", lexer="dynamic_complete")


def parse_query(text: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Robust parser with safe fallback to regex-based query_router().
    Always returns (meta, hints) dicts.
    """
    try:
        tree = _parser.parse(text or "")
        tx = QTransform()
        res = tx.transform(tree)
        return res["meta"], res["hints"]
    except Exception:
        # 안전 폴백: 정규식 라우터
        from query_router import query_router
        return query_router(text)
