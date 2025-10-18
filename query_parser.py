# query_parser.py
from __future__ import annotations
from typing import Dict, Any, Optional, Tuple, List
import re
from lark import Lark, Transformer, Token

GRAMMAR = r"""
?start: query
?query: (range | item)+

?range: article_range | page_range
article_range: "제"? INT "조" ("의" INT)? ("~" "제"? INT "조" ("의" INT)?)?
page_range: ("p."| "페이지") INT ("-" INT)?

?item: article | clause | table | annex | appendix | cohort | program | date | keyword
article: "제"? INT "조" ("의" INT)?
clause: INT "항" (("및" | "·" | "," ) INT "항")*
table: /(표|table)/i
annex: /(부칙)/i
appendix: /(별표|별지)/i
cohort: /(20\d{2})\s*학?번?/
program: /(IME|석사|박사|학부|대학원|MS|PHD|UG)/i
date: /(시행일|기준일|effective|since|after|이후|부터)\s*(\d{4}-\d{2}-\d{2})/i
keyword: /[^\s]+/  -> kw

%import common.INT
%import common.WS
%ignore WS
"""

PROG_MAP = {
    "IME": "IME_MS", "MS": "MS", "석사": "MS",
    "박사": "PHD", "PHD": "PHD", "학부": "UG", "대학원": "GRAD"
}

class QTransform(Transformer):
    def __init__(self):
        self.meta = {}       # articleNumber, clauseNumber(s), page(s), program, cohort, ...
        self.hints = {}      # wants_table, wants_annex, wants_appendix, refDate, ranges, ...
        self.keywords: List[str] = []

    def article(self, items):
        # 제15조, 제15조의2
        nums = [int(t) for t in items if isinstance(t, Token) and t.type=="INT"]
        base = nums[0]; sub = nums[1] if len(nums) > 1 else None
        self.meta["articleNumber"] = base
        if sub is not None:
            self.meta["articleSub"] = sub
        return None

    def clause(self, items):
        # 2항, 2항 및 3항
        ints = [int(t) for t in items if isinstance(t, Token) and t.type=="INT"]
        # 주요 항 하나와 부가 항목들
        self.meta["clauseNumbers"] = list(sorted(set(ints)))
        if ints:
            self.meta["clauseNumber"] = ints[0]
        return None

    def article_range(self, items):
        # 제15조 ~ 제17조, 제15조의2 ~ 제17조의1
        ints = [int(t) for t in items if isinstance(t, Token) and t.type=="INT"]
        if len(ints) >= 2:
            self.hints.setdefault("articleRanges", []).append((ints[0], ints[-1]))
        else:
            # 단일만 있어도 range 컨테이너에 적재(후처리 통일)
            self.hints.setdefault("articleRanges", []).append((ints[0], ints[0]))
        return None

    def page_range(self, items):
        ints = [int(t) for t in items if isinstance(t, Token) and t.type=="INT"]
        if len(ints) == 1:
            self.meta["page"] = ints[0]
        elif len(ints) >= 2:
            self.hints.setdefault("pageRanges", []).append((ints[0], ints[1]))
        return None

    def table(self, _): self.hints["wants_table"] = True
    def annex(self, _): self.hints["wants_annex"] = True
    def appendix(self, _): self.hints["wants_appendix"] = True

    def cohort(self, items):
        # 2023학번
        m = re.search(r"(20\d{2})", str(items[0]))
        if m: self.meta["cohort"] = f"Cohort_{m.group(1)}"

    def program(self, items):
        s = str(items[0]).upper()
        for k,v in PROG_MAP.items():
            if k in s or s==k:
                self.meta["program"] = v; break

    def date(self, items):
        s = str(items[0])
        m = re.search(r"(\d{4}-\d{2}-\d{2})", s)
        if m: self.hints["refDate"] = m.group(1)

    def kw(self, items):
        self.keywords.append(str(items[0]))

    def query(self, _):
        # 최종 후처리: clauseNumbers 단수화
        if "clauseNumbers" in self.meta and "clauseNumber" not in self.meta:
            self.meta["clauseNumber"] = self.meta["clauseNumbers"][0]
        self.hints["keywords"] = self.keywords
        return {"meta": self.meta, "hints": self.hints}

_parser = Lark(GRAMMAR, parser="lalr")

def parse_query(text: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    tree = _parser.parse(text or "")
    tx = QTransform()
    res = tx.transform(tree)          # <- 매 호출마다 새 Transformer
    return res["meta"], res["hints"]
